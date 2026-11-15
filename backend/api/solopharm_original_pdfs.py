"""Narrow observed Solopharm whole originals; no inferred label or clinical text.

Only the retained public Solopharm product/PDF namespaces and the physically
reviewed Grotex finished-manufacturer block are covered by this profile.
"""
import hashlib
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from .manufacturer_original_pdfs import MAX_HTML_BYTES, _legal, _literal, manufacturer_pdf_url

DATA_TITLE = 'Читать инструкцию'
PDF_PREFIX = '/storage/files/products/'
# These are the actual observed literals. This is not an address normalizer or
# permission to associate another factory/site with the short company name.
PDF_MANUFACTURER = 'ООО «Гротекс»'
PDF_ADDRESS = 'Россия, 195279, Санкт-Петербург, Индустриальный пр., д.71, к.2, лит.А'
GRLS_COMPANY = 'Общество с ограниченной ответственностью "Гротекс" (ООО "Гротекс")'
GRLS_ADDRESS = '195279, г. Санкт-Петербург, Индустриальный проспект, д. 71, корп. 2, лит. А, Россия'
# Opt-in literal typography for exactly two independently reviewed originals.
# The SHA and physical page pins are the admission boundary, not examples that
# permit another document/company/site or a general address normalization.
GROTEX_ADDRESS_PROFILE = 'solopharm_grotex_71_2_A_typography_v1'
_GROTEX_ADDRESS_TUPLES = {
    'atrevozol_country_separate_full_pr': (
        'f712fb4233228757dc6d3f69857c4c2e13fbb0f549102b32e667c0adf5ec89d9', 7, 7,
        'Российская Федерация',
        '195279, г. Санкт-Петербург, Индустриальный проспект, д. 71, корп. 2, лит. А',
        'Производитель\nРоссийская Федерация\nООО «Гротекс»\n'
        '195279, г. Санкт-Петербург, Индустриальный проспект, д. 71, корп. 2, лит. А',
    ),
    'pentox_country_companyline_short_pr': (
        'ab75a66b13554ab76142b16a71ccc423d386334beff8a961a1897e17d85d8e0c', 10, 10,
        'Россия',
        '195279, Санкт-Петербург, Индустриальный пр., д. 71, корп. 2, лит. А',
        'Производитель\nООО «Гротекс», Россия\n'
        '195279, Санкт-Петербург, Индустриальный пр., д. 71, корп. 2, лит. А',
    ),
}
_DOCUMENT_SUFFIXES = re.compile(r'\.(?:pdf|docx?|od[ft]|rtf|xlsx?|pptx?|txt|zip)(?:$|[/;])', re.I)
_DOCUMENT_MIME = re.compile(r'^(?:application/(?:pdf|msword|rtf|postscript)|text/(?:plain|rtf|csv))(?:\s*;|$)|officedocument|opendocument|vnd\.ms-(?:excel|powerpoint)', re.I)
_MEDICAL_LABEL = re.compile(r'инструкц|instruk|instruction|лист[ао]к[\s-]*вкладыш|информаци[яю]\s+для\s+(?:пациент|работник)|общ[а-я]+\s+характеристик|(?<!\w)(?:ОХЛП|PIL|SmPC)(?!\w)|leaflet', re.I)


def solopharm_href(product_url, href):
    """Validate raw links before joining could erase a traversal component."""
    if not isinstance(href, str) or not 1 <= len(href) <= 2048:
        raise ValueError('a bounded actual Solopharm PDF href is required')
    if href.startswith(PDF_PREFIX):
        return manufacturer_pdf_url('solopharm', 'https://solopharm.com' + href)
    return manufacturer_pdf_url('solopharm', href)


def _project_guard(*values):
    for value in values:
        value = unicodedata.normalize('NFKC', value)
        for _ in range(4):
            value = unquote(value)
        if re.search(r'проект|draft|project|proekt', value, re.I):
            raise ValueError('Solopharm project/draft source requires quarantine')


def validate_solopharm_product_proof(proof):
    if proof.get('actual_inner_text') != '' or proof.get('actual_data_title') != DATA_TITLE:
        raise ValueError('Solopharm requires its actual empty innerText and separate data-title attribute')
    # A fabricated visible label must not replace actual attribute provenance.
    if 'actual_label' in proof:
        raise ValueError('Solopharm data-title must not be recorded as an inferred visible label')
    _project_guard(_literal(proof.get('url'), 'product.url'),
                   _literal(proof.get('actual_href'), 'product.actual_href'),
                   _literal(proof.get('pdf_url'), 'product.pdf_url'), proof['actual_data_title'])


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.open_text, self.bases = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag == 'base':
            self.bases.append(dict(attrs).get('href'))
        if tag not in ('a', 'object', 'embed', 'iframe', 'link'):
            return
        # Check every document-capable tag before dict collapse. The retained
        # footer repeats an identical mailto href, which does not hide a second
        # destination; conflicting href/src/data/type/label values would.
        if any(len({value for key, value in attrs if key == name}) > 1
               for name in ('href', 'src', 'data', 'type', 'title', 'aria-label', 'data-title', 'download')):
            raise ValueError('duplicate Solopharm document/label attributes are ambiguous')
        values = dict(attrs)
        href_key = 'data' if tag == 'object' else 'src' if tag in ('embed', 'iframe') else 'href'
        link = {'href': values.get(href_key) or '', 'attrs': values, 'text': [], 'tag': tag,
                'embedded': tag != 'a'}
        # Retain all tags first. MIME, visible/fallback text and medical label
        # classification happens uniformly below, even for opaque destinations.
        self.links.append(link)
        if tag in ('a', 'object', 'iframe'):
            # Keep text provenance bounded even for malformed deeply nested
            # document elements in the retained source HTML.
            if len(self.open_text) >= 32:
                raise ValueError('Solopharm document text nesting exceeds its bound')
            self.open_text.append(link)

    def handle_data(self, data):
        for link in self.open_text:
            link['text'].append(data)

    def handle_endtag(self, tag):
        for index in range(len(self.open_text) - 1, -1, -1):
            if self.open_text[index]['tag'] == tag:
                del self.open_text[index:]
                break


