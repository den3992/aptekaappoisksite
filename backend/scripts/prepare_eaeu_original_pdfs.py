#!/usr/bin/env python3
"""Prepare exact, source-proven whole-PDF wrappers from an offline EAEU corpus.

No network, DB writes, OCR approval, unit conversion or clinical-text generation.
The downloaded corpus, catalog and current GRLS export remain unchanged. Unclear
identities, project documents, multiple current attachments and malformed PDFs
are written to a separate rejection report for review.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from api.instruction_original_evidence import derive_identity_evidence, validate_identity_evidence
from api.medication_instructions import _identity, _ru
from api.medication_original_pdfs import (
    MAX_PAGES, MAX_PDF_BYTES, canonical_hash, match_original_to_medication,
    validate_original_document,
)
from scripts.sources.renewal_instructions import _worker_rss_kib


class OriginalPreparationError(ValueError):
    pass


def _read_jsonl(path):
    with Path(path).open() as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as error:
                    raise OriginalPreparationError(f'invalid JSONL row {number}') from error


def check_original_pdf(path, attachment, expected_sha256):
    """Validate the entire original binary, without modifying or OCRing it."""
    path = Path(path)
    size = path.stat().st_size
    if not 20 <= size <= MAX_PDF_BYTES or type(attachment.get('size')) is not int or attachment['size'] != size:
        raise OriginalPreparationError('original byte size is absent, unequal or outside bounds')
    started = time.monotonic()
    child = subprocess.Popen([sys.executable, '-m', 'scripts.check_instruction_original_pdf', str(path)],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    reason = None
    try:
        while child.poll() is None:
            rss = _worker_rss_kib(child.pid)
            if rss is None and child.poll() is None:
                reason = 'PDF validation memory monitor unavailable'
            elif rss is not None and rss > 512 * 1024:
                reason = 'PDF validation memory bound exceeded'
            elif time.monotonic() - started > 30:
                reason = 'PDF validation deadline exceeded'
            if reason:
                child.kill()
                break
            time.sleep(0.02)
        stdout, _ = child.communicate(timeout=3)
        if reason or child.returncode or len(stdout) > 4096:
            raise OriginalPreparationError(reason or 'retained original failed bounded strict PDF validation')
        result = json.loads(stdout)
        if (result.get('original_sha256') != expected_sha256 or result.get('original_bytes') != size
                or result.get('all_pages_resolved') is not True or result.get('encrypted') is not False
                or type(result.get('page_count')) is not int or not 1 <= result['page_count'] <= MAX_PAGES):
            raise OriginalPreparationError('original differs from retained download proof or PDF structural bounds')
        return {'sha256': result['original_sha256'], 'bytes': size, 'page_count': result['page_count'],
                'header_document_type': result.get('header_document_type'),
                'header_has_project_marker': result.get('header_has_project_marker'),
                'binary_validation': {**result, 'strict_pdf_parser': True,
                    'nested_resources_checked': True, 'cpu_bound_seconds': 20,
                    'rss_bound_bytes': 512 * 1024 * 1024, 'deadline_seconds': 30,
                    'declared_and_actual_bytes_equal': True, 'clinical_text_verified': False}}
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def _document_type(binary, attachment):
    # PDF metadata confirms USAGE_INSTRUCTION, but not whether the actual
    # document is an old-format instruction or a patient leaflet. Require a
    # literal embedded heading; scanned documents need separate manual proof.
    source_name = str(attachment.get('name') or '').casefold()
    if (binary.get('header_has_project_marker') is not False
            or re.search(r'\b(?:проект|draft)\b', source_name)):
        raise OriginalPreparationError('document has a project/draft marker')
    if binary.get('header_document_type') in {'patient_leaflet', 'medical_instruction'}:
        return binary['header_document_type']
    raise OriginalPreparationError('actual document type requires manual identity review')


def prepare_candidate(proof, folder, medications, grls_rows, *, checked_at=None):
    """Return one validated immutable-original wrapper and exact match evidence."""
    folder = Path(folder)
    candidate = proof.get('candidate') or {}
    snapshot, selected = candidate.get('source') or {}, candidate.get('document') or {}
    registration_number = (candidate.get('registration') or {}).get('registration_number')
    ru_key = _ru(registration_number)
    matching = [r for r in snapshot.get('russian_registrations') or []
                if _ru(r.get('registration_number')) == ru_key]
    if not ru_key or len(matching) != 1:
        raise OriginalPreparationError('exact source Russian registration is ambiguous')
    registration = matching[0]
    if (registration.get('country') != 'RU' or registration.get('registration_status_code') != '03'
            or registration.get('cancelled_at')):
        raise OriginalPreparationError('source registration is not current Russian registration')
    usages = [d for d in registration.get('documents') or [] if d.get('kind') == 'USAGE_INSTRUCTION']
    if len(usages) != 1 or usages[0] != selected or selected.get('review_flags'):
        raise OriginalPreparationError('current instruction version/path requires independent selection')
    rows = [r for r in grls_rows if r.get('source_status_book') == 'Действующий' and not r.get('cancelled_at')]
    if len(rows) != 1:
        raise OriginalPreparationError('exact current GRLS registration row is absent or ambiguous')
    grls = rows[0]
    binary = check_original_pdf(folder / 'original.pdf', selected, (proof.get('download') or {}).get('sha256'))
    profile = _document_type(binary, selected)
    source_names = snapshot.get('manufacturers') or []
    if not source_names:
        raise OriginalPreparationError('explicit finished-product manufacturer is absent')

    scopes, manufacturers, eligible_meds, rejected_targets = [], [], [], []
    for med in medications:
        if (_identity(med.get('name')) != _identity(registration.get('trade_name'))
                or not med.get('slug') or med.get('is_canonical') is False):
            rejected_targets.append({'slug': med.get('slug'), 'reason': 'exact canonical trade name differs'})
            continue
        if not any(_ru(v.get('ru_number') or med.get('ru_number')) == ru_key for v in med.get('variants') or []):
            continue
        scope = {'ru_number': registration_number, 'form': med.get('form'), 'dosage': med.get('dosage')}
        proven_names = None
        last_reason = 'no proven literal manufacturer identity'
        for source_name in source_names:
            names = list(dict.fromkeys([med.get('manufacturer'), source_name]))
            try:
                derive_identity_evidence(snapshot, registration, [scope], names, grls)
                proven_names = names
                break
            except ValueError as error:
                last_reason = str(error)
        if proven_names is None:
            rejected_targets.append({'slug': med['slug'], 'reason': last_reason})
            continue
        if scope not in scopes:
            scopes.append(scope)
        manufacturers.extend(v for v in proven_names if v not in manufacturers)
        eligible_meds.append(med)
    if not eligible_meds:
        raise OriginalPreparationError('no exact source/GRLS/catalog tuple: ' +
                                       '; '.join(sorted({v['reason'] for v in rejected_targets}))[:1000])

    scopes.sort(key=lambda v: (_ru(v['ru_number']), v['form'], v['dosage']))
    manufacturers.sort()
    version_fingerprint = canonical_hash({'snapshot_sha256': canonical_hash(snapshot),
        'grls_row_sha256': canonical_hash(grls), 'original_sha256': binary['sha256'],
        'registration_number': ru_key, 'document_type': profile,
        'scopes': scopes, 'manufacturers': manufacturers})
    checkpoint_path = folder / 'official-original-verification.json'
    checkpoint = json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {'versions': {}}
    previous = (checkpoint.get('versions') or {}).get(version_fingerprint)
    now = previous or checked_at or datetime.now(timezone.utc).isoformat()
    sha, oid = binary['sha256'], snapshot['record_id']
    evidence = {
        'registry_snapshot': snapshot, 'registry_snapshot_sha256': canonical_hash(snapshot),
        'original_sha256': sha, 'full_pdf_checked': True, 'not_unapproved_project': True,
        'finished_manufacturer_confirmed': True, 'checked_at': now,
        'identity_review': 'Точные текущее российское РУ, торговое наименование, форма и буквальная дозировка сопоставлены между снимком ЕАЭС, действующей строкой ГРЛС и карточкой. Каждый юридический вариант имени производителя имеет отдельное воспроизводимое первичное доказательство; роль готового производителя взята только из явной стадии ЕАЭС.',
        'document_version_review': 'Для точного действующего российского РУ снимок официального реестра содержит единственное вложение USAGE_INSTRUCTION с этим фактическим uploadedFile.path. Отметки проекта в метаданных и извлечённом заголовке отсутствуют. Исходный PDF сохранён целиком с проверкой всех страниц, размера и SHA256. Дата загрузки и дата нормативной документации не объявлялись датой клинической ревизии.',
        'binary_validation': binary['binary_validation'],
        'current_ru_document': {'registration_number': registration_number,
            'record_id': oid, 'source_version': snapshot.get('source_version'),
            'usage_instruction_count': 1, 'uploaded_file_path': selected['uploaded_file_path'],
            'uploaded_at': selected.get('uploaded_at'), 'source_document_name': selected.get('name')},
        'inline_text_verified': False, 'ocr_text_published': False,
        'preparation_version_fingerprint': version_fingerprint,
    }
    evidence.update(derive_identity_evidence(snapshot, registration, scopes, manufacturers, grls))
    document = {
        'id': 'eaeu-pdf-' + oid + '-' + sha[:16] + '-' + version_fingerprint[:12],
        'title': registration['trade_name'] + ' — официальный оригинал инструкции',
        'document_type': profile, 'content_format': 'official_original_pdf',
        'registration_numbers': [registration_number],
        'source': {'name': 'Единый реестр зарегистрированных лекарственных средств ЕАЭС',
            'url': snapshot['source_url'], 'kind': 'official_registry', 'provider': 'eaeu',
            'record_id': oid, 'uploaded_file_path': selected['uploaded_file_path'],
            'metadata_sha256': snapshot['metadata_sha256']},
        'version': 'Текущий USAGE_INSTRUCTION снимка ЕАЭС; версия записи ' + str(snapshot.get('source_version')) + '; SHA-256 ' + sha,
        'approved_at': None,
        'retrieved_at': datetime.fromtimestamp((folder / 'original.pdf').stat().st_mtime, timezone.utc).isoformat(),
        'original_sha256': sha, 'original_bytes': binary['bytes'], 'page_count': binary['page_count'],
        'identity': {'trade_name': registration['trade_name'], 'manufacturers': manufacturers},
        'scopes': scopes,
        'verification': {'status': 'verified', 'verified_at': now,
            'verified_by': 'offline exact EAEU-current-GRLS original proof',
            'method': 'literal_primary_identity_and_complete_immutable_original; no inline text approval'},
        'evidence': evidence,
    }
    validate_identity_evidence(document, snapshot, registration, scopes, manufacturers)
    document = validate_original_document(document)
    matches = []
    for med in eligible_meds:
        match = match_original_to_medication(document, med)
        if not match['matched']:
            raise OriginalPreparationError('validated source tuple did not bind its exact catalog variant')
        matches.append({'slug': med['slug'], 'covered_variants': match['covered_variants'],
                        'fully_covered': match['fully_covered']})
    if not previous:
        checkpoint.setdefault('versions', {})[version_fingerprint] = now
        temporary = checkpoint_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2))
        temporary.replace(checkpoint_path)
    return {'document': document, 'original_file': str((folder / 'original.pdf').resolve())}, {
        'candidate_key': candidate.get('candidate_key'), 'document_id': document['id'],
        'original_sha256': sha, 'page_count': binary['page_count'], 'matches': matches,
        'rejected_targets': rejected_targets}


def prepare_corpus(corpus_root, catalog_path, grls_path, output_path, rejection_path, *, max_candidates=None):
    catalog_by_ru = defaultdict(list)
    for value in _read_jsonl(catalog_path):
        med = value.get('medication', value)
        keys = {_ru(v.get('ru_number') or med.get('ru_number')) for v in med.get('variants') or []}
        for ru in keys - {''}:
            catalog_by_ru[ru].append(med)
    grls_by_ru = defaultdict(list)
    for row in _read_jsonl(grls_path):
        grls_by_ru[_ru(row.get('registration_number'))].append(row)
    outputs, rejections, previews = [], [], []
    seen_ids = set()
    counts = Counter()
    paths = sorted(Path(corpus_root).glob('*/source-proof.json'))
    if max_candidates is not None:
        paths = paths[:max_candidates]
    for path in paths:
        counts['checked_candidates'] += 1
        try:
            proof = json.loads(path.read_text())
            ru = _ru((proof.get('candidate', {}).get('registration') or {}).get('registration_number'))
            wrapper, preview = prepare_candidate(proof, path.parent, catalog_by_ru[ru], grls_by_ru[ru])
            if wrapper['document']['id'] in seen_ids:
                counts['duplicate_document'] += 1
                continue
            seen_ids.add(wrapper['document']['id'])
            outputs.append(wrapper)
            previews.append(preview)
            counts['verified_original_documents'] += 1
        except (ValueError, KeyError, TypeError, OSError) as error:
            counts['rejected_or_needs_review'] += 1
            rejections.append({'candidate_key': path.parent.name, 'reason': str(error),
                               'error_class': type(error).__name__, 'status': 'draft_needs_review'})
    for path, records in [(Path(output_path), outputs), (Path(rejection_path), rejections)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(''.join(json.dumps(value, ensure_ascii=False) + '\n' for value in records))
        temporary.replace(path)
    return {'counts': dict(counts), 'covered_cards': len({m['slug'] for p in previews for m in p['matches']}),
            'covered_variants': sum(m['covered_variants'] for p in previews for m in p['matches']),
            'network_requests': 0, 'database_writes': 0, 'previews': previews,
            'output_path': str(output_path), 'rejection_path': str(rejection_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus-root', required=True)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--grls-index', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--rejections', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--max-candidates', type=int)
    args = parser.parse_args(argv)
    if args.max_candidates is not None and args.max_candidates < 1:
        parser.error('--max-candidates must be positive')
    report = prepare_corpus(args.corpus_root, args.catalog, args.grls_index, args.output,
                            args.rejections, max_candidates=args.max_candidates)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != 'previews'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
