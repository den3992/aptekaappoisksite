"""Actual catalog labels with explicitly synthetic source/PDF fixture identities.

Tests authorize neither the retained real source documents nor publication.
They exercise optional per-row matching, both live-write checks and read/cache.
"""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.canon_variant_form_evidence import DISABLED, label_identity_digest
from api.eaeu_variant_form_evidence import (
    MODE, FILM_FORM, GENERIC_FORM, build_evidence, eligible_variant_keys,
    evidence_digest, reviewed_variant_facts,
)
from api.instruction_original_evidence import derive_identity_evidence
from api.instruction_original_structured_dose import PROOF_MODE as SOLID_MODE
from api.medication_instructions import _ru, _variant, _variant_key, medication_identity_fingerprint
from api.medication_original_pdfs import (
    MedicationOriginalService, canonical_hash, match_original_to_medication, validate_original_document,
)
from scripts.import_medication_instructions import (
    ImportConflict, apply_plan, binding_id, build_plan,
)
from scripts.import_medication_originals import OriginalCollections, validate_archive
from scripts.prepare_eaeu_original_pdfs import (
    OriginalPreparationError, prepare_candidate, prepare_corpus, VARIANT_FILM_MODE,
)
from test_instruction_import import Collection
from test_instruction_originals import AsyncCollection, fixture
from test_instruction_original_structured_dose import source as structured_source
from test_prepare_eaeu_original_pdfs import corpus_fixture, _registry_files


REAL = json.loads((Path(__file__).parent / 'fixtures/eaeu_variant_form_labels.json').read_text())['scopes']


def _refresh(doc, *, dosage_mode=SOLID_MODE):
    ev = doc['evidence']; snap = ev['registry_snapshot']; reg = snap['russian_registrations'][0]
    ev.update(derive_identity_evidence(snap, reg, doc['scopes'], doc['identity']['manufacturers'],
                                     ev['current_grls_registration'], dosage_proof_mode=dosage_mode))
    if dosage_mode is None:
        ev.pop('dosage_proof_mode', None)
    ev['registry_snapshot_sha256'] = canonical_hash(snap)
    return validate_original_document(doc)


def film_fixture(index=0, *, strengths=None):
    item = REAL[index]
    med = copy.deepcopy(item['medication'])
    doc, _, body = fixture()
    ru, name, maker = item['ru_number'], med['name'], med['manufacturer']
    doses = strengths or [item['source_dosage']]
    doc.update(id='synthetic-eaeu-film-' + str(index), registration_numbers=[ru],
               identity={'trade_name': name, 'manufacturers': [maker]},
               scopes=[{'ru_number': ru, 'form': FILM_FORM, 'dosage': d} for d in doses])
    ev = doc['evidence']; snap = ev['registry_snapshot']; reg = snap['russian_registrations'][0]
    snap.update(form=FILM_FORM, manufacturers=[maker])
    reg.update(registration_number=ru, trade_name=name)
    packages = []
    for dose in doses:
        package = structured_source()['package_dosages'][0]
        package['form'] = FILM_FORM
        details = package['dosage']
        details['dosageUnitDetails']['dosageUnitMeasure']['value'] = dose.split(' ')[0]
        details['substanceDetails'][0]['substanceMeasure'][0]['value'] = dose.split(' ')[0]
        packages.append(package)
    snap['package_dosages'] = packages
    grls = ev['current_grls_registration']
    grls.update(registration_number=ru, registration_key=_ru(ru), trade_name=name,
                release_forms='; '.join(FILM_FORM + ', ' + d + ', 10 шт.' for d in doses) + ';',
                production_stages='Производитель (готовой ЛФ),' + maker + ', Россия')
    return _refresh(doc), med, body


def proof_for(doc, med, *, dose=None, subset=None):
    scope = next(s for s in doc['scopes'] if dose is None or s['dosage'] == dose)
    proof = build_evidence(doc, med, {k: scope[k] for k in ('ru_number', 'form', 'dosage')})
    if subset is not None:
        proof['variants'] = [v for v in proof['variants'] if v['gtin'] in subset]
    return proof


def plan_for(records, meds):
    return build_plan(records, meds, validator=validate_original_document,
                      matcher=match_original_to_medication, allow_variant_form_evidence=True)


