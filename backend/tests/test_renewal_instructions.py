"""No network: official-link discovery and stop/identity guard fixtures."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.robotparser import RobotFileParser

from scripts.sources.renewal_instructions import (
    ORIGIN, RenewalAccessError, RenewalClient, RenewalSourceError,
    Provider, _worker_rss_kib, discover, extraction_diagnostics, is_challenge, parse_product_html, public_url, relevant_slugs, robots_lines,
)


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status, self.headers = status, headers or {}


class Opener:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        return self.response


class RenewalTests(unittest.TestCase):
    def test_observed_akrikhin_product_uses_document_title_without_h1(self):
        provider = Provider('akrikhin', 'https://akrikhin.ru', ('akrikhin.ru',),
                            '/catalog/', ('/upload/',), ('акрихин',))
        html = '<title>Тестовый препарат (крем для наружного применения) 0,1 %</title><a href="/upload/pil.pdf">Инструкция</a>'
        parsed = parse_product_html(html, 'https://akrikhin.ru/catalog/fixture/', provider)
        self.assertEqual(parsed['title'], 'Тестовый препарат (крем для наружного применения) 0,1 %')
        self.assertEqual(len(parsed['pdf_links']), 1)

    def test_plain_official_sitemap_index_follows_only_observed_child_and_product(self):
        class PlainClient:
            provider = Provider('fixture', 'https://manufacturer.test', ('manufacturer.test',),
                                '/products/', ('/files/',), ('fixture',))

            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append(url)
                bodies = {
                    'https://manufacturer.test/robots.txt': b'User-agent: *\nSitemap: https://manufacturer.test/sitemap.xml\n',
                    'https://manufacturer.test/sitemap.xml': b'<sitemapindex><sitemap><loc>https://manufacturer.test/sitemap-ru.xml</loc></sitemap></sitemapindex>',
                    'https://manufacturer.test/sitemap-ru.xml': b'<urlset><url><loc>https://manufacturer.test/products/fixture/</loc></url><url><loc>https://foreign.test/products/other/</loc></url></urlset>',
                }
                return bodies[url], {'url': url, 'sha256': 'synthetic'}

        with tempfile.TemporaryDirectory() as temporary:
            client = PlainClient()
            urls = discover(client, Path(temporary))
            self.assertEqual(urls, ['https://manufacturer.test/products/fixture/'])
            self.assertEqual(len(client.calls), 3)

    def test_explicit_provider_policy_upgrades_observed_http_redirect_using_tls(self):
        class SequenceOpener:
            def __init__(self, destination):
                self.destination, self.calls = destination, []

            def open(self, request, timeout):
                self.calls.append(request.full_url)
                return (Response(b'', 301, {'Location': self.destination}) if len(self.calls) == 1
                        else Response(b'official product'))

        provider = Provider('fixture', 'https://manufacturer.test', ('manufacturer.test',),
                            '/catalog/', ('/upload/',), ('fixture',), True)
        opener = SequenceOpener('http://manufacturer.test/catalog/current/')
        with patch('scripts.sources.renewal_instructions.time.sleep'):
            body, metadata = RenewalClient(opener, provider=provider).get('https://manufacturer.test/catalog/old/')
        self.assertEqual(body, b'official product')
        self.assertEqual(opener.calls, ['https://manufacturer.test/catalog/old/', 'https://manufacturer.test/catalog/current/'])
        self.assertEqual(metadata['https_transport_upgrades'][0]['advertised_location'], opener.destination)
        for target in ['http://foreign.test/catalog/current/', 'http://manufacturer.test:8080/current/',
                       'http://manufacturer.test/current/?role=doctor', 'http://user@manufacturer.test/current/']:
            with self.subTest(target=target), patch('scripts.sources.renewal_instructions.time.sleep'):
                bad = SequenceOpener(target)
                with self.assertRaises(RenewalSourceError):
                    RenewalClient(bad, provider=provider).get('https://manufacturer.test/catalog/old/')
                self.assertEqual(len(bad.calls), 1)
        strict = Provider('fixture', 'https://manufacturer.test', ('manufacturer.test',),
                          '/catalog/', ('/upload/',), ('fixture',))
        with self.assertRaises(RenewalSourceError):
            RenewalClient(SequenceOpener(opener.destination), provider=strict).get('https://manufacturer.test/catalog/old/')

    def test_only_actual_official_instruction_links_are_kept(self):
        html = '''<h1>Тестовый препарат Реневал 10 мг</h1>
        <a href="/upload/iblock/fixture/test.pdf">Скачать инструкцию</a>
        <a href="/upload/iblock/fixture/test.pdf">Подробнее в инструкции</a>
        <a href="https://other.test/instruction.pdf">Инструкция</a>
        <a href="javascript:alert(1)">Инструкция</a>
        <a href="/upload/privacy.pdf">Политика конфиденциальности</a>
        <a href="/login/?file=instruction.pdf">Инструкция</a>'''
        result = parse_product_html(html, ORIGIN + '/products/fixture/')
        self.assertEqual(result['title'], 'Тестовый препарат Реневал 10 мг')
        self.assertEqual([row['url'] for row in result['pdf_links']], [ORIGIN + '/upload/iblock/fixture/test.pdf'])

    def test_product_selection_is_a_hint_and_respects_name_boundaries(self):
        meds = [{'slug':'test','name':'Тест® Реневал','manufacturer':'АО ПФК ОБНОВЛЕНИЕ'},
                {'slug':'different','name':'Тест','manufacturer':'Другая компания'}]
        self.assertEqual(relevant_slugs('Тест Реневал 10 мг №30', meds), ['test'])
        self.assertEqual(relevant_slugs('Тест Реневалплюс 10 мг', meds), [])

    def test_literal_percent_in_actual_pdf_name_is_encoded_without_double_encoding(self):
        url = public_url('/upload/iblock/fixture/Раствор 0,1% 10мл.pdf')
        self.assertIn('0,1%25%2010', url)
        self.assertIn('%D0%A0', url)
        self.assertEqual(public_url(url), url)
        self.assertEqual(public_url('/upload/fixture/already%20encoded%25.pdf'),
                         ORIGIN + '/upload/fixture/already%20encoded%25.pdf')

    def test_no_role_or_auth_claim_and_no_foreign_or_query_urls(self):
        opener = Opener(Response(b'public fixture'))
        client = RenewalClient(opener)
        body, meta = client.get(ORIGIN + '/products/fixture/')
        self.assertEqual(body, b'public fixture')
        self.assertEqual(opener.calls[0].get_method(), 'GET')
        self.assertNotIn('Cookie', opener.calls[0].headers)
        self.assertNotIn('Authorization', opener.calls[0].headers)
        for url in ['https://other.test/file.pdf', ORIGIN + '/?role=doctor', 'javascript:alert(1)',
                    ORIGIN + ':8080/upload/file.pdf', ORIGIN + ':invalid/upload/file.pdf']:
            with self.assertRaises(RenewalSourceError):
                public_url(url)

    def test_access_denial_stops_after_one_request(self):
        for status in [401,403,429]:
            opener = Opener(Response(b'blocked', status))
            with self.assertRaises(RenewalAccessError):
                RenewalClient(opener).get(ORIGIN + '/products/fixture/')
            self.assertEqual(len(opener.calls), 1)
        self.assertTrue(is_challenge(b'<form id="challenge-form">'))
        self.assertFalse(is_challenge(b'<script src="recaptcha.js"></script><h1>Public product</h1>'))

    def test_provider_configuration_keeps_host_and_path_boundaries(self):
        provider = Provider('fixture','https://manufacturer.test',('manufacturer.test',),'/catalog/',('/files/',),('fixture',))
        html = '<h1>Fixture medicine</h1><a href="/files/instruction.pdf">Инструкция</a><a href="https://www.renewal.ru/upload/instruction.pdf">Инструкция</a>'
        row = parse_product_html(html,'https://manufacturer.test/catalog/product/',provider)
        self.assertEqual([x['url'] for x in row['pdf_links']],['https://manufacturer.test/files/instruction.pdf'])
        self.assertEqual(robots_lines(r'User-Agent: *\r\nDisallow: /private/\r\nSitemap: https://manufacturer.test/sitemap.xml'),
                         ['User-Agent: *','Disallow: /private/','Sitemap: https://manufacturer.test/sitemap.xml'])

    def test_mixed_sitemap_urls_skip_http_and_foreign_without_upgrade(self):
        class PublicFixtureClient:
            provider = Provider('fixture','https://manufacturer.test',('manufacturer.test',),'/catalog/',('/files/',),('fixture',))

            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append(url)
                payloads = {
                    'https://manufacturer.test/robots.txt': b'User-agent: *\nSitemap: http://manufacturer.test/ar/sitemap.xml\nSitemap: https://foreign.test/sitemap.xml\nSitemap: https://manufacturer.test/sitemap.xml\n',
                    'https://manufacturer.test/sitemap.xml': b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://manufacturer.test/catalog/medicine/</loc></url></urlset>',
                }
                return payloads[url], {'url': url, 'sha256':'fixture'}

        client = PublicFixtureClient()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            self.assertEqual(discover(client, directory), ['https://manufacturer.test/catalog/medicine/'])
            result = json.loads((directory / 'product-urls.json').read_text())
        self.assertEqual(client.calls, ['https://manufacturer.test/robots.txt', 'https://manufacturer.test/sitemap.xml'])
        self.assertEqual([item['url'] for item in result['ignored_source_urls']],
                         ['http://manufacturer.test/ar/sitemap.xml', 'https://foreign.test/sitemap.xml'])

    def test_vertex_observed_title_and_patient_tab_exclude_research(self):
        provider = Provider('vertex','https://vertex.spb.ru',('vertex.spb.ru',),'/products/',('/upload/',),('вертекс',))
        html = '''<title>Карбоцистеин</title><meta property="og:title" content="Карбоцистеин">
        <div class="product-information__content-box" data-index="2"><div class="product-information__row">
        <b>Информация для пациента</b><a title="карбоцистеин.pdf" href="/upload/medialibrary/fixture.pdf">Карбоцистеин сироп</a></div></div>
        <div class="product-information__content-box" data-index="5"><div class="product-information__row">
        <a href="/upload/medialibrary/study.pdf">Исследование инструкции и эффективности препарата</a></div></div>'''
        row = parse_product_html(html,provider.origin+'/products/otc-medicines/carbocisteine/',provider)
        self.assertEqual(row['title'], 'Карбоцистеин')
        self.assertEqual([link['url'] for link in row['pdf_links']], ['https://vertex.spb.ru/upload/medialibrary/fixture.pdf'])
        row = parse_product_html('<meta property="og:title" content="ДУОКОЛД&amp;reg;">',provider.origin+'/products/otc-medicines/duocold/',provider)
        self.assertEqual(row['title'], 'ДУОКОЛД®')

    def test_patient_and_professional_leaflets_are_candidates_not_approval(self):
        html = '<h1>Fixture</h1><a href="/upload/patient.pdf">Скачать информацию для пациента</a><a href="/upload/professional.pdf">Скачать информацию для работника здравоохранения</a><a href="/upload/general.pdf">Общая характеристика лекарственного препарата</a>'
        result = parse_product_html(html, ORIGIN + '/products/fixture/')
        self.assertEqual(len(result['pdf_links']), 3)
        self.assertNotIn('verification', result)

    def test_incomplete_transport_is_rejected(self):
        opener = Opener(Response(b'%PDF-fixture', headers={'Content-Length': '1000'}))
        with self.assertRaisesRegex(RenewalSourceError, 'Content-Length'):
            RenewalClient(opener).get(ORIGIN + '/upload/fixture.pdf')

    def test_redirect_respects_robots_without_requesting_disallowed_target(self):
        opener = Opener(Response(b'', 302, {'Location': '/private/instruction.pdf'}))
        client = RenewalClient(opener)
        client.robots = RobotFileParser()
        client.robots.parse(['User-agent: *', 'Disallow: /private/'])
        with self.assertRaisesRegex(RenewalSourceError, 'robots.txt'):
            client.get(ORIGIN + '/upload/fixture.pdf')
        self.assertEqual(len(opener.calls), 1)

    def test_empty_required_heading_is_not_semantic_completeness(self):
        report = {'text':'ИНСТРУКЦИЯ ПО МЕДИЦИНСКОМУ ПРИМЕНЕНИЮ', 'missing_sections':[],
                  'sections':[{'key':'composition','title':'Состав','text':'Состав'},
                              {'key':'composition_2','title':'Состав','text':'Состав\nFixture table text'}]}
        row = extraction_diagnostics(report)
        self.assertTrue(row['old_headers_present'])
        self.assertEqual(row['heading_only_sections'], ['composition'])
        self.assertTrue(row['clinical_table_order_review'])
        self.assertFalse(row['classification_is_approval'])
        self.assertNotEqual(row['verification_status'], 'verified')

    def test_leaflet_profile_does_not_claim_old_instruction_headers(self):
        report = {'text':'Листок-вкладыш. Информация для пациента',
                  'document_type':'patient_leaflet', 'missing_sections':[], 'sections':[],
                  'section_review_reasons':[]}
        row = extraction_diagnostics(report)
        self.assertEqual(row['extracted_document_type'], 'patient_leaflet')
        self.assertTrue(row['required_profile_sections_present'])
        self.assertIsNone(row['old_headers_present'])
        self.assertFalse(row['classification_is_approval'])
        self.assertNotEqual(row['verification_status'], 'verified')

    def test_linux_memory_monitor_uses_proc_without_ps(self):
        with patch('scripts.sources.renewal_instructions.sys.platform', 'linux'), \
             patch.object(Path, 'read_text', return_value='Name:\tpython\nVmRSS:\t123456 kB\n'), \
             patch('scripts.sources.renewal_instructions.subprocess.run') as run:
            self.assertEqual(_worker_rss_kib(123), 123456)
            run.assert_not_called()
        with patch('scripts.sources.renewal_instructions.sys.platform', 'linux'), \
             patch.object(Path, 'read_text', side_effect=FileNotFoundError):
            self.assertIsNone(_worker_rss_kib(123))

    def test_unavailable_macos_memory_monitor_fails_closed(self):
        with patch('scripts.sources.renewal_instructions.sys.platform', 'darwin'), \
             patch('scripts.sources.renewal_instructions.subprocess.run', side_effect=FileNotFoundError):
            self.assertIsNone(_worker_rss_kib(123))

    def test_linux_exec_transition_requires_real_rss_after_bounded_retry(self):
        starting = 'Name:\tpython\nState:\tR (running)\nThreads:\t1\n'
        ready = starting + 'VmRSS:\t123456 kB\n'
        with patch('scripts.sources.renewal_instructions.sys.platform', 'linux'), \
             patch.object(Path, 'read_text', side_effect=[starting, starting, ready]) as read, \
             patch('scripts.sources.renewal_instructions.time.sleep') as sleep:
            self.assertEqual(_worker_rss_kib(123), 123456)
            self.assertEqual(read.call_count, 3)
            self.assertEqual([call.args for call in sleep.call_args_list], [(0.01,), (0.01,)])
        with patch('scripts.sources.renewal_instructions.sys.platform', 'linux'), \
             patch.object(Path, 'read_text', return_value=starting) as read, \
             patch('scripts.sources.renewal_instructions.time.sleep') as sleep:
            self.assertIsNone(_worker_rss_kib(123))
            self.assertEqual(read.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_linux_confirmed_zombie_or_dead_task_has_zero_resident_memory(self):
        for state in ['Z (zombie)', 'X (dead)']:
            with patch('scripts.sources.renewal_instructions.sys.platform', 'linux'), \
                 patch.object(Path, 'read_text', return_value='Name:\tpython\nState:\t' + state + '\n'), \
                 patch('scripts.sources.renewal_instructions.time.sleep') as sleep:
                self.assertEqual(_worker_rss_kib(123), 0)
                sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
