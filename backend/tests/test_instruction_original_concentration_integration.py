import copy
import json
import subprocess
import sys

import pytest

from api.instruction_original_concentration import PROOF_MODE
from api.instruction_original_evidence import _hash, derive_identity_evidence, validate_identity_evidence
from api.medication_original_pdfs import validate_original_document
from scripts.prepare_eaeu_original_pdfs import OriginalPreparationError, prepare_candidate, prepare_corpus
from test_instruction_original_concentration import source
from test_instruction_original_evidence import original_document
from test_prepare_eaeu_original_pdfs import corpus_fixture, _registry_files


def concentration_document():
    doc = original_document()
    snapshot = doc['evidence']['registry_snapshot']
    factual = source()
    snapshot['form'] = factual['form']
    snapshot['package_dosages'] = factual['package_dosages']
    doc['scopes'][0].update(form=factual['form'], dosage='50 мг/мл')
    doc['evidence']['current_grls_registration']['release_forms'] = factual['form'] + ', 50 мг/мл, 1 мл - ампулы; '
    doc['evidence']['registry_snapshot_sha256'] = _hash(snapshot)
    return doc


def derive(doc, mode=PROOF_MODE):
    snapshot = doc['evidence']['registry_snapshot']
    return derive_identity_evidence(snapshot, snapshot['russian_registrations'][0], doc['scopes'],
        doc['identity']['manufacturers'], doc['evidence']['current_grls_registration'], dosage_proof_mode=mode)


def validate(doc):
    snapshot = doc['evidence']['registry_snapshot']
    return validate_identity_evidence(doc, snapshot, snapshot['russian_registrations'][0],
        doc['scopes'], doc['identity']['manufacturers'])


def corpus(tmp_path):
    folder, proof, grls, med = corpus_fixture(tmp_path)
    doc = concentration_document()
    proof['candidate']['source']['form'] = doc['evidence']['registry_snapshot']['form']
    proof['candidate']['source']['package_dosages'] = doc['evidence']['registry_snapshot']['package_dosages']
    grls['release_forms'] = doc['evidence']['current_grls_registration']['release_forms']
    med.update(form=proof['candidate']['source']['form'], dosage='50 мг/мл')
    return folder, proof, grls, med


def test_explicit_api_mode_and_independently_reproduced_proof():
    doc = concentration_document()
    with pytest.raises(ValueError, match='literal single-active'):
        derive(doc, None)
    doc['evidence'].update(derive(doc))
    assert validate(doc)['dosage_proof_mode'] == PROOF_MODE
    assert validate_original_document(doc)['evidence']['dosage_proof_mode'] == PROOF_MODE
    proof = doc['evidence']['scope_evidence'][0]
    assert proof['source_active_substance_text'] is None
    assert 'source_structured_strength' not in proof
    assert proof['source_structured_concentration']['unit_code'] == 'O25'


@pytest.mark.parametrize('mutation', ['unit', 'kind', 'classifiers', 'proof_amount', 'proof_source', 'mode',
                                    'new_good_text_bad_package', 'grls_dose', 'source_form', 'old_ru',
                                    'scope_decimal', 'manufacturer', 'inactive'])
def test_api_cannot_bypass_existing_identity_or_new_evidence(mutation):
    doc = concentration_document()
    doc['evidence'].update(derive(doc))
    snapshot = doc['evidence']['registry_snapshot']
    structured = doc['evidence']['scope_evidence'][0]['source_structured_concentration']
    if mutation == 'unit':
        structured['unit_code'] = '025'
    elif mutation == 'kind':
        structured['dosage_unit_kind_code'] = '05'
    elif mutation == 'classifiers':
        structured['classifiers'][1]['body_utf8'] += ' '
    elif mutation == 'proof_amount':
        structured['literal_amount'] = '500'
    elif mutation == 'proof_source':
        structured['source_active_substance']['substanceMeasure'][0]['scaleNumber'] = '1'
    elif mutation == 'mode':
        doc['evidence'].pop('dosage_proof_mode')
    elif mutation == 'new_good_text_bad_package':
        for package in snapshot['package_dosages']:
            next(v for v in package['dosage']['substanceDetails'] if v['drugSubstanceRoleCode'] == '01')['substanceText'] = '50 мг/мл'
        snapshot['package_dosages'][-1]['dosage']['dosageUnitDetails']['dosageUnitKindCode'] = '05'
    elif mutation == 'grls_dose':
        doc['evidence']['current_grls_registration']['release_forms'] = snapshot['form'] + ', 500 мг/мл, 1 мл - ампулы; '
    elif mutation == 'source_form':
        snapshot['form'] = 'раствор'
    elif mutation == 'old_ru':
        doc['scopes'][0]['ru_number'] = 'ЛП-005174'
    elif mutation == 'scope_decimal':
        doc['scopes'][0]['dosage'] = '50.0 мг/мл'
    elif mutation == 'manufacturer':
        doc['identity']['manufacturers'].append('ООО Держатель')
    else:
        doc['evidence']['current_grls_registration']['source_status_book'] = 'Недействующий'
    with pytest.raises(ValueError):
        validate(doc)


