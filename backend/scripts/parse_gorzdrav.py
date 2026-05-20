"""
Парсер цен и наличия с gorzdrav.org.

Для каждого препарата из коллекции medications:
  1. Ищем совпадение в Горздрав по названию + дозировке
  2. Если не нашли — ищем по МНН + дозировке (второй проход)
  3. Проверяем производителя (с транслитерацией и нормализацией)
  4. Сохраняем цену и кол-во аптек в коллекцию prices_real

Запуск:
    python -m scripts.parse_gorzdrav              # все препараты
    python -m scripts.parse_gorzdrav --limit 100  # первые 100
    python -m scripts.parse_gorzdrav --popular     # только популярные MNN
    python -m scripts.parse_gorzdrav --slug nurofen-200-mg-tabletki
    python -m scripts.parse_gorzdrav --rematch     # перематчить даже уже сматченные
"""
from __future__ import annotations

import os
import sys
import asyncio
import argparse
import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "aptekaa")

GZ_BASE = "https://gorzdrav.org"
GZ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Flex-Locale": "country=RU;bs=gz.ru",
    "Flex-Region": "region=MOS",
    "Flex-App": "WEB",
}

POPULAR_MNN = {
    "ПАРАЦЕТАМОЛ", "ИБУПРОФЕН", "АЦЕТИЛСАЛИЦИЛОВАЯ КИСЛОТА",
    "ОМЕПРАЗОЛ", "ЛОРАТАДИН", "ЦЕТИРИЗИН", "ХЛОРОПИРАМИН",
    "ДРОТАВЕРИН", "МЕТАМИЗОЛ НАТРИЯ", "КЕТОПРОФЕН",
    "ЛОПЕРАМИД", "СМЕКТИТ ДИОКТАЭДРИЧЕСКИЙ",
    "АМБРОКСОЛ", "БРОМГЕКСИН", "АЦЕТИЛЦИСТЕИН",
    "АМОКСИЦИЛЛИН", "АЗИТРОМИЦИН", "ЦИПРОФЛОКСАЦИН",
    "МЕТРОНИДАЗОЛ", "ФЛУКОНАЗОЛ",
    "КОЛЕКАЛЬЦИФЕРОЛ", "АСКОРБИНОВАЯ КИСЛОТА",
    "МАГНИЯ ЛАКТАТ", "МАГНИЯ ЦИТРАТ", "МЕЛЬДОНИЙ",
    "ФУРОСЕМИД", "ЭНАЛАПРИЛ", "ЛОЗАРТАН", "АМЛОДИПИН",
    "БИСОПРОЛОЛ", "МЕТОПРОЛОЛ",
    "ГЛИЦИН", "МЕЛАТОНИН",
    "НИМЕСУЛИД", "ДИКЛОФЕНАК",
    "АНАСТРОЗОЛ", "ТАМОКСИФЕН",
    "ИНСУЛИН ГЛАРГИН", "МЕТФОРМИН",
    "АМИОДАРОН", "ВАРФАРИН", "ГЕПАРИН НАТРИЯ",
    "СУМАТРИПТАН", "БЕТАГИСТИН",
    "АТОРВАСТАТИН", "РОЗУВАСТАТИН", "СИМВАСТАТИН",
    "КЕТОТИФЕН", "ДЕЗЛОРАТАДИН",
    "ИВЕРМЕКТИН", "ОСЕЛЬТАМИВИР", "АЦИКЛОВИР",
    "УМИФЕНОВИР", "РИБАВИРИН",
    "ЭСОМЕПРАЗОЛ", "ПАНТОПРАЗОЛ", "ФАМОТИДИН",
    "ДОМПЕРИДОН", "МЕТОКЛОПРАМИД",
    "СПИРОНОЛАКТОН", "ИНДАПАМИД",
}

REQUEST_DELAY = 0.3
NAME_THRESHOLD = 0.72
SEARCH_SIZE = 20

