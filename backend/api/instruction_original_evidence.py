"""Literal identity proofs for retained official originals; no inferred strengths.

EAEU's normalized ``manufacturers`` contains only explicit finished-product
manufacturers. GRLS production rows corroborate the legal entity, not its role.
No transliteration, word reordering, unit conversion or old/new RU equivalence
is performed here. The same derivation is used by preparation and validation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import unicodedata

from .medication_instructions import _identity, _ru

PAIRED_ENTITY_MODE = 'eaeu_paired_entity_v1'


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _legal(value):
    # Typographic quotation marks and case are the only legal-name aliases.
    value = unicodedata.normalize('NFKC', str(value or ''))
    return ' '.join(re.sub(r'["«»„“”‟‹›]', '', value).split()).casefold()


def _company_aliases(company):
    aliases = {company.strip()}
    # A short legal name explicitly printed in parentheses is evidence. An
    # arbitrary parenthetical note/address is not a company alias.
    short = re.search(r'\s+\(([^()]*)\)\s*$', company)
    if short and re.match(r'^(?:ООО|АО|ПАО|ЗАО|ОАО|НАО)\b', short[1].strip(), re.I):
        aliases.add(company[:short.start()].strip())
        aliases.add(short[1].strip())
    return aliases


def _production_companies(grls):
    result = []
    for line in re.split(r'_x000D_|[\r\n]+', grls.get('production_stages') or ''):
        line = line.strip()
        if not line:
            continue
        parts = line.split(',', 2)
        if len(parts) < 3 or not parts[0].strip() or not parts[1].strip():
            continue
        company = parts[1].strip()
        result.append((line, company, _company_aliases(company)))
    return result


def _paired_entities(snapshot):
    entities = snapshot.get('manufacturer_entities')
    if not isinstance(entities, list) or not 1 <= len(entities) <= 128:
        raise ValueError('paired legal identity requires explicit EAEU manufacturing entities')
    pointers, pairs = set(), []
    pointer_pattern = (r'/drugDetails/manufacturingAuthorizationHolderDetails(?:/(?:0|[1-9][0-9]*))?'
                       r'/manufacturingAreaDetails(?:/(?:0|[1-9][0-9]*))?')
    for entity in entities:
        if not isinstance(entity, dict):
            raise ValueError('invalid source manufacturing entity')
        raw, pointer = entity.get('raw_entity'), entity.get('source_pointer')
        if (not isinstance(raw, dict) or not isinstance(pointer, str)
                or not re.fullmatch(pointer_pattern, pointer) or pointer in pointers
                or entity.get('source_entity_sha256') != _hash(raw)):
            raise ValueError('source manufacturing entity pointer/hash is invalid')
        pointers.add(pointer)
        stages = raw.get('manufactureStageDetails') or []
        stages = [stages] if isinstance(stages, dict) else stages
        if not isinstance(stages, list) or not any(isinstance(v, dict) and str(v.get('manufacturingStageCode')) == '25' for v in stages):
            raise ValueError('source legal entity lacks an explicit finished-product stage25')
        name, brief = raw.get('businessEntityName'), raw.get('businessEntityBriefName')
        if entity.get('name') != name or entity.get('brief_name') != brief:
            raise ValueError('source entity names differ from its literal hashed payload')
        actual_name = name or brief
        if not isinstance(actual_name, str) or actual_name not in snapshot.get('manufacturers', []):
            raise ValueError('paired entity is absent from the explicit finished manufacturer list')
        if isinstance(name, str) and name.strip() and isinstance(brief, str) and brief.strip():
            pairs.append(entity)
    return pairs


def _check_grls(grls, registration):
    if not isinstance(grls, dict):
        raise ValueError('current_grls_registration is required')
    if (_ru(grls.get('registration_number')) != _ru(registration.get('registration_number'))
            or _ru(grls.get('registration_key')) != _ru(registration.get('registration_number'))):
        raise ValueError('GRLS evidence must use the exact current RU')
    if (grls.get('source_status_book') != 'Действующий' or grls.get('cancelled_at')
            or type(grls.get('row')) is not int or grls['row'] < 2
            or grls.get('sheet') != 'Действующий'
            or not re.fullmatch(r'[a-f0-9]{64}', str(grls.get('snapshot_sha256') or ''))
            or not str(grls.get('snapshot_file') or '').endswith('.xlsx')):
        raise ValueError('GRLS evidence requires an identified current source row')
    if _identity(grls.get('trade_name')) != _identity(registration.get('trade_name')):
        raise ValueError('GRLS trade name differs from the Russian registration')
    try:
        registered = datetime.strptime(grls.get('registered_at') or '', '%d.%m.%Y').date()
        expiry = (datetime.strptime(grls['expires_at'], '%d.%m.%Y').date()
                  if grls.get('expires_at') else None)
    except (ValueError, TypeError):
        raise ValueError('GRLS registration dates must be explicit valid dates') from None
    today = datetime.now(timezone.utc).date()
    if registered > today or (expiry and expiry <= today):
        raise ValueError('GRLS registration is not current')


def _active_strengths(snapshot, form):
    result = set()
    for package in snapshot.get('package_dosages') or []:
        if not isinstance(package, dict) or _identity(package.get('form')) != _identity(form):
            continue
        substances = (package.get('dosage') or {}).get('substanceDetails') or []
        active = [s for s in substances if isinstance(s, dict) and s.get('drugSubstanceRoleCode') == '01']
        # Multiple ingredients must not be reduced to one ingredient's dose.
        if len(active) == 1 and isinstance(active[0].get('substanceText'), str):
            result.add(active[0]['substanceText'])
    return result


def _active_tuples(snapshot, form):
    """Preserve combination identities when checking an unspecified strength."""
    tuples = set()
    for package in snapshot.get('package_dosages') or []:
        if not isinstance(package, dict) or _identity(package.get('form')) != _identity(form):
            continue
        active = [s for s in (package.get('dosage') or {}).get('substanceDetails') or []
                  if isinstance(s, dict) and s.get('drugSubstanceRoleCode') == '01']
        if any(not (isinstance(s.get('substanceText'), str) and s['substanceText'].strip())
               and not s.get('substanceMeasure') for s in active):
            raise ValueError('unspecified dosage has incomplete active-strength evidence')
        # Compare unknown numeric/unit structures literally; this is only an
        # ambiguity check, never a conversion of coded units into a strength.
        tuples.add((_hash((package.get('dosage') or {}).get('dosageUnitDetails') or {}),
                    tuple(sorted(_hash(s) for s in active))))
    return tuples


def derive_identity_evidence(snapshot, registration, scopes, manufacturers, grls_row, *, manufacturer_proof_mode=None):
    """Return literal, reproducible proof fields or raise on any uncertainty.

    This does not verify PDF approval, completeness, version or binary integrity;
    callers must independently verify those facts before publishing an original.
    """
    if manufacturer_proof_mode not in {None, PAIRED_ENTITY_MODE}:
        raise ValueError('unsupported manufacturer proof mode')
    pairs = _paired_entities(snapshot) if manufacturer_proof_mode == PAIRED_ENTITY_MODE else []
    _check_grls(grls_row, registration)
    source_names = snapshot.get('manufacturers') or []
    if not isinstance(source_names, list) or not source_names:
        raise ValueError('EAEU explicit finished-product manufacturers are required')
    companies = _production_companies(grls_row)
    manufacturer_evidence = []
    if not isinstance(manufacturers, list) or not manufacturers:
        raise ValueError('explicit manufacturer identities are required')
    for alias in manufacturers:
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError('manufacturer alias must be nonempty text')
        candidates = []
        for source_name in source_names:
            for fragment, company, aliases in companies:
                legal_aliases = {_legal(v) for v in aliases}
                if _legal(source_name) not in legal_aliases:
                    continue
                if _legal(alias) in legal_aliases | {_legal(source_name)}:
                    candidates.append({'alias': alias, 'source_name': source_name,
                                       'grls_company': company,
                                       'grls_production_fragment': fragment})
        for entity in pairs:
            entity_names = {_legal(entity['name']), _legal(entity['brief_name'])}
            for fragment, company, aliases in companies:
                legal_aliases = {_legal(v) for v in aliases}
                if not entity_names.intersection(legal_aliases):
                    continue
                if _legal(alias) in entity_names | legal_aliases:
                    candidates.append({'alias': alias, 'source_name': entity['name'],
                        'grls_company': company, 'grls_production_fragment': fragment,
                        'source_entity_pointer': entity['source_pointer'],
                        'source_entity_sha256': entity['source_entity_sha256'],
                        'source_entity_long_name': entity['name'],
                        'source_entity_brief_name': entity['brief_name']})
        if not candidates:
            raise ValueError('manufacturer alias lacks literal EAEU and GRLS legal-entity evidence')
        # Multiple GRLS stages for the same entity are harmless; pick stable
        # literal evidence, without claiming that its GRLS role was finished LF.
        manufacturer_evidence.append(sorted(candidates, key=lambda v: (
            bool(v.get('source_entity_pointer')), v['source_name'], v['grls_production_fragment'],
            v.get('source_entity_pointer', '')))[0])

    fragments = [v.strip() for v in (grls_row.get('release_forms') or '').split(';') if v.strip()]
    scope_evidence = []
    if not isinstance(scopes, list) or not scopes:
        raise ValueError('explicit scopes are required')
    for scope in scopes:
        if not isinstance(scope, dict) or scope.get('gtin') or scope.get('manufacturer_scope'):
            raise ValueError('only source-proven exact RU/form/dosage scopes are supported')
        ru, form, dosage = scope.get('ru_number'), scope.get('form'), scope.get('dosage')
        if (_ru(ru) != _ru(registration.get('registration_number'))
                or not isinstance(form, str) or not form.strip()
                or not isinstance(dosage, str) or not dosage.strip()
                or _identity(form) != _identity(snapshot.get('form'))):
            raise ValueError('scope differs from the explicit source RU/form')
        prefix = _identity(form + ', ' + dosage + ',')
        matches = [v for v in fragments if _identity(v).startswith(prefix)]
        if not matches:
            raise ValueError('scope form/dosage is absent from literal GRLS release forms')
        active_text = None
        if dosage.strip() == '~':
            if len(_active_tuples(snapshot, form)) > 1:
                raise ValueError('unspecified dosage cannot select between differing EAEU active strengths')
        else:
            matches_source = [v for v in _active_strengths(snapshot, form) if _identity(v) == _identity(dosage)]
            if not matches_source:
                raise ValueError('numeric dosage lacks a literal single-active EAEU substanceText')
            active_text = sorted(matches_source)[0]
        scope_evidence.append({'ru_number': _ru(ru), 'form': form, 'dosage': dosage,
                               'grls_release_form': sorted(matches)[0],
                               'source_form': snapshot['form'],
                               'source_active_substance_text': active_text})
    result = {'current_grls_registration': grls_row,
            'current_grls_registration_sha256': _hash(grls_row),
            'manufacturer_evidence': manufacturer_evidence,
            'scope_evidence': scope_evidence}
    if manufacturer_proof_mode is not None:
        result['manufacturer_proof_mode'] = manufacturer_proof_mode
    return result


def validate_identity_evidence(document, snapshot, registration, scopes, manufacturers):
    """Require independently reproducible evidence for every alias and scope."""
    evidence = document.get('evidence') or {}
    expected = derive_identity_evidence(snapshot, registration, scopes, manufacturers,
                                        evidence.get('current_grls_registration'),
                                        manufacturer_proof_mode=evidence.get('manufacturer_proof_mode'))
    for field, value in expected.items():
        if evidence.get(field) != value:
            raise ValueError('invalid or incomplete original identity proof: ' + field)
    return expected
