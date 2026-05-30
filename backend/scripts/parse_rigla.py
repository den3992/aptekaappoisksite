"""
Парсер цен Ригла (rigla.ru) → коллекция prices_real, source="rigla".

Ригла — 3-й источник цен по Москве (после Горздрав и 36,6). В отличие от
gorzdrav.org / 366.ru (общая платформа platfomni с REST product-search/ext),
Ригла работает на Magento и отдаёт каталог через GraphQL:

    POST https://www.rigla.ru/graphql
    Headers: Content-Type: application/json ; X-APP: WEB
    query Q($query,$pageSize,$currentPage){
      products: productsElastic(search:$query, pageSize:$pageSize,
                 currentPage:$currentPage,
                 sort:{is_in_stock:DESC, score:DESC, name:ASC}){   # sort ОБЯЗАТЕЛЕН
        total_count
        items{ id sku name url_key is_in_stock
               price{ regularPrice{ amount{ value } } } }
      }
    }

Регион = Москва (домен www.rigla.ru, без region-заголовка). Поэтому Ригла
парсится ТОЛЬКО для city="msk" (в отличие от gz/366 с MOS+SPE).

Матчинг переиспользуется из parse_gorzdrav (name_score / dosage_matches /
form_matches / extract_pack / match_product[s]). У ответа Ригла нет поля
manufacturer в удобном виде (атрибут SelectAttributeElastic нестабилен),
поэтому attributes пустые → статусы матча будут "needs_review"/"mnn_match"
(производитель не подтверждается, но это валидный отображаемый статус, как
у Горздрава/36,6 needs_review).

КЛЮЧЕВОЕ ОГРАНИЧЕНИЕ (требование заказчика): сохраняем ТОЛЬКО те позиции,
которые уже есть в нашем каталоге medications (через match_products). Новые
SKU не заводим.

ЭТАП 1 (этот файл): матчинг + цена по Москве → «сравнение цен» 3 сетей.
ЭТАП 2 (позже): карта наличия по конкретным аптекам Ригла (store_bitmap) —
через getPvzStocks/pvzList. Здесь не реализуется.

Запуск:
    python -m scripts.parse_rigla                  # все канонические, msk
    python -m scripts.parse_rigla --limit 100
    python -m scripts.parse_rigla --slug nurofen-200-mg-tabletki
    python -m scripts.parse_rigla --popular
    python -m scripts.parse_rigla --from-gorzdrav  # только слаги с матчем Горздрава msk
    python -m scripts.parse_rigla --update-only    # только препараты с матчем Ригла
    python -m scripts.parse_rigla --rematch        # перематчить уже сматченные
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

# Переиспользуем матчинг и константы Горздрава (импорт read-only).
from scripts.parse_gorzdrav import (
    MONGO_URL, DB_NAME, POPULAR_MNN,
    REQUEST_DELAY, CONCURRENCY,
    match_product, match_products, extract_pack,
    log,
)

SOURCE = "rigla"
CITY = "msk"  # Ригла — только Москва (домен www.rigla.ru)
GRAPHQL_URL = "https://www.rigla.ru/graphql"
PAGE_SIZE = 50  # верхних 50 листингов достаточно для всех упаковок препарата

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-APP": "WEB",
}

# sort ОБЯЗАТЕЛЕН (без него GraphQL отдаёт 500).
GQL_SEARCH = (
    "query Q($query:String,$pageSize:Int!,$currentPage:Int!){"
    " products: productsElastic(search:$query, pageSize:$pageSize,"
    " currentPage:$currentPage, sort:{is_in_stock:DESC, score:DESC, name:ASC}){"
    " total_count items{ id sku name url_key is_in_stock"
    " price{ regularPrice{ amount{ value } } } } } }"
)

# slug-и с изменившейся ценой Ригла — для IndexNow.
CHANGED_SLUGS: set[str] = set()

# Ригла пишет счётные упаковки как «№ 30» / «№30» (в конце имени), тогда как
# Горздрав/36,6 — как «30 шт». Чтобы gz_pack совпадал между источниками (и
# фронт сводил цены сетей по одной упаковке), нормализуем «№N» → «N шт».
# Жидкие формы у Ригла заканчиваются на «100мл»/«5г» → их ловит штатный
# extract_pack Горздрава.
_RIGLA_NUM_RE = re.compile(r"№\s*(\d+)")


def rigla_extract_pack(name: str) -> str | None:
    if not name:
        return None
    m = _RIGLA_NUM_RE.search(name)
    if m:
        return f"{int(m.group(1))} шт"
    return extract_pack(name)


def _normalize_item(raw: dict) -> dict:
    """Приводим листинг Ригла к структуре, которую ждёт матчинг Горздрава
    (name + attributes). attributes пустые: manufacturer Ригла нестабилен."""
    return {
        "name": raw.get("name", ""),
        "extId": str(raw.get("sku") or raw.get("id") or ""),
        "url_key": raw.get("url_key", ""),
        "is_in_stock": str(raw.get("is_in_stock", "")).lower() == "true",
        "_price": (((raw.get("price") or {}).get("regularPrice") or {})
                   .get("amount") or {}).get("value"),
        "attributes": [],
    }


async def search_rigla(client: httpx.AsyncClient, query: str) -> list[dict]:
    """POST GraphQL productsElastic, 3 попытки с backoff."""
    payload = {
        "query": GQL_SEARCH,
        "variables": {"query": query, "pageSize": PAGE_SIZE, "currentPage": 1},
    }
    for attempt in range(3):
        try:
            r = await client.post(GRAPHQL_URL, json=payload, timeout=25)
            r.raise_for_status()
            data = r.json()
            if data.get("errors"):
                log.warning(f"[rigla] GraphQL errors for '{query[:40]}': "
                            f"{data['errors'][0].get('message', '')[:120]}")
                return []
            items = (((data.get("data") or {}).get("products") or {})
                     .get("items") or [])
            return [_normalize_item(it) for it in items]
        except Exception as e:
            if attempt < 2:
                wait = 1 + attempt * 2
                log.warning(f"[rigla] search '{query[:40]}' попытка {attempt + 1}/3: {e} — пауза {wait}с")
                await asyncio.sleep(wait)
                continue
            log.warning(f"[rigla] search error for '{query[:40]}' (после 3 попыток): {e}")
            return []
    return []


async def process_medication(
    client: httpx.AsyncClient,
    db,
    med: dict,
    rematch: bool,
    matched_ext_ids: set,
) -> None:
    med_id = med["_id"]
    slug = med.get("slug", str(med_id))
    name = med.get("name", "")
    dosage = med.get("dosage", "")
    mnn = med.get("mnn", "")

    existing = await db.prices_real.find_one(
        {"medication_id": med_id, "source": SOURCE, "city": CITY}
    )
    if existing and not rematch:
        log.debug(f"skip (already matched): {slug}")
        return

    # Проход 1: поиск по бренд-названию.
    query = name.strip()
    items = await search_rigla(client, query)
    await asyncio.sleep(REQUEST_DELAY)
    items2: list[dict] = []

    matched_item, status = match_product(med, items)
    search_pass = "name"

    # Проход 2: по МНН, если по имени не нашли.
    if matched_item is None and mnn and mnn.lower() not in name.lower():
        mnn_query = f"{mnn.lower()} {dosage}".strip()
        items2 = await search_rigla(client, mnn_query)
        await asyncio.sleep(REQUEST_DELAY)
        matched_item, status = match_product(med, items2, allow_combo=False)
        if matched_item:
            search_pass = "mnn"
            if status == "matched":
                status = "mnn_match"

    if not items and (not mnn or mnn.lower() in name.lower()):
        log.info(f"[{CITY}/not_found]  {slug}")
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
        top_name = items[0].get("name", "") if items else ""
        log.info(f"[{CITY}/no match]   {slug} | top: {top_name[:60]}")
        await db.prices_real.update_one(
            {"medication_id": med_id, "source": SOURCE, "city": CITY},
            {"$set": {
                "medication_id": med_id, "slug": slug, "source": SOURCE, "city": CITY,
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
        gz_pack = rigla_extract_pack(gz_name)
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
            f"  [{item_status:12s}] pack={gz_pack:<10} | {price} руб | {gz_name[:50]}"
        )

        # IndexNow: фиксируем изменение цены.
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
                "search_query": query,
                "search_pass": search_pass,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        matched_ext_ids.add(ext_id)
        saved += 1

    # Удаляем устаревшие упаковки Ригла для этого препарата.
    if saved > 0 and seen_packs:
        await db.prices_real.delete_many({
            "medication_id": med_id, "source": SOURCE, "city": CITY,
            "gz_pack": {"$nin": list(seen_packs), "$ne": None},
        })

    log.info(f"[{CITY}/{slug[:40]:<40}] saved {saved} packs (pass={search_pass})")


async def main(args: argparse.Namespace) -> None:
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    log.info(f"=== [rigla] city={CITY} (Москва) ===")

    query: dict = {"is_canonical": True}
    if args.slug:
        query["slug"] = args.slug
    if args.popular:
        query["mnn"] = {"$in": list(POPULAR_MNN)}
    if args.from_gorzdrav:
        # Узкий набор: только препараты с уже существующим матчем Горздрава
        # в Москве. ×N меньше работы, ровно SEO-значимые страницы.
        gz_slugs = await db.prices_real.distinct(
            "slug",
            {"source": "gorzdrav", "city": CITY,
             "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
             "price": {"$ne": None}},
        )
        query["slug"] = {"$in": gz_slugs}
        log.info(f"--from-gorzdrav: {len(gz_slugs)} слагов с матчем Горздрава")
    if args.update_only:
        matched_slugs = await db.prices_real.distinct(
            "slug",
            {"source": SOURCE, "city": CITY,
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
    log.info(f"Препаратов для обработки: {len(meds)}")

    matched_ext_ids: set[str] = set()
    async with httpx.AsyncClient(headers=HEADERS) as client:
        sem = asyncio.Semaphore(CONCURRENCY)
        done = [0]

        async def worker(med):
            async with sem:
                await process_medication(client, db, med, args.rematch, matched_ext_ids)
                done[0] += 1
                if done[0] % 100 == 0:
                    log.info(f"Прогресс: {done[0]}/{len(meds)}")

        await asyncio.gather(*(worker(m) for m in meds))

    stats = {}
    async for doc in db.prices_real.aggregate([
        {"$match": {"source": SOURCE}},
        {"$group": {"_id": "$match_status", "count": {"$sum": 1}}},
    ]):
        stats[doc["_id"] or "?"] = doc["count"]

    log.info(f"[rigla] Готово. Статистика: {stats}")

    # IndexNow: slug-и с изменившейся ценой → отдельный файл.
    out_path = os.environ.get("INDEXNOW_CHANGED_FILE_RIGLA", "/tmp/indexnow_changed_rigla.txt")
    try:
        with open(out_path, "w") as f:
            for sl in sorted(CHANGED_SLUGS):
                f.write(sl + "\n")
        log.info(f"[rigla] IndexNow: {len(CHANGED_SLUGS)} изменённых slug-ов -> {out_path}")
    except Exception as e:
        log.warning(f"[rigla] IndexNow: не смог записать {out_path}: {e}")
    client_db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--slug", type=str, default="")
    parser.add_argument("--popular", action="store_true")
    parser.add_argument("--from-gorzdrav", action="store_true",
                        help="Только препараты с уже существующим матчем Горздрава в Москве.")
    parser.add_argument("--update-only", action="store_true",
                        help="Обновить только препараты с уже существующим матчем Ригла.")
    parser.add_argument("--rematch", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args))
