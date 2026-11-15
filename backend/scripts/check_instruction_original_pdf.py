"""Small subprocess-only PDF structure check; emits no source text or credentials."""
import hashlib
import json
from pathlib import Path
import re
import sys


def check_resources(reader):
    from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, IndirectObject, NullObject, StreamObject
    seen = set()

    def resolve(value):
        if isinstance(value, IndirectObject):
            key = (value.idnum, value.generation)
            if key in seen:
                return value.get_object()
            seen.add(key)
            value = value.get_object()
            if value is None or isinstance(value, NullObject):
                raise ValueError('missing PDF resource reference')
        if isinstance(value, DictionaryObject):
            for child in value.values():
                resolve(child)
        elif isinstance(value, ArrayObject):
            for child in value:
                resolve(child)
        return value

    visited_streams = set()

    def content_operators(contents, resources):
        if contents is None:
            return
        resources = resolve(resources)
        if not isinstance(resources, DictionaryObject):
            raise ValueError('missing PDF resource dictionary')
        if len(contents.get_data()) > 8 * 1024 * 1024:
            raise ValueError('oversized PDF content stream')
        stream = contents if isinstance(contents, ContentStream) else ContentStream(contents, reader)
        for operands, operator in stream.operations:
            if operator not in {b'Do', b'Tf', b'gs'}:
                continue
            category = {b'Do': '/XObject', b'Tf': '/Font', b'gs': '/ExtGState'}[operator]
            mapping = resolve(resources.get(category))
            if not operands or not isinstance(mapping, DictionaryObject) or operands[0] not in mapping:
                raise ValueError('content refers to an absent PDF resource')
            target = resolve(mapping.raw_get(operands[0]))
            if operator == b'Tf' and (not isinstance(target, DictionaryObject)
                    or target.get('/Type') != '/Font'
                    or target.get('/Subtype') not in {'/Type0', '/Type1', '/MMType1', '/Type3', '/TrueType'}):
                raise ValueError('invalid PDF font resource')
            if operator == b'gs' and (not isinstance(target, DictionaryObject)
                    or target.get('/Type') not in {None, '/ExtGState'}):
                raise ValueError('invalid PDF graphics state resource')
            if operator == b'Do':
                if not isinstance(target, StreamObject) or target.get('/Subtype') not in {'/Image', '/Form'}:
                    raise ValueError('invalid PDF XObject')
                if target.get('/Subtype') == '/Form' and id(target) not in visited_streams:
                    visited_streams.add(id(target))
                    content_operators(target, target.get('/Resources', resources))

    for page in reader.pages:
        resources = page.get('/Resources', {})
        resolve(resources)
        content_operators(page.get_contents(), resources)


def alternate_medical_heading(first_page):
    """Recognize one complete observed heading, never a body reference or OHLP."""
    heading = re.search(
        r'^[ \t\u00a0]*инструкция\s+по\s+применению\s+лекарственного\s+'
        r'препарата\s+для\s+медицинского\s+применения[ \t\u00a0]*(?=\r?$)',
        first_page, re.I | re.M)
    # Search the full physical page so cutting at 12k cannot invent a line end.
    # A conflicting OHLP heading can occur later in the PDF drawing order.
    return bool(heading and heading.end() <= 12000 and not re.search(
        r'общая\s+характеристика\s+лекарственного\s+препарата', first_page, re.I))


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        if sys.platform.startswith('linux'):
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        from pypdf import PdfReader
        original = Path(sys.argv[1])
        if original.stat().st_size > 32 * 1024 * 1024:
            return 1
        body = original.read_bytes()
        if not body.startswith(b'%PDF-') or b'%%EOF' not in body[-1024:]:
            return 1
        reader = PdfReader(original, strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 256:
            return 1
        for page in reader.pages:
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > 8 * 1024 * 1024:
                return 1
        check_resources(reader)
        first_page = reader.pages[0].extract_text() or ''
        profile = None
        if re.search(r'листок\s*[-–—]\s*вкладыш', first_page[:12000], re.I):
            profile = 'patient_leaflet'
        elif (re.search(r'инструкци[яи]\s+по\s+медицинскому\s+применению', first_page[:12000], re.I)
              or alternate_medical_heading(first_page)):
            profile = 'medical_instruction'
        print(json.dumps({'original_sha256': hashlib.sha256(body).hexdigest(), 'original_bytes': len(body),
                          'page_count': len(reader.pages), 'all_pages_resolved': True, 'encrypted': False,
                          'header_document_type': profile,
                          # Check the whole bounded physical first page. Source
                          # draw order can place a project label after 12k chars.
                          'header_has_project_marker': bool(re.search(r'проект|draft|project|proekt', first_page, re.I)),
                          'first_page_letters': len(re.findall(r'[A-Za-zА-Яа-яЁё]', first_page))}))
        return 0
    except Exception:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