def validate_solopharm_product_html(document, body):
    if not isinstance(body, bytes) or not 1 <= len(body) <= MAX_HTML_BYTES:
        raise ValueError('retained Solopharm product HTML is absent or too large')
    proof = document['evidence']['product_page']
    validate_solopharm_product_proof(proof)
    if hashlib.sha256(body).hexdigest() != proof['html_sha256']:
        raise ValueError('retained Solopharm product HTML hash differs')
    parser = _Links()
    parser.feed(body.decode('utf-8'))
    if parser.bases:
        raise ValueError('Solopharm product HTML base is not supported')
    candidates, selected = set(), 0
    for link in parser.links:
        attrs, href = link['attrs'], link['href']
        # HTML indentation around an SVG is not a visible text label. Only
        # trim surrounding whitespace; never substitute attribute text.
        inner_text = ''.join(link['text']).strip()
        label = ' '.join([inner_text, attrs.get('title') or '', attrs.get('aria-label') or '',
                          attrs.get('data-title') or '', href])
        if (not _DOCUMENT_SUFFIXES.search(unquote(urlsplit(href).path))
                and not _DOCUMENT_MIME.search(attrs.get('type') or '')
                and not _MEDICAL_LABEL.search(label) and 'download' not in attrs):
            continue
        try:
            target = solopharm_href(proof['url'], href)
        except ValueError:
            raise ValueError('unknown or nonallowlisted Solopharm product document requires review') from None
        _project_guard(href, target, label)
        candidates.add(target)
        if href == proof['actual_href'] and target == proof['pdf_url']:
            if (link.get('embedded') or inner_text != proof['actual_inner_text']
                    or attrs.get('data-title') != proof['actual_data_title']
                    or attrs.get('title') or attrs.get('aria-label')):
                raise ValueError('actual Solopharm anchor or separate label provenance differs')
            selected += 1
    if selected != 1 or candidates != {proof['pdf_url']}:
        raise ValueError('one actual Solopharm instruction anchor and sole document version are required')


def _validate_pinned_address_typography(document, manufacturer):
    """Require the unchanged physical block from one of two reviewed PDFs."""
    if manufacturer.get('physical_address_profile') != GROTEX_ADDRESS_PROFILE:
        raise ValueError('unknown Solopharm literal address profile')
    key = manufacturer.get('physical_address_tuple')
    if not isinstance(key, str) or len(key) > 64 or key not in _GROTEX_ADDRESS_TUPLES:
        raise ValueError('unknown Solopharm literal address tuple')
    sha, count, page, country, address, context = _GROTEX_ADDRESS_TUPLES[key]
    evidence = document.get('evidence')
    visual = evidence.get('visual_identity') if isinstance(evidence, dict) else None
    if (document.get('original_sha256') != sha or type(document.get('page_count')) is not int
            or document['page_count'] != count or not isinstance(visual, dict)
            or visual.get('original_sha256') != sha or type(visual.get('page_count')) is not int
            or visual['page_count'] != count or visual.get('all_pages_visually_reviewed') is not True
            or manufacturer.get('page_indices') != [page]):
        raise ValueError('Solopharm literal address tuple requires its exact PDF SHA and physical pages')
    # Exact comparisons impose fixed length bounds. No legal/whitespace/address
    # normalization is applied on this new opt-in path, including raw context.
    expected = {'raw': PDF_MANUFACTURER, 'raw_role': 'Производитель',
                'physical_country_raw': country, 'physical_address_raw': address, 'context_raw': context}
    if any(type(manufacturer.get(field)) is not str or manufacturer[field] != value
           for field, value in expected.items()):
        raise ValueError('Solopharm literal address tuple requires its separate exact producer block')


def validate_solopharm_physical_proof(document, manufacturer, grls_parts):
    """Corroborate the exact observed factory without a new legal/address alias."""
    if (document.get('revision_date') is not None or document.get('approved_at') is not None
            or document.get('version') != 'sha256:' + document['original_sha256']):
        raise ValueError('Solopharm uses a SHA archive version and no inferred revision/approval date')
    if (_legal(manufacturer['raw']) != _legal(PDF_MANUFACTURER)
            or _legal(grls_parts[1].strip()) != _legal(GRLS_COMPANY)
            or grls_parts[2].strip() != GRLS_ADDRESS):
        raise ValueError('Solopharm requires the same observed Grotex finished factory at 71/2/A')
    if 'physical_address_profile' in manufacturer:
        _validate_pinned_address_typography(document, manufacturer)
    elif manufacturer.get('physical_address_raw') != PDF_ADDRESS:
        raise ValueError('Solopharm requires the same observed Grotex finished factory at 71/2/A')
