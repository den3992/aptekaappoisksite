import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from instruction_profiles import LEAFLET_SECTION_ORDER, PATIENT_LEAFLET, document_type
from scripts.extract_instruction_pdf import analyze_text, extract_pdf, split_sections


LEAFLET_HEADINGS = [
    "1. Что из себя представляет препарат Пример и для чего его применяют",
    "2. О чем следует знать перед приемом препарата Пример",
    "3. Прием препарата Пример", "4. Возможные нежелательные реакции",
    "5. Хранение препарата Пример", "6. Содержимое упаковки и прочие сведения",
]
LEAFLET_BODY = "Точный текст соответствующего раздела источника, который сохраняется полностью без изменения смысла."


def leaflet_text(*, contents=True, heading_order=None):
    lines = ["Листок-вкладыш — информация для пациента", "Препарат Пример 500 мг"]
    if contents:
        lines += ["Содержание листка-вкладыша", *LEAFLET_HEADINGS]
    for index in heading_order if heading_order is not None else range(6):
        lines += [LEAFLET_HEADINGS[index], LEAFLET_BODY]
        if index == 1:
            lines += ["Беременность и грудное вскармливание", "Точный дополнительный текст источника о беременности.",
                      "Дети и подростки", "Точный дополнительный текст источника о применении у детей."]
    return "\n".join(lines)


class PdfSectionTests(unittest.TestCase):
    def test_leaflet_six_bodies_use_profile_and_keep_contents_and_all_extra_text(self):
        text = leaflet_text()
        report = analyze_text(text)
        self.assertEqual(report["document_type"], PATIENT_LEAFLET)
        self.assertEqual(report["missing_sections"], [])
        self.assertEqual(report["section_review_reasons"], [])
        self.assertEqual([section["key"] for section in report["sections"]], ["source_preamble", *LEAFLET_SECTION_ORDER])
        self.assertEqual([line.strip() for line in text.splitlines() if line.strip()],
                         [line.strip() for section in report["sections"] for line in section["text"].splitlines() if line.strip()])

    def test_contents_only_with_or_without_page_leaders_does_not_become_full_leaflet(self):
        for ending in ["", " .... 3", " 3"]:
            text = "Листок-вкладыш\nСодержание листка-вкладыша\n" + "\n".join(heading + ending for heading in LEAFLET_HEADINGS)
            report = analyze_text(text)
            self.assertNotEqual(report["document_type"], PATIENT_LEAFLET)
            self.assertEqual(report["candidate_document_type"], PATIENT_LEAFLET)
            self.assertTrue(report["missing_sections"])
            self.assertTrue(report["section_review_reasons"])

    def test_missing_body_section_is_not_complete_even_if_its_title_is_in_contents(self):
        for index in range(6):
            report = analyze_text(leaflet_text(heading_order=[number for number in range(6) if number != index]))
            self.assertEqual(report["document_type"], PATIENT_LEAFLET)
            self.assertIn(LEAFLET_SECTION_ORDER[index], report["missing_sections"])
            self.assertTrue(report["section_review_reasons"])

    def test_duplicate_or_out_of_order_body_headings_require_review(self):
        for order in [[0, 1, 2, 3, 4, 5, 0], [1, 0, 2, 3, 4, 5]]:
            report = analyze_text(leaflet_text(heading_order=order))
            self.assertEqual(report["document_type"], PATIENT_LEAFLET)
            self.assertTrue(report["section_review_reasons"])

    def test_marker_only_in_body_citation_cannot_classify_leaflet(self):
        text = leaflet_text(contents=False).replace("Листок-вкладыш — информация для пациента\n", "")
        text = text.replace(LEAFLET_BODY, LEAFLET_BODY + "\nЛисток-вкладыш упомянут здесь как ссылка.", 1)
        self.assertEqual(analyze_text(text)["document_type"], "medical_instruction")
        self.assertEqual(analyze_text("Листок-вкладыш\nНет разделов.")["document_type"], "medical_instruction")

    def test_wrapped_main_heading_is_preserved_and_standard_reading_header_is_valid(self):
        text = leaflet_text().replace("Листок-вкладыш — информация для пациента", "Перед приемом препарата полностью прочитайте листок-вкладыш,")
        text = text.replace(LEAFLET_HEADINGS[0], "1. Что из себя представляет препарат Пример\nи для чего его применяют")
        report = analyze_text(text)
        self.assertEqual(report["document_type"], PATIENT_LEAFLET)
        self.assertEqual(report["missing_sections"], [])
        self.assertFalse(report["section_review_reasons"])
        self.assertIn("Пример\nи для чего", report["sections"][1]["text"])

    def test_scanned_page_keeps_extraction_in_review_even_with_six_text_sections(self):
        pages = [SimpleNamespace(extract_text=lambda: leaflet_text()), SimpleNamespace(extract_text=lambda: "1")]
        reader = SimpleNamespace(is_encrypted=False, pages=pages)
        with tempfile.TemporaryDirectory() as directory, patch("pypdf.PdfReader", return_value=reader):
            path = Path(directory) / "fixture.pdf"
            path.write_bytes(b"%PDF-offline-fixture")
            report = extract_pdf(path)
        self.assertEqual(report["document_type"], PATIENT_LEAFLET)
        self.assertEqual(report["missing_sections"], [])
        self.assertEqual(report["pages_requiring_review"], [2])
        self.assertFalse(report["extraction_has_required_sections"])
        self.assertFalse(report["full_document_confirmed"])
        self.assertEqual(report["verification_status"], "draft")

    def test_unknown_profile_is_rejected_in_pure_module(self):
        with self.assertRaises(ValueError):
            document_type("smpc")

    def test_exact_source_text_and_unknown_sections_survive_splitting(self):
        text = "Официальный документ\nСостав:\nДанные 0,1 мг.\nОсобый раздел производителя\nЕго точный текст.\nСпособ применения и дозы\nТекст источника.\nУсловия хранения\nТочный текст хранения."
        sections = split_sections(text)
        self.assertEqual([section["key"] for section in sections], ["source_preamble", "composition", "administration", "storage"])
        source_lines = [line.strip() for line in text.splitlines() if line.strip()]
        extracted_lines = [line.strip() for section in sections for line in section["text"].splitlines() if line.strip()]
        self.assertEqual(source_lines, extracted_lines)

    def test_repeated_headers_get_distinct_keys_without_merging_editions(self):
        sections = split_sections("Показания к применению\nПервый источник.\nПоказания к применению\nВторой фрагмент.")
        self.assertEqual([section["key"] for section in sections], ["indications", "indications_2"])

    def test_reference_in_paragraph_does_not_create_a_false_section(self):
        sections = split_sections("Показания к применению см. в разделе ниже.\nУсловия хранения не изменяются при транспортировке.")
        self.assertEqual([section["key"] for section in sections], ["source_preamble"])


if __name__ == "__main__":
    unittest.main()
