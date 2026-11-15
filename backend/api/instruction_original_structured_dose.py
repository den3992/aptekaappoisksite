"""Narrow, non-converting strength proof from pinned primary EAEU fields.

This is an opt-in supplement to literal substanceText matching. It never derives
a concentration from package size, adds ingredients, or changes an amount/unit.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re

from .medication_instructions import _identity

PROOF_MODE = 'eaeu_structured_solid_v1'
DATA_ROOT = Path(__file__).parent / 'data' / 'eaeu'
CLASSIFIERS = {
    'P.CLS.039': {
        'sha256': '4c5b93f323a0992ec3d5d73891740c1de9c6e9fa83822b46d179b1bd3c9e63c7',
        'retrieved_at': '2026-11-15T05:36:52.381400+00:00',
        'rows': 84,
    },
    'P.CLS.138': {
        'sha256': 'fade621ef19a2e9d0b5f55f472ec6dbd39e8e124406b2eab9a6b9ff4c25445f9',
        'retrieved_at': '2026-11-15T05:36:52.551483+00:00',
        'rows': 9,
    },
}
SOLID_FORMS = frozenset({
    'таблетки', 'капсулы', 'капсулы твердые', 'таблетки диспергируемые',
    'таблетки, покрытые оболочкой', 'таблетки, покрытые пленочной оболочкой',
})
MASS_UNITS = {'161': 'мг', '163': 'г'}


def classifier_evidence():
    """Return the exact pinned public responses, never a runtime network lookup."""
    result = []
    for code, expected in CLASSIFIERS.items():
        raw = (DATA_ROOT / f'classifier-{code}.json').read_bytes()
        if len(raw) > 16384 or hashlib.sha256(raw).hexdigest() != expected['sha256']:
            raise ValueError('pinned EAEU classifier checksum differs')
        rows = json.loads(raw)
        if (not isinstance(rows, list) or len(rows) != expected['rows']
                or len({v.get('code') for v in rows if isinstance(v, dict)}) != len(rows)):
            raise ValueError('pinned EAEU classifier shape differs')
        names = {v['code']: v.get('name') for v in rows}
        if code == 'P.CLS.039' and any(names.get(k) != v for k, v in MASS_UNITS.items()):
            raise ValueError('pinned EAEU mass unit names differ')
        result.append({'code': code, 'source_url': f'https://pharma.eaeunion.org//dict/{code}',
                       'sha256': expected['sha256'], 'retrieved_at': expected['retrieved_at'],
                       'body_utf8': raw.decode('utf-8')})
    return result


def _amount(measure):
    if not isinstance(measure, dict) or measure.get('scaleNumber') != '0':
        raise ValueError('structured strength requires an explicit zero scale')
    value, code = measure.get('value'), measure.get('substanceMeasureCode')
    if (not isinstance(value, str) or len(value) > 32
            or not re.fullmatch(r'\d+(?:[.,]\d+)?', value)
            or not re.search(r'[1-9]', value) or not isinstance(code, str) or code not in MASS_UNITS):
        raise ValueError('structured strength requires a positive literal amount and known mass unit')
    return value, code


def prove_structured_solid_dose(snapshot, form, dosage):
    """Prove one exact solid-form dose; return raw source fields and unit proofs.

All same-form packages must identify the same single active constituent. A
nonempty contradictory substanceText cannot be bypassed by structured fields.
"""
    if not isinstance(snapshot, dict) or _identity(form) not in SOLID_FORMS or not isinstance(dosage, str):
        raise ValueError('structured strength supports only explicit solid forms')
    packages = snapshot.get('package_dosages') or []
    if not isinstance(packages, list):
        raise ValueError('structured strength requires a package list')
    identities, candidates = set(), []
    for index, package in enumerate(packages):
        if not isinstance(package, dict) or _identity(package.get('form')) != _identity(form):
            continue
        source = package.get('dosage') or {}
        if not isinstance(source, dict):
            raise ValueError('structured strength requires explicit dosage fields')
        details = source.get('dosageUnitDetails') or {}
        if not isinstance(details, dict):
            raise ValueError('structured strength requires explicit dosage unit fields')
        if details.get('dosageUnitKindCode') not in {'01', '02'}:
            raise ValueError('structured strength excludes package, mass and volume dose kinds')
        substances = source.get('substanceDetails') or []
        if not isinstance(substances, list):
            raise ValueError('structured strength requires a substance list')
        active = [v for v in substances
                  if isinstance(v, dict) and v.get('drugSubstanceRoleCode') == '01']
        if len(active) != 1:
            raise ValueError('structured strength requires exactly one active constituent')
        identity = active[0].get('activeSubstanceDetails') or {}
        if (not isinstance(identity, dict) or not isinstance(identity.get('activeSubstanceName'), str)
                or not identity['activeSubstanceName'].strip()):
            raise ValueError('structured strength requires an identified active constituent')
        identities.add(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        measures = active[0].get('substanceMeasure') or []
        if (not isinstance(measures, list) or len(measures) != 1 or not isinstance(measures[0], dict)
                or measures[0].get('substanceMeasureTypeCode') != '01'):
            raise ValueError('structured strength requires one explicit active amount')
        amount = _amount(measures[0])
        if amount != _amount(details.get('dosageUnitMeasure')):
            raise ValueError('active and dosage amounts or units disagree')
        literal = amount[0] + ' ' + MASS_UNITS[amount[1]]
        text = active[0].get('substanceText')
        if text is not None and (not isinstance(text, str) or (text.strip() and _identity(text) != _identity(literal))):
            raise ValueError('literal active strength conflicts with structured amount')
        if _identity(literal) == _identity(dosage):
            candidates.append({'source_package_index': index,
                'source_dosage_unit_details': copy.deepcopy(details),
                'source_active_substance': copy.deepcopy(active[0]),
                'literal_amount': amount[0], 'unit_code': amount[1],
                'unit_name': MASS_UNITS[amount[1]], 'literal_dosage': literal})
    if len(identities) != 1 or not candidates:
        raise ValueError('no unambiguous exact structured solid strength')
    proof = candidates[0]
    proof['proof_mode'] = PROOF_MODE
    proof['classifiers'] = classifier_evidence()
    return proof
