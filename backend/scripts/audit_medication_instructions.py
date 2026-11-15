"""Read-only inventory of medication identities and complete instruction coverage.

No indexes, prices, medication records, or instructions are changed. Use
``--export-jsonl`` to stream public catalog identities to a local manifest;
database credentials are taken from the existing environment and never printed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Iterable


IDENTITY_PROJECTION = {
    "_id": 0, "slug": 1, "name": 1, "form": 1, "dosage": 1,
    "manufacturer": 1, "ru_number": 1, "variants": 1,
    "is_canonical": 1, "canonical_slug": 1,
    "enrichment.medical_details_status": 1, "enrichment.sources": 1,
    "enrichment.generated_at": 1, "enrichment.model": 1,
    "instruction": 1, "instructions": 1,
    "instruction_url": 1, "instruction_text": 1,
}


def normalize_identifier(value) -> str:
    return " ".join(str(value or "").strip().upper().split())


def audit_records(records: Iterable[dict], coverage_by_slug=None, on_record=None) -> dict:
    counts = Counter()
    statuses = Counter()
    instruction_fields = Counter()
    registrations = set()
    gtins = set()
    profiles = set()
    missing_identity = Counter()
    coverage_by_slug = coverage_by_slug or {}
    for med in records:
        counts["records"] += 1
        if med.get("is_canonical") is False:
            counts["aliases"] += 1
            continue
        counts["canonical_cards"] += 1
        if on_record:
            on_record(med)
        for key in ("name", "form", "dosage", "manufacturer"):
            missing_identity[key] += not bool(str(med.get(key) or "").strip())
        enrichment = med.get("enrichment") or {}
        counts["cards_with_enrichment"] += bool(enrichment)
        statuses[str(enrichment.get("medical_details_status") or "unspecified")] += 1
        counts["cards_with_legacy_generated_enrichment"] += bool(enrichment.get("model"))
        counts["cards_with_enrichment_sources"] += bool(enrichment.get("sources"))
        for key in ("instruction", "instructions", "instruction_url", "instruction_text"):
            instruction_fields[key] += bool(med.get(key))
        rus = set()
        if med.get("ru_number"):
            rus.add(normalize_identifier(med["ru_number"]))
        variants = med.get("variants") or []
        counts["variants"] += len(variants)
        counts["cards_without_variants"] += not bool(variants)
        for variant in variants:
            ru = normalize_identifier(variant.get("ru_number"))
            gtin = str(variant.get("gtin") or "").strip()
            if ru:
                rus.add(ru)
            if gtin:
                gtins.add(gtin)
            counts["variants_with_ru"] += bool(ru)
            counts["variants_with_gtin"] += bool(gtin)
            counts["variants_without_ru_or_gtin"] += not bool(ru or gtin)
        registrations.update(rus)
        for ru in rus:
            profiles.add((ru, normalize_identifier(med.get("name")),
                          normalize_identifier(med.get("form")),
                          normalize_identifier(med.get("dosage"))))
        counts["cards_without_ru" if not rus else "cards_one_ru" if len(rus) == 1 else "cards_multiple_ru"] += 1
        coverage = coverage_by_slug.get(med.get("slug")) or {}
        covered = min(int(coverage.get("covered_variants") or 0), len(variants))
        counts["covered_variants"] += covered
        counts["cards_with_any_complete_instruction"] += bool(covered)
        counts["fully_covered_cards"] += bool(variants) and covered == len(variants)
    counts["cards_missing_any_complete_instruction"] = (
        counts["canonical_cards"] - counts["cards_with_any_complete_instruction"])
    counts["cards_not_fully_covered"] = counts["canonical_cards"] - counts["fully_covered_cards"]
    counts["uncovered_variants"] = counts["variants"] - counts["covered_variants"]
    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "counts": dict(counts),
        "unique_gtins": len(gtins),
        "unique_registration_numbers": len(registrations),
        "registration_name_form_dosage_profiles": len(profiles),
        "missing_card_identity": dict(missing_identity),
        "enrichment_status": dict(statuses),
        "legacy_instruction_field_presence": dict(instruction_fields),
        "notes": [
            "Enrichment summaries and unbound links are not complete instructions.",
            "Aliases and regional pages do not increase the instruction denominator.",
            "The number of distinct documents depends on the source's explicit scope.",
        ],
    }


def load_manifest(path: Path):
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("record_type") == "medication":
                yield row["medication"]
            elif "slug" in row:
                yield row
            else:
                raise ValueError(f"Manifest line {number} is not a medication identity")


def live_coverage(db, timeout_ms: int) -> dict:
    """Reuse the public attachment rules; load only existing instruction bindings."""
    raw_documents = list(db.instruction_documents.find(
        {"verification.status": "verified"}).max_time_ms(timeout_ms))
    if not raw_documents:
        return {}
    from api.medication_instructions import (
        match_document_to_medication, medication_identity_fingerprint, validate_document,
        _variant, _variant_key,
    )

    documents = {}
    for raw in raw_documents:
        try:
            doc = validate_document(raw)
        except ValueError:
            continue
        documents[doc["id"]] = doc
    if not documents:
        return {}
    coverage = {}
    bindings = db.medication_instruction_bindings.find(
        {"status": "verified", "active": True, "document_id": {"$in": list(documents)}}
    ).max_time_ms(timeout_ms)
    grouped = {}
    for binding in bindings:
        grouped.setdefault(binding.get("medicine_slug"), []).append(binding)
    for slug, rows in grouped.items():
        med = db.medications.find_one({"slug": slug}, IDENTITY_PROJECTION, max_time_ms=timeout_ms)
        if not med or med.get("is_canonical") is False:
            continue
        fingerprint = medication_identity_fingerprint(med)
        covered = set()
        for row in rows:
            if row.get("identity_fingerprint") != fingerprint:
                continue
            result = match_document_to_medication(documents[row["document_id"]], med)
            if not result.get("matched"):
                continue
            # A binding is scoped to the exact variants accepted at import.
            accepted = {_variant_key(item) for item in row.get("variant_bindings", [])}
            covered.update(_variant_key(item) for item in result.get("bindings", [])
                           if _variant_key(item) in accepted)
        coverage[slug] = {"covered_variants": sum(
            _variant_key(_variant(med, item)) in covered for item in med.get("variants") or [])}
    return coverage


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--export-jsonl", action="store_true")
    parser.add_argument("--max-time-ms", type=int, default=4000)
    args = parser.parse_args(argv)
    if args.max_time_ms < 1:
        parser.error("--max-time-ms must be positive")
    client = None
    if args.input_manifest:
        records = load_manifest(args.input_manifest)
        coverage = {}
    else:
        from pymongo import MongoClient
        client = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=3000)
        db = client[os.environ["DB_NAME"]]
        coverage = live_coverage(db, args.max_time_ms)
        records = db.medications.find({}, IDENTITY_PROJECTION).batch_size(250).max_time_ms(args.max_time_ms)
    def export(med):
        print(json.dumps({"record_type": "medication", "medication": med}, ensure_ascii=False), flush=False)
    try:
        report = audit_records(records, coverage, export if args.export_jsonl else None)
    finally:
        if client:
            client.close()
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, file=sys.stderr if args.export_jsonl else sys.stdout, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
