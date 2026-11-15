import copy
import json

import pytest

from api.instruction_original_evidence import derive_identity_evidence, validate_identity_evidence, _hash
from api.instruction_original_structured_dose import PROOF_MODE
from test_instruction_original_evidence import original_document
from test_instruction_original_structured_dose import source
from test_prepare_eaeu_original_pdfs import corpus_fixture
from scripts.prepare_eaeu_original_pdfs import prepare_candidate, OriginalPreparationError


def derive(doc, mode=None):
    snapshot = doc['evidence']['registry_snapshot']
    return derive_identity_evidence(snapshot, snapshot['russian_registrations'][0],
        doc['scopes'], doc['identity']['manufacturers'], doc['evidence']['current_grls_registration'],
        dosage_proof_mode=mode)


def validate(doc):
    snapshot = doc['evidence']['registry_snapshot']
    return validate_identity_evidence(doc, snapshot, snapshot['russian_registrations'][0],
        doc['scopes'], doc['identity']['manufacturers'])


def structured_document():
    doc = original_document()
    snapshot = doc['evidence']['registry_snapshot']
    snapshot['package_dosages'] = source()['package_dosages']
    doc['evidence']['registry_snapshot_sha256'] = _hash(snapshot)
    return doc


def test_legacy_literal_evidence_bytes_and_shape_are_unchanged():
    doc = original_document()
    expected = {key: doc['evidence'][key] for key in ['current_grls_registration',
        'current_grls_registration_sha256', 'manufacturer_evidence', 'scope_evidence']}
    assert json.dumps(derive(doc), ensure_ascii=False, sort_keys=True) == json.dumps(expected, ensure_ascii=False, sort_keys=True)
    assert 'dosage_proof_mode' not in derive(doc)
    assert 'source_structured_strength' not in derive(doc)['scope_evidence'][0]


def test_structured_fallback_requires_opt_in_and_revalidates_exact_primary_fields():
    doc = structured_document()
    with pytest.raises(ValueError, match='literal single-active'):
        derive(doc)
    doc['evidence'].update(derive(doc, PROOF_MODE))
    assert validate(doc)['dosage_proof_mode'] == PROOF_MODE
    scope = doc['evidence']['scope_evidence'][0]
    assert scope['source_active_substance_text'] is None
    assert scope['source_structured_strength']['literal_dosage'] == '25 мг'
    altered = copy.deepcopy(doc)
    altered['evidence']['scope_evidence'][0]['source_structured_strength']['classifiers'][0]['sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='scope_evidence'):
        validate(altered)
    altered = copy.deepcopy(doc)
    altered['evidence']['scope_evidence'][0]['source_structured_strength']['classifiers'][0]['body_utf8'] += ' '
    with pytest.raises(ValueError, match='scope_evidence'):
        validate(altered)


def test_structured_fallback_cannot_bypass_current_grls_dose_or_source_form():
    doc = structured_document()
    doc['evidence']['current_grls_registration']['release_forms'] = 'таблетки, 50 мг, 20 шт. - пачки картонные; '
    with pytest.raises(ValueError, match='literal GRLS'):
        derive(doc, PROOF_MODE)
    doc = structured_document()
    doc['evidence']['registry_snapshot']['form'] = 'капсулы'
    with pytest.raises(ValueError, match='source RU/form'):
        derive(doc, PROOF_MODE)
    for bad in ['unknown', [], 1]:
        with pytest.raises(ValueError, match='unsupported dosage'):
            derive(structured_document(), bad)


def test_offline_preparation_uses_explicit_dose_mode_and_stable_payload(tmp_path):
    folder, proof, grls, med = corpus_fixture(tmp_path)
    proof['candidate']['source']['package_dosages'] = source()['package_dosages']
    with pytest.raises(OriginalPreparationError, match='literal single-active'):
        prepare_candidate(proof, folder, [med], [grls])
    first, _ = prepare_candidate(proof, folder, [med], [grls], dosage_proof_mode=PROOF_MODE,
                                 checked_at='2026-01-01T00:00:00Z')
    second, _ = prepare_candidate(proof, folder, [med], [grls], dosage_proof_mode=PROOF_MODE,
                                  checked_at='2026-01-02T00:00:00Z')
    assert first == second
    assert first['document']['evidence']['dosage_proof_mode'] == PROOF_MODE
    assert first['document']['evidence']['scope_evidence'][0]['source_structured_strength']['unit_name'] == 'мг'
