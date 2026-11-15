"""Synthetic identity fixtures: no medical instruction text or external requests."""
import copy
import hashlib
import json

import pytest

from api.instruction_original_evidence import derive_identity_evidence, validate_identity_evidence


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
