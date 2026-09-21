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
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from bson.binary import Binary
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

MONGO_URL = os.environ.get("MONGO_URL", "")
DB_NAME = os.environ.get("DB_NAME", "aptekaa")

GZ_BASE = "https://gorzdrav.org"
# Базовые заголовки. Flex-Region проставляется per-region в main().
GZ_HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Flex-Locale": "country=RU;bs=gz.ru",
    "Flex-App": "WEB",
}
# (Горздрав-регион → city-id в нашем приложении).
REGIONS = [
    ("MOS", "msk"),
    ("SPE", "spb"),
]

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

# Сколько препаратов обрабатываем параллельно. При 4 каждый воркер делает
# свои паузы независимо — эффективная нагрузка на Горздрав ~13 req/s (4× от
# sequential ~3.3 req/s). Полный прогон сокращается с ~7ч до ~2ч.
CONCURRENCY = 4

# Фаза наличия: размер батча и пауза для delivery/map/region/detail.
# Эндпоинт тяжёлый на стороне Горздрава (считает наличие по ~1900 аптекам);
# на крупных батчах отдаёт 502/503 — поэтому батч небольшой + ретраи с backoff.
AVAIL_BATCH = 100
AVAIL_DELAY = 3.0
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
    pairs = re.findall(
        r"(\d+(?:[.,]\d+)?)\s*(мг|мкг|г|%|мл|ме|ед)",
        our_dosage.lower(),
    )
    if not pairs:
        return normalize(our_dosage) in normalize(gz_name)
    expected = Counter((number.replace(",", "."), unit) for number, unit in pairs)
    actual = Counter(
        (number.replace(",", "."), unit)
        for number, unit in re.findall(
            r"(?<![\d.])(\d+(?:[.,]\d+)?)(?![\d.])\s*(мг|мкг|г|%|мл|ме|ед)",
            gz_name.lower(),
        )
    )
    return all(actual[pair] >= count for pair, count in expected.items())


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


def curated_pack_matches(med: dict, gz_name: str, gz_pack: str) -> bool:
    """Match a network row to one of the exact user-approved pack variants."""
    actual = extract_pack(gz_pack) or gz_pack
    actual_match = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*([а-яa-z]+)", str(actual), re.I)
    if not actual_match:
        return False
    actual_count = float(actual_match.group(1).replace(",", "."))
    actual_unit = actual_match.group(2).lower()
    title = gz_name.lower().replace(",", ".")
    for variant in med.get("variants") or []:
        label = str(variant.get("pack_size") or "")
        count_match = re.match(r"^\s*(\d+(?:[.,]\d+)?)", label)
        if not count_match:
            continue
        outer_count = float(count_match.group(1).replace(",", "."))
        volume = re.search(r"[×xх]\s*(\d+(?:[.,]\d+)?)\s*(мл|г|мг|мкг)", label, re.I)
        inner_matches_actual = False
        if volume:
            inner_count = float(volume.group(1).replace(",", "."))
            inner_unit = volume.group(2).lower()
            inner_matches_actual = inner_count == actual_count and inner_unit == actual_unit
        if outer_count != actual_count and not inner_matches_actual:
            continue
        if volume:
            number = volume.group(1).replace(",", ".")
            unit = volume.group(2).lower()
            if not re.search(rf"(?<![\d.]){re.escape(number)}(?![\d.])\s*{unit}", title):
                continue
        return True
    return False


