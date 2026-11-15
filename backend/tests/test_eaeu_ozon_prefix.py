"""Synthetic source identities only; no clinical text or external requests."""
from copy import deepcopy
import json

import pytest

from api.instruction_original_evidence import (
    PAIRED_ENTITY_MODE, _hash, derive_identity_evidence, validate_identity_evidence,
)
from api.instruction_original_ozon_prefix import (
    PROOF_MODE, RAW_ALIAS, FULL_NAME, BRIEF_NAME, GRLS_COMPANY, FINISHED_ROLE,
)
from api.medication_original_pdfs import validate_original_document, match_original_to_medication
from scripts.prepare_eaeu_original_pdfs import prepare_candidate, prepare_corpus
from test_instruction_original_evidence import original_document, original_medication
from test_prepare_eaeu_original_pdfs import corpus_fixture, _registry_files


def ozon_inputs():
    doc = original_document()
    snap = doc['evidence']['registry_snapshot']
    snap['manufacturers'] = [FULL_NAME]
    raw = {'businessEntityName': FULL_NAME, 'businessEntityBriefName': BRIEF_NAME,
           'manufactureStageDetails': [{'manufacturingStageCode': '25'}, {'manufacturingStageCode': '60'}]}
    snap['manufacturer_entities'] = [{
        'source_pointer': '/drugDetails/manufacturingAuthorizationHolderDetails/0/manufacturingAreaDetails/0',
        'source_entity_sha256': _hash(raw), 'name': FULL_NAME, 'brief_name': BRIEF_NAME, 'raw_entity': raw}]
    doc['identity']['manufacturers'] = [RAW_ALIAS, FULL_NAME]
    grls = doc['evidence']['current_grls_registration']
    grls['production_stages'] = 'Упаковщик/фасовщик,' + GRLS_COMPANY + ', г. Пример, Россия_x000D_\n' + FINISHED_ROLE + ',' + GRLS_COMPANY + ', г. Пример, ул. Примерная, д. 6, Россия'
    return doc, snap, snap['russian_registrations'][0], grls


def derive(doc, snap, registration, grls, **extra):
    return derive_identity_evidence(snap, registration, doc['scopes'], doc['identity']['manufacturers'],
        grls, manufacturer_proof_mode=PROOF_MODE, **extra)


def ozon_document():
    doc, snap, registration, grls = ozon_inputs()
    doc['evidence'].update(derive(doc, snap, registration, grls))
    doc['evidence']['registry_snapshot_sha256'] = _hash(snap)
    return doc


def test_explicit_prefix_only_preserves_catalog_alias_and_grls_site_provenance():
    doc = ozon_document()
    before = deepcopy(doc)
    evidence = doc['evidence']
    proof = evidence['ozon_ascii_legal_prefix_proof']
    assert proof['raw_catalog_alias'] == RAW_ALIAS
    assert proof['comparison_alias'] == 'ООО ОЗОН'
    assert proof['comparison']['unchanged_core'] == 'ОЗОН'
    assert proof['site_evidence_source'] == 'current_grls_production_fragment_only'
    assert proof['eaeu_physical_site_proven'] is False
    assert proof['grls_site_address_raw'] == 'г. Пример, ул. Примерная, д. 6'
    assert proof['grls_site_country_raw'] == 'Россия'
    assert all(v['alias'] == alias and v['grls_production_fragment'].startswith(FINISHED_ROLE + ',')
               for v, alias in zip(evidence['manufacturer_evidence'], doc['identity']['manufacturers']))
    canonical = validate_original_document(doc)
    assert canonical['identity']['manufacturers'] == [RAW_ALIAS, FULL_NAME]
    med = original_medication()
    med['manufacturer'] = RAW_ALIAS
    assert match_original_to_medication(canonical, med)['covered_variants'] == 1
    assert doc == before


@pytest.mark.parametrize('alias', ['ООО ОЗОН', 'OOO ОЗОH', 'OOO OZON', 'OOO ОЗОН ФАРМ',
    'ОOO ОЗОН', 'OOО ОЗОН', 'AO ОЗОН', 'ОАО ОЗОН', 'OOO  ОЗОН', ' OOO ОЗОН', 'OOO ОЗОН '])
def test_no_other_ascii_core_mixed_legal_form_or_whitespace_alias(alias):
    doc, snap, reg, grls = ozon_inputs()
    doc['identity']['manufacturers'][0] = alias
    with pytest.raises(ValueError, match='observed raw'):
        derive(doc, snap, reg, grls)


