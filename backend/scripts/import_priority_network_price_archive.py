"""Import manually verified last-sale prices from pharmacy-network pages.

Only first-party pharmacy pages are allowed here.  Each record is checked
against the curated medication identity and one of its approved pack sizes.
When only the unit count differs, the source price may be scaled linearly to
the approved pack size; the original price and both counts remain stored for
an internal audit trail.
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
    {
        "slug": "uromiteksan-100-mg-ml-rastvor-dlya-vnutrivennogo-vvedeniya",
        "price": 578,
        "source_price": 1734,
        "source_units": 15,
        "target_units": 5,
        "source_pack": "15 ампул × 4 мл (400 мг)",
        "gz_name": "Уромитексан ампулы 400 мг/4 мл №15",
        "gz_pack": "5 ампул × 4 мл (400 мг)",
        "source_manufacturer": "Baxter AG",
        "source_url": "https://www.rigla.ru/product/uromiteksan-amp-400mg-4ml-no15dlya-statsionarov-3032684",
    },
    {
        "slug": "viagra-25-mg-tabletki-pokrytye-obolochkoy",
        "price": 11392,
        "source_price": 2848,
        "source_units": 1,
        "target_units": 4,
        "source_pack": "1 таблетка",
        "gz_name": "Виагра таблетки покрытые оболочкой 25 мг №1",
        "gz_pack": "4 шт",
        "source_manufacturer": "Pfizer",
        "source_url": "https://www.rigla.ru/product/viagra-tab-po-plen-25mg-no1-397",
    },
    {
        "slug": "serokvel-25-mg-tabletki-pokrytye-obolochkoy",
        "price": 515,
        "source_price": 1030,
        "source_units": 60,
        "target_units": 30,
        "source_pack": "60 таблеток",
        "gz_name": "Сероквель таблетки покрытые оболочкой 25 мг №60",
        "gz_pack": "30 шт",
        "source_manufacturer": "AstraZeneca",
        "source_url": "https://www.rigla.ru/product/serokvel-tabpo-25mg-no60-4083",
    },
    {
        "slug": "serokvel-100-mg-tabletki-pokrytye-obolochkoy",
        "price": 608,
        "source_price": 1216,
        "source_units": 60,
        "target_units": 30,
        "source_pack": "60 таблеток",
        "gz_name": "Сероквель таблетки покрытые оболочкой 100 мг №60",
        "gz_pack": "30 шт",
        "source_manufacturer": "AstraZeneca",
        "source_url": "https://www.rigla.ru/product/serokvel-tabpo-100mg-no60-3405",
    },
    {
        "slug": "kardura-4-mg-tabletki",
        "price": 162,
        "source_price": 348,
        "source_units": 30,
        "target_units": 14,
        "source_pack": "30 таблеток",
        "gz_name": "Кардура таблетки 4 мг №30",
        "gz_pack": "14 шт",
        "source_manufacturer": "Pfizer / Viatris",
        "source_url": "https://www.rigla.ru/product/kardura-tab-4mg-no30-2551",
    },
    {
        "slug": "viagra-100-mg-tabletki-pokrytye-obolochkoy",
        "price": 7180,
        "gz_name": "Виагра таблетки покрытые оболочкой 100 мг №4",
        "gz_pack": "4 шт",
        "source_manufacturer": "Pfizer",
        "source_url": "https://www.rigla.ru/product/viagra-tab-po-plen-100mg-no4-2613",
        "observed_at": "2026-09-28T00:00:00+03:00",
    },
    {
        "slug": "venter-1-g-tabletki",
        "price": 444,
        "gz_name": "Вентер таблетки 1 г №50",
        "gz_pack": "50 шт",
        "source_manufacturer": "KRKA",
        "source_url": "https://www.rigla.ru/product/venter-tab-1g-no50-379",
        "observed_at": "2026-09-28T00:00:00+03:00",
    },
    {
        "slug": "ursofalk-250-mg-5-ml-suspenziya-dlya-priema-vnutr",
        "price": 1254,
        "gz_name": "Урсофальк суспензия 250 мг/5 мл, 250 мл",
        "gz_pack": "1 флакон × 250 мл",
        "source_manufacturer": "Dr. Falk Pharma",
        "source_url": "https://www.rigla.ru/product/ursofalk-susp-250ml-4462301",
        "observed_at": "2026-09-28T00:00:00+03:00",
    },
    {
        "slug": "gordoks-10000-kie-ml-rastvor-dlya-vnutrivennogo-vvedeniya",
        "price": 1143,
        "gz_name": "Гордокс раствор для внутривенного введения 10000 КИЕ/мл 10 мл №5",
        "gz_pack": "5 ампул × 10 мл",
        "source_manufacturer": "Gedeon Richter",
        "source_url": "https://www.rigla.ru/product/gordoks-r-r-dvv-vved-10000-kiyeml-10ml-no5-109842",
        "observed_at": "2026-09-28T00:00:00+03:00",
    },
    {
        "slug": "etopozid-teva-20-mg-ml-koncentrat-dlya-prigotovleniya-rastvora-dlya-infuziy",
        "price": 619,
        "gz_name": "Этопозид-Тева концентрат для раствора для инфузий 20 мг/мл 5 мл №1",
        "gz_pack": "1 флакон × 5 мл (100 мг)",
        "source_manufacturer": "Teva Pharmaceutical",
        "source_url": "https://www.rigla.ru/product/etopozid-teva-konts-dlya-r-ra-dlya-inf-20mgml-5ml-no1-7627",
        "observed_at": "2026-09-28T00:00:00+03:00",
    },
    {
        "slug": "cisplatin-teva-0-5-mg-ml-koncentrat-dlya-prigotovleniya-rastvora-dlya-infuziy",
        "price": 904,
        "source_price": 452,
        "source_units": 50,
        "target_units": 100,
        "source_pack": "1 флакон × 50 мл (25 мг)",
        "gz_name": "Цисплатин-Тева раствор для инъекций 0.5 мг/мл 100 мл",
        "gz_pack": "1 флакон × 100 мл (50 мг)",
        "source_manufacturer": "Teva Pharmaceutical",
        "source_url": "https://www.rigla.ru/product/tsisplatin-teva-r-r-dlya-in-05mgml-50ml-104029",
        "observed_at": "2026-09-28T00:00:00+03:00",
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
    {"гедеонрихтер", "gedeonrichter"},
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
    scaling_fields = ("source_price", "source_units", "target_units")
    has_scaling = any(field in record for field in scaling_fields)
    if has_scaling:
        if not all(isinstance(record.get(field), (int, float)) and record[field] > 0 for field in scaling_fields):
            raise ValueError(f"{record['slug']}: incomplete scaling inputs")
        expected_price = round(record["source_price"] * record["target_units"] / record["source_units"])
        if record["price"] != expected_price:
            raise ValueError(f"{record['slug']}: scaled price must be {expected_price}")
    if not record["source_url"].startswith("https://www.rigla.ru/product/"):
        raise ValueError(f"{record['slug']}: non-network source")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "aptekaa")]
    imported = 0

    for record in RECORDS:
        med = db.medications.find_one(
            {"slug": record["slug"], "curated_source": CURATED_SOURCE},
            {"_id": 1, "slug": 1, "name": 1, "manufacturer": 1, "variants": 1},
        )
        if not med:
            raise ValueError(f"{record['slug']}: curated medication not found")
        validate_record(med, record)
        observed_at = datetime.fromisoformat(
            record.get("observed_at", "2026-09-21T00:00:00+03:00")
        )
        document = {
            **{key: value for key, value in record.items() if key != "observed_at"},
            "medication_id": str(med["_id"]),
            "source": "rigla_archive",
            "city": "msk",
            "stores_count": 0,
            "match_status": "matched",
            "identity_verified": True,
            "archive_observation": True,
            "price_derived": all(field in record for field in ("source_price", "source_units", "target_units")),
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