def test_builder_explicit_mode_stability_and_generation_fingerprint(tmp_path):
    folder, proof, grls, med = corpus(tmp_path)
    with pytest.raises(OriginalPreparationError):
        prepare_candidate(proof, folder, [med], [grls])
    proof['source_normalization_generation'] = {'method': 'factual_test_generation', 'snapshot': _hash(proof['candidate']['source'])}
    first, preview = prepare_candidate(proof, folder, [med], [grls], dosage_proof_mode=PROOF_MODE,
                                      checked_at='2026-01-01T00:00:00Z')
    second, _ = prepare_candidate(proof, folder, [med], [grls], dosage_proof_mode=PROOF_MODE,
                                 checked_at='2026-01-02T00:00:00Z')
    assert first == second
    assert preview['matches'][0]['covered_variants'] == 1
    assert first['document']['evidence']['source_normalization_generation'] == proof['source_normalization_generation']
    proof['source_normalization_generation']['snapshot'] = 'f' * 64
    third, _ = prepare_candidate(proof, folder, [med], [grls], dosage_proof_mode=PROOF_MODE)
    assert third['document']['id'] != first['document']['id']


@pytest.mark.parametrize('problem', ['project', 'multiple_usage', 'old_registration', 'foreign_maker'])
def test_builder_retains_existing_attachment_registration_and_manufacturer_guards(tmp_path, problem):
    folder, proof, grls, med = corpus(tmp_path)
    registration = proof['candidate']['registration']
    if problem == 'project':
        proof['candidate']['document']['review_flags'] = ['source_attachment_mentions_project']
    elif problem == 'multiple_usage':
        registration['documents'].append(copy.deepcopy(proof['candidate']['document']))
    elif problem == 'old_registration':
        registration['registration_status_code'] = '04'
    else:
        med['manufacturer'] = 'АО Чужой'
    with pytest.raises(OriginalPreparationError):
        prepare_candidate(proof, folder, [med], [grls], dosage_proof_mode=PROOF_MODE)


@pytest.mark.parametrize('changed', [False, True])
def test_corpus_full_registry_upgrade_is_additive_hash_pinned_and_opt_in(tmp_path, changed):
    folder, proof, grls, med = corpus(tmp_path)
    (folder / 'source-proof.json').write_text(json.dumps(proof, ensure_ascii=False))
    original_bytes = (folder / 'source-proof.json').read_bytes()
    current = copy.deepcopy(proof['candidate']['source'])
    current['manufacturer_entities'] = []
    if changed:
        current['package_dosages'][0]['dosage']['dosageUnitDetails']['dosageUnitKindCode'] = '05'
    index, validation = _registry_files(tmp_path, [current])
    catalog_path, grls_path = tmp_path / 'catalog.jsonl', tmp_path / 'grls.jsonl'
    catalog_path.write_text(json.dumps({'medication': med}, ensure_ascii=False) + '\n')
    grls_path.write_text(json.dumps(grls, ensure_ascii=False) + '\n')
    output = tmp_path / 'candidates.jsonl'
    report = prepare_corpus(folder.parent, catalog_path, grls_path, output, tmp_path / 'drafts.jsonl',
        registry_index_path=index, registry_validation_path=validation, dosage_proof_mode=PROOF_MODE)
    assert (folder / 'source-proof.json').read_bytes() == original_bytes
    if changed:
        assert report['counts'].get('verified_original_documents', 0) == 0
        assert 'not additive' in (tmp_path / 'drafts.jsonl').read_text()
    else:
        assert report['counts']['verified_original_documents'] == 1
        doc = json.loads(output.read_text())['document']
        generation = doc['evidence']['source_normalization_generation']
        assert generation['new_normalized_snapshot_sha256'] == _hash(current)
        assert generation['legacy_normalized_snapshot_sha256'] == _hash(proof['candidate']['source'])
        assert generation['preserved_raw_metadata_sha256'] == current['metadata_sha256']


def test_cli_exposes_only_explicit_concentration_choice():
    result = subprocess.run([sys.executable, '-m', 'scripts.prepare_eaeu_original_pdfs', '--help'],
                            check=True, capture_output=True, text=True)
    assert PROOF_MODE in result.stdout
    assert 'eaeu_structured_solid_v1' in result.stdout