@pytest.mark.parametrize('problem', ['entity_full', 'entity_brief', 'raw_hash', 'source_name',
    'source_stage', 'holder_pointer', 'borrowed_brief', 'separate_ozonfarm', 'source_registration',
    'foreign_source_country', 'inactive_source', 'source_cancelled', 'holder_grls', 'packer_grls',
    'qa_grls', 'foreign_grls', 'no_grls_address', 'other_grls_company', 'short_only_grls',
    'grls_currentru', 'grls_inactive', 'grls_expired', 'source_form', 'scope_form', 'scope_dose',
    'scope_ru', 'no_scope_strength', 'concentration_mode'])
def test_every_new_identity_gate_fails_closed(problem):
    doc, snap, reg, grls = ozon_inputs()
    entity = snap['manufacturer_entities'][0]
    if problem == 'entity_full':
        entity['raw_entity']['businessEntityName'] = entity['name'] = 'Общество с ограниченной ответственностью "Другой"'
        entity['source_entity_sha256'] = _hash(entity['raw_entity'])
        snap['manufacturers'] = [entity['name']]
    elif problem in {'entity_brief', 'borrowed_brief'}:
        entity['brief_name'] = entity['raw_entity']['businessEntityBriefName'] = 'ООО "Озон Фарм"' if problem == 'borrowed_brief' else 'ООО "Другой"'
        entity['source_entity_sha256'] = _hash(entity['raw_entity'])
    elif problem == 'raw_hash': entity['source_entity_sha256'] = 'f' * 64
    elif problem == 'source_name': snap['manufacturers'] = ['ООО Другой']
    elif problem == 'source_stage':
        entity['raw_entity']['manufactureStageDetails'][0]['manufacturingStageCode'] = '75'
        entity['source_entity_sha256'] = _hash(entity['raw_entity'])
    elif problem == 'holder_pointer': entity['source_pointer'] = '/drugDetails/manufacturingAuthorizationHolderDetails/0'
    elif problem == 'separate_ozonfarm':
        other = deepcopy(entity)
        other['source_pointer'] = other['source_pointer'][:-1] + '1'
        other['name'] = other['raw_entity']['businessEntityName'] = FULL_NAME.replace('Озон', 'Озон Фарм')
        other['brief_name'] = other['raw_entity']['businessEntityBriefName'] = BRIEF_NAME.replace('Озон', 'Озон Фарм')
        other['source_entity_sha256'] = _hash(other['raw_entity'])
        snap['manufacturer_entities'].append(other)
        snap['manufacturers'].append(other['name'])
    elif problem == 'source_registration':
        reg = deepcopy(reg)
        reg['registration_number'] = 'ЛП-№(000002)-(РГ-RU)'
        grls['registration_number'] = reg['registration_number']
        grls['registration_key'] = reg['registration_number'].replace('№', 'N')
        doc['scopes'][0]['ru_number'] = reg['registration_number']
    elif problem == 'foreign_source_country': reg['country'] = 'BY'
    elif problem == 'inactive_source': reg['registration_status_code'] = '02'
    elif problem == 'source_cancelled': reg['cancelled_at'] = '2026-01-01T00:00:00Z'
    elif problem in {'holder_grls', 'packer_grls', 'qa_grls'}:
        role = {'holder_grls': 'Держатель', 'packer_grls': 'Упаковщик/фасовщик', 'qa_grls': 'Выпускающий контроль качества'}[problem]
        grls['production_stages'] = role + ',' + GRLS_COMPANY + ', г. Пример, Россия'
    elif problem == 'foreign_grls': grls['production_stages'] = FINISHED_ROLE + ',' + GRLS_COMPANY + ', г. Пример, Беларусь'
    elif problem == 'no_grls_address': grls['production_stages'] = FINISHED_ROLE + ',' + GRLS_COMPANY + ', Россия'
    elif problem == 'other_grls_company': grls['production_stages'] = FINISHED_ROLE + ',' + GRLS_COMPANY.replace('Озон', 'Другой') + ', г. Пример, Россия'
    elif problem == 'short_only_grls': grls['production_stages'] = FINISHED_ROLE + ',' + BRIEF_NAME + ', г. Пример, Россия'
    elif problem == 'grls_currentru': grls['registration_number'] = 'ЛП-№(000002)-(РГ-RU)'
    elif problem == 'grls_inactive': grls['source_status_book'] = 'Недействующий'
    elif problem == 'grls_expired': grls['expires_at'] = '01.01.2020'
    elif problem == 'source_form': snap['form'] = 'капсулы'
    elif problem == 'scope_form': doc['scopes'][0]['form'] = 'капсулы'
    elif problem == 'scope_dose': doc['scopes'][0]['dosage'] = '250 мг'
    elif problem == 'scope_ru': doc['scopes'][0]['ru_number'] = 'ЛП-№(000002)-(РГ-RU)'
    elif problem == 'no_scope_strength': snap['package_dosages'][0]['dosage']['substanceDetails'][0]['substanceText'] = '50 мг'
    with pytest.raises(ValueError):
        derive(doc, snap, reg, grls, **({'dosage_proof_mode': 'future_concentration'} if problem == 'concentration_mode' else {}))


