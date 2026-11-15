"""Preview verified instruction JSONL imports; --apply writes only instruction collections.

Each JSONL row is either a document or {"document": ..., "original_file": ...}.
Original files are retained by the caller; an apply requires a local original
whose SHA-256 matches the document. Relative paths resolve beside the JSONL.
Use --manifest for a completely offline preview. Without it, canonical catalog
identities are read from MongoDB with deadlines. Credentials are never printed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from api.medication_instructions import (
    _gtin, _ru, _variant_key, medication_identity_fingerprint,
    match_document_to_medication, validate_document,
)
from scripts.audit_medication_instructions import IDENTITY_PROJECTION, load_manifest


TIMEOUT_MS = 4000
LOCK_ID = "__instruction_import_writer__"
LEASE_SECONDS = 120


class ImportConflict(ValueError):
    """A bounded, credential-free explanation suitable for a preview report."""


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def binding_id(document_id, medicine_slug, fingerprint, bindings, *, variant_form_evidence=None) -> str:
    if variant_form_evidence is not None:
        from api.eaeu_variant_form_evidence import form_binding_id
        return form_binding_id(document_id, medicine_slug, fingerprint, bindings, variant_form_evidence)
    return _digest({
        "document_id": document_id, "medicine_slug": medicine_slug,
        "identity_fingerprint": fingerprint,
        "variant_bindings": sorted((_variant_key(binding) for binding in bindings)),
    })


class CandidateIndex:
    def __init__(self, medications):
        self.medications, self.by_ru, self.by_gtin = {}, defaultdict(set), defaultdict(set)
        for med in medications:
            if med.get("is_canonical") is False:
                continue
            slug = med.get("slug")
            if not slug or slug in self.medications:
                raise ImportConflict("catalog has missing or duplicate canonical slugs")
            self.medications[slug] = med
            for variant in med.get("variants") or []:
                number, gtin = _ru(variant.get("ru_number")), _gtin(variant.get("gtin"))
                if number:
                    self.by_ru[number].add(slug)
                if gtin:
                    self.by_gtin[gtin].add(slug)

    def candidates(self, document):
        slugs = set()
        for scope in document["scopes"]:
            if scope.get("gtin"):
                slugs.update(self.by_gtin.get(_gtin(scope["gtin"]), ()))
            else:
                slugs.update(self.by_ru.get(_ru(scope["ru_number"]), ()))
        return (self.medications[slug] for slug in sorted(slugs))


def load_documents(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                records.append({"error": "invalid JSON", "line": line_number})
                continue
            if not isinstance(value, dict):
                records.append({"error": "document row must be an object", "line": line_number})
                continue
            record = {"document": value.get("document", value), "line": line_number}
            if 'variant_form_evidence' in value:
                record['variant_form_evidence'] = value['variant_form_evidence']
            original_file = value.get("original_file")
            if original_file:
                original_file = Path(original_file)
                record["original_file"] = str((path.parent / original_file).resolve() if not original_file.is_absolute() else original_file.resolve())
            records.append(record)
    return records


def _coverage(index, bindings):
    covered = defaultdict(set)
    for binding in bindings:
        covered[binding["medicine_slug"]].update(_variant_key(variant) for variant in binding["variant_bindings"])
    cards_any = cards_full = variants_covered = variants_total = 0
    for slug, med in index.medications.items():
        variants = med.get("variants") or []
        variants_total += len(variants)
        count = sum(
            _variant_key({
                **variant, "form": variant.get("form") or med.get("form"),
                "dosage": variant.get("dosage") or med.get("dosage"),
            }) in covered[slug] for variant in variants
        )
        cards_any += bool(count)
        cards_full += bool(variants) and count == len(variants)
        variants_covered += count
    return {
        "canonical_cards": len(index.medications), "cards_with_any_instruction": cards_any,
        "fully_covered_cards": cards_full, "total_variants": variants_total,
        "covered_variants": variants_covered, "uncovered_variants": variants_total - variants_covered,
    }


def find_overlaps(bindings, existing_bindings=()):
    owners = defaultdict(set)
    for row in [*existing_bindings, *bindings]:
        if row.get("status") != "verified" or row.get("active") is not True:
            continue
        for variant in row.get("variant_bindings") or []:
            owners[(row["medicine_slug"], row["identity_fingerprint"], _variant_key(variant))].add(row["document_id"])
    return [
        {"medicine_slug": slug, "identity_fingerprint": fingerprint,
         "variant_key": list(variant), "document_ids": sorted(document_ids)}
        for (slug, fingerprint, variant), document_ids in sorted(owners.items()) if len(document_ids) > 1
    ]


def build_plan(records, medications, *, existing_bindings=(), existing_state_checked=False,
               validator=validate_document, matcher=match_document_to_medication, archive_validator=None,
               allow_variant_form_evidence=False):
    """Pure indexed preview; does not create clients, write files or touch MongoDB."""
    index = CandidateIndex(medications)
    documents, rejected, blocked_ids = {}, [], set()
    for record in records:
        if record.get("error"):
            rejected.append({"line": record.get("line"), "reason": record["error"]})
            continue
        try:
            document = validator(record.get("document"))
            original_file = record.get("original_file")
            if original_file and file_sha256(Path(original_file)) != document["original_sha256"]:
                raise ImportConflict("original file SHA-256 differs")
            if original_file and archive_validator:
                archive_validator(document, Path(original_file))
            entry = {"document": document, "original_file": original_file, "archive_verified": bool(original_file)}
            if 'variant_form_evidence' in record:
                from api.eaeu_variant_form_evidence import validate_evidence_shape, MAX_VARIANTS
                proofs = record['variant_form_evidence']
                if not allow_variant_form_evidence or not isinstance(proofs, list) or not 1 <= len(proofs) <= MAX_VARIANTS:
                    raise ImportConflict('explicit original-only variant-form evidence list is required')
                by_slug = {}
                for proof in proofs:
                    validate_evidence_shape(proof)
                    if proof['medicine_slug'] in by_slug:
                        raise ImportConflict('duplicate variant-form medication evidence')
                    by_slug[proof['medicine_slug']] = proof
                entry['variant_form_evidence'] = by_slug
            document_id = document["id"]
            if document_id in blocked_ids:
                raise ImportConflict("document id has conflicting input records")
            if document_id in documents and documents[document_id]["document"] != document:
                documents.pop(document_id)
                blocked_ids.add(document_id)
                raise ImportConflict("document id has conflicting input records")
            if (document_id in documents and documents[document_id].get('variant_form_evidence')
                    != entry.get('variant_form_evidence')):
                documents.pop(document_id)
                blocked_ids.add(document_id)
                raise ImportConflict('document id has conflicting optional binding evidence')
            if document_id not in documents or original_file:
                documents[document_id] = entry
        except (ValueError, TypeError, KeyError, OSError) as error:
            reason = str(error) if isinstance(error, ValueError) else type(error).__name__
            rejected.append({"line": record.get("line"), "reason": reason})
    bindings, unmatched, matched_ids, candidate_comparisons = [], [], set(), 0
    for document_id, entry in documents.items():
        document = entry["document"]
        matches = 0
        document_bindings, reviewed_slugs = [], set()
        binding_proofs = entry.get('variant_form_evidence', {})
        failure = None
        for med in index.candidates(document):
            candidate_comparisons += 1
            proof = binding_proofs.get(med['slug'])
            try:
                if proof is not None:
                    from api.eaeu_variant_form_evidence import eligible_variant_keys
                    eligible_variant_keys(document, med, proof)
                    reviewed_slugs.add(med['slug'])
                    match = matcher(document, med, variant_form_evidence=proof)
                    if not match['matched']:
                        raise ImportConflict('reviewed variant-form evidence did not match its source identity')
                else:
                    match = matcher(document, med)
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                failure = str(error) if isinstance(error, ValueError) else type(error).__name__
                break
            if not match["matched"]:
                continue
            row = {
                "medicine_slug": med["slug"], "document_id": document_id,
                "identity_fingerprint": match["identity_fingerprint"],
                "variant_bindings": match["bindings"], "status": "verified", "active": True,
            }
            if proof is not None:
                from api.eaeu_variant_form_evidence import evidence_digest
                row['variant_form_evidence'] = proof
                row['variant_form_evidence_sha256'] = evidence_digest(proof)
            row["binding_id"] = binding_id(document_id, med["slug"], match["identity_fingerprint"], match["bindings"],
                                           variant_form_evidence=proof)
            document_bindings.append(row)
            matches += 1
        if failure or reviewed_slugs != set(binding_proofs):
            rejected.append({'document_id': document_id, 'reason': failure or 'variant-form evidence names an absent medication'})
            continue
        bindings.extend(document_bindings)
        if matches:
            matched_ids.add(document_id)
        else:
            unmatched.append(document_id)
    overlaps = find_overlaps(bindings, existing_bindings)
    plan = {
        "mode": "preview", "existing_state_checked": existing_state_checked,
        "documents": [documents[document_id] for document_id in sorted(matched_ids)],
        "bindings": sorted(bindings, key=lambda row: row["binding_id"]),
        "rejected": rejected, "unmatched_document_ids": sorted(unmatched), "overlaps": overlaps,
        "counts": {
            "input_rows": len(records), "validated_unique_documents": len(documents),
            "matched_documents": len(matched_ids), "planned_bindings": len(bindings),
            "unmatched_documents": len(unmatched), "rejected_rows": len(rejected),
            "overlaps": len(overlaps), "candidate_comparisons": candidate_comparisons,
            "documents_missing_archive": sum(not documents[document_id]["archive_verified"] for document_id in matched_ids),
        },
        "coverage_planned": _coverage(index, bindings),
    }
    plan["plan_hash"] = _digest({"documents": plan["documents"], "bindings": plan["bindings"]})
    return plan


def _now():
    return datetime.now(timezone.utc)


@contextmanager
def writer_lease(db):
    """One writer across CLI processes; metadata stays in the bindings collection."""
    from pymongo import ReturnDocument
    from pymongo.errors import DuplicateKeyError
    owner = uuid.uuid4().hex
    now = _now()
    try:
        row = db.medication_instruction_bindings.find_one_and_update({
            "_id": LOCK_ID, "$or": [{"expires_at": {"$lte": now}}, {"owner": owner}],
        }, {"$set": {
            "record_type": "writer_lock", "owner": owner,
            "expires_at": now + timedelta(seconds=LEASE_SECONDS),
        }}, upsert=True, return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        raise ImportConflict("another instruction import writer holds the lease") from None
    if not row or row.get("owner") != owner:
        raise ImportConflict("could not obtain instruction writer lease")

    def renew():
        updated = db.medication_instruction_bindings.update_one({"_id": LOCK_ID, "owner": owner}, {
            "$set": {"expires_at": _now() + timedelta(seconds=LEASE_SECONDS)},
        })
        if updated.matched_count != 1:
            raise ImportConflict("instruction writer lease was lost")
    try:
        yield renew
    finally:
        db.medication_instruction_bindings.update_one({"_id": LOCK_ID, "owner": owner}, {
            "$set": {"expires_at": _now(), "owner": None},
        })


def ensure_indexes(db):
    db.instruction_documents.create_index("id", unique=True, name="instruction_id_unique")
    db.medication_instruction_bindings.create_index("binding_id", unique=True,
        partialFilterExpression={"record_type": "binding"}, name="instruction_binding_unique")
    db.medication_instruction_bindings.create_index([
        ("medicine_slug", 1), ("identity_fingerprint", 1), ("status", 1), ("active", 1),
    ], name="instruction_public_lookup")
    db.medication_instruction_bindings.create_index("batch_id", name="instruction_batch_lookup")


def read_existing_bindings(db, slugs):
    if not slugs:
        return []
    return list(db.medication_instruction_bindings.find({
        "medicine_slug": {"$in": sorted(slugs)}, "status": "verified", "active": True,
    }, {"_id": 0}).max_time_ms(TIMEOUT_MS))


def _read_medication(db, slug):
    return db.medications.find_one({"slug": slug}, IDENTITY_PROJECTION, max_time_ms=TIMEOUT_MS)


def _verify_live_binding(row, document, med, *, matcher=match_document_to_medication):
    proof = row.get('variant_form_evidence')
    if proof is not None:
        from api.eaeu_variant_form_evidence import eligible_variant_keys, evidence_digest
        try:
            eligible_variant_keys(document, med, proof)
            if row.get('variant_form_evidence_sha256') != evidence_digest(proof):
                raise ValueError('optional binding evidence digest differs')
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ImportConflict('reviewed variant-form label/source identity changed') from None
        matched = matcher(document, med, variant_form_evidence=proof)
    else:
        if 'variant_form_evidence' in row or 'variant_form_evidence_sha256' in row:
            raise ImportConflict('optional binding evidence is missing')
        matched = matcher(document, med)
    expected_keys = sorted(_variant_key(variant) for variant in matched["bindings"])
    actual_keys = sorted(_variant_key(variant) for variant in row["variant_bindings"])
    expected_id = binding_id(document["id"], med["slug"], matched["identity_fingerprint"], matched["bindings"],
                             variant_form_evidence=proof)
    if (
        not matched["matched"] or actual_keys != expected_keys
        or row["identity_fingerprint"] != matched["identity_fingerprint"]
        or row["document_id"] != document["id"] or row["medicine_slug"] != med["slug"]
        or row.get("status") != "verified" or row.get("active") is not True
        or row.get("binding_id") != expected_id
    ):
        raise ImportConflict("proposed binding no longer matches the live document/variant identity")


def apply_plan(db, plan, *, batch_id=None, validator=validate_document,
               matcher=match_document_to_medication, archive_validator=None,
               allow_variant_form_evidence=False):
    """Recheck live identity and conflicts; never update medication or price data."""
    if plan.get("plan_hash") != _digest({"documents": plan["documents"], "bindings": plan["bindings"]}):
        raise ImportConflict("preview plan changed; regenerate and review it")
    if plan["rejected"] or plan["overlaps"]:
        raise ImportConflict("preview contains rejected rows or overlapping documents")
    if not allow_variant_form_evidence and any('variant_form_evidence' in row for row in plan['bindings']):
        raise ImportConflict('variant-form bindings require the explicit original-only importer')
    batch_id = batch_id or "instructions-" + _now().strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    if not plan["bindings"]:
        return {"mode": "apply", "batch_id": batch_id, "added_documents": 0, "added_bindings": 0}
    with writer_lease(db) as renew:
        ensure_indexes(db)
        document_by_id = {entry["document"]["id"]: validator(entry["document"]) for entry in plan["documents"]}
        fingerprints = {row["medicine_slug"]: row["identity_fingerprint"] for row in plan["bindings"]}
        live_medications = {}
        for slug, fingerprint in fingerprints.items():
            renew()
            med = _read_medication(db, slug)
            if not med or medication_identity_fingerprint(med) != fingerprint:
                raise ImportConflict(f"medication identity changed: {slug}")
            live_medications[slug] = med
        for row in plan["bindings"]:
            _verify_live_binding(row, document_by_id[row["document_id"]], live_medications[row["medicine_slug"]], matcher=matcher)
        existing_rows = read_existing_bindings(db, fingerprints)
        if find_overlaps(plan["bindings"], existing_rows):
            raise ImportConflict("live active instructions overlap the proposed variants")
        for entry in plan["documents"]:
            renew()
            document = validator(entry["document"])
            path = entry.get("original_file")
            if not path or file_sha256(Path(path)) != document["original_sha256"]:
                raise ImportConflict("apply requires a retained original file with matching SHA-256")
            if archive_validator:
                archive_validator(document, Path(path))
            existing = db.instruction_documents.find_one({"id": document["id"]}, max_time_ms=TIMEOUT_MS)
            if existing and validator(existing) != document:
                raise ImportConflict("immutable document id already has a different payload")
        for row in plan["bindings"]:
            existing = db.medication_instruction_bindings.find_one({"binding_id": row["binding_id"]}, max_time_ms=TIMEOUT_MS)
            if existing and (existing.get("active") is not True or existing.get("status") != "verified"):
                raise ImportConflict("a deterministic binding was previously disabled; no implicit reactivation")
            equality_fields = ["medicine_slug", "document_id", "identity_fingerprint", "variant_bindings"]
            if 'variant_form_evidence' in row:
                equality_fields += ['variant_form_evidence', 'variant_form_evidence_sha256']
            if existing and any(existing.get(key) != row.get(key) for key in equality_fields):
                raise ImportConflict("deterministic binding id has a different payload")
        audit_id = "batch:" + batch_id
        db.medication_instruction_bindings.insert_one({
            "_id": audit_id, "record_type": "import_batch", "batch_id": batch_id,
            "status": "running", "created_at": _now(), "plan_hash": plan["plan_hash"],
        })
        added_documents = added_bindings = 0
        try:
            for entry in plan["documents"]:
                renew()
                document = entry["document"]
                # The writer lease serializes all supported writers; existing versions are untouched.
                existing = db.instruction_documents.find_one({"id": document["id"]}, max_time_ms=TIMEOUT_MS)
                if not existing:
                    db.instruction_documents.insert_one({
                        **document, "_id": document["id"], "created_batch_id": batch_id,
                        "source_archive": {"path": entry["original_file"], "sha256": document["original_sha256"]},
                    })
                    added_documents += 1
                elif validator(existing) != document:
                    raise ImportConflict("immutable document changed during import")
            for row in plan["bindings"]:
                renew()
                med = _read_medication(db, row["medicine_slug"])
                if not med or medication_identity_fingerprint(med) != row["identity_fingerprint"]:
                    raise ImportConflict(f"medication identity changed before binding: {row['medicine_slug']}")
                _verify_live_binding(row, document_by_id[row["document_id"]], med, matcher=matcher)
                updated = db.medication_instruction_bindings.update_one({"binding_id": row["binding_id"]}, {
                    "$setOnInsert": {**row, "_id": row["binding_id"], "record_type": "binding", "batch_id": batch_id, "created_at": _now()},
                }, upsert=True)
                added_bindings += updated.upserted_id is not None
        except Exception as error:
            disabled = db.medication_instruction_bindings.update_many({
                "record_type": "binding", "batch_id": batch_id, "active": True,
            }, {"$set": {"active": False, "disabled_at": _now(), "disable_reason": "failed import batch"}})
            db.medication_instruction_bindings.update_one({"_id": audit_id}, {"$set": {
                "status": "failed", "finished_at": _now(),
                "added_documents": added_documents, "added_bindings": added_bindings,
                "auto_disabled_bindings": disabled.modified_count,
            }})
            reason = str(error) if isinstance(error, ImportConflict) else type(error).__name__
            raise ImportConflict(f"batch {batch_id} failed; own new bindings disabled; {reason}") from None
        db.medication_instruction_bindings.update_one({"_id": audit_id}, {"$set": {
            "status": "complete", "finished_at": _now(),
            "added_documents": added_documents, "added_bindings": added_bindings,
        }})
    return {"mode": "apply", "batch_id": batch_id, "added_documents": added_documents, "added_bindings": added_bindings}


def rollback_batch(db, batch_id):
    """Disable only this import's bindings; retain documents and every audit row."""
    with writer_lease(db) as renew:
        renew()
        audit = db.medication_instruction_bindings.find_one({"_id": "batch:" + batch_id}, max_time_ms=TIMEOUT_MS)
        if not audit or audit.get("record_type") != "import_batch":
            raise ImportConflict("unknown instruction import batch")
        updated = db.medication_instruction_bindings.update_many({
            "record_type": "binding", "batch_id": batch_id, "active": True,
        }, {"$set": {"active": False, "disabled_at": _now(), "disable_reason": "batch rollback"}})
        db.medication_instruction_bindings.update_one({"_id": "batch:" + batch_id}, {"$set": {
            "rollback_at": _now(), "rollback_disabled_bindings": updated.modified_count,
        }, "$push": {"rollback_events": {"at": _now(), "disabled_bindings": updated.modified_count}}})
        return {"mode": "rollback", "batch_id": batch_id, "disabled_bindings": updated.modified_count, "documents_retained": True}


