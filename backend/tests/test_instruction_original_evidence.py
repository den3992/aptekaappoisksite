"""Synthetic identity fixtures: no medical instruction text or external requests."""
import copy
import hashlib
import json

import pytest

from api.instruction_original_evidence import PAIRED_ENTITY_MODE, derive_identity_evidence, validate_identity_evidence


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def original_medication():
    return {'slug': 'synthetic-example', 'name': 'Тестовый препарат', 'is_canonical': True,
            'manufacturer': 'АО ПРИМЕР', 'form': 'таблетки', 'dosage': '25 мг',
            'variants': [{'gtin': '04600000000001', 'ru_number': 'ЛП-№(000001)-(РГ-RU)',
                          'label_name': 'Тестовый препарат', 'pack_size': '20'}]}


def original_document():
    ru, oid = 'ЛП-№(000001)-(РГ-RU)', '0123456789abcdef01234567'
    path, sha = 'example/original.pdf', 'a' * 64
    registration = {'registration_number': ru, 'country': 'RU', 'registration_status_code': '03',
                    'registration_status': 'зарегистрировано', 'cancelled_at': None,
                    'valid_until': None, 'trade_name': 'Тестовый препарат',
                    'documents': [{'kind': 'USAGE_INSTRUCTION', 'uploaded_file_path': path,
                                   'size': 100, 'valid_until': None, 'review_flags': []}]}
    snapshot = {'record_id': oid, 'metadata_sha256': 'b' * 64, 'form': 'таблетки',
                'manufacturers': ['Акционерное общество «Пример»'],
                'russian_registrations': [registration], 'source_version': 1,
                'package_dosages': [{'form': 'таблетки', 'dosage': {'substanceDetails': [
                    {'drugSubstanceRoleCode': '01', 'substanceText': '25 мг'}]}}]}
    grls = {'registration_number': ru, 'registration_key': ru.replace('№', 'N'),
            'registered_at': '01.01.2020', 'expires_at': '', 'cancelled_at': '',
            'trade_name': 'Тестовый препарат', 'holder': 'ООО Держатель',
            'release_forms': 'таблетки, 25 мг, 20 шт. - пачки картонные; ',
            'production_stages': 'Упаковщик/фасовщик (вторичная/третичная упаковка),Акционерное общество "Пример" (АО "Пример"), Россия_x000D_\n',
            'snapshot_file': '/synthetic/current.xlsx', 'snapshot_sha256': 'c' * 64,
            'sheet': 'Действующий', 'row': 2, 'source_status_book': 'Действующий'}
    scopes = [{'ru_number': ru, 'form': 'таблетки', 'dosage': '25 мг'}]
    manufacturers = ['АО ПРИМЕР', 'Акционерное общество «Пример»']
    evidence = {'registry_snapshot': snapshot, 'registry_snapshot_sha256': _hash(snapshot),
                'original_sha256': sha, 'full_pdf_checked': True,
                'not_unapproved_project': True, 'finished_manufacturer_confirmed': True,
                'checked_at': '2026-01-01T00:00:00Z',
                'identity_review': 'Синтетические точные форма, дозировка и изготовитель проверены по двум явным первичным записям.',
                'document_version_review': 'Синтетическое единственное текущее вложение инструкции связано с точным регистрационным удостоверением.'}
    evidence.update(derive_identity_evidence(snapshot, registration, scopes, manufacturers, grls))
    return {'id': 'synthetic-original', 'title': 'Синтетический оригинал',
            'document_type': 'medical_instruction', 'content_format': 'official_original_pdf',
            'registration_numbers': [ru], 'version': 'synthetic-v1', 'approved_at': None,
            'retrieved_at': '2026-01-01T00:00:00Z', 'original_sha256': sha,
            'original_bytes': 100, 'page_count': 1,
            'source': {'name': 'Официальный реестр: синтетический fixture',
                       'url': 'https://pharma.eaeunion.org/pharma/registers/26/ru/register/registered-medicinal-products/' + oid,
                       'kind': 'official_registry', 'provider': 'eaeu', 'record_id': oid,
                       'uploaded_file_path': path, 'metadata_sha256': 'b' * 64},
            'identity': {'trade_name': 'Тестовый препарат', 'manufacturers': manufacturers},
            'scopes': scopes, 'verification': {'status': 'verified',
                'verified_at': '2026-01-01T00:00:00Z', 'verified_by': 'synthetic fixture',
                'method': 'synthetic literal source proof'}, 'evidence': evidence}


def _validate(doc):
    snapshot = doc['evidence']['registry_snapshot']
    return validate_identity_evidence(doc, snapshot, snapshot['russian_registrations'][0],
                                      doc['scopes'], doc['identity']['manufacturers'])


