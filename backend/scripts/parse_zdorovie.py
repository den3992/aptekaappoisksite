"""
Парсер цен «Здоровье» (s-zdorovie.ru) → коллекция prices_real, source="zdorovie".

«Здоровье» — краснодарская аптечная сеть (26 аптек в Краснодаре + Ставрополь/
Ростов/Адыгея). Из наших городов используем ТОЛЬКО **Краснодар (krd)** — это
2-й источник цен для Краснодара (1-й — Максавит).

Город по умолчанию на сайте = Краснодар (<option value="first">Краснодар</option>),
цена единая (от cookie города не зависит) → берём дефолтные цены, city="krd".

⚠️ У сайта НЕТ товарного HTTP-поиска (Bitrix-поиск не индексирует товары,
live-search POST / возвращает пусто). Поэтому модель ИНВЕРТИРОВАНА относительно
Аптечества: сначала КРАУЛИМ весь каталог (разделы по пагинации ?PAGEN_1=N,
60 товаров/стр, Bitrix catalog.section), строим индекс по названию, и уже его
матчим с нашим каталогом medications (а не ищем каждый препарат по сети).

Карточка листинга (UTF-8):
    product-item-container ...
      <a class="entry__image" href="/catalog/<root>/<slug>/" title="<НАЗВАНИЕ ...>" data-entity="image-wrapper">
      ... <span class="product-item-price-current">NNN ₽</span>
Slug стабилен и содержит фасовку (krestor_tab__p_plen__obol__20mg__28 → 28 шт).

Матчинг переиспользуется из parse_gorzdrav (match_product[s] / extract_pack).
КЛЮЧЕВОЕ ОГРАНИЧЕНИЕ: сохраняем ТОЛЬКО позиции, уже существующие в medications.

ЭТАП 1 (этот файл): матчинг + цена. Карта наличия по аптекам НЕ реализуется
(seed-аптека без координат, маркеров нет).

Запуск:
    python -m scripts.parse_zdorovie                  # весь канонический каталог, krd
    python -m scripts.parse_zdorovie --limit 100
    python -m scripts.parse_zdorovie --slug nurofen-...
    python -m scripts.parse_zdorovie --popular
    python -m scripts.parse_zdorovie --from-maksavit  # только слаги с ценой Максавита в krd
    python -m scripts.parse_zdorovie --update-only    # только препараты с матчем Здоровья
    python -m scripts.parse_zdorovie --rematch
"""
from __future__ import annotations

import os
import re
import sys
import html
import asyncio
import argparse
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from motor.motor_asyncio import AsyncIOMotorClient

from scripts.parse_gorzdrav import (
    MONGO_URL, DB_NAME, POPULAR_MNN,
    REQUEST_DELAY,
    match_product, match_products, extract_pack,
    log,
)

SOURCE = "zdorovie"
CITY = "krd"
BASE = "https://s-zdorovie.ru"

