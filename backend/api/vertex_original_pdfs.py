"""One observed Vertex whole leaflet; no clinical transcription or new aliases.

The combined producer/holder heading and the separate representative website
block are deliberately provider-specific. All other Vertex sources stay draft.
"""
import hashlib
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from .medication_instructions import _identity, _object, _ru
from .manufacturer_original_pdfs import MAX_HTML_BYTES, manufacturer_pdf_url
from .solopharm_original_pdfs import _Links, _DOCUMENT_SUFFIXES, _DOCUMENT_MIME, _MEDICAL_LABEL

MODE = 'vertex_combined_holder_manufacturer_v1'
ORIGINAL_SHA256 = 'b7dd6ba6a2556532e1e7afe9e5df1d65e4040bc6c887a00af3dad30b6092097d'
ORIGINAL_BYTES, PAGE_COUNT = 755457, 8
CURRENT_RU = 'ЛП-№(002790)-(РГ-RU)'
CURRENT_GTIN = '04670033324402'
TRADE_NAME, FORM, DOSAGE = 'Гинкго Билоба', 'капсулы', '80 мг'
PRODUCT_URL = 'https://vertex.spb.ru/products/otc-medicines/ginkgo-biloba/'
PDF_PREFIX = '/upload/medialibrary/'
HREF = '/upload/medialibrary/474/ynjviprwywq0fdgixjdksijs8na3tqeu.pdf'
PDF_URL = 'https://vertex.spb.ru' + HREF
INNER_TEXT, TITLE = 'Информация для пациента', 'ЛВ Гинкго-Билоба.pdf'
ROLE = 'Держатель регистрационного удостоверения и производитель'
COMPANY = 'АО «ВЕРТЕКС»'
GRLS_COMPANY = 'Акционерное общество "ВЕРТЕКС" (АО "ВЕРТЕКС")'
PDF_ADDRESS = '197350, г. Санкт-Петербург, Дорога в Каменку, д. 62, лит. А.'
GRLS_ADDRESS = 'г. Санкт-Петербург, Дорога в Каменку, д.62, лит. А, Россия'
SOURCE_HOST_RAW = 'Веб-сайт: vertex.spb.ru'
PRODUCER_BLOCK = (ROLE + '\nРоссийская Федерация\n' + COMPANY + '\nАдрес: ' + PDF_ADDRESS
    + '\nТел.: 8 (800) 2000 305\nАдрес электронной почты: vertex@vertex.spb.ru'
    + '\nАдрес электронной почты для информирования о нежелательных реакциях:'
    + '\npharmacovigilance@vertex.spb.ru')
REPRESENTATIVE_BLOCK = ('За любой информацией о препарате, а также в случаях возникновения претензий следует'
    '\nобращаться к местному представителю держателя регистрационного удостоверения.'
    '\nРоссийская Федерация\n' + COMPANY + '\nАдрес: ' + PDF_ADDRESS
    + '\nТел.: 8 (800) 2000 305\n' + SOURCE_HOST_RAW)
REPORT_STAMP = 'СООТВЕТСТВУЕТ ЭКСПЕРТНОМУ ОТЧЕТУ от 13.07.2023 № 13167 (ПОСЛЕДОВАТЕЛЬНОСТЬ 0001)'


def _exact_keys(value, keys, field):
    value = _object(value, field)
    if set(value) != set(keys):
        raise ValueError('Vertex ' + field + ' must retain its exact explicit proof shape')
    return value


def _project_guard(*values):
    for value in values:
        value = unicodedata.normalize('NFKC', value)
        for _ in range(4):
            value = unquote(value)
        if re.search(r'проект|draft|project|proekt', value, re.I):
            raise ValueError('Vertex project/draft source requires quarantine')


