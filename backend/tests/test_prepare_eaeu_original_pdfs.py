import copy
import hashlib
import json

from pypdf import PdfWriter
from pypdf.generic import (ArrayObject, ByteStringObject, ContentStream, DictionaryObject,
                           NameObject, NumberObject)
import pytest

from scripts.prepare_eaeu_original_pdfs import OriginalPreparationError, prepare_candidate, prepare_corpus
from test_instruction_original_evidence import original_document, original_medication


def _write_pdf(path, text, *, missing_image=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    if text:
        # A real, self-contained embedded text layer. No unbound .txt heading.
        chars = list(dict.fromkeys(text))
        codes = {char: index + 1 for index, char in enumerate(chars)}
        differences = ArrayObject([NumberObject(1)] + [NameObject('/uni%04X' % ord(c)) for c in chars])
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica'),
            NameObject('/Encoding'): DictionaryObject({NameObject('/Type'): NameObject('/Encoding'),
                NameObject('/BaseEncoding'): NameObject('/WinAnsiEncoding'), NameObject('/Differences'): differences})})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        contents = ContentStream(None, writer)
        contents.operations = [([], b'BT'), ([NameObject('/F1'), NumberObject(12)], b'Tf'),
            ([NumberObject(10), NumberObject(100)], b'Td'),
            ([ByteStringObject(bytes(codes[c] for c in text))], b'Tj'), ([], b'ET')]
        if missing_image:
            contents.operations.append(([NameObject('/MissingImage')], b'Do'))
        page[NameObject('/Contents')] = writer._add_object(contents)
    with path.open('wb') as handle:
        writer.write(handle)
    return path.read_bytes()


def _replace_original(folder, proof, text, **kwargs):
    binary = _write_pdf(folder / 'original.pdf', text, **kwargs)
    proof['candidate']['document']['size'] = len(binary)
    proof['download'].update(sha256=hashlib.sha256(binary).hexdigest(), bytes=len(binary))


def corpus_fixture(tmp_path):
    doc = original_document()
    folder = tmp_path / 'corpus' / 'synthetic-candidate'
    folder.mkdir(parents=True)
    binary = _write_pdf(folder / 'original.pdf', 'ИНСТРУКЦИЯ ПО МЕДИЦИНСКОМУ ПРИМЕНЕНИЮ')
    snapshot = doc['evidence']['registry_snapshot']
    registration = snapshot['russian_registrations'][0]
    attachment = registration['documents'][0]
    attachment['size'] = len(binary)
    snapshot['source_url'] = doc['source']['url']
    (folder / 'embedded-text.txt').write_text('ИНСТРУКЦИЯ ПО МЕДИЦИНСКОМУ ПРИМЕНЕНИЮ\nСинтетический fixture')
    proof = {'candidate': {'candidate_key': folder.name, 'source': snapshot,
                           'registration': registration, 'document': attachment},
             'download': {'sha256': hashlib.sha256(binary).hexdigest(), 'bytes': len(binary)}}
    (folder / 'source-proof.json').write_text(json.dumps(proof, ensure_ascii=False))
    grls = doc['evidence']['current_grls_registration']
    return folder, proof, grls, original_medication()


def test_exact_offline_original_binds_without_inline_text_claim(tmp_path):
    folder, proof, grls, med = corpus_fixture(tmp_path)
    wrapper, preview = prepare_candidate(proof, folder, [med], [grls])
    doc = wrapper['document']
    assert doc['content_format'] == 'official_original_pdf'
    assert not doc.get('sections')
    assert doc['completeness']['inline_text_verified'] is False
    assert preview['matches'][0]['covered_variants'] == 1
    assert doc['evidence']['scope_evidence'][0]['source_active_substance_text'] == '25 мг'


@pytest.mark.parametrize('problem', ['wrong_dose', 'foreign_manufacturer', 'multiple_usage',
                                  'hash_mismatch', 'truncated_pdf', 'project',
                                  'scan_type_unknown', 'inactive_grls'])
def test_fail_closed_original_needs_review(tmp_path, problem):
    folder, proof, grls, med = corpus_fixture(tmp_path)
    if problem == 'wrong_dose':
        med['dosage'] = '250 мг'
    elif problem == 'foreign_manufacturer':
        med['manufacturer'] = 'АО Чужой'
    elif problem == 'multiple_usage':
        proof['candidate']['registration']['documents'].append(copy.deepcopy(proof['candidate']['document']))
    elif problem == 'hash_mismatch':
        proof['download']['sha256'] = '0' * 64
    elif problem == 'truncated_pdf':
        (folder / 'original.pdf').write_bytes((folder / 'original.pdf').read_bytes()[:-20])
    elif problem == 'project':
        _replace_original(folder, proof, 'Проект инструкции по медицинскому применению')
    elif problem == 'scan_type_unknown':
        _replace_original(folder, proof, '')
    else:
        grls['source_status_book'] = 'Недействующий'
    with pytest.raises((OriginalPreparationError, ValueError)):
        prepare_candidate(proof, folder, [med], [grls])


def test_corpus_separates_verified_originals_from_rejections(tmp_path):
    folder, proof, grls, med = corpus_fixture(tmp_path)
    bad_folder = folder.parent / 'bad-candidate'
    bad_folder.mkdir()
    (bad_folder / 'source-proof.json').write_text('{}')
    catalog_path, grls_path = tmp_path / 'catalog.jsonl', tmp_path / 'grls.jsonl'
    catalog_path.write_text(json.dumps({'medication': med}, ensure_ascii=False) + '\n')
    grls_path.write_text(json.dumps(grls, ensure_ascii=False) + '\n')
    report = prepare_corpus(folder.parent, catalog_path, grls_path, tmp_path / 'verified.jsonl', tmp_path / 'drafts.jsonl')
    assert report['counts']['verified_original_documents'] == 1
    assert report['counts']['rejected_or_needs_review'] == 1
    assert report['covered_cards'] == report['covered_variants'] == 1
    assert report['network_requests'] == report['database_writes'] == 0
    assert json.loads((tmp_path / 'drafts.jsonl').read_text())['status'] == 'draft_needs_review'


def test_stale_heading_sidecar_does_not_approve_blank_pdf(tmp_path):
    folder, proof, grls, med = corpus_fixture(tmp_path)
    _replace_original(folder, proof, '')
    # The fixture's sidecar still contains an instruction heading.
    with pytest.raises(OriginalPreparationError, match='actual document type'):
        prepare_candidate(proof, folder, [med], [grls])


def test_broken_nested_resource_is_rejected_before_wrapper(tmp_path):
    folder, proof, grls, med = corpus_fixture(tmp_path)
    _replace_original(folder, proof, 'ИНСТРУКЦИЯ ПО МЕДИЦИНСКОМУ ПРИМЕНЕНИЮ', missing_image=True)
    with pytest.raises(OriginalPreparationError, match='bounded strict PDF'):
        prepare_candidate(proof, folder, [med], [grls])


def test_repeat_generation_keeps_immutable_id_and_payload(tmp_path):
    folder, proof, grls, med = corpus_fixture(tmp_path)
    first, _ = prepare_candidate(proof, folder, [med], [grls], checked_at='2026-01-01T00:00:00Z')
    second, _ = prepare_candidate(proof, folder, [med], [grls], checked_at='2026-01-02T00:00:00Z')
    assert first == second
    # An actual primary-evidence version change gets a new immutable ID.
    grls['row'] = 3
    third, _ = prepare_candidate(proof, folder, [med], [grls], checked_at='2026-01-02T00:00:00Z')
    assert third['document']['id'] != first['document']['id']
