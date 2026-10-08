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
        "price": 687,
        "gz_name": "Этопозид-Тева концентрат для раствора для инфузий 20 мг/мл 5 мл №1",
        "gz_pack": "1 флакон × 5 мл (100 мг)",
        "source_manufacturer": "Teva Pharmaceutical",
        "source_url": "https://www.rigla.ru/product/etopozid-teva-konts-dlya-r-ra-dlya-inf-20mgml-5ml-no1-7627",
        "observed_at": "2026-09-28T00:00:00+03:00",
    },
    {
        "slug": "cisplatin-teva-0-5-mg-ml-koncentrat-dlya-prigotovleniya-rastvora-dlya-infuziy",
        "price": 1394,
        "gz_name": "Цисплатин-Тева раствор для инъекций 0.5 мг/мл 100 мл",
        "gz_pack": "1 флакон × 100 мл (50 мг)",
        "source_manufacturer": "Teva Pharmaceutical",
        "source_url": "https://www.rigla.ru/product/tsisplatin-teva-r-r-dlya-in-05mgml-100ml-36424",
        "observed_at": "2026-09-28T00:00:00+03:00",
    },
    {
        "slug": "tamoksifen-geksal-20-mg-tabletki-pokrytye-obolochkoy",
        "price": 640,
        "source_price": 192,
        "source_units": 30,
        "target_units": 100,
        "source_pack": "30 таблеток",
        "gz_name": "Тамоксифен Гексал таблетки покрытые оболочкой 20 мг №100",
        "gz_pack": "100 шт",
        "source_manufacturer": "Hexal",
        "source_url": "https://www.rigla.ru/product/tamoksifen-tabpo-20mg-no30-28227",
        "observed_at": "2026-09-28T00:00:00+03:00",
    },
    {
        "slug": "kamrou-150-mkg-ml-750-me-ml-rastvor-dlya-vnutrimyshechnogo-vvedeniya",
        "price": 1787,
        "gz_name": "КамРОУ раствор для внутримышечного введения 750 МЕ/мл 2 мл №1",
        "gz_pack": "1 флакон × 2 мл",
        "source_manufacturer": "Kamada Ltd",
        "source_url": "https://www.rigla.ru/product/immunoglobulin-chelovecheskiy-antirezus-kamrou-r-r-dvm-vved-750meml-2ml-no1-73766",
        "observed_at": "2026-09-28T00:00:00+03:00",
    },
    {
        "slug": "karboplatin-teva-10-mg-ml-koncentrat-dlya-prigotovleniya-rastvora-dlya-infuziy",
        "price": 2504,
        "gz_name": "Карбоплатин-Тева концентрат для раствора для инфузий 10 мг/мл 45 мл №1",
        "gz_pack": "1 флакон × 45 мл (450 мг)",
        "source_manufacturer": "Teva Pharmaceutical",
        "source_url": "https://www.rigla.ru/product/karboplatin-kontsdr-ra-dinf-450mg-45ml-no1-46660",
        "observed_at": "2026-09-28T00:00:00+03:00",
    },
    {
        "slug": "vinkristin-teva-1-mg-ml-rastvor-dlya-vnutrivennogo-vvedeniya",
        "price": 836,
        "gz_name": "Винкристин-Тева раствор для внутривенного введения 1 мг/мл 2 мл №1",
        "gz_pack": "1 флакон × 2 мл",
        "source_manufacturer": "ФАРМАХЕМИ Б. В.",
        "source_url": "https://www.rigla.ru/product/vinkristin-teva-r-r-dlya-vv-vved-1mgml-fl-2ml-no1-116323",
        "observed_at": "2026-09-28T00:00:00+03:00",
    },
    {
        "slug": "oksaliplatin-ebeve-5-mg-ml-koncentrat-dlya-prigotovleniya-rastvora-dlya-infuziy",
        "price": 2065,
        "gz_name": "Оксалиплатин Эбеве концентрат 5 мг/мл 10 мл №1",
        "gz_pack": "1 флакон × 10 мл (50 мг)",
        "source_manufacturer": "ФАРЕВА Унтерах ГмбХ",
        "source_url": "https://www.rigla.ru/product/oksaliplatin-ebeve-konts-dlya-prigot-r-ra-dlya-inf-5mgml-fl-10ml-no1-114964",
        "approved_target_name": "Оксалиплатин Эбеве",
        "approved_target_manufacturer": "EBEWE PHARMA",
        "reference_approved_at": "2026-10-08",
        "observed_at": "2026-10-08T00:00:00+03:00",
    },
    {
        "slug": "neotigazon-10-mg-kapsuly",
        "price": 1783,
        "gz_name": "Неотигазон капсулы 10 мг №30",
        "gz_pack": "30 шт",
        "source_manufacturer": "Roche (рецепт.)",
        "source_url": "https://www.rigla.ru/product/neotigazon-kaps-10mg-no30-3032500",
        "approved_target_name": "Неотигазон",
        "approved_target_manufacturer": "ACTAVIS",
        "reference_approved_at": "2026-10-08",
        "observed_at": "2026-10-08T00:00:00+03:00",
    },
    {
        "slug": "neotigazon-25-mg-kapsuly",
        "price": 3634,
        "gz_name": "Неотигазон капсулы 25 мг №30",
        "gz_pack": "30 шт",
        "source_manufacturer": "Roche (рецепт.)",
        "source_url": "https://www.rigla.ru/product/neotigazon-kaps-25mg-no30-4454100",
        "approved_target_name": "Неотигазон",
        "approved_target_manufacturer": "ACTAVIS",
        "reference_approved_at": "2026-10-08",
        "observed_at": "2026-10-08T00:00:00+03:00",
    },
    {
        "slug": "moviprep-poroshok-dlya-prigotovleniya-rastvora-dlya-priema-vnutr",
        "price": 1249,
        "gz_name": "Мовипреп порошок саше А №2 + Б №2",
        "gz_pack": "4 саше (2 саше A + 2 саше B)",
        "source_manufacturer": "Норджин Лимитед",
        "source_url": "https://www.rigla.ru/product/moviprep-por-dlya-r-ra-dlya-priyema-vnutr-sashe-a-111896g-no2b-10600g-no2-102079",
        "approved_target_name": "Мовипреп",
        "approved_target_manufacturer": "ACINO",
        "reference_approved_at": "2026-10-08",
        "observed_at": "2026-10-08T00:00:00+03:00",
    },
    {
        "slug": "rasilez-150-mg-tabletki-pokrytye-obolochkoy",
        "price": 13363,
        "source_price": 3818,
        "source_units": 28,
        "target_units": 98,
        "source_pack": "28 таблеток",
        "gz_name": "Расилез таблетки покрытые оболочкой 150 мг №28",
        "gz_pack": "98 шт",
        "source_manufacturer": "Novartis Pharma",
        "source_url": "https://www.rigla.ru/product/rasilez-tabpo-150mg-no28-31957",
        "approved_target_name": "Расилез",
        "approved_target_manufacturer": "NODEN PHARMA",
        "reference_approved_at": "2026-10-08",
        "observed_at": "2026-10-08T00:00:00+03:00",
    },
    {
        "slug": "isentress-400-mg-tabletki-pokrytye-obolochkoy",
        "price": 16050,
        "source_price": 19260,
        "source_units": 60,
        "target_units": 50,
        "source_pack": "60 таблеток",
        "gz_name": "Исентресс таблетки покрытые пленочной оболочкой 400 мг №60",
        "gz_pack": "50 шт",
        "source_manufacturer": "Р-Фарм АО",
        "source_url": "https://www.rigla.ru/product/isentress-tabpo-plen-400mg-no60-109078",
        "approved_target_name": "Исентресс",
        "approved_target_manufacturer": "MSD",
        "reference_approved_at": "2026-10-08",
        "observed_at": "2026-10-08T00:00:00+03:00",
    },
    {
        "slug": "5-ftoruracil-ebeve-50-mg-ml-koncentrat-dlya-prigotovleniya-rastvora-dlya-infuziy",
        "price": 270,
        "gz_name": "5-Фторурацил-Эбеве концентрат 1 г/20 мл №1",
        "gz_pack": "1 флакон × 20 мл (1000 мг)",
        "source_manufacturer": "Ever Neuro Pharma",
        "source_url": "https://www.rigla.ru/product/5-ftoruratsil-ebeve-konts-dlya-r-ra-dlya-inf-1g20ml-no1-4455315",
        "approved_target_name": "5-Фторурацил-Эбеве",
        "approved_target_manufacturer": "EBEWE PHARMA",
        "reference_approved_at": "2026-10-08",
        "observed_at": "2026-10-08T00:00:00+03:00",
    },
    {
        "slug": "doksorubicin-ebeve-2-mg-ml-koncentrat-dlya-prigotovleniya-rastvora-dlya-infuziy",
        "price": 1267,
        "gz_name": "Доксорубицин концентрат 50 мг/25 мл №1",
        "gz_pack": "1 флакон × 25 мл (50 мг)",
        "source_manufacturer": "Ever Neuro Pharma",
        "source_url": "https://www.rigla.ru/product/doksorubitsin-konts-dlya-r-ra-dlya-inf-50mg-25ml-3032763",
        "approved_target_name": "Доксорубицин Эбеве",
        "approved_target_manufacturer": "EBEWE PHARMA",
        "reference_approved_at": "2026-10-08",
        "observed_at": "2026-10-08T00:00:00+03:00",
    },
]


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", text)


MANUFACTURER_EQUIVALENTS = (
    {"viatris", "pfizer"},
    {"teva", "tevapharmaceutical", "фармахемибв"},
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


def approved_reference(med: dict, record: dict) -> bool:
    # Explicit approval of this specific target, not manufacturer equivalence.
    return bool(
        record.get("reference_approved_at")
        and norm(med.get("name")) == norm(record.get("approved_target_name"))
        and norm(med.get("manufacturer")) == norm(record.get("approved_target_manufacturer"))
    )


def validate_record(med: dict, record: dict) -> None:
    approved = approved_reference(med, record)
    if norm(med.get("name")) not in norm(record["gz_name"]) and not approved:
        raise ValueError(f"{record['slug']}: trade name mismatch")
    if not manufacturer_matches(med.get("manufacturer", ""), record["source_manufacturer"]) and not approved:
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
            "identity_verified": bool(
                norm(med.get("name")) in norm(record["gz_name"])
                and manufacturer_matches(med.get("manufacturer", ""), record["source_manufacturer"])
            ),
            "user_approved_reference": approved_reference(med, record),
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