FORM_KEYWORDS: dict[str, list[str]] = {
    "таблетки": ["таблетк"],
    "капсулы": ["капсул"],
    "суспензия": ["суспензи"],
    "суппозитории": ["суппозитори"],
    "гель": ["гель", "геля"],
    "мазь": ["мазь", "мази"],
    "крем": ["крем"],
    "раствор": ["раствор"],
    "капли": ["капли", "капель"],
    "спрей": ["спрей"],
    "порошок": ["порошок"],
    "сироп": ["сироп"],
    "аэрозоль": ["аэрозоль"],
    "лиофилизат": ["лиофилизат"],
    "концентрат": ["концентрат"],
    "ампулы": ["ампул"],
    "пластырь": ["пластырь"],
}

# Транслитерация Кириллица → Латиница для сравнения производителей
_CYR_TO_LAT = str.maketrans({
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd',
    'е': 'e', 'ё': 'e', 'ж': 'zh', 'з': 'z', 'и': 'i',
    'й': 'i', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
    'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't',
    'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch',
    'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '',
    'э': 'e', 'ю': 'yu', 'я': 'ya',
})

# Юридические суффиксы которые не несут смысловой нагрузки при сравнении
_LEGAL_SUFFIX_RE = re.compile(
    r'\b(ag|ltd|llc|gmbh|inc|corp|sa|bv|nv|oy|ab|as|plc|co'
    r'|ооо|оао|зао|пао|ао|нпо|нпк|нпф|фгуп|гуп)\b',
    re.I,
)

# Символ "+" в GZ-названии означает комбо-препарат
_COMBO_RE = re.compile(r'\+')


def normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[«»""''\-–—]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_manufacturer(s: str) -> str:
    """Нормализация производителя: юр.суффиксы, транслитерация, только латиница."""
    s = s.lower()
    s = _LEGAL_SUFFIX_RE.sub(' ', s)
    s = s.translate(_CYR_TO_LAT)
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def manufacturer_matches(our_mfr: str, gz_mfr: str) -> bool:
    """
    Сравниваем производителей с учётом транслитерации и юр.суффиксов.
    Примеры: 'Байер' == 'Bayer AG', 'Pfizer' == 'Пфайзер Мануфэкчуринг'.
    """
    if not our_mfr or not gz_mfr:
        return True
    a = normalize_manufacturer(our_mfr)
    b = normalize_manufacturer(gz_mfr)
    if not a or not b:
        return True
    # Общие токены → точный матч
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if a_tokens & b_tokens:
        return True
    # Иначе — нечёткое сравнение всей строки (ловит baier/bayer, pfaizer/pfizer)
    return SequenceMatcher(None, a, b).ratio() >= 0.72


def token_set(s: str) -> set[str]:
    return {w for w in re.split(r"[\s\-/+,]+", normalize(s)) if len(w) > 1}


def name_score(our_name: str, gz_name: str) -> float:
    our_tokens = token_set(our_name)
    gz_tokens = token_set(gz_name)
    if not our_tokens:
        return 0.0
    return len(our_tokens & gz_tokens) / len(our_tokens)


def dosage_matches(our_dosage: str, gz_name: str) -> bool:
    if not our_dosage:
        return True
    d = re.sub(r"(\d)(мг|мкг|г|%|мл|ме|ед)", r"\1 \2", our_dosage.lower())
    d = re.sub(r"\s+", " ", d).strip()
    gz_lower = gz_name.lower()
    first_part = re.split(r"[+/]", d)[0].strip()
    number = re.search(r"[\d\.,]+", first_part)
    unit = re.search(r"[а-яё%]+", first_part)
    if number and unit:
        return number.group() in gz_lower and unit.group() in gz_lower
    return first_part in gz_lower


def form_matches(our_form: str, gz_name: str) -> bool:
    if not our_form:
        return True
    our_form_lower = our_form.lower()
    gz_lower = gz_name.lower()
    for form_key, gz_keywords in FORM_KEYWORDS.items():
        if form_key in our_form_lower:
            return any(kw in gz_lower for kw in gz_keywords)
    return True


