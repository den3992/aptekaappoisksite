"""Explicit per-binding Canon label evidence; no global dosage-form aliases.

The source document keeps its precise film-coated scope. A reviewed raw label
can justify only that exact GTIN's omitted film modifier in the catalog.
"""
import hashlib
import json
import re

from .medication_instructions import _gtin, _identity, _ru, _variant, _variant_key

MODE = 'canon_variant_label_film_v1'
GENERIC_FORM = 'таблетки, покрытые оболочкой'
FILM_FORM = 'таблетки, покрытые пленочной оболочкой'
MAX_VARIANTS = 128
MAX_LABEL_BYTES = 1024
MAX_EVIDENCE_BYTES = 128 * 1024
DISABLED = 'variant-form-fallback-disabled'
_FIELDS = {'mode', 'medicine_slug', 'catalog_name', 'catalog_manufacturer',
           'document_sha256', 'original_sha256', 'grls_row_sha256', 'product_html_sha256',
           'source_form_pages', 'source_dosage_pages', 'variants'}
_VARIANT_FIELDS = {'gtin', 'ru_number', 'catalog_form', 'catalog_dosage',
                   'label_name', 'label_sha256', 'esklp_code'}


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _bounded_text(value, limit=MAX_LABEL_BYTES):
    if not isinstance(value, str) or not value or len(value) > limit or len(value.encode()) > limit:
        raise ValueError('bounded literal variant-form text is required')
    return value


def _facts(med, raw):
    variant = _variant(med, raw)
    return {'gtin': _gtin(variant['gtin']), 'ru_number': _ru(variant['ru_number']),
            'catalog_form': variant['form'], 'catalog_dosage': variant['dosage'],
            'label_name': raw.get('label_name'), 'esklp_code': raw.get('esklp_code')}


def label_identity_digest(med):
    """Separate bounded cache identity; legacy medication fingerprints stay intact."""
    try:
        raw_variants = med.get('variants') or []
        if not isinstance(raw_variants, list) or len(raw_variants) > MAX_VARIANTS:
            return DISABLED
        candidates = []
        for raw in raw_variants:
            if not isinstance(raw, dict):
                return DISABLED
            if _identity(raw.get('form') or med.get('form')) != GENERIC_FORM:
                continue
            if len(candidates) >= MAX_VARIANTS:
                return DISABLED
            facts = _facts(med, raw)
            for key in ('ru_number', 'catalog_form', 'catalog_dosage', 'label_name'):
                _bounded_text(facts[key])
            if not facts['gtin'] or (facts['esklp_code'] is not None and not isinstance(facts['esklp_code'], str)):
                return DISABLED
            if facts['esklp_code'] is not None:
                _bounded_text(facts['esklp_code'])
            candidates.append(facts)
        if not candidates:
            return 'no-generic-coated-variants'
        base = {key: _bounded_text(med.get(key)) for key in ('slug', 'name', 'manufacturer')}
        # Fixed-size facts and at most128 bounded labels; no unbounded nested data.
        return _hash({'medication': base, 'variants': sorted(candidates, key=lambda v: (v['gtin'], v['ru_number'], v['label_name']))})
    except (ValueError, TypeError, KeyError, AttributeError):
        return DISABLED


def validate_evidence_shape(proof):
    """Bound the optional schema before hashing or using caller-provided fields."""
    if not isinstance(proof, dict) or set(proof) != _FIELDS or proof.get('mode') != MODE:
        raise ValueError('unknown or malformed Canon variant-form evidence')
    for field in ('medicine_slug', 'catalog_name', 'catalog_manufacturer'):
        _bounded_text(proof.get(field))
    for field in ('document_sha256', 'original_sha256', 'grls_row_sha256', 'product_html_sha256'):
        if not isinstance(proof[field], str) or not re.fullmatch('[a-f0-9]{64}', proof[field]):
            raise ValueError('variant-form source SHA256 is required')
    for field in ('source_form_pages', 'source_dosage_pages'):
        pages = proof[field]
        if (not isinstance(pages, list) or not 1 <= len(pages) <= 256
                or any(type(p) is not int or not 1 <= p <= 256 for p in pages)
                or len(set(pages)) != len(pages)):
            raise ValueError('variant-form physical page evidence is invalid')
    variants = proof['variants']
    if not isinstance(variants, list) or not 1 <= len(variants) <= MAX_VARIANTS:
        raise ValueError('variant-form proof count is out of bounds')
    seen = set()
    for value in variants:
        if not isinstance(value, dict) or set(value) != _VARIANT_FIELDS:
            raise ValueError('unknown variant-form proof fields')
        for field in ('gtin', 'ru_number', 'catalog_form', 'catalog_dosage', 'label_name'):
            _bounded_text(value[field])
        if value['esklp_code'] is not None:
            _bounded_text(value['esklp_code'])
        if not _gtin(value['gtin']) or value['gtin'] != _gtin(value['gtin']) or not _ru(value['ru_number']):
            raise ValueError('variant-form exact GTIN and RU are required')
        key = (value['gtin'], _ru(value['ru_number']))
        if key in seen:
            raise ValueError('duplicate variant-form identity')
        seen.add(key)
        if (not isinstance(value['label_sha256'], str)
                or value['label_sha256'] != hashlib.sha256(value['label_name'].encode()).hexdigest()):
            raise ValueError('raw variant label SHA256 differs')
    if len(json.dumps(proof, ensure_ascii=False).encode()) > MAX_EVIDENCE_BYTES:
        raise ValueError('variant-form evidence is too large')
    return proof


