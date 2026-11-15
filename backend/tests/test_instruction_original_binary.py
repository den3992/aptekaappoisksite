"""Real PDF structure regressions, including unresolved scan and nested form data."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.import_medication_originals import validate_archive


def pdf_bytes(resources='<< >>', content=b'q Q', extra_objects=()):
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               ('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources ' + resources + ' /Contents 4 0 R >>').encode(),
               b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream', *extra_objects]
    data = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(str(number).encode() + b' 0 obj\n' + body + b'\nendobj\n')
    xref = len(data)
    data.extend(b'xref\n0 ' + str(len(offsets)).encode() + b'\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(b'trailer\n<< /Size ' + str(len(offsets)).encode() + b' /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n')
    return bytes(data)


def project_pdf_bytes():
    resources = '<< /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>'
    return pdf_bytes(resources, b'BT /F1 12 Tf (' + b'x' * 12050 + b'_PROJECT_final_) Tj ET')


class OriginalBinaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'original.pdf'

    def check(self, body, page_count=1):
        self.path.write_bytes(body)
        return validate_archive({'original_bytes': len(body), 'page_count': page_count,
                                 'original_sha256': hashlib.sha256(body).hexdigest()}, self.path)

    def test_complete_simple_pdf_resolves(self):
        self.check(pdf_bytes())

    def test_wrong_page_count_and_fake_eof_pdf_fail(self):
        with self.assertRaises(ValueError):
            self.check(pdf_bytes(), page_count=2)
        with self.assertRaises(ValueError):
            self.check(b'%PDF-1.4\nnot a document\n%%EOF\n')

    def test_missing_scan_image_reference_is_not_a_complete_original(self):
        with self.assertRaises(ValueError):
            self.check(pdf_bytes('<< /XObject << /Im0 999999 0 R >> >>', b'/Im0 Do'))

    def test_missing_font_and_missing_xobject_names_fail(self):
        for content in [b'/Missing Do', b'BT /Missing 12 Tf ET', b'/Missing gs']:
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.check(pdf_bytes(content=content))

    def test_nested_form_missing_font_reference_fails(self):
        content = b'BT /F1 12 Tf ET'
        form = (b'<< /Type /XObject /Subtype /Form /BBox [0 0 100 100] '
                b'/Resources << /Font << /F1 999999 0 R >> >> /Length ' + str(len(content)).encode()
                + b' >>\nstream\n' + content + b'\nendstream')
        with self.assertRaises(ValueError):
            self.check(pdf_bytes('<< /XObject << /Fm 5 0 R >> >>', b'/Fm Do', [form]))

    def test_font_and_graphics_state_resource_types_must_resolve(self):
        for resources, content in [
            ('<< /Font << /F1 42 >> >>', b'BT /F1 12 Tf ET'),
            ('<< /Font << /F1 << /Type /Font /Subtype /Image >> >> >>', b'BT /F1 12 Tf ET'),
            ('<< /ExtGState << /G1 42 >> >>', b'/G1 gs'),
        ]:
            with self.subTest(resources=resources), self.assertRaises(ValueError):
                self.check(pdf_bytes(resources, content))
        self.check(pdf_bytes('<< /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>',
                             b'BT /F1 12 Tf (fixture) Tj ET'))
        self.check(pdf_bytes('<< /ExtGState << /G1 << /Type /ExtGState /ca 1 >> >> >>', b'/G1 gs'))

    def test_valid_form_and_image_resources_pass(self):
        for subtype, extra in [
            ('Form', b'/BBox [0 0 100 100] /Resources << >>'),
            ('Image', b'/Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8'),
        ]:
            content = b'q Q' if subtype == 'Form' else b'\x00'
            resource = (b'<< /Type /XObject /Subtype /' + subtype.encode() + b' ' + extra
                        + b' /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream')
            with self.subTest(subtype=subtype):
                self.check(pdf_bytes('<< /XObject << /Obj 5 0 R >> >>', b'/Obj Do', [resource]))

    def test_truncated_original_is_rejected_before_any_parser(self):
        with self.assertRaisesRegex(ValueError, 'EOF'):
            self.check(pdf_bytes()[:-20])

    def test_actual_first_page_project_after_twelve_thousand_chars_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'physical first page.*project/draft'):
            self.check(project_pdf_bytes())

    def test_missing_or_nonboolean_actual_project_check_is_rejected(self):
        body = pdf_bytes()
        result = {'original_sha256': hashlib.sha256(body).hexdigest(), 'original_bytes': len(body),
                  'page_count': 1, 'all_pages_resolved': True, 'encrypted': False}
        for fields in [{}, {'header_has_project_marker': None}, {'header_has_project_marker': 0},
                       {'header_has_project_marker': 'false'}]:
            child = Mock(returncode=0)
            child.poll.return_value = 0
            child.communicate.return_value = (json.dumps({**result, **fields}).encode(), None)
            with self.subTest(fields=fields), patch('scripts.import_medication_originals.subprocess.Popen', return_value=child):
                with self.assertRaisesRegex(ValueError, 'physical first page.*project/draft'):
                    self.check(body)


if __name__ == '__main__':
    unittest.main()
