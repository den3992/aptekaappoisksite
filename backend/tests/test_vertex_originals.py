"""Unit metadata is never independent data approval or a published wrapper."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from api.instruction_original_delivery import OfficialPdfCache, OriginalUnavailable
from api.manufacturer_original_pdfs import manufacturer_pdf_url, validate_manufacturer_archive, validate_product_html
from api.medication_original_pdfs import canonical_hash, match_original_to_medication, validate_original_document
from api.medication_instructions import _ru
from api.vertex_original_pdfs import (MODE, ORIGINAL_SHA256, ORIGINAL_BYTES, PAGE_COUNT,
    CURRENT_RU, CURRENT_GTIN, PRODUCT_URL, PDF_URL, HREF, INNER_TEXT, TITLE, ROLE,
    COMPANY, PDF_ADDRESS, PRODUCER_BLOCK, REPRESENTATIVE_BLOCK, REPORT_STAMP)
from test_canon_originals import canon_fixture, physical_stage_fixture
from test_manufacturer_originals import manufacturer_fixture
from test_solopharm_originals import solopharm_fixture
from test_instruction_originals import Clock, Reply, Session, fixture


def vertex_fixture():
    facts = json.loads((Path(__file__).parent / 'fixtures/vertex_ginkgo_source_facts.json').read_text())
    html = ('<a title="' + TITLE + '" href="' + HREF + '">' + INNER_TEXT + '</a>').encode()
    grls = facts['current_grls_registration']
    fields = copy.deepcopy(facts['literal_fields'])
    fields['manufacturer']['physical_address_raw'] = PDF_ADDRESS
    fields = {key: fields[key] for key in ['registration_number', 'trade_name', 'form', 'dosage', 'manufacturer']}
    version = 'sha256:' + ORIGINAL_SHA256
    blocks = {}
    for key, raw in [('producer', facts['physical_producer_block']), ('publisher', facts['physical_representative_block'])]:
        blocks[key] = {'raw_block': raw, 'company_raw': COMPANY, 'address_raw': PDF_ADDRESS,
                       'page_indices': [8], 'original_sha256': ORIGINAL_SHA256}
    proof = {'mode': MODE, 'original_sha256': ORIGINAL_SHA256, 'page_count': PAGE_COUNT, **blocks,
        'allpage_project_review': {'original_sha256': ORIGINAL_SHA256, 'page_indices': list(range(1, 9)),
            'all_pages_visually_checked': True, 'project_marker_found': False},
        'source_version_context': {'report_stamp_raw': REPORT_STAMP,
            'grls_normative_documentation_raw': grls['normative_documentation'],
            'leaflet_revision_heading_raw': 'Листок-вкладыш пересмотрен', 'leaflet_revision_value': None,
            'no_newest_version_assertion': True, 'competing_retained_version_found': False}}
    timestamp = '2026-11-15T09:00:00+00:00'
    doc = {'id': 'vertex-ginkgo-unit-metadata-not-publication', 'title': 'Unit metadata only',
        'content_format': 'official_original_pdf', 'document_type': 'patient_leaflet',
        'registration_numbers': [CURRENT_RU], 'version': version, 'approved_at': None, 'revision_date': None,
        'retrieved_at': timestamp, 'original_sha256': ORIGINAL_SHA256, 'original_bytes': ORIGINAL_BYTES,
        'page_count': PAGE_COUNT, 'source': {'kind': 'official_manufacturer', 'provider': 'vertex',
            'name': 'Vertex unit source facts only', 'url': PRODUCT_URL, 'pdf_url': PDF_URL},
        'identity': {'trade_name': 'Гинкго Билоба', 'manufacturers': ['АО ВЕРТЕКС']},
        'scopes': [{'gtin': CURRENT_GTIN, 'ru_number': _ru(CURRENT_RU), 'form': 'капсулы', 'dosage': '80 мг'}],
        'verification': {'status': 'verified', 'method': 'manual_visual_manufacturer_original',
            'verified_at': timestamp, 'verified_by': 'unittest metadata, never publication approval'},
        'evidence': {'current_grls_registration': grls, 'current_grls_registration_sha256': canonical_hash(grls),
            'grls_production_fragment': facts['grls_production_fragment'],
            'product_page': {'url': PRODUCT_URL, 'pdf_url': PDF_URL, 'actual_href': HREF,
                'actual_inner_text': INNER_TEXT, 'actual_title': TITLE, 'html_sha256': hashlib.sha256(html).hexdigest()},
            'visual_identity': {'original_sha256': ORIGINAL_SHA256, 'page_count': PAGE_COUNT,
                'all_pages_visually_reviewed': True, 'document_type': 'patient_leaflet', 'version': version,
                'not_unapproved_project': True, 'version_conflict': False, 'reviewer': 'unittest metadata only',
                'verified_at': timestamp, 'revision_date': None, 'fields': fields,
                'version_review': 'Unit fixture retains whole source facts and unknown revision; this test is no independent clinical or publication approval.'},
            'vertex_physical_proof': proof},
        'completeness': {'original_pdf_confirmed': True, 'inline_text_verified': False}}
    selected = facts['selected_scope']
    med = {'slug': selected['slug'], 'name': selected['trade_name'], 'manufacturer': selected['manufacturer'],
        'form': selected['form'], 'dosage': selected['dosage'],
        'variants': copy.deepcopy(selected['excluded_old_RU_variants'] + [selected['selected_current_RU_variant']])}
    return doc, med, html


def with_html(doc, body):
    doc = copy.deepcopy(doc)
    doc['evidence']['product_page']['html_sha256'] = hashlib.sha256(body).hexdigest()
    return doc


class VertexIdentityTests(unittest.TestCase):
    def test_patient_leaflet_idempotent_only_current_gtin_one_of_two(self):
        doc, med, html = vertex_fixture()
        result = validate_original_document(doc)
        self.assertEqual(result, doc)
        self.assertEqual(result, validate_original_document(result))
        validate_product_html(result, html)
        match = match_original_to_medication(result, med)
        self.assertEqual(match['covered_variants'], 1)
        self.assertEqual(match['total_variants'], 2)
        self.assertFalse(match['fully_covered'])
        self.assertEqual(match['bindings'][0]['gtin'], CURRENT_GTIN)
        self.assertEqual(result['document_type'], 'patient_leaflet')
        self.assertIsNone(result['approved_at'])
        self.assertIsNone(result['revision_date'])
        self.assertFalse(result['completeness']['inline_text_verified'])

    def test_old_and_new_unreviewed_packaging_cannot_inherit_current_proof(self):
        doc, med, _ = vertex_fixture()
        old = copy.deepcopy(med); old['variants'] = old['variants'][:1]
        self.assertFalse(match_original_to_medication(doc, old)['matched'])
        new = copy.deepcopy(med); new['variants'] = new['variants'][1:]
        new['variants'][0]['gtin'] = '04670033324419'
        self.assertFalse(match_original_to_medication(doc, new)['matched'])
        for key, value in [('name', 'Гинкго'), ('form', 'таблетки'), ('dosage', '40 мг'), ('manufacturer', 'ООО ВЕРТЕКС')]:
            changed = copy.deepcopy(med); changed[key] = value
            with self.subTest(key=key):self.assertFalse(match_original_to_medication(doc, changed)['matched'])

    def test_no_new_gtin_ru_form_dose_or_name_scope_exceptions(self):
        for key, value in [('gtin', None), ('gtin', '04607003247119'), ('gtin', '04670033324419'),
                           ('ru_number', 'ЛП-002183'), ('form', 'таблетки'), ('dosage', '40 мг'),
                           ('dosage', '80.0 мг'), ('dosage', '0,08 г')]:
            doc = vertex_fixture()[0];doc['scopes'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):validate_original_document(doc)
        doc = vertex_fixture()[0];doc['scopes'].append(copy.deepcopy(doc['scopes'][0]))
        with self.assertRaises(ValueError):validate_original_document(doc)
        doc = vertex_fixture()[0];doc['identity']['trade_name'] = 'Гинкго-Билоба'
        with self.assertRaises(ValueError):validate_original_document(doc)

    def test_only_unchanged_eightpage_patient_leaflet_binary_is_in_scope(self):
        for key, value in [('document_type', 'medical_instruction'), ('original_sha256', 'a' * 64),
                           ('original_bytes', ORIGINAL_BYTES + 1), ('page_count', 7)]:
            doc = vertex_fixture()[0];doc[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):validate_original_document(doc)

    def test_exact_combined_role_and_explicit_mode_are_required(self):
        for mode in ['missing-proof', 'missing-mode', 'other-mode', 'holder-only', 'manufacturer-only', 'QA', 'packager', 'canon-fallback']:
            doc = vertex_fixture()[0];e = doc['evidence'];p = e['vertex_physical_proof']
            if mode == 'missing-proof':del e['vertex_physical_proof']
            if mode == 'missing-mode':del p['mode']
            if mode == 'other-mode':p['mode'] = 'generic_combined_holder'
            if mode == 'holder-only':e['visual_identity']['fields']['manufacturer']['raw_role'] = 'Держатель регистрационного удостоверения'
            if mode == 'manufacturer-only':e['visual_identity']['fields']['manufacturer']['raw_role'] = 'Производитель'
            if mode == 'QA':e['visual_identity']['fields']['manufacturer']['raw_role'] = 'Выпускающий контроль качества'
            if mode == 'packager':e['visual_identity']['fields']['manufacturer']['raw_role'] = 'Упаковщик'
            if mode == 'canon-fallback':e['manufacturer_proof_mode'] = 'physical_pdf_finished_stage_v1'
            with self.subTest(mode=mode), self.assertRaises(ValueError):validate_original_document(doc)

    def test_other_providers_do_not_accept_vertex_proof_or_combined_role(self):
        proof = vertex_fixture()[0]['evidence']['vertex_physical_proof']
        for make in [manufacturer_fixture, canon_fixture, physical_stage_fixture, solopharm_fixture]:
            for borrowed in [True, False]:
                doc = make()[0]
                if borrowed:doc['evidence']['vertex_physical_proof'] = copy.deepcopy(proof)
                else:doc['evidence']['visual_identity']['fields']['manufacturer']['raw_role'] = ROLE
                with self.subTest(provider=make.__name__, borrowed=borrowed), self.assertRaises(ValueError):validate_original_document(doc)

    def test_current_grls_finished_role_company_and_literal_site_pair_stay_strict(self):
        for mode in ['holder', 'packager', 'QA', 'company', 'new-alias', 'different-holder', 'GRLS-site', 'PDF-site']:
            doc = vertex_fixture()[0];e = doc['evidence'];grls = e['current_grls_registration']
            if mode in ['holder', 'packager', 'QA']:
                replacement = {'holder': 'Держатель РУ', 'packager': 'Упаковщик', 'QA': 'Выпускающий контроль качества'}[mode]
                e['grls_production_fragment'] = e['grls_production_fragment'].replace('Производитель (готовой ЛФ)', replacement)
                grls['production_stages'] = e['grls_production_fragment']
            if mode == 'company':e['visual_identity']['fields']['manufacturer']['raw'] = 'ООО «ВЕРТЕКС»'
            if mode == 'new-alias':doc['identity']['manufacturers'].append('ООО ВЕРТЕКС')
            if mode == 'different-holder':grls['holder'] = 'Другая компания'
            if mode == 'GRLS-site':
                e['grls_production_fragment'] = e['grls_production_fragment'].replace('д.62', 'д.63')
                grls['production_stages'] = e['grls_production_fragment']
            if mode == 'PDF-site':e['visual_identity']['fields']['manufacturer']['physical_address_raw'] = PDF_ADDRESS.replace('62', '63')
            e['current_grls_registration_sha256'] = canonical_hash(grls)
            with self.subTest(mode=mode), self.assertRaises(ValueError):validate_original_document(doc)

    def test_two_actual_blocks_same_pdf_same_page_and_separate_website_context(self):
        for mode in ['missing-publisher', 'website-in-producer', 'copied-producer-as-publisher',
                     'publisher-other-SHA', 'producer-other-SHA', 'publisher-other-page', 'publisher-float-page',
                     'publisher-other-company', 'publisher-other-site', 'publisher-other-host']:
            doc = vertex_fixture()[0];p = doc['evidence']['vertex_physical_proof']
            if mode == 'missing-publisher':del p['publisher']
            if mode == 'website-in-producer':p['producer']['raw_block'] += '\nВеб-сайт: vertex.spb.ru'
            if mode == 'copied-producer-as-publisher':p['publisher']['raw_block'] = p['producer']['raw_block']
            if mode == 'publisher-other-SHA':p['publisher']['original_sha256'] = 'a' * 64
            if mode == 'producer-other-SHA':p['producer']['original_sha256'] = 'a' * 64
            if mode == 'publisher-other-page':p['publisher']['page_indices'] = [7]
            if mode == 'publisher-float-page':p['publisher']['page_indices'] = [8.0]
            if mode == 'publisher-other-company':p['publisher']['company_raw'] = 'ООО ВЕРТЕКС'
            if mode == 'publisher-other-site':p['publisher']['address_raw'] = PDF_ADDRESS.replace('62', '63')
            if mode == 'publisher-other-host':p['publisher']['raw_block'] = p['publisher']['raw_block'].replace('vertex.spb.ru', 'evil.test')
            with self.subTest(mode=mode), self.assertRaises(ValueError):validate_original_document(doc)

    def test_allpage_project_review_cannot_be_replaced_by_binary_firstpage_flag(self):
        for mode in ['only-first', 'missing-last', 'project-found', 'not-viewed', 'borrowed-SHA', 'bool-page', 'missing-generic-visual-review']:
            doc = vertex_fixture()[0];p = doc['evidence']['vertex_physical_proof']['allpage_project_review']
            if mode == 'only-first':p['page_indices'] = [1]
            if mode == 'missing-last':p['page_indices'] = list(range(1, 8))
            if mode == 'project-found':p['project_marker_found'] = True
            if mode == 'not-viewed':p['all_pages_visually_checked'] = False
            if mode == 'borrowed-SHA':p['original_sha256'] = 'a' * 64
            if mode == 'bool-page':p['page_indices'][0] = True
            if mode == 'missing-generic-visual-review':doc['evidence']['visual_identity']['all_pages_visually_reviewed'] = False
            with self.subTest(mode=mode), self.assertRaises(ValueError):validate_original_document(doc)

    def test_stamp_normative_context_and_unknown_dates_cannot_be_reinterpreted(self):
        for mode in ['revision', 'approval', 'newest-version', 'stamp', 'normative', 'missing-normative', 'revision-value', 'newest-claim', 'competing-version']:
            doc = vertex_fixture()[0];p = doc['evidence']['vertex_physical_proof']['source_version_context']
            if mode == 'revision':doc['revision_date'] = doc['evidence']['visual_identity']['revision_date'] = '2023-07-13'
            if mode == 'approval':doc['approved_at'] = '2023-07-13'
            if mode == 'newest-version':doc['version'] = doc['evidence']['visual_identity']['version'] = 'newest2026'
            if mode == 'stamp':p['report_stamp_raw'] = 'Утверждено2026'
            if mode == 'normative':p['grls_normative_documentation_raw'] = '2023'
            if mode == 'missing-normative':
                del doc['evidence']['current_grls_registration']['normative_documentation']
                doc['evidence']['current_grls_registration_sha256'] = canonical_hash(doc['evidence']['current_grls_registration'])
                p['grls_normative_documentation_raw'] = None
            if mode == 'revision-value':p['leaflet_revision_value'] = '2026'
            if mode == 'newest-claim':p['no_newest_version_assertion'] = False
            if mode == 'competing-version':p['competing_retained_version_found'] = True
            with self.subTest(mode=mode), self.assertRaises(ValueError):validate_original_document(doc)

    def test_existing_canonical_hashes_unchanged(self):
        for make, expected in [(canon_fixture, '7abfff9cbf78741c6123095f02f061f3d2476f7113cd19ff4639673cb85efade'),
            (physical_stage_fixture, '35b9342029c7a688aaf3a948e99813b5f561e262b47eb3b936d34fd46701d46e'),
            (manufacturer_fixture, 'c36756f5717cdb826f7eb63ada911bd6fe76497a6521e2ea990c34c5df9d7cda'),
            (solopharm_fixture, '498367ba290c812654ac92b2a6a0e73c523e3c25b2ff24a72bcdf87b12d7399f'),
            (fixture, '150a545a1a2ee9dcff3f812d152e92ff9cafcc132c0207cfea1a861e6ad319da')]:
            with self.subTest(provider=make.__name__):self.assertEqual(canonical_hash(validate_original_document(make()[0])), expected)


class VertexHTMLTests(unittest.TestCase):
    def test_exact_distinct_title_and_visible_text_cannot_be_inferred(self):
        doc, _, html = vertex_fixture();validate_product_html(doc, html)
        for key in ['actual_href', 'actual_title', 'actual_inner_text']:
            changed = copy.deepcopy(doc);changed['evidence']['product_page'][key] = 'Инструкция'
            with self.subTest(key=key), self.assertRaises(ValueError):validate_original_document(changed)
        changed = copy.deepcopy(doc);changed['evidence']['product_page']['actual_data_title'] = 'Invented'
        with self.assertRaises(ValueError):validate_original_document(changed)
        for changed in [html.replace(TITLE.encode(), b'Other'), html.replace(INNER_TEXT.encode(), b''),
                        html.replace(b'<a ', b'<a aria-label="Instruction" '), html.replace(b'<a ', b'<a download '),
                        html.replace(b'<a ', b'<a data-title="Instruction" ')]:
            with self.subTest(body=changed), self.assertRaises(ValueError):validate_product_html(with_html(doc, changed), changed)

    def test_all_document_tags_mime_labels_and_conflicting_attrs_fail_closed(self):
        doc, _, html = vertex_fixture()
        for extra in ['<a href="/upload/medialibrary/other.pdf">Other</a>', '<a href="https://evil.test/a.pdf"></a>',
            '<a href="/opaque" type="application/pdf"></a>', '<iframe src="/opaque" title="Инструкция"></iframe>',
            '<object data="https://evil.test/a.pdf" data="/opaque"></object>',
            '<iframe src="/upload/medialibrary/other.pdf" src="/opaque"></iframe>',
            '<embed src="/opaque" type="application/msword">', '<link href="/opaque" type="application/pdf">',
            '<object data="/opaque">Patient leaflet</object>', '<a href="/opaque" download>File</a>',
            '<iframe srcdoc="<a href=https://evil.test/other.pdf>Instruction</a>"></iframe>',
            '<iframe src="/opaque"></iframe>', '<object data="/opaque"></object>', '<embed src="/opaque">',
            '<iframe src="' + PDF_URL + '" srcdoc="<a href=https://evil.test/other.pdf>Instruction</a>"></iframe>',
            '<iframe src="' + PDF_URL + '"></iframe>', '<iframe src="' + HREF + '"></iframe>',
            '<object data="' + PDF_URL + '"></object>', '<object data="' + HREF + '"></object>',
            '<embed src="' + PDF_URL + '">', '<embed src="' + HREF + '">',
            '<a href="/opaque" title="ОХЛП"></a>', '<a href="/upload/medialibrary/a.docx"></a>',
            '<base href="https://vertex.spb.ru/">', html.decode(), '<object data="/opaque">' * 33]:
            body = html + extra.encode()
            with self.subTest(extra=extra), self.assertRaises(ValueError):validate_product_html(with_html(doc, body), body)
        mail = html + b'<a href="mailto:test@example.test" href="mailto:test@example.test">Email</a>'
        validate_product_html(with_html(doc, mail), mail)

    def test_fixed_https_origin_namespace_and_raw_paths_have_no_alias_or_traversal(self):
        for url in ['http://vertex.spb.ru/upload/medialibrary/a.pdf', 'https://www.vertex.spb.ru/upload/medialibrary/a.pdf',
            'https://vertex.spb.ru.evil.test/upload/medialibrary/a.pdf', 'https://user@vertex.spb.ru/upload/medialibrary/a.pdf',
            'https://vertex.spb.ru:444/upload/medialibrary/a.pdf', 'https://vertex.spb.ru/upload/a.pdf',
            PDF_URL + '?x=1', PDF_URL + '#fragment', 'https://vertex.spb.ru/upload/medialibrary/../a.pdf',
            'https://vertex.spb.ru/upload/medialibrary/./a.pdf', 'https://vertex.spb.ru/upload/medialibrary/%252e%252e/a.pdf',
            'https://vertex.spb.ru/upload/medialibrary/a%2fb.pdf', 'https://vertex.spb.ru/upload/medialibrary/a\nb.pdf']:
            with self.subTest(url=url), self.assertRaises(ValueError):manufacturer_pdf_url('vertex', url)
        for href in [HREF + '?x=1', HREF.replace('474/', '474/../474/'), '//vertex.spb.ru' + HREF,
                     HREF.replace('.pdf', '_PROJECT_.pdf')]:
            changed = vertex_fixture()[0];changed['evidence']['product_page']['actual_href'] = href
            with self.subTest(href=href), self.assertRaises(ValueError):validate_original_document(changed)

    def test_saved_html_is_checked_every_archive_apply_without_pdf_cache_bypass(self):
        doc, _, html = vertex_fixture()
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / (ORIGINAL_SHA256 + '.pdf')
            path = Path(directory) / (doc['evidence']['product_page']['html_sha256'] + '.html')
            path.write_bytes(html);validate_manufacturer_archive(doc, pdf)
            path.write_bytes(html + b'<a href="/opaque">Instruction</a>')
            with self.assertRaisesRegex(ValueError, 'HTML hash'):validate_manufacturer_archive(doc, pdf)
            path.unlink()
            with self.assertRaisesRegex(ValueError, 'HTML sibling'):validate_manufacturer_archive(doc, pdf)


class VertexDeliveryTests(unittest.TestCase):
    def test_vertex_source_stop_is_separate_and_keeps_other_markers(self):
        doc = vertex_fixture()[0];session, clock = Session([Reply(b'', status=403)]), Clock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);other = root / '.source-stopped-solopharm';other.write_bytes(b'keep')
            cache = OfficialPdfCache(root, session_factory=lambda: session, clock=clock.now, sleep=clock.sleep)
            with self.assertRaises(OriginalUnavailable):cache.get_bytes(doc)
            self.assertEqual(other.read_bytes(), b'keep')
            self.assertTrue((root / '.source-stopped-vertex').exists())
            self.assertEqual(len(session.calls), 1)
            with self.assertRaises(OriginalUnavailable):cache.get_bytes(doc)
            self.assertEqual(len(session.calls), 1)

    def test_redirect_bad_binary_and_overrun_never_cache_and_tls_is_explicit(self):
        doc = vertex_fixture()[0]
        for reply in [Reply(b'', status=302), Reply(b'%PDF-false\n%%EOF'), Reply(b'x', declared=ORIGINAL_BYTES + 1)]:
            session, clock = Session([reply]), Clock()
            with self.subTest(status=reply.status_code), tempfile.TemporaryDirectory() as directory:
                cache = OfficialPdfCache(directory, session_factory=lambda: session, clock=clock.now, sleep=clock.sleep)
                with self.assertRaises(OriginalUnavailable):cache.get_bytes(doc)
                self.assertEqual(list(Path(directory).glob('*.pdf')), [])
                _, url, options = session.calls[0]
                self.assertEqual(url, PDF_URL);self.assertTrue(options['verify']);self.assertFalse(options['allow_redirects'])
                self.assertFalse(session.trust_env)


if __name__ == '__main__':
    unittest.main()
