"""Offline Solopharm profile; synthetic evidence is never publication approval."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from api.instruction_original_delivery import OfficialPdfCache, OriginalUnavailable
from api.manufacturer_original_pdfs import manufacturer_pdf_url, validate_product_html
from api.medication_original_pdfs import canonical_hash, match_original_to_medication, validate_original_document
from api.solopharm_original_pdfs import DATA_TITLE, GRLS_ADDRESS, GRLS_COMPANY, PDF_ADDRESS, PDF_MANUFACTURER
from scripts.import_medication_originals import validate_archive
from test_canon_originals import canon_fixture, physical_stage_fixture
from test_manufacturer_originals import manufacturer_fixture, write_archive
from test_instruction_original_binary import project_pdf_bytes
from test_instruction_originals import Clock, Reply, Session, fixture


def solopharm_fixture():
    doc, med, body, _ = manufacturer_fixture()
    page = 'https://solopharm.com/products/synthetic/200-mg'
    href = '/storage/files/products/SyntheticOriginal.pdf'
    pdf = 'https://solopharm.com' + href
    html = ('<h1>Синтетический препарат</h1><a data-title="' + DATA_TITLE + '" href="' + href + '"></a>').encode()
    doc['id'] = 'solopharm-synthetic-original'
    doc['source'].update(provider='solopharm', name='Официальный производитель: synthetic fixture', url=page, pdf_url=pdf)
    doc['evidence']['product_page'] = {'url': page, 'pdf_url': pdf, 'actual_href': href,
        'html_sha256': hashlib.sha256(html).hexdigest(), 'actual_data_title': DATA_TITLE, 'actual_inner_text': ''}
    doc['version'] = 'sha256:' + doc['original_sha256']
    doc['identity']['manufacturers'] = ['ООО ГРОТЕКС']
    med['manufacturer'] = 'ООО ГРОТЕКС'
    evidence = doc['evidence']
    evidence['visual_identity']['version'] = doc['version']
    evidence['visual_identity']['fields']['manufacturer'].update(raw=PDF_MANUFACTURER,
        raw_role='Производитель/Организация, принимающая претензии', physical_address_raw=PDF_ADDRESS)
    fragment = 'Производитель (готовой ЛФ),' + GRLS_COMPANY + ', ' + GRLS_ADDRESS
    evidence['current_grls_registration']['production_stages'] = fragment
    evidence['current_grls_registration_sha256'] = canonical_hash(evidence['current_grls_registration'])
    evidence['grls_production_fragment'] = fragment
    return doc, med, body, html


def with_html(doc, html):
    result = copy.deepcopy(doc)
    result['evidence']['product_page']['html_sha256'] = hashlib.sha256(html).hexdigest()
    return result


class SolopharmIdentityTests(unittest.TestCase):
    def test_explicit_profile_remains_idempotent_and_exact_variant_specific(self):
        doc, med, _, html = solopharm_fixture()
        result = validate_original_document(doc)
        self.assertEqual(result, validate_original_document(result))
        self.assertEqual(result['completeness'], {'original_pdf_confirmed': True, 'inline_text_verified': False})
        self.assertNotIn('sections', result)
        self.assertIsNone(result['approved_at'])
        self.assertIsNone(result['revision_date'])
        validate_product_html(result, html)
        self.assertEqual(match_original_to_medication(result, med)['covered_variants'], 1)
        for key, value in [('name', 'Итилокт БВ'), ('dosage', '250 мг'), ('form', 'капсулы'), ('manufacturer', 'ООО Другой')]:
            with self.subTest(key=key):
                self.assertFalse(match_original_to_medication(result, {**med, key: value})['matched'])

    def test_prior_provider_canonical_hashes_are_unchanged(self):
        for make, expected in [
            (canon_fixture, '7abfff9cbf78741c6123095f02f061f3d2476f7113cd19ff4639673cb85efade'),
            (physical_stage_fixture, '35b9342029c7a688aaf3a948e99813b5f561e262b47eb3b936d34fd46701d46e'),
            (manufacturer_fixture, 'c36756f5717cdb826f7eb63ada911bd6fe76497a6521e2ea990c34c5df9d7cda'),
            (fixture, '150a545a1a2ee9dcff3f812d152e92ff9cafcc132c0207cfea1a861e6ad319da')]:
            with self.subTest(provider=make.__name__):
                self.assertEqual(canonical_hash(validate_original_document(make()[0])), expected)

    def test_url_origin_static_namespace_and_raw_href_are_narrow(self):
        base = 'https://solopharm.com/storage/files/products/'
        for url in ['http://solopharm.com/storage/files/products/x.pdf',
                    'https://www.solopharm.com/storage/files/products/x.pdf',
                    'https://solopharm.com.evil.test/storage/files/products/x.pdf',
                    'https://user:pass@solopharm.com/storage/files/products/x.pdf',
                    'https://solopharm.com:444/storage/files/products/x.pdf',
                    'https://solopharm.com/upload/x.pdf', base + 'x.pdf?token=x', base + 'x.pdf#fragment',
                    base + '../x.pdf', base + './x.pdf', base + '%2e%2e/x.pdf', base + '%252e%252e/x.pdf', base + 'x%2fy.pdf',
                    base + 'x\\y.pdf', base + 'x\ny.pdf', base + 'x.docx']:
            with self.subTest(url=url), self.assertRaises(ValueError): manufacturer_pdf_url('solopharm', url)
        for href in ['//solopharm.com/storage/files/products/SyntheticOriginal.pdf',
                     '/storage/files/products/../products/SyntheticOriginal.pdf',
                     '/storage/files/products/%252e%252e/SyntheticOriginal.pdf']:
            doc = solopharm_fixture()[0]
            doc['evidence']['product_page']['actual_href'] = href
            with self.subTest(href=href), self.assertRaises(ValueError): validate_original_document(doc)
        for url in [base + 'x.pdf', 'https://solopharm.com:443/storage/files/products/x.pdf']:
            self.assertEqual(manufacturer_pdf_url('solopharm', url), url)

    def test_old_ru_wrong_name_form_dose_or_any_missing_physical_proof_rejects(self):
        for key, value in [('registration_number', 'ЛП-000099'), ('trade_name', 'Итилокт БВ'),
                           ('form', 'таблетки, покрытые пленочной оболочкой'), ('dosage', '0.255 мг/доза'),
                           ('manufacturer', 'Другая компания')]:
            doc = solopharm_fixture()[0]
            doc['evidence']['visual_identity']['fields'][key]['raw'] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_original_document(doc)
        for field, value in [('all_pages_visually_reviewed', False), ('version_conflict', True),
                             ('not_unapproved_project', False), ('reviewer', ''), ('verified_at', ''),
                             ('original_sha256', 'a' * 64), ('version_review', '')]:
            doc = solopharm_fixture()[0]
            doc['evidence']['visual_identity'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_original_document(doc)

    def test_explicit_finished_grotex_company_alias_and_same_observed_address_are_required(self):
        for mode in ['holder-role', 'packaging', 'missing-address', 'different-address', 'grls-address',
                     'new-alias', 'different-company', 'canon-fallback']:
            doc = solopharm_fixture()[0]
            evidence = doc['evidence']
            visual = evidence['visual_identity']['fields']['manufacturer']
            if mode == 'holder-role': visual['raw_role'] = 'Держатель регистрационного удостоверения'
            if mode == 'packaging': evidence['current_grls_registration']['production_stages'] = evidence['grls_production_fragment'] = evidence['grls_production_fragment'].replace('Производитель (готовой ЛФ)', 'Упаковщик')
            if mode == 'missing-address': del visual['physical_address_raw']
            if mode == 'different-address': visual['physical_address_raw'] = PDF_ADDRESS.replace('к.2', 'к.3')
            if mode == 'grls-address': evidence['current_grls_registration']['production_stages'] = evidence['grls_production_fragment'] = evidence['grls_production_fragment'].replace('корп. 2', 'корп. 3')
            if mode == 'new-alias': doc['identity']['manufacturers'].append('АО ГРОТЕКС')
            if mode == 'different-company': visual['raw'] = 'ООО Другая компания'
            if mode == 'canon-fallback': evidence['manufacturer_proof_mode'] = 'physical_pdf_finished_stage_v1'
            evidence['current_grls_registration_sha256'] = canonical_hash(evidence['current_grls_registration'])
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_original_document(doc)

    def test_no_revision_approval_filename_date_or_non_sha_version_inference(self):
        for mode in ['revision', 'approval', 'version']:
            doc = solopharm_fixture()[0]
            if mode == 'revision': doc['revision_date'] = doc['evidence']['visual_identity']['revision_date'] = '2025-01-01'
            if mode == 'approval': doc['approved_at'] = '2025-01-01'
            if mode == 'version': doc['version'] = doc['evidence']['visual_identity']['version'] = 'newest-2026'
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_original_document(doc)


class SolopharmProductProvenanceTests(unittest.TestCase):
    def test_actual_empty_inner_text_is_distinct_from_data_title(self):
        doc, _, _, html = solopharm_fixture()
        indented = html.replace(b'></a>', b'>\n  <svg></svg>\n </a>')
        validate_product_html(with_html(doc, indented), indented)
        footer = html + b'<a href="mailto:source@example.test" href="mailto:source@example.test">Email</a>'
        validate_product_html(with_html(doc, footer), footer)
        for mode in ['missing-attribute-proof', 'invented-label', 'attribute-as-text', 'wrong-attribute']:
            altered = copy.deepcopy(doc)
            proof = altered['evidence']['product_page']
            if mode == 'missing-attribute-proof': del proof['actual_data_title']
            if mode == 'invented-label': proof['actual_label'] = DATA_TITLE
            if mode == 'attribute-as-text': proof['actual_inner_text'] = DATA_TITLE
            if mode == 'wrong-attribute': proof['actual_data_title'] = 'Скачать'
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_original_document(altered)
        for altered_html in [html.replace(DATA_TITLE.encode(), 'Скачать'.encode()),
                             html.replace(b'></a>', ('>' + DATA_TITLE + '</a>').encode()),
                             html.replace(b'<a ', b'<a aria-label="Instruction" '),
                             html.replace(b'<a ', b'<a data-title="Other" '),
                             html.replace(b'<a ', b'<a href="https://evil.test/a.pdf" ')]:
            with self.subTest(html=altered_html), self.assertRaises(ValueError):
                validate_product_html(with_html(doc, altered_html), altered_html)

    def test_all_unknown_document_formats_medical_labels_and_embeds_fail_closed(self):
        doc, _, _, html = solopharm_fixture()
        for extra in ['<a href="/storage/files/products/other.pdf">Unlabelled</a>',
                      '<a href="/storage/files/products/other.doc">Unlabelled</a>',
                      '<a href="/storage/files/products/other.docx">Unlabelled</a>',
                      '<a href="/storage/files/products/other.odt">Unlabelled</a>',
                      '<a href="https://evil.test/other.pdf">Unlabelled</a>',
                      '<a href="/opaque" data-title="Читать инструкцию"></a>',
                      '<a href="/opaque">Общая характеристика лекарственного препарата</a>',
                      '<a href="/opaque" download>File</a>',
                      '<a href="/opaque">ОХЛП</a>',
                      '<a href="/opaque">PIL</a>',
                      '<a href="/opaque">SmPC</a>',
                      '<a href="/opaque">Patient leaflet</a>',
                      '<a href="/storage/files/products/other.pdf/download">Download</a>',
                      '<object data="https://evil.test/a.pdf"></object>',
                      '<embed src="/storage/files/products/other.pdf">',
                      '<iframe src="/storage/files/products/other.pdf"></iframe>',
                      '<link type="application/pdf" href="/opaque">',
                      '<base href="https://solopharm.com/">']:
            altered_html = html + extra.encode()
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_product_html(with_html(doc, altered_html), altered_html)

    def test_conflicting_document_tag_attributes_cannot_hide_another_original(self):
        doc, _, _, html = solopharm_fixture()
        # First two cases are the independently reproduced duplicate-collapse
        # failures; all processed document tags must apply the same rule.
        examples = [
            '<object data="https://evil.test/other.pdf" data="/opaque"></object>',
            '<iframe src="/storage/files/products/other.pdf" src="/opaque"></iframe>',
            '<embed src="https://evil.test/other.pdf" src="/opaque">',
            '<link href="https://evil.test/other.pdf" href="/opaque">',
            '<a href="/opaque" type="application/pdf" type="text/html"></a>',
            '<object data="/opaque" title="Инструкция" title=""></object>',
            '<iframe src="/opaque" aria-label="Instruction" aria-label=""></iframe>',
            '<embed src="/opaque" data-title="Читать инструкцию" data-title="">',
        ]
        for extra in examples:
            altered = html + extra.encode()
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'duplicate.*attributes'):
                validate_product_html(with_html(doc, altered), altered)

    def test_opaque_document_mime_and_medical_labels_are_classified_on_every_tag(self):
        doc, _, _, html = solopharm_fixture()
        # These are the two opaque-destination reproductions. The remaining
        # fixtures cover the same MIME/label classification on all other tags.
        examples = [
            '<a href="/opaque" type="application/pdf"></a>',
            '<iframe src="/opaque" title="Инструкция"></iframe>',
            '<object data="/opaque" type="application/pdf"></object>',
            '<embed src="/opaque" type="application/msword">',
            '<link href="/opaque" type="application/pdf">',
            '<object data="/opaque" aria-label="Instruction"></object>',
            '<embed src="/opaque" data-title="Читать инструкцию">',
            '<link href="/opaque" title="Общая характеристика"></link>',
            '<iframe src="/opaque">Инструкция</iframe>',
            '<object data="/opaque">Instruction</object>',
        ]
        for extra in examples:
            altered = html + extra.encode()
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'product document requires review'):
                validate_product_html(with_html(doc, altered), altered)

    def test_unclosed_unknown_anchor_or_repeated_selected_anchor_is_ambiguous(self):
        doc, _, _, html = solopharm_fixture()
        for extra in [b'<a href="/storage/files/products/other.pdf">', html,
                      b'<object data="/opaque">' * 33]:
            altered_html = html + extra
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_product_html(with_html(doc, altered_html), altered_html)

    def test_encoded_source_project_markers_cannot_be_overridden_by_visual_final_claims(self):
        for marker in ['_PROJECT_', '_proekt_', '_DRAFT_', 'проект', '%70roject']:
            doc = solopharm_fixture()[0]
            proof = doc['evidence']['product_page']
            href = '/storage/files/products/' + marker + 'Original.pdf'
            proof.update(actual_href=href, pdf_url='https://solopharm.com' + href)
            doc['source']['pdf_url'] = proof['pdf_url']
            with self.subTest(marker=marker), self.assertRaises(ValueError): validate_original_document(doc)

    def test_retained_html_is_rechecked_before_even_cached_pdf_archive_validation(self):
        doc, _, body, html = solopharm_fixture()
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            pdf = write_archive(folder, doc, body, html)
            validate_archive(validate_original_document(doc), pdf)
            html_path = folder / (doc['evidence']['product_page']['html_sha256'] + '.html')
            html_path.write_bytes(html + b'<a href="/opaque">Instruction</a>')
            with self.assertRaisesRegex(ValueError, 'HTML hash'): validate_archive(validate_original_document(doc), pdf)
            html_path.unlink()
            with self.assertRaisesRegex(ValueError, 'HTML sibling'): validate_archive(validate_original_document(doc), pdf)

    def test_real_physical_first_page_project_guard_is_preserved(self):
        doc, _, _, html = solopharm_fixture()
        body = project_pdf_bytes()
        doc.update(original_sha256=hashlib.sha256(body).hexdigest(), original_bytes=len(body))
        doc['version'] = 'sha256:' + doc['original_sha256']
        doc['evidence']['visual_identity'].update(original_sha256=doc['original_sha256'], version=doc['version'])
        with tempfile.TemporaryDirectory() as directory:
            pdf = write_archive(Path(directory), doc, body, html)
            with self.assertRaisesRegex(ValueError, 'physical first page.*project/draft'): validate_archive(doc, pdf)


class SolopharmDeliveryTests(unittest.TestCase):
    def test_fixed_host_delivery_reuses_bounded_cache_tls_and_no_redirect(self):
        doc, _, body, _ = solopharm_fixture()
        session, clock = Session([Reply(body)]), Clock()
        with tempfile.TemporaryDirectory() as directory:
            cache = OfficialPdfCache(directory, session_factory=lambda: session, clock=clock.now, sleep=clock.sleep)
            self.assertEqual(cache.get_bytes(doc), body)
            self.assertEqual(cache.get_bytes(doc), body)
            self.assertEqual(len(session.calls), 1)
            method, url, options = session.calls[0]
            self.assertEqual((method, url), ('GET', doc['source']['pdf_url']))
            self.assertTrue(options['verify'])
            self.assertFalse(options['allow_redirects'])
            self.assertFalse(session.trust_env)
            self.assertTrue(session.closed)

    def test_redirect_changed_sha_truncation_and_byte_overrun_never_cache(self):
        doc, _, body, _ = solopharm_fixture()
        for reply in [Reply(b'', status=302), Reply(body.replace(b'q Q', b'q q')),
                      Reply(body[:-3], declared=len(body)), Reply(body + b'x')]:
            reply.headers['Location'] = 'https://evil.test/a.pdf'
            with tempfile.TemporaryDirectory() as directory:
                session = Session([reply])
                with self.subTest(reply=reply), self.assertRaises(OriginalUnavailable):
                    OfficialPdfCache(directory, session_factory=lambda: session).get_bytes(doc)
                self.assertEqual(len(session.calls), 1)
                self.assertEqual(list(Path(directory).glob('*.pdf')), [])

    def test_access_denial_stops_only_solopharm_and_preserves_other_markers(self):
        doc, _, body, _ = solopharm_fixture()
        renewal = manufacturer_fixture()[0]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            folder.mkdir(exist_ok=True)
            eaeu_stop = folder / '.source-stopped'
            eaeu_stop.write_text('existing EAEU stop')
            for status in [401, 403, 429]:
                marker = folder / '.source-stopped-solopharm'
                marker.unlink(missing_ok=True)
                session = Session([Reply(b'blocked', status=status)])
                cache = OfficialPdfCache(directory, session_factory=lambda: session)
                with self.subTest(status=status), self.assertRaises(OriginalUnavailable): cache.get_bytes(doc)
                self.assertTrue(marker.is_file())
                unused = Session([])
                with self.assertRaises(OriginalUnavailable): OfficialPdfCache(directory, session_factory=lambda: unused).get_bytes(doc)
                self.assertEqual(unused.calls, [])
                self.assertEqual(eaeu_stop.read_text(), 'existing EAEU stop')
            # An independent manufacturer is still allowed.
            self.assertEqual(OfficialPdfCache(directory, session_factory=lambda: Session([Reply(body)])).get_bytes(renewal), body)
            self.assertFalse((folder / '.source-stopped-renewal').exists())


if __name__ == '__main__':
    unittest.main()
