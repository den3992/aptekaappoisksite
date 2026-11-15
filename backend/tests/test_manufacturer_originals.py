"""Offline Renewal original identity, HTML provenance and fixed-host delivery."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api.instruction_original_delivery import OfficialPdfCache, OriginalUnavailable
from api.manufacturer_original_pdfs import renewal_pdf_url, validate_product_html, validate_manufacturer_archive
from api.medication_original_pdfs import MedicationOriginalService, canonical_hash, match_original_to_medication, validate_original_document
from scripts.import_medication_originals import OriginalCollections, validate_archive
from scripts.import_medication_instructions import apply_plan, build_plan, rollback_batch
from test_instruction_import import Collection
from test_instruction_originals import AsyncCollection, Clock, Reply, Session, fixture, workflow
from test_instruction_original_binary import project_pdf_bytes


def manufacturer_fixture():
    original, med, body = fixture()
    grls = copy.deepcopy(original['evidence']['current_grls_registration'])
    name = med['name']
    company = med['manufacturer']
    fragment = 'Производитель (готовой ЛФ),' + company + ', Россия'
    grls['production_stages'] = fragment
    page_url = 'https://www.renewal.ru/products/synthetic/'
    href = '/upload/fixture/original.pdf'
    pdf_url = 'https://www.renewal.ru' + href
    html = ('<h1>Синтетический препарат</h1><a href="' + href + '">Инструкция</a>').encode()
    html_sha = hashlib.sha256(html).hexdigest()
    fields = {key: {'raw': value, 'page_indices': [1]} for key, value in [
        ('registration_number', original['registration_numbers'][0]), ('trade_name', name),
        ('form', med['form']), ('dosage', med['dosage']), ('manufacturer', company)]}
    fields['manufacturer']['raw_role'] = 'Производитель'
    doc = {
        **{key: original[key] for key in ['title', 'content_format', 'document_type', 'registration_numbers',
            'original_sha256', 'original_bytes', 'page_count', 'identity', 'scopes']},
        'id': 'renewal-synthetic-original', 'version': 'reviewed-SHA-' + original['original_sha256'],
        'approved_at': None, 'revision_date': None, 'retrieved_at': '2026-01-01T00:00:00Z',
        'source': {'name': 'Официальный производитель: синтетический fixture', 'kind': 'official_manufacturer',
                   'provider': 'renewal', 'url': page_url, 'pdf_url': pdf_url},
        'verification': {'status': 'verified', 'method': 'manual_visual_manufacturer_original',
                         'verified_at': '2026-01-01T00:00:00Z', 'verified_by': 'synthetic fixture'},
        'evidence': {'product_page': {'url': page_url, 'html_sha256': html_sha, 'actual_href': href, 'pdf_url': pdf_url},
            'current_grls_registration': grls, 'current_grls_registration_sha256': canonical_hash(grls),
            'grls_production_fragment': fragment,
            'visual_identity': {'original_sha256': original['original_sha256'], 'page_count': 1,
                'all_pages_visually_reviewed': True, 'reviewer': 'synthetic fixture', 'verified_at': '2026-01-01T00:00:00Z',
                'document_type': original['document_type'], 'version': 'reviewed-SHA-' + original['original_sha256'],
                'revision_date': None, 'not_unapproved_project': True, 'version_conflict': False,
                'version_review': 'The exact archived official product page contains one instruction PDF; every physical source page was visually checked and no project marker or version conflict was found.',
                'fields': fields}},
    }
    doc['identity'] = {'trade_name': name, 'manufacturers': [company]}
    return doc, med, body, html


def write_archive(folder, doc, body, html):
    pdf = folder / 'original.pdf'
    pdf.write_bytes(body)
    (folder / (doc['evidence']['product_page']['html_sha256'] + '.html')).write_bytes(html)
    return pdf


class ManufacturerValidationTests(unittest.TestCase):
    def test_actual_project_pdf_blocks_renewal_after_real_retained_html_guard(self):
        doc, _, _, html = manufacturer_fixture()
        body = project_pdf_bytes()
        digest = hashlib.sha256(body).hexdigest()
        doc.update(original_sha256=digest, original_bytes=len(body), version='reviewed-SHA-' + digest)
        doc['evidence']['visual_identity'].update(original_sha256=digest, version=doc['version'])
        validate_original_document(doc)
        self.assertEqual(doc['source']['kind'], 'official_manufacturer')
        with tempfile.TemporaryDirectory() as directory:
            path = write_archive(Path(directory), doc, body, html)
            with patch('api.manufacturer_original_pdfs.validate_manufacturer_archive', wraps=validate_manufacturer_archive) as html_guard:
                with self.assertRaisesRegex(ValueError, 'physical first page.*project/draft'):
                    validate_archive(doc, path)
                html_guard.assert_called_once_with(doc, path)

    def test_separate_profile_is_idempotent_and_matches_only_exact_variants(self):
        doc, med, _, html = manufacturer_fixture()
        result = validate_original_document(doc)
        self.assertEqual(result, validate_original_document(result))
        self.assertEqual(result['source']['provider'], 'renewal')
        self.assertEqual(result['completeness'], {'original_pdf_confirmed': True, 'inline_text_verified': False})
        self.assertNotIn('sections', result)
        self.assertIsNone(result['revision_date'])
        self.assertEqual(match_original_to_medication(result, med)['covered_variants'], 1)
        validate_product_html(result, html)
        for key, value in [('name', 'Другой'), ('dosage', '250 мг'), ('manufacturer', 'Чужой')]:
            self.assertFalse(match_original_to_medication(result, {**med, key: value})['matched'])

    def test_wrong_ru_dose_manufacturer_and_physical_pages_fail_closed(self):
        for field, value in [('registration_number', 'ЛП-000099'), ('dosage', '250 мг'), ('form', 'капсулы'),
                             ('manufacturer', 'Чужой производитель'), ('trade_name', 'Другой препарат')]:
            doc, _, _, _ = manufacturer_fixture()
            doc['evidence']['visual_identity']['fields'][field]['raw'] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_original_document(doc)
        for pages in [[0], [2], [True], [1, 1], []]:
            doc, _, _, _ = manufacturer_fixture()
            doc['evidence']['visual_identity']['fields']['dosage']['page_indices'] = pages
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                validate_original_document(doc)

    def test_holder_packaging_stage_wrong_grls_and_version_review_are_not_identity(self):
        for mode in ['packaging', 'holder-role', 'wrong-grls-ru', 'wrong-grls-dose', 'inactive', 'project',
                     'version-conflict', 'draft', 'wrong-sha', 'no-whole-review', 'unknown-provider']:
            doc, _, _, _ = manufacturer_fixture()
            evidence, visual = doc['evidence'], doc['evidence']['visual_identity']
            if mode == 'packaging':
                evidence['current_grls_registration']['production_stages'] = 'Упаковщик,' + doc['identity']['manufacturers'][0] + ', Россия'
                evidence['grls_production_fragment'] = evidence['current_grls_registration']['production_stages']
            if mode == 'holder-role': visual['fields']['manufacturer']['raw_role'] = 'Держатель регистрационного удостоверения'
            if mode == 'wrong-grls-ru': evidence['current_grls_registration']['registration_number'] = 'ЛП-000099'
            if mode == 'wrong-grls-dose': evidence['current_grls_registration']['release_forms'] = 'таблетки, 250 мг, 20 шт.;'
            if mode == 'inactive': evidence['current_grls_registration']['source_status_book'] = 'Недействующий'
            if mode == 'project': visual['not_unapproved_project'] = False
            if mode == 'version-conflict': visual['version_conflict'] = True
            if mode == 'draft': doc['verification']['status'] = 'draft'
            if mode == 'wrong-sha': visual['original_sha256'] = 'b' * 64
            if mode == 'no-whole-review': visual['all_pages_visually_reviewed'] = False
            if mode == 'unknown-provider': doc['source']['provider'] = 'other'
            evidence['current_grls_registration_sha256'] = canonical_hash(evidence['current_grls_registration'])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_original_document(doc)

    def test_url_allowlist_rejects_other_hosts_ports_queries_and_upload_escape(self):
        for url in ['https://evil.test/upload/file.pdf', 'http://www.renewal.ru/upload/file.pdf',
                    'https://www.renewal.ru:444/upload/file.pdf', 'https://user:pass@www.renewal.ru/upload/file.pdf',
                    'https://www.renewal.ru/upload/file.pdf?token=x', 'https://www.renewal.ru/upload/../file.pdf',
                    'https://www.renewal.ru/upload/%2e%2e/file.pdf', 'https://www.renewal.ru/upload/%252e%252e/file.pdf',
                    'https://www.renewal.ru/private/file.pdf']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                renewal_pdf_url(url)

    def test_renewal_legal_form_rule_is_narrow_explicit_and_not_an_oao_pao_alias(self):
        doc, _, _, _ = manufacturer_fixture()
        company = 'АО "Производственная фармацевтическая компания Обновление"'
        raw = 'Акционерное общество «Производственная фармацевтическая компания Обновление»'
        fragment = 'Производитель (готовой ЛФ),' + company + ' (АО "ПФК Обновление"), Россия'
        doc['identity']['manufacturers'] = ['АО ПФК ОБНОВЛЕНИЕ']
        doc['evidence']['current_grls_registration']['production_stages'] = fragment
        doc['evidence']['current_grls_registration_sha256'] = canonical_hash(doc['evidence']['current_grls_registration'])
        doc['evidence']['grls_production_fragment'] = fragment
        doc['evidence']['visual_identity']['fields']['manufacturer']['raw'] = raw
        with self.assertRaises(ValueError):
            validate_original_document(doc)
        doc['evidence']['manufacturer_legal_form_equivalence'] = {'rule': 'renewal_ao_full_name_v1', 'pdf_literal': raw, 'grls_literal': company}
        validate_original_document(doc)
        for changed in [raw.replace('Акционерное', 'Публичное акционерное'), raw.replace('Обновление', 'Другая компания')]:
            bad = copy.deepcopy(doc)
            bad['evidence']['visual_identity']['fields']['manufacturer']['raw'] = changed
            with self.assertRaises(ValueError):
                validate_original_document(bad)
        for prefix in ['ОАО', 'ПАО']:
            bad = copy.deepcopy(doc)
            bad['identity']['manufacturers'] = [prefix + ' ПФК ОБНОВЛЕНИЕ']
            with self.assertRaises(ValueError):
                validate_original_document(bad)


class ManufacturerArchiveAndDeliveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.doc, self.med, self.body, self.html = manufacturer_fixture()

    def test_html_archive_and_actual_href_are_required_again_at_apply(self):
        pdf = write_archive(self.folder, self.doc, self.body, self.html)
        validate_archive(validate_original_document(self.doc), pdf)
        html_path = self.folder / (self.doc['evidence']['product_page']['html_sha256'] + '.html')
        html_path.write_bytes(b'changed HTML')
        with self.assertRaises(ValueError):
            validate_archive(validate_original_document(self.doc), pdf)
        html_path.unlink()
        with self.assertRaises(ValueError):
            validate_archive(validate_original_document(self.doc), pdf)

    def test_href_mismatch_or_multiple_instruction_versions_is_not_approved(self):
        for html in ['<a href="/upload/other.pdf">Инструкция</a>'.encode(),
                     self.html + '<a href="/upload/another.pdf">Инструкция</a>'.encode(),
                     self.html + b'<a href="/upload/other-opaque.pdf">Download PDF</a>',
                     self.html + b'<a href="https://foreign.test/upload/another.pdf">Instruction</a>',
                     self.html + b'<a href="/upload/alsem.areas/ad4/privacy.pdf">Different unclassified document</a>',
                     self.html.replace(b'/upload/fixture/original.pdf', b'https://evil.test/upload/fixture/original.pdf')]:
            doc = copy.deepcopy(self.doc)
            doc['evidence']['product_page']['html_sha256'] = hashlib.sha256(html).hexdigest()
            with self.assertRaises(ValueError):
                validate_product_html(doc, html)

    def test_only_reviewed_legal_footer_pdf_path_and_label_pairs_are_excluded(self):
        html = self.html + ('<a href="/upload/alsem.areas/ad4/privacy.pdf">Правила пользования сайтом</a>'
                            '<a href="/upload/alsem.areas/47c/privacy.pdf">Политика конфиденциальности</a>').encode()
        doc = copy.deepcopy(self.doc)
        doc['evidence']['product_page']['html_sha256'] = hashlib.sha256(html).hexdigest()
        validate_product_html(doc, html)

    def test_fixed_host_download_has_tls_no_redirect_and_verified_whole_bytes(self):
        session = Session([Reply(self.body)])
        clock = Clock()
        cache = OfficialPdfCache(self.folder / 'cache', session_factory=lambda: session, clock=clock.now, sleep=clock.sleep)
        self.assertEqual(cache.get_bytes(self.doc), self.body)
        self.assertEqual(cache.get_bytes(self.doc), self.body)
        self.assertEqual(len(session.calls), 1)
        method, url, options = session.calls[0]
        self.assertEqual((method, url), ('GET', self.doc['source']['pdf_url']))
        self.assertTrue(options['verify'])
        self.assertFalse(options['allow_redirects'])
        self.assertFalse(session.trust_env)
        self.assertTrue(session.closed)

    def test_foreign_redirect_and_changed_hash_never_return_or_cache_bytes(self):
        for response in [Reply(b'', status=302), Reply(self.body.replace(b'q Q', b'q q'))]:
            response.headers['Location'] = 'https://evil.test/original.pdf'
            with tempfile.TemporaryDirectory() as directory:
                session = Session([response])
                with self.assertRaises(OriginalUnavailable):
                    OfficialPdfCache(directory, session_factory=lambda: session).get_bytes(self.doc)
                self.assertEqual(len(session.calls), 1)
                self.assertEqual(list(Path(directory).glob('*.pdf')), [])

    def test_renewal_denial_does_not_stop_independent_eaeu_source(self):
        eaeu, _, body = fixture()
        sessions = [Session([Reply(b'blocked', status=403)]), Session(workflow(body))]
        clock = Clock()
        cache = OfficialPdfCache(self.folder / 'cache', session_factory=lambda: sessions.pop(0), clock=clock.now, sleep=clock.sleep)
        with self.assertRaises(OriginalUnavailable):
            cache.get_bytes(self.doc)
        self.assertTrue((self.folder / 'cache/.source-stopped-renewal').exists())
        self.assertFalse((self.folder / 'cache/.source-stopped').exists())
        self.assertEqual(cache.get_bytes(eaeu), body)

    def test_eaeu_stop_does_not_stop_manufacturer_and_renewal_stop_blocks_its_next_fetch(self):
        directory = self.folder / 'cache'
        directory.mkdir()
        (directory / '.source-stopped').write_text('EAEU stopped')
        session = Session([Reply(self.body)])
        cache = OfficialPdfCache(directory, session_factory=lambda: session)
        self.assertEqual(cache.get_bytes(self.doc), self.body)
        (directory / (self.doc['original_sha256'] + '.pdf')).unlink()
        (directory / '.source-stopped-renewal').write_text('Renewal stopped')
        with self.assertRaises(OriginalUnavailable):
            cache.get_bytes(self.doc)
        self.assertEqual(len(session.calls), 1)

    def test_import_rollback_and_missing_html_touch_only_original_collections(self):
        pdf = write_archive(self.folder, self.doc, self.body, self.html)
        database = SimpleNamespace(medications=Collection([self.med], read_only=True), prices=Collection(read_only=True),
            instruction_documents=Collection(read_only=True), medication_instruction_bindings=Collection(read_only=True),
            instruction_original_documents=Collection(), medication_original_bindings=Collection())
        plan = build_plan([{'document': self.doc, 'original_file': str(pdf)}], [self.med], validator=validate_original_document,
                          matcher=match_original_to_medication, archive_validator=validate_archive)
        html_path = self.folder / (self.doc['evidence']['product_page']['html_sha256'] + '.html')
        html_path.unlink()
        with self.assertRaises(ValueError):
            apply_plan(OriginalCollections(database), plan, validator=validate_original_document,
                       matcher=match_original_to_medication, archive_validator=validate_archive)
        self.assertEqual(database.instruction_original_documents.rows, [])
        html_path.write_bytes(self.html)
        applied = apply_plan(OriginalCollections(database), plan, validator=validate_original_document,
                             matcher=match_original_to_medication, archive_validator=validate_archive)
        self.assertEqual(applied['added_bindings'], 1)
        self.assertEqual(rollback_batch(OriginalCollections(database), applied['batch_id'])['disabled_bindings'], 1)
        self.assertFalse(database.medications.writes or database.prices.writes or database.instruction_documents.writes)


class ManufacturerPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_whole_pdf_has_separate_coverage_and_no_raw_proof_or_inline_sections(self):
        doc, med, _, _ = manufacturer_fixture()
        match = match_original_to_medication(doc, med)
        row = {'document_id': doc['id'], 'status': 'verified', 'active': True,
               'medicine_slug': med['slug'], 'identity_fingerprint': match['identity_fingerprint'],
               'variant_bindings': match['bindings']}
        db = SimpleNamespace(instruction_original_documents=AsyncCollection([doc]), medication_original_bindings=AsyncCollection([row]))
        service = MedicationOriginalService(db)
        med['instructions'] = []
        med['instruction_coverage'] = {'covered_variants': 0, 'fully_covered': False}
        result = await service.attach(copy.deepcopy(med))
        public = result['instruction_originals'][0]
        self.assertEqual(public['source']['url'], doc['source']['url'])
        self.assertIsNone(public['revision_date'])
        self.assertEqual(result['instruction_original_coverage']['covered_variants'], 1)
        self.assertEqual(result['instruction_coverage']['covered_variants'], 0)
        self.assertNotIn('evidence', public)
        self.assertNotIn('sections', public)
        changed = copy.deepcopy(med)
        changed['dosage'] = '250 мг'
        self.assertEqual((await service.attach(changed))['instruction_originals'], [])


if __name__ == '__main__':
    unittest.main()