# Разделы каталога с препаратами/витаминами/БАДами (наш каталог — это они).
SECTIONS = ["lekarstvennye-sredstva", "vitaminy", "bady"]
MAX_PAGES = 250          # предохранитель на раздел
CRAWL_DELAY = 0.6        # пауза между страницами каталога

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html, */*",
    "Accept-Encoding": "gzip",
}

CHANGED_SLUGS: set[str] = set()

# --- Парсинг листинга ---
_CARD_HREF_RE = re.compile(
    r'href="(/catalog/[a-z0-9_/-]+?/)"\s+title="([^"]+)"\s+data-entity="image-wrapper"'
)
_PRICE_RE = re.compile(r'([\d\s ]+?)\s*₽')

_SLUG_PACK_RE = re.compile(r'_(\d+)(?:_(sht|ml|g|mg|mcg|l|amp|dose|pak|tab|kaps|vanil|fl))?/?$')
_SLUG_UNIT = {"sht": "шт", "ml": "мл", "g": "г", "l": "л", "amp": "шт",
              "tab": "шт", "kaps": "шт", "pak": "шт", "dose": "шт",
              "vanil": "шт", "fl": "шт", None: "шт"}


def zdr_extract_pack(title: str, slug: str) -> str | None:
    """Фасовка из title (предпочтительно) или из хвоста slug."""
    p = extract_pack(title or "")
    if p:
        return p
    m = _SLUG_PACK_RE.search(slug or "")
    if m:
        unit = _SLUG_UNIT.get(m.group(2), "шт")
        return f"{int(m.group(1))} {unit}"
    return None


def _parse_price(block: str) -> int | None:
    m = _PRICE_RE.search(block)
    if not m:
        return None
    digits = re.sub(r"[\s ]", "", m.group(1))
    if not digits.isdigit():
        return None
    val = int(digits)
    return val if val > 0 else None


def parse_listing(text: str) -> list[dict]:
    """HTML листинга catalog.section → список товаров {name, extId=slug, url_key, _price}."""
    out: list[dict] = []
    parts = text.split("product-item-container")
    for seg in parts[1:]:
        block = seg[:4000]
        hm = _CARD_HREF_RE.search(block)
        if not hm:
            continue
        url = hm.group(1)
        slug = url.rstrip("/").split("/")[-1]
        if not slug:
            continue
        title = html.unescape(hm.group(2)).strip()
        title = re.sub(r"\s+", " ", title)
        if not title:
            continue
        price = _parse_price(block)
        out.append({
            "name": title,
            "extId": slug,
            "url_key": url,
            "_price": price,
            "attributes": [],
        })
    return out


async def _get(client: httpx.AsyncClient, url: str) -> str | None:
    for attempt in range(3):
        try:
            r = await client.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(1 + attempt * 2)
                continue
            log.warning(f"[zdorovie] GET fail {url}: {e}")
            return None
    return None


async def crawl_catalog(client: httpx.AsyncClient) -> list[dict]:
    """Обойти разделы по пагинации, собрать все товары (дедуп по slug)."""
    by_slug: dict[str, dict] = {}
    for section in SECTIONS:
        log.info(f"[zdorovie] crawl раздел /{section}/ ...")
        empty_streak = 0
        for pg in range(1, MAX_PAGES + 1):
            url = f"{BASE}/catalog/{section}/?PAGEN_1={pg}"
            text = await _get(client, url)
            if text is None:
                break
            cards = parse_listing(text)
            new = 0
            for it in cards:
                if it["extId"] not in by_slug:
                    by_slug[it["extId"]] = it
                    new += 1
            if not cards:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0
            if pg % 20 == 0:
                log.info(f"[zdorovie]   {section} стр {pg}: всего собрано {len(by_slug)}")
            await asyncio.sleep(CRAWL_DELAY)
        log.info(f"[zdorovie] раздел /{section}/ готов, итого товаров: {len(by_slug)}")
    items = list(by_slug.values())
    with_price = sum(1 for it in items if it["_price"])
    log.info(f"[zdorovie] КАТАЛОГ собран: {len(items)} товаров ({with_price} с ценой)")
    return items


# --- Индекс каталога по словам названия для быстрого подбора кандидатов ---
_STOP = {"таблетки", "капсулы", "раствор", "мазь", "крем", "гель", "сироп",
         "порошок", "суспензия", "свечи", "спрей", "капли", "для", "покрытые",
         "оболочкой", "пленочной", "приготовления", "наружного", "применения",
         "внутривенного", "внутримышечного", "введения", "флакон", "ампулы"}
_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.I)


def _key_words(name: str) -> list[str]:
    words = [w.lower() for w in _WORD_RE.findall(name or "")]
    return [w for w in words if len(w) >= 4 and w not in _STOP and not w.isdigit()]


def build_index(items: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for it in items:
        for w in _key_words(it["name"])[:3]:   # первые 3 значащих слова (бренд/действ.в-во)
            idx.setdefault(w, []).append(it)
    return idx


def lookup_candidates(index: dict[str, list[dict]], med: dict) -> list[dict]:
    """Кандидаты = товары каталога, делящие значащее слово с названием ИЛИ МНН препарата."""
    cand: dict[str, dict] = {}
    words = _key_words(med.get("name", ""))[:3] + _key_words(med.get("mnn", ""))[:2]
    for w in words:
        for it in index.get(w, []):
            cand[it["extId"]] = it
    return list(cand.values())


async def process_medication(db, med: dict, index: dict, rematch: bool,
                             matched_ext_ids: set) -> None:
    med_id = med["_id"]
    slug = med.get("slug", str(med_id))

    existing = await db.prices_real.find_one(
        {"medication_id": med_id, "source": SOURCE, "city": CITY}
    )
    if existing and not rematch:
        return

    candidates = lookup_candidates(index, med)

    matched_item, status = match_product(med, candidates)

    if not candidates:
        await db.prices_real.update_one(
            {"medication_id": med_id, "source": SOURCE, "city": CITY},
            {"$set": {
                "medication_id": med_id, "slug": slug, "source": SOURCE, "city": CITY,
                "match_status": "not_found",
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return

    if matched_item is None:
        top_name = candidates[0].get("name", "") if candidates else ""
        await db.prices_real.update_one(
            {"medication_id": med_id, "source": SOURCE, "city": CITY},
            {"$set": {
                "medication_id": med_id, "slug": slug, "source": SOURCE, "city": CITY,
                "match_status": "no_match",
                "gz_top_candidate": top_name,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return

    all_matches = match_products(med, candidates, allow_combo=False)
    if not all_matches:
        all_matches = [(matched_item, status)]

    seen_packs: set[str] = set()
    saved = 0
    for item, item_status in all_matches:
        gz_name = item.get("name", "")
        ext_id = item.get("extId", "")
        gz_pack = zdr_extract_pack(gz_name, ext_id)
        if not gz_pack or gz_pack in seen_packs:
            continue
        price = item.get("_price")
        if price is None:
            continue
        seen_packs.add(gz_pack)
        price = int(price)

        log.info(f"  [krd/{item_status:12s}] pack={gz_pack:<10} | {price} руб | {gz_name[:50]}")

        _prev = await db.prices_real.find_one(
            {"medication_id": med_id, "source": SOURCE, "city": CITY, "gz_pack": gz_pack},
            {"_id": 0, "price": 1},
        )
        if _prev is None or _prev.get("price") != price:
            CHANGED_SLUGS.add(slug)

        await db.prices_real.update_one(
            {"medication_id": med_id, "source": SOURCE, "city": CITY, "gz_pack": gz_pack},
            {"$set": {
                "medication_id": med_id,
                "slug": slug,
                "source": SOURCE,
                "city": CITY,
                "gz_pack": gz_pack,
                "match_status": item_status,
                "gz_ext_id": ext_id,
                "gz_name": gz_name,
                "gz_url_key": item.get("url_key", ""),
                "price": price,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        matched_ext_ids.add(ext_id)
        saved += 1

    if saved > 0 and seen_packs:
        await db.prices_real.delete_many({
            "medication_id": med_id, "source": SOURCE, "city": CITY,
            "gz_pack": {"$nin": list(seen_packs), "$ne": None},
        })

    if saved:
        log.info(f"[krd/{slug[:40]:<40}] saved {saved} packs")


async def main(args: argparse.Namespace) -> None:
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        catalog = await crawl_catalog(client)

    index = build_index(catalog)
    log.info(f"[zdorovie] индекс: {len(index)} ключевых слов")

    query: dict = {"is_canonical": True}
    if args.slug:
        query["slug"] = args.slug
    if args.popular:
        query["mnn"] = {"$in": list(POPULAR_MNN)}
    if args.from_maksavit:
        mk_slugs = await db.prices_real.distinct(
            "slug",
            {"source": "maksavit", "city": CITY,
             "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
             "price": {"$ne": None}},
        )
        query["slug"] = {"$in": mk_slugs}
        log.info(f"[krd] --from-maksavit: {len(mk_slugs)} слагов с ценой Максавита")
    if args.update_only:
        matched_slugs = await db.prices_real.distinct(
            "slug",
            {"source": SOURCE, "city": CITY,
             "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
             "price": {"$ne": None}},
        )
        query["slug"] = {"$in": matched_slugs}

    cursor = db.medications.find(query, {
        "name": 1, "dosage": 1, "form": 1, "manufacturer": 1, "slug": 1, "mnn": 1,
    })
    if args.limit:
        cursor = cursor.limit(args.limit)
    meds = await cursor.to_list(length=None)
    log.info(f"[krd] Препаратов для обработки: {len(meds)}")

    rematch = args.rematch or args.update_only
    matched_ext_ids: set[str] = set()
    for i, med in enumerate(meds, 1):
        await process_medication(db, med, index, rematch, matched_ext_ids)
        if i % 500 == 0:
            log.info(f"[krd] Прогресс: {i}/{len(meds)}")

    stats = {}
    async for doc in db.prices_real.aggregate([
        {"$match": {"source": SOURCE}},
        {"$group": {"_id": "$match_status", "count": {"$sum": 1}}},
    ]):
        stats[doc["_id"]] = doc["count"]
    log.info(f"[zdorovie] Готово. Статистика: {stats}")

    out_path = os.environ.get("INDEXNOW_CHANGED_FILE_ZDOROVIE", "/tmp/indexnow_changed_zdorovie.txt")
    try:
        with open(out_path, "w") as f:
            for sl in sorted(CHANGED_SLUGS):
                f.write(sl + "\n")
        log.info(f"[zdorovie] IndexNow: {len(CHANGED_SLUGS)} изменённых slug-ов -> {out_path}")
    except Exception as e:
        log.warning(f"[zdorovie] IndexNow: не смог записать {out_path}: {e}")
    client_db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--slug", type=str, default="")
    parser.add_argument("--popular", action="store_true")
    parser.add_argument("--from-maksavit", action="store_true",
                        help="Только препараты с уже существующей ценой Максавита в Краснодаре.")
    parser.add_argument("--update-only", action="store_true",
                        help="Обновить только препараты с уже существующим матчем Здоровья.")
    parser.add_argument("--rematch", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args))