def record(doc, med, path=None):
    row = {'document': doc, 'variant_form_evidence': [proof_for(doc, med)]}
    if path is not None:
        row['original_file'] = str(path)
    return row


def row_for(doc, med, variants, proof=None):
    fp = medication_identity_fingerprint(med)
    row = {'document_id': doc['id'], 'medicine_slug': med['slug'], 'record_type': 'binding',
           'status': 'verified', 'active': True, 'identity_fingerprint': fp, 'variant_bindings': variants}
    row['binding_id'] = binding_id(doc['id'], med['slug'], fp, variants, variant_form_evidence=proof)
    if proof is not None:
        row.update(variant_form_evidence=proof, variant_form_evidence_sha256=evidence_digest(proof))
    return row


def test_all_real53_scope_labels_124_variants_keep_source_scopes_and_require_optin():
    keys, source_keys = set(), set()
    for index, item in enumerate(REAL):
        doc, med, _ = film_fixture(index)
        before = canonical_hash(doc)
        assert not match_original_to_medication(doc, med)['matched']
        proof = proof_for(doc, med)
        result = match_original_to_medication(doc, med, variant_form_evidence=proof)
        actual = {(v['gtin'], _ru(v['ru_number'])) for v in result['bindings']}
        assert actual == {(v['gtin'], _ru(v['ru_number'])) for v in item['expected_GTIN_RU']}
        keys.update((med['slug'], *k) for k in actual)
        source_keys.add(item['candidate_key'])
        assert doc['scopes'][0]['form'] == FILM_FORM
        assert all(_ru(v['ru_number']) == doc['scopes'][0]['ru_number'] for v in result['bindings'])
        assert all(v['form'] == med['form'] for v in result['bindings'])
        assert before == canonical_hash(doc)
        assert 'variant_form_evidence' not in doc
    assert (len(REAL), len(source_keys), len(keys)) == (53, 30, 124)


@pytest.mark.parametrize('name_separator', [' ', ', '])
@pytest.mark.parametrize('dose_separator', [' ', ', '])
def test_exact_four_observed_whole_label_delimiters_only(name_separator, dose_separator):
    doc, med, _ = film_fixture()
    for raw in med['variants']:
        raw['label_name'] = med['name'] + name_separator + FILM_FORM + dose_separator + med['dosage']
    assert match_original_to_medication(doc, med, variant_form_evidence=proof_for(doc, med))['matched']


@pytest.mark.parametrize('suffix', [' ретард', ' кишечнорастворимые', ' 20 шт.', ' производитель Пример', ' плюс'])
def test_suffixes_are_not_discarded(suffix):
    doc, med, _ = film_fixture()
    for raw in med['variants']:
        raw['label_name'] += suffix
    with pytest.raises(ValueError, match='complete literal'):
        proof_for(doc, med)


@pytest.mark.parametrize('change', ['label', 'gtin', 'ru_number', 'dosage', 'form', 'esklp_code', 'duplicate', 'no_label'])
def test_raw_variant_mutations_never_borrow_med_label_or_other_variant(change):
    doc, med, _ = film_fixture()
    proof = proof_for(doc, med)
    fingerprint = medication_identity_fingerprint(med)
    raw = med['variants'][0]
    if change == 'label': raw['label_name'] += ' 20 шт.'
    elif change == 'gtin': raw['gtin'] = '99900000000001'
    elif change == 'ru_number': raw['ru_number'] = 'ЛП-004551'
    elif change == 'dosage': raw['dosage'] = '999 мг'
    elif change == 'form': raw['form'] = 'таблетки кишечнорастворимые'
    elif change == 'esklp_code': raw['esklp_code'] = 'changed'
    elif change == 'duplicate': med['variants'].append(copy.deepcopy(raw))
    else: med['label_name'] = raw.pop('label_name')
    with pytest.raises(ValueError): eligible_variant_keys(doc, med, proof)
    assert not match_original_to_medication(doc, med, variant_form_evidence=proof)['matched']
    if change in ('label', 'esklp_code', 'no_label'):
        assert fingerprint == medication_identity_fingerprint(med)


@pytest.mark.parametrize('field', ['document_sha256', 'original_sha256', 'grls_row_sha256',
                                 'source_registry_snapshot_sha256', 'source_metadata_sha256'])
