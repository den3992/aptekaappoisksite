"""Whole verified official PDFs are distinct from verified inline instruction text."""
from __future__ import annotations

from collections import OrderedDict
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import re

from .async_cache import AsyncTTLValue
from .medication_instructions import (
    _gtin, _identity, _object, _required_text, _ru, _sha256, _timestamp, _variant,
    _variant_key, medication_identity_fingerprint,
)

logger = logging.getLogger(__name__)
CONTENT_FORMAT = 'official_original_pdf'
REGISTRY_BASE = 'https://pharma.eaeunion.org/pharma/registers/26/ru/register/registered-medicinal-products/'
MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_PAGES = 256
MAX_DOCUMENTS = 32
MAX_BINDINGS = 128


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def instruction_attachment_needs_review(attachment):
    """Recheck source facts independently of old normalization and claims."""
    if not isinstance(attachment, dict) or attachment.get('review_flags'):
        return True
    # Filenames often use underscores or transliterated dossier labels. A word
    # boundary would miss those markers; final/stamp labels cannot override one.
    return any(re.search(r'проект|draft|project|proekt', str(attachment.get(field) or ''), re.I)
               for field in ['name', 'file_name', 'uploaded_file_path'])


def _future_or_absent(value, field):
    if not value:
        return
    parsed = datetime.fromisoformat(_timestamp(value, field).replace('Z', '+00:00'))
    if parsed <= datetime.now(timezone.utc):
        raise ValueError(field + ' has expired')


