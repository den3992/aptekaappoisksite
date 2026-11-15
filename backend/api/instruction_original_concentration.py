"""Opt-in literal O25/kind04 concentration, never a strength conversion."""
from __future__ import annotations

import copy
import hashlib
import json
import re

from .instruction_original_structured_dose import CLASSIFIERS, classifier_evidence

PROOF_MODE = 'eaeu_structured_mg_per_ml_v1'
UNIT_CODE = 'O25'  # Latin LETTER O; code 025 does not identify this unit.
UNIT_NAME = 'мг/мл'
KIND_CODE = '04'
MAX_PACKAGES = 256
MAX_SUBSTANCES = 128
# These twelve literal forms occur in the reviewed positive feasibility cohort.
# Case and surrounding whitespace are typography only; no route/form aliases.
LIQUID_FORMS = frozenset({
    'концентрат для приготовления раствора для внутривенного введения',
    'капли для приема внутрь',
    'раствор для внутривенного введения и приема внутрь',
    'раствор для внутривенного и внутримышечного введения',
    'раствор для внутримышечного введения',
    'концентрат для приготовления раствора для инфузий',
    'спрей назальный',
    'концентрат для приготовления раствора для местного и наружного применения',
    'капли глазные', 'раствор для инъекций',
    'раствор для внутриполостного введения и наружного применения',
    'раствор для подкожного введения',
})


def _form(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise ValueError('literal concentration requires a bounded full form')
    return value.strip().casefold()


def _classifiers():
    try:
        proofs = classifier_evidence()
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise ValueError('pinned concentration classifiers are unavailable or invalid') from error
    names = {}
    if not isinstance(proofs, list) or len(proofs) != 2:
        raise ValueError('both pinned concentration classifiers are required')
    for proof in proofs:
        if (not isinstance(proof, dict) or not isinstance(proof.get('code'), str)
                or proof['code'] not in CLASSIFIERS):
            raise ValueError('unknown concentration classifier')
        code, body = proof['code'], proof.get('body_utf8')
        if (code in names or not isinstance(body, str) or len(body.encode()) > 16384
                or proof.get('sha256') != CLASSIFIERS[code]['sha256']
                or hashlib.sha256(body.encode()).hexdigest() != CLASSIFIERS[code]['sha256']):
            raise ValueError('concentration classifier body or SHA differs')
        rows = json.loads(body)
        if not isinstance(rows, list) or len(rows) != CLASSIFIERS[code]['rows']:
            raise ValueError('concentration classifier rows differ')
        names[code] = {v['code']: v.get('name') for v in rows if isinstance(v, dict)}
        if len(names[code]) != len(rows):
            raise ValueError('concentration classifier codes are ambiguous')
    if (names.get('P.CLS.039', {}).get(UNIT_CODE) != UNIT_NAME
            or names.get('P.CLS.138', {}).get(KIND_CODE) != 'Дозировка указана на единицу объема\r'):
        raise ValueError('primary O25/kind04 concentration meanings differ')
    return proofs


def _amount(measure, *, active=False):
    keys = {'scaleNumber', 'substanceMeasureCode', 'value'}
    if active:
        keys.add('substanceMeasureTypeCode')
    if (not isinstance(measure, dict) or set(measure) != keys
            or measure.get('scaleNumber') != '0' or measure.get('substanceMeasureCode') != UNIT_CODE
            or (active and measure.get('substanceMeasureTypeCode') != '01')):
        raise ValueError('concentration requires exact O25 absolute measure and explicit string zero scale')
    value = measure.get('value')
    if (not isinstance(value, str) or not 1 <= len(value) <= 32
            or not re.fullmatch(r'[0-9]+(?:[.,][0-9]+)?', value) or not re.search(r'[1-9]', value)):
        raise ValueError('concentration requires a positive literal amount string')
    return value


def prove_structured_mg_per_ml_dose(snapshot, form, dosage):
    """Prove every same-form package before selecting one exact literal dose.

    No Decimal arithmetic, denominator/package-volume inference, alternate unit,
    dilution/reconstitution, ingredient sum or contradictory text fallback.
    """
    requested_form = _form(form)
    if (not isinstance(snapshot, dict) or requested_form not in LIQUID_FORMS
            or _form(snapshot.get('form')) != requested_form
            or not isinstance(dosage, str) or not 1 <= len(dosage) <= 64):
        raise ValueError('concentration requires an observed exact full liquid form and literal dose')
    packages = snapshot.get('package_dosages')
    if not isinstance(packages, list) or not 1 <= len(packages) <= MAX_PACKAGES:
        raise ValueError('concentration requires a bounded nonempty package list')
    identities, candidates = set(), []
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            raise ValueError('concentration package is malformed')
        if _form(package.get('form')) != requested_form:
            continue
        source = package.get('dosage')
        details = source.get('dosageUnitDetails') if isinstance(source, dict) else None
        if (not isinstance(details, dict) or set(details) != {'dosageUnitKindCode', 'dosageUnitMeasure'}
                or details.get('dosageUnitKindCode') != KIND_CODE):
            raise ValueError('concentration requires direct per-volume kind04 only')
        substances = source.get('substanceDetails')
        if (not isinstance(substances, list) or not 1 <= len(substances) <= MAX_SUBSTANCES
                or any(not isinstance(v, dict) or not isinstance(v.get('drugSubstanceRoleCode'), str)
                       or v['drugSubstanceRoleCode'] not in {'01', '02'} for v in substances)):
            raise ValueError('concentration requires explicit bounded active/inactive substance roles')
        active = [v for v in substances if v['drugSubstanceRoleCode'] == '01']
        if len(active) != 1:
            raise ValueError('concentration requires exactly one active constituent')
        identity = active[0].get('activeSubstanceDetails')
        if (not isinstance(identity, dict) or not isinstance(identity.get('activeSubstanceName'), str)
                or not identity['activeSubstanceName'].strip()):
            raise ValueError('concentration requires an explicit named active identity')
        identity_key = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if len(identity_key.encode()) > 4096:
            raise ValueError('concentration active identity exceeds its bound')
        identities.add(identity_key)
        measures = active[0].get('substanceMeasure')
        if not isinstance(measures, list) or len(measures) != 1:
            raise ValueError('concentration requires exactly one absolute active measure')
        value = _amount(measures[0], active=True)
        if value != _amount(details.get('dosageUnitMeasure')):
            raise ValueError('active and dosage concentration amounts differ literally')
        literal = value + ' ' + UNIT_NAME
        text = active[0].get('substanceText')
        if text is not None and (not isinstance(text, str) or (text.strip() and text.strip() != literal)):
            raise ValueError('nonempty active text contradicts the exact concentration')
        if dosage.strip() == literal:
            candidates.append({'source_package_index': index, 'source_dosage_unit_details': copy.deepcopy(details),
                'source_active_substance': copy.deepcopy(active[0]), 'literal_amount': value, 'unit_code': UNIT_CODE,
                'unit_name': UNIT_NAME, 'dosage_unit_kind_code': KIND_CODE, 'literal_dosage': literal})
    if len(identities) != 1 or not candidates:
        raise ValueError('no unambiguous exact direct concentration across same-form packages')
    proof = candidates[0]
    proof['proof_mode'] = PROOF_MODE
    proof['classifiers'] = _classifiers()
    return proof
