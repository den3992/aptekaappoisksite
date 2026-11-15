"""Offline Canon-only whole originals; no provider, version or identity inference."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from api.instruction_original_delivery import OfficialPdfCache, OriginalUnavailable
from api.manufacturer_original_pdfs import PHYSICAL_FINISHED_STAGE_MODE, canon_pdf_url, validate_product_html
from api.medication_original_pdfs import canonical_hash, match_original_to_medication, validate_original_document
from scripts.import_medication_originals import validate_archive
from test_instruction_original_binary import project_pdf_bytes
from test_instruction_originals import Clock, Reply, Session, fixture, workflow
from test_manufacturer_originals import manufacturer_fixture, write_archive


def canon_fixture():
    doc, med, body, _ = manufacturer_fixture()
    page = 'https://www.canonpharma.ru/catalog/synthetic/'
    href = '/upload/iblock/synthetic/original.pdf'
    label = 'Скачать информацию для пациента'
    pdf_url = 'https://www.canonpharma.ru' + href
    html = ('<h1>Синтетический препарат</h1><a href="' + href + '">' + label + '</a>').encode()
    doc['id'] = 'canon-synthetic-original'
    doc['source'].update(provider='canon', name='Официальный производитель: Canon fixture', url=page, pdf_url=pdf_url)
    doc['evidence']['product_page'] = {'url': page, 'html_sha256': hashlib.sha256(html).hexdigest(),
                                     'actual_href': href, 'actual_label': label, 'pdf_url': pdf_url}
    return doc, med, body, html


def with_html(doc, html):
    result = copy.deepcopy(doc)
    result['evidence']['product_page']['html_sha256'] = hashlib.sha256(html).hexdigest()
    return result


def physical_stage_fixture():
    doc, med, body, html = canon_fixture()
    evidence = doc['evidence']
    manufacturer = evidence['visual_identity']['fields']['manufacturer']
    grls_role = 'Выпускающий контроль качества'
    fragment = grls_role + ',' + manufacturer['raw'] + ', Россия'
    evidence['current_grls_registration']['production_stages'] = fragment
    evidence['current_grls_registration_sha256'] = canonical_hash(evidence['current_grls_registration'])
    evidence['grls_production_fragment'] = fragment
    manufacturer['raw_role'] = 'Производство готовой лекарственной формы'
    evidence['manufacturer_proof_mode'] = PHYSICAL_FINISHED_STAGE_MODE
    evidence['physical_pdf_finished_stage'] = {
        'original_sha256': doc['original_sha256'], 'page_count': doc['page_count'], 'page_indices': [1],
        'grls_role_raw': grls_role, 'grls_production_fragment': fragment,
        'pdf_manufacturer_raw': manufacturer['raw'], 'pdf_role_raw': manufacturer['raw_role'],
        'pdf_producer_block_raw': 'Производитель\n' + manufacturer['raw'] + ', Российская Федерация\n'
                                  + manufacturer['raw_role'] + '\nМосковская область, улица Заводская, корпус 16',
    }
    return doc, med, body, html


class CanonPhysicalFinishedStageTests(unittest.TestCase):
    def test_explicit_physical_stage_keeps_actual_grls_qa_role_separate_and_is_idempotent(self):
        doc, med, _, html = physical_stage_fixture()
        result = validate_original_document(doc)
        self.assertEqual(result, validate_original_document(result))
        self.assertEqual(result['evidence']['current_grls_registration'], doc['evidence']['current_grls_registration'])
        self.assertEqual(result['evidence']['physical_pdf_finished_stage']['grls_role_raw'], 'Выпускающий контроль качества')
        self.assertEqual(result['evidence']['visual_identity']['fields']['manufacturer']['raw_role'],
                         'Производство готовой лекарственной формы')
        self.assertEqual(match_original_to_medication(result, med)['covered_variants'], 1)
        self.assertNotIn('sections', result)
        validate_product_html(result, html)

    def test_mode_is_explicit_canon_only_unknown_missing_or_unnecessary_modes_fail(self):
        for mode in ['missing-mode', 'missing-proof', 'unknown', 'unnecessary', 'non-canon', 'none-proof']:
            doc = physical_stage_fixture()[0]
            evidence = doc['evidence']
            if mode == 'missing-mode': del evidence['manufacturer_proof_mode']
            if mode == 'missing-proof': del evidence['physical_pdf_finished_stage']
            if mode == 'unknown': evidence['manufacturer_proof_mode'] = {'invented': True}
            if mode == 'none-proof': evidence['manufacturer_proof_mode'] = None
            if mode == 'unnecessary':
                fragment = 'Производитель (готовой ЛФ),' + doc['identity']['manufacturers'][0] + ', Россия'
                evidence['current_grls_registration']['production_stages'] = fragment
                evidence['grls_production_fragment'] = fragment
                evidence['current_grls_registration_sha256'] = canonical_hash(evidence['current_grls_registration'])
            if mode == 'non-canon':
                legacy = manufacturer_fixture()[0]
                doc['source'] = legacy['source']
                evidence['product_page'] = legacy['evidence']['product_page']
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_original_document(doc)

    def test_any_explicit_grls_finished_manufacturer_blocks_physical_fallback(self):
        for company in ['Другая производственная компания', physical_stage_fixture()[0]['identity']['manufacturers'][0]]:
            doc = physical_stage_fixture()[0]
            grls = doc['evidence']['current_grls_registration']
            grls['production_stages'] += '\nПроизводитель (готовой ЛФ),' + company + ', Россия'
            doc['evidence']['current_grls_registration_sha256'] = canonical_hash(grls)
            with self.subTest(company=company), self.assertRaisesRegex(ValueError, 'unnecessary|conflicting'):
                validate_original_document(doc)

    def test_holder_alone_or_absent_literal_production_fragment_is_not_a_grls_company_proof(self):
        for mode in ['holder-role', 'holder-only', 'changed-fragment', 'changed-grls-role']:
            doc = physical_stage_fixture()[0]
            evidence = doc['evidence']
            grls = evidence['current_grls_registration']
            if mode == 'holder-role':
                fragment = 'Держатель регистрационного удостоверения,' + doc['identity']['manufacturers'][0] + ', Россия'
                grls['production_stages'] = evidence['grls_production_fragment'] = fragment
                evidence['physical_pdf_finished_stage'].update(grls_role_raw='Держатель регистрационного удостоверения',
                                                              grls_production_fragment=fragment)
            if mode == 'holder-only': grls['production_stages'] = ''; grls['holder'] = doc['identity']['manufacturers'][0]
            if mode == 'changed-fragment': evidence['physical_pdf_finished_stage']['grls_production_fragment'] += ' different'
            if mode == 'changed-grls-role': evidence['physical_pdf_finished_stage']['grls_role_raw'] = 'Производитель'
            evidence['current_grls_registration_sha256'] = canonical_hash(grls)
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_original_document(doc)

    def test_qa_packaging_and_one_word_producer_are_not_physical_finished_stage(self):
        for role in ['Производитель', 'Выпускающий контроль качества', 'Первичная упаковка',
                     'Производство активной фармацевтической субстанции', 'Держатель регистрационного удостоверения']:
            doc = physical_stage_fixture()[0]
            proof = doc['evidence']['physical_pdf_finished_stage']
            proof['pdf_producer_block_raw'] = proof['pdf_producer_block_raw'].replace(proof['pdf_role_raw'], role)
            proof['pdf_role_raw'] = doc['evidence']['visual_identity']['fields']['manufacturer']['raw_role'] = role
            with self.subTest(role=role), self.assertRaises(ValueError): validate_original_document(doc)

    def test_role_cannot_be_borrowed_from_another_block_company_or_disconnected_page(self):
        for mode in ['other-company', 'other-prefix', 'company-after-role', 'intervening-company',
                     'qa-block', 'packing-block', 'role-absent', 'different-field-role', 'different-proof-company']:
            doc = physical_stage_fixture()[0]
            proof = doc['evidence']['physical_pdf_finished_stage']
            company, role, block = proof['pdf_manufacturer_raw'], proof['pdf_role_raw'], proof['pdf_producer_block_raw']
            if mode == 'other-company': block = block.replace(company, 'ООО Другая компания')
            if mode == 'other-prefix': block = block.replace('Производитель\n', 'Держатель\n')
            if mode == 'company-after-role': block = 'Производитель\n' + role + '\n' + company
            if mode == 'intervening-company': block = block.replace(role, 'ООО Другая компания\n' + role)
            if mode == 'qa-block': block += '\nВыпускающий контроль качества, другой адрес'
            if mode == 'packing-block': block += '\nПервичная упаковка, другой адрес'
            if mode == 'role-absent': block = block.replace(role, 'Стадия не указана')
            if mode == 'different-field-role': doc['evidence']['visual_identity']['fields']['manufacturer']['raw_role'] = 'Производитель'
            if mode == 'different-proof-company': proof['pdf_manufacturer_raw'] = 'Другая компания'
            proof['pdf_producer_block_raw'] = block
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_original_document(doc)

    def test_original_sha_page_count_and_exact_physical_field_pages_are_required(self):
        for field, value in [('original_sha256', 'a' * 64), ('page_count', 2), ('page_count', True),
                             ('page_indices', []), ('page_indices', [True]), ('page_indices', [0]),
                             ('page_indices', [1, 1]), ('page_indices', [2])]:
            doc = physical_stage_fixture()[0]
            doc['evidence']['physical_pdf_finished_stage'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): validate_original_document(doc)
        doc = physical_stage_fixture()[0]
        doc['page_count'] = doc['evidence']['visual_identity']['page_count'] = 2
        doc['evidence']['physical_pdf_finished_stage'].update(page_count=2, page_indices=[2])
        with self.assertRaises(ValueError): validate_original_document(doc)


class CanonIdentityTests(unittest.TestCase):
    def test_canon_uses_explicit_profile_and_same_exact_variant_matcher(self):
        doc, med, _, html = canon_fixture()
        result = validate_original_document(doc)
        self.assertEqual(result, validate_original_document(result))
        self.assertEqual(result['source']['provider'], 'canon')
        self.assertEqual(result['completeness'], {'original_pdf_confirmed': True, 'inline_text_verified': False})
        self.assertNotIn('sections', result)
        self.assertIsNone(result['revision_date'])
        validate_product_html(result, html)
        self.assertEqual(match_original_to_medication(result, med)['covered_variants'], 1)
        for field, value in [('name', 'Другой препарат'), ('dosage', '250 мг'), ('manufacturer', 'Другая компания')]:
            with self.subTest(field=field):
                self.assertFalse(match_original_to_medication(result, {**med, field: value})['matched'])

    def test_legacy_renewal_and_eaeu_canonical_bytes_are_unchanged(self):
        # SHA of the complete sorted UTF-8 canonical JSON before adding Canon.
        self.assertEqual(canonical_hash(validate_original_document(manufacturer_fixture()[0])),
                         'c36756f5717cdb826f7eb63ada911bd6fe76497a6521e2ea990c34c5df9d7cda')
        self.assertEqual(canonical_hash(validate_original_document(fixture()[0])),
                         '150a545a1a2ee9dcff3f812d152e92ff9cafcc132c0207cfea1a861e6ad319da')

    def test_host_port_static_namespace_and_raw_href_traversal_fail_closed(self):
        for url in ['http://www.canonpharma.ru/upload/original.pdf',
                    'https://cdn.canonpharma.ru/upload/original.pdf',
                    'https://www.canonpharma.ru.evil.test/upload/original.pdf',
                    'https://renewal.ru/upload/original.pdf',
                    'https://www.canonpharma.ru:444/upload/original.pdf',
                    'https://user:pass@www.canonpharma.ru/upload/original.pdf',
                    'https://www.canonpharma.ru/upload/original.pdf?token=x',
                    'https://www.canonpharma.ru/upload/original.pdf#fragment',
                    'https://www.canonpharma.ru/private/original.pdf',
                    'https://www.canonpharma.ru/upload/../original.pdf',
                    'https://www.canonpharma.ru/upload/%2e%2e/original.pdf',
                    'https://www.canonpharma.ru/upload/%252e%252e/original.pdf',
                    'https://www.canonpharma.ru/upload/%25252525252e%25252525252e/original.pdf',
                    'https://www.canonpharma.ru/upload/fixture%2foriginal.pdf',
                    'https://www.canonpharma.ru/upload/original.doc',
                    'https://www.canonpharma.ru/upload/original\n.pdf']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                canon_pdf_url(url)
        for url in ['https://canonpharma.ru/upload/original.pdf', 'https://www.canonpharma.ru:443/upload/original.pdf']:
            self.assertEqual(canon_pdf_url(url), url)
        for href in ['/upload/iblock/../synthetic/original.pdf', '/upload/%252e%252e/original.pdf',
                     '//www.canonpharma.ru/upload/iblock/synthetic/original.pdf']:
            doc = canon_fixture()[0]
            doc['evidence']['product_page']['actual_href'] = href
            with self.subTest(href=href), self.assertRaises(ValueError):
                validate_original_document(doc)

    def test_wrong_product_namespace_provider_host_and_undeclared_link_label_reject(self):
        for mode in ['products-path', 'foreign-product', 'foreign-pdf', 'unknown-provider', 'missing-label']:
            doc = canon_fixture()[0]
            product = doc['evidence']['product_page']
            if mode == 'products-path':
                doc['source']['url'] = product['url'] = 'https://www.canonpharma.ru/products/synthetic/'
            if mode == 'foreign-product':
                doc['source']['url'] = product['url'] = 'https://renewal.ru/catalog/synthetic/'
            if mode == 'foreign-pdf':
                doc['source']['pdf_url'] = product['pdf_url'] = 'https://cdn.canonpharma.ru/upload/original.pdf'
            if mode == 'unknown-provider': doc['source']['provider'] = 'canon-group'
            if mode == 'missing-label': del product['actual_label']
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_original_document(doc)

    def test_current_grls_and_every_physical_identity_field_remain_mandatory(self):
        for mode in ['old-ru', 'dose', 'form', 'name', 'manufacturer', 'holder', 'packaging', 'no-every-page',
                     'wrong-sha', 'no-version-review', 'version-conflict', 'draft', 'unknown-page']:
            doc = canon_fixture()[0]
            evidence = doc['evidence']
            visual = evidence['visual_identity']
            if mode == 'old-ru': visual['fields']['registration_number']['raw'] = 'ЛП-000099'
            if mode == 'dose': visual['fields']['dosage']['raw'] = '250 мг'
            if mode == 'form': visual['fields']['form']['raw'] = 'капсулы'
            if mode == 'name': visual['fields']['trade_name']['raw'] = 'Другой препарат'
            if mode == 'manufacturer': visual['fields']['manufacturer']['raw'] = 'Другая компания'
            if mode == 'holder': visual['fields']['manufacturer']['raw_role'] = 'Держатель регистрационного удостоверения'
            if mode == 'packaging':
                fragment = 'Упаковщик,' + doc['identity']['manufacturers'][0] + ', Россия'
                evidence['current_grls_registration']['production_stages'] = fragment
                evidence['grls_production_fragment'] = fragment
                evidence['current_grls_registration_sha256'] = canonical_hash(evidence['current_grls_registration'])
            if mode == 'no-every-page': visual['all_pages_visually_reviewed'] = False
            if mode == 'wrong-sha': visual['original_sha256'] = 'a' * 64
            if mode == 'no-version-review': visual['version_review'] = ''
            if mode == 'version-conflict': visual['version_conflict'] = True
            if mode == 'draft': doc['verification']['status'] = 'draft'
            if mode == 'unknown-page': visual['fields']['dosage']['page_indices'] = [2]
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_original_document(doc)

    def test_renewal_legal_exception_cannot_authorize_canon_or_another_company(self):
        doc = canon_fixture()[0]
        company = 'АО "Производственная фармацевтическая компания Обновление"'
        raw = 'Акционерное общество «Производственная фармацевтическая компания Обновление»'
        fragment = 'Производитель (готовой ЛФ),' + company + ' (АО "ПФК Обновление"), Россия'
        evidence = doc['evidence']
        doc['identity']['manufacturers'] = ['АО ПФК ОБНОВЛЕНИЕ']
        evidence['current_grls_registration']['production_stages'] = fragment
        evidence['current_grls_registration_sha256'] = canonical_hash(evidence['current_grls_registration'])
        evidence['grls_production_fragment'] = fragment
        evidence['visual_identity']['fields']['manufacturer']['raw'] = raw
        evidence['manufacturer_legal_form_equivalence'] = {'rule': 'renewal_ao_full_name_v1',
                                                         'pdf_literal': raw, 'grls_literal': company}
        with self.assertRaises(ValueError):
            validate_original_document(doc)

    def test_project_path_href_and_label_cannot_be_overridden_by_visual_final_claims(self):
        for field in ['pdf-path', 'href', 'label']:
            for marker in ['_PrOjEcT_final_', '_proekt_stamp_', 'проект', 'DRAFT', '%70roject']:
                doc = canon_fixture()[0]
                product = doc['evidence']['product_page']
                if field in ['pdf-path', 'href']:
                    href = '/upload/iblock/synthetic/' + marker + 'original.pdf'
                    product['actual_href'] = href
                    doc['source']['pdf_url'] = product['pdf_url'] = 'https://www.canonpharma.ru' + href
                else:
                    product['actual_label'] += ' ' + marker
                self.assertTrue(doc['evidence']['visual_identity']['not_unapproved_project'])
                with self.subTest(field=field, marker=marker), self.assertRaisesRegex(ValueError, 'quarantine'):
                    validate_original_document(doc)


class CanonHtmlAndBinaryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.doc, self.med, self.body, self.html = canon_fixture()

    def test_actual_single_href_label_and_html_hash_are_rechecked_at_apply(self):
        path = write_archive(self.folder, self.doc, self.body, self.html)
        doc = validate_original_document(self.doc)
        validate_archive(doc, path)
        html_path = self.folder / (doc['evidence']['product_page']['html_sha256'] + '.html')
        html_path.write_bytes(b'changed HTML')
        with self.assertRaises(ValueError): validate_archive(doc, path)
        html_path.unlink()
        with self.assertRaises(ValueError): validate_archive(doc, path)

    def test_other_pdf_even_patient_healthcare_pair_footer_or_cdn_is_ambiguous(self):
        for addition in [b'<a href="/upload/second.pdf">Download PDF</a>',
                         b'<a href="/upload/unclosed.pdf">',
                         '<a href="/upload/healthcare.pdf">Скачать информацию для работника здравоохранения</a>'.encode(),
                         '<a href="/upload/alsem.areas/ad4/privacy.pdf">Правила пользования сайтом</a>'.encode(),
                         b'<a href="https://cdn.canonpharma.ru/upload/original.pdf">Instruction</a>',
                         b'<a href="https://foreign.test/other.pdf">Download</a>']:
            html = self.html + addition
            with self.subTest(addition=addition), self.assertRaises(ValueError):
                validate_product_html(with_html(self.doc, html), html)

    def test_unknown_or_mismatched_href_label_and_project_label_in_actual_html_reject(self):
        for html in [self.html.replace(b'/upload/iblock/synthetic/original.pdf', b'/upload/other.pdf'),
                     self.html.replace('Скачать информацию для пациента'.encode(), b'PROJECT_final'),
                     self.html.replace('Скачать информацию для пациента'.encode(), b'Different label'),
                     b'<base href="https://evil.test/">' + self.html,
                     self.html + b'<base href="https://www.canonpharma.ru/"><base href="https://www.canonpharma.ru/">']:
            with self.subTest(html=html), self.assertRaises(ValueError):
                validate_product_html(with_html(self.doc, html), html)

    def test_actual_first_physical_project_page_fails_despite_clean_filename_and_manual_claims(self):
        body = project_pdf_bytes()
        digest = hashlib.sha256(body).hexdigest()
        doc = copy.deepcopy(self.doc)
        doc.update(original_sha256=digest, original_bytes=len(body), version='reviewed-SHA-' + digest)
        doc['evidence']['visual_identity'].update(original_sha256=digest, version=doc['version'])
        validate_original_document(doc)
        path = write_archive(self.folder, doc, body, self.html)
        with self.assertRaisesRegex(ValueError, 'physical first page.*project/draft'):
            validate_archive(doc, path)

    def test_missing_or_nonboolean_physical_project_check_never_passes_canon(self):
        path = write_archive(self.folder, self.doc, self.body, self.html)
        result = {key: self.doc[key] for key in ['original_sha256', 'original_bytes', 'page_count']}
        result.update(all_pages_resolved=True, encrypted=False)
        for fields in [{}, {'header_has_project_marker': None}, {'header_has_project_marker': 0}]:
            child = Mock(returncode=0)
            child.poll.return_value = 0
            child.communicate.return_value = (json.dumps({**result, **fields}).encode(), None)
            with self.subTest(fields=fields), patch('scripts.import_medication_originals.subprocess.Popen', return_value=child):
                with self.assertRaisesRegex(ValueError, 'physical first page.*project/draft'):
                    validate_archive(self.doc, path)


class CanonDeliveryTests(unittest.TestCase):
    def test_direct_tls_fixed_host_no_redirect_and_whole_hash_cache(self):
        doc, _, body, _ = canon_fixture()
        session = Session([Reply(body)])
        clock = Clock()
        with tempfile.TemporaryDirectory() as folder:
            cache = OfficialPdfCache(folder, session_factory=lambda: session, clock=clock.now, sleep=clock.sleep)
            self.assertEqual(cache.get_bytes(doc), body)
            self.assertEqual(cache.get_bytes(doc), body)
        self.assertEqual(len(session.calls), 1)
        method, url, options = session.calls[0]
        self.assertEqual((method, url), ('GET', doc['source']['pdf_url']))
        self.assertTrue(options['verify'])
        self.assertFalse(options['allow_redirects'])
        self.assertFalse(session.trust_env)
        self.assertTrue(session.closed)

    def test_all_redirects_changed_hash_or_truncated_files_fail_without_cache(self):
        doc, _, body, _ = canon_fixture()
        for response in [Reply(b'', status=302), Reply(body.replace(b'q Q', b'q q')),
                         Reply(body, declared=len(body) + 1), Reply(body[:-15])]:
            response.headers['Location'] = 'https://cdn.canonpharma.ru/upload/other.pdf'
            session = Session([response])
            with self.subTest(status=response.status_code), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(OriginalUnavailable):
                    OfficialPdfCache(folder, session_factory=lambda: session).get_bytes(doc)
                self.assertEqual(len(session.calls), 1)
                self.assertEqual(list(Path(folder).glob('*.pdf')), [])

    def test_each_source_stop_is_persistent_and_independent_of_other_two_profiles(self):
        canon, _, body, _ = canon_fixture()
        renewal = manufacturer_fixture()[0]
        eaeu = fixture()[0]
        profiles = {'canon': (canon, '.source-stopped-canon'), 'renewal': (renewal, '.source-stopped-renewal'),
                    'eaeu': (eaeu, '.source-stopped')}
        for stopped_name, (stopped_doc, marker) in profiles.items():
            for allowed_name, (allowed_doc, _) in profiles.items():
                if stopped_name == allowed_name:
                    continue
                denied = Session([Reply(b'blocked', status=403)])
                allowed = Session(workflow(body) if allowed_name == 'eaeu' else [Reply(body)])
                sessions = [denied, allowed]
                clock = Clock()
                with self.subTest(stopped=stopped_name, allowed=allowed_name), tempfile.TemporaryDirectory() as folder:
                    cache = OfficialPdfCache(folder, session_factory=lambda: sessions.pop(0), clock=clock.now, sleep=clock.sleep)
                    with self.assertRaises(OriginalUnavailable): cache.get_bytes(stopped_doc)
                    self.assertTrue((Path(folder) / marker).is_file())
                    self.assertEqual(cache.get_bytes(allowed_doc), body)
                    # Force a fetch after a new cache instance to prove that the
                    # stopped source cannot be retried through in-memory state.
                    (Path(folder) / (allowed_doc['original_sha256'] + '.pdf')).unlink()
                    unused = Session([])
                    restarted = OfficialPdfCache(folder, session_factory=lambda: unused, clock=clock.now, sleep=clock.sleep)
                    with self.assertRaises(OriginalUnavailable): restarted.get_bytes(stopped_doc)
                    self.assertEqual(unused.calls, [])


if __name__ == '__main__':
    unittest.main()
