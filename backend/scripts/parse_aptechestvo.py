"""
Парсер цен «Аптечество» (aptechestvo.ru) → коллекция prices_real, source="aptechestvo".

Аптечество — 2-й источник цен для Нижнего Новгорода (city="nn"), в дополнение к
Максавиту. Сеть Поволжья (НН/Владимир/Киров/Йошкар-Ола/Москва), входит в группу
Протек/Ригла (email аптек @rigla.ru), но это отдельный сайт на Bitrix.

Главный сайт под Qrator нам не нужен — товары отдаёт AJAX-эндпоинт быстрого
поиска (автокомплит), открытый и без авторизации:

    GET https://aptechestvo.ru/ajax/new_app/speedSearch.php?q=<имя>
    → HTML-фрагмент: до ~10 товаров, у каждого:
        <div class="row mb-3 speed-srarch-wrap">
          ...<a href="/catalog/<slug>/"></a>          # slug = стабильный ID
          <div class="product-title ..."><a ...>TITLE</a></div>   # с фасовкой
          <div class="product-prices ..."><div class="curent-price">726.00 ...

Регион = Нижний Новгород ПО УМОЛЧАНИЮ (getRegions: PROPERTY_DEFAULT_VALUE:"Y"
для г. Нижний Новгород; главная для нашего IP показывает «Ваш город — Нижний
Новгород»). Отдельный city-cookie не требуется.

Матчинг переиспользуется из parse_gorzdrav (match_product[s] / extract_pack) —
как у Ригла/Максавита. Производитель из автокомплита недоступен → attributes
пустые → статусы "needs_review"/"mnn_match" (валидно отображаемые).

КЛЮЧЕВОЕ ОГРАНИЧЕНИЕ: сохраняем ТОЛЬКО позиции, уже существующие в нашем
каталоге medications (через match_products). Новые SKU не заводим.

ЭТАП 1 (этот файл): матчинг + цена по НН → «сравнение цен» 2 сетей (Максавит +
Аптечество). Карта наличия по аптекам — НЕ реализуется (как было у 36,6 на
Этапе 1): seed-аптека без координат, маркеров на карте нет.

Запуск:
    python -m scripts.parse_aptechestvo                 # все канонические, nn
    python -m scripts.parse_aptechestvo --limit 100
    python -m scripts.parse_aptechestvo --slug nurofen-ekspress-kapsuly-200-mg
    python -m scripts.parse_aptechestvo --popular
    python -m scripts.parse_aptechestvo --from-gorzdrav # только слаги с матчем Горздрава
    python -m scripts.parse_aptechestvo --update-only   # только препараты с матчем Аптечество
    python -m scripts.parse_aptechestvo --rematch       # перематчить уже сматченные
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
CITY = "nn"  # Аптечество парсим для Нижнего Новгорода (дефолтный регион сайта)
SEARCH_URL = "https://aptechestvo.ru/ajax/new_app/speedSearch.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://aptechestvo.ru/",
}

# slug-и с изменившейся ценой Аптечество — для IndexNow.
CHANGED_SLUGS: set[str] = set()

# --- Парсинг HTML-фрагмента speedSearch ---
# Каждый товар — блок с маркером "speed-srarch-wrap"; режем по нему.
_ITEM_RE = re.compile(r'speed-srarch-wrap(.*?)(?=speed-srarch-wrap|$)', re.S)
_HREF_RE = re.compile(r'href="(/catalog/[^"?#]+?/)"')
_TITLE_RE = re.compile(r'product-title.*?<a[^>]*>(.*?)</a>', re.S)
_PRICE_RE = re.compile(r'curent-price"\s*>\s*([\d]+(?:[.,]\d+)?)')
_TAG_RE = re.compile(r'<[^>]+>')

# Аптечество кладёт фасовку в title/slug: «… 200 мг, 40 шт» / slug «…_40_sht».
# extract_pack Горздрава ловит хвостовые «N шт»/«N мл». Доп. fallback по slug:
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
    """HTML-фрагмент speedSearch → список листингов в форме для матчинга
    (name + attributes), как ждёт match_product Горздрава."""
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


async def search_aptechestvo(client: httpx.AsyncClient, query: str) -> list[dict]:
    """GET speedSearch.php?q=, 3 попытки с backoff."""
    for attempt in range(3):
        try:
            r = await client.get(SEARCH_URL, params={"q": query}, timeout=25)
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
    items = await search_aptechestvo(client, query)
    await asyncio.sleep(REQUEST_DELAY)
    items2: list[dict] = []

    matched_item, status = match_product(med, items)
    search_pass = "name"

    # Проход 2: по МНН, если по имени не нашли.
    if matched_item is None and mnn and mnn.lower() not in name.lower():
        mnn_query = f"{mnn.lower()} {dosage}".strip()
        items2 = await search_aptechestvo(client, mnn_query)
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

    # Удаляем устаревшие упаковки Аптечества для этого препарата.
    if saved > 0 and seen_packs:
        await db.prices_real.delete_many({
            "medication_id": med_id, "source": SOURCE, "city": CITY,
            "gz_pack": {"$nin": list(seen_packs), "$ne": None},
        })

    log.info(f"[{CITY}/{slug[:40]:<40}] saved {saved} packs (pass={search_pass})")


async def main(args: argparse.Namespace) -> None:
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    log.info(f"=== [aptechestvo] city={CITY} (Нижний Новгород) ===")

    query: dict = {"is_canonical": True}
    if args.slug:
        query["slug"] = args.slug
    if args.popular:
        query["mnn"] = {"$in": list(POPULAR_MNN)}
    if args.from_gorzdrav:
        # Узкий набор: только препараты с уже существующим матчем Горздрава.
        # Каталог общий, ×N меньше работы, ровно SEO-значимые страницы.
        gz_slugs = await db.prices_real.distinct(
            "slug",
            {"source": "gorzdrav",
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

    log.info(f"[aptechestvo] Готово. Статистика: {stats}")

    # IndexNow: slug-и с изменившейся ценой → отдельный файл.
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
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--slug", type=str, default="")
    parser.add_argument("--popular", action="store_true")
    parser.add_argument("--from-gorzdrav", action="store_true",
                        help="Только препараты с уже существующим матчем Горздрава.")
    parser.add_argument("--update-only", action="store_true",
                        help="Обновить только препараты с уже существующим матчем Аптечество.")
    parser.add_argument("--rematch", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args))
