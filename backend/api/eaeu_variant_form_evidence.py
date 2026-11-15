"""Opt-in EAEU per-binding film-form labels, with unchanged Canon dispatch.

Source scopes remain the exact registered film form. Only the observed whole
label of one GTIN may justify that variant's generic catalog form. This module
does not normalize medical forms, alter dose evidence, or approve PDF content.
"""
import hashlib
import json
import re

from . import canon_variant_form_evidence as canon
from .instruction_original_evidence import PAIRED_ENTITY_MODE
from .instruction_original_structured_dose import PROOF_MODE as STRUCTURED_DOSE_MODE
from .medication_instructions import _gtin, _identity, _ru, _variant, _variant_key

MODE = 'eaeu_variant_label_film_v1'
GENERIC_FORM, FILM_FORM = canon.GENERIC_FORM, canon.FILM_FORM
MAX_VARIANTS, MAX_LABEL_BYTES, MAX_EVIDENCE_BYTES = (
    canon.MAX_VARIANTS, canon.MAX_LABEL_BYTES, canon.MAX_EVIDENCE_BYTES)
_FIELDS = {'mode', 'medicine_slug', 'catalog_name', 'catalog_manufacturer',
           'document_sha256', 'original_sha256', 'grls_row_sha256',
           'source_registry_snapshot_sha256', 'source_metadata_sha256',
           'source_scope', 'variants'}
_VARIANT_FIELDS = {'gtin', 'ru_number', 'catalog_form', 'catalog_dosage',
                   'label_name', 'label_sha256', 'esklp_code'}


def _is_eaeu(proof):
    return isinstance(proof, dict) and proof.get('mode') == MODE


def _scope(value):
    if not isinstance(value, dict) or set(value) != {'ru_number', 'form', 'dosage'}:
        raise ValueError('one exact EAEU source scope is required')
    for field in value:
        canon._bounded_text(value[field])
    if (not _ru(value['ru_number']) or _identity(value['form']) != FILM_FORM
            or not re.fullmatch(r'[1-9][0-9]* мг', value['dosage'])):
        raise ValueError('only a literal positive integer-mg film scope is supported')
    return value


def validate_evidence_shape(proof):
    from . import mdlp_variant_form_evidence as mdlp
    if mdlp.is_proof(proof):
        return mdlp.validate_evidence_shape(proof)
    if not _is_eaeu(proof):
        return canon.validate_evidence_shape(proof)
    if set(proof) != _FIELDS:
        raise ValueError('unknown EAEU variant-form evidence fields')
    for field in ('medicine_slug', 'catalog_name', 'catalog_manufacturer'):
        canon._bounded_text(proof[field])
    for field in ('document_sha256', 'original_sha256', 'grls_row_sha256',
                  'source_registry_snapshot_sha256', 'source_metadata_sha256'):
        if not isinstance(proof[field], str) or not re.fullmatch('[a-f0-9]{64}', proof[field]):
            raise ValueError('EAEU variant-form source SHA256 is required')
    _scope(proof['source_scope'])
    variants = proof['variants']
    if not isinstance(variants, list) or not 1 <= len(variants) <= MAX_VARIANTS:
        raise ValueError('EAEU variant-form proof count is out of bounds')
    seen = set()
    for value in variants:
        if not isinstance(value, dict) or set(value) != _VARIANT_FIELDS:
            raise ValueError('unknown EAEU variant proof fields')
        for field in ('gtin', 'ru_number', 'catalog_form', 'catalog_dosage', 'label_name'):
            canon._bounded_text(value[field])
        if value['esklp_code'] is not None:
            canon._bounded_text(value['esklp_code'])
        if not _gtin(value['gtin']) or value['gtin'] != _gtin(value['gtin']) or not _ru(value['ru_number']):
            raise ValueError('EAEU variant-form exact GTIN and RU are required')
        key = (value['gtin'], _ru(value['ru_number']))
        if key in seen:
            raise ValueError('duplicate EAEU variant-form identity')
        seen.add(key)
        if (not isinstance(value['label_sha256'], str)
                or value['label_sha256'] != hashlib.sha256(value['label_name'].encode()).hexdigest()):
            raise ValueError('raw EAEU variant label SHA256 differs')
    if len(json.dumps(proof, ensure_ascii=False).encode()) > MAX_EVIDENCE_BYTES:
        raise ValueError('EAEU variant-form evidence is too large')
    return proof


