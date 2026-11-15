"""Catalog denominators and disjoint work batches are independent of summaries."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
import copy

from scripts.audit_medication_instructions import audit_records, live_coverage
from scripts.partition_instruction_catalog import partition_catalog


def med(slug, **values):
    return {"slug": slug, "name": "Пример", "form": "таблетки", "dosage": "1 мг",
            "manufacturer": "Завод", "variants": [{"gtin": "4600000000001", "ru_number": "РУ-1"}], **values}


class InventoryTests(unittest.TestCase):
    def test_live_coverage_agrees_with_api_binding_keys_and_counts_actual_variants(self):
        from test_medication_instructions import document, medication, binding
        item = medication()
        item["variants"] = [copy.deepcopy(item["variants"][0]), copy.deepcopy(item["variants"][0])]
        doc = document()
        accepted = binding(doc, item)
        accepted["variant_bindings"][0]["form"] = "  таблетки "

        class Cursor:
            def __init__(self, values):
                self.values = values
            def max_time_ms(self, timeout):
                self.timeout = timeout
                return self
            def __iter__(self):
                return iter(self.values)

        class Collection:
            def __init__(self, values):
                self.values = values
            def find(self, query):
                return Cursor(self.values)
            def find_one(self, query, projection, max_time_ms):
                return copy.deepcopy(self.values[0])

        db = SimpleNamespace(instruction_documents=Collection([doc]),
                             medication_instruction_bindings=Collection([accepted]),
                             medications=Collection([item]))
        coverage = live_coverage(db, 4000)
        self.assertEqual(coverage[item["slug"]]["covered_variants"], 2)
        self.assertEqual(audit_records([item], coverage)["counts"]["fully_covered_cards"], 1)
        accepted["identity_fingerprint"] = "stale"
        self.assertEqual(live_coverage(db, 4000)[item["slug"]]["covered_variants"], 0)

    def test_summaries_aliases_and_unbound_links_do_not_count_as_complete(self):
        records = [
            med("a", enrichment={"medical_details_status": "source-backed", "sources": [{"url": "https://example.org"}]}),
            med("b", enrichment={"model": "legacy"}, instruction_url="https://example.org/file.pdf"),
            med("old-a", is_canonical=False),
        ]
        report = audit_records(records)
        counts = report["counts"]
        self.assertEqual((counts["records"], counts["canonical_cards"], counts["aliases"]), (3, 2, 1))
        self.assertEqual(counts["cards_missing_any_complete_instruction"], 2)
        self.assertEqual(counts["covered_variants"], 0)
        self.assertEqual(report["legacy_instruction_field_presence"]["instruction_url"], 1)

    def test_partial_card_and_full_card_have_different_coverage(self):
        records = [med("a", variants=[{"gtin": "1", "ru_number": "РУ-1"}, {"gtin": "2", "ru_number": "РУ-2"}]), med("b")]
        report = audit_records(records, {"a": {"covered_variants": 1}, "b": {"covered_variants": 1}})
        counts = report["counts"]
        self.assertEqual(counts["cards_with_any_complete_instruction"], 2)
        self.assertEqual(counts["fully_covered_cards"], 1)
        self.assertEqual(counts["uncovered_variants"], 1)
        self.assertEqual(counts["cards_multiple_ru"], 1)

    def test_partition_is_disjoint_repeatable_and_has_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalog.jsonl"
            source.write_text("".join(json.dumps(med(f"m-{index:04d}")) + "\n" for index in reversed(range(2001))), encoding="utf-8")
            destination = Path(directory) / "batches"
            report = partition_catalog(source, destination)
            self.assertEqual([batch["cards"] for batch in report["batches"]], [1000, 1000, 1])
            self.assertEqual(partition_catalog(source, destination), report)
            slugs = [json.loads(line)["medication"]["slug"] for batch in report["batches"]
                     for line in (destination / batch["file"]).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(slugs), len(set(slugs)))
            self.assertEqual(slugs, sorted(slugs))

    def test_partition_refuses_duplicate_identities_or_overwriting_other_work(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalog.jsonl"
            destination = Path(directory) / "batches"
            source.write_text(json.dumps(med("a")) + "\n", encoding="utf-8")
            partition_catalog(source, destination)
            source.write_text(json.dumps(med("b")) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing to replace"):
                partition_catalog(source, destination)
            source.write_text((json.dumps(med("a")) + "\n") * 2, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate slugs"):
                partition_catalog(source, destination)


if __name__ == "__main__":
    unittest.main()
