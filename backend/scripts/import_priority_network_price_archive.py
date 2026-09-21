"""Import manually verified last-sale prices from pharmacy-network pages.

Only first-party pharmacy pages are allowed here.  Each record is checked
against the curated medication identity and one of its approved pack sizes.
The imported rows are historical and can never make a page SEO-indexable or
claim current pharmacy availability.

Run without ``--apply`` to validate and preview the records.
"""
from __future__ import annotations

import argparse
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient


ROOT = Path(__file__).resolve().parents[1]
CURATED_SOURCE = "priority_medications_2026-09"

# Verified on the first-party Moscow pages on 21 September 2026.  These pages
# explicitly label the value as "Последняя цена продажи" and "Нет в наличии".
RECORDS = [
    {
        "slug": "miakalcik-100-me-ml-rastvor-dlya-inekciy",
        "price": 1159,
        "gz_name": "Миакальцик ампулы 100МЕ 1мл №5",
        "gz_pack": "5 ампул × 1 мл",
        "source_manufacturer": "Novartis Pharma",
        "source_url": "https://www.rigla.ru/product/miakaltsik-amp-100me-1ml-no5-1177",
    },
    {
        "slug": "cernilton-3-mg-60-mg-tabletki",
        "price": 2215,
        "gz_name": "Цернилтон таблетки №100",
        "gz_pack": "100 шт",
        "source_manufacturer": "Graminex L.L.C.",
        "source_url": "https://www.rigla.ru/product/tsernilton-tab-no100-11237",
    },
    {
        "slug": "cernilton-3-mg-60-mg-tabletki",
        "price": 3490,
        "gz_name": "Цернилтон таблетки №200",
        "gz_pack": "200 шт",
        "source_manufacturer": "Graminex L.L.C.",
        "source_url": "https://www.rigla.ru/product/tsernilton-tab-no200-8157",
    },
    {
        "slug": "endoksan-1000-mg-poroshok-dlya-prigotovleniya-rastvora-dlya-vnutrivennogo-vvedeniya",
        "price": 996,
        "gz_name": "Эндоксан порошок для инъекций 1 г, флакон №1",
        "gz_pack": "1 флакон",
        "source_manufacturer": "Baxter AG",
        "source_url": "https://www.rigla.ru/product/endoksan-pordin1g-fl-no1-4981327",
    },
    {
        "slug": "viagra-50-mg-tabletki-pokrytye-obolochkoy",
        "price": 6477,
        "gz_name": "Виагра таблетки покрытые оболочкой 50 мг №4",
        "gz_pack": "4 шт",
        "source_manufacturer": "Pfizer",
        "source_url": "https://www.rigla.ru/product/viagra-tab-po-plen-50mg-no4-2614",
    },
]


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", text)


MANUFACTURER_EQUIVALENTS = (
    {"viatris", "pfizer"},
    {"novartis", "novartispharma"},
    {"graminex", "graminexllc"},
    {"baxter", "baxterag"},
)


def manufacturer_matches(expected: str, actual: str) -> bool:
    left, right = norm(expected), norm(actual)
    if left == right or left in right or right in left:
        return True
    return any(left in group and right in group for group in MANUFACTURER_EQUIVALENTS)


def validate_record(med: dict, record: dict) -> None:
    if norm(med.get("name")) not in norm(record["gz_name"]):
        raise ValueError(f"{record['slug']}: trade name mismatch")
    if not manufacturer_matches(med.get("manufacturer", ""), record["source_manufacturer"]):
        raise ValueError(f"{record['slug']}: manufacturer mismatch")
    approved_packs = {norm(item.get("pack_size")) for item in med.get("variants") or []}
    if norm(record["gz_pack"]) not in approved_packs:
        raise ValueError(f"{record['slug']}: pack mismatch")
    if not isinstance(record.get("price"), (int, float)) or record["price"] <= 0:
        raise ValueError(f"{record['slug']}: invalid price")
    if not record["source_url"].startswith("https://www.rigla.ru/product/"):
        raise ValueError(f"{record['slug']}: non-network source")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "aptekaa")]
    observed_at = datetime.fromisoformat("2026-09-21T00:00:00+03:00")
    imported = 0

    for record in RECORDS:
        med = db.medications.find_one(
            {"slug": record["slug"], "curated_source": CURATED_SOURCE},
            {"_id": 1, "slug": 1, "name": 1, "manufacturer": 1, "variants": 1},
        )
        if not med:
            raise ValueError(f"{record['slug']}: curated medication not found")
        validate_record(med, record)
        document = {
            **record,
            "medication_id": str(med["_id"]),
            "source": "rigla_archive",
            "city": "msk",
            "stores_count": 0,
            "match_status": "matched",
            "identity_verified": True,
            "archive_observation": True,
            "updated_at": observed_at,
        }
        print(f"OK {record['slug']} {record['gz_pack']}: {record['price']} RUB")
        if args.apply:
            db.prices_real.update_one(
                {
                    "slug": record["slug"],
                    "source": "rigla_archive",
                    "city": "msk",
                    "gz_pack": record["gz_pack"],
                },
                {"$set": document},
                upsert=True,
            )
        imported += 1

    print(f"RESULT verified={imported}/{len(RECORDS)} applied={args.apply}")


if __name__ == "__main__":
    main()
