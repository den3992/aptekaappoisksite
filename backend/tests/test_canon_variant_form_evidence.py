"""Offline per-GTIN form proofs, live apply races and row-local read/cache guards.

Labels/identities are retained real catalog fixtures. PDF/provenance objects are
explicitly synthetic test fixtures and are never publication wrappers.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from api.canon_variant_form_evidence import (
    DISABLED, FILM_FORM, GENERIC_FORM, MODE, eligible_variant_keys, evidence_digest,
    form_binding_id, label_identity_digest,
)
from api.medication_instructions import _ru, _variant, medication_identity_fingerprint
from api.medication_original_pdfs import (
    MedicationOriginalService, canonical_hash, match_original_to_medication, validate_original_document,
)
from scripts.import_medication_instructions import ImportConflict, apply_plan, binding_id, build_plan, load_documents
from scripts.import_medication_originals import OriginalCollections, validate_archive
from test_canon_originals import canon_fixture
from test_instruction_import import Collection
from test_instruction_originals import AsyncCollection
from test_manufacturer_originals import write_archive


REAL_SCOPES = json.loads((Path(__file__).parent / 'fixtures/canon_variant_form_labels.json').read_text())['scopes']


def film_fixture(index=0):
    source = copy.deepcopy(REAL_SCOPES[index])
    source.pop('source_form'); source.pop('source_pdf_sha256')
    med = {**source, 'is_canonical': True}
    doc, _, body, html = canon_fixture()
    doc['id'] = 'synthetic-form-' + hashlib.sha256(med['slug'].encode()).hexdigest()[:16]
    doc['identity'] = {'trade_name': med['name'], 'manufacturers': [med['manufacturer']]}
    doc['registration_numbers'] = [med['ru_number']]
    doc['scopes'] = [{'gtin': None, 'ru_number': med['ru_number'], 'form': FILM_FORM, 'dosage': med['dosage']}]
    evidence = doc['evidence']; grls = evidence['current_grls_registration']
    grls.update(registration_number=med['ru_number'], registration_key=_ru(med['ru_number']),
                trade_name=med['name'], holder=med['manufacturer'],
                release_forms=FILM_FORM + ', ' + med['dosage'] + ', 10 шт.;')
    fragment = 'Производитель (готовой ЛФ),' + med['manufacturer'] + ', Россия'
    grls['production_stages'] = evidence['grls_production_fragment'] = fragment
    evidence['current_grls_registration_sha256'] = canonical_hash(grls)
    for key, value in [('registration_number', med['ru_number']), ('trade_name', med['name']),
                       ('form', FILM_FORM), ('dosage', med['dosage']), ('manufacturer', med['manufacturer'])]:
        evidence['visual_identity']['fields'][key]['raw'] = value
    return validate_original_document(doc), med, body, html


def proof_for(doc, med, variants=None):
    fields = doc['evidence']['visual_identity']['fields']
    values = []
    for raw in med['variants'] if variants is None else variants:
        variant = _variant(med, raw)
        values.append({'gtin': variant['gtin'], 'ru_number': _ru(variant['ru_number']),
                       'catalog_form': variant['form'], 'catalog_dosage': variant['dosage'],
                       'label_name': raw.get('label_name'), 'esklp_code': raw.get('esklp_code'),
                       'label_sha256': hashlib.sha256((raw.get('label_name') or '').encode()).hexdigest()})
    return {'mode': MODE, 'medicine_slug': med['slug'], 'catalog_name': med['name'],
            'catalog_manufacturer': med['manufacturer'], 'document_sha256': canonical_hash(doc),
            'original_sha256': doc['original_sha256'],
            'grls_row_sha256': doc['evidence']['current_grls_registration_sha256'],
            'product_html_sha256': doc['evidence']['product_page']['html_sha256'],
            'source_form_pages': fields['form']['page_indices'],
            'source_dosage_pages': fields['dosage']['page_indices'], 'variants': values}


def record(doc, med, path=None):
    result = {'document': doc, 'variant_form_evidence': [proof_for(doc, med)]}
    if path is not None:
        result['original_file'] = str(path)
    return result


def plan_for(records, meds):
    return build_plan(records, meds, validator=validate_original_document, matcher=match_original_to_medication,
                      allow_variant_form_evidence=True)


def row_for(doc, med, variants, proof=None):
    row = {'document_id': doc['id'], 'medicine_slug': med['slug'], 'record_type': 'binding',
           'status': 'verified', 'active': True, 'identity_fingerprint': medication_identity_fingerprint(med),
           'variant_bindings': variants}
    row['binding_id'] = binding_id(doc['id'], med['slug'], row['identity_fingerprint'], variants,
                                   variant_form_evidence=proof)
    if proof is not None:
        row.update(variant_form_evidence=proof, variant_form_evidence_sha256=evidence_digest(proof))
    return row


class FormEvidenceTests(unittest.TestCase):
    def test_complete_real_seven_scope_41_variant_batch_is_explicit_and_source_preserving(self):
        fixtures = [film_fixture(i) for i in range(len(REAL_SCOPES))]
        documents = [canonical_hash(doc) for doc, _, _, _ in fixtures]
        for doc, med, _, _ in fixtures:
            self.assertFalse(match_original_to_medication(doc, med)['matched'])
            matched = match_original_to_medication(doc, med, variant_form_evidence=proof_for(doc, med))
            self.assertEqual(matched['covered_variants'], len(med['variants']))
            self.assertTrue(all(v['form'] == med['form'] for v in matched['bindings']))
            self.assertTrue(all(v['form'].casefold() == GENERIC_FORM for v in matched['bindings']))
        plan = plan_for([record(doc, med) for doc, med, _, _ in fixtures], [med for _, med, _, _ in fixtures])
        self.assertEqual(plan['rejected'], [])
        self.assertEqual(plan['counts']['matched_documents'], 7)
        self.assertEqual(plan['counts']['planned_bindings'], 7)
        self.assertEqual(plan['coverage_planned']['covered_variants'], 41)
        self.assertEqual(plan['coverage_planned']['cards_with_any_instruction'], 7)
        self.assertEqual(documents, [canonical_hash(doc) for doc, _, _, _ in fixtures])
        self.assertTrue(all(entry['document']['scopes'][0]['form'] == FILM_FORM for entry in plan['documents']))
        changed_meds = [copy.deepcopy(med) for _, med, _, _ in fixtures]
        changed_meds[0]['variants'][0]['label_name'] = 'Изменена подпись одного из41 вариантов'
        blocked = plan_for([record(doc, med) for doc, med, _, _ in fixtures], changed_meds)
        self.assertEqual(len(blocked['rejected']), 1)
        with self.assertRaises(ImportConflict):
            apply_plan(SimpleNamespace(), blocked, validator=validate_original_document,
                       matcher=match_original_to_medication, allow_variant_form_evidence=True)

    def test_raw_label_only_mutation_rejects_preview_despite_unchanged_legacy_fingerprint(self):
        doc, med, _, _ = film_fixture()
        proposal = record(doc, med)
        changed = copy.deepcopy(med)
        changed['variants'][0]['label_name'] = changed['variants'][0]['label_name'].replace('пленочной ', '')
        self.assertEqual(medication_identity_fingerprint(med), medication_identity_fingerprint(changed))
        self.assertNotEqual(label_identity_digest(med), label_identity_digest(changed))
        plan = plan_for([proposal], [changed])
        self.assertEqual(len(plan['rejected']), 1)
        self.assertEqual(plan['bindings'], [])
        self.assertFalse(match_original_to_medication(doc, changed,
                         variant_form_evidence=proposal['variant_form_evidence'][0])['matched'])

    def test_variant_label_is_never_borrowed_from_med_or_synthesized(self):
        doc, med, _, _ = film_fixture()
        proof = proof_for(doc, med)
        med['label_name'] = med['variants'][0]['label_name']
        del med['variants'][0]['label_name']
        self.assertEqual(label_identity_digest(med), DISABLED)
        self.assertFalse(match_original_to_medication(doc, med, variant_form_evidence=proof)['matched'])

    def test_total_list_bound_precedes_scanning_even_with_one_generic_and129_nongeneric(self):
        doc, med, _, _ = film_fixture()
        proof = proof_for(doc, med, [med['variants'][0]])
        generic = copy.deepcopy(med['variants'][0])
        strict = copy.deepcopy(generic); strict.update(gtin='99900000000001', form=FILM_FORM)
        rows = [generic, strict]
        for index in range(128):
            other = copy.deepcopy(generic); other.update(gtin=str(90000000000000 + index), form='капсулы')
            rows.append(other)
        class NoIteration(list):
            def __iter__(self):
                raise AssertionError('optional path scanned an over-limit list')
        med['variants'] = NoIteration(rows)
        self.assertEqual(label_identity_digest(med), DISABLED)
        with self.assertRaisesRegex(ValueError, 'over bound'):
            eligible_variant_keys(doc, med, proof)
        med['variants'] = rows
        # The optional path is disabled, but the existing strict matcher still
        # accepts its one ordinary film-form variant.
        result = match_original_to_medication(doc, med, variant_form_evidence=proof)
        self.assertEqual(result['covered_variants'], 1)
        self.assertEqual(result['bindings'][0]['gtin'], strict['gtin'])

    def test_other_strengths_old_ru_and_longer_enteric_retard_labels_do_not_match(self):
        for index, changed_label in [(3, REAL_SCOPES[4]['variants'][0]['label_name']),
                                      (5, REAL_SCOPES[6]['variants'][0]['label_name']),
                                      (0, 'Эксхол Форте таблетки, покрытые пленочной оболочкой кишечнорастворимые, 500 мг'),
                                      (0, 'Эксхол Форте таблетки, покрытые пленочной оболочкой ретард, 500 мг'),
                                      (0, '<b>Эксхол Форте</b> таблетки, покрытые пленочной оболочкой, 500 мг')]:
            doc, med, _, _ = film_fixture(index)
            med['variants'][0]['label_name'] = changed_label
            proof = proof_for(doc, med)
            with self.subTest(label=changed_label):
                self.assertFalse(match_original_to_medication(doc, med, variant_form_evidence=proof)['matched'])
        doc, med, _, _ = film_fixture()
        proof = proof_for(doc, med)
        for key, value in [('ru_number', 'ЛП-003798'), ('gtin', '99900000000001'),
                            ('form', 'таблетки кишечнорастворимые'), ('dosage', '250 мг')]:
            changed = copy.deepcopy(med); changed['variants'][0][key] = value
            self.assertFalse(match_original_to_medication(doc, changed, variant_form_evidence=proof)['matched'])

    def test_source_pins_mode_unknown_fields_duplicate_identity_and_oversize_are_rejected(self):
        doc, med, _, _ = film_fixture()
        for change in ['document_sha256', 'original_sha256', 'grls_row_sha256', 'product_html_sha256',
                       'mode', 'extra', 'duplicate', 'oversize', 'wrong_esklp']:
            proof = proof_for(doc, med)
            if change.endswith('sha256'): proof[change] = '0' * 64
            elif change == 'mode': proof['mode'] = 'global_coating_alias'
            elif change == 'extra': proof['invented'] = True
            elif change == 'duplicate': proof['variants'].append(copy.deepcopy(proof['variants'][0]))
            elif change == 'oversize': proof['variants'][0]['label_name'] = 'a' * 1025
            else: proof['variants'][0]['esklp_code'] = 'other'
            with self.subTest(change=change), self.assertRaises(ValueError):
                eligible_variant_keys(doc, med, proof)
            self.assertFalse(match_original_to_medication(doc, med, variant_form_evidence=proof)['matched'])

    def test_changed_canonical_scope_version_and_noncanon_source_cannot_reuse_proof(self):
        doc, med, _, _ = film_fixture()
        proof = proof_for(doc, med)
        changed = copy.deepcopy(doc)
        changed['version'] += '-changed'
        changed['evidence']['visual_identity']['version'] = changed['version']
        changed = validate_original_document(changed)
        self.assertFalse(match_original_to_medication(changed, med, variant_form_evidence=proof)['matched'])
        for form, dose in [('таблетки кишечнорастворимые, покрытые пленочной оболочкой', '500 мг'),
                           (FILM_FORM, '0,2 мг')]:
            changed = copy.deepcopy(doc)
            changed['scopes'][0].update(form=form, dosage=dose)
            changed['evidence']['visual_identity']['fields']['form']['raw'] = form
            changed['evidence']['visual_identity']['fields']['dosage']['raw'] = dose
            grls = changed['evidence']['current_grls_registration']
            grls['release_forms'] = form + ', ' + dose + ', 10 шт.;'
            changed['evidence']['current_grls_registration_sha256'] = canonical_hash(grls)
            changed = validate_original_document(changed)
            with self.assertRaises(ValueError): eligible_variant_keys(changed, med, proof_for(changed, med))
        changed = copy.deepcopy(doc)
        changed['source'].update(provider='renewal', url='https://www.renewal.ru/products/synthetic/',
                                 pdf_url='https://www.renewal.ru/upload/iblock/synthetic/original.pdf')
        changed['evidence']['product_page'].update(url=changed['source']['url'], pdf_url=changed['source']['pdf_url'])
        changed = validate_original_document(changed)
        with self.assertRaises(ValueError): eligible_variant_keys(changed, med, proof_for(changed, med))

    def test_wrapper_requires_original_importer_and_retains_optional_proof(self):
        doc, med, _, _ = film_fixture()
        proposal = record(doc, med)
        self.assertEqual(len(build_plan([proposal], [med], validator=validate_original_document,
                         matcher=match_original_to_medication)['rejected']), 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.jsonl'
            path.write_text(json.dumps(proposal))
            loaded = load_documents(path)
            self.assertEqual(loaded[0]['variant_form_evidence'], proposal['variant_form_evidence'])
        absent = copy.deepcopy(proposal); absent['variant_form_evidence'][0]['medicine_slug'] = 'absent'
        self.assertEqual(len(plan_for([absent], [med])['rejected']), 1)


class FormEvidenceApplyTests(unittest.TestCase):
    def test_fresh_and_final_live_label_only_changes_block_apply_without_active_bindings(self):
        for mutate_at in (1, 2):
            doc, med, body, html = film_fixture()
            with self.subTest(mutate_at=mutate_at), tempfile.TemporaryDirectory() as directory:
                path = write_archive(Path(directory), doc, body, html)
                plan = plan_for([record(doc, med, path)], [med])
                database = SimpleNamespace(medications=Collection([med], read_only=True),
                    instruction_original_documents=Collection(), medication_original_bindings=Collection())
                namespace = OriginalCollections(database)
                def mutate(collection, count):
                    if count == mutate_at:
                        collection.rows[0]['variants'][0]['label_name'] = 'Изменена только подпись'
                database.medications.on_read = mutate
                with self.assertRaisesRegex(ImportConflict, 'variant-form'):
                    apply_plan(namespace, plan, validator=validate_original_document, matcher=match_original_to_medication,
                               archive_validator=validate_archive, allow_variant_form_evidence=True)
                self.assertEqual(medication_identity_fingerprint(med), medication_identity_fingerprint(database.medications.rows[0]))
                self.assertFalse(any(row.get('record_type') == 'binding' and row.get('active')
                                     for row in database.medication_original_bindings.rows))
                self.assertEqual(database.medications.writes, [])

    def test_valid_original_binding_evidence_persists_and_legacy_ids_do_not_gain_fields(self):
        doc, med, body, html = film_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = write_archive(Path(directory), doc, body, html)
            plan = plan_for([record(doc, med, path)], [med])
            database = SimpleNamespace(medications=Collection([med], read_only=True),
                instruction_original_documents=Collection(), medication_original_bindings=Collection())
            namespace = OriginalCollections(database)
            with self.assertRaises(ImportConflict):
                apply_plan(namespace, plan, validator=validate_original_document, matcher=match_original_to_medication)
            result = apply_plan(namespace, plan, validator=validate_original_document, matcher=match_original_to_medication,
                                archive_validator=validate_archive, allow_variant_form_evidence=True)
            self.assertEqual(result['added_bindings'], 1)
            stored = next(row for row in database.medication_original_bindings.rows if row.get('record_type') == 'binding')
            proof = stored['variant_form_evidence']
            self.assertEqual(stored['variant_form_evidence_sha256'], evidence_digest(proof))
            self.assertEqual(stored['binding_id'], form_binding_id(doc['id'], med['slug'], medication_identity_fingerprint(med),
                                                                  stored['variant_bindings'], proof))
            legacy = binding_id(doc['id'], med['slug'], medication_identity_fingerprint(med), stored['variant_bindings'])
            self.assertNotEqual(legacy, stored['binding_id'])


class FormEvidenceReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_old_binding_survives_its_unused_label_change(self):
        doc, med, _, _ = canon_fixture()
        doc = validate_original_document(doc)
        med['variants'][0]['label_name'] = 'Первоначальная подпись обычной строгой привязки'
        variants = match_original_to_medication(doc, med)['bindings']
        row = row_for(doc, med, variants)
        old_id = row['binding_id']
        db = SimpleNamespace(instruction_original_documents=AsyncCollection([doc]),
                             medication_original_bindings=AsyncCollection([row]))
        service = MedicationOriginalService(db)
        self.assertEqual((await service.attach(copy.deepcopy(med)))['instruction_original_coverage']['covered_variants'], 1)
        changed = copy.deepcopy(med)
        changed['variants'][0]['label_name'] = 'Другая подпись, на которую обычная привязка не опиралась'
        self.assertEqual(medication_identity_fingerprint(med), medication_identity_fingerprint(changed))
        self.assertEqual(row_for(doc, changed, variants)['binding_id'], old_id)
        self.assertEqual((await service.attach(changed))['instruction_original_coverage']['covered_variants'], 1)
        self.assertNotIn('variant_form_evidence', row)

    def mixed(self):
        doc, med, _, _ = film_fixture()
        proof = proof_for(doc, med, [med['variants'][0]])
        first = _variant(med, med['variants'][0]); second = _variant(med, med['variants'][1])
        strict = copy.deepcopy(med['variants'][0]); strict.update(gtin='99900000000001', form=FILM_FORM)
        strict.pop('label_name'); med['variants'].append(strict)
        rows = [row_for(doc, med, [first], proof), row_for(doc, med, [second]),
                row_for(doc, med, [_variant(med, strict)])]
        db = SimpleNamespace(instruction_original_documents=AsyncCollection([doc]),
                             medication_original_bindings=AsyncCollection(rows))
        return doc, med, rows, MedicationOriginalService(db)

    async def test_same_document_rows_cannot_borrow_proofs_and_label_mutation_invalidates_warm_cache(self):
        _, med, _, service = self.mixed()
        first = await service.attach(copy.deepcopy(med))
        self.assertEqual(first['instruction_original_coverage']['covered_variants'], 2)
        self.assertEqual(len(service.cache), 1)
        changed = copy.deepcopy(med)
        changed['variants'][0]['label_name'] = changed['variants'][0]['label_name'].replace('пленочной ', '')
        self.assertEqual(medication_identity_fingerprint(med), medication_identity_fingerprint(changed))
        second = await service.attach(changed)
        self.assertEqual(len(service.cache), 2)
        self.assertEqual(second['instruction_original_coverage']['covered_variants'], 1)
        self.assertEqual(second['instruction_originals'][0]['matched_variants'][0]['gtin'], '99900000000001')
        self.assertNotIn('variant_form_evidence', second['instruction_originals'][0])

    async def test_missing_bad_evidence_and_overflow_disable_only_fallback_preserving_strict(self):
        for mode in ('missing', 'digest', 'binding_id', 'unknown_mode', 'label_missing', 'overflow', 'nongeneric_overflow'):
            doc, med, rows, _ = self.mixed()
            if mode == 'missing': rows[0].pop('variant_form_evidence')
            elif mode == 'digest': rows[0]['variant_form_evidence_sha256'] = '0' * 64
            elif mode == 'binding_id': rows[0]['binding_id'] = '0' * 64
            elif mode == 'unknown_mode': rows[0]['variant_form_evidence']['mode'] = 'anything'
            elif mode == 'label_missing': med['variants'][0].pop('label_name')
            else:
                for index in range(130):
                    raw = copy.deepcopy(med['variants'][0]); raw['gtin'] = str(90000000000000 + index)
                    if mode == 'nongeneric_overflow':
                        raw['form'] = 'капсулы'
                    med['variants'].append(raw)
                self.assertEqual(label_identity_digest(med), DISABLED)
                for row in rows:
                    row['identity_fingerprint'] = medication_identity_fingerprint(med)
                    row['binding_id'] = binding_id(doc['id'], med['slug'], row['identity_fingerprint'],
                                                   row['variant_bindings'],
                                                   variant_form_evidence=row.get('variant_form_evidence'))
            db = SimpleNamespace(instruction_original_documents=AsyncCollection([doc]),
                                 medication_original_bindings=AsyncCollection(rows))
            with self.subTest(mode=mode):
                result = await MedicationOriginalService(db).attach(med)
                self.assertEqual(result['instruction_original_coverage']['covered_variants'], 1)
                self.assertEqual(result['instruction_originals'][0]['matched_variants'][0]['gtin'], '99900000000001')


if __name__ == '__main__':
    unittest.main()