def vertex_href(product_url, href):
    if not isinstance(href, str) or not 1 <= len(href) <= 2048:
        raise ValueError('a bounded actual Vertex PDF href is required')
    # Check before joining can erase traversal or invent an origin.
    if href.startswith(PDF_PREFIX):
        return manufacturer_pdf_url('vertex', 'https://vertex.spb.ru' + href)
    return manufacturer_pdf_url('vertex', href)


def validate_vertex_product_proof(proof):
    _exact_keys(proof, ('url', 'pdf_url', 'actual_href', 'actual_inner_text',
                        'actual_title', 'html_sha256'), 'product proof')
    if (proof.get('url') != PRODUCT_URL or proof.get('pdf_url') != PDF_URL
            or proof.get('actual_href') != HREF or proof.get('actual_inner_text') != INNER_TEXT
            or proof.get('actual_title') != TITLE or 'actual_label' in proof):
        raise ValueError('Vertex requires the exact observed separate href/title/innerText')
    _project_guard(proof['url'], proof['pdf_url'], proof['actual_href'],
                   proof['actual_inner_text'], proof['actual_title'])


def validate_vertex_product_html(document, body):
    if not isinstance(body, bytes) or not 1 <= len(body) <= MAX_HTML_BYTES:
        raise ValueError('retained Vertex product HTML is absent or too large')
    proof = document['evidence']['product_page']
    validate_vertex_product_proof(proof)
    if hashlib.sha256(body).hexdigest() != proof['html_sha256']:
        raise ValueError('retained Vertex product HTML hash differs')
    # Reuse the unchanged document-capable tag parser, including rejection of
    # conflicting sensitive duplicate attributes before attribute dict collapse.
    parser = _Links()
    parser.feed(body.decode('utf-8'))
    if parser.bases:
        raise ValueError('Vertex product HTML base is not supported')
    candidates, selected = set(), 0
    for link in parser.links:
        attrs, href = link['attrs'], link['href']
        inner_text = ''.join(link['text']).strip()
        label = ' '.join([inner_text, attrs.get('title') or '', attrs.get('aria-label') or '',
                          attrs.get('data-title') or '', href])
        # The retained pilot has no embedded documents. Reject all of them,
        # including same-PDF src: srcdoc can override its displayed content.
        if link['tag'] in ('iframe', 'object', 'embed'):
            raise ValueError('Vertex embedded documents require separate source review')
        if (not _DOCUMENT_SUFFIXES.search(unquote(urlsplit(href).path))
                and not _DOCUMENT_MIME.search(attrs.get('type') or '')
                and not _MEDICAL_LABEL.search(label) and 'download' not in attrs):
            continue
        try:
            target = vertex_href(proof['url'], href)
        except ValueError:
            raise ValueError('unknown or nonallowlisted Vertex product document requires review') from None
        _project_guard(href, target, label)
        candidates.add(target)
        if href == proof['actual_href'] and target == proof['pdf_url']:
            if (link.get('embedded') or inner_text != proof['actual_inner_text']
                    or attrs != {'href': HREF, 'title': TITLE}):
                raise ValueError('actual Vertex anchor or separate label provenance differs')
            selected += 1
    if selected != 1 or candidates != {proof['pdf_url']}:
        raise ValueError('one actual Vertex instruction anchor and sole document version are required')


def vertex_scope_gtin(scope, number):
    if (number != _ru(CURRENT_RU) or scope.get('gtin') != CURRENT_GTIN
            or _identity(scope.get('form')) != _identity(FORM)
            or _identity(scope.get('dosage')) != _identity(DOSAGE)):
        raise ValueError('Vertex supports only the exact reviewed current Ginkgo80mg GTIN scope')
    return CURRENT_GTIN


