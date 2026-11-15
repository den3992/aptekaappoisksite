"""Offline verification of source identity, per-variant binding and API fail-closed behavior."""
import asyncio
import copy
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from instruction_profiles import LEAFLET_SECTION_ORDER, PATIENT_LEAFLET
from api import make_router
from api.medication_instructions import (
    REQUIRED_SECTIONS, MedicationInstructionService, instruction_content_hash,
    match_document_to_medication, medication_identity_fingerprint, validate_document,
    plain_text,
)


def medication():
    return {
        "slug": "example-500-tablets", "name": "Пример", "manufacturer": "Завод А",
        "form": "ТАБЛЕТКИ", "dosage": "500 мг", "is_canonical": True,
        "ru_number": "РУ-001",
        "variants": [
            {"gtin": "4600000000001", "ru_number": "РУ-001", "pack_size": "10 шт"},
            {"gtin": "4600000000002", "ru_number": "РУ-002", "pack_size": "10 шт"},
            {"curated_variant_id": "no-identifiers", "pack_size": "20 шт"},
        ],
    }


def document():
    sections = [
        {"key": key, "title": key.replace("_", " "), "text": f"Полный текст источника: {key}."}
        for key in sorted(REQUIRED_SECTIONS)
    ]
    sections.append({"key": "driving", "title": "Вождение", "text": "Раздел источника о вождении."})
    return {
        "id": "document-v1", "title": "Инструкция Пример 500 мг", "registration_numbers": ["РУ-001"],
        "version": "v1", "approved_at": None, "retrieved_at": "2026-11-15T00:00:00Z",
        "source": {
            "name": "Источник", "provider": "offline-fixture", "kind": "licensed_reference",
            "url": "https://example.org/product", "source_product_id": "1",
            "source_document_id": "d1", "rights_basis": "test fixture",
        },
        "original_url": "https://example.org/document.pdf", "original_sha256": "a" * 64,
        "identity": {"trade_name": "Пример", "manufacturers": ["Завод А"]},
        "scopes": [{"ru_number": "РУ-001", "form": "таблетки", "dosage": "500 мг"}],
        "verification": {"status": "verified", "verified_at": "2026-11-15T00:00:00Z", "verified_by": "offline-test"},
        "completeness": {
            "is_complete": True, "full_document_confirmed": True,
            "required_sections": sorted(REQUIRED_SECTIONS), "missing_sections": [],
        },
        "sections": sections, "content_hash": instruction_content_hash(sections),
    }


def leaflet_document():
    doc = document()
    doc["id"] = "leaflet-v1"
    doc["document_type"] = PATIENT_LEAFLET
    doc["sections"] = [{
        "key": "source_preamble", "title": "Начало исходного документа",
        "text": "Листок-вкладыш — информация для пациента\nПример 500 мг, таблетки.\nСохраните этот листок-вкладыш.",
    }] + [
        {"key": key, "title": key, "text": "Полный точный текст соответствующего раздела исходного листка-вкладыша для пациента."}
        for key in LEAFLET_SECTION_ORDER
    ]
    doc["content_hash"] = instruction_content_hash(doc["sections"])
    doc["completeness"]["required_sections"] = list(LEAFLET_SECTION_ORDER)
    return doc


def binding(doc, med):
    match = match_document_to_medication(doc, med)
    return {
        "medicine_slug": med["slug"], "document_id": doc["id"], "active": True,
        "status": "verified", "identity_fingerprint": match["identity_fingerprint"],
        "variant_bindings": match["bindings"],
    }


class Cursor:
    def __init__(self, rows, error=None, gate=None):
        self.rows, self.error, self.gate = rows, error, gate

    def max_time_ms(self, value):
        if value != 1500:
            raise AssertionError("Mongo deadline must be bounded")
        return self

    async def to_list(self, length):
        if self.gate is not None:
            await self.gate.wait()
        if self.error:
            raise self.error
        return copy.deepcopy(self.rows[:length])


class Collection:
    def __init__(self, rows):
        self.rows, self.calls, self.error, self.gate = rows, [], None, None

    def find(self, query, projection):
        self.calls.append(query)

        def matches(row):
            for key, value in query.items():
                if isinstance(value, dict):
                    if row.get(key) not in value["$in"]:
                        return False
                elif row.get(key) != value:
                    return False
            return True

        return Cursor([row for row in self.rows if matches(row)], self.error, self.gate)


