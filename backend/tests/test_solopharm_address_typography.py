"""Exactly two source-pinned typography blocks; fixtures are not publication approval."""
import copy
import unittest

from api.medication_original_pdfs import canonical_hash, validate_original_document
from api.solopharm_original_pdfs import (
    GRLS_ADDRESS, GRLS_COMPANY, GROTEX_ADDRESS_PROFILE, PDF_ADDRESS,
    validate_solopharm_physical_proof,
)
from test_solopharm_originals import solopharm_fixture


# Independently transcribed from physically viewed retained pages. Do not import
# the implementation's tuple table into expectations or generate medical text.
OBSERVED = [
    {'tuple': 'atrevozol_country_separate_full_pr',
     'sha': 'f712fb4233228757dc6d3f69857c4c2e13fbb0f549102b32e667c0adf5ec89d9',
     'pages': 7, 'maker_page': 7, 'country': 'Российская Федерация',
     'address': '195279, г. Санкт-Петербург, Индустриальный проспект, д. 71, корп. 2, лит. А',
     'context': 'Производитель\nРоссийская Федерация\nООО «Гротекс»\n'
                '195279, г. Санкт-Петербург, Индустриальный проспект, д. 71, корп. 2, лит. А'},
    {'tuple': 'pentox_country_companyline_short_pr',
     'sha': 'ab75a66b13554ab76142b16a71ccc423d386334beff8a961a1897e17d85d8e0c',
     'pages': 10, 'maker_page': 10, 'country': 'Россия',
     'address': '195279, Санкт-Петербург, Индустриальный пр., д. 71, корп. 2, лит. А',
     'context': 'Производитель\nООО «Гротекс», Россия\n'
                '195279, Санкт-Петербург, Индустриальный пр., д. 71, корп. 2, лит. А'},
]
GRLS_PARTS = ['Производитель (готовой ЛФ)', GRLS_COMPANY, GRLS_ADDRESS]


def physical_fixture(index=0):
    observed = OBSERVED[index]
    maker = {'raw': 'ООО «Гротекс»', 'raw_role': 'Производитель',
             'physical_address_profile': GROTEX_ADDRESS_PROFILE, 'physical_address_tuple': observed['tuple'],
             'physical_country_raw': observed['country'], 'physical_address_raw': observed['address'],
             'context_raw': observed['context'], 'page_indices': [observed['maker_page']]}
    doc = {'original_sha256': observed['sha'], 'version': 'sha256:' + observed['sha'],
           'page_count': observed['pages'], 'revision_date': None, 'approved_at': None,
           'evidence': {'visual_identity': {'original_sha256': observed['sha'], 'page_count': observed['pages'],
                        'all_pages_visually_reviewed': True, 'fields': {'manufacturer': maker}}}}
    return doc, maker


def validation_only_fixture(index=0):
    """Synthetic metadata exercises global guards, not the real PDF archive.

    No synthetic fixture is serialized/imported as a real reviewed wrapper.
    Actual retained binary/identity checks are a separate required data gate.
    """
    doc = solopharm_fixture()[0]
    physical, maker = physical_fixture(index)
    doc.update({key: physical[key] for key in ('original_sha256', 'version', 'page_count')})
    visual = doc['evidence']['visual_identity']
    visual.update(original_sha256=doc['original_sha256'], version=doc['version'], page_count=doc['page_count'])
    visual['fields']['manufacturer'] = maker
    return doc


