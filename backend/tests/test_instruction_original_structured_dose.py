import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from api.instruction_original_structured_dose import (
    DATA_ROOT, classifier_evidence, prove_structured_solid_dose,
)


def source():
    return {'package_dosages': [{'form': 'таблетки', 'dosage': {
        'dosageUnitDetails': {'dosageUnitKindCode': '01', 'dosageUnitMeasure': {
            'value': '25', 'substanceMeasureCode': '161', 'scaleNumber': '0'}},
        'substanceDetails': [{'drugSubstanceRoleCode': '01',
            'activeSubstanceDetails': {'activeSubstanceName': 'Действующее вещество'},
            'substanceMeasure': [{'value': '25', 'substanceMeasureCode': '161',
                                 'scaleNumber': '0', 'substanceMeasureTypeCode': '01'}]}]}}]}


def fields(snapshot):
    dosage = snapshot['package_dosages'][0]['dosage']
    return dosage['dosageUnitDetails'], dosage['substanceDetails'][0]


def test_direct_exact_solid_amount_keeps_raw_fields_and_pinned_primary_units():
    snapshot = source()
    proof = prove_structured_solid_dose(snapshot, 'ТАБЛЕТКИ', '25 мг')
    assert proof['literal_dosage'] == '25 мг'
    assert proof['source_package_index'] == 0
    assert proof['source_dosage_unit_details'] == fields(snapshot)[0]
    assert proof['source_active_substance'] == fields(snapshot)[1]
    assert [v['code'] for v in proof['classifiers']] == ['P.CLS.039', 'P.CLS.138']
    assert all(v['body_utf8'] and len(v['sha256']) == 64 for v in proof['classifiers'])
    proof['source_active_substance']['substanceMeasure'][0]['value'] = '999'
    assert fields(snapshot)[1]['substanceMeasure'][0]['value'] == '25'


@pytest.mark.parametrize('kind', ['03', '04', '05', None, '99'])
def test_mass_volume_package_or_unknown_kind_cannot_be_a_solid_strength(kind):
    snapshot = source()
    fields(snapshot)[0]['dosageUnitKindCode'] = kind
    with pytest.raises(ValueError):
        prove_structured_solid_dose(snapshot, 'таблетки', '25 мг')


@pytest.mark.parametrize('scale', ['1', '-1', '', None, 0])
@pytest.mark.parametrize('target', ['dosage', 'active'])
def test_nonzero_or_missing_scale_never_becomes_a_zero_scale(scale, target):
    snapshot = source()
    details, active = fields(snapshot)
    measure = details['dosageUnitMeasure'] if target == 'dosage' else active['substanceMeasure'][0]
    measure['scaleNumber'] = scale
    with pytest.raises(ValueError):
        prove_structured_solid_dose(snapshot, 'таблетки', '25 мг')


@pytest.mark.parametrize('code', ['O25', '744', 'unknown', [], None])
def test_concentration_percentage_and_unknown_units_are_not_mass(code):
    snapshot = source()
    details, active = fields(snapshot)
    details['dosageUnitMeasure']['substanceMeasureCode'] = code
    active['substanceMeasure'][0]['substanceMeasureCode'] = code
    with pytest.raises(ValueError):
        prove_structured_solid_dose(snapshot, 'таблетки', '25 мг')


def test_no_conversion_or_wrong_catalog_dose():
    snapshot = source()
    details, active = fields(snapshot)
    for measure in [details['dosageUnitMeasure'], active['substanceMeasure'][0]]:
        measure.update(value='0.03', substanceMeasureCode='163')
    assert prove_structured_solid_dose(snapshot, 'таблетки', '0.03 г')['unit_name'] == 'г'
    for catalog in ['30 мг', '300 мг', '0.030 г']:
        with pytest.raises(ValueError):
            prove_structured_solid_dose(snapshot, 'таблетки', catalog)


def test_active_and_dosage_fields_must_match_without_salt_or_base_substitution():
    snapshot = source()
    details, active = fields(snapshot)
    active['substanceMeasure'][0]['value'] = '27.5'
    with pytest.raises(ValueError, match='disagree'):
        prove_structured_solid_dose(snapshot, 'таблетки', '25 мг')
    active['substanceMeasure'][0]['value'] = '25'
    active['substanceText'] = '27,5 мг гидрохлорида в пересчете на 25 мг основания'
    with pytest.raises(ValueError, match='conflicts'):
        prove_structured_solid_dose(snapshot, 'таблетки', '25 мг')


def test_multiple_active_components_or_measure_alternatives_are_not_reduced():
    snapshot = source()
    snapshot['package_dosages'][0]['dosage']['substanceDetails'].append(copy.deepcopy(fields(snapshot)[1]))
    with pytest.raises(ValueError, match='exactly one'):
        prove_structured_solid_dose(snapshot, 'таблетки', '25 мг')
    snapshot = source()
    fields(snapshot)[1]['substanceMeasure'].append(copy.deepcopy(fields(snapshot)[1]['substanceMeasure'][0]))
    with pytest.raises(ValueError, match='one explicit'):
        prove_structured_solid_dose(snapshot, 'таблетки', '25 мг')


def test_different_actives_across_packages_do_not_share_one_strength():
    snapshot = source()
    second = copy.deepcopy(snapshot['package_dosages'][0])
    second['dosage']['substanceDetails'][0]['activeSubstanceDetails']['activeSubstanceName'] = 'Другой компонент'
    snapshot['package_dosages'].append(second)
    with pytest.raises(ValueError, match='unambiguous'):
        prove_structured_solid_dose(snapshot, 'таблетки', '25 мг')


def test_other_solid_strengths_of_the_same_identified_active_can_coexist():
    snapshot = source()
    second = copy.deepcopy(snapshot['package_dosages'][0])
    second['dosage']['dosageUnitDetails']['dosageUnitMeasure']['value'] = '50'
    second['dosage']['substanceDetails'][0]['substanceMeasure'][0]['value'] = '50'
    snapshot['package_dosages'].append(second)
    assert prove_structured_solid_dose(snapshot, 'таблетки', '25 мг')['source_package_index'] == 0
    assert prove_structured_solid_dose(snapshot, 'таблетки', '50 мг')['source_package_index'] == 1


def test_wrong_form_and_modified_classifier_fail_closed(tmp_path):
    with pytest.raises(ValueError):
        prove_structured_solid_dose(source(), 'раствор для инъекций', '25 мг')
    for path in DATA_ROOT.glob('classifier-*.json'):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    changed = tmp_path / 'classifier-P.CLS.039.json'
    changed.write_bytes(changed.read_bytes() + b' ')
    with patch('api.instruction_original_structured_dose.DATA_ROOT', tmp_path):
        with pytest.raises(ValueError, match='checksum'):
            classifier_evidence()