def test_each_independent_source_pin_is_required(field):
    doc, med, _ = film_fixture(); proof = proof_for(doc, med)
    proof[field] = '0' * 64
    with pytest.raises(ValueError): eligible_variant_keys(doc, med, proof)


@pytest.mark.parametrize('dose', ['0 мг', '0,2 мг', '25 мг+5 мг', '25 мг/мл', '~', '025 мг', '25 г'])
def test_no_extra_dose_types_or_conversions(dose):
    doc, med, _ = film_fixture(); proof = proof_for(doc, med)
    proof['source_scope']['dosage'] = dose
    with pytest.raises(ValueError): eligible_variant_keys(doc, med, proof)


def test_actual_scope_selection_cannot_borrow_another_strength_or_version():
    doc, med, _ = film_fixture(strengths=['200 мг', '400 мг'])
    proof = proof_for(doc, med, dose='200 мг')
    assert eligible_variant_keys(doc, med, proof)
    proof['source_scope']['dosage'] = '400 мг'
    with pytest.raises(ValueError): eligible_variant_keys(doc, med, proof)
    proof = proof_for(doc, med, dose='200 мг')
    changed = copy.deepcopy(doc); changed['version'] += '-changed'
    with pytest.raises(ValueError): eligible_variant_keys(changed, med, proof)


def test_literal_only_dose_profile_cannot_silently_intersect_new_label_mode():
    doc, med, _ = film_fixture()
    active = doc['evidence']['registry_snapshot']['package_dosages'][0]['dosage']['substanceDetails'][0]
    active['substanceText'] = med['dosage']
    literal = _refresh(doc, dosage_mode=None)
    with pytest.raises(ValueError, match='solid-dose profile'): proof_for(literal, med)


def test_even_previously_reviewed_multiple_versions_do_not_enable_new_film_profile():
    doc, med, _ = film_fixture()
    snap = doc['evidence']['registry_snapshot']
    other = copy.deepcopy(snap['russian_registrations'][0]['documents'][0])
    other['uploaded_file_path'] = 'example/other-reviewed.pdf'
    snap['russian_registrations'][0]['documents'].append(other)
    doc['evidence']['document_version_selection'] = 'independently_reviewed'
    doc = _refresh(doc)
    with pytest.raises(ValueError, match='same verified source'): proof_for(doc, med)


def test_total_bound_checked_before_any_iteration_and_ordinary_strict_survives():
    doc, med, _ = film_fixture(); proof = proof_for(doc, med)
    strict = copy.deepcopy(med['variants'][0]); strict.update(gtin='99900000000001', form=FILM_FORM)
    extras = [{**strict, 'gtin': str(90000000000000+i), 'form': 'капсулы'} for i in range(129)]
    class NoIteration(list):
        def __iter__(self): raise AssertionError('unbounded optional scan')
    med['variants'] = NoIteration([med['variants'][0], strict] + extras)
    assert label_identity_digest(med) == DISABLED
    with pytest.raises(ValueError, match='over bound'): eligible_variant_keys(doc, med, proof)
    med['variants'] = list.__getitem__(med['variants'], slice(None))
    result = match_original_to_medication(doc, med, variant_form_evidence=proof)
    assert [v['gtin'] for v in result['bindings']] == [strict['gtin']]


@pytest.mark.parametrize('mutation', ['unknown_mode', 'unknown_key', 'scope_extra', 'duplicate', 'oversize', 'bad_digest'])
def test_optional_schema_and_utf8_bounds(mutation):
    doc, med, _ = film_fixture(); proof = proof_for(doc, med)
    if mutation == 'unknown_mode': proof['mode'] = 'global_coated_alias'
    elif mutation == 'unknown_key': proof['new'] = True
    elif mutation == 'scope_extra': proof['source_scope']['gtin'] = None
    elif mutation == 'duplicate': proof['variants'].append(copy.deepcopy(proof['variants'][0]))
    elif mutation == 'oversize': proof['variants'][0]['label_name'] = 'я' * 513
    else: proof['variants'][0]['label_sha256'] = '0' * 64
    with pytest.raises(ValueError): eligible_variant_keys(doc, med, proof)