def is_combo(gz_name: str) -> bool:
    """Горздрав-название содержит '+' → это комбо-препарат."""
    return bool(_COMBO_RE.search(gz_name))


_PACK_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(шт|мл|мкг|мг|г|л)\.?\s*$", re.IGNORECASE)


def extract_pack(gz_name: str) -> str | None:
    """
    Вытягиваем размер упаковки из конца имени Горздрав.
    'Лосек Мапс ... 28 шт' -> '28 шт', 'Капли ... 0,25 г 6 шт' -> '6 шт'
    """
    if not gz_name:
        return None
    m = _PACK_RE.search(gz_name)
    if not m:
        return None
    qty = m.group(1).replace(",", ".")
    if "." in qty:
        qty = qty.rstrip("0").rstrip(".")
    return f"{qty} {m.group(2).lower()}"


def match_products(
    med: dict,
    gz_items: list[dict],
    allow_combo: bool = False,
) -> list[tuple[dict, str]]:
    """Все листинги, прошедшие фильтры. Дедуп по extId на стороне вызова."""
    our_name = med.get("name", "")
    our_dosage = med.get("dosage", "")
    our_form = med.get("form", "")
    our_manufacturer = med.get("manufacturer", "")
    our_is_combo = "+" in our_name
    out: list[tuple[dict, str]] = []
    for item in gz_items:
        gz_name = item.get("name", "")
        if not allow_combo:
            if is_combo(gz_name) and not our_is_combo: continue
            if not is_combo(gz_name) and our_is_combo: continue
        if name_score(our_name, gz_name) < NAME_THRESHOLD: continue
        if not form_matches(our_form, gz_name): continue
        if not dosage_matches(our_dosage, gz_name): continue
        gz_manufacturer = ""
        for attr in item.get("attributes", []):
            if attr.get("code") == "manufacturer":
                gz_manufacturer = attr.get("value", "")
                break
        status = "matched" if manufacturer_matches(our_manufacturer, gz_manufacturer) else "needs_review"
        out.append((item, status))
    return out


def match_product(
    med: dict,
    gz_items: list[dict],
    allow_combo: bool = False,
) -> tuple[dict | None, str | None]:
    """Старая обёртка: лучший по score. Оставлена для not_found-веток."""
    our_name = med.get("name", "")
    our_dosage = med.get("dosage", "")
    our_form = med.get("form", "")
    our_manufacturer = med.get("manufacturer", "")
    our_is_combo = "+" in our_name

    best_item = None
    best_score = 0.0
    best_status = None

    for item in gz_items:
        gz_name = item.get("name", "")

        # Комбо-фильтр: не матчим одиночный препарат с комбо и наоборот
        if not allow_combo:
            if is_combo(gz_name) and not our_is_combo:
                continue
            if not is_combo(gz_name) and our_is_combo:
                continue

        score = name_score(our_name, gz_name)
        if score < NAME_THRESHOLD:
            continue

        if not form_matches(our_form, gz_name):
            continue

        if not dosage_matches(our_dosage, gz_name):
            continue

        gz_manufacturer = ""
        for attr in item.get("attributes", []):
            if attr.get("code") == "manufacturer":
                gz_manufacturer = attr.get("value", "")
                break

        mfr_ok = manufacturer_matches(our_manufacturer, gz_manufacturer)
        status = "matched" if mfr_ok else "needs_review"

        if score > best_score:
            best_score = score
            best_item = item
            best_status = status

    return best_item, best_status