def curated_identity_verified(med: dict, item: dict, gz_pack: str, status: str) -> bool:
    if med.get("curated_source") != "priority_medications_2026-09":
        return False
    gz_manufacturer = ""
    for attr in item.get("attributes", []):
        if attr.get("code") == "manufacturer":
            gz_manufacturer = attr.get("value", "")
            break
    # A generic/MNN-named card cannot be tied to the approved manufacturer
    # when the source omits manufacturer data.
    compact_name = re.sub(r"[^a-zа-я0-9]+", "", normalize(med.get("name", "")))
    compact_mnn = re.sub(r"[^a-zа-я0-9]+", "", normalize(med.get("mnn", "")))
    expected_manufacturer = med.get("manufacturer", "")
    if expected_manufacturer and not gz_manufacturer:
        return False
    if not gz_manufacturer and compact_name and compact_name == compact_mnn:
        return False
    return bool(
        status == "matched"
        and name_score(med.get("name", ""), item.get("name", "")) >= NAME_THRESHOLD
        and dosage_matches(med.get("dosage", ""), item.get("name", ""))
        and form_matches(med.get("form", ""), item.get("name", ""))
        and manufacturer_matches(expected_manufacturer, gz_manufacturer)
        and curated_pack_matches(med, item.get("name", ""), gz_pack)
    )


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
    # 3 попытки с backoff: под конкурентной нагрузкой Горздрав иногда
    # отдаёт 429/502/503, ретрай разруливает.
    for attempt in range(3):
        try:
            r = await client.post(
                f"{GZ_BASE}/api/v1/product-search/ext",
                json={"page": 1, "size": SEARCH_SIZE, "filters": {"q": query}},
                timeout=20,
            )
            r.raise_for_status()
            return r.json().get("data", {}).get("result", {}).get("items", [])
        except Exception as e:
            if attempt < 2:
                wait = 1 + attempt * 2
                log.warning(f"search '{query[:40]}' попытка {attempt + 1}/3: {e} — пауза {wait}с")
                await asyncio.sleep(wait)
                continue
            log.warning(f"search error for '{query[:40]}' (после 3 попыток): {e}")
            return []
    return []


def _popcount(b: bytes) -> int:
    return sum(bin(x).count("1") for x in b)


async def refresh_availability(
    client: httpx.AsyncClient, db, ext_ids: list[str], city: str
) -> None:
    """Фаза 2: батчевый запрос наличия по аптекам и запись битовой маски.

    delivery/map/region/detail с emptyStock=False отдаёт список аптек,
    где товар реально есть в текущем регионе (по Flex-Region у клиента).
    Бит i маски store_bitmap взведён, если аптека с idx=i (из gorzdrav_stores)
    имеет товар в продаже (customer > 0). Пишем только в записи нужного city,
    чтобы маски MSK/SPB не перетирали друг друга для одного ext_id.
    """
    if not ext_ids:
        return

    store_idx: dict[str, int] = {}
    max_idx = -1
    async for s in db.gorzdrav_stores.find({}, {"_id": 0, "store_id": 1, "idx": 1}):
        idx = s.get("idx")
        if idx is None:
            continue
        store_idx[s["store_id"]] = idx
        if idx > max_idx:
            max_idx = idx
    if max_idx < 0:
        log.error("gorzdrav_stores без поля idx — сначала запусти import_gorzdrav_stores.py")
        return

    nbytes = (max_idx + 8) // 8
    log.info(
        f"Availability: {len(ext_ids)} ext_id, {len(store_idx)} аптек, маска {nbytes} б"
    )

    updated = 0
    failed = 0
    total_batches = (len(ext_ids) + AVAIL_BATCH - 1) // AVAIL_BATCH
    for i in range(0, len(ext_ids), AVAIL_BATCH):
        batch = ext_ids[i:i + AVAIL_BATCH]
        stores = None
        for attempt in range(5):
            try:
                r = await client.post(
                    f"{GZ_BASE}/api/v1/delivery/map/region/detail",
                    json={"productIds": batch, "emptyStock": False},
                    timeout=120,
                )
                r.raise_for_status()
                stores = r.json().get("stores", [])
                break
            except Exception as e:
                wait = 5 * (2 ** attempt)
                log.warning(
                    f"availability батч @{i} попытка {attempt + 1}/5: {e} — пауза {wait}с"
                )
                await asyncio.sleep(wait)
        if stores is None:
            failed += 1
            log.error(f"availability батч @{i}: не удалось за 5 попыток, пропуск")
            continue

        masks = {eid: bytearray(nbytes) for eid in batch}
        for st in stores:
            idx = store_idx.get(st.get("locationId"))
            if idx is None:
                continue
            byte_i, bit = idx >> 3, idx & 7
            for eid, stk in (st.get("stocks") or {}).items():
                ba = masks.get(eid)
                if ba is not None and (stk or {}).get("customer", 0) > 0:
                    ba[byte_i] |= 1 << bit

        for eid, ba in masks.items():
            observed_at = datetime.now(timezone.utc)
            res = await db.prices_real.update_many(
                {"source": "gorzdrav", "city": city, "gz_ext_id": eid},
                {"$set": {"store_bitmap": Binary(bytes(ba)),
                          "stores_count": _popcount(ba),
                          "availability_observed_at": observed_at}},
            )
            updated += res.modified_count
        log.info(
            f"Availability: батч {i // AVAIL_BATCH + 1}/{total_batches}, "
            f"ext_id {min(i + AVAIL_BATCH, len(ext_ids))}/{len(ext_ids)}"
        )
        await asyncio.sleep(AVAIL_DELAY)

    log.info(
        f"Availability: обновлено записей prices_real: {updated}, "
        f"неудачных батчей: {failed}"
    )