@pytest.mark.parametrize('mutate_at', [1, 2])
def test_fresh_and_final_apply_check_literal_label_again_with_legacy_fingerprint_unchanged(tmp_path, mutate_at):
    doc, med, body = film_fixture(); path = tmp_path / 'original.pdf'; path.write_bytes(body)
    plan = plan_for([record(doc, med, path)], [med])
    assert not plan['rejected']
    db = SimpleNamespace(medications=Collection([med], read_only=True),
                         instruction_original_documents=Collection(), medication_original_bindings=Collection())
    def mutate(collection, count):
        if count == mutate_at: collection.rows[0]['variants'][0]['label_name'] += ' 20 шт.'
    db.medications.on_read = mutate
    with pytest.raises(ImportConflict, match='variant-form'):
        apply_plan(OriginalCollections(db), plan, validator=validate_original_document,
                   matcher=match_original_to_medication, archive_validator=validate_archive,
                   allow_variant_form_evidence=True)
    assert medication_identity_fingerprint(med) == medication_identity_fingerprint(db.medications.rows[0])
    assert not any(r.get('record_type') == 'binding' and r.get('active') for r in db.medication_original_bindings.rows)
    assert not db.medications.writes


def test_same_document_row_isolation_warm_cache_label_invalidation_and_strict_independence():
    # Scope0 in the retained fixture has multiple actual variants.
    doc, med, _ = film_fixture()
    assert len(med['variants']) >= 2
    proof = proof_for(doc, med, subset={med['variants'][0]['gtin']})
    strict = copy.deepcopy(med['variants'][0]); strict.update(gtin='99900000000001', form=FILM_FORM)
    strict.pop('label_name'); med['variants'].append(strict)
    rows = [row_for(doc, med, [_variant(med, med['variants'][0])], proof),
            row_for(doc, med, [_variant(med, med['variants'][1])]),
            row_for(doc, med, [_variant(med, strict)])]
    db = SimpleNamespace(instruction_original_documents=AsyncCollection([doc]),
                         medication_original_bindings=AsyncCollection(rows))
    service = MedicationOriginalService(db)
    assert asyncio.run(service.attach(copy.deepcopy(med)))['instruction_original_coverage']['covered_variants'] == 2
    changed = copy.deepcopy(med); changed['variants'][0]['label_name'] += ' 20 шт.'
    assert medication_identity_fingerprint(changed) == medication_identity_fingerprint(med)
    after = asyncio.run(service.attach(changed))
    assert len(service.cache) == 2
    assert [v['gtin'] for v in after['instruction_originals'][0]['matched_variants']] == [strict['gtin']]


@pytest.mark.parametrize('problem', ['missing', 'digest', 'binding_id', 'mode', 'overflow'])
def test_missing_malformed_overflow_proofs_disable_only_new_fallback(problem):
    doc, med, _ = film_fixture(); proof = proof_for(doc, med)
    strict = copy.deepcopy(med['variants'][0]); strict.update(gtin='99900000000001', form=FILM_FORM)
    strict.pop('label_name'); med['variants'].append(strict)
    row = row_for(doc, med, match_original_to_medication(doc, med, variant_form_evidence=proof)['bindings'], proof)
    if problem == 'missing': row.pop('variant_form_evidence')
    elif problem == 'digest': row['variant_form_evidence_sha256'] = '0' * 64
    elif problem == 'binding_id': row['binding_id'] = '0' * 64
    elif problem == 'mode': row['variant_form_evidence']['mode'] = 'global_alias'
    else:
        med['variants'].extend([{**strict, 'gtin': str(90000000000000+i), 'form': 'капсулы'} for i in range(129)])
        row['identity_fingerprint'] = medication_identity_fingerprint(med)
        row['binding_id'] = binding_id(doc['id'], med['slug'], row['identity_fingerprint'], row['variant_bindings'], variant_form_evidence=proof)
    db = SimpleNamespace(instruction_original_documents=AsyncCollection([doc]),
                         medication_original_bindings=AsyncCollection([row]))
    after = asyncio.run(MedicationOriginalService(db).attach(med))
    assert [v['gtin'] for v in after['instruction_originals'][0]['matched_variants']] == [strict['gtin']]