def validate_original_document(raw):
    """Validate provenance and exact variant scopes; never claim an OCR approval."""
    doc = _object(raw, 'document')
    if isinstance(doc.get('source'), dict) and doc['source'].get('kind') == 'official_manufacturer':
        from .manufacturer_original_pdfs import validate_manufacturer_original_document
        return validate_manufacturer_original_document(doc)
    if doc.get('content_format') != CONTENT_FORMAT or doc.get('sections'):
        raise ValueError('whole PDF originals must be explicit and contain no purported inline sections')
    identifier = _required_text(doc.get('id'), 'id')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', identifier):
        raise ValueError('invalid internal original document id')
    profile = doc.get('document_type')
    if profile not in {'medical_instruction', 'patient_leaflet'}:
        raise ValueError('the actual instruction document type is required')
    size, pages = doc.get('original_bytes'), doc.get('page_count')
    if type(size) is not int or not 20 <= size <= MAX_PDF_BYTES:
        raise ValueError('original PDF byte length must be bounded')
    if type(pages) is not int or not 1 <= pages <= MAX_PAGES:
        raise ValueError('original PDF page count must be bounded')
    sha = _sha256(doc.get('original_sha256'), 'original_sha256')
    source = _object(doc.get('source'), 'source')
    record_id = source.get('record_id')
    path = source.get('uploaded_file_path')
    if (source.get('kind') != 'official_registry' or source.get('provider') != 'eaeu'
            or not isinstance(record_id, str) or not re.fullmatch(r'[a-f0-9]{24}', record_id)
            or source.get('url') != REGISTRY_BASE + record_id):
        raise ValueError('only a proven official EAEU registry record is supported')
    if (not isinstance(path, str) or len(path) > 512 or '..' in path
            or not re.fullmatch(r'[A-Za-z0-9_./-]+\.pdf', path, re.I) or path.startswith('/')):
        raise ValueError('invalid observed uploaded PDF path')
    metadata_sha = _sha256(source.get('metadata_sha256'), 'source.metadata_sha256')
    evidence = _object(doc.get('evidence'), 'evidence')
    serialized_evidence = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if len(serialized_evidence.encode()) > 256 * 1024:
        raise ValueError('original PDF evidence is too large')
    def reject_temporary_credentials(value):
        if isinstance(value, dict):
            if {'download_url', 'fileid', 'instanceid', 'token', 'access_token'}.intersection(value):
                raise ValueError('temporary workflow credentials cannot enter immutable provenance')
            for item in value.values():
                reject_temporary_credentials(item)
        elif isinstance(value, list):
            for item in value:
                reject_temporary_credentials(item)
    reject_temporary_credentials(evidence)
    snapshot = _object(evidence.get('registry_snapshot'), 'evidence.registry_snapshot')
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if len(payload.encode()) > 128 * 1024:
        raise ValueError('registry evidence is too large')
    if (snapshot.get('record_id') != record_id or snapshot.get('metadata_sha256') != metadata_sha
            or evidence.get('registry_snapshot_sha256') != canonical_hash(snapshot)):
        raise ValueError('registry evidence is not bound to the recorded source snapshot')
    numbers = doc.get('registration_numbers')
    if (not isinstance(numbers, list) or len(numbers) != 1 or not isinstance(numbers[0], str)
            or not _ru(numbers[0])):
        raise ValueError('one exact current Russian registration is required')
    ru_key = _ru(numbers[0])
    registrations = [r for r in snapshot.get('russian_registrations') or []
                     if isinstance(r, dict) and _ru(r.get('registration_number')) == ru_key]
    if len(registrations) != 1:
        raise ValueError('the exact registration is absent or ambiguous in the source snapshot')
    registration = registrations[0]
    if (registration.get('country') != 'RU' or registration.get('registration_status_code') != '03'
            or registration.get('cancelled_at')):
        raise ValueError('the registration must be currently registered in Russia')
    _future_or_absent(registration.get('valid_until'), 'registration.valid_until')
    current = [d for d in registration.get('documents') or []
               if isinstance(d, dict) and d.get('kind') == 'USAGE_INSTRUCTION']
    matching = [d for d in current if d.get('uploaded_file_path') == path]
    if len(matching) != 1:
        raise ValueError('the original is not an unambiguous actual USAGE_INSTRUCTION attachment')
    attachment = matching[0]
    if instruction_attachment_needs_review(attachment):
        raise ValueError('source instruction attachment has a project/draft marker or unresolved review flags')
    _future_or_absent(attachment.get('valid_until'), 'attachment.valid_until')
    if type(attachment.get('size')) is int and attachment['size'] != size:
        raise ValueError('PDF size differs from official attachment metadata')
    if len(current) != 1 and evidence.get('document_version_selection') != 'independently_reviewed':
        raise ValueError('multiple source instruction versions require explicit reviewed selection')
    for field in ['identity_review', 'document_version_review']:
        reason = _required_text(evidence.get(field), 'evidence.' + field)
        if len(re.findall(r'[A-Za-zА-Яа-яЁё]', reason)) < 40:
            raise ValueError(field + ' requires concrete source evidence')
    if evidence.get('not_unapproved_project') is not True:
        raise ValueError('an unapproved project cannot be published as an official original')
    if evidence.get('original_sha256') != sha or evidence.get('full_pdf_checked') is not True:
        raise ValueError('a complete retained original with this SHA is required')
    checked_at = _timestamp(evidence.get('checked_at'), 'evidence.checked_at')
    identity_input = _object(doc.get('identity'), 'identity')
    name = _required_text(identity_input.get('trade_name'), 'identity.trade_name')
    if _identity(name) != _identity(registration.get('trade_name')):
        raise ValueError('trade name differs from the exact Russian registration')
    manufacturers = identity_input.get('manufacturers')
    if not isinstance(manufacturers, list) or not 1 <= len(manufacturers) <= 32:
        raise ValueError('explicit finished-product manufacturer names are required')
    manufacturers = [_required_text(v, 'identity.manufacturers') for v in manufacturers]
    if not snapshot.get('manufacturers') or evidence.get('finished_manufacturer_confirmed') is not True:
        raise ValueError('a registration holder cannot substitute for a finished-product manufacturer')
    if not {_identity(v) for v in manufacturers}.intersection(_identity(v) for v in snapshot['manufacturers']):
        raise ValueError('explicit identity must include the source finished-product manufacturer')
    scopes = doc.get('scopes')
    if not isinstance(scopes, list) or not 1 <= len(scopes) <= 1000:
        raise ValueError('explicit variant scopes are required')
    validated_scopes = []
    for scope in scopes:
        scope = _object(scope, 'scope')
        if _ru(scope.get('ru_number')) != ru_key or scope.get('manufacturer_scope'):
            raise ValueError('scope must use this exact RU and explicit manufacturer identity')
        gtin = _gtin(scope.get('gtin'))
        if scope.get('gtin') and not gtin:
            raise ValueError('invalid scope GTIN')
        validated_scopes.append({'gtin': gtin or None, 'ru_number': ru_key,
                                 'form': _required_text(scope.get('form'), 'scope.form'),
                                 'dosage': _required_text(scope.get('dosage'), 'scope.dosage')})
    from .instruction_original_evidence import validate_identity_evidence
    validate_identity_evidence(doc, snapshot, registration, validated_scopes, manufacturers)
    verification = _object(doc.get('verification'), 'verification')
    if verification.get('status') != 'verified':
        raise ValueError('only verified original PDF metadata may be published')
    approved_at = doc.get('approved_at')
    if approved_at is not None:
        try:
            datetime.fromisoformat(approved_at.replace('Z', '+00:00'))
        except (ValueError, TypeError, AttributeError):
            raise ValueError('approved_at must be an ISO date or null') from None
    return {
        'id': identifier, 'title': _required_text(doc.get('title'), 'title'),
        'content_format': CONTENT_FORMAT, 'document_type': profile,
        'registration_numbers': [numbers[0].strip()], 'version': _required_text(doc.get('version'), 'version'),
        'approved_at': approved_at, 'retrieved_at': _timestamp(doc.get('retrieved_at'), 'retrieved_at'),
        'original_sha256': sha, 'original_bytes': size, 'page_count': pages,
        'source': {'name': _required_text(source.get('name'), 'source.name'), 'url': source['url'],
                   'kind': 'official_registry', 'provider': 'eaeu', 'record_id': record_id,
                   'uploaded_file_path': path, 'metadata_sha256': metadata_sha},
        'identity': {'trade_name': name, 'manufacturers': manufacturers}, 'scopes': validated_scopes,
        'verification': {'status': 'verified', 'verified_at': _timestamp(verification.get('verified_at'), 'verification.verified_at'),
                         'verified_by': _required_text(verification.get('verified_by'), 'verification.verified_by'),
                         'method': _required_text(verification.get('method'), 'verification.method')},
        'evidence': {**evidence, 'checked_at': checked_at},
        'completeness': {'original_pdf_confirmed': True, 'inline_text_verified': False},
    }