def main(argv=None, *, validator=validate_document, matcher=match_document_to_medication,
         archive_validator=None, db_adapter=None, allow_variant_form_evidence=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", metavar="BATCH_ID")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.rollback and (args.documents or args.manifest or not args.apply):
        parser.error("--rollback requires --apply and cannot be combined with documents or manifest")
    if not args.rollback and not args.documents:
        parser.error("--documents is required")
    client = None
    try:
        db = None
        if args.apply or not args.manifest:
            from pymongo import MongoClient
            client = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=3000,
                                 connectTimeoutMS=3000, socketTimeoutMS=10000)
            db = client[os.environ["DB_NAME"]]
            if db_adapter:
                db = db_adapter(db)
        if args.rollback:
            report = rollback_batch(db, args.rollback)
        else:
            records = load_documents(args.documents)
            medications = list(load_manifest(args.manifest)) if args.manifest else list(db.medications.find(
                {"is_canonical": {"$ne": False}}, IDENTITY_PROJECTION,
            ).batch_size(250).max_time_ms(TIMEOUT_MS))
            report = build_plan(records, medications, validator=validator, matcher=matcher,
                                archive_validator=archive_validator,
                                allow_variant_form_evidence=allow_variant_form_evidence)
            if db is not None:
                existing = read_existing_bindings(db, {row["medicine_slug"] for row in report["bindings"]})
                report["overlaps"] = find_overlaps(report["bindings"], existing)
                report["counts"]["overlaps"] = len(report["overlaps"])
                report["existing_state_checked"] = True
            if args.apply:
                report["applied"] = apply_plan(db, report, validator=validator, matcher=matcher,
                                               archive_validator=archive_validator,
                                               allow_variant_form_evidence=allow_variant_form_evidence)
                report["mode"] = "apply"
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary = {key: value for key, value in report.items() if key not in {"documents", "bindings", "rejected", "overlaps"}}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return int(bool(report.get("rejected") or report.get("overlaps")))
    except Exception as error:
        # Driver exceptions can contain connection details. Never print them.
        message = str(error) if isinstance(error, ImportConflict) else "instruction import failed; see error_type"
        print(json.dumps({"error": message, "error_type": type(error).__name__}), file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