class SolopharmAddressTypographyTests(unittest.TestCase):
    def test_two_real_literal_blocks_require_their_own_original_and_do_not_rewrite(self):
        for index in range(2):
            doc, maker = physical_fixture(index)
            before = copy.deepcopy(doc)
            with self.subTest(original=doc['original_sha256']):
                self.assertIsNone(validate_solopharm_physical_proof(doc, maker, GRLS_PARTS))
                self.assertEqual(doc, before)
                normalized = validate_original_document(validation_only_fixture(index))
                self.assertEqual(normalized, validate_original_document(normalized))
                self.assertNotIn('sections', normalized)

    def test_another_pdf_cannot_reuse_either_address_block_even_with_consistent_rewritten_proof(self):
        for index in range(2):
            doc, maker = physical_fixture(index)
            doc['original_sha256'] = 'a' * 64
            doc['version'] = 'sha256:' + doc['original_sha256']
            doc['evidence']['visual_identity']['original_sha256'] = doc['original_sha256']
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'exact PDF SHA'):
                validate_solopharm_physical_proof(doc, maker, GRLS_PARTS)

    def test_visual_sha_page_count_and_exact_singleton_maker_page_are_pinned(self):
        mutations = [
            ('document_count', lambda d, m: d.update(page_count=d['page_count'] + 1)),
            ('consistent_other_count', lambda d, m: (d.update(page_count=d['page_count'] + 1),
                d['evidence']['visual_identity'].update(page_count=d['page_count']))),
            ('visual_count', lambda d, m: d['evidence']['visual_identity'].update(page_count=1)),
            ('visual_sha', lambda d, m: d['evidence']['visual_identity'].update(original_sha256='a' * 64)),
            ('unreviewed', lambda d, m: d['evidence']['visual_identity'].update(all_pages_visually_reviewed=False)),
            ('wrong_maker_page', lambda d, m: m.update(page_indices=[1])),
            ('extra_maker_page', lambda d, m: m.update(page_indices=[1, d['page_count']])),
            ('wrong_tuple', lambda d, m: m.update(physical_address_tuple=OBSERVED[1]['tuple'])),
            ('malformed_visual', lambda d, m: d['evidence'].update(visual_identity=[])),
            ('missing_evidence', lambda d, m: d.pop('evidence')),
        ]
        for name, mutate in mutations:
            doc, maker = physical_fixture()
            mutate(doc, maker)
            with self.subTest(mutation=name), self.assertRaises(ValueError):
                validate_solopharm_physical_proof(doc, maker, GRLS_PARTS)

    def test_every_country_company_address_role_context_literal_is_exact(self):
        for index in range(2):
            mutations = [
                ('raw', 'ООО "Гротекс"'), ('raw', 'Другая компания'),
                ('raw_role', 'Держатель регистрационного удостоверения и производитель'),
                ('raw_role', 'Производитель/Организация, принимающая претензии'),
                ('raw_role', 'Упаковщик'), ('raw_role', 'Выпускающий контроль'),
                ('physical_country_raw', 'РФ'),
                ('physical_address_raw', OBSERVED[index]['address'].replace('71', '72')),
                ('physical_address_raw', OBSERVED[index]['address'].replace('корп. 2', 'корп. 3')),
                ('physical_address_raw', OBSERVED[index]['address'].replace('лит. А', 'лит. Б')),
                ('physical_address_raw', OBSERVED[index]['address'].replace('корп. 2', 'к.2')),
                ('physical_address_raw', PDF_ADDRESS),
                ('context_raw', OBSERVED[index]['context'].replace('Производитель', 'Держатель регистрационного удостоверения')),
                ('context_raw', OBSERVED[index]['context'] + '\n'),
                ('context_raw', 'x' * 100000),
            ]
            for field, value in mutations:
                doc, maker = physical_fixture(index); maker[field] = value
                with self.subTest(index=index, field=field, value=str(value)[:100]), self.assertRaises(ValueError):
                    validate_solopharm_physical_proof(doc, maker, GRLS_PARTS)

    def test_no_optin_missing_unknown_or_malformed_proof_never_enables_new_address(self):
        for field in ['physical_address_profile', 'physical_address_tuple', 'physical_country_raw',
                      'physical_address_raw', 'context_raw', 'raw_role', 'page_indices']:
            for value in ['missing', None, [], {}, 123, 'unknown']:
                doc, maker = physical_fixture()
                if value == 'missing': maker.pop(field)
                else: maker[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_solopharm_physical_proof(doc, maker, GRLS_PARTS)

    def test_current_grls_finished_company_and_site_guard_remains_required(self):
        for index, value in [(1, GRLS_COMPANY.replace('Гротекс', 'Другая')),
                             (2, GRLS_ADDRESS.replace('корп. 2', 'корп. 3')),
                             (2, GRLS_ADDRESS.replace('лит. А', 'лит. Б'))]:
            doc, maker = physical_fixture(); parts = list(GRLS_PARTS);parts[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                validate_solopharm_physical_proof(doc, maker, parts)

    def test_global_identity_current_ru_project_version_and_whole_review_guards_remain_required(self):
        for mutate in [
            lambda d: d['evidence']['visual_identity']['fields']['registration_number'].update(raw='ЛП-000099'),
            lambda d: d['evidence']['visual_identity']['fields']['form'].update(raw='капсулы'),
            lambda d: d['evidence']['visual_identity']['fields']['dosage'].update(raw='20%'),
            lambda d: d['evidence']['visual_identity'].update(version_conflict=True),
            lambda d: d['evidence']['visual_identity'].update(not_unapproved_project=False),
            lambda d: d['evidence']['visual_identity'].update(all_pages_visually_reviewed=False),
            lambda d: d.update(approved_at='2025-01-01'),
        ]:
            doc = validation_only_fixture(); mutate(doc)
            with self.subTest(mutation=repr(mutate)), self.assertRaises(ValueError): validate_original_document(doc)

    def test_legacy_hash_and_behavior_remain_unchanged_without_optin(self):
        doc = solopharm_fixture()[0]
        self.assertNotIn('physical_address_profile', doc['evidence']['visual_identity']['fields']['manufacturer'])
        normalized = validate_original_document(doc)
        self.assertEqual(canonical_hash(normalized), '498367ba290c812654ac92b2a6a0e73c523e3c25b2ff24a72bcdf87b12d7399f')
        self.assertEqual(normalized, validate_original_document(normalized))
        maker = doc['evidence']['visual_identity']['fields']['manufacturer']
        maker['physical_address_profile'] = None
        with self.assertRaises(ValueError): validate_original_document(doc)


if __name__ == '__main__':
    unittest.main()
