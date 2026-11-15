"""Explicit manufacturer originals: literal current GRLS and visual provenance.

This profile verifies the whole original and its identity, never a clinical
transcription. It is deliberately independent of the EAEU evidence derivation.
"""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import unquote, urljoin, urlsplit

from .medication_instructions import _identity, _object, _required_text, _ru, _sha256, _timestamp

MAX_HTML_BYTES = 3 * 1024 * 1024
HOSTS = ('renewal.ru', 'www.renewal.ru')
CANON_HOSTS = ('canonpharma.ru', 'www.canonpharma.ru')
SOLOPHARM_HOSTS = ('solopharm.com',)
# Explicitly reviewed nonmedical footer documents on the retained product pages.
# A new/renamed footer PDF is intentionally reviewed before this list changes.
LEGAL_FOOTER_PDFS = {
    '/upload/alsem.areas/ad4/privacy.pdf': 'Правила пользования сайтом',
    '/upload/alsem.areas/47c/privacy.pdf': 'Политика конфиденциальности',
}
MANUFACTURER_PROFILES = {
    'renewal': {'name': 'Renewal', 'hosts': HOSTS, 'product_prefix': '/products/',
                'footer_pdfs': LEGAL_FOOTER_PDFS},
    # Retained Canon product pages have no observed recurring legal PDF links.
    # Multiple patient/healthcare PDFs remain ambiguous under this sole-PDF
    # profile; labels do not authorize choosing one over another.
    'canon': {'name': 'Canon', 'hosts': CANON_HOSTS, 'product_prefix': '/catalog/',
              'footer_pdfs': {}},
    # This is the single observed public origin, not a domain-family alias.
    'solopharm': {'name': 'Solopharm', 'hosts': SOLOPHARM_HOSTS,
                  'product_prefix': '/products/', 'pdf_prefix': '/storage/files/products/',
                  'footer_pdfs': {}},
}
PHYSICAL_FINISHED_STAGE_MODE = 'physical_pdf_finished_stage_v1'
_GRLS_FINISHED_ROLE = (r'производитель\s*\((?:готовой\s+лф|все\s+стадии)\)'
                       r'|производство\s+готовой\s+лекарственной\s+формы')


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _profile(provider):
    if not isinstance(provider, str) or provider not in MANUFACTURER_PROFILES:
        raise ValueError('unknown official manufacturer provider')
    return MANUFACTURER_PROFILES[provider]


def _manufacturer_url(value, provider, *, prefix=None, pdf=False):
    profile = _profile(provider)
    label = profile['name']
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('a bounded official ' + label + ' URL is required')
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError('invalid official ' + label + ' port') from None
    if (parsed.scheme != 'https' or parsed.hostname not in profile['hosts'] or port not in (None, 443)
            or parsed.username or parsed.password or '?' in value or '#' in value
            or '\\' in value or re.search(r'%2e|%2f|%5c|%00', value, re.I)
            or (provider in ('canon', 'solopharm') and re.search(r'[\x00-\x20\x7f]|%25', value, re.I))):
        raise ValueError('only public HTTPS ' + label + ' URLs on port 443 are supported')
    if provider == 'solopharm' and '.' in parsed.path.split('/'):
        raise ValueError('Solopharm static paths cannot contain dot segments')
    decoded = parsed.path
    for _ in range(4):
        decoded = unquote(decoded)
        if '..' in decoded.split('/') or '\\' in decoded or '\x00' in decoded:
            raise ValueError(label + ' URL has an encoded static-path escape')
    if (re.search(r'%2e|%2f|%5c|%00', decoded, re.I)
            or (prefix and (not parsed.path.startswith(prefix) or parsed.path == prefix))
            or (pdf and not parsed.path.lower().endswith('.pdf'))):
        raise ValueError(label + ' URL is outside the permitted static path')
    return value


def _renewal_url(value, *, prefix=None, pdf=False):
    return _manufacturer_url(value, 'renewal', prefix=prefix, pdf=pdf)


def renewal_pdf_url(value):
    return _renewal_url(value, prefix='/upload/', pdf=True)


def canon_pdf_url(value):
    return _manufacturer_url(value, 'canon', prefix='/upload/', pdf=True)