@pytest.mark.parametrize('field', ['raw_catalog_alias', 'comparison_alias', 'comparison',
    'source_entity_pointer', 'source_entity_sha256', 'source_entity_long_name',
    'source_entity_brief_name', 'source_manufacturing_stage_code',
    'current_grls_registration_sha256', 'current_grls_row', 'grls_company',
    'grls_production_fragment', 'grls_finished_role', 'grls_site_address_raw',
    'grls_site_country_raw', 'site_evidence_source', 'eaeu_physical_site_proven'])
def test_opt_in_proof_is_rederived_not_trusted(field):
    doc = ozon_document()
    doc['evidence']['ozon_ascii_legal_prefix_proof'][field] = 'invented'
    snap = doc['evidence']['registry_snapshot']
    with pytest.raises(ValueError, match='ozon_ascii_legal_prefix_proof'):
        validate_identity_evidence(doc, snap, snap['russian_registrations'][0],
                                   doc['scopes'], doc['identity']['manufacturers'])


def test_default_and_prior_paired_modes_cannot_silently_use_prefix_proof():
    doc, snap, reg, grls = ozon_inputs()
    for mode in (None, PAIRED_ENTITY_MODE):
        with pytest.raises(ValueError, match='manufacturer alias'):
            derive_identity_evidence(snap, reg, doc['scopes'], doc['identity']['manufacturers'],
                                     grls, manufacturer_proof_mode=mode)


def test_offline_preparation_uses_explicit_new_mode_and_raw_catalog_binding(tmp_path):
    folder, proof, _, med = corpus_fixture(tmp_path)
    doc, snapshot, reg, grls = ozon_inputs()
    # Keep the actual synthetic PDF's pinned attachment and source URL.
    old = proof['candidate']['source']
    snapshot['source_url'] = old['source_url']
    reg['documents'] = old['russian_registrations'][0]['documents']
    proof['candidate'].update(source=snapshot, registration=reg, document=reg['documents'][0])
    med['manufacturer'] = RAW_ALIAS
    index, validation = _registry_files(tmp_path, [snapshot])
    catalog, grls_path = tmp_path / 'catalog.jsonl', tmp_path / 'grls.jsonl'
    catalog.write_text(json.dumps({'medication': med}, ensure_ascii=False) + '\n')
    grls_path.write_text(json.dumps(grls, ensure_ascii=False) + '\n')
    (folder / 'source-proof.json').write_text(json.dumps(proof, ensure_ascii=False))
    before = catalog.read_bytes()
    report = prepare_corpus(folder.parent, catalog, grls_path, tmp_path / 'test-output.jsonl', tmp_path / 'drafts.jsonl',
        registry_index_path=index, registry_validation_path=validation, manufacturer_proof_mode=PROOF_MODE)
    assert report['covered_cards'] == report['covered_variants'] == 1
    assert report['counts']['verified_original_documents'] == 1
    assert report['network_requests'] == report['database_writes'] == 0
    wrapper = json.loads((tmp_path / 'test-output.jsonl').read_text())
    assert RAW_ALIAS in wrapper['document']['identity']['manufacturers']
    assert wrapper['document']['evidence']['manufacturer_proof_mode'] == PROOF_MODE
    first_id = wrapper['document']['id']
    second, _ = prepare_candidate(proof, folder, [med], [grls], manufacturer_proof_mode=PROOF_MODE)
    # Generation proof is fingerprinted; repeated identical corpus generation
    # retains the same fingerprint/checkpoint, with no catalog edit.
    again = prepare_corpus(folder.parent, catalog, grls_path, tmp_path / 'test-output2.jsonl', tmp_path / 'drafts2.jsonl',
        registry_index_path=index, registry_validation_path=validation, manufacturer_proof_mode=PROOF_MODE)
    assert json.loads((tmp_path / 'test-output2.jsonl').read_text())['document']['id'] == first_id
    assert again['covered_variants'] == 1 and second['document']['identity']['manufacturers'] == [RAW_ALIAS, FULL_NAME]
    assert catalog.read_bytes() == before
