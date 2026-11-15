import unittest

from scripts.extract_instruction_pdf import split_sections


class PdfSectionTests(unittest.TestCase):
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