def test_preparer_optin_creates_separate_proofs_and_does_not_rewrite_med_or_source(tmp_path):
    folder, source_proof, grls, med = corpus_fixture(tmp_path)
    snap = source_proof['candidate']['source']; snap['form'] = FILM_FORM
    package = structured_source()['package_dosages'][0]; package['form'] = FILM_FORM
    snap['package_dosages'] = [package]
    med['form'] = GENERIC_FORM
    med['variants'][0]['label_name'] = med['name'] + ', ' + FILM_FORM + ', 25 мг'
    grls['release_forms'] = FILM_FORM + ', 25 мг, 20 шт.;'
    source_proof_before, med_before = copy.deepcopy(source_proof), copy.deepcopy(med)
    with pytest.raises(OriginalPreparationError):
        prepare_candidate(source_proof, folder, [med], [grls], dosage_proof_mode=SOLID_MODE)
    wrapper, preview = prepare_candidate(source_proof, folder, [med], [grls],
        dosage_proof_mode=SOLID_MODE, variant_form_proof_mode=VARIANT_FILM_MODE)
    assert wrapper['document']['scopes'][0]['form'] == FILM_FORM
    assert wrapper['variant_form_evidence'][0]['mode'] == MODE
    assert 'variant_form_evidence' not in wrapper['document']
    assert preview['matches'][0]['covered_variants'] == 1
    assert med == med_before and source_proof == source_proof_before
    planned = plan_for([wrapper], [med])
    assert not planned['rejected'] and len(planned['bindings']) == 1
    assert len(build_plan([wrapper], [med], validator=validate_original_document,
                         matcher=match_original_to_medication)['rejected']) == 1


@pytest.mark.parametrize('manufacturer_mode,dosage_mode', [(None, None), (None, 'eaeu_structured_mg_per_ml_v1'),
                                                         ('eaeu_ozon_ooo_prefix_v1', SOLID_MODE)])
def test_preparer_rejects_unreviewed_profile_intersections_before_reading_sources(manufacturer_mode, dosage_mode):
    with pytest.raises(OriginalPreparationError, match='film labels require'):
        prepare_candidate({}, '/no-read', [], [], manufacturer_proof_mode=manufacturer_mode,
                          dosage_proof_mode=dosage_mode, variant_form_proof_mode=VARIANT_FILM_MODE)


@pytest.mark.parametrize('mutation', ['none', 'selected_review_flag', 'changed_form', 'duplicate_RU'])
def test_full_registry_current_snapshot_guard_is_required_even_without_paired_maker(tmp_path, mutation):
    folder, proof, grls, med = corpus_fixture(tmp_path)
    snap = proof['candidate']['source']; snap['form'] = FILM_FORM
    package = structured_source()['package_dosages'][0]; package['form'] = FILM_FORM
    snap['package_dosages'] = [package]
    med['form'] = GENERIC_FORM
    med['variants'][0]['label_name'] = med['name'] + ' ' + FILM_FORM + ', 25 мг'
    grls['release_forms'] = FILM_FORM + ', 25 мг, 20 шт.;'
    (folder / 'source-proof.json').write_text(json.dumps(proof, ensure_ascii=False))
    source_before = (folder / 'source-proof.json').read_bytes()
    current = copy.deepcopy(snap); current['manufacturer_entities'] = []
    if mutation == 'selected_review_flag':
        current['russian_registrations'][0]['documents'][0]['review_flags'] = ['review_required']
    elif mutation == 'changed_form': current['form'] = 'капсулы'
    records = [current]
    if mutation == 'duplicate_RU':
        other = copy.deepcopy(current); other['record_id'] = 'f' * 24; records.append(other)
    index, validation = _registry_files(tmp_path, records)
    catalog, grls_index = tmp_path/'catalog.jsonl', tmp_path/'grls.jsonl'
    catalog.write_text(json.dumps({'medication': med}, ensure_ascii=False)+'\n')
    grls_index.write_text(json.dumps(grls, ensure_ascii=False)+'\n')
    output = tmp_path/'output.jsonl'
    report = prepare_corpus(folder.parent, catalog, grls_index, output, tmp_path/'rejected.jsonl',
        registry_index_path=index, registry_validation_path=validation,
        dosage_proof_mode=SOLID_MODE, variant_form_proof_mode=VARIANT_FILM_MODE)
    assert (folder/'source-proof.json').read_bytes() == source_before
    if mutation == 'none':
        assert report['counts']['verified_original_documents'] == 1
        doc = json.loads(output.read_text())['document']
        assert doc['evidence']['registry_snapshot'] == current
        assert report['variant_form_proof_mode'] == MODE
    else:
        assert report['counts']['rejected_or_needs_review'] == 1
        assert output.read_bytes() == b''