def match_original_to_medication(document, med, *, variant_form_evidence=None, raw_source_rows=None):
    doc = validate_original_document(document)
    variants = med.get('variants') or []
    result = {'matched': False, 'bindings': [], 'total_variants': len(variants), 'covered_variants': 0,
              'fully_covered': False, 'identity_fingerprint': medication_identity_fingerprint(med), 'reasons': []}
    identity = doc['identity']
    if (not med.get('slug') or med.get('is_canonical') is False
            or _identity(med.get('name')) != _identity(identity['trade_name'])
            or _identity(med.get('manufacturer')) not in {_identity(v) for v in identity['manufacturers']}):
        result['reasons'].append('canonical medication name or explicit manufacturer differs')
        return result
    form_keys = set()
    if variant_form_evidence is not None:
        from .eaeu_variant_form_evidence import eligible_variant_keys
        try:
            form_keys = eligible_variant_keys(doc, med, variant_form_evidence, raw_source_rows=raw_source_rows)
        except (ValueError, KeyError, TypeError, AttributeError):
            # Optional evidence cannot invalidate an ordinary strict binding.
            pass
    for raw_variant in variants:
        variant = _variant(med, raw_variant)
        for scope in doc['scopes']:
            if _ru(variant['ru_number']) != scope['ru_number']:
                continue
            if scope['gtin'] and _gtin(variant['gtin']) != scope['gtin']:
                continue
            strict = all(_identity(scope[k]) == _identity(variant[k]) for k in ['form', 'dosage'])
            if not strict and _variant_key(variant) not in form_keys:
                continue
            result['bindings'].append(variant)
            break
    result['covered_variants'] = len(result['bindings'])
    result['matched'] = bool(result['bindings'])
    result['fully_covered'] = bool(variants) and len(result['bindings']) == len(variants)
    if not result['matched']:
        result['reasons'].append('no exact RU, manufacturer, form and dosage matched')
    return result


