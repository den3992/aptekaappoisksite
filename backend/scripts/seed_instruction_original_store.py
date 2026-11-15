"""Offline, bounded, no-overwrite seed from reviewed immutable source unpacks.

No extraction, network, DB, LRU operations or runtime writes are performed.
The input plan lists all reviewed source manifests, including the old store's
cohort; an unknown existing store file stops the operation without deleting it.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import uuid

from api.instruction_original_store import (
    CHUNK_BYTES, MAX_FILE_BYTES, STORE_BUDGET_BYTES, OriginalStoreError,
    open_private_directory, read_checked_fd, signature,
)

SCHEMA = 'aptekaa-original-store-seed-v1'
MAX_SOURCES, MAX_FILES, MAX_ENTRIES = 128, 4096, 32768
MAX_MANIFEST_BYTES, MAX_SECONDS = 4 * 1024 * 1024, 300
MAX_SOURCE_TOTAL_BYTES = 1024 * 1024 * 1024
MIN_FREE_BYTES, METADATA_RESERVE = 256 * 1024 * 1024, 32 * 1024 * 1024
_SHA = re.compile(r'[a-f0-9]{64}')
_PDF = re.compile(r'([a-f0-9]{64})\.pdf')
_LRU_COMPONENTS = {'aptekaa-official-instruction-pdfs', 'deploy_instruction_pdf_cache'}
SOURCE_PREFIXES = {
    'original_pdf': 'pdf/', 'retained_product_html': 'html/', 'verified_document': 'documents/',
    # The already-reviewed initial incremental source also retained its exact
    # wrappers and data receipts. These are checked as opaque immutable bytes.
    'verified_document_unchanged_canonical_serialization': 'documents/',
    'exact_reviewed_wrapper_input': 'wrappers/',
    'existing_schema_archive_and_full_matcher_preview': 'provenance/',
    'manual_identity_proof': 'provenance/', 'manual_review_summary': 'provenance/',
    'official_version_selection_provenance': 'provenance/',
    'private_visual_review_ledger_not_a_publication_input': 'provenance/',
    'source_preserving_manual_review_provenance': 'provenance/',
}


def _check_time(deadline):
    if time.monotonic() >= deadline:
        raise ValueError('original-store helper deadline exceeded')


def _protected(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_uid, info.st_gid)


def _stats(info):
    return {'device': info.st_dev, 'inode': info.st_ino, 'mode': stat.S_IMODE(info.st_mode),
            'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns,
            'nlink': info.st_nlink, 'uid': info.st_uid}


def _read_regular(fd, maximum, deadline):
    before = os.fstat(fd)
    if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 <= before.st_size <= maximum):
        raise ValueError('source metadata must be bounded regular0600')
    parts, total = [], 0
    while True:
        _check_time(deadline)
        chunk = os.read(fd, min(CHUNK_BYTES, maximum + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise ValueError('source metadata exceeds bounds')
        parts.append(chunk)
    if total != before.st_size or signature(before) != signature(os.fstat(fd)):
        raise ValueError('source metadata changed while read')
    return b''.join(parts), before


@contextmanager
def _source_file(root, relative):
    # Manifest rows have exactly one fixed safe subdirectory and an ASCII name.
    parts = PurePosixPath(relative).parts
    if (len(parts) != 2 or parts[0] not in {'pdf', 'html', 'documents', 'wrappers', 'provenance'}
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', parts[1]) or parts[1] in {'.', '..'}):
        raise ValueError('unsafe retained source member path')
    root_fd = child_fd = file_fd = None
    try:
        root_fd = open_private_directory(root)
        child_fd = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
        info = os.fstat(child_fd)
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('retained source subdirectory must be private0700')
        file_fd = os.open(parts[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=child_fd)
        yield file_fd, child_fd, parts[1]
        if signature(os.stat(parts[1], dir_fd=child_fd, follow_symlinks=False)) != signature(os.fstat(file_fd)):
            raise ValueError('retained source entry changed')
    finally:
        for fd in (file_fd, child_fd, root_fd):
            if fd is not None:
                os.close(fd)


def _check_source(root, row, deadline):
    with _source_file(root, row['path']) as (fd, _, _):
        if row['kind'] == 'original_pdf':
            _, info = read_checked_fd(fd, expected_bytes=row['bytes'], expected_sha256=row['sha256'],
                deadline=deadline, return_body=False)
        else:
            digest, total, before = hashlib.sha256(), 0, os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size != row['bytes']:
                raise ValueError('retained source member is not regular0600 exact length')
            while True:
                _check_time(deadline)
                chunk = os.read(fd, min(CHUNK_BYTES, row['bytes'] + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > row['bytes']:
                    raise ValueError('retained source member grew')
                digest.update(chunk)
            if (total != row['bytes'] or digest.hexdigest() != row['sha256']
                    or signature(before) != signature(os.fstat(fd))):
                raise ValueError('retained source member differs from reviewed manifest')
            info = os.fstat(fd)
        return info


def validate_sources(plan, *, deadline):
    if (plan.get('schema') != SCHEMA or not isinstance(plan.get('sources'), list)
            or not 1 <= len(plan['sources']) <= MAX_SOURCES):
        raise ValueError('bounded reviewed source plan required')
    budget = plan.get('budget_bytes')
    if type(budget) is not int or not MAX_FILE_BYTES <= budget <= STORE_BUDGET_BYTES:
        raise ValueError('logical original-store budget must stay within512MiB')
    pdfs, all_sources, manifests, roots = {}, [], [], set()
    entries, source_bytes = 0, 0
    for source in plan['sources']:
        if source.get('kind') != 'immutable_source_archive_unpack_v1':
            raise ValueError('only reviewed immutable unpacks may be sources, never LRU')
        root = Path(source['directory'])
        if not root.is_absolute() or str(root) in roots or _LRU_COMPONENTS.intersection(root.parts):
            raise ValueError('source directories must be explicit distinct absolute paths')
        roots.add(str(root))
        root_fd = open_private_directory(root)
        try:
            names = set(os.listdir(root_fd))
            if any(name.startswith('.source') or name == '.next-request-at' for name in names):
                raise ValueError('LRU source directories cannot seed immutable originals')
            fd = os.open('manifest.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
            try:
                raw, _ = _read_regular(fd, MAX_MANIFEST_BYTES, deadline)
            finally:
                os.close(fd)
        finally:
            os.close(root_fd)
        manifest_sha = hashlib.sha256(raw).hexdigest()
        if manifest_sha != source.get('manifest_sha256'):
            raise ValueError('reviewed source manifest SHA differs')
        manifest = json.loads(raw)
        manifest_schema = manifest.get('schema')
        if manifest_schema not in {'aptekaa_instruction_source_archive_v1', 'aptekaa_instruction_source_incremental_archive_v1'}:
            raise ValueError('unsupported reviewed source manifest schema')
        files = manifest.get('files')
        if not isinstance(files, list) or not files:
            raise ValueError('source manifest has no files')
        paths, own_pdfs = set(), {}
        for row in files:
            entries += 1
            if entries > MAX_ENTRIES or not isinstance(row, dict):
                raise ValueError('source manifest file-count bound exceeded')
            relative = row.get('path')
            digest, size = row.get('sha256'), row.get('bytes')
            if (not isinstance(relative, str) or not relative.isascii() or relative in paths
                    or not isinstance(digest, str) or not _SHA.fullmatch(digest)
                    or type(size) is not int or not 0 < size <= MAX_FILE_BYTES):
                raise ValueError('invalid source manifest path/SHA/size')
            paths.add(relative)
            source_bytes += size
            if source_bytes > MAX_SOURCE_TOTAL_BYTES:
                raise ValueError('total retained-source byte bound exceeded')
            if row.get('kind') not in SOURCE_PREFIXES or not relative.startswith(SOURCE_PREFIXES[row['kind']]):
                raise ValueError('unknown source member kind or path')
            info = _check_source(root, row, deadline)
            all_sources.append({'root': str(root), 'row': row, 'before': info})
            if row['kind'] == 'original_pdf':
                if relative != 'pdf/' + digest + '.pdf':
                    raise ValueError('PDF source path must be exact reviewed SHA')
                own_pdfs[digest] = size
                if digest in pdfs and pdfs[digest]['row']['bytes'] != size:
                    raise ValueError('duplicate PDF SHA has conflicting length')
                pdfs.setdefault(digest, {'root': str(root), 'row': row, 'before': info})
        counts = manifest.get('counts') or {}
        count_key = 'new_unique_pdf' if manifest_schema == 'aptekaa_instruction_source_incremental_archive_v1' else 'unique_pdf'
        bytes_key = count_key + '_bytes'
        if (type(counts.get(count_key)) is not int or type(counts.get(bytes_key)) is not int
                or counts[count_key] != len(own_pdfs) or counts[bytes_key] != sum(own_pdfs.values())):
            raise ValueError('source PDF manifest counts differ')
        manifests.append({'directory': str(root), 'sha256': manifest_sha, 'files_checked': len(files)})
    total = sum(value['row']['bytes'] for value in pdfs.values())
    if (not 1 <= len(pdfs) <= MAX_FILES or total > budget
            or type(plan.get('expected_unique_pdf')) is not int or type(plan.get('expected_unique_pdf_bytes')) is not int
            or plan.get('expected_unique_pdf') != len(pdfs) or plan.get('expected_unique_pdf_bytes') != total):
        raise ValueError('reviewed unique PDF count/logical bytes/budget differs')
    return pdfs, all_sources, manifests, total


def _existing(directory, pdfs, deadline):
    existing = set()
    try:
        fd = open_private_directory(directory)
    except FileNotFoundError:
        return existing
    try:
        names = os.listdir(fd)
        if len(names) > MAX_FILES + 1:
            raise ValueError('store file-count bound exceeded')
        for name in names:
            _check_time(deadline)
            if name == '.seed.lock':
                lock_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    info = os.fstat(lock_fd)
                    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size:
                        raise ValueError('unsafe original-store lock')
                finally:
                    os.close(lock_fd)
                continue
            match = _PDF.fullmatch(name)
            if not match or match[1] not in pdfs:
                raise ValueError('unknown existing original-store entry; manual audit required')
            file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                row = pdfs[match[1]]['row']
                _, info = read_checked_fd(file_fd, expected_bytes=row['bytes'], expected_sha256=match[1],
                    deadline=deadline, return_body=False)
                if signature(os.stat(name, dir_fd=fd, follow_symlinks=False)) != signature(info):
                    raise ValueError('existing store entry changed')
            finally:
                os.close(file_fd)
            existing.add(match[1])
    finally:
        os.close(fd)
    return existing


def _disk_guard(path, *, copy_bytes, new_files):
    info = os.statvfs(path)
    free = info.f_bavail * info.f_frsize
    if free < MIN_FREE_BYTES + METADATA_RESERVE + copy_bytes:
        raise ValueError('free disk reserve is insufficient for bounded original-store seed')
    if info.f_favail >= 0 and info.f_favail < new_files * 2 + 64:
        raise ValueError('free inode reserve is insufficient')
    return free


def seed(plan, directory, *, apply=False, allow_copy=False):
    deadline = time.monotonic() + MAX_SECONDS
    pdfs, sources, manifests, logical_bytes = validate_sources(plan, deadline=deadline)
    directory = Path(directory)
    if not directory.is_absolute() or _LRU_COMPONENTS.intersection(directory.parts):
        raise ValueError('explicit absolute private store directory required')
    destination_path = directory.resolve(strict=False)
    for root in {Path(source['root']).resolve() for source in sources}:
        if destination_path == root or root in destination_path.parents or destination_path in root.parents:
            raise ValueError('store must be separate from retained source unpacks')
    existing = _existing(directory, pdfs, deadline)
    needed = set(pdfs) - existing
    # Default hardlinks use only directory/inode metadata. Explicit EXDEV copy
    # permission reserves the complete new unique bytes before any mutation.
    copy_reserve = sum(pdfs[digest]['row']['bytes'] for digest in needed) if allow_copy else 0
    free_before = _disk_guard(directory if directory.exists() else directory.parent,
        copy_bytes=copy_reserve, new_files=len(needed))
    report = {'schema': SCHEMA, 'mode': 'apply' if apply else 'read_only_plan',
        'reviewed_manifests': manifests, 'source_files_checked': len(sources),
        'unique_pdf': len(pdfs), 'logical_bytes': logical_bytes, 'budget_bytes': plan['budget_bytes'],
        'existing_pdf': len(existing), 'new_pdf': len(needed), 'hardlinked': 0, 'copied': 0,
        'free_before': free_before, 'copy_fallback_explicit': allow_copy, 'source_changes': [],
        'source_LRU_used': False, 'source_archives_extracted': False, 'network_requests': 0, 'database_writes': 0}
    if not apply:
        return report
    if not directory.exists():
        directory.mkdir(mode=0o700, exist_ok=False)
    directory_fd = open_private_directory(directory)
    lock_fd = None
    try:
        lock_fd = os.open('.seed.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600, dir_fd=directory_fd)
        lock_info = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_info.st_mode) or stat.S_IMODE(lock_info.st_mode) != 0o600 or lock_info.st_size:
            raise ValueError('unsafe original-store lock')
        while True:
            _check_time(deadline)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.05)
        existing = _existing(directory, pdfs, deadline)
        for digest in sorted(set(pdfs) - existing):
            _check_time(deadline)
            source, name = pdfs[digest], digest + '.pdf'
            row = source['row']
            _disk_guard(directory, copy_bytes=row['bytes'] if allow_copy else 0, new_files=1)
            temporary = '.seed-' + uuid.uuid4().hex
            own_inode = None
            temporary_fd = None
            try:
                with _source_file(source['root'], row['path']) as (source_fd, source_parent, source_name):
                    _, before = read_checked_fd(source_fd, expected_bytes=row['bytes'], expected_sha256=digest,
                        deadline=deadline, return_body=False)
                    if _protected(before) != _protected(source['before']):
                        raise ValueError('source bytes/inode/mode/mtime changed after preflight')
                    copied = False
                    try:
                        os.link(source_name, temporary, src_dir_fd=source_parent,
                            dst_dir_fd=directory_fd, follow_symlinks=False)
                        own_inode = os.stat(temporary, dir_fd=directory_fd, follow_symlinks=False)
                        if (own_inode.st_dev, own_inode.st_ino) != (before.st_dev, before.st_ino):
                            raise ValueError('temporary hardlink differs from stable source FD')
                    except OSError as error:
                        if error.errno != errno.EXDEV or not allow_copy:
                            raise
                        temporary_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                            0o600, dir_fd=directory_fd)
                        own_inode = os.fstat(temporary_fd)
                        os.lseek(source_fd, 0, os.SEEK_SET)
                        remaining = row['bytes']
                        while remaining:
                            _check_time(deadline)
                            chunk = os.read(source_fd, min(CHUNK_BYTES, remaining))
                            if not chunk:
                                raise ValueError('copy source was truncated')
                            view = memoryview(chunk)
                            while view:
                                written = os.write(temporary_fd, view)
                                if not written: raise ValueError('copy write made no progress')
                                view = view[written:]
                            remaining -= len(chunk)
                        os.fsync(temporary_fd)
                        os.close(temporary_fd)
                        temporary_fd = None
                        copied = True
                    check_fd = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                    try:
                        _, checked = read_checked_fd(check_fd, expected_bytes=row['bytes'], expected_sha256=digest,
                            deadline=deadline, return_body=False)
                    finally:
                        os.close(check_fd)
                    if _protected(before) != _protected(os.fstat(source_fd)):
                        raise ValueError('source changed before atomic publication')
                    # link() is atomic no-replace on both supported local hosts.
                    # No rename()/replace() can overwrite an existing entry.
                    os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
                    published = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if (published.st_dev, published.st_ino) != (checked.st_dev, checked.st_ino):
                        raise ValueError('published original inode differs from checked temporary')
                    report['copied' if copied else 'hardlinked'] += 1
            finally:
                if temporary_fd is not None:
                    os.close(temporary_fd)
                if own_inode is not None:
                    actual = os.stat(temporary, dir_fd=directory_fd, follow_symlinks=False)
                    if (actual.st_dev, actual.st_ino) != (own_inode.st_dev, own_inode.st_ino):
                        raise ValueError('own temporary entry changed; refusing unrelated cleanup')
                    os.unlink(temporary, dir_fd=directory_fd)
        os.fsync(directory_fd)
        verified = _existing(directory, pdfs, deadline)
        if verified != set(pdfs):
            raise ValueError('final permanent-store union differs from reviewed PDFs')
        for source in sources:
            after = _check_source(source['root'], source['row'], deadline)
            if _protected(source['before']) != _protected(after):
                raise ValueError('retained source bytes/inode/mode/mtime changed')
            if source['row']['kind'] == 'original_pdf':
                report['source_changes'].append({'path': str(Path(source['root'])/source['row']['path']),
                    'before': _stats(source['before']), 'after': _stats(after),
                    'bytes_inode_mode_mtime_preserved': True,
                    'nlink_ctime_may_change_due_to_hardlinks': True})
        report['final_hash_verified_pdf'] = len(verified)
        report['free_after'] = _disk_guard(directory, copy_bytes=0, new_files=0)
        report['all_source_bytes_inode_mode_mtime_preserved'] = True
        return report
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(directory_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--store', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--allow-copy', action='store_true', help='Explicitly allow bounded EXDEV copy fallback')
    args = parser.parse_args(argv)
    fd = os.open(args.plan, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        raw, _ = _read_regular(fd, MAX_MANIFEST_BYTES, time.monotonic()+MAX_SECONDS)
    finally:
        os.close(fd)
    result = seed(json.loads(raw), args.store, apply=args.apply, allow_copy=args.allow_copy)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
