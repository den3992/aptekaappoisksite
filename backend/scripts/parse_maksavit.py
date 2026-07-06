"""
Парсер цен и наличия сети «Максавит» (maksavit.ru) → коллекция prices_real,
source="maksavit". 4-й источник (после Горздрав, 36,6, Ригла).

В отличие от Ригла (только Москва), Максавит — мультигородний. Сеть НЕ работает
в Москве; из нужных нам городов есть:
    nn  → Нижний Новгород      (city code 0000600317, ~256 аптек)
    spb → Санкт-Петербург      (city code 0000103664, ~22 аптеки)
    krd → Краснодар            (city code 0000386590, ~16 аптек)
    msk → Пушкино, Моск. обл.  (city code 0000058308, 3 аптеки) — вешаем на Москву

API (Nuxt + Bitrix, без авторизации, JSON):
    Город задаётся cookie  location_code=<cityCode>; location_selected=Y
    Поиск/цена:   GET /api/catalog/all?queryString=<text>[&limit=N]
                  → {count, products:[{id,urlId,code,name,price,
                                       todayDrugstoreCount, offers:[...]}]}
                  цена в листинге уже по выбранному городу.
    Наличие:      GET /api/product/<urlId>
                  → {product:{...}, drugstores:{drugstoreList:[{id,
                       availableOfferCount, ...}]}}  — список аптет ВЫБРАННОГО
                       города с наличием (availableOfferCount>0 = есть в наличии).
    Аптеки:       GET /api/drugstore/city/code/<cityCode>
                  → {drugstoreList:[{id,title,address,latitude,longitude,
                                     schedule,phone,district,...}]}
    Ключ связи реестра и наличия — store id (общее пространство id/xmlId).

Матчинг переиспользуется из parse_gorzdrav (match_product[s]/extract_pack).
КЛЮЧЕВОЕ ОГРАНИЧЕНИЕ (требование заказчика): сохраняем ТОЛЬКО позиции, которые
уже есть в нашем каталоге medications. Новые SKU не заводим.

Запуск:
    python -m scripts.parse_maksavit                  # все города, цены+наличие
    python -m scripts.parse_maksavit --city nn        # только один город
    python -m scripts.parse_maksavit --limit 100
    python -m scripts.parse_maksavit --slug nurofen-...
    python -m scripts.parse_maksavit --update-only    # только препараты с матчем Максавит
    python -m scripts.parse_maksavit --rematch
    python -m scripts.parse_maksavit --availability-only
    python -m scripts.parse_maksavit --no-availability
"""
from __future__ import annotations

import os
import re
import sys
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
    REQUEST_DELAY, CONCURRENCY, _popcount,
    match_product, match_products, extract_pack,
    log,
)
from bson.binary import Binary

SOURCE = "maksavit"
BASE = "https://maksavit.ru"
# Поиск /api/catalog/all отдаёт по 15 товаров на страницу (page_size фиксирован,
# параметр limit вызывает 400). Берём до MAX_PAGES страниц через ?page=N —
# на запрос по названию препарата этого с запасом хватает на все упаковки.
MAX_PAGES = 4

# Наш slug города → city code Максавита (location_code).
CITY_CODES: dict[str, str] = {
    "nn":  "0000600317",  # Нижний Новгород
    "spb": "0000103664",  # Санкт-Петербург
    "krd": "0000386590",  # Краснодар
    "msk": "0000058308",  # Пушкино (Московская обл.) — вешаем на Москву
    # Расширение на слабые города, где Максавит реально работает (2-я сеть →
    # города становятся «сильными», ≥2 сети). Коды из /api/location/city-list.
    "kzn": "0000550426",  # Казань (Татарстан)
    "vrn": "0000293598",  # Воронеж
    "ufa": "0000728734",  # Уфа (Башкортостан)
    "rnd": "0000445112",  # Ростов-на-Дону
    "nsk": "0000949228",  # Новосибирск (3-я сеть: +Магнит +Фармакопейка)
}
# Человекочитаемое имя для логов.
CITY_NAMES = {"nn": "Нижний Новгород", "spb": "Санкт-Петербург",
              "krd": "Краснодар", "msk": "Пушкино (МО)",
              "kzn": "Казань", "vrn": "Воронеж", "ufa": "Уфа",
              "rnd": "Ростов-на-Дону", "nsk": "Новосибирск"}