def evidence_digest(proof):
    from . import mdlp_variant_form_evidence as mdlp
    if mdlp.is_proof(proof):
        return mdlp.evidence_digest(proof)
    if not _is_eaeu(proof):
        return canon.evidence_digest(proof)
    return canon._hash(validate_evidence_shape(proof))


def form_binding_id(document_id, slug, fingerprint, bindings, proof):
    from . import mdlp_variant_form_evidence as mdlp
    if mdlp.is_proof(proof):
        return mdlp.form_binding_id(document_id, slug, fingerprint, bindings, proof)
    if not _is_eaeu(proof):
        return canon.form_binding_id(document_id, slug, fingerprint, bindings, proof)
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= MAX_VARIANTS:
        raise ValueError('EAEU variant-form binding count is out of bounds')
    return canon._hash({'document_id': document_id, 'medicine_slug': slug,
                        'identity_fingerprint': fingerprint,
                        'variant_bindings': sorted(_variant_key(v) for v in bindings),
                        'variant_form_evidence_sha256': evidence_digest(proof)})


def _catalog_by_identity(med):
    raw_variants = med.get('variants') or []
    # Check total raw length before iterating: a small proof must not authorize
    # an unbounded scan of unrelated non-generic variants.
    if (not isinstance(raw_variants, list) or len(raw_variants) > MAX_VARIANTS
            or canon.label_identity_digest(med) == canon.DISABLED):
        raise ValueError('EAEU variant-form catalog list is malformed or over bound')
    result = {}
    for raw in raw_variants:
        if not isinstance(raw, dict):
            raise ValueError('malformed EAEU catalog variant')
        facts = canon._facts(med, raw)
        key = (facts['gtin'], facts['ru_number'])
        if key in result:
            raise ValueError('ambiguous catalog GTIN/RU for EAEU variant-form evidence')
        result[key] = (raw, facts)
    return result


def _labels(trade_name, scope):
    return {_identity(trade_name + name_separator + scope['form'] + dose_separator + scope['dosage'])
            for name_separator in (' ', ', ') for dose_separator in (', ', ' ')}


def reviewed_variant_facts(med, trade_name, scope):
    """Collect actual raw labels only; no med-label fallback or synthesized label."""
    _scope(scope)
    result = []
    labels = _labels(trade_name, scope)
    for raw, facts in _catalog_by_identity(med).values():
        if (not facts['gtin'] or facts['ru_number'] != _ru(scope['ru_number'])
                or _identity(facts['catalog_form']) != GENERIC_FORM
                or _identity(facts['catalog_dosage']) != _identity(scope['dosage'])
                or _identity(facts['label_name']) not in labels):
            continue
        result.append({**facts, 'label_sha256': hashlib.sha256(facts['label_name'].encode()).hexdigest()})
    if not result:
        raise ValueError('no complete literal EAEU film-form variant label')
    return result


