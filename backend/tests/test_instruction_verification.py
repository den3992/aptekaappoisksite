"""Real generated PDF fixtures; no medical advice, network or production writes."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from api.medication_instructions import validate_document
from scripts.verify_instruction_pdf import (
    PdfInstructionVerifier, canonical_hash, comparison_text, file_hash, inspect_pdf, number_tokens,
)
from test_medication_instructions import document, medication


HEADINGS = [
    "Состав", "Показания к применению", "Противопоказания", "Способ применения и дозы",
    "Побочное действие", "Взаимодействие с другими лекарственными средствами",
    "Передозировка", "Условия хранения",
]
BODY = [
    "Тестовый исходный текст раздела. Это искусственный пример проверки копирования.",
    "Числа источника: -0,03 мг; 30%; 1-2; 300 мг/г. Не является медицинской инструкцией.",
]
RU = "ЛП-N (000015)-(РГ-RU)"


def create_pdf(path, *, token="reference", hidden=False, table=False, columns=False,
               blank_page=False, partial=False, clipped=False, white_overlay=False,
               full_page_clip=False, white_background=False, out_of_order=False):
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    font = next((path for path in candidates if Path(path).is_file()), None)
    if font is None:
        raise unittest.SkipTest("Cyrillic TrueType test font is required")
    if "VerifierFixture" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("VerifierFixture",font))
    c = canvas.Canvas(str(path),pagesize=(595,842),invariant=1)
    if white_background:
        c.setFillColorRGB(1,1,1)
        c.rect(0,0,595,842,stroke=0,fill=1)
        c.setFillColorRGB(0,0,0)
    if full_page_clip:
        clip = c.beginPath()
        clip.rect(0,0,595,842)
        c.clipPath(clip,stroke=0,fill=0)
    c.setFont("VerifierFixture",10)
    y = 810
    for line in ["УТВЕРЖДЕНО",RU,"Пример","ТАБЛЕТКИ","500 мг","Завод А",token+" 1234567890"]:
        c.drawString(45,y,line)
        y -= 12
    if clipped:
        clip = c.beginPath()
        clip.rect(40,40,20,20)
        c.clipPath(clip,stroke=0,fill=0)
    for heading in HEADINGS[:4] if partial else HEADINGS:
        y -= 8
        c.drawString(45,y,heading)
        y -= 12
        for line in BODY:
            c.drawString(45,y,line)
            y -= 12
    if hidden:
        text = c.beginText(45,50)
        text.setTextRenderMode(3)
        text.textLine("hidden source identity")
        c.drawText(text)
    if table:
        c.rect(45,55,400,30)
        c.line(200,55,200,85)
    if columns:
        c.drawString(45,50,"10 мг")
        c.drawString(300,50,"300 мг")
        c.drawString(45,35,"20 мг")
        c.drawString(300,35,"500 мг")
    if white_overlay:
        c.setFillColorRGB(1,1,1)
        c.rect(0,0,595,842,stroke=0,fill=1)
    if out_of_order:
        c.drawString(45,30,"Второй абзац 20 мг.")
        c.drawString(45,45,"Первый абзац 10 мг.")
    if blank_page:
        c.showPage()
    c.save()


class VerificationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.reference, self.target = self.folder/"reference.pdf", self.folder/"target.pdf"
        create_pdf(self.reference)
        create_pdf(self.target,token="different target")
        self.calibration = {"schema_version":1,"families":[{
            "family_id":"fixture-simple-one-column",
            "references":[{
                "path":str(self.reference),"original_sha256":file_hash(self.reference),
                "all_pages_visually_reviewed":True,"reviewer":"synthetic-fixture-test",
                "reviewed_at":"2026-11-15T00:00:00Z",
            }],
        }]}
        self.verifier = PdfInstructionVerifier(self.calibration)
        self.med = medication()
        self.med["variants"][0]["ru_number"] = RU
        self.doc = document()
        self.doc["registration_numbers"] = [RU]
        self.doc["source"]["kind"] = "official_registry"
        self.doc["identity"]["form"], self.doc["identity"]["dosage"] = self.med["form"],self.med["dosage"]
        self.doc["scopes"] = [{"ru_number":RU,"form":self.med["form"],"dosage":self.med["dosage"]}]
        self.doc["original_sha256"] = file_hash(self.target)
        self.doc["verification"]["status"] = "draft"
        self.proof = {
            "country":"RU","document_kind":"USAGE_INSTRUCTION",
            "registration_current":True,"document_current":True,
            "original_sha256":file_hash(self.target),"metadata_sha256":"a"*64,
            "version":self.doc["version"],"source_url":self.doc["source"]["url"],
            "original_url":self.doc["original_url"],"source_document_id":self.doc["source"]["source_document_id"],
            "registration_number":RU,"trade_name":self.med["name"],"form":self.med["form"],
            "dosage":self.med["dosage"],"manufacturers":[self.med["manufacturer"]],
            "approval_marker":"УТВЕРЖДЕНО",
        }

    def verify(self):
        return self.verifier.verify(self.target,self.doc,self.med,self.proof)

    def replace_target(self,**options):
        create_pdf(self.target,token="different target",**options)
        self.doc["original_sha256"] = self.proof["original_sha256"] = file_hash(self.target)

    def assert_draft(self,result,reason):
        self.assertEqual(result["verification_status"],"draft",result["evidence"]["reasons"])
        self.assertIsNone(result["document"])
        self.assertTrue(any(reason in value for value in result["evidence"]["reasons"]),result["evidence"]["reasons"])

    def test_two_different_actual_pdfs_in_calibrated_family_have_a_working_positive_path(self):
        self.assertNotEqual(file_hash(self.reference),file_hash(self.target))
        result = self.verify()
        self.assertEqual(result["verification_status"],"verified",result["evidence"]["reasons"])
        doc = result["document"]
        self.assertEqual(doc["verification"]["method"],"deterministic_pdf")
        self.assertEqual(validate_document(doc),doc)
        self.assertEqual(doc["verification"]["evidence_sha256"],canonical_hash(result["evidence"]))
        self.assertTrue(all(page["checks_passed"] for page in result["evidence"]["pages"]))
        self.assertEqual(doc["verification"]["reference_sha256"],[file_hash(self.reference)])
        self.assertNotIn("manual",doc["verification"]["verified_by"])
        source = inspect_pdf(self.target)["text"]
        published = "\n".join(section["text"] for section in doc["sections"])
        self.assertEqual(comparison_text(source),comparison_text(published))
        self.assertEqual(number_tokens(source),number_tokens(published))

    def test_legacy_canonical_document_is_byte_compatible(self):
        doc = validate_document(document())
        self.assertNotIn("method",doc["verification"])
        encoded = json.dumps(doc,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
        self.assertEqual(hashlib.sha256(encoded).hexdigest(),"b5dd8f277f26bf078efba5d99f1e7aaafe492c51be62c797a041fe4ef8726dcb")

    def test_proven_full_page_clip_and_white_background_are_not_blanket_rejected(self):
        self.replace_target(full_page_clip=True,white_background=True)
        result = self.verify()
        self.assertEqual(result["verification_status"],"verified",result["evidence"]["reasons"])

    def test_pattern_resource_nested_raster_is_detected_even_when_page_images_misses_it(self):
        from pypdf import PdfReader,PdfWriter
        from pypdf.generic import NameObject,NumberObject,ArrayObject,DictionaryObject,DecodedStreamObject
        writer = PdfWriter()
        writer.append(PdfReader(self.target))
        image = DecodedStreamObject()
        image.set_data(b"\x00\x00\x00")
        image.update({NameObject("/Type"):NameObject("/XObject"),NameObject("/Subtype"):NameObject("/Image"),
                      NameObject("/Width"):NumberObject(1),NameObject("/Height"):NumberObject(1),
                      NameObject("/ColorSpace"):NameObject("/DeviceRGB"),NameObject("/BitsPerComponent"):NumberObject(8)})
        pattern = DecodedStreamObject()
        pattern.set_data(b"q /I Do Q")
        pattern.update({NameObject("/Type"):NameObject("/Pattern"),NameObject("/PatternType"):NumberObject(1),
                        NameObject("/PaintType"):NumberObject(1),NameObject("/TilingType"):NumberObject(1),
                        NameObject("/BBox"):ArrayObject([NumberObject(v) for v in (0,0,1,1)]),
                        NameObject("/XStep"):NumberObject(1),NameObject("/YStep"):NumberObject(1),
                        NameObject("/Resources"):DictionaryObject({NameObject("/XObject"):DictionaryObject({
                            NameObject("/I"):writer._add_object(image),
                        })})})
        resources = writer.pages[0]["/Resources"]
        resources[NameObject("/Pattern")] = DictionaryObject({NameObject("/P"):writer._add_object(pattern)})
        writer.write(self.target)
        self.doc["original_sha256"] = self.proof["original_sha256"] = file_hash(self.target)
        self.assert_draft(self.verify(),"nested raster")

    def test_unreviewed_changed_or_unsupported_calibration_cannot_approve(self):
        for key,value in [("all_pages_visually_reviewed",False),("original_sha256","b"*64),("reviewer","")]:
            calibration = copy.deepcopy(self.calibration)
            calibration["families"][0]["references"][0][key] = value
            with self.subTest(key=key),self.assertRaises(ValueError):
                PdfInstructionVerifier(calibration)
        create_pdf(self.reference,hidden=True)
        self.calibration["families"][0]["references"][0]["original_sha256"] = file_hash(self.reference)
        with self.assertRaisesRegex(ValueError,"geometry"):
            PdfInstructionVerifier(self.calibration)

    def test_unknown_font_or_producer_family_remains_draft(self):
        actual = inspect_pdf(self.target)
        actual["family_sha256"] = "f"*64
        with patch("scripts.verify_instruction_pdf.inspect_pdf",return_value=actual):
            self.assert_draft(self.verify(),"family is not calibrated")

    def test_hidden_clipped_tables_columns_and_text_covering_paint_fail_closed(self):
        for option,reason in [("hidden","rendering"),("clipped","clipping"),("table","table"),
                              ("columns","borderless"),("white_overlay","covering")]:
            with self.subTest(option=option):
                self.replace_target(**{option:True})
                self.assert_draft(self.verify(),reason)

    def test_missing_source_sections_and_scanned_or_empty_pages_are_not_complete(self):
        self.replace_target(partial=True)
        self.assert_draft(self.verify(),"required source sections")
        self.replace_target(blank_page=True)
        # Reportlab doesn't emit a trailing unpainted page. Add one explicitly.
        from pypdf import PdfReader,PdfWriter
        writer = PdfWriter()
        writer.append(PdfReader(self.target))
        writer.add_blank_page(595,842)
        writer.write(self.target)
        self.doc["original_sha256"] = self.proof["original_sha256"] = file_hash(self.target)
        self.assert_draft(self.verify(),"insufficient")

    def test_crop_box_and_out_of_order_text_fail_closed(self):
        self.replace_target(out_of_order=True)
        self.assert_draft(self.verify(),"ordered parser")
        self.replace_target()
        from pypdf import PdfReader,PdfWriter
        writer = PdfWriter()
        writer.append(PdfReader(self.target))
        writer.pages[0].cropbox.upper_right = (400,700)
        writer.write(self.target)
        self.doc["original_sha256"] = self.proof["original_sha256"] = file_hash(self.target)
        self.assert_draft(self.verify(),"cropped")

    def test_independent_extractor_losing_negative_dose_is_rejected_by_actual_verifier(self):
        import pdfplumber.page
        actual = pdfplumber.page.Page.extract_text
        def broken(page,*args,**kwargs):
            return actual(page,*args,**kwargs).replace("-0,03","0,03")
        with patch("pdfplumber.page.Page.extract_text",broken):
            self.assert_draft(self.verify(),"ordered source numbers")

    def test_identity_current_version_and_provenance_are_required(self):
        for key,value in [("registration_current",False),("document_current",False),("country","KZ"),
                          ("dosage","300 мг"),("registration_number","ЛП-N (000016)-(РГ-RU)"),
                          ("version","unproven"),("original_sha256","b"*64),("manufacturers",["Держатель РУ"]),
                          ("approval_marker","Пример")]:
            original = copy.deepcopy(self.proof)
            self.proof[key] = value
            with self.subTest(key=key):
                self.assertEqual(self.verify()["verification_status"],"draft")
            self.proof = original

    def test_lost_minus_decimal_comma_unit_or_paragraph_order_never_agrees(self):
        text = "A -0,03 мг 300 мг/г\nB 30% 1-2"
        for changed in [text.replace("-0","0"),text.replace("0,03","0,3"),text.replace("мг/г","мг"),
                        "\n".join(reversed(text.splitlines()))]:
            self.assertNotEqual(comparison_text(text),comparison_text(changed))
        self.assertNotEqual(number_tokens(text),number_tokens(text.replace("-0","0")))
        self.assertEqual(comparison_text("A\n\nB  3"),"A B 3")
        self.assertNotEqual(comparison_text("A 1 0 мг"),comparison_text("A 10 мг"))
        self.assertNotEqual(comparison_text("A\n2\nB"),comparison_text("A\nB"))

    def test_agreement_before_validator_does_not_hide_final_text_loss(self):
        from api.medication_instructions import validate_document as real_validate
        def losing(document):
            doc = real_validate(document)
            doc["sections"][-1]["text"] = doc["sections"][-1]["text"].replace("300","30")
            return doc
        with patch("scripts.verify_instruction_pdf.validate_document",side_effect=losing):
            self.assert_draft(self.verify(),"final canonical sections")

    def test_optional_evidence_rejects_missing_hash_different_original_or_manual_claim(self):
        doc = self.verify()["document"]
        for field,value in [("evidence_sha256",""),("original_sha256","b"*64),
                            ("page_count",True),("verified_by","manual reviewer"),("reference_sha256",[])]:
            changed = copy.deepcopy(doc)
            changed["verification"][field] = value
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate_document(changed)


if __name__=="__main__":
    unittest.main()