# Параллельность фазы наличия (запросы /api/product тяжёлые, ~1 МБ).
AVAIL_CONCURRENCY = 6
AVAIL_DELAY = 0.15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "application/json",
}

# slug-и с изменившейся ценой — для IndexNow.
CHANGED_SLUGS: set[str] = set()


def _cookies(code: str) -> dict:
    return {"location_code": code, "location_selected": "Y"}


# Максавит пишет упаковки как «№20» (в конце имени), как Ригла. Приводим к
# «N шт», чтобы gz_pack совпадал с Горздрав/36,6/Ригла. Жидкие формы
# («100 мг/5 мл 200 мл») ловит штатный extract_pack.
_NUM_RE = re.compile(r"№\s*(\d+)")


def maksavit_extract_pack(name: str) -> str | None:
    if not name:
        return None
    m = _NUM_RE.search(name)
    if m:
        return f"{int(m.group(1))} шт"
    return extract_pack(name)


# Расписание Максавита: «Пн - Вс: 08.00 - 21.00 » (точка-разделитель времени).
# Приводим к виду Горздрава: «Круглосуточно» / «Ежедневно HH:MM–HH:MM».
_MK_TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})\s*[-–]\s*(\d{1,2})[.:](\d{2})")


def fmt_maksavit_schedule(raw: str) -> tuple[str, bool]:
    if not raw or not isinstance(raw, str):
        return "", False
    s = " ".join(raw.split())  # схлопываем пробелы
    if "круглосут" in s.lower():
        return "Круглосуточно", True
    m = _MK_TIME_RE.search(s)
    if not m:
        return s, False
    a = f"{int(m.group(1)):02d}:{m.group(2)}"
    b = f"{int(m.group(3)):02d}:{m.group(4)}"
    if a == "00:00" and b in ("24:00", "00:00"):
        return "Круглосуточно", True
    return f"Ежедневно {a}–{b}", False


# Телефон Максавита: обычно один номер «+7 915 943-22-14». Нормализуем по одному
# на строку (на случай нескольких через ; / перенос).
def normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    parts = [p.strip() for p in re.split(r"[;\n]+", raw) if p.strip()]
    return "\n".join(parts)


# Максавит сокращает лекформу в названии («табл.», «капс.», «р-р», «конц.»),
# а form_matches Горздрава ищет полные основы («таблетк», «капсул», «раствор»,
# «концентрат»). Дописываем к имени полные слова-подсказки, чтобы form_matches
# срабатывал. Оригинальное имя сохраняем отдельно (для отображения и упаковки).
_FORM_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bтабл\b", re.I), "таблетки"),
    (re.compile(r"\bкапс\b", re.I), "капсулы"),
    (re.compile(r"\bсусп\b", re.I), "суспензия"),
    (re.compile(r"\b(?:супп|свеч)\w*", re.I), "суппозитории"),
    (re.compile(r"\bпор\b", re.I), "порошок"),
    (re.compile(r"\bр-ра?\b", re.I), "раствор"),
    (re.compile(r"\bконц\b", re.I), "концентрат"),
    (re.compile(r"\bаэр\w*", re.I), "аэрозоль"),
    (re.compile(r"\bлиоф\w*", re.I), "лиофилизат"),
    (re.compile(r"\bгран\w*", re.I), "гранулы"),
    (re.compile(r"\bдраже\b", re.I), "драже"),
    (re.compile(r"\bпласт\w*", re.I), "пластырь"),
]


def _form_hint(name: str) -> str:
    if not name:
        return ""
    extra = [full for rx, full in _FORM_HINTS if rx.search(name)]
    return " ".join(extra)


def _normalize_item(raw: dict) -> dict:
    """Листинг Максавита → структура для матчинга Горздрава (name+attributes).
    attributes пустые: производитель в листинге нестабилен (brandName).
    К name дописываем полную лекформу-подсказку для form_matches; оригинал
    кладём в orig_name (его используем для отображения и упаковки)."""
    orig = raw.get("name", "")
    # Максавит пишет дробные дозировки через запятую («0,4 мг»), наш каталог —
    # через точку («0.4 мг»). Для матчинга приводим к точке (отображение и
    # упаковку берём из orig_name, их не трогаем).
    match_name = re.sub(r"(\d),(\d)", r"\1.\2", orig)
    hint = _form_hint(orig)
    return {
        "name": f"{match_name} {hint}".strip() if hint else match_name,
        "orig_name": orig,
        "extId": str(raw.get("urlId") or raw.get("id") or ""),  # urlId → /api/product/<urlId>
        "code": raw.get("code", ""),
        "is_in_stock": not raw.get("isNotAvailable", False),
        "_price": raw.get("price"),
        "attributes": [],
    }