class ValidationTests(unittest.TestCase):
    def test_legacy_canonical_document_and_hash_are_byte_compatible(self):
        validated = validate_document(document())
        self.assertNotIn("document_type", validated)
        self.assertEqual(validated["content_hash"], "6e8fd915c26e2ead551dc6ef23224c473c8a5465b136f88882f512af9cfeb398")
        canonical = json.dumps(validated, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), "b5dd8f277f26bf078efba5d99f1e7aaafe492c51be62c797a041fe4ef8726dcb")
        explicit = {**document(), "document_type": "medical_instruction"}
        self.assertEqual(validate_document(explicit), validated)
        self.assertEqual(validate_document(validated), validated)

    def test_patient_leaflet_uses_its_six_sections_and_preserves_explicit_type(self):
        doc = leaflet_document()
        validated = validate_document(doc)
        self.assertEqual(validated["document_type"], PATIENT_LEAFLET)
        self.assertEqual(validate_document(validated), validated)
        self.assertEqual(validated["sections"], doc["sections"])
        self.assertEqual(match_document_to_medication(doc, medication())["covered_variants"], 1)
        self.assertEqual(validated["content_hash"], instruction_content_hash(validated["sections"]))

    def test_leaflet_header_is_required_in_preserved_source_preamble(self):
        for mode in ["absent", "body-citation", "inline-preamble-citation"]:
            doc = leaflet_document()
            doc["sections"] = doc["sections"][1:]
            if mode == "body-citation":
                doc["sections"][0]["text"] += "\nЛисток-вкладыш — информация для пациента"
            if mode == "inline-preamble-citation":
                doc["sections"].insert(0, {"key": "source_preamble", "title": "Начало документа",
                    "text": "В другом источнике упомянут листок-вкладыш, см. ссылку."})
            doc["content_hash"] = instruction_content_hash(doc["sections"])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_document(doc)
        doc = leaflet_document()
        doc["sections"][0]["text"] = "Перед применением препарата полностью прочитайте листок-вкладыш, поскольку он содержит важные сведения."
        doc["content_hash"] = instruction_content_hash(doc["sections"])
        self.assertEqual(validate_document(doc)["document_type"], PATIENT_LEAFLET)

    def test_unknown_document_types_are_rejected(self):
        for value in ["smpc", "leaflet", "", None, {}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_document({**document(), "document_type": value})

    def test_leaflet_missing_heading_body_order_or_duplicate_never_passes(self):
        for key in LEAFLET_SECTION_ORDER:
            doc = leaflet_document()
            doc["sections"] = [section for section in doc["sections"] if section["key"] != key]
            doc["content_hash"] = instruction_content_hash(doc["sections"])
            with self.subTest(missing=key), self.assertRaises(ValueError):
                validate_document(doc)
        for mode in ["heading-only", "order", "duplicate", "no-manual-confirmation", "draft"]:
            doc = leaflet_document()
            if mode == "heading-only":
                doc["sections"][1]["text"] = "1. Что из себя представляет препарат Пример и для чего его применяют"
            if mode == "order":
                doc["sections"][1], doc["sections"][2] = doc["sections"][2], doc["sections"][1]
            if mode == "duplicate":
                doc["sections"].append({**doc["sections"][1], "key": "leaflet_about_2"})
            if mode == "no-manual-confirmation":
                doc["completeness"]["full_document_confirmed"] = False
            if mode == "draft":
                doc["verification"]["status"] = "draft"
            doc["content_hash"] = instruction_content_hash(doc["sections"])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_document(doc)

    def test_number_marker_and_trademark_typography_do_not_create_false_misses(self):
        doc = document()
        doc["identity"]["trade_name"] = "Пример®"
        doc["registration_numbers"] = ["ЛП-№(000015)-(РГ-RU)"]
        doc["scopes"] = [{"ru_number": "ЛП-№(000015)-(РГ-RU)", "form": "таблетки", "dosage": "500 мг"}]
        item = medication()
        item["variants"][0]["ru_number"] = "ЛП-N (000015)-(РГ-RU)"
        self.assertEqual(match_document_to_medication(doc, item)["covered_variants"], 1)
        item["variants"][0]["ru_number"] = "ЛП-N (000016)-(РГ-RU)"
        self.assertFalse(match_document_to_medication(doc, item)["matched"])
        item["variants"][0]["ru_number"] = "ЛП-N (000015)-(ГП-RU)"
        self.assertFalse(match_document_to_medication(doc, item)["matched"])

    def test_official_registration_number_typography_is_preserved(self):
        doc = document()
        official = "ЛП-№(005951)-(РГ-RU)"
        doc["registration_numbers"] = [official]
        doc["scopes"] = [{"gtin": "4600000000001", "ru_number": official}]
        item = medication()
        item["variants"][0]["ru_number"] = official
        valid = validate_document(doc)
        self.assertEqual(valid["registration_numbers"], [official])
        self.assertEqual(validate_document(valid), valid)
        self.assertEqual(match_document_to_medication(valid, item)["covered_variants"], 1)

    def test_html_table_cell_boundaries_are_not_merged(self):
        text = plain_text("<table><tr><th>Доза</th><th>Возраст</th></tr><tr><td>2 мг</td><td>Взрослые</td></tr></table>")
        self.assertIn("Доза | Возраст", text)
        self.assertIn("2 мг | Взрослые", text)
        self.assertNotIn("ДозаВозраст", text)
        self.assertEqual(plain_text(text), text)

    def test_valid_document_retains_every_section_and_does_not_mutate_source(self):
        doc = document()
        original = copy.deepcopy(doc)
        validated = validate_document(doc)
        self.assertEqual(doc, original)
        self.assertEqual(validated["sections"][-1]["key"], "driving")
        self.assertEqual(validate_document(validated), validated)

    def test_draft_partial_unproven_or_changed_content_is_rejected(self):
        changes = [
            lambda doc: doc["verification"].update(status="draft"),
            lambda doc: doc["completeness"].update(full_document_confirmed=False),
            lambda doc: doc["completeness"].update(missing_sections=["driving"]),
            lambda doc: doc.update(version=""),
            lambda doc: doc.update(original_sha256="missing"),
            lambda doc: doc["source"].update(rights_basis=""),
            lambda doc: doc["source"].update(url="javascript:alert(1)"),
            lambda doc: doc["sections"][0].update(text="changed after approval"),
            lambda doc: doc["completeness"].update(required_sections=[{}]),
            lambda doc: doc.update(verification=[]),
        ]
        for change in changes:
            with self.subTest(change=change):
                doc = document()
                change(doc)
                with self.assertRaises(ValueError):
                    validate_document(doc)

    def test_html_is_plain_text_and_script_is_not_published(self):
        doc = document()
        doc["sections"][0]["text"] = "<p>Текст &amp; данные</p><script>alert(1)</script><p>Продолжение</p>"
        doc["content_hash"] = instruction_content_hash(doc["sections"])
        validated = validate_document(doc)
        self.assertEqual(validated["sections"][0]["text"], "Текст & данные\nПродолжение")

    def test_ru_dose_form_manufacturer_and_name_are_exact(self):
        doc, med = document(), medication()
        match = match_document_to_medication(doc, med)
        self.assertEqual(match["covered_variants"], 1)
        self.assertFalse(match["fully_covered"])
        self.assertEqual(match["bindings"][0]["ru_number"], "РУ-001")
        for key, value in (("name", "Пример Форте"), ("dosage", "100 мг"), ("form", "КАПСУЛЫ"), ("manufacturer", "Завод Б")):
            altered = copy.deepcopy(med)
            altered[key] = value
            self.assertFalse(match_document_to_medication(doc, altered)["matched"])
        altered = copy.deepcopy(med)
        altered["variants"][0]["ru_number"] = "РУ-ДРУГОЕ"
        self.assertFalse(match_document_to_medication(doc, altered)["matched"])

    def test_exact_gtin_can_match_without_manufacturer_but_explicit_conflicts_reject(self):
        doc, med = document(), medication()
        doc["identity"]["manufacturers"] = []
        doc["identity"]["holders"] = ["Держатель РУ не является производителем"]
        doc["scopes"] = [{"gtin": "04600000000001"}]
        self.assertEqual(match_document_to_medication(doc, med)["covered_variants"], 1)
        doc["scopes"][0]["dosage"] = "100 мг"
        self.assertFalse(match_document_to_medication(doc, med)["matched"])
        doc["scopes"][0].pop("dosage")
        doc["registration_numbers"] = ["РУ-ДРУГОЕ"]
        self.assertFalse(match_document_to_medication(doc, med)["matched"])
        doc["registration_numbers"] = ["РУ-001"]
        doc["identity"]["manufacturers"] = ["Держатель РУ не является производителем"]
        self.assertFalse(match_document_to_medication(doc, med)["matched"])

    def test_ru_without_manufacturer_requires_explicit_official_registration_scope(self):
        doc = document()
        doc["identity"]["manufacturers"] = []
        with self.assertRaises(ValueError):
            validate_document(doc)
        doc["source"]["kind"] = "official_registry"
        doc["scopes"][0]["manufacturer_scope"] = "registration-wide"
        self.assertEqual(match_document_to_medication(doc, medication())["covered_variants"], 1)

    def test_no_matching_by_pack_size_top_level_ru_or_mnn(self):
        doc, med = document(), medication()
        med["variants"] = [{"pack_size": "10 шт"}]
        med["mnn"] = "Пример"
        self.assertFalse(match_document_to_medication(doc, med)["matched"])


class APITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.med, self.doc = medication(), document()
        self.bindings = Collection([binding(self.doc, self.med)])
        self.documents = Collection([self.doc])
        self.db = SimpleNamespace(medication_instruction_bindings=self.bindings, instruction_documents=self.documents)

    async def test_only_verified_active_variant_bindings_are_public_and_coverage_is_separate(self):
        original = copy.deepcopy(self.med)
        service = MedicationInstructionService(self.db)
        attached = await service.attach(copy.deepcopy(self.med))
        self.assertEqual(self.med, original)
        self.assertEqual(attached["instruction_coverage"], {"total_variants": 3, "covered_variants": 1, "fully_covered": False})
        self.assertEqual(len(attached["instructions"]), 1)
        self.assertEqual(len(attached["instructions"][0]["bindings"]), 1)
        self.assertNotIn("verification", attached["instructions"][0])
        self.assertEqual(set(attached["instructions"][0]["source"]), {"name", "url"})
        self.assertEqual(attached["instructions"][0]["document_type"], "medical_instruction")
        await service.attach(copy.deepcopy(self.med))
        self.assertEqual(len(self.bindings.calls), 1)

    async def test_public_leaflet_type_and_coverage_require_verified_active_document(self):
        doc = leaflet_document()
        self.documents.rows, self.bindings.rows = [doc], [binding(doc, self.med)]
        attached = await MedicationInstructionService(self.db).attach(copy.deepcopy(self.med))
        self.assertEqual(attached["instructions"][0]["document_type"], "patient_leaflet")
        self.assertEqual(attached["instruction_coverage"]["covered_variants"], 1)
        doc["verification"]["status"] = "draft"
        with patch("api.medication_instructions.logger.warning"):
            attached = await MedicationInstructionService(self.db).attach(copy.deepcopy(self.med))
        self.assertEqual(attached["instructions"], [])
        self.assertEqual(attached["instruction_coverage"]["covered_variants"], 0)

    async def test_changed_identity_rejects_stored_binding_and_avoids_old_cache(self):
        service = MedicationInstructionService(self.db)
        await service.attach(copy.deepcopy(self.med))
        changed = copy.deepcopy(self.med)
        changed["variants"][0]["ru_number"] = "РУ-НОВОЕ"
        attached = await service.attach(changed)
        self.assertEqual(attached["instructions"], [])
        self.assertEqual(attached["instruction_coverage"]["covered_variants"], 0)
        self.assertNotEqual(medication_identity_fingerprint(changed), medication_identity_fingerprint(self.med))
        self.assertEqual(len(self.bindings.calls), 2)

    async def test_inactive_draft_partial_and_forged_variant_mapping_are_never_published(self):
        for mode in ("inactive", "draft", "partial", "forged"):
            with self.subTest(mode=mode):
                row, doc = binding(self.doc, self.med), copy.deepcopy(self.doc)
                if mode == "inactive": row["active"] = False
                if mode == "draft": doc["verification"]["status"] = "draft"
                if mode == "partial": doc["completeness"]["full_document_confirmed"] = False
                if mode == "forged": row["variant_bindings"] = [{"pack_size": "10 шт"}]
                self.bindings.rows, self.documents.rows = [row], [doc]
                with patch("api.medication_instructions.logger.warning"):
                    attached = await MedicationInstructionService(self.db).attach(copy.deepcopy(self.med))
                self.assertEqual(attached["instructions"], [])

    async def test_full_coverage_needs_every_variant_with_real_identifier(self):
        doc, med = copy.deepcopy(self.doc), copy.deepcopy(self.med)
        med["variants"] = med["variants"][:2]
        doc["registration_numbers"].append("РУ-002")
        doc["scopes"].append({"ru_number": "РУ-002", "form": "таблетки", "dosage": "500 мг"})
        self.bindings.rows, self.documents.rows = [binding(doc, med)], [doc]
        attached = await MedicationInstructionService(self.db).attach(med)
        self.assertEqual(attached["instruction_coverage"], {"total_variants": 2, "covered_variants": 2, "fully_covered": True})

    async def test_multiple_documents_union_variant_coverage_without_double_counting(self):
        second = copy.deepcopy(self.doc)
        second["id"] = "second-registration"
        second["registration_numbers"] = ["РУ-002"]
        second["scopes"] = [{"ru_number": "РУ-002", "form": "таблетки", "dosage": "500 мг"}]
        self.documents.rows.append(second)
        self.bindings.rows.extend([binding(second, self.med), binding(self.doc, self.med)])
        attached = await MedicationInstructionService(self.db).attach(copy.deepcopy(self.med))
        self.assertEqual(len(attached["instructions"]), 2)
        self.assertEqual(attached["instruction_coverage"], {"total_variants": 3, "covered_variants": 2, "fully_covered": False})

    async def test_parallel_readers_share_one_lookup(self):
        self.bindings.gate = asyncio.Event()
        service = MedicationInstructionService(self.db)
        readers = [asyncio.create_task(service.attach(copy.deepcopy(self.med))) for _ in range(20)]
        while not self.bindings.calls:
            await asyncio.sleep(0)
        self.assertEqual(len(self.bindings.calls), 1)
        self.bindings.gate.set()
        attached = await asyncio.gather(*readers)
        self.assertTrue(all(len(med["instructions"]) == 1 for med in attached))
        self.assertEqual(len(self.documents.calls), 1)

    async def test_database_failure_does_not_poison_cache_or_break_medication(self):
        service = MedicationInstructionService(self.db)
        self.documents.error = RuntimeError("offline failure")
        with self.assertLogs("api.medication_instructions", level="WARNING"):
            attached = await service.attach(copy.deepcopy(self.med))
        self.assertEqual(attached["instructions"], [])
        self.assertEqual(attached["name"], self.med["name"])
        self.documents.error = None
        attached = await service.attach(copy.deepcopy(self.med))
        self.assertEqual(len(attached["instructions"]), 1)
        self.assertEqual(len(self.documents.calls), 2)

    async def test_timeout_does_not_poison_cache_and_capacity_is_bounded(self):
        service = MedicationInstructionService(self.db, capacity=2, load_timeout=0.01)
        self.bindings.gate = asyncio.Event()
        with self.assertLogs("api.medication_instructions", level="WARNING"):
            attached = await service.attach(copy.deepcopy(self.med))
        self.assertEqual(attached["instructions"], [])
        self.bindings.gate.set()
        attached = await service.attach(copy.deepcopy(self.med))
        self.assertEqual(len(attached["instructions"]), 1)
        for index in range(4):
            other = copy.deepcopy(self.med)
            other["slug"] = f"other-{index}"
            await service.attach(other)
        self.assertLessEqual(len(service.cache), 2)

    async def test_force_empty_stock_api_path_still_attaches_instructions(self):
        class Medications:
            async def find_one(inner, query, projection):
                return {**copy.deepcopy(self.med), "force_empty_stock": True}
        self.db.medications = Medications()
        router = make_router(self.db)
        route = next(route.endpoint for route in router.routes if route.path == "/medications/{slug}")
        attached = await route(self.med["slug"], city="msk")
        self.assertEqual(attached["prices_by_city"], {"msk": [], "spb": []})
        self.assertEqual(len(attached["instructions"]), 1)


if __name__ == "__main__":
    unittest.main()