def evidence_digest(proof):
    return _hash(validate_evidence_shape(proof))


def form_binding_id(document_id, slug, fingerprint, bindings, proof):
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= MAX_VARIANTS:
        raise ValueError('variant-form binding count is out of bounds')
    return _hash({'document_id': document_id, 'medicine_slug': slug,
                  'identity_fingerprint': fingerprint,
                  'variant_bindings': sorted(_variant_key(v) for v in bindings),
                  'variant_form_evidence_sha256': evidence_digest(proof)})


def eligible_variant_keys(document, med, proof):
    """Raise on any stale proof; never borrow med.label_name or infer a source form."""
    validate_evidence_shape(proof)
    raw_variants = med.get('variants') or []
    if (not isinstance(raw_variants, list) or len(raw_variants) > MAX_VARIANTS
            or any(not isinstance(raw, dict) for raw in raw_variants)):
        raise ValueError('variant-form catalog list is malformed or over bound')
    source, evidence = document.get('source') or {}, document.get('evidence') or {}
    if (source.get('kind') != 'official_manufacturer' or source.get('provider') != 'canon'
            or document.get('content_format') != 'official_original_pdf'
            or document.get('verification', {}).get('method') != 'manual_visual_manufacturer_original'
            or proof['document_sha256'] != _hash(document)
            or proof['original_sha256'] != document.get('original_sha256')
            or proof['grls_row_sha256'] != evidence.get('current_grls_registration_sha256')
            or proof['product_html_sha256'] != evidence.get('product_page', {}).get('html_sha256')):
        raise ValueError('variant-form evidence requires the same verified Canon original')
    fields = evidence.get('visual_identity', {}).get('fields', {})
    if (proof['source_form_pages'] != fields.get('form', {}).get('page_indices')
            or proof['source_dosage_pages'] != fields.get('dosage', {}).get('page_indices')):
        raise ValueError('variant-form physical source pages differ')
    scopes = document.get('scopes') or []
    if (len(scopes) != 1 or _identity(scopes[0].get('form')) != FILM_FORM
            or not re.fullmatch(r'[0-9]+ мг', scopes[0].get('dosage') or '')):
        raise ValueError('only one literal integer-mg film-coated scope is supported')
    scope = scopes[0]
    if (proof['medicine_slug'] != med.get('slug') or proof['catalog_name'] != med.get('name')
            or proof['catalog_manufacturer'] != med.get('manufacturer')
            or label_identity_digest(med) == DISABLED):
        raise ValueError('variant-form catalog identity or bounds changed')
    by_identity = {}
    for raw in raw_variants:
        facts = _facts(med, raw)
        key = (facts['gtin'], facts['ru_number'])
        if key in by_identity:
            raise ValueError('ambiguous catalog GTIN/RU for variant-form evidence')
        by_identity[key] = (raw, facts)
    result = set()
    for value in proof['variants']:
        raw, facts = by_identity.get((value['gtin'], _ru(value['ru_number'])), (None, None))
        if facts is None or any(value[key] != facts[key] for key in facts):
            raise ValueError('reviewed raw variant label or identity changed')
        if (_identity(facts['catalog_form']) != GENERIC_FORM
                or facts['ru_number'] != _ru(scope['ru_number'])
                or _identity(facts['catalog_dosage']) != _identity(scope['dosage'])):
            raise ValueError('variant-form evidence cannot change RU, release form or dose')
        # These two observed delimiters are the entire allowed grammar. All form
        # words remain literal; enteric/retard/prose suffixes cannot disappear.
        allowed = {_identity(document['identity']['trade_name'] + ' ' + scope['form'] + separator + scope['dosage'])
                   for separator in (', ', ' ')}
        if _identity(facts['label_name']) not in allowed:
            raise ValueError('variant label is not the complete literal name, film form and dose')
        result.add(_variant_key(_variant(med, raw)))
    return result
