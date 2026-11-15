"""Offline import/rollback tests; fake Mongo writes only into instruction-owned collections."""
import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pymongo.errors import DuplicateKeyError

from scripts.import_medication_instructions import (
    ImportConflict, LOCK_ID, apply_plan, build_plan,
    file_sha256, load_documents, main, rollback_batch, writer_lease,
)
from test_medication_instructions import document, medication, omission_document


def matches(row, query):
    for key, value in query.items():
        if key == "$or":
            if not any(matches(row, branch) for branch in value):
                return False
        elif isinstance(value, dict):
            if "$in" in value and row.get(key) not in value["$in"]:
                return False
            if "$lte" in value and (key not in row or row[key] > value["$lte"]):
                return False
        elif row.get(key) != value:
            return False
    return True


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def max_time_ms(self, milliseconds):
        if milliseconds != 4000:
            raise AssertionError("read deadline is missing")
        return self

    def batch_size(self, count):
        return self

    def __iter__(self):
        return iter(copy.deepcopy(self.rows))


class Collection:
    def __init__(self, rows=(), *, read_only=False):
        self.rows = copy.deepcopy(list(rows))
        self.read_only = read_only
        self.writes = []
        self.find_one_calls = 0
        self.on_read = None

    def find(self, query, projection=None):
        return Cursor([row for row in self.rows if matches(row, query)])

    def find_one(self, query, projection=None, max_time_ms=None):
        if max_time_ms != 4000:
            raise AssertionError("read deadline is missing")
        self.find_one_calls += 1
        if self.on_read:
            self.on_read(self, self.find_one_calls)
        return next((copy.deepcopy(row) for row in self.rows if matches(row, query)), None)

    def _write(self, operation):
        if self.read_only:
            raise AssertionError("medications/prices must never be mutated")
        self.writes.append(operation)

    def create_index(self, *args, **kwargs):
        self._write("create_index")

    def insert_one(self, row):
        self._write("insert_one")
        for existing in self.rows:
            if any(row.get(key) is not None and row.get(key) == existing.get(key) for key in ("_id", "id", "binding_id")):
                raise DuplicateKeyError("duplicate fixture id")
        self.rows.append(copy.deepcopy(row))
        return SimpleNamespace(inserted_id=row.get("_id"))

    @staticmethod
    def update(row, update, *, inserted=False):
        if inserted:
            row.update(copy.deepcopy(update.get("$setOnInsert", {})))
        row.update(copy.deepcopy(update.get("$set", {})))
        for key, value in update.get("$push", {}).items():
            row.setdefault(key, []).append(copy.deepcopy(value))

    def update_one(self, query, update, upsert=False):
        self._write("update_one")
        for row in self.rows:
            if matches(row, query):
                self.update(row, update)
                return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            row = {key: value for key, value in query.items() if not key.startswith("$") and not isinstance(value, dict)}
            self.update(row, update, inserted=True)
            self.insert_one(row)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=row.get("_id"))
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    def update_many(self, query, update):
        self._write("update_many")
        count = 0
        for row in self.rows:
            if matches(row, query):
                self.update(row, update)
                count += 1
        return SimpleNamespace(modified_count=count)

    def find_one_and_update(self, query, update, upsert=False, **kwargs):
        self._write("find_one_and_update")
        for row in self.rows:
            if matches(row, query):
                self.update(row, update)
                return copy.deepcopy(row)
        if upsert:
            row = {"_id": query["_id"]}
            self.update(row, update, inserted=True)
            self.insert_one(row)
            return copy.deepcopy(row)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.folder = Path(self.folder.name)
        self.original = self.folder / "original.source"
        self.original.write_bytes(b"original offline source record")
        self.doc, self.med = document(), medication()
        self.doc["original_sha256"] = file_sha256(self.original)
        self.records = [{"document": self.doc, "original_file": str(self.original), "line": 1}]
        self.db = SimpleNamespace(
            medications=Collection([self.med], read_only=True), prices=Collection(read_only=True),
            instruction_documents=Collection(), medication_instruction_bindings=Collection(),
        )

    def plan(self, records=None, meds=None, **kwargs):
        return build_plan(self.records if records is None else records, [self.med] if meds is None else meds, **kwargs)

    def active_bindings(self):
        return [row for row in self.db.medication_instruction_bindings.rows if row.get("record_type") == "binding" and row["active"]]

    def test_indexed_preview_separates_any_full_and_variants_without_writes(self):
        meds = [self.med]
        for index in range(100):
            med = medication()
            med["slug"] = f"unrelated-{index}"
            med["variants"] = [{"ru_number": f"РУ-ДРУГОЕ-{index}", "gtin": f"900{index:010d}"}]
            meds.append(med)
        plan = self.plan(meds=meds)
        self.assertEqual(plan["counts"]["candidate_comparisons"], 1)
        self.assertEqual(plan["counts"]["planned_bindings"], 1)
        self.assertEqual(plan["coverage_planned"]["cards_with_any_instruction"], 1)
        self.assertEqual(plan["coverage_planned"]["fully_covered_cards"], 0)
        self.assertEqual(plan["coverage_planned"]["covered_variants"], 1)
        self.assertEqual(self.db.instruction_documents.writes, [])

    def test_source_omissions_preserve_archive_hash_and_immutable_review_on_apply(self):
        doc = omission_document()
        doc["original_sha256"] = file_sha256(self.original)
        for item in doc["completeness"]["omission_evidence"].values():
            item["original_sha256"] = doc["original_sha256"]
        records = [{"document": doc, "original_file": str(self.original)}]
        plan = self.plan(records=records)
        self.assertEqual(plan["counts"]["planned_bindings"], 1)
        self.original.write_bytes(b"changed after whole-source review")
        with self.assertRaises(ImportConflict):
            apply_plan(self.db, plan, batch_id="omissions-changed-original")
        self.assertEqual(self.db.instruction_documents.rows, [])
        self.original.write_bytes(b"original offline source record")
        apply_plan(self.db, plan, batch_id="omissions-reviewed")
        stored = self.db.instruction_documents.rows[0]
        self.assertEqual(stored["completeness"], doc["completeness"])
        changed_review = copy.deepcopy(doc)
        changed_review["completeness"]["omission_evidence"]["overdose"]["reason"] += " Новый комментарий проверяющего."
        with self.assertRaises(ImportConflict):
            apply_plan(self.db, self.plan(records=[{"document": changed_review, "original_file": str(self.original)}]))
        self.assertEqual(self.db.medications.writes, [])
        self.assertEqual(self.db.prices.writes, [])

    def test_jsonl_preview_is_offline_by_default_and_original_hash_is_checked(self):
        path = self.folder / "docs.jsonl"
        path.write_text(json.dumps({"document": self.doc, "original_file": "original.source"}) + "\n")
        records = load_documents(path)
        self.assertEqual(records[0]["original_file"], str(self.original.resolve()))
        manifest = self.folder / "catalog.jsonl"
        manifest.write_text(json.dumps(self.med) + "\n")
        report = self.folder / "preview.json"
        with patch.dict("os.environ", {}, clear=True), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(main(["--documents", str(path), "--manifest", str(manifest), "--report", str(report)]), 0)
        self.assertEqual(json.loads(report.read_text())["mode"], "preview")
        self.original.write_bytes(b"changed original")
        self.assertEqual(self.plan(records=records)["counts"]["rejected_rows"], 1)

    def test_invalid_unmatched_and_conflicting_duplicate_documents_are_reported(self):
        bad, unmatched = copy.deepcopy(self.doc), copy.deepcopy(self.doc)
        bad["verification"]["status"] = "draft"
        unmatched["id"] = "unmatched"
        unmatched["scopes"] = [{"gtin": "9999999999999"}]
        plan = self.plan(records=[{"document": bad}, {"document": unmatched}])
        self.assertEqual(plan["counts"]["rejected_rows"], 1)
        self.assertEqual(plan["unmatched_document_ids"], ["unmatched"])
        changed = copy.deepcopy(self.doc)
        changed["version"] = "another payload under same id"
        plan = self.plan(records=[{"document": self.doc}, {"document": changed}])
        self.assertEqual(plan["bindings"], [])
        self.assertEqual(plan["counts"]["rejected_rows"], 1)

    def test_two_documents_cannot_implicitly_replace_an_overlapping_variant(self):
        second = copy.deepcopy(self.doc)
        second["id"] = "document-v2"
        plan = self.plan(records=self.records + [{"document": second}])
        self.assertEqual(plan["counts"]["overlaps"], 1)
        with self.assertRaises(ImportConflict):
            apply_plan(self.db, plan)
        self.assertEqual(self.db.instruction_documents.writes, [])

    def test_apply_is_idempotent_immutable_and_never_mutates_catalog_or_prices(self):
        plan = self.plan()
        first = apply_plan(self.db, plan, batch_id="first")
        second = apply_plan(self.db, plan, batch_id="second")
        self.assertEqual((first["added_documents"], first["added_bindings"]), (1, 1))
        self.assertEqual((second["added_documents"], second["added_bindings"]), (0, 0))
        self.assertEqual(self.active_bindings()[0]["batch_id"], "first")
        self.assertEqual(self.db.medications.writes, [])
        self.assertEqual(self.db.prices.writes, [])
        changed = copy.deepcopy(self.doc)
        changed["version"] = "mutated immutable version"
        with self.assertRaisesRegex(ImportConflict, "immutable"):
            apply_plan(self.db, self.plan(records=[{"document": changed, "original_file": str(self.original)}]))

    def test_apply_checks_live_identity_and_original_before_publishing(self):
        plan = self.plan()
        self.db.medications.rows[0]["manufacturer"] = "Changed"
        with self.assertRaisesRegex(ImportConflict, "identity changed"):
            apply_plan(self.db, plan)
        self.assertEqual(self.active_bindings(), [])
        self.db.medications.rows = [copy.deepcopy(self.med)]
        self.original.write_bytes(b"changed since preview")
        with self.assertRaisesRegex(ImportConflict, "original file"):
            apply_plan(self.db, plan)
        self.assertEqual(self.db.instruction_documents.rows, [])

    def test_apply_refuses_missing_archive_or_changed_preview(self):
        plan = self.plan(records=[{"document": self.doc}])
        with self.assertRaisesRegex(ImportConflict, "retained original"):
            apply_plan(self.db, plan)
        plan = self.plan()
        plan["bindings"][0]["variant_bindings"][0]["ru_number"] = "FORGED"
        with self.assertRaisesRegex(ImportConflict, "preview plan changed"):
            apply_plan(self.db, plan)

    def test_live_overlap_with_another_version_blocks_apply_and_preserves_both_documents(self):
        apply_plan(self.db, self.plan(), batch_id="first")
        newer = copy.deepcopy(self.doc)
        newer["id"], newer["version"] = "new-version", "v2"
        plan = self.plan(records=[{"document": newer, "original_file": str(self.original)}])
        with self.assertRaisesRegex(ImportConflict, "overlap"):
            apply_plan(self.db, plan)
        self.assertEqual(len(self.db.instruction_documents.rows), 1)
        self.assertEqual(len(self.active_bindings()), 1)

    def test_rollback_only_disables_own_bindings_and_retains_documents_and_audit(self):
        apply_plan(self.db, self.plan(), batch_id="first")
        apply_plan(self.db, self.plan(), batch_id="idempotent")
        self.assertEqual(rollback_batch(self.db, "idempotent")["disabled_bindings"], 0)
        self.assertEqual(len(self.active_bindings()), 1)
        self.assertEqual(rollback_batch(self.db, "first")["disabled_bindings"], 1)
        self.assertEqual(self.active_bindings(), [])
        self.assertEqual(len(self.db.instruction_documents.rows), 1)
        rollback_batch(self.db, "first")
        audit = next(row for row in self.db.medication_instruction_bindings.rows if row.get("_id") == "batch:first")
        self.assertEqual(len(audit["rollback_events"]), 2)
        with self.assertRaisesRegex(ImportConflict, "previously disabled"):
            apply_plan(self.db, self.plan())

    def test_one_writer_lease_is_exclusive_and_is_released(self):
        with writer_lease(self.db):
            with self.assertRaisesRegex(ImportConflict, "another instruction import writer"):
                with writer_lease(self.db):
                    self.fail("second writer must not run")
        with writer_lease(self.db):
            pass
        lock = next(row for row in self.db.medication_instruction_bindings.rows if row.get("_id") == LOCK_ID)
        self.assertIsNone(lock["owner"])

    def test_identity_change_during_apply_disables_new_batch_bindings(self):
        second = copy.deepcopy(self.med)
        second["slug"] = "second-card"
        self.db.medications.rows.append(second)
        plan = self.plan(meds=[self.med, second])

        def change_before_second_binding(collection, call):
            if call == 4:  # Two preflight reads followed by one read per binding.
                for med in collection.rows:
                    med["dosage"] = "changed during apply"
        self.db.medications.on_read = change_before_second_binding
        with self.assertRaisesRegex(ImportConflict, "own new bindings disabled"):
            apply_plan(self.db, plan, batch_id="failed")
        self.assertEqual(self.active_bindings(), [])
        audit = next(row for row in self.db.medication_instruction_bindings.rows if row.get("_id") == "batch:failed")
        self.assertEqual(audit["status"], "failed")
        self.assertEqual(audit["auto_disabled_bindings"], 1)
        self.assertEqual(len(self.db.instruction_documents.rows), 1)


if __name__ == "__main__":
    unittest.main()
