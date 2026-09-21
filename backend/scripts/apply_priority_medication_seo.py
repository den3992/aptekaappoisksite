"""Apply reviewed SEO/medical content to the approved priority medicines.

The script is preview-only unless ``--apply`` is supplied.  Every previous
enrichment/SEO payload is backed up before it is replaced.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

from scripts.import_priority_medications import SOURCE, curated_key, target_group


ROOT = Path(__file__).resolve().parents[1]
MEDICATIONS = ROOT / "data" / "priority_medications_2026-09.json"
MONOGRAPHS = ROOT / "data" / "priority_medication_monographs_2026-09.json"
CONTENT_VERSION = "priority-seo-moscow-2026-09-v2"
GRLS_SOURCE = {
    "title": "ГРЛС Минздрава России: поиск официальной инструкции конкретной упаковки",
    "url": "https://grls.rosminzdrav.ru/",
}


def profile_key(item: dict) -> str:
    name = item["name"]
    form = item.get("form") or ""
    if name == "Синактен Депо":
        return "ТЕТРАКОЗАКТИД-ДЕПО"
    if name == "Синактен":
        return "ТЕТРАКОЗАКТИД-ДИАГНОСТИЧЕСКИЙ"
    if item.get("mnn") == "КАЛЬЦИТОНИН ЛОСОСЯ СИНТЕТИЧЕСКИЙ":
        return "КАЛЬЦИТОНИН-СПРЕЙ" if "СПРЕЙ" in form else "КАЛЬЦИТОНИН-ИНЪЕКЦИИ"
    if name == "Провера" and item.get("dosage") == "500 мг":
        return "МЕДРОКСИПРОГЕСТЕРОН-500"
    if name == "Протефлазид":
        return "ПРОТЕФЛАЗИД"
    return item.get("mnn") or name.upper()


def lower_first(value: str) -> str:
    return value[:1].lower() + value[1:] if value else value


def pack_phrase(pack_sizes: list[str]) -> str:
    if len(pack_sizes) == 1:
        return pack_sizes[0]
    return ", ".join(pack_sizes[:-1]) + " и " + pack_sizes[-1]


def build_payload(item: dict, monograph: dict, *, title_qualifier: str | None = None) -> tuple[dict, dict]:
    name = item["name"]
    dose = item.get("dosage")
    form = lower_first(item["form"])
    manufacturer = item["manufacturer"]
    packs = pack_phrase(item["pack_sizes"])
    name_dose = " ".join(filter(None, (name, dose)))

    summary = (
        f"{name_dose} — {monograph['overview']}. "
        f"Лекарственная форма: {form}; производитель — {manufacturer}; "
        f"варианты упаковки в каталоге: {packs}. "
        "Наличие и цены показываются только по подтвержденным данным аптечных сетей выбранного города."
    )
    sources = [GRLS_SOURCE, *(monograph.get("sources") or [])]
    details_are_source_backed = monograph.get("details_source") == "product-specific"
    # Keep source order stable and avoid duplicate URLs.
    deduped_sources = []
    seen_urls = set()
    for source in sources:
        if source["url"] in seen_urls:
            continue
        seen_urls.add(source["url"])
        deduped_sources.append(source)

    enrichment = {
        "summary": summary,
        "indications": monograph["indications"] if details_are_source_backed else [],
        "contraindications": monograph["contraindications"] if details_are_source_backed else [],
        "how_to_take": monograph["administration"] if details_are_source_backed else None,
        "medical_details_status": "source-backed" if details_are_source_backed else "catalog-summary-only",
        "disclaimer": (
            "Справочная информация не заменяет официальную инструкцию и консультацию врача. "
            "Имеются противопоказания; для рецептурных и госпитальных препаратов требуется назначение специалиста."
        ),
        "sources": deduped_sources,
        "updated_at": "2026-09-21",
        "content_version": CONTENT_VERSION,
    }
    seo = {
        "focus_city": "msk",
        "primary_query": f"{name_dose} купить в Москве",
        "secondary_queries": [
            f"{name_dose} цена",
            f"{name_dose} наличие в аптеках Москвы",
            f"{name_dose} инструкция",
            f"{name_dose} аналоги",
        ],
        "product_facts": {
            "form": item["form"],
            "dosage": dose,
            "manufacturer": manufacturer,
            "manufacturer_country": item.get("manufacturer_country"),
            "packs": item["pack_sizes"],
        },
        "content_version": CONTENT_VERSION,
    }
    if title_qualifier:
        seo["title_qualifier"] = title_qualifier
    return enrichment, seo


def validate_payload(enrichment: dict) -> list[str]:
    errors = []
    if len(enrichment["summary"]) < 180:
        errors.append("summary is too short")
    details_are_source_backed = enrichment.get("medical_details_status") == "source-backed"
    if details_are_source_backed and not (1 <= len(enrichment["indications"]) <= 6):
        errors.append("source-backed indications must contain 1-6 items")
    if details_are_source_backed and not (1 <= len(enrichment["contraindications"]) <= 7):
        errors.append("source-backed contraindications must contain 1-7 items")
    if not details_are_source_backed and (enrichment["indications"] or enrichment["contraindications"] or enrichment["how_to_take"]):
        errors.append("unverified medical details must not be published")
    if not enrichment.get("sources"):
        errors.append("sources are missing")
    text = json.dumps(enrichment, ensure_ascii=False).lower()
    for forbidden in ("гарантирован", "лучший препарат", "безопасен для всех"):
        if forbidden in text:
            errors.append(f"forbidden claim: {forbidden}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    items = json.loads(MEDICATIONS.read_text(encoding="utf-8"))
    monographs = json.loads(MONOGRAPHS.read_text(encoding="utf-8"))
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    missing_profiles = sorted({profile_key(item) for item in items} - set(monographs))
    if missing_profiles:
        raise SystemExit(f"Missing content profiles: {missing_profiles}")

    plan = []
    errors = []
    group_counts = {}
    for item in items:
        group = target_group(item)
        group_counts[group] = group_counts.get(group, 0) + 1
    for item in items:
        key = curated_key(item)
        doc = db.medications.find_one({"curated_source": SOURCE, "curated_key": key})
        if not doc:
            errors.append(f"Medication is missing: {item['name']} {item.get('dosage')}")
            continue
        qualifier = item["manufacturer"] if group_counts[target_group(item)] > 1 else None
        enrichment, seo = build_payload(
            item,
            monographs[profile_key(item)],
            title_qualifier=qualifier,
        )
        for error in validate_payload(enrichment):
            errors.append(f"{doc['slug']}: {error}")
        plan.append((doc, enrichment, seo))

    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    if args.verify:
        verify_errors = []
        for doc, expected_enrichment, expected_seo in plan:
            live = db.medications.find_one({"_id": doc["_id"]})
            if live.get("enrichment") != expected_enrichment:
                verify_errors.append(f"{doc['slug']}: enrichment differs")
            if live.get("seo") != expected_seo:
                verify_errors.append(f"{doc['slug']}: seo differs")
        if verify_errors:
            print("VERIFY FAILED")
            for error in verify_errors:
                print(f"  - {error}")
            raise SystemExit(1)
        print(f"VERIFY OK: {len(plan)} cards match {CONTENT_VERSION}")
        return

    print(f"Cards ready: {len(plan)}")
    print(f"Existing descriptions to replace: {sum(bool(doc.get('enrichment')) for doc, _, _ in plan)}")
    for doc, enrichment, _ in plan:
        print(f"  {doc['slug']} | {len(enrichment['summary'])} chars | {len(enrichment['sources'])} sources")

    if not args.apply:
        print("PREVIEW ONLY: re-run with --apply to write changes")
        return

    batch_id = f"{CONTENT_VERSION}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    for doc, enrichment, seo in plan:
        db.curated_import_backups.insert_one({
            "batch_id": batch_id,
            "source": CONTENT_VERSION,
            "slug": doc["slug"],
            "action": "replace-seo-content",
            "backed_up_at": now,
            "document": {"enrichment": doc.get("enrichment"), "seo": doc.get("seo")},
        })
        db.medications.update_one(
            {"_id": doc["_id"]},
            {"$set": {"enrichment": enrichment, "seo": seo, "seo_updated_at": now}},
        )
    print(f"APPLIED: {len(plan)} cards; backup batch={batch_id}")


if __name__ == "__main__":
    main()