async def search_gorzdrav(client: httpx.AsyncClient, query: str) -> list[dict]:
    try:
        r = await client.post(
            f"{GZ_BASE}/api/v1/product-search/ext",
            json={"page": 1, "size": SEARCH_SIZE, "filters": {"q": query}},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("result", {}).get("items", [])
    except Exception as e:
        log.warning(f"search error for '{query}': {e}")
        return []


async def get_stores_quantity(client: httpx.AsyncClient, ext_id: str) -> int:
    try:
        r = await client.post(
            f"{GZ_BASE}/api/v2/stock/region/getStoresQuantity",
            json={"productIds": [ext_id]},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if data and isinstance(data, list):
            return data[0].get("storesQuantity", 0)
    except Exception as e:
        log.warning(f"stock error for extId={ext_id}: {e}")
    return 0


# IndexNow: slug-и препаратов, у которых цена изменилась за прогон.
# В конце main() выгружаются в файл, cron-обёртка шлёт их на IndexNow.
CHANGED_SLUGS: set[str] = set()


async def process_medication(
    client: httpx.AsyncClient,
    db,
    med: dict,
    rematch: bool,
) -> None:
    med_id = med["_id"]
    slug = med.get("slug", str(med_id))
    name = med.get("name", "")
    dosage = med.get("dosage", "")
    mnn = med.get("mnn", "")

    existing = await db.prices_real.find_one({"medication_id": med_id, "source": "gorzdrav"})
    if existing and not rematch:
        log.debug(f"skip (already matched): {slug}")
        return

    # Проход 1: поиск по бренд-названию (без дозировки — Горздрав сужает выдачу
    # слишком агрессивно, теряя варианты упаковок. Дозировка проверяется
    # потом через dosage_matches на возвращённых листингах).
    query = name.strip()
    gz_items = await search_gorzdrav(client, query)
    await asyncio.sleep(REQUEST_DELAY)
    gz_items2 = []

    matched_item, status = match_product(med, gz_items)
    search_pass = "name"

    # Проход 2: если не нашли — ищем по МНН (если он отличается от имени)
    if matched_item is None and mnn and mnn.lower() not in name.lower():
        mnn_query = f"{mnn.lower()} {dosage}".strip()
        gz_items2 = await search_gorzdrav(client, mnn_query)
        await asyncio.sleep(REQUEST_DELAY)
        # При MNN-поиске разрешаем комбо (МНН может быть общим)
        matched_item, status = match_product(med, gz_items2, allow_combo=False)
        if matched_item:
            search_pass = "mnn"
            # МНН-матч — помечаем как needs_review если был matched (менее уверен)
            if status == "matched":
                status = "mnn_match"

    if not gz_items and (not mnn or mnn.lower() in name.lower()):
        log.info(f"[not_found]  {slug}")
        await db.prices_real.update_one(
            {"medication_id": med_id, "source": "gorzdrav"},
            {"$set": {
                "medication_id": med_id, "slug": slug, "source": "gorzdrav",
                "match_status": "not_found",
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return

    if matched_item is None:
        top_name = gz_items[0].get("name", "") if gz_items else ""
        log.info(f"[no match]   {slug} | top: {top_name[:60]}")
        await db.prices_real.update_one(
            {"medication_id": med_id, "source": "gorzdrav"},
            {"$set": {
                "medication_id": med_id, "slug": slug, "source": "gorzdrav",
                "match_status": "no_match",
                "search_query": query,
                "gz_top_candidate": top_name,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return

    # Получаем ВСЕ листинги, прошедшие фильтры (для разных упаковок).
    # При single-match режиме gz_items уже был выбран match_product (best),
    # поэтому ищем все варианты в исходном списке gz_items, на котором был matched_item.
    if search_pass == "name":
        all_matches = match_products(med, gz_items, allow_combo=False)
    else:
        all_matches = match_products(med, gz_items2, allow_combo=False)
        all_matches = [(it, "mnn_match" if st == "matched" else st) for (it, st) in all_matches]

    if not all_matches:
        # fallback на старое поведение если match_products почему-то ничего не нашёл
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

        stores_count = await get_stores_quantity(client, ext_id)
        await asyncio.sleep(REQUEST_DELAY)

        log.info(
            f"  [{item_status:12s}] pack={gz_pack:<10} | {price} руб | {stores_count} аптек | {gz_name[:50]}"
        )

        # IndexNow: фиксируем изменение цены (новая запись или другая цена).
        _prev = await db.prices_real.find_one(
            {"medication_id": med_id, "source": "gorzdrav", "gz_pack": gz_pack},
            {"_id": 0, "price": 1},
        )
        if _prev is None or _prev.get("price") != price:
            CHANGED_SLUGS.add(slug)

        await db.prices_real.update_one(
            {"medication_id": med_id, "source": "gorzdrav", "gz_pack": gz_pack},
            {"$set": {
                "medication_id": med_id,
                "slug": slug,
                "source": "gorzdrav",
                "gz_pack": gz_pack,
                "match_status": item_status,
                "gz_ext_id": ext_id,
                "gz_name": gz_name,
                "price": price,
                "stores_count": stores_count,
                "search_query": query,
                "search_pass": search_pass,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        saved += 1

    # Удаляем устаревшие записи Горздрав для этого препарата
    # (упаковки, которых больше нет в выдаче).
    if saved > 0 and seen_packs:
        await db.prices_real.delete_many({
            "medication_id": med_id, "source": "gorzdrav",
            "gz_pack": {"$nin": list(seen_packs), "$ne": None},
        })
        # Также удаляем старую запись без gz_pack (legacy format)
        await db.prices_real.delete_many({
            "medication_id": med_id, "source": "gorzdrav",
            "gz_pack": {"$exists": False},
            "match_status": {"$in": ["matched", "needs_review", "mnn_match"]},
        })

    log.info(f"[{slug[:40]:<40}] saved {saved} packs (pass={search_pass})")


async def main(args: argparse.Namespace) -> None:
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    query: dict = {"is_canonical": True}
    if args.slug:
        query["slug"] = args.slug
    if args.popular:
        query["mnn"] = {"$in": list(POPULAR_MNN)}
    if args.update_only:
        # Берём slug-и тех препаратов, для которых уже есть успешный матч.
        matched_slugs = await db.prices_real.distinct(
            "slug",
            {"source": "gorzdrav",
             "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
             "price": {"$ne": None}},
        )
        query["slug"] = {"$in": matched_slugs}
        # В update-only всегда нужен rematch (иначе пропустит уже сматченные)
        args.rematch = True

    cursor = db.medications.find(query, {
        "name": 1, "dosage": 1, "form": 1, "manufacturer": 1, "slug": 1, "mnn": 1,
    })
    if args.limit:
        cursor = cursor.limit(args.limit)

    meds = await cursor.to_list(length=None)
    log.info(f"Препаратов для обработки: {len(meds)}")

    async with httpx.AsyncClient(headers=GZ_HEADERS) as client:
        for i, med in enumerate(meds, 1):
            if i % 100 == 0:
                log.info(f"Прогресс: {i}/{len(meds)}")
            await process_medication(client, db, med, args.rematch)

    stats = {}
    async for doc in db.prices_real.aggregate([
        {"$match": {"source": "gorzdrav"}},
        {"$group": {"_id": "$match_status", "count": {"$sum": 1}}},
    ]):
        stats[doc["_id"]] = doc["count"]

    log.info(f"Готово. Статистика: {stats}")

    # IndexNow: выгружаем slug-и с изменившейся ценой для последующей отправки.
    out_path = os.environ.get("INDEXNOW_CHANGED_FILE", "/tmp/indexnow_changed.txt")
    try:
        with open(out_path, "w") as f:
            for sl in sorted(CHANGED_SLUGS):
                f.write(sl + "\n")
        log.info(f"IndexNow: {len(CHANGED_SLUGS)} изменённых slug-ов -> {out_path}")
    except Exception as e:
        log.warning(f"IndexNow: не смог записать {out_path}: {e}")
    client_db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--slug", type=str, default="")
    parser.add_argument("--popular", action="store_true")
    parser.add_argument("--rematch", action="store_true")
    parser.add_argument("--update-only", action="store_true",
                        help="Обновить только препараты, для которых уже есть Горздрав-матчи (быстрее).")
    args = parser.parse_args()
    asyncio.run(main(args))
