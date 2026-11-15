"""Pinned factual metadata, never generated clinical text or publication approval."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from api.instruction_original_concentration import (
    LIQUID_FORMS, MAX_PACKAGES, MAX_SUBSTANCES, PROOF_MODE, prove_structured_mg_per_ml_dose,
)
from api.instruction_original_evidence import PAIRED_ENTITY_MODE, derive_identity_evidence, validate_identity_evidence
from api.instruction_original_structured_dose import classifier_evidence

FIXTURE = Path(__file__).parent / 'fixtures/eaeu-concentration-primary.json'
FIXTURE_SHA = '99c00c68f326a4e246b77196c95fabb417957960f9cea126c4bb07bd44b6e7a4'


def cases():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA
    return json.loads(raw)['cases']


def source():
    return copy.deepcopy(cases()[0]['registry_snapshot'])


def fields(snapshot, index=0):
    dosage = snapshot['package_dosages'][index]['dosage']
    return dosage['dosageUnitDetails'], next(v for v in dosage['substanceDetails'] if v['drugSubstanceRoleCode'] == '01')


def prove(snapshot):
    return prove_structured_mg_per_ml_dose(snapshot, snapshot['form'], '50 мг/мл')


@pytest.mark.parametrize('case', cases(), ids=lambda v: v['registry_snapshot']['record_id'])
def test_all_nineteen_actual_primary_records_and_twenty_one_scopes(case):
    snapshot = case['registry_snapshot']
    before = json.dumps(case, ensure_ascii=False, sort_keys=True)
    assert hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest() == case['registry_snapshot_sha256']
    registration = next(v for v in snapshot['russian_registrations'] if
                        v['registration_number'] == case['registration_number'])
    for target in case['scopes']:
        proof = prove_structured_mg_per_ml_dose(snapshot, target['form'], target['dosage'])
        assert proof['proof_mode'] == PROOF_MODE
        assert proof['literal_dosage'] == target['dosage']
        assert proof['source_dosage_unit_details'] == target['fact']['dosageUnitDetails']
        assert proof['source_active_substance'] == target['fact']['active_substance']
        scope = {'ru_number': case['registration_number'], 'form': target['form'], 'dosage': target['dosage']}
        derived = derive_identity_evidence(snapshot, registration, [scope],
            target['supported_manufacturer_names'], case['current_grls_registration'],
            manufacturer_proof_mode=PAIRED_ENTITY_MODE, dosage_proof_mode=PROOF_MODE)
        assert derived['scope_evidence'][0]['source_structured_concentration'] == proof
        assert validate_identity_evidence({'evidence': derived}, snapshot, registration, [scope],
            target['supported_manufacturer_names']) == derived
    assert json.dumps(case, ensure_ascii=False, sort_keys=True) == before


def test_positive_cohort_and_literal_form_allowlist_are_bounded():
    cohort = cases()
    assert len(cohort) == 19
    assert sum(len(c['scopes']) for c in cohort) == 21
    assert sum(t['current_variant_count'] for c in cohort for t in c['scopes']) == 37
    assert {c['registry_snapshot']['form'].casefold() for c in cohort} == LIQUID_FORMS


@pytest.mark.parametrize('target', ['details', 'active'])
@pytest.mark.parametrize('code', ['025', 'O28', '161', 'мг/мл', None, [], 25])
def test_only_latin_letter_o25_not_digit_zero_or_mass_units(target, code):
    snapshot = source()
    details, active = fields(snapshot)
    measure = details['dosageUnitMeasure'] if target == 'details' else active['substanceMeasure'][0]
    measure['substanceMeasureCode'] = code
    with pytest.raises(ValueError):
        prove(snapshot)


@pytest.mark.parametrize('kind', ['01', '02', '03', '05', '06', '07', 4, None, [], '04 '])
def test_only_direct_kind04_no_mass_package_dilution_reconstitution(kind):
    snapshot = source()
    fields(snapshot)[0]['dosageUnitKindCode'] = kind
    with pytest.raises(ValueError):
        prove(snapshot)


@pytest.mark.parametrize('target', ['details', 'active'])
@pytest.mark.parametrize('scale', ['1', '-1', '', None, 0, False])
def test_both_explicit_string_zero_scales_required(target, scale):
    snapshot = source()
    details, active = fields(snapshot)
    measure = details['dosageUnitMeasure'] if target == 'details' else active['substanceMeasure'][0]
    measure['scaleNumber'] = scale
    with pytest.raises(ValueError):
        prove(snapshot)


@pytest.mark.parametrize('value', ['0', '0.0', '-1', '1e2', ' 50', '50 ', '', None, 50,
                                  '9' * 33, '５0', '50/1'])
def test_positive_bounded_literal_ascii_amounts_only(value):
    snapshot = source()
    details, active = fields(snapshot)
    details['dosageUnitMeasure']['value'] = active['substanceMeasure'][0]['value'] = value
    with pytest.raises(ValueError):
        prove(snapshot)


@pytest.mark.parametrize('pair', [('10.0', '10'), ('7.5', '7,5'), ('50', '500')])
def test_no_arithmetic_or_decimal_spelling_equivalence(pair):
    snapshot = source()
    details, active = fields(snapshot)
    details['dosageUnitMeasure']['value'], active['substanceMeasure'][0]['value'] = pair
    with pytest.raises(ValueError, match='literally'):
        prove(snapshot)
    for measure in [details['dosageUnitMeasure'], active['substanceMeasure'][0]]:
        measure['value'] = pair[0]
    with pytest.raises(ValueError):
        prove_structured_mg_per_ml_dose(snapshot, snapshot['form'], pair[1] + ' мг/мл')
    assert prove_structured_mg_per_ml_dose(snapshot, snapshot['form'], pair[0] + ' мг/мл')['literal_amount'] == pair[0]


@pytest.mark.parametrize('text', ['-', '~', '50 мг', '5 %', '50 мг в 1 мл', '50 МГ/МЛ', '50 мг/мл основания', 50, []])
def test_nonempty_substance_text_must_literally_equal_concentration(text):
    snapshot = source()
    fields(snapshot)[1]['substanceText'] = text
    with pytest.raises(ValueError):
        prove(snapshot)


@pytest.mark.parametrize('text', [None, '', '   ', '50 мг/мл'])
def test_blank_or_exact_substance_text_does_not_change_proof_semantics(text):
    snapshot = source()
    fields(snapshot)[1]['substanceText'] = text
    assert prove(snapshot)['literal_dosage'] == '50 мг/мл'


@pytest.mark.parametrize('problem', ['combination', 'identity', 'second_measure', 'relative', 'missing_identity',
                                   'unknown_role', 'list_role', 'extra_measure_field', 'extra_details_field'])
def test_single_absolute_active_identity_and_exact_measure_shapes(problem):
    snapshot = source()
    details, active = fields(snapshot)
    substances = snapshot['package_dosages'][0]['dosage']['substanceDetails']
    if problem == 'combination':
        substances.append(copy.deepcopy(active))
    elif problem == 'identity':
        second = copy.deepcopy(snapshot['package_dosages'][0])
        snapshot['package_dosages'].append(second)
        fields(snapshot, len(snapshot['package_dosages']) - 1)[1]['activeSubstanceDetails']['activeSubstanceName'] = 'другой'
    elif problem == 'second_measure':
        active['substanceMeasure'].append(copy.deepcopy(active['substanceMeasure'][0]))
    elif problem == 'relative':
        active['substanceMeasure'][0]['substanceMeasureTypeCode'] = '02'
    elif problem == 'missing_identity':
        active.pop('activeSubstanceDetails')
    elif problem.endswith('role'):
        active['drugSubstanceRoleCode'] = [] if problem == 'list_role' else '03'
    elif problem == 'extra_measure_field':
        active['substanceMeasure'][0]['denominator'] = '1 мл'
    else:
        details['packageVolume'] = '1 мл'
    with pytest.raises(ValueError):
        prove(snapshot)


def test_bad_same_form_package_cannot_hide_behind_good_literal_text():
    snapshot = source()
    for index in range(len(snapshot['package_dosages'])):
        fields(snapshot, index)[1]['substanceText'] = '50 мг/мл'
    second = copy.deepcopy(snapshot['package_dosages'][0])
    second['dosage']['dosageUnitDetails']['dosageUnitKindCode'] = '05'
    snapshot['package_dosages'].append(second)
    with pytest.raises(ValueError):
        prove(snapshot)


def test_distinct_valid_strengths_same_active_are_preserved_not_combined():
    snapshot = source()
    second = copy.deepcopy(snapshot['package_dosages'][0])
    second['dosage']['dosageUnitDetails']['dosageUnitMeasure']['value'] = '100'
    next(v for v in second['dosage']['substanceDetails'] if v['drugSubstanceRoleCode'] == '01')['substanceMeasure'][0]['value'] = '100'
    snapshot['package_dosages'].append(second)
    assert prove(snapshot)['literal_dosage'] == '50 мг/мл'
    assert prove_structured_mg_per_ml_dose(snapshot, snapshot['form'], '100 мг/мл')['source_package_index'] == len(snapshot['package_dosages']) - 1


@pytest.mark.parametrize('form', ['таблетки', 'раствор', 'раствор для инфузий',
    'лиофилизат для приготовления раствора для инъекций', 'раствор для наружного применения'])
def test_no_generic_or_unreviewed_forms(form):
    snapshot = source()
    snapshot['form'] = form
    for package in snapshot['package_dosages']:
        package['form'] = form
    with pytest.raises(ValueError):
        prove(snapshot)


@pytest.mark.parametrize('bound', ['packages', 'substances', 'active_identity', 'malformed_package', 'missing_form'])
def test_early_bounded_lists_and_malformed_source_fail_closed(bound):
    snapshot = source()
    if bound == 'packages':
        snapshot['package_dosages'] = [snapshot['package_dosages'][0]] * (MAX_PACKAGES + 1)
    elif bound == 'substances':
        snapshot['package_dosages'][0]['dosage']['substanceDetails'] = [fields(snapshot)[1]] * (MAX_SUBSTANCES + 1)
    elif bound == 'active_identity':
        fields(snapshot)[1]['activeSubstanceDetails']['activeSubstanceName'] = 'x' * 4097
    elif bound == 'missing_form':
        snapshot['package_dosages'][0].pop('form')
    else:
        snapshot['package_dosages'].append(None)
    with pytest.raises(ValueError):
        prove(snapshot)


@pytest.mark.parametrize('problem', ['missing', 'body', 'sha', 'code_shape', 'exception'])
def test_primary_classifier_body_and_sha_are_reverified(problem):
    proofs = classifier_evidence()
    if problem == 'missing':
        proofs.pop()
    elif problem == 'body':
        proofs[0]['body_utf8'] += ' '
    elif problem == 'sha':
        proofs[0]['sha256'] = 'f' * 64
    elif problem == 'code_shape':
        proofs[0]['code'] = []
    with patch('api.instruction_original_concentration.classifier_evidence',
               side_effect=FileNotFoundError() if problem == 'exception' else None, return_value=proofs):
        with pytest.raises(ValueError):
            prove(source())
