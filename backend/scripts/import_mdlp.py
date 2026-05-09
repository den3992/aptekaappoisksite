"""
ETL: import the official Russian medications registry (mdlp.crpt.ru) into MongoDB.

Source: /app/backend/data/mdlp_lp_registry.xlsx
        72k rows, 30 columns, one row per GTIN/SKU.

Strategy:
  1. Stream the XLSX row by row (read_only=True), normalize Russian columns to
     ASCII keys, push into `medications_raw` collection (one doc per GTIN).
  2. Group rows by trade name + manufacturer + dosage to build "card-ready"
     `medications` collection (one doc per merchandisable drug card with
     a `variants[]` array of pack sizes / GTINs).
  3. Build a small `mnn_index` mapping MNN → list of medication slugs
     for the "analogs" feature.
  4. Create the indexes the search/detail APIs need.

Usage (locally):
    python -m scripts.import_mdlp           # full import (drops & rebuilds)
    python -m scripts.import_mdlp --dry     # parse only, no DB writes
    python -m scripts.import_mdlp --limit 1000

Idempotent: re-running drops the three collections and rebuilds.
"""
from __future__ import annotations

import os
import re
import sys
import time
import argparse
from pathlib import Path
from typing import Dict, Optional, List, Iterable

import openpyxl
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, TEXT
from pymongo.errors import BulkWriteError

ROOT = Path(__file__).resolve().parents[1]  # /app/backend
load_dotenv(ROOT / ".env")

XLSX_PATH = ROOT / "data" / "mdlp_lp_registry.xlsx"

# Column index → ascii key. Order from the file header (verified).
COLS = {
    0: "gtin",
    1: "esklp_code",
    2: "drug_code_version",
    3: "ru_number",
    4: "ru_date",
    5: "trade_name",
    6: "mnn_std",
    7: "mnn_norm",
    8: "label_name",
    9: "vzn",                       # высокозатратные нозологии Yes/No
    10: "vital",                    # ЖНВЛП Yes/No
    11: "narcotic",                 # Наркотические/Психотропные Yes/No
    12: "limit_price",              # ПОЦ, руб.
    13: "form_std",
    14: "form_norm",
    15: "dosage_std",
    16: "dosage_norm",
    17: "primary_pack",
    18: "primary_mass",
    19: "primary_unit",
    20: "substance_qty",
    21: "substance_unit",
    22: "primary_pack_desc",
    23: "primary_in_consumer_qty",
    24: "manufacturer",
    25: "manufacturer_country",
    26: "tn_ved_code",
    27: "manufacturer_contact",     # noisy field, drop on import
    28: "completeness",
    29: "pku",                      # ПКУ Yes/No
}

# Translit table (GOST‑ish, optimized for slugs).
_RU_LATIN = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
)


def slugify(*parts: Optional[str]) -> str:
    """Build a SEO-friendly latin slug like 'nayz-100mg-tabletki-20sht'."""
    text = " ".join([p for p in parts if p]).lower().strip()
    text = text.translate(_RU_LATIN)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:120] or "med"


def yn_to_bool(v) -> bool:
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("да", "yes", "true", "1")


