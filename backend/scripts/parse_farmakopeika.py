"""
Парсер цен «Фармакопейка» (farmakopeika.ru) → коллекция prices_real,
source="farmakopeika", city="nsk" (Новосибирск).

«Фармакопейка» — сибирская аптечная сеть. Регион задаётся ПОДДОМЕНОМ
({city}.farmakopeika.ru). Из наших городов используем ТОЛЬКО **Новосибирск
(nsk)** = novosibirsk.farmakopeika.ru → это 2-я сеть цен для nsk (1-я — Магнит),
которая выводит город из «слабых» (1 сеть) в «сильные» (≥2 сети, сравнение цен).

Модель ИНВЕРТИРОВАНА (как «Здоровье», НЕ как «Аптечество»): у сайта нет честного
HTTP-поиска по товарам (Diginetica-autocomplete капризничает), поэтому КРАУЛИМ
весь каталог лекарств/БАД, строим индекс по названию и матчим его с нашим
medications.

Каталог = раздел 2440 «Лекарства и БАД» (Blade-SSR, НЕ Vue: карточки товаров в
серверном HTML). Пагинация ?page=N&limit=48 (48 — макс размер страницы). Карточка:
    <div class="product product--catalog ...">
      <a href="https://novosibirsk.farmakopeika.ru/catalog/<cat>/<prodId>" class="product__link">
      ... <div class="product__name ...">НАЗВАНИЕ С ФАСОВКОЙ</div>
      ... <div class="product__price-value ...">от 1399.00 ₽</div>
ВАЖНО: на поддомене novosibirsk цена в карточке = ПО-НОВОСИБИРСКАЯ (мин «от»).
→ цена берётся прямо из листинга, отдельный заход на товарную стр НЕ нужен.

Матчинг переиспользуется из parse_gorzdrav (match_product[s] / extract_pack).
Сохраняем ТОЛЬКО позиции, уже существующие в medications (is_canonical).

ЭТАП 1 (этот файл): матчинг + цена. Карта наличия по аптекам — опц. потом.

Запуск (внутри backend-контейнера, скрипты ЗАПЕКАЮТСЯ в образ):
    python -m scripts.parse_farmakopeika                 # весь канонический каталог, nsk
    python -m scripts.parse_farmakopeika --limit 100
    python -m scripts.parse_farmakopeika --slug nurofen-...
    python -m scripts.parse_farmakopeika --popular
    python -m scripts.parse_farmakopeika --from-magnit   # только слаги с ценой Магнита в nsk
    python -m scripts.parse_farmakopeika --update-only   # только препараты с матчем Фармакопейки
    python -m scripts.parse_farmakopeika --rematch
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
    MONGO_URL, DB_NAME, POPULAR_MNN, NAME_THRESHOLD,
    name_score, dosage_matches, is_combo, manufacturer_matches,
    log,
)

SOURCE = "farmakopeika"
CITY = "nsk"
BASE = "https://novosibirsk.farmakopeika.ru"

CATALOG_ID = "2440"      # «Лекарства и БАД» — корневой раздел с лекарствами
PAGE_LIMIT = 48          # макс размер страницы листинга (96+ откатывается к 12)
MAX_PAGES = 400          # предохранитель (cat 2440 ~143 стр при limit=48)
CRAWL_DELAY = 0.4

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html, */*",
    "Accept-Encoding": "gzip",
}

CHANGED_SLUGS: set[str] = set()

# --- Парсинг листинга ---
_CARD_SPLIT = '<div class="product product--catalog'
_HREF_RE = re.compile(r'/catalog/(\d+)/(\d+)')
_NAME_RE = re.compile(r'product__name[^>]*>\s*(.*?)\s*</', re.S)
_PRICE_RE = re.compile(r'product__price-value[^>]*>\s*(?:от)?\s*([\d\s ]+(?:[.,]\d+)?)\s*₽', re.S)


# Развёртка частых сокращений в названиях Фармакопейки, которые сбивают
# name_score при матчинге («Фолиевая к-та» vs канон «Фолиевая кислота»).
_ABBR_RE = [
    (re.compile(r'\bк[-\s]?т[аы]\b', re.I), 'кислота'),
    (re.compile(r'\bк[-\s]?ты\b', re.I), 'кислоты'),
]


def _clean(s: str) -> str:
    s = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', s))).strip()
    for rx, rep in _ABBR_RE:
        s = rx.sub(rep, s)
    return s


# Фасовка из имени Фармакопейки. Формат отличается от Горздрава: количество в
# штуках задаётся «№NN» (а не «NN шт» в конце), объёмные формы — «20г»/«100мл»
# в хвосте. Приводим к каноническому «{n} шт» / «{n} г» / «{n} мл» — как у
# Магнита/Горздрава, чтобы упаковки совпадали в кросс-сетевом сравнении на фронте.
_FK_NUM_RE = re.compile(r'№\s*(\d+)')
_FK_VOL_RE = re.compile(r'(\d+(?:[.,]\d+)?)\s*(мл|г|л)\b', re.IGNORECASE)


def fk_extract_pack(name: str) -> str | None:
    if not name:
        return None
    nums = _FK_NUM_RE.findall(name)
    if nums:
        return f"{int(nums[-1])} шт"
    vols = _FK_VOL_RE.findall(name)
    if vols:
        qty, unit = vols[-1]
        qty = qty.replace(',', '.')
        if '.' in qty:
            qty = qty.rstrip('0').rstrip('.')
        return f"{qty} {unit.lower()}"
    return None


# Сопоставление формы: Фармакопейка СОКРАЩАЕТ формы в названии («табл», «капс»,
# «р-р», «супп») — стандартный FORM_KEYWORDS Горздрава (полные основы «таблетк»,
# «капсул», «раствор») их не ловит. Свой словарь сокращений. Порядок важен:
# «концентрат»/«лиофилизат» проверяем ДО «раствор» (их имя тоже содержит «раствор»).
_FK_FORM: list[tuple[str, list[str]]] = [
    ("концентрат", ["конц", "р-р", "р р"]),
    ("лиофилизат", ["лиоф"]),
    ("суппозитори", ["супп", "свеч"]),
    ("таблетк", ["табл", "тб "]),
    ("капсул", ["капс"]),
    ("суспензи", ["сусп"]),
    ("аэрозол", ["аэроз"]),
    ("порошок", ["пор ", "пор."]),
    ("гранул", ["гранул"]),
    ("драже", ["драже"]),
    ("гель", ["гель", "геля"]),
    ("мазь", ["мазь", "мази"]),
    ("крем", ["крем"]),
    ("спрей", ["спрей"]),
    ("сироп", ["сироп", "сир "]),
    ("капли", ["капли", "капель", "кап."]),
    ("пластыр", ["пластыр", "тдс"]),
    ("раствор", ["р-р", "р р", "раствор"]),
    ("ампул", ["амп"]),
]


def _fk_form_ok(our_form: str, gz_name: str) -> bool:
    if not our_form:
        return True
    fl = our_form.lower()
    nl = gz_name.lower()
    for stem, abbrs in _FK_FORM:
        if stem in fl:
            return any(a in nl for a in abbrs)
    return True


def fk_match(med: dict, items: list[dict]) -> list[tuple[dict, str]]:
    """Все товары каталога, прошедшие фильтры имя/форма/дозировка.
    Клон match_products из parse_gorzdrav, но с FK-сокращениями форм и без
    атрибута производителя (его в листинге нет → status='matched')."""
    our_name = med.get("name", "")
    our_dosage = med.get("dosage", "")
    our_form = med.get("form", "")
    our_manufacturer = med.get("manufacturer", "")
    our_is_combo = "+" in our_name
    out: list[tuple[dict, str]] = []
    for item in items:
        gz_name = item.get("name", "")
        if is_combo(gz_name) and not our_is_combo:
            continue
        if not is_combo(gz_name) and our_is_combo:
            continue
        if name_score(our_name, gz_name) < NAME_THRESHOLD:
            continue
        if not _fk_form_ok(our_form, gz_name):
            continue
        if not dosage_matches(our_dosage, gz_name):
            continue
        # производителя в листинге нет → manufacturer_matches(our, "") == True
        status = "matched" if manufacturer_matches(our_manufacturer, "") else "needs_review"
        out.append((item, status))
    return out


def _parse_price(block: str) -> int | None:
    m = _PRICE_RE.search(block)
    if not m:
        return None
    digits = re.sub(r'[\s ]', '', m.group(1)).replace(',', '.')
    try:
        val = float(digits)
    except ValueError:
        return None
    val = int(round(val))
    return val if val > 0 else None


def parse_listing(text: str) -> list[dict]:
    """HTML листинга → список товаров {name, extId=prodId, url_key, _price}."""
    out: list[dict] = []
    for seg in text.split(_CARD_SPLIT)[1:]:
        block = seg[:4000]
        hm = _HREF_RE.search(block)
        nm = _NAME_RE.search(block)
        if not hm or not nm:
            continue
        prod_id = hm.group(2)
        name = _clean(nm.group(1))
        if not prod_id or not name:
            continue
        out.append({
            "name": name,
            "extId": prod_id,
            "url_key": f"/catalog/{hm.group(1)}/{prod_id}",
            "_price": _parse_price(block),
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
            log.warning(f"[farmakopeika] GET fail {url}: {e}")
            return None
    return None


async def crawl_catalog(client: httpx.AsyncClient) -> list[dict]:
    """Обойти раздел 2440 по пагинации, собрать все товары (дедуп по prodId)."""
    by_id: dict[str, dict] = {}
    empty_streak = 0
    for pg in range(1, MAX_PAGES + 1):
        url = f"{BASE}/catalog/{CATALOG_ID}?page={pg}&limit={PAGE_LIMIT}"
        text = await _get(client, url)
        if text is None:
            break
        cards = parse_listing(text)
        new = 0
        for it in cards:
            if it["extId"] not in by_id:
                by_id[it["extId"]] = it
                new += 1
        if not cards or new == 0:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
        if pg % 20 == 0:
            log.info(f"[farmakopeika]   стр {pg}: всего собрано {len(by_id)}")
        await asyncio.sleep(CRAWL_DELAY)
    items = list(by_id.values())
    with_price = sum(1 for it in items if it["_price"])
    log.info(f"[farmakopeika] КАТАЛОГ собран: {len(items)} товаров ({with_price} с ценой)")
    return items


# --- Индекс каталога по словам названия ---
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
        for w in _key_words(it["name"])[:3]:
            idx.setdefault(w, []).append(it)
    return idx


def lookup_candidates(index: dict[str, list[dict]], med: dict) -> list[dict]:
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

    if not candidates:
        await db.prices_real.update_one(
            {"medication_id": med_id, "source": SOURCE, "city": CITY},
            {"$set": {"medication_id": med_id, "slug": slug, "source": SOURCE, "city": CITY,
                      "match_status": "not_found", "updated_at": datetime.now(timezone.utc)}},
            upsert=True)
        return

    all_matches = fk_match(med, candidates)

    if not all_matches:
        top_name = candidates[0].get("name", "") if candidates else ""
        await db.prices_real.update_one(
            {"medication_id": med_id, "source": SOURCE, "city": CITY},
            {"$set": {"medication_id": med_id, "slug": slug, "source": SOURCE, "city": CITY,
                      "match_status": "no_match", "gz_top_candidate": top_name,
                      "updated_at": datetime.now(timezone.utc)}},
            upsert=True)
        return

    seen_packs: set[str] = set()
    saved = 0
    for item, item_status in all_matches:
        gz_name = item.get("name", "")
        ext_id = item.get("extId", "")
        gz_pack = fk_extract_pack(gz_name)
        if not gz_pack or gz_pack in seen_packs:
            continue
        price = item.get("_price")
        if price is None:
            continue
        seen_packs.add(gz_pack)
        price = int(price)
        log.info(f"  [nsk/{item_status:12s}] pack={gz_pack:<10} | {price} руб | {gz_name[:50]}")

        _prev = await db.prices_real.find_one(
            {"medication_id": med_id, "source": SOURCE, "city": CITY, "gz_pack": gz_pack},
            {"_id": 0, "price": 1})
        if _prev is None or _prev.get("price") != price:
            CHANGED_SLUGS.add(slug)

        await db.prices_real.update_one(
            {"medication_id": med_id, "source": SOURCE, "city": CITY, "gz_pack": gz_pack},
            {"$set": {"medication_id": med_id, "slug": slug, "source": SOURCE, "city": CITY,
                      "gz_pack": gz_pack, "match_status": item_status, "gz_ext_id": ext_id,
                      "gz_name": gz_name, "gz_url_key": item.get("url_key", ""),
                      "price": price, "updated_at": datetime.now(timezone.utc)}},
            upsert=True)
        matched_ext_ids.add(ext_id)
        saved += 1

    if saved > 0 and seen_packs:
        await db.prices_real.delete_many({
            "medication_id": med_id, "source": SOURCE, "city": CITY,
            "gz_pack": {"$nin": list(seen_packs), "$ne": None}})
    if saved:
        log.info(f"[nsk/{slug[:40]:<40}] saved {saved} packs")


async def main(args: argparse.Namespace) -> None:
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        catalog = await crawl_catalog(client)

    index = build_index(catalog)
    log.info(f"[farmakopeika] индекс: {len(index)} ключевых слов")

    query: dict = {"is_canonical": True}
    if args.slug:
        query["slug"] = args.slug
    if args.popular:
        query["mnn"] = {"$in": list(POPULAR_MNN)}
    if args.from_magnit:
        mg_slugs = await db.prices_real.distinct(
            "slug",
            {"source": "magnit", "city": CITY,
             "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
             "price": {"$ne": None}})
        query["slug"] = {"$in": mg_slugs}
        log.info(f"[nsk] --from-magnit: {len(mg_slugs)} слагов с ценой Магнита")
    if args.update_only:
        matched_slugs = await db.prices_real.distinct(
            "slug",
            {"source": SOURCE, "city": CITY,
             "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
             "price": {"$ne": None}})
        query["slug"] = {"$in": matched_slugs}

    cursor = db.medications.find(query, {
        "name": 1, "dosage": 1, "form": 1, "manufacturer": 1, "slug": 1, "mnn": 1})
    if args.limit:
        cursor = cursor.limit(args.limit)
    meds = await cursor.to_list(length=None)
    log.info(f"[nsk] Препаратов для обработки: {len(meds)}")

    rematch = args.rematch or args.update_only
    matched_ext_ids: set[str] = set()
    for i, med in enumerate(meds, 1):
        await process_medication(db, med, index, rematch, matched_ext_ids)
        if i % 500 == 0:
            log.info(f"[nsk] Прогресс: {i}/{len(meds)}")

    stats = {}
    async for doc in db.prices_real.aggregate([
        {"$match": {"source": SOURCE}},
        {"$group": {"_id": "$match_status", "count": {"$sum": 1}}}]):
        stats[doc["_id"]] = doc["count"]
    log.info(f"[farmakopeika] Готово. Статистика: {stats}")

    out_path = os.environ.get("INDEXNOW_CHANGED_FILE_FARMAKOPEIKA",
                              "/tmp/indexnow_changed_farmakopeika.txt")
    try:
        with open(out_path, "w") as f:
            for sl in sorted(CHANGED_SLUGS):
                f.write(sl + "\n")
        log.info(f"[farmakopeika] IndexNow: {len(CHANGED_SLUGS)} изменённых slug -> {out_path}")
    except Exception as e:
        log.warning(f"[farmakopeika] IndexNow: не смог записать {out_path}: {e}")
    client_db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--slug", type=str, default="")
    parser.add_argument("--popular", action="store_true")
    parser.add_argument("--from-magnit", dest="from_magnit", action="store_true",
                        help="Только препараты с уже существующей ценой Магнита в Новосибирске.")
    parser.add_argument("--update-only", dest="update_only", action="store_true",
                        help="Обновить только препараты с уже существующим матчем Фармакопейки.")
    parser.add_argument("--rematch", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args))