def eligible_variant_keys(document, med, proof, *, raw_source_rows=None):
    from . import mdlp_variant_form_evidence as mdlp
    if mdlp.is_proof(proof):
        return mdlp.eligible_variant_keys(document, med, proof, raw_source_rows=raw_source_rows)
    if not _is_eaeu(proof):
        return canon.eligible_variant_keys(document, med, proof)
    validate_evidence_shape(proof)
    by_identity = _catalog_by_identity(med)
    from .medication_original_pdfs import validate_original_document
    doc = validate_original_document(document)
    source, evidence = doc['source'], doc['evidence']
    if (source.get('kind') != 'official_registry' or source.get('provider') != 'eaeu'
            or doc.get('content_format') != 'official_original_pdf'):
        raise ValueError('EAEU variant-form evidence requires the same verified registry source')
    registrations = [r for r in evidence['registry_snapshot']['russian_registrations']
                     if _ru(r.get('registration_number')) == _ru(doc['registration_numbers'][0])]
    usages = [d for d in registrations[0]['documents'] if d.get('kind') == 'USAGE_INSTRUCTION']
    if (len(usages) != 1
            or usages[0].get('uploaded_file_path') != source.get('uploaded_file_path')
            or evidence.get('manufacturer_proof_mode') not in (None, PAIRED_ENTITY_MODE)
            or evidence.get('dosage_proof_mode') != STRUCTURED_DOSE_MODE
            or proof['document_sha256'] != canon._hash(doc)
            or proof['original_sha256'] != doc['original_sha256']
            or proof['grls_row_sha256'] != evidence.get('current_grls_registration_sha256')
            or proof['source_registry_snapshot_sha256'] != evidence.get('registry_snapshot_sha256')
            or proof['source_metadata_sha256'] != source.get('metadata_sha256')):
        raise ValueError('EAEU variant-form evidence requires the same verified source and solid-dose profile')
    scope = proof['source_scope']
    selected = [s for s in doc['scopes'] if {k: s[k] for k in scope} == scope and s.get('gtin') is None]
    if len(selected) != 1:
        raise ValueError('EAEU variant-form proof must select one actual precise source scope')
    if (proof['medicine_slug'] != med.get('slug') or proof['catalog_name'] != med.get('name')
            or proof['catalog_manufacturer'] != med.get('manufacturer')):
        raise ValueError('EAEU variant-form catalog identity changed')
    labels, result = _labels(doc['identity']['trade_name'], scope), set()
    for value in proof['variants']:
        raw, facts = by_identity.get((value['gtin'], _ru(value['ru_number'])), (None, None))
        if facts is None or any(value[key] != facts[key] for key in facts):
            raise ValueError('reviewed raw EAEU variant label or identity changed')
        if (_identity(facts['catalog_form']) != GENERIC_FORM
                or facts['ru_number'] != _ru(scope['ru_number'])
                or _identity(facts['catalog_dosage']) != _identity(scope['dosage'])
                or _identity(facts['label_name']) not in labels):
            raise ValueError('EAEU variant label is not the complete literal name, film form and dose')
        result.add(_variant_key(_variant(med, raw)))
    return result


def build_evidence(document, med, scope):
    """Prepare optional binding facts separately from the canonical source PDF."""
    selected = [s for s in document['scopes']
                if _ru(s['ru_number']) == _ru(scope['ru_number'])
                and s['form'] == scope['form'] and s['dosage'] == scope['dosage']
                and s.get('gtin') is None]
    if len(selected) != 1:
        raise ValueError('one precise canonical EAEU source scope is required')
    scope = {key: selected[0][key] for key in ('ru_number', 'form', 'dosage')}
    evidence, source = document['evidence'], document['source']
    proof = {'mode': MODE, 'medicine_slug': med['slug'], 'catalog_name': med['name'],
             'catalog_manufacturer': med['manufacturer'], 'document_sha256': canon._hash(document),
             'original_sha256': document['original_sha256'],
             'grls_row_sha256': evidence['current_grls_registration_sha256'],
             'source_registry_snapshot_sha256': evidence['registry_snapshot_sha256'],
             'source_metadata_sha256': source['metadata_sha256'], 'source_scope': dict(scope),
             'variants': reviewed_variant_facts(med, document['identity']['trade_name'], scope)}
    eligible_variant_keys(document, med, proof)
    return proof