def validate_vertex_physical_proof(document, manufacturer, grls_parts):
    if (document.get('document_type') != 'patient_leaflet'
            or document.get('original_sha256') != ORIGINAL_SHA256
            or document.get('original_bytes') != ORIGINAL_BYTES or document.get('page_count') != PAGE_COUNT
            or document.get('revision_date') is not None or document.get('approved_at') is not None
            or document.get('version') != 'sha256:' + ORIGINAL_SHA256
            or _identity(document.get('identity', {}).get('trade_name')) != _identity(TRADE_NAME)
            or len(document.get('scopes') or []) != 1):
        raise ValueError('Vertex supports the unchanged reviewed8page Ginkgo whole leaflet only')
    if (manufacturer.get('raw') != COMPANY or manufacturer.get('raw_role') != ROLE
            or manufacturer.get('physical_address_raw') != PDF_ADDRESS
            or manufacturer.get('page_indices') != [8]
            or grls_parts[0].strip() != 'Производитель (готовой ЛФ)'
            or grls_parts[1].strip() != GRLS_COMPANY or grls_parts[2].strip() != GRLS_ADDRESS):
        raise ValueError('Vertex requires the exact combined role and current finished factory62litA')
    evidence = document['evidence']
    if evidence['current_grls_registration'].get('holder') != GRLS_COMPANY:
        raise ValueError('Vertex combined holder/manufacturer block must match the current literal holder too')
    fields = evidence['visual_identity']['fields']
    if any(fields[key]['page_indices'] != pages for key, pages in
           [('registration_number', [1]), ('trade_name', [1, 7]), ('form', [1, 7]), ('dosage', [1, 7])]):
        raise ValueError('Vertex physical identity pages must match the actual reviewed leaflet')
    proof = _exact_keys(evidence.get('vertex_physical_proof'),
        ('mode', 'original_sha256', 'page_count', 'producer', 'publisher', 'allpage_project_review',
         'source_version_context'), 'physical proof')
    if (proof['mode'] != MODE or proof['original_sha256'] != ORIGINAL_SHA256
            or type(proof['page_count']) is not int or proof['page_count'] != PAGE_COUNT):
        raise ValueError('Vertex physical proof mode or original identity differs')
    for key, raw in [('producer', PRODUCER_BLOCK), ('publisher', REPRESENTATIVE_BLOCK)]:
        block = _exact_keys(proof[key], ('raw_block', 'company_raw', 'address_raw',
            'page_indices', 'original_sha256'), key + ' block')
        if (block['raw_block'] != raw or block['company_raw'] != COMPANY
                or block['address_raw'] != PDF_ADDRESS or block['page_indices'] != [8]
                or any(type(p) is not int for p in block['page_indices'])
                or block['original_sha256'] != ORIGINAL_SHA256):
            raise ValueError('Vertex requires separate actual producer and same-site representative blocks')
        _project_guard(block['raw_block'])
    project = _exact_keys(proof['allpage_project_review'],
        ('original_sha256', 'page_indices', 'all_pages_visually_checked', 'project_marker_found'), 'allpage project review')
    if (project['original_sha256'] != ORIGINAL_SHA256 or project['page_indices'] != list(range(1, 9))
            or any(type(p) is not int for p in project['page_indices'])
            or project['all_pages_visually_checked'] is not True or project['project_marker_found'] is not False):
        raise ValueError('Vertex requires actual all8page visual project-marker review')
    version = _exact_keys(proof['source_version_context'], ('report_stamp_raw',
        'grls_normative_documentation_raw', 'leaflet_revision_heading_raw', 'leaflet_revision_value',
        'no_newest_version_assertion', 'competing_retained_version_found'), 'source version context')
    normative = evidence['current_grls_registration'].get('normative_documentation')
    if (version['report_stamp_raw'] != REPORT_STAMP
            or not isinstance(normative, str) or not normative.strip() or len(normative) > 8000
            or version['grls_normative_documentation_raw'] != normative
            or version['leaflet_revision_heading_raw'] != 'Листок-вкладыш пересмотрен'
            or version['leaflet_revision_value'] is not None or version['no_newest_version_assertion'] is not True
            or version['competing_retained_version_found'] is not False):
        raise ValueError('Vertex reportstamp and normative context must remain separate from unknown revision')