def clean_str(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def to_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except Exception:
        return None


def is_rx(row: Dict) -> bool:
    """A drug is "Отпускается по рецепту" if it's narcotic/PKU OR a vital‑VZN
    drug OR a clearly Rx form (injections / infusions). This is a *sane default*;
    real Rx flag in mdlp is implicit and we err on the side of caution."""
    if yn_to_bool(row.get("narcotic")) or yn_to_bool(row.get("pku")):
        return True
    if yn_to_bool(row.get("vzn")):
        return True
    form = (row.get("form_std") or "").upper()
    rx_keywords = (
        "ИНЪЕКЦ", "ИНФУЗ", "ЛИОФИЛИЗАТ", "ИМПЛАНТ", "ВНУТРИВЕН", "ВНУТРИМЫШЕЧ",
        "ИНТРАТЕКАЛ", "СУБКОНЪЮНКТ", "ИНТРАВИТ",
    )
    return any(k in form for k in rx_keywords)


# Maps MNN keyword → category slug. We only mark drugs we recognise; the rest
# stay in "other" until LLM enrichment fills the gap.
CATEGORY_RULES: List[tuple] = [
    # (set of substrings to match in MNN, category_slug)
    (("ПАРАЦЕТАМОЛ", "ИБУПРОФЕН", "НИМЕСУЛИД", "ДИКЛОФЕНАК", "КЕТОРОЛАК",
      "АНАЛЬГИН", "МЕТАМИЗОЛ", "НАПРОКСЕН", "АСПИРИН", "АЦЕТИЛСАЛИЦИЛ"),
     "obezbolivayuschie"),
    (("УМИФЕНОВИР", "ОСЕЛЬТАМИВИР", "КАГОЦЕЛ", "ИНТЕРФЕРОН",
      "АМБРОКСОЛ", "БРОМГЕКСИН", "АЦЕТИЛЦИСТЕИН", "КСИЛОМЕТАЗОЛИН",
      "ОКСИМЕТАЗОЛИН", "ФЕНИЛЭФРИН", "АЛТЕЯ", "ТЕРМОПСИС",
      "РЕМАНТАДИН", "ЭРГОФЕРОН", "АНАФЕРОН"), "ot-prostudy"),
    (("ВИТАМИН", "АСКОРБИНОВАЯ", "КОЛЕКАЛЬЦИФЕРОЛ", "ХОЛЕКАЛЬЦИФЕРОЛ",
      "ТОКОФЕРОЛ", "ЦИАНОКОБАЛАМИН", "ПИРИДОКСИН", "ТИАМИН",
      "РЫБИЙ ЖИР", "ОМЕГА", "МАГНИЯ", "КАЛЬЦИЯ", "ЦИНК"), "vitaminy-bady"),
    (("ОМЕПРАЗОЛ", "РАБЕПРАЗОЛ", "ПАНТОПРАЗОЛ", "ЛАНЗОПРАЗОЛ",
      "СМЕКТИТ", "ЛОПЕРАМИД", "ДОМПЕРИДОН", "МЕТОКЛОПРАМИД",
      "ФОСФОЛИПИДЫ", "ЛАКТУЛОЗА", "СЕННА"), "zhkt"),
    (("БИСОПРОЛОЛ", "МЕТОПРОЛОЛ", "АТЕНОЛОЛ", "АМЛОДИПИН",
      "ВАЛСАРТАН", "ЛОЗАРТАН", "ЭНАЛАПРИЛ", "ПЕРИНДОПРИЛ",
      "ЛИЗИНОПРИЛ", "НИФЕДИПИН", "ВЕРАПАМИЛ"), "serdce"),
    (("ЦЕТИРИЗИН", "ЛОРАТАДИН", "ДЕЗЛОРАТАДИН", "ХЛОРОПИРАМИН",
      "ФЕКСОФЕНАДИН", "ЭБАСТИН", "БИЛАСТИН"), "allergiya"),
    (("АМОКСИЦИЛЛИН", "АЗИТРОМИЦИН", "ЦЕФТРИАКСОН", "ЦИПРОФЛОКСАЦИН",
      "ЛЕВОФЛОКСАЦИН", "ДОКСИЦИКЛИН", "КЛАВУЛАН", "МЕТРОНИДАЗОЛ"),
     "antibiotiki"),
    (("ДЕКСПАНТЕНОЛ", "ХЛОРГЕКСИДИН", "БЕТАМЕТАЗОН", "ГИДРОКОРТИЗОН",
      "АДАПАЛЕН", "БЕНЗОИЛ"), "kozha"),
    (("ТЕТРИЗОЛИН", "ОФТАГЕЛЬ", "ТАУФОН", "ВИЗИН", "ОФТАЛЬМОЛ"),
     "glaza"),
    (("ГЛИЦИН", "ФАБОМОТИЗОЛ", "МЕЛАТОНИН", "ВАЛЕРИАН",
      "ПУСТЫРНИК", "АФОБАЗОЛ", "ТЕНОТЕН"), "nervnaya"),
]


def detect_category(mnn: Optional[str]) -> str:
    if not mnn:
        return "other"
    upper = mnn.upper()
    for keys, slug in CATEGORY_RULES:
        if any(k in upper for k in keys):
            return slug
    return "other"


def parse_pack_size(row: Dict) -> Optional[str]:
    """Build a human pack label like '20 шт' or '30 мл' from registry fields."""
    qty = row.get("primary_in_consumer_qty")
    primary_mass = row.get("primary_mass")
    primary_unit = row.get("primary_unit")
    if primary_mass and primary_unit:
        try:
            mass = float(str(primary_mass).replace(",", "."))
            unit_short = primary_unit
            if qty and float(str(qty).replace(",", ".")) > 1:
                return f"{int(float(qty))} × {int(mass) if mass.is_integer() else mass} {unit_short}"
            return f"{int(mass) if mass.is_integer() else mass} {unit_short}"
        except Exception:
            pass
    desc = row.get("primary_pack_desc")
    return desc


def stream_rows(xlsx: Path, limit: Optional[int] = None) -> Iterable[Dict]:
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    yielded = 0
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # header
        if not row or not row[0]:
            continue
        doc = {COLS[idx]: clean_str(val) for idx, val in enumerate(row) if idx in COLS}
        # Drop the noisy contact field per discussion.
        doc.pop("manufacturer_contact", None)
        # Booleans
        for k in ("vzn", "vital", "narcotic", "pku"):
            doc[k] = yn_to_bool(doc.get(k))
        doc["limit_price"] = to_float(doc.get("limit_price"))
        doc["rx"] = is_rx(doc)
        doc["category"] = detect_category(doc.get("mnn_std"))
        yield doc
        yielded += 1
        if limit and yielded >= limit:
            break
    wb.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="Parse only, no DB writes")
    ap.add_argument("--limit", type=int, default=None, help="Limit row count (for testing)")
    args = ap.parse_args()

    if not XLSX_PATH.exists():
        print(f"❌ File not found: {XLSX_PATH}", file=sys.stderr)
        sys.exit(1)

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    print(f"→ Mongo: {mongo_url} db={db_name}")

    client = MongoClient(mongo_url) if not args.dry else None
    db = client[db_name] if client else None

    if db is not None:
        # Fresh import → drop the 3 collections we own
        for coll in ("medications_raw", "medications", "mnn_index"):
            db.drop_collection(coll)
            print(f"  dropped {coll}")

    raw_batch: List[Dict] = []
    grouped: Dict[str, Dict] = {}      # slug → card document
    mnn_to_slugs: Dict[str, set] = {}

    started = time.time()
    n_rows = 0
    n_unique_cards = 0
    n_skipped_duplicate_gtin = 0

    seen_gtins: set = set()

    for doc in stream_rows(XLSX_PATH, limit=args.limit):
        n_rows += 1
        gtin = doc.get("gtin")
        if not gtin or gtin in seen_gtins:
            n_skipped_duplicate_gtin += 1
            continue
        seen_gtins.add(gtin)

        # Card: same trade name + manufacturer + dosage = one card with variants
        card_key_parts = (
            (doc.get("trade_name") or "").upper(),
            (doc.get("manufacturer") or "").upper(),
            (doc.get("dosage_std") or "").upper(),
            (doc.get("form_std") or "").upper(),
        )
        card_key = "|".join(card_key_parts)
        if card_key not in grouped:
            slug_base = slugify(
                doc.get("trade_name"),
                doc.get("dosage_std"),
                doc.get("form_std"),
            )
            slug = slug_base
            # ensure slug uniqueness within this run
            i = 2
            while any(c.get("_slug") == slug for c in grouped.values()):
                slug = f"{slug_base}-{i}"
                i += 1
            grouped[card_key] = {
                "_slug": slug,
                "name": doc.get("trade_name"),
                "label_name": doc.get("label_name"),
                "mnn": doc.get("mnn_std"),
                "form": doc.get("form_std"),
                "dosage": doc.get("dosage_std"),
                "manufacturer": doc.get("manufacturer"),
                "manufacturer_country": doc.get("manufacturer_country"),
                "category": doc.get("category"),
                "rx": doc.get("rx"),
                "vital": doc.get("vital"),
                "vzn": doc.get("vzn"),
                "narcotic": doc.get("narcotic"),
                "pku": doc.get("pku"),
                "limit_price": doc.get("limit_price"),
                "ru_number": doc.get("ru_number"),
                "variants": [],
            }
            n_unique_cards += 1
        card = grouped[card_key]

        # variant within the card
        card["variants"].append({
            "gtin": gtin,
            "esklp_code": doc.get("esklp_code"),
            "ru_number": doc.get("ru_number"),
            "ru_date": doc.get("ru_date"),
            "pack_size": parse_pack_size(doc),
            "primary_pack_desc": doc.get("primary_pack_desc"),
            "primary_in_consumer_qty": doc.get("primary_in_consumer_qty"),
            "label_name": doc.get("label_name"),
        })

        # MNN index (skip empty)
        mnn = doc.get("mnn_std")
        if mnn:
            mnn_to_slugs.setdefault(mnn.upper(), set()).add(card["_slug"])

        raw_batch.append(doc)
        if len(raw_batch) >= 1000 and db is not None:
            db.medications_raw.insert_many(raw_batch, ordered=False)
            raw_batch.clear()

        if n_rows % 10000 == 0:
            print(f"  parsed {n_rows} rows, {n_unique_cards} cards…")

    if raw_batch and db is not None:
        try:
            db.medications_raw.insert_many(raw_batch, ordered=False)
        except BulkWriteError as e:
            print("  bulk write warnings", e.details.get("nInserted"))

    # Persist cards
    if db is not None:
        cards = []
        for card in grouped.values():
            slug = card.pop("_slug")
            card["slug"] = slug
            cards.append(card)
        if cards:
            for i in range(0, len(cards), 1000):
                db.medications.insert_many(cards[i:i + 1000], ordered=False)

        # Persist MNN index
        idx_docs = [{"mnn": k, "slugs": sorted(list(v))} for k, v in mnn_to_slugs.items()]
        if idx_docs:
            for i in range(0, len(idx_docs), 1000):
                db.mnn_index.insert_many(idx_docs[i:i + 1000], ordered=False)

        # Indexes
        db.medications.create_index([("slug", ASCENDING)], unique=True)
        db.medications.create_index([("name", TEXT), ("mnn", TEXT)],
                                    default_language="russian", name="med_text")
        db.medications.create_index([("category", ASCENDING)])
        db.medications.create_index([("mnn", ASCENDING)])
        db.medications.create_index([("manufacturer", ASCENDING)])
        db.mnn_index.create_index([("mnn", ASCENDING)], unique=True)
        db.medications_raw.create_index([("gtin", ASCENDING)], unique=True)

    elapsed = time.time() - started
    print("─" * 50)
    print(f"✓ rows parsed       : {n_rows}")
    print(f"✓ unique cards      : {n_unique_cards}")
    print(f"✓ duplicate GTIN    : {n_skipped_duplicate_gtin}")
    print(f"✓ unique MNN        : {len(mnn_to_slugs)}")
    print(f"✓ elapsed           : {elapsed:.1f}s")
    if args.dry:
        print("(dry run — nothing written)")
    else:
        print(f"✓ wrote to mongo db '{db_name}': "
              f"medications_raw, medications, mnn_index")


if __name__ == "__main__":
    main()
