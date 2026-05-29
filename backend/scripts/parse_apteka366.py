"""
Парсер цен Аптеки 36,6 (366.ru) → коллекция prices_real, source="apteka366".

36,6 и Горздрав работают на ОДНОЙ платформе (platfomni/id-soft), поэтому API
идентичен Горздраву: тот же `POST /api/v1/product-search/ext`, та же структура
ответа (items[].{extId, name, prices, attributes, ...}). Отличие — заголовок
`Flex-Locale: country=RU;bs=366.ru` (у Горздрава bs=gz.ru) переключает каталог
и ЦЕНЫ бренда. extId общий для обоих брендов, но цены различаются (≈80% SKU).

Логика матчинга переиспользуется импортом из parse_gorzdrav (тот же набор:
name_score / dosage_matches / form_matches / extract_pack / match_product[s]),
чтобы не дублировать 700 строк и не расходиться с Горздравом по качеству матча.

ЭТАП 1 (этот файл): матчинг + per-city цена → настоящее «сравнение цен» 2 сетей.
ЭТАП 2 (позже): карта наличия по конкретным аптекам (store_bitmap) — требует
раскрытия region-параметра в /api/v1/delivery/map/region/detail у 366.ru.

Запуск:
    python -m scripts.parse_apteka366                 # все канонические, оба города
    python -m scripts.parse_apteka366 --limit 100
    python -m scripts.parse_apteka366 --slug nurofen-ekspress-kapsuly-200-mg
    python -m scripts.parse_apteka366 --popular
    python -m scripts.parse_apteka366 --update-only   # только препараты с матчем 36,6
    python -m scripts.parse_apteka366 --rematch       # перематчить уже сматченные
    python -m scripts.parse_apteka366 --region MOS    # MOS | SPE | both (по умолч.)
"""
from __future__ import annotations

import os
import sys
import asyncio
import argparse
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from motor.motor_asyncio import AsyncIOMotorClient

# Переиспользуем матчинг и константы Горздрава (импорт read-only,
# на работающий крон parse_gorzdrav никак не влияет).
from scripts.parse_gorzdrav import (
    MONGO_URL, DB_NAME, REGIONS, POPULAR_MNN,
    SEARCH_SIZE, REQUEST_DELAY, CONCURRENCY,
    match_product, match_products, extract_pack,
    log,
)

SOURCE = "apteka366"
BASE = "https://366.ru"
# Базовые заголовки. Flex-Region проставляется per-region в main().
# Ключевое отличие от Горздрава — bs=366.ru (brand-segment → каталог/цены 36,6).
HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Flex-Locale": "country=RU;bs=366.ru",
    "Flex-App": "WEB",
}

# slug-и с изменившейся ценой 36,6 — для IndexNow.
CHANGED_SLUGS: set[str] = set()


async def search_366(client: httpx.AsyncClient, query: str) -> list[dict]:
    # 3 попытки с backoff: под конкурентной нагрузкой платформа иногда
    # отдаёт 429/502/503, ретрай разруливает.
    for attempt in range(3):
        try:
            r = await client.post(
                f"{BASE}/api/v1/product-search/ext",
                json={"page": 1, "size": SEARCH_SIZE, "filters": {"q": query}},
                timeout=20,
            )
            r.raise_for_status()
            return r.json().get("data", {}).get("result", {}).get("items", [])
        except Exception as e:
            if attempt < 2:
                wait = 1 + attempt * 2
                log.warning(f"[366] search '{query[:40]}' попытка {attempt + 1}/3: {e} — пауза {wait}с")
                await asyncio.sleep(wait)
                continue
            log.warning(f"[366] search error for '{query[:40]}' (после 3 попыток): {e}")
            return []
    return []