# IndexNow: slug-и препаратов, у которых цена изменилась за прогон.
# В конце main() выгружаются в файл, cron-обёртка шлёт их на IndexNow.
CHANGED_SLUGS: set[str] = set()


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
        {"medication_id": med_id, "source": "gorzdrav", "city": city}
    )
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
        log.info(f"[{city}/not_found]  {slug}")
        await db.prices_real.update_one(
            {"medication_id": med_id, "source": "gorzdrav", "city": city},
            {"$set": {
                "medication_id": med_id, "slug": slug, "source": "gorzdrav", "city": city,
                "match_status": "not_found",
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        return

    if matched_item is None:
        top_name = gz_items[0].get("name", "") if gz_items else ""
        log.info(f"[{city}/no match]   {slug} | top: {top_name[:60]}")
        await db.prices_real.update_one(
            {"medication_id": med_id, "source": "gorzdrav", "city": city},
            {"$set": {
                "medication_id": med_id, "slug": slug, "source": "gorzdrav", "city": city,
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
        gz_manufacturer = ""
        for attr in item.get("attributes", []):
            if attr.get("code") == "manufacturer":
                gz_manufacturer = attr.get("value", "")
                break
        identity_verified = curated_identity_verified(med, item, gz_pack, item_status)

        # Наличие по аптекам (store_bitmap / stores_count) заполняется
        # позже батчем в refresh_availability — здесь только фиксируем ext_id.
        log.info(
            f"  [{item_status:12s}] pack={gz_pack:<10} | {price} руб | {gz_name[:50]}"
        )

        # IndexNow: фиксируем изменение цены (новая запись или другая цена).
        _prev = await db.prices_real.find_one(
            {"medication_id": med_id, "source": "gorzdrav", "city": city, "gz_pack": gz_pack},
            {"_id": 0, "price": 1},
        )
        if _prev is None or _prev.get("price") != price:
            CHANGED_SLUGS.add(slug)

        await db.prices_real.update_one(
            {"medication_id": med_id, "source": "gorzdrav", "city": city, "gz_pack": gz_pack},
            {"$set": {
                "medication_id": med_id,
                "slug": slug,
                "source": "gorzdrav",
                "city": city,
                "gz_pack": gz_pack,
                "match_status": item_status,
                "gz_ext_id": ext_id,
                "gz_name": gz_name,
                "gz_manufacturer": gz_manufacturer,
                "price": price,
                "search_query": query,
                "search_pass": search_pass,
                "identity_verified": identity_verified,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        matched_ext_ids.add(ext_id)
        saved += 1

    # Удаляем устаревшие записи Горздрав для этого препарата в этом городе
    # (упаковки, которых больше нет в выдаче региона).
    if saved > 0 and seen_packs:
        await db.prices_real.delete_many({
            "medication_id": med_id, "source": "gorzdrav", "city": city,
            "gz_pack": {"$nin": list(seen_packs), "$ne": None},
        })
        # Также удаляем старую запись без gz_pack (legacy format)
        await db.prices_real.delete_many({
            "medication_id": med_id, "source": "gorzdrav", "city": city,
            "gz_pack": {"$exists": False},
            "match_status": {"$in": ["matched", "needs_review", "mnn_match"]},
        })

    log.info(f"[{city}/{slug[:40]:<40}] saved {saved} packs (pass={search_pass})")


async def main(args: argparse.Namespace) -> None:
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    # Какие регионы прогонять.
    if args.region == "both":
        regions_to_run = REGIONS
    else:
        regions_to_run = [(r, c) for r, c in REGIONS if r == args.region]
    if not regions_to_run:
        log.error(f"Неизвестный регион: {args.region}")
        client_db.close()
        return

    # Режим только наличия: пропускаем перематчинг, обновляем store_bitmap
    # для всех уже сматченных упаковок. Быстро (только батчи availability).
    if args.availability_only:
        for region, city in regions_to_run:
            ext_ids = await db.prices_real.distinct("gz_ext_id", {
                "source": "gorzdrav",
                "city": city,
                "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
                "gz_ext_id": {"$ne": None},
                "price": {"$ne": None},
            })
            headers = {**GZ_HEADERS_BASE, "Flex-Region": f"region={region}"}
            async with httpx.AsyncClient(headers=headers) as client:
                log.info(f"=== availability-only: {region} → city={city}, {len(ext_ids)} ext_id ===")
                await refresh_availability(client, db, sorted(ext_ids), city)
        client_db.close()
        return

    for region, city in regions_to_run:
        log.info(f"=== Регион {region} → city={city} ===")
        query: dict = {"is_canonical": True}
        if args.curated_source:
            query["curated_source"] = args.curated_source
        if args.slug:
            query["slug"] = args.slug
        if args.popular:
            query["mnn"] = {"$in": list(POPULAR_MNN)}
        if args.update_only:
            # Берём slug-и, у которых уже есть успешный матч ИМЕННО в этом городе.
            matched_slugs = await db.prices_real.distinct(
                "slug",
                {"source": "gorzdrav", "city": city,
                 "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
                 "price": {"$ne": None}},
            )
            query["slug"] = {"$in": matched_slugs}
            args.rematch = True

        cursor = db.medications.find(query, {
            "name": 1, "dosage": 1, "form": 1, "manufacturer": 1, "slug": 1, "mnn": 1,
            "variants": 1, "curated_source": 1,
        })
        if args.limit:
            cursor = cursor.limit(args.limit)

        meds = await cursor.to_list(length=None)
        log.info(f"[{region}] Препаратов для обработки: {len(meds)}")

        matched_ext_ids: set[str] = set()
        headers = {**GZ_HEADERS_BASE, "Flex-Region": f"region={region}"}
        async with httpx.AsyncClient(headers=headers) as client:
            # Параллельная обработка препаратов с семафором (CONCURRENCY воркеров).
            # search/Mongo I/O-bound, GIL не мешает; ретраи в search_gorzdrav
            # разруливают возможные 429 под нагрузкой.
            sem = asyncio.Semaphore(CONCURRENCY)
            done = [0]

            async def worker(med):
                async with sem:
                    await process_medication(client, db, med, args.rematch, city, matched_ext_ids)
                    done[0] += 1
                    if done[0] % 100 == 0:
                        log.info(f"[{region}] Прогресс: {done[0]}/{len(meds)}")

            await asyncio.gather(*(worker(m) for m in meds))

            await refresh_availability(client, db, sorted(matched_ext_ids), city)

    stats = {}
    async for doc in db.prices_real.aggregate([
        {"$match": {"source": "gorzdrav"}},
        {"$group": {"_id": {"city": "$city", "status": "$match_status"}, "count": {"$sum": 1}}},
    ]):
        stats[f"{doc['_id'].get('city','?')}/{doc['_id'].get('status','?')}"] = doc["count"]

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
    parser.add_argument("--curated-source", type=str, default="",
                        help="Обработать только карточки из указанной курируемой подборки.")
    parser.add_argument("--popular", action="store_true")
    parser.add_argument("--rematch", action="store_true")
    parser.add_argument("--update-only", action="store_true",
                        help="Обновить только препараты, для которых уже есть Горздрав-матчи (быстрее).")
    parser.add_argument("--availability-only", action="store_true",
                        help="Только наличие по аптекам (store_bitmap) для сматченных упаковок, без перематчинга.")
    parser.add_argument("--region", type=str, default="both", choices=["MOS", "SPE", "both"],
                        help="Регион Горздрав: MOS (Москва), SPE (СПб), both — по умолчанию оба.")
    args = parser.parse_args()
    asyncio.run(main(args))
