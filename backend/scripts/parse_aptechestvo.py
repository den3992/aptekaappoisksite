"""
Парсер цен «Аптечество» (aptechestvo.ru) → коллекция prices_real, source="aptechestvo".

Аптечество — сеть группы Протек/Ригла (email аптек @rigla.ru). Обслуживает
несколько регионов; из наших городов — **Нижний Новгород, Москва, Санкт-Петербург**
(Краснодар НЕ обслуживает).

Регион переключается ПОДДОМЕНОМ (не cookie):
    nn  → https://aptechestvo.ru          (дефолт)
    msk → https://moscow.aptechestvo.ru
    spb → https://spb.aptechestvo.ru
Цены регион-специфичны (проверено: Нурофен Экспресс 40шт НН 726 / Москва 670 / СПб 722).

Главный сайт под Qrator нам не нужен — товары отдаёт открытый AJAX-автокомплит:
    GET https://<sub>/ajax/new_app/speedSearch.php?q=<имя>
    → HTML-фрагмент, до ~10 товаров, блок `speed-srarch-wrap`:
        <a href="/catalog/<slug>/">          # slug = стабильный ID
        <div class="product-title ..."><a>TITLE</a>   # с фасовкой
        <div class="curent-price">726.00 ...
Без авторизации.

Матчинг переиспользуется из parse_gorzdrav (match_product[s] / extract_pack).
Производитель из автокомплита недоступен → attributes пустые → статусы
"needs_review"/"mnn_match".

КЛЮЧЕВОЕ ОГРАНИЧЕНИЕ: сохраняем ТОЛЬКО позиции, уже существующие в нашем
каталоге medications. Новые SKU не заводим.

ЭТАП 1 (этот файл): матчинг + цена по городу. Карта наличия по аптекам НЕ
реализуется (seed-аптека без координат, маркеров нет).

Запуск:
    python -m scripts.parse_aptechestvo                       # все канонические, города nn,msk,spb
    python -m scripts.parse_aptechestvo --city msk
    python -m scripts.parse_aptechestvo --city nn,spb
    python -m scripts.parse_aptechestvo --limit 100
    python -m scripts.parse_aptechestvo --slug nurofen-...
    python -m scripts.parse_aptechestvo --popular
    python -m scripts.parse_aptechestvo --from-gorzdrav       # только слаги с матчем Горздрава
    python -m scripts.parse_aptechestvo --update-only         # только препараты с матчем Аптечество
    python -m scripts.parse_aptechestvo --rematch
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

# Переиспользуем матчинг и константы Горздрава (импорт read-only).
from scripts.parse_gorzdrav import (
    MONGO_URL, DB_NAME, POPULAR_MNN,
    REQUEST_DELAY, CONCURRENCY,
    match_product, match_products, extract_pack,
    log,
)

SOURCE = "aptechestvo"

# Город → поддомен (регион-специфичные цены). Краснодар Аптечество не обслуживает.
CITY_BASE = {
    "nn": "https://aptechestvo.ru",
    "msk": "https://moscow.aptechestvo.ru",
    "spb": "https://spb.aptechestvo.ru",
}
DEFAULT_CITIES = ["nn", "msk", "spb"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html, */*",
    "X-Requested-With": "XMLHttpRequest",
}

# slug-и с изменившейся ценой Аптечество — для IndexNow (по всем городам).
CHANGED_SLUGS: set[str] = set()

# --- Парсинг HTML-фрагмента speedSearch ---
_ITEM_RE = re.compile(r'speed-srarch-wrap(.*?)(?=speed-srarch-wrap|$)', re.S)
_HREF_RE = re.compile(r'href="(/catalog/[^"?#]+?/)"')
_TITLE_RE = re.compile(r'product-title.*?<a[^>]*>(.*?)</a>', re.S)
_PRICE_RE = re.compile(r'curent-price"\s*>\s*([\d]+(?:[.,]\d+)?)')
_TAG_RE = re.compile(r'<[^>]+>')

_SLUG_PACK_RE = re.compile(r'_(\d+)_(sht|ml|g|mg|mcg|l|amp|dose|pak|tab|kaps)\b')
_SLUG_UNIT = {"sht": "шт", "ml": "мл", "g": "г", "l": "л", "amp": "шт",
              "tab": "шт", "kaps": "шт", "pak": "шт", "dose": "шт"}


def apt_extract_pack(title: str, slug: str) -> str | None:
    """Фасовка из title (предпочтительно) или из хвоста slug."""
    p = extract_pack(title or "")
    if p:
        return p
    m = _SLUG_PACK_RE.search(slug or "")
    if m:
        unit = _SLUG_UNIT.get(m.group(2))
        if unit:
            return f"{int(m.group(1))} {unit}"
    return None


def _parse_search_html(text: str) -> list[dict]:
    """HTML-фрагмент speedSearch → список листингов (name + attributes)."""
    out: list[dict] = []
    seen_slugs: set[str] = set()
    for m in _ITEM_RE.finditer(text):
        block = m.group(1)
        href = _HREF_RE.search(block)
        if not href:
            continue
        url = href.group(1)
        slug = url.strip("/").split("/")[-1]
        if not slug or slug in seen_slugs:
            continue
        tm = _TITLE_RE.search(block)
        if not tm:
            continue
        title = html.unescape(_TAG_RE.sub("", tm.group(1))).strip()
        title = re.sub(r"\s+", " ", title)
        if not title:
            continue
        pm = _PRICE_RE.search(block)
        price = None
        if pm:
            try:
                price = int(float(pm.group(1).replace(",", ".")))
            except ValueError:
                price = None
        seen_slugs.add(slug)
        out.append({
            "name": title,
            "extId": slug,        # стабильный ID Аптечества = slug каталога
            "url_key": url,
            "_price": price,
            "attributes": [],
        })
    return out


async def search_aptechestvo(client: httpx.AsyncClient, query: str, base: str) -> list[dict]:
    """GET <base>/ajax/new_app/speedSearch.php?q=, 3 попытки с backoff."""
    url = f"{base}/ajax/new_app/speedSearch.php"
    for attempt in range(3):
        try:
            r = await client.get(url, params={"q": query},
                                 headers={"Referer": base + "/"}, timeout=25)
            r.raise_for_status()
            return _parse_search_html(r.text)
        except Exception as e:
            if attempt < 2:
                wait = 1 + attempt * 2
                log.warning(f"[aptechestvo] search '{query[:40]}' попытка {attempt + 1}/3: {e} — пауза {wait}с")
                await asyncio.sleep(wait)
                continue
            log.warning(f"[aptechestvo] search error for '{query[:40]}' (после 3 попыток): {e}")
            return []
    return []


async def process_medication(
    client: httpx.AsyncClient,
    db,
    med: dict,
    rematch: bool,
    matched_ext_ids: set,
    city: str,
    base: str,
) -> None:
    med_id = med["_id"]
    slug = med.get("slug", str(med_id))
    name = med.get("name", "")
    dosage = med.get("dosage", "")
    mnn = med.get("mnn", "")

    existing = await db.prices_real.find_one(
        {"medication_id": med_id, "source": SOURCE, "city": city}
    )
    if existing and not rematch:
        log.debug(f"skip (already matched): {slug}")
        return

    # Проход 1: поиск по бренд-названию.
    query = name.strip()
    items = await search_aptechestvo(client, query, base)
    await asyncio.sleep(REQUEST_DELAY)
    items2: list[dict] = []

    matched_item, status = match_product(med, items)
    search_pass = "name"

    # Проход 2: по МНН, если по имени не нашли.
    if matched_item is None and mnn and mnn.lower() not in name.lower():
        mnn_query = f"{mnn.lower()} {dosage}".strip()
        items2 = await search_aptechestvo(client, mnn_query, base)
        await asyncio.sleep(REQUEST_DELAY)
        matched_item, status = match_product(med, items2, allow_combo=False)
        if matched_item:
            search_pass = "mnn"
            if status == "matched":
                status = "mnn_match"

    if not items and (not mnn or mnn.lower() in name.lower()):
        log.info(f"[{city}/not_found]  {slug}")
        await db.prices_real.update_one(
            {"medication_id": med_id, "source": SOURCE, "city": city},
            {"$set": {
                "medication_id": med_id, "slug": slug, "source": SOURCE, "city": city,
                "match_status": "not_found",
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return

    if matched_item is None:
        top_name = items[0].get("name", "") if items else ""
        log.info(f"[{city}/no match]   {slug} | top: {top_name[:60]}")
        await db.prices_real.update_one(
            {"medication_id": med_id, "source": SOURCE, "city": city},
            {"$set": {
                "medication_id": med_id, "slug": slug, "source": SOURCE, "city": city,
                "match_status": "no_match",
                "search_query": query,
                "gz_top_candidate": top_name,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return

    # Все листинги, прошедшие фильтры (для разных упаковок).
    if search_pass == "name":
        all_matches = match_products(med, items, allow_combo=False)
    else:
        all_matches = match_products(med, items2, allow_combo=False)
        all_matches = [(it, "mnn_match" if st == "matched" else st) for (it, st) in all_matches]

    if not all_matches:
        all_matches = [(matched_item, status)]

    seen_packs = set()
    saved = 0
    for item, item_status in all_matches:
        gz_name = item.get("name", "")
        ext_id = item.get("extId", "")
        gz_pack = apt_extract_pack(gz_name, ext_id)
        if not gz_pack:
            log.warning(f"  skip (no pack in name): {gz_name[:60]}")
            continue
        if gz_pack in seen_packs:
            continue
        seen_packs.add(gz_pack)

        price = item.get("_price")
        if price is None:
            continue
        price = int(price)

        log.info(
            f"  [{city}/{item_status:12s}] pack={gz_pack:<10} | {price} руб | {gz_name[:50]}"
        )

        _prev = await db.prices_real.find_one(
            {"medication_id": med_id, "source": SOURCE, "city": city, "gz_pack": gz_pack},
            {"_id": 0, "price": 1},
        )
        if _prev is None or _prev.get("price") != price:
            CHANGED_SLUGS.add(slug)

        await db.prices_real.update_one(
            {"medication_id": med_id, "source": SOURCE, "city": city, "gz_pack": gz_pack},
            {"$set": {
                "medication_id": med_id,
                "slug": slug,
                "source": SOURCE,
                "city": city,
                "gz_pack": gz_pack,
                "match_status": item_status,
                "gz_ext_id": ext_id,
                "gz_name": gz_name,
                "gz_url_key": item.get("url_key", ""),
                "price": price,
                "search_query": query,
                "search_pass": search_pass,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        matched_ext_ids.add(ext_id)
        saved += 1

    if saved > 0 and seen_packs:
        await db.prices_real.delete_many({
            "medication_id": med_id, "source": SOURCE, "city": city,
            "gz_pack": {"$nin": list(seen_packs), "$ne": None},
        })

    log.info(f"[{city}/{slug[:40]:<40}] saved {saved} packs (pass={search_pass})")


async def run_city(client: httpx.AsyncClient, db, city: str, args: argparse.Namespace) -> None:
    base = CITY_BASE[city]
    log.info(f"=== [aptechestvo] city={city} ({base}) ===")

    query: dict = {"is_canonical": True}
    if args.slug:
        query["slug"] = args.slug
    if args.popular:
        query["mnn"] = {"$in": list(POPULAR_MNN)}
    if args.from_gorzdrav:
        gz_slugs = await db.prices_real.distinct(
            "slug",
            {"source": "gorzdrav",
             "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
             "price": {"$ne": None}},
        )
        query["slug"] = {"$in": gz_slugs}
        log.info(f"[{city}] --from-gorzdrav: {len(gz_slugs)} слагов с матчем Горздрава")
    if args.update_only:
        matched_slugs = await db.prices_real.distinct(
            "slug",
            {"source": SOURCE, "city": city,
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
    log.info(f"[{city}] Препаратов для обработки: {len(meds)}")

    rematch = args.rematch or args.update_only
    matched_ext_ids: set[str] = set()
    sem = asyncio.Semaphore(CONCURRENCY)
    done = [0]

    async def worker(med):
        async with sem:
            await process_medication(client, db, med, rematch, matched_ext_ids, city, base)
            done[0] += 1
            if done[0] % 100 == 0:
                log.info(f"[{city}] Прогресс: {done[0]}/{len(meds)}")

    await asyncio.gather(*(worker(m) for m in meds))


async def main(args: argparse.Namespace) -> None:
    cities = [c.strip() for c in args.city.split(",") if c.strip()]
    bad = [c for c in cities if c not in CITY_BASE]
    if bad:
        log.error(f"[aptechestvo] неизвестные города: {bad} (доступно: {list(CITY_BASE)})")
        return

    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    async with httpx.AsyncClient(headers=HEADERS) as client:
        for city in cities:
            await run_city(client, db, city, args)

    stats = {}
    async for doc in db.prices_real.aggregate([
        {"$match": {"source": SOURCE}},
        {"$group": {"_id": {"city": "$city", "st": "$match_status"}, "count": {"$sum": 1}}},
    ]):
        stats[f"{doc['_id'].get('city')}/{doc['_id'].get('st')}"] = doc["count"]
    log.info(f"[aptechestvo] Готово. Статистика: {stats}")

    out_path = os.environ.get("INDEXNOW_CHANGED_FILE_APTECHESTVO", "/tmp/indexnow_changed_aptechestvo.txt")
    try:
        with open(out_path, "w") as f:
            for sl in sorted(CHANGED_SLUGS):
                f.write(sl + "\n")
        log.info(f"[aptechestvo] IndexNow: {len(CHANGED_SLUGS)} изменённых slug-ов -> {out_path}")
    except Exception as e:
        log.warning(f"[aptechestvo] IndexNow: не смог записать {out_path}: {e}")
    client_db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", type=str, default=",".join(DEFAULT_CITIES),
                        help="Города через запятую (nn,msk,spb). По умолчанию все три.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--slug", type=str, default="")
    parser.add_argument("--popular", action="store_true")
    parser.add_argument("--from-gorzdrav", action="store_true",
                        help="Только препараты с уже существующим матчем Горздрава.")
    parser.add_argument("--update-only", action="store_true",
                        help="Обновить только препараты с уже существующим матчем Аптечество (в этом городе).")
    parser.add_argument("--rematch", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args))