def test_valid_literal_aliases_and_source_finished_role():
    doc = original_document()
    assert _validate(doc)['scope_evidence'][0]['source_active_substance_text'] == '25 мг'
    # GRLS calls the same company a packer; only EAEU supplied the finished role.
    assert 'Упаковщик' in doc['evidence']['manufacturer_evidence'][0]['grls_production_fragment']


@pytest.mark.parametrize('mutation', ['foreign_alias', 'wrong_dose', 'wrong_form', 'wrong_ru',
                                    'evidence_fragment', 'hash', 'expired', 'inactive',
                                    'latin_prefix', 'holder', 'unit_conversion', 'multiple_actives'])
def test_reject_unproven_or_changed_identity(mutation):
    doc = original_document()
    if mutation == 'foreign_alias':
        doc['identity']['manufacturers'].append('АО Чужой')
    elif mutation == 'wrong_dose':
        doc['scopes'][0]['dosage'] = '250 мг'
    elif mutation == 'wrong_form':
        doc['scopes'][0]['form'] = 'капсулы'
    elif mutation == 'wrong_ru':
        doc['scopes'][0]['ru_number'] = 'ЛП-№(000002)-(РГ-RU)'
    elif mutation == 'evidence_fragment':
        doc['evidence']['scope_evidence'][0]['grls_release_form'] += ' invented'
    elif mutation == 'hash':
        doc['evidence']['current_grls_registration_sha256'] = 'd' * 64
    elif mutation == 'expired':
        doc['evidence']['current_grls_registration']['expires_at'] = '01.01.2020'
    elif mutation == 'inactive':
        doc['evidence']['current_grls_registration']['source_status_book'] = 'Недействующий'
    elif mutation == 'latin_prefix':
        doc['identity']['manufacturers'].append('AO ПРИМЕР')
    elif mutation == 'holder':
        doc['identity']['manufacturers'].append('ООО Держатель')
    elif mutation == 'unit_conversion':
        doc['scopes'][0]['dosage'] = '0.025 г'
    else:
        doc['evidence']['registry_snapshot']['package_dosages'][0]['dosage']['substanceDetails'].append(
            {'drugSubstanceRoleCode': '01', 'substanceText': '50 мг'})
    with pytest.raises(ValueError):
        _validate(doc)


def test_tilde_requires_literal_grls_and_same_source_form():
    doc = original_document()
    grls = doc['evidence']['current_grls_registration']
    scopes = copy.deepcopy(doc['scopes'])
    scopes[0]['dosage'] = '~'
    snapshot = doc['evidence']['registry_snapshot']
    registration = snapshot['russian_registrations'][0]
    with pytest.raises(ValueError):
        derive_identity_evidence(snapshot, registration, scopes, doc['identity']['manufacturers'], grls)
    grls['release_forms'] = 'таблетки, ~, 20 шт. - пачки картонные; '
    result = derive_identity_evidence(snapshot, registration, scopes, doc['identity']['manufacturers'], grls)
    assert result['scope_evidence'][0]['source_active_substance_text'] is None


def test_no_arbitrary_parenthesis_company_alias():
    doc = original_document()
    grls = doc['evidence']['current_grls_registration']
    grls['production_stages'] = 'Производитель,Акционерное общество "Пример" (чужая компания), Россия'
    with pytest.raises(ValueError):
        _validate(doc)


def test_tilde_does_not_select_between_differing_source_strengths():
    doc = original_document()
    snapshot = doc['evidence']['registry_snapshot']
    grls = doc['evidence']['current_grls_registration']
    grls['release_forms'] = 'таблетки, ~, 20 шт. - пачки картонные; '
    doc['scopes'][0]['dosage'] = '~'
    second = copy.deepcopy(snapshot['package_dosages'][0])
    second['dosage']['substanceDetails'][0]['substanceText'] = '50 мг'
    snapshot['package_dosages'].append(second)
    with pytest.raises(ValueError, match='differing EAEU active strengths'):
        derive_identity_evidence(snapshot, snapshot['russian_registrations'][0], doc['scopes'],
                                 doc['identity']['manufacturers'], grls)


def paired_document():
    doc = original_document()
    snapshot = doc['evidence']['registry_snapshot']
    raw = {'businessEntityName': snapshot['manufacturers'][0],
           'businessEntityBriefName': 'АО «Пример»',
           'manufactureStageDetails': [{'manufacturingStageCode': '25'}]}
    snapshot['manufacturer_entities'] = [{
        'source_pointer': '/drugDetails/manufacturingAuthorizationHolderDetails/0/manufacturingAreaDetails/0',
        'source_entity_sha256': _hash(raw), 'name': raw['businessEntityName'],
        'brief_name': raw['businessEntityBriefName'], 'raw_entity': raw}]
    # No GRLS short alias: the new short name is proven solely by the exact
    # same EAEU finished entity whose long name literally matches GRLS.
    grls = doc['evidence']['current_grls_registration']
    grls['production_stages'] = 'Производитель (готовой ЛФ),Акционерное общество "Пример", Россия_x000D_\n'
    doc['evidence'].update(derive_identity_evidence(snapshot, snapshot['russian_registrations'][0],
        doc['scopes'], doc['identity']['manufacturers'], grls, manufacturer_proof_mode=PAIRED_ENTITY_MODE))
    doc['evidence']['registry_snapshot_sha256'] = _hash(snapshot)
    return doc