async def _fetch_page(client: httpx.AsyncClient, query: str, code: str, page: int) -> dict | None:
    """Одна страница поиска. 3 попытки с backoff."""
    params = {"queryString": query}
    if page > 1:
        params["page"] = page
    for attempt in range(3):
        try:
            r = await client.get(f"{BASE}/api/catalog/all", params=params,
                                  cookies=_cookies(code), timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt < 2:
                wait = 1 + attempt * 2
                log.warning(f"[maksavit] search '{query[:40]}' p{page} попытка {attempt+1}/3: {e} — пауза {wait}с")
                await asyncio.sleep(wait)
                continue
            log.warning(f"[maksavit] search error '{query[:40]}' p{page} (после 3 попыток): {e}")
            return None
    return None


async def search_maksavit(client: httpx.AsyncClient, query: str, code: str) -> list[dict]:
    """GET /api/catalog/all?queryString=… с пагинацией (до MAX_PAGES страниц)."""
    data = await _fetch_page(client, query, code, 1)
    if data is None:
        return []
    items = list(data.get("products") or [])
    page_count = int(((data.get("pager") or {}).get("page_count")) or 1)
    for page in range(2, min(page_count, MAX_PAGES) + 1):
        d = await _fetch_page(client, query, code, page)
        if not d:
            break
        items.extend(d.get("products") or [])
    return [_normalize_item(it) for it in items]


async def process_medication(
    client: httpx.AsyncClient, db, med: dict, city: str, code: str,
    rematch: bool, matched_ext_ids: set,
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
        return

    query = name.strip()
    items = await search_maksavit(client, query, code)
    await asyncio.sleep(REQUEST_DELAY)
    items2: list[dict] = []

    matched_item, status = match_product(med, items)
    search_pass = "name"

    if matched_item is None and mnn and mnn.lower() not in name.lower():
        mnn_query = f"{mnn.lower()} {dosage}".strip()
        items2 = await search_maksavit(client, mnn_query, code)
        await asyncio.sleep(REQUEST_DELAY)
        matched_item, status = match_product(med, items2, allow_combo=False)
        if matched_item:
            search_pass = "mnn"
            if status == "matched":
                status = "mnn_match"

    if not items and (not mnn or mnn.lower() in name.lower()):
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
        gz_name = item.get("orig_name") or item.get("name", "")
        ext_id = item.get("extId", "")  # urlId
        gz_pack = maksavit_extract_pack(gz_name)
        if not gz_pack:
            continue
        if gz_pack in seen_packs:
            continue
        seen_packs.add(gz_pack)

        price = item.get("_price")
        if price is None:
            continue
        price = int(price)

        log.info(f"  [{city}/{item_status:12s}] pack={gz_pack:<10} | {price} руб | {gz_name[:48]}")

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
                "gz_code": item.get("code", ""),
                "gz_name": gz_name,
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


async def refresh_stores_maksavit(client: httpx.AsyncClient, db, city: str, code: str) -> dict[int, int]:
    """Подтягиваем аптеки Максавита города в общий реестр gorzdrav_stores
    (append-only idx, source='maksavit'). store_id = 'maksavit_<id>'.
    Возвращает {maksavit_store_id(int): idx} для активных точек с координатами.
    """
    try:
        r = await client.get(f"{BASE}/api/drugstore/city/code/{code}",
                             cookies=_cookies(code), timeout=30)
        r.raise_for_status()
        raw = (r.json() or {}).get("drugstoreList") or []
    except Exception as e:
        log.warning(f"[maksavit] {city}: не смог получить аптеки: {e}")
        return {}
    log.info(f"[maksavit] {city} ({CITY_NAMES.get(city,'')}): аптек в выдаче {len(raw)}")

    # Существующие idx (по всему реестру — append-only).
    store_idx: dict[str, int] = {}
    next_idx = -1
    async for st in db.gorzdrav_stores.find({}, {"_id": 0, "store_id": 1, "idx": 1}):
        i = st.get("idx")
        if i is None:
            continue
        store_idx[st["store_id"]] = i
        if i > next_idx:
            next_idx = i
    next_idx += 1

    out: dict[int, int] = {}
    seen: list[str] = []
    for it in raw:
        try:
            mid = int(it["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if it.get("latitude") is None or it.get("longitude") is None:
            continue
        try:
            lat = float(it["latitude"]); lng = float(it["longitude"])
        except (TypeError, ValueError):
            continue
        sid = f"maksavit_{mid}"
        seen.append(sid)
        idx = store_idx.get(sid)
        if idx is None:
            idx = next_idx
            next_idx += 1
            store_idx[sid] = idx
        hours, is_24h = fmt_maksavit_schedule(it.get("schedule") or "")
        await db.gorzdrav_stores.update_one(
            {"store_id": sid},
            {"$setOnInsert": {"store_id": sid, "idx": idx},
             "$set": {
                 "name": "Максавит",
                 "full_name": it.get("title") or "Аптека «Максавит»",
                 "lat": lat, "lng": lng,
                 "address": (it.get("address") or "").strip(),
                 "phone": normalize_phone(it.get("phone") or ""),
                 "hours": hours,
                 "is_24h": is_24h,
                 "city": city,
                 "source": SOURCE,
                 "active": True,
                 "updated_at": datetime.now(timezone.utc),
             }},
            upsert=True,
        )
        out[mid] = idx

    deact = await db.gorzdrav_stores.update_many(
        {"source": SOURCE, "city": city, "store_id": {"$nin": seen}},
        {"$set": {"active": False}},
    )
    log.info(f"[maksavit] {city}: реестр обновлён — {len(out)} активных, деактивировано {deact.modified_count}")
    return out


async def refresh_availability_maksavit(
    client: httpx.AsyncClient, db, city: str, code: str, urlids: list[str],
) -> None:
    """Фаза наличия: для каждого urlId (упаковки) запрашиваем /api/product/<urlId>
    в контексте города, по drugstoreList взводим бит idx аптек, где
    availableOfferCount>0. Маску пишем в prices_real по gz_ext_id (urlId)."""
    if not urlids:
        log.info(f"[maksavit] {city} availability: нет urlId — пропуск")
        return
    store_map = await refresh_stores_maksavit(client, db, city, code)
    if not store_map:
        log.warning(f"[maksavit] {city} availability: нет аптек — пропуск")
        return

    # nbytes по максимальному idx ВСЕГО реестра (общий с другими сетями).
    max_idx = -1
    async for st in db.gorzdrav_stores.find({}, {"_id": 0, "idx": 1}):
        i = st.get("idx")
        if i is not None and i > max_idx:
            max_idx = i
    nbytes = (max_idx + 8) // 8
    urlids = sorted(set(u for u in urlids if u))
    log.info(f"[maksavit] {city} availability: {len(urlids)} urlId × {len(store_map)} аптек, маска {nbytes} б")

    sem = asyncio.Semaphore(AVAIL_CONCURRENCY)
    done = [0]
    total = len(urlids)

    async def one_product(urlid: str):
        ba = bytearray(nbytes)
        try:
            async with sem:
                r = await client.get(f"{BASE}/api/product/{urlid}",
                                     cookies=_cookies(code), timeout=40)
                r.raise_for_status()
                data = r.json()
                await asyncio.sleep(AVAIL_DELAY)
        except Exception as e:
            log.warning(f"[maksavit] {city} product {urlid}: {e}")
            return
        ds = ((data or {}).get("drugstores") or {}).get("drugstoreList") or []
        for s in ds:
            try:
                if int(s.get("availableOfferCount") or 0) <= 0:
                    continue
                idx = store_map.get(int(s["id"]))
            except (TypeError, ValueError):
                continue
            if idx is None:
                continue
            ba[idx >> 3] |= 1 << (idx & 7)
        await db.prices_real.update_many(
            {"source": SOURCE, "city": city, "gz_ext_id": urlid},
            {"$set": {"store_bitmap": Binary(bytes(ba)), "stores_count": _popcount(ba)}},
        )
        done[0] += 1
        if done[0] % 200 == 0:
            log.info(f"[maksavit] {city} availability: {done[0]}/{total}")

    await asyncio.gather(*(one_product(u) for u in urlids))
    log.info(f"[maksavit] {city} availability: готово ({total} urlId)")


async def run_city(client, db, city: str, code: str, args, meds: list[dict]) -> None:
    log.info(f"=== [maksavit] city={city} ({CITY_NAMES.get(city,'')}) code={code} ===")

    if args.availability_only:
        urlids = await db.prices_real.distinct(
            "gz_ext_id",
            {"source": SOURCE, "city": city, "price": {"$ne": None},
             "gz_ext_id": {"$nin": [None, ""]}},
        )
        await refresh_availability_maksavit(client, db, city, code, urlids)
        return

    matched_ext_ids: set[str] = set()
    sem = asyncio.Semaphore(CONCURRENCY)
    done = [0]

    async def worker(med):
        async with sem:
            await process_medication(client, db, med, city, code, args.rematch, matched_ext_ids)
            done[0] += 1
            if done[0] % 200 == 0:
                log.info(f"[maksavit] {city} прогресс: {done[0]}/{len(meds)}")

    await asyncio.gather(*(worker(m) for m in meds))

    if not args.no_availability:
        await refresh_availability_maksavit(
            client, db, city, code, sorted(matched_ext_ids))


async def main(args: argparse.Namespace) -> None:
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    cities = [c.strip() for c in args.city.split(",")] if args.city else list(CITY_CODES.keys())
    cities = [c for c in cities if c in CITY_CODES]
    if not cities:
        log.error(f"Неизвестный город. Доступно: {list(CITY_CODES)}")
        client_db.close()
        return

    # Набор препаратов (общий для всех городов).
    if args.availability_only:
        meds = []
    else:
        query: dict = {"is_canonical": True}
        if args.slug:
            query["slug"] = args.slug
        if args.popular:
            query["mnn"] = {"$in": list(POPULAR_MNN)}
        if args.from_magnit:
            mg_slugs = await db.prices_real.distinct(
                "slug",
                {"source": "magnit", "city": {"$in": cities}, "price": {"$gt": 0}},
            )
            query["slug"] = {"$in": mg_slugs}
            log.info(f"[maksavit] --from-magnit: {len(mg_slugs)} слагов с Магнитом в {cities}")
        if args.update_only:
            matched_slugs = await db.prices_real.distinct(
                "slug",
                {"source": SOURCE,
                 "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
                 "price": {"$ne": None}},
            )
            query["slug"] = {"$in": matched_slugs}
            args.rematch = True
        cursor = db.medications.find(query, {
            "name": 1, "dosage": 1, "form": 1, "manufacturer": 1, "slug": 1, "mnn": 1,
        })
        if args.limit:
            cursor = cursor.limit(args.limit)
        meds = await cursor.to_list(length=None)
        log.info(f"[maksavit] препаратов для обработки: {len(meds)} × городов: {len(cities)}")

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        for city in cities:
            await run_city(client, db, city, CITY_CODES[city], args, meds)

    stats = {}
    async for doc in db.prices_real.aggregate([
        {"$match": {"source": SOURCE}},
        {"$group": {"_id": {"city": "$city", "st": "$match_status"}, "count": {"$sum": 1}}},
    ]):
        k = f"{doc['_id'].get('city')}/{doc['_id'].get('st')}"
        stats[k] = doc["count"]
    log.info(f"[maksavit] Готово. Статистика: {stats}")

    out_path = os.environ.get("INDEXNOW_CHANGED_FILE_MAKSAVIT", "/tmp/indexnow_changed_maksavit.txt")
    try:
        with open(out_path, "w") as f:
            for sl in sorted(CHANGED_SLUGS):
                f.write(sl + "\n")
        log.info(f"[maksavit] IndexNow: {len(CHANGED_SLUGS)} изменённых slug -> {out_path}")
    except Exception as e:
        log.warning(f"[maksavit] IndexNow: не смог записать {out_path}: {e}")
    client_db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", type=str, default="", help="nn|spb|krd|msk (по умолч. все)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--from-magnit", dest="from_magnit", action="store_true",
                        help="Только препараты с ценой Магнита в целевых городах (будущие сильные страницы).")
    parser.add_argument("--slug", type=str, default="")
    parser.add_argument("--popular", action="store_true")
    parser.add_argument("--update-only", action="store_true",
                        help="Только препараты с уже существующим матчем Максавит.")
    parser.add_argument("--rematch", action="store_true")
    parser.add_argument("--availability-only", action="store_true",
                        help="Только маски наличия (store_bitmap), без перематчинга цен.")
    parser.add_argument("--no-availability", action="store_true",
                        help="Не запускать фазу наличия после матчинга цен.")
    args = parser.parse_args()
    asyncio.run(main(args))