async def process_medication(
    client: httpx.AsyncClient,
    db,
    med: dict,
    rematch: bool,
    city: str,
    matched_ext_ids: set,
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

    # Проход 1: поиск по бренд-названию (дозировка проверяется через
    # dosage_matches на возвращённых листингах).
    query = name.strip()
    items = await search_366(client, query)
    await asyncio.sleep(REQUEST_DELAY)
    items2 = []

    matched_item, status = match_product(med, items)
    search_pass = "name"

    # Проход 2: если не нашли — по МНН (если он отличается от имени).
    if matched_item is None and mnn and mnn.lower() not in name.lower():
        mnn_query = f"{mnn.lower()} {dosage}".strip()
        items2 = await search_366(client, mnn_query)
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
        gz_pack = extract_pack(gz_name)
        if not gz_pack:
            log.warning(f"  skip (no pack in name): {gz_name[:60]}")
            continue
        if gz_pack in seen_packs:
            continue
        seen_packs.add(gz_pack)

        price = None
        for pr in item.get("prices", []):
            if pr.get("type") == "customer":
                price = pr.get("price")
                break
        if price is None:
            continue

        log.info(
            f"  [{item_status:12s}] pack={gz_pack:<10} | {price} руб | {gz_name[:50]}"
        )

        # IndexNow: фиксируем изменение цены (новая запись или другая цена).
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
                "price": price,
                "search_query": query,
                "search_pass": search_pass,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        matched_ext_ids.add(ext_id)
        saved += 1

    # Удаляем устаревшие записи 36,6 для этого препарата в этом городе.
    if saved > 0 and seen_packs:
        await db.prices_real.delete_many({
            "medication_id": med_id, "source": SOURCE, "city": city,
            "gz_pack": {"$nin": list(seen_packs), "$ne": None},
        })

    log.info(f"[{city}/{slug[:40]:<40}] saved {saved} packs (pass={search_pass})")


async def main(args: argparse.Namespace) -> None:
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    if args.region == "both":
        regions_to_run = REGIONS
    else:
        regions_to_run = [(r, c) for r, c in REGIONS if r == args.region]
    if not regions_to_run:
        log.error(f"Неизвестный регион: {args.region}")
        client_db.close()
        return

    for region, city in regions_to_run:
        log.info(f"=== [366] Регион {region} → city={city} ===")
        query: dict = {"is_canonical": True}
        if args.slug:
            query["slug"] = args.slug
        if args.popular:
            query["mnn"] = {"$in": list(POPULAR_MNN)}
        if args.update_only:
            matched_slugs = await db.prices_real.distinct(
                "slug",
                {"source": SOURCE, "city": city,
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
        log.info(f"[{region}] Препаратов для обработки: {len(meds)}")

        matched_ext_ids: set[str] = set()
        headers = {**HEADERS_BASE, "Flex-Region": f"region={region}"}
        async with httpx.AsyncClient(headers=headers) as client:
            sem = asyncio.Semaphore(CONCURRENCY)
            done = [0]

            async def worker(med):
                async with sem:
                    await process_medication(client, db, med, args.rematch, city, matched_ext_ids)
                    done[0] += 1
                    if done[0] % 100 == 0:
                        log.info(f"[{region}] Прогресс: {done[0]}/{len(meds)}")

            await asyncio.gather(*(worker(m) for m in meds))

    stats = {}
    async for doc in db.prices_real.aggregate([
        {"$match": {"source": SOURCE}},
        {"$group": {"_id": {"city": "$city", "status": "$match_status"}, "count": {"$sum": 1}}},
    ]):
        stats[f"{doc['_id'].get('city','?')}/{doc['_id'].get('status','?')}"] = doc["count"]

    log.info(f"[366] Готово. Статистика: {stats}")

    # IndexNow: slug-и с изменившейся ценой → отдельный файл (не перетираем
    # горздравовский /tmp/indexnow_changed.txt).
    out_path = os.environ.get("INDEXNOW_CHANGED_FILE_366", "/tmp/indexnow_changed_366.txt")
    try:
        with open(out_path, "w") as f:
            for sl in sorted(CHANGED_SLUGS):
                f.write(sl + "\n")
        log.info(f"[366] IndexNow: {len(CHANGED_SLUGS)} изменённых slug-ов -> {out_path}")
    except Exception as e:
        log.warning(f"[366] IndexNow: не смог записать {out_path}: {e}")
    client_db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--slug", type=str, default="")
    parser.add_argument("--popular", action="store_true")
    parser.add_argument("--rematch", action="store_true")
    parser.add_argument("--update-only", action="store_true",
                        help="Обновить только препараты, у которых уже есть матч 36,6 (быстрее).")
    parser.add_argument("--region", type=str, default="both", choices=["MOS", "SPE", "both"],
                        help="Регион: MOS (Москва), SPE (СПб), both — по умолчанию оба.")
    args = parser.parse_args()
    asyncio.run(main(args))