def test_same_finished_entity_long_brief_pair_is_explicit_opt_in():
    doc = paired_document()
    expected = _validate(doc)
    short = expected['manufacturer_evidence'][0]
    assert short['source_entity_pointer'].endswith('/manufacturingAreaDetails/0')
    assert short['source_entity_sha256'] == _hash(doc['evidence']['registry_snapshot']['manufacturer_entities'][0]['raw_entity'])
    assert short['source_entity_brief_name'] == 'АО «Пример»'
    # This document cannot silently fall back to the older proof definition.
    doc['evidence'].pop('manufacturer_proof_mode')
    with pytest.raises(ValueError):
        _validate(doc)


@pytest.mark.parametrize('problem', ['mixed_fields', 'holder_pointer', 'packer', 'bad_hash',
                                   'ao_to_oao', 'latin_prefix', 'unknown_mode'])
def test_paired_entity_proof_rejects_unproven_aliases(problem):
    doc = paired_document()
    entity = doc['evidence']['registry_snapshot']['manufacturer_entities'][0]
    if problem == 'mixed_fields':
        entity['brief_name'] = 'АО Другой'
    elif problem == 'holder_pointer':
        entity['source_pointer'] = '/drugDetails/manufacturingAuthorizationHolderDetails/0'
    elif problem == 'packer':
        entity['raw_entity']['manufactureStageDetails'][0]['manufacturingStageCode'] = '60'
        entity['source_entity_sha256'] = _hash(entity['raw_entity'])
    elif problem == 'bad_hash':
        entity['source_entity_sha256'] = 'd' * 64
    elif problem == 'ao_to_oao':
        doc['identity']['manufacturers'][0] = 'ОАО ПРИМЕР'
    elif problem == 'latin_prefix':
        doc['identity']['manufacturers'][0] = 'AO ПРИМЕР'
    else:
        doc['evidence']['manufacturer_proof_mode'] = 'invented'
    with pytest.raises(ValueError):
        _validate(doc)


def test_different_finished_entity_brief_cannot_bind_the_first_grls_company():
    doc = paired_document()
    snapshot = doc['evidence']['registry_snapshot']
    other = copy.deepcopy(snapshot['manufacturer_entities'][0])
    other['source_pointer'] = other['source_pointer'][:-1] + '1'
    other['name'] = other['raw_entity']['businessEntityName'] = 'Акционерное общество «Другой»'
    other['brief_name'] = other['raw_entity']['businessEntityBriefName'] = 'АО «Другой»'
    other['source_entity_sha256'] = _hash(other['raw_entity'])
    snapshot['manufacturer_entities'].append(other)
    snapshot['manufacturers'].append(other['name'])
    doc['identity']['manufacturers'][0] = 'АО Другой'
    with pytest.raises(ValueError):
        _validate(doc)


def test_ozon_farm_pair_never_becomes_ozon_alias():
    doc = paired_document()
    snapshot = doc['evidence']['registry_snapshot']
    entity = snapshot['manufacturer_entities'][0]
    entity['name'] = entity['raw_entity']['businessEntityName'] = 'Общество с ограниченной ответственностью «Озон Фарм»'
    entity['brief_name'] = entity['raw_entity']['businessEntityBriefName'] = 'ООО «Озон Фарм»'
    entity['source_entity_sha256'] = _hash(entity['raw_entity'])
    snapshot['manufacturers'] = [entity['name']]
    doc['identity']['manufacturers'] = ['ООО ОЗОН']
    doc['evidence']['current_grls_registration']['production_stages'] = 'Производитель (готовой ЛФ),' + entity['name'] + ', Россия'
    with pytest.raises(ValueError, match='manufacturer alias'):
        _validate(doc)


def test_legacy_evidence_and_document_bytes_remain_unchanged():
    doc = original_document()
    before = json.dumps(doc, ensure_ascii=False, sort_keys=True)
    result = _validate(doc)
    assert 'manufacturer_proof_mode' not in result
    assert all('source_entity_pointer' not in row for row in result['manufacturer_evidence'])
    assert json.dumps(doc, ensure_ascii=False, sort_keys=True) == before