class MedicationOriginalService:
    def __init__(self, db, *, ttl=60, capacity=64, load_timeout=3):
        if ttl <= 0 or capacity < 1 or load_timeout <= 0:
            raise ValueError('original PDF cache bounds must be positive')
        self.db, self.ttl, self.capacity, self.load_timeout = db, ttl, capacity, load_timeout
        self.cache = OrderedDict()
        self.raw_hints = OrderedDict()
        from .mdlp_raw_source import AsyncRawSource
        self.raw_source = AsyncRawSource(db)

    def _key(self, med):
        from .canon_variant_form_evidence import label_identity_digest
        return (med['slug'], medication_identity_fingerprint(med), label_identity_digest(med))

    async def _load(self, med, *, authorize_raw=False):
        from . import mdlp_variant_form_evidence as mdlp
        fingerprint = medication_identity_fingerprint(med)
        rows = await self.db.medication_original_bindings.find({
            'medicine_slug': med['slug'], 'identity_fingerprint': fingerprint,
            'status': 'verified', 'active': True,
        }, {}).max_time_ms(1500).to_list(MAX_BINDINGS + 1)
        if len(rows) > MAX_BINDINGS:
            raise ValueError('too many original PDF bindings')
        raw_rows = None
        if any(mdlp.is_row(row) for row in rows):
            key = self._key(med)
            self.raw_hints[key] = True
            self.raw_hints.move_to_end(key)
            while len(self.raw_hints) > self.capacity:
                self.raw_hints.popitem(last=False)
            if authorize_raw:
                try:
                    current = await self.db.medications.find_one({'slug':med['slug']},
                        {'_id':0,'slug':1,'name':1,'manufacturer':1,'form':1,'dosage':1,
                         'ru_number':1,'variants':{'$slice':129},'is_canonical':1},max_time_ms=1500)
                    if (not current or not isinstance(current.get('variants'),list)
                            or len(current['variants'])>128
                            or self._key(current) != self._key(med)):
                        raise ValueError('current canonical identity or literal labels changed')
                    gtins = set()
                    for row in rows:
                        if mdlp.is_row(row):
                            try:
                                gtins.update(v['gtin'] for v in mdlp.expected_rows(row.get('variant_form_evidence')))
                            except (ValueError,TypeError,KeyError,AttributeError):
                                continue
                    if not 1 <= len(gtins) <= mdlp.MAX_PAIRS:
                        raise ValueError('too many optional raw identities')
                    raw_rows = await self.raw_source.get(sorted(gtins))
                except Exception:
                    # Optional lookup failure cannot discard an ordinary binding.
                    raw_rows = None
        ids = list(dict.fromkeys(row.get('document_id') for row in rows if row.get('document_id')))
        if len(ids) > MAX_DOCUMENTS:
            raise ValueError('too many original PDFs')
        if not ids:
            return []
        raw_docs = await self.db.instruction_original_documents.find({'id': {'$in': ids}}, {'_id': 0}).max_time_ms(1500).to_list(MAX_DOCUMENTS + 1)
        if len(raw_docs) > MAX_DOCUMENTS or len({d.get('id') for d in raw_docs}) != len(raw_docs):
            raise ValueError('ambiguous original PDF ids')
        result = []
        for raw_doc in raw_docs:
            try:
                doc = validate_original_document(raw_doc)
                strict_match = match_original_to_medication(doc, med)
            except (ValueError, KeyError, TypeError):
                continue
            bound = {}
            for row in rows:
                if row.get('document_id') != doc['id']:
                    continue
                if mdlp.is_row(row) and not authorize_raw:
                    # Even a strict variant carried by an MDLP binding row
                    # must not enter the ordinary positive payload cache.
                    continue
                # Each row must justify its own fallback. Never union one row's
                # label proof into another row that merely names the same PDF.
                allowed = {_variant_key(v): v for v in strict_match['bindings']}
                proof = row.get('variant_form_evidence')
                if mdlp.is_row(row):
                    try:
                        proof = mdlp.validate_binding_row(row, doc, med)
                        if raw_rows is not None:
                            wanted = {v['gtin'] for v in mdlp.expected_rows(proof)}
                            subset = [v for v in raw_rows if v.get('gtin') in wanted]
                            match = match_original_to_medication(doc, med, variant_form_evidence=proof,
                                                                raw_source_rows=subset)
                            allowed.update({_variant_key(v): v for v in match['bindings']})
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue
                elif proof is not None:
                    from .eaeu_variant_form_evidence import evidence_digest, form_binding_id
                    try:
                        if (row.get('variant_form_evidence_sha256') != evidence_digest(proof)
                                or row.get('binding_id') != form_binding_id(doc['id'], med['slug'], fingerprint,
                                                                          row.get('variant_bindings'), proof)):
                            raise ValueError('variant-form binding evidence differs')
                        match = match_original_to_medication(doc, med, variant_form_evidence=proof)
                        allowed.update({_variant_key(v): v for v in match['bindings']})
                    except (ValueError, KeyError, TypeError, AttributeError):
                        pass
                for value in row.get('variant_bindings') or []:
                    if _variant_key(value) in allowed:
                        bound[_variant_key(value)] = allowed[_variant_key(value)]
            if not bound:
                continue
            result.append({
                **{key: doc[key] for key in ['id', 'title', 'content_format', 'document_type', 'registration_numbers',
                                            'version', 'approved_at', 'original_sha256', 'page_count', 'original_bytes']},
                **({'revision_date': doc['revision_date']} if doc['source']['kind'] == 'official_manufacturer' else {}),
                'source': {key: doc['source'][key] for key in ['name', 'url']},
                'download_url': '/api/instructions/originals/' + doc['id'] + '.pdf',
                'matched_variants': list(bound.values()),
                'verification': {'status': 'verified', 'verified_at': doc['verification']['verified_at']},
            })
        return result

    async def attach(self, med):
        variants = med.get('variants') or []
        med['instruction_originals'] = []
        med['instruction_original_coverage'] = {'total_variants': len(variants), 'covered_variants': 0, 'fully_covered': False}
        if not med.get('slug'):
            return med
        key = self._key(med)
        if key not in self.cache:
            self.cache[key] = AsyncTTLValue(lambda: self._load(med), ttl=self.ttl, load_timeout=self.load_timeout,
                                            name='official instruction originals')
        self.cache.move_to_end(key)
        while len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
        try:
            originals = await self.cache[key].get()
        except Exception:
            logger.warning('Official original lookup failed for %s', med.get('slug'))
            return med
        if self.raw_hints.get(key):
            try:
                # Cached results contain ordinary bindings only. MDLP positives
                # are computed afresh and are never written into that cache.
                originals = await asyncio.wait_for(
                    self._load(med, authorize_raw=True), timeout=self.load_timeout)
            except Exception:
                logger.warning('Optional original catalog lookup unavailable')
        keys = {_variant_key(v) for doc in originals for v in doc['matched_variants']}
        covered = sum(_variant_key(_variant(med, v)) in keys for v in variants)
        med['instruction_originals'] = originals
        med['instruction_original_coverage'] = {'total_variants': len(variants), 'covered_variants': covered,
                                               'fully_covered': bool(variants) and covered == len(variants)}
        return med