def manufacturer_pdf_url(provider, value):
    return _manufacturer_url(value, provider, prefix=_profile(provider).get('pdf_prefix', '/upload/'), pdf=True)


def _canon_href(product_url, href):
    # Preserve and validate raw static-path components before urljoin could
    # normalize away traversal segments. Observed links are root-relative or
    # absolute public HTTPS files; protocol-relative hosts are not inferred.
    if not isinstance(href, str) or len(href) > 2048:
        raise ValueError('a bounded actual Canon PDF href is required')
    if href.startswith('/upload/'):
        return canon_pdf_url('https://' + urlsplit(product_url).netloc + href)
    return canon_pdf_url(href)


def _canon_project_guard(*values):
    for value in values:
        text = unicodedata.normalize('NFKC', str(value))
        for _ in range(4):
            text = unquote(text)
        if re.search(r'проект|draft|project|proekt', text, re.I):
            raise ValueError('Canon project/draft source requires quarantine, regardless of final/stamp claims')


def _literal(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 8000:
        raise ValueError(field + ' requires bounded literal source text')
    return value.strip()


def _legal(value):
    return ' '.join(re.sub(r'["«»„“”‟‹›]', '', unicodedata.normalize('NFKC', value)).split()).casefold()


def _aliases(company):
    result = {company}
    short = re.search(r'\s+\(([^()]*)\)\s*$', company)
    if short and re.match(r'^(?:ООО|АО|ПАО|ЗАО|ОАО|НАО)\b', short[1].strip(), re.I):
        result.update({company[:short.start()].strip(), short[1].strip()})
    return {_legal(value) for value in result}


def _pdf_manufacturer_matches(raw, company, evidence, provider='renewal'):
    if _legal(raw) in _aliases(company):
        if evidence.get('manufacturer_legal_form_equivalence') is not None:
            raise ValueError('unnecessary manufacturer legal-form exception')
        return True
    short = re.search(r'\s+\(([^()]*)\)\s*$', company)
    full_company = company[:short.start()].strip() if short else company
    # One reviewed provider-specific legal-form spelling, not a general company
    # normalizer. The actual PDF and GRLS literals remain immutable evidence.
    if (provider != 'renewal'
            or _legal(raw) != _legal('Акционерное общество «Производственная фармацевтическая компания Обновление»')
            or _legal(full_company) != _legal('АО «Производственная фармацевтическая компания Обновление»')):
        return False
    expected = {'rule': 'renewal_ao_full_name_v1', 'pdf_literal': raw, 'grls_literal': full_company}
    if evidence.get('manufacturer_legal_form_equivalence') != expected:
        raise ValueError('Renewal legal-form spelling requires its explicit literal proof')
    return True


def _visual_field(fields, key, page_count):
    item = _object(fields.get(key), 'visual_identity.fields.' + key)
    _literal(item.get('raw'), 'visual_identity.fields.' + key + '.raw')
    pages = item.get('page_indices')
    if (not isinstance(pages, list) or not pages or any(type(page) is not int or not 1 <= page <= page_count for page in pages)
            or len(set(pages)) != len(pages)):
        raise ValueError('visual identity requires unique physical PDF page indices')
    return item


def _validate_physical_finished_stage(evidence, manufacturer, fragment, grls_role, sha, pages):
    proof = _object(evidence.get('physical_pdf_finished_stage'), 'physical_pdf_finished_stage')
    indices = proof.get('page_indices')
    if (proof.get('original_sha256') != sha or type(proof.get('page_count')) is not int
            or proof['page_count'] != pages or not isinstance(indices, list) or not indices
            or any(type(index) is not int or not 1 <= index <= pages for index in indices)
            or len(set(indices)) != len(indices) or indices != manufacturer['page_indices']):
        raise ValueError('physical finished-stage proof must match the same original and manufacturer pages')
    # Keep the actual GRLS role (including QA) separate from the physical PDF
    # role. This opt-in never relabels a GRLS quality-control/packaging stage.
    if (proof.get('grls_role_raw') != grls_role or proof.get('grls_production_fragment') != fragment):
        raise ValueError('physical finished-stage proof differs from the literal GRLS role/fragment')
    company = _literal(proof.get('pdf_manufacturer_raw'), 'physical_pdf_finished_stage.pdf_manufacturer_raw')
    role = _literal(proof.get('pdf_role_raw'), 'physical_pdf_finished_stage.pdf_role_raw')
    if (company != manufacturer['raw'] or role != manufacturer.get('raw_role')
            or not re.fullmatch(r'производство\s+готовой\s+лекарственной\s+формы\s*:?', role, re.I)):
        raise ValueError('an explicit physical PDF finished dosage-form role for the same manufacturer is required')
    block = _literal(proof.get('pdf_producer_block_raw'), 'physical_pdf_finished_stage.pdf_producer_block_raw')
    if block.count(company) != 1 or block.count(role) != 1:
        raise ValueError('one literal company and finished stage must occur in the same physical producer block')
    company_at, role_at = block.index(company), block.index(role)
    prefix, between = block[:company_at], block[company_at + len(company):role_at]
    # Only the observed Canon layout is supported: explicit producer heading,
    # literal company, optional country, then its finished-dosage-form stage.
    # A role elsewhere on the page cannot be borrowed for this company.
    if (company_at >= role_at or not re.fullmatch(r'производитель\s*:?\s*', prefix.strip(), re.I)
            or not re.fullmatch(r'[\s,;]*(?:(?:Российская\s+Федерация|Россия)[\s,;]*)?', between, re.I)
            or re.search(r'упаков|контрол|держател|владел', block, re.I)):
        raise ValueError('physical finished-stage evidence must be one producer block, without unrelated roles/entities')


class _ProductLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.current, self.bases = [], None, []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'base' and values.get('href'):
            self.bases.append(values['href'])
        if tag == 'a':
            self.current = {'href': values.get('href', ''), 'text': [values.get('title', ''), values.get('aria-label', '')]}
            # Retain even an unclosed anchor: malformed markup must not hide an
            # additional unknown PDF from the sole-instruction check.
            self.links.append(self.current)

    def handle_data(self, data):
        if self.current:
            self.current['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.current:
            self.current = None


def validate_product_html(document, body):
    provider = document['source']['provider']
    if provider == 'solopharm':
        from .solopharm_original_pdfs import validate_solopharm_product_html
        return validate_solopharm_product_html(document, body)
    profile = _profile(provider)
    if not isinstance(body, bytes) or not 1 <= len(body) <= MAX_HTML_BYTES:
        raise ValueError('retained ' + profile['name'] + ' product HTML is absent or too large')
    proof = document['evidence']['product_page']
    if hashlib.sha256(body).hexdigest() != proof['html_sha256']:
        raise ValueError('retained ' + profile['name'] + ' product HTML hash differs')
    parser = _ProductLinks()
    parser.feed(body.decode('utf-8'))
    base = proof['url']
    if len(parser.bases) > 1:
        raise ValueError('ambiguous product HTML base')
    if parser.bases:
        base = _manufacturer_url(urljoin(base, parser.bases[0]), provider)
    candidates, selected = set(), False
    for link in parser.links:
        label = ' '.join(link['text']) + ' ' + link['href']
        looks_like_instruction = bool(re.search(r'инструкц|instruk|instruction|лист[ао]к[\s-]*вкладыш|информаци[яю]\s+для\s+(?:пациент|работник)|общ[а-я]+\s+характеристик', label, re.I))
        resolved = urljoin(base, link['href'])
        parsed = urlsplit(resolved)
        if not unquote(parsed.path).lower().endswith('.pdf') and not looks_like_instruction:
            continue
        try:
            target = (_canon_href(base, link['href']) if provider == 'canon'
                      else manufacturer_pdf_url(provider, resolved))
        except ValueError:
            raise ValueError('unknown or nonallowlisted product document href requires explicit review') from None
        footer_label = profile['footer_pdfs'].get(urlsplit(target).path)
        if footer_label and _identity(' '.join(link['text'])) == _identity(footer_label):
            continue
        candidates.add(target)
        if link['href'] == proof['actual_href'] and target == proof['pdf_url']:
            if provider == 'canon':
                actual_label = ' '.join(' '.join(link['text']).split())
                _canon_project_guard(link['href'], target, actual_label)
                if actual_label != proof.get('actual_label'):
                    raise ValueError('retained Canon PDF link label differs from the source proof')
            selected = True
    if not selected or candidates != {proof['pdf_url']}:
        raise ValueError('actual product href or sole selected instruction version is not proven')


def validate_manufacturer_archive(document, pdf_path):
    sha = document['evidence']['product_page']['html_sha256']
    path = Path(pdf_path).parent / (sha + '.html')
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_HTML_BYTES:
        raise ValueError('retained product HTML sibling is required for manufacturer apply')
    validate_product_html(document, path.read_bytes())


def validate_manufacturer_original_document(raw):
    from .medication_original_pdfs import CONTENT_FORMAT, MAX_PAGES, MAX_PDF_BYTES
    doc = _object(raw, 'document')
    identifier = _required_text(doc.get('id'), 'id')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', identifier):
        raise ValueError('invalid internal original document id')
    if doc.get('content_format') != CONTENT_FORMAT or doc.get('sections'):
        raise ValueError('manufacturer originals contain no purported inline sections')
    kind = doc.get('document_type')
    if kind not in ('medical_instruction', 'patient_leaflet'):
        raise ValueError('explicit actual original document type is required')
    size, pages = doc.get('original_bytes'), doc.get('page_count')
    if type(size) is not int or not 20 <= size <= MAX_PDF_BYTES or type(pages) is not int or not 1 <= pages <= MAX_PAGES:
        raise ValueError('manufacturer PDF binary bounds are invalid')
    sha = _sha256(doc.get('original_sha256'), 'original_sha256')
    source = _object(doc.get('source'), 'source')
    if source.get('kind') != 'official_manufacturer':
        raise ValueError('an explicit official manufacturer profile is required')
    provider = source.get('provider')
    profile = _profile(provider)
    product_url = _manufacturer_url(source.get('url'), provider, prefix=profile['product_prefix'])
    pdf_url = manufacturer_pdf_url(provider, source.get('pdf_url'))
    evidence = _object(doc.get('evidence'), 'evidence')
    if len(json.dumps(evidence, ensure_ascii=False).encode()) > 256 * 1024:
        raise ValueError('manufacturer evidence is too large')
    def reject_credentials(value):
        if isinstance(value, dict):
            if {'download_url', 'fileid', 'instanceid', 'token', 'access_token'}.intersection(value):
                raise ValueError('temporary credentials cannot enter manufacturer evidence')
            for item in value.values():
                reject_credentials(item)
        elif isinstance(value, list):
            for item in value:
                reject_credentials(item)
    reject_credentials(evidence)
    product = _object(evidence.get('product_page'), 'evidence.product_page')
    if product.get('url') != product_url or product.get('pdf_url') != pdf_url:
        raise ValueError('product page evidence differs from the selected source')
    _sha256(product.get('html_sha256'), 'product_page.html_sha256')
    href = _literal(product.get('actual_href'), 'product_page.actual_href')
    if provider == 'solopharm':
        from .solopharm_original_pdfs import solopharm_href, validate_solopharm_product_proof
        validate_solopharm_product_proof(product)
        resolved_href = solopharm_href(product_url, href)
    else:
        resolved_href = (_canon_href(product_url, href) if provider == 'canon'
                         else manufacturer_pdf_url(provider, urljoin(product_url, href)))
    if resolved_href != pdf_url:
        raise ValueError('observed product href does not resolve to the selected PDF')
    if provider == 'canon':
        label = _literal(product.get('actual_label'), 'product_page.actual_label')
        _canon_project_guard(href, pdf_url, label)
    numbers = doc.get('registration_numbers')
    if not isinstance(numbers, list) or len(numbers) != 1 or not isinstance(numbers[0], str) or not _ru(numbers[0]):
        raise ValueError('one exact current Russian registration is required')
    number = _ru(numbers[0])
    identity = _object(doc.get('identity'), 'identity')
    name = _required_text(identity.get('trade_name'), 'identity.trade_name')
    manufacturers = identity.get('manufacturers')
    if not isinstance(manufacturers, list) or not 1 <= len(manufacturers) <= 16:
        raise ValueError('explicit finished-product manufacturer identities are required')
    manufacturers = [_required_text(value, 'identity.manufacturers') for value in manufacturers]
    grls = _object(evidence.get('current_grls_registration'), 'current_grls_registration')
    if (evidence.get('current_grls_registration_sha256') != _hash(grls)
            or _ru(grls.get('registration_number')) != number or _ru(grls.get('registration_key')) != number
            or grls.get('source_status_book') != 'Действующий' or grls.get('cancelled_at')
            or grls.get('sheet') != 'Действующий' or type(grls.get('row')) is not int or grls['row'] < 2
            or not str(grls.get('snapshot_file') or '').endswith('.xlsx')
            or _identity(grls.get('trade_name')) != _identity(name)):
        raise ValueError('exact current GRLS source row is not proven')
    _sha256(grls.get('snapshot_sha256'), 'GRLS snapshot_sha256')
    try:
        registered = datetime.strptime(grls.get('registered_at') or '', '%d.%m.%Y').date()
        expiry = datetime.strptime(grls['expires_at'], '%d.%m.%Y').date() if grls.get('expires_at') else None
    except (ValueError, TypeError):
        raise ValueError('GRLS registration dates are invalid') from None
    today = datetime.now(timezone.utc).date()
    if registered > today or (expiry and expiry <= today):
        raise ValueError('GRLS registration is not current')
    fragment = _literal(evidence.get('grls_production_fragment'), 'grls_production_fragment')
    grls_fragments = [line.strip() for line in re.split(r'_x000D_|[\r\n]+', grls.get('production_stages') or '') if line.strip()]
    if fragment not in grls_fragments:
        raise ValueError('finished-product stage is absent from the exact GRLS row')
    parts = fragment.split(',', 2)
    if len(parts) != 3:
        raise ValueError('GRLS production fragment must identify a literal role and company')
    mode = evidence.get('manufacturer_proof_mode')
    if mode is not None and (mode != PHYSICAL_FINISHED_STAGE_MODE or provider != 'canon'):
        raise ValueError('unknown or non-Canon manufacturer proof mode')
    if mode is None and 'physical_pdf_finished_stage' in evidence:
        raise ValueError('physical finished-stage evidence requires its explicit proof mode')
    if mode is None and not re.fullmatch(_GRLS_FINISHED_ROLE, parts[0].strip(), re.I):
        raise ValueError('GRLS stage does not explicitly identify finished dosage-form manufacture')
    if mode == PHYSICAL_FINISHED_STAGE_MODE:
        if not parts[0].strip() or re.search(r'держател|владел', parts[0], re.I):
            raise ValueError('a GRLS production-company role is required; holder alone is insufficient')
        # No implicit version resolution: any explicit finished manufacturer in
        # this current GRLS record makes this fallback unnecessary or conflicting.
        for line in grls_fragments:
            stage = line.split(',', 2)
            if re.fullmatch(_GRLS_FINISHED_ROLE, stage[0].strip(), re.I):
                same = len(stage) >= 2 and _legal(stage[1].strip()) in _aliases(parts[1].strip())
                raise ValueError('physical finished-stage mode is unnecessary for an explicit GRLS finished company'
                                 if same else 'current GRLS has a conflicting explicit finished manufacturer')
    legal_aliases = _aliases(parts[1].strip())
    if any(_legal(alias) not in legal_aliases for alias in manufacturers):
        raise ValueError('manufacturer alias is not literally supported by GRLS finished-product company')
    scopes = doc.get('scopes')
    if not isinstance(scopes, list) or not scopes or len(scopes) > 128:
        raise ValueError('explicit manufacturer scopes are required')
    validated_scopes, pairs = [], set()
    release_forms = [line.strip() for line in (grls.get('release_forms') or '').split(';') if line.strip()]
    for raw_scope in scopes:
        scope = _object(raw_scope, 'scope')
        form, dose = _required_text(scope.get('form'), 'scope.form'), _required_text(scope.get('dosage'), 'scope.dosage')
        if (_ru(scope.get('ru_number')) != number or scope.get('gtin') or scope.get('manufacturer_scope')
                or dose == '~' or not any(_identity(line).startswith(_identity(form + ', ' + dose + ',')) for line in release_forms)):
            raise ValueError('scope requires literal exact GRLS RU/form/dosage without conversions')
        pairs.add((_identity(form), _identity(dose)))
        validated_scopes.append({'gtin': None, 'ru_number': number, 'form': form, 'dosage': dose})
    if len(pairs) != 1:
        raise ValueError('one unambiguous form/dosage pair is supported per visual proof')
    visual = _object(evidence.get('visual_identity'), 'visual_identity')
    version = _required_text(doc.get('version'), 'version')
    if (visual.get('original_sha256') != sha or type(visual.get('page_count')) is not int or visual.get('page_count') != pages
            or visual.get('all_pages_visually_reviewed') is not True or visual.get('document_type') != kind
            or visual.get('version') != version or visual.get('not_unapproved_project') is not True
            or visual.get('version_conflict') is not False):
        raise ValueError('whole original visual identity and selected non-project version must be proven')
    _required_text(visual.get('reviewer'), 'visual_identity.reviewer')
    _timestamp(visual.get('verified_at'), 'visual_identity.verified_at')
    reason = _required_text(visual.get('version_review'), 'visual_identity.version_review')
    if len(re.findall(r'[A-Za-zА-Яа-яЁё]', reason)) < 40:
        raise ValueError('selected version requires a concrete source-review reason')
    revision = doc.get('revision_date')
    if visual.get('revision_date') != revision:
        raise ValueError('revision date differs from visual source proof')
    if revision is not None:
        try:
            datetime.strptime(revision, '%Y-%m-%d')
        except (ValueError, TypeError):
            raise ValueError('revision_date must be an actual ISO source date or null') from None
    fields = _object(visual.get('fields'), 'visual_identity.fields')
    proofs = {key: _visual_field(fields, key, pages) for key in ('registration_number', 'trade_name', 'form', 'dosage', 'manufacturer')}
    scope = validated_scopes[0]
    if (_ru(proofs['registration_number']['raw']) != number or _identity(proofs['trade_name']['raw']) != _identity(name)
            or _identity(proofs['form']['raw']) != _identity(scope['form']) or _identity(proofs['dosage']['raw']) != _identity(scope['dosage'])
            or not _pdf_manufacturer_matches(proofs['manufacturer']['raw'], parts[1].strip(), evidence, provider)):
        raise ValueError('literal physical PDF identity differs from exact GRLS scopes/manufacturer')
    role = _literal(proofs['manufacturer'].get('raw_role'), 'visual manufacturer raw_role')
    if (not re.search(r'\bпроизводител[ья]\b|производство\s+готовой', role, re.I)
            or re.search(r'держател|владел|упаков|контрол|выпускающ', role, re.I)):
        raise ValueError('visual PDF role does not prove the finished-product manufacturer')
    if mode == PHYSICAL_FINISHED_STAGE_MODE:
        _validate_physical_finished_stage(evidence, proofs['manufacturer'], fragment, parts[0].strip(), sha, pages)
    if provider == 'solopharm':
        from .solopharm_original_pdfs import validate_solopharm_physical_proof
        validate_solopharm_physical_proof(doc, proofs['manufacturer'], parts)
    verification = _object(doc.get('verification'), 'verification')
    if verification.get('status') != 'verified' or verification.get('method') != 'manual_visual_manufacturer_original':
        raise ValueError('only verified original PDF metadata is public')
    if doc.get('approved_at') is not None:
        raise ValueError('manufacturer profile does not infer an approval date from revision/filename')
    return {
        'id': identifier, 'title': _required_text(doc.get('title'), 'title'), 'content_format': CONTENT_FORMAT,
        'document_type': kind, 'registration_numbers': [numbers[0].strip()], 'version': version,
        'approved_at': None, 'revision_date': revision, 'retrieved_at': _timestamp(doc.get('retrieved_at'), 'retrieved_at'),
        'original_sha256': sha, 'original_bytes': size, 'page_count': pages,
        'source': {'name': _required_text(source.get('name'), 'source.name'), 'url': product_url,
                   'kind': 'official_manufacturer', 'provider': provider, 'pdf_url': pdf_url},
        'identity': {'trade_name': name, 'manufacturers': manufacturers}, 'scopes': validated_scopes,
        'verification': {'status': 'verified', 'verified_at': _timestamp(verification.get('verified_at'), 'verification.verified_at'),
                         'verified_by': _required_text(verification.get('verified_by'), 'verification.verified_by'),
                         'method': 'manual_visual_manufacturer_original'},
        'evidence': evidence, 'completeness': {'original_pdf_confirmed': True, 'inline_text_verified': False},
    }
