"""Bounded local originals and offline seeding, with actual filesystem races."""
from copy import deepcopy
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import time
from unittest.mock import patch

import pytest

from api.instruction_original_delivery import OfficialPdfCache, OriginalUnavailable
from api.instruction_original_store import (
    STORE_DIRECTORY, STORE_BUDGET_BYTES, MAX_FILE_BYTES, OriginalStoreError, PermanentOriginalStore,
)
from scripts.seed_instruction_original_store import SCHEMA, seed
from test_instruction_originals import fixture, Session, workflow


def private_file(path, body):
    path.write_bytes(body)
    path.chmod(0o600)
    return path


def store_fixture(tmp_path):
    doc, med, body = fixture()
    store = tmp_path/'permanent'
    store.mkdir(mode=0o700)
    file = private_file(store/(doc['original_sha256']+'.pdf'), body)
    return doc, med, body, store, file


def test_fixed_default_and_valid_read_leave_bytes_mode_mtime_unchanged(tmp_path):
    doc, _, body, directory, file = store_fixture(tmp_path)
    assert str(PermanentOriginalStore().directory) == STORE_DIRECTORY == '/var/lib/aptekaa-instruction-originals'
    before = file.stat()
    root_before = directory.stat()
    cache = OfficialPdfCache(tmp_path/'lru', original_store_directory=directory,
        session_factory=lambda: pytest.fail('a retained original must not start a source session'))
    (cache.directory/'.source-stopped').write_text('unchanged')
    (cache.directory/'.source-stopped-solopharm').write_text('unchanged')
    for _ in range(2):
        assert cache.get_bytes(doc) == body
    after = file.stat()
    assert (before.st_ino, before.st_mode, before.st_mtime_ns, before.st_size) == (after.st_ino, after.st_mode, after.st_mtime_ns, after.st_size)
    assert root_before.st_mtime_ns == directory.stat().st_mtime_ns
    assert not list(cache.directory.glob('*.pdf')) and not (cache.directory/'.source.lock').exists()
    assert (cache.directory/'.source-stopped').read_text() == 'unchanged'
    assert (cache.directory/'.source-stopped-solopharm').read_text() == 'unchanged'


@pytest.mark.parametrize('missing', ['directory', 'file'])
def test_missing_store_keeps_exact_old_lru_network_fallback(tmp_path, missing):
    doc, _, body = fixture()
    store = tmp_path/'missing'
    if missing == 'file': store.mkdir(mode=0o700)
    session = Session(workflow(body))
    cache = OfficialPdfCache(tmp_path/'lru', original_store_directory=store, session_factory=lambda: session)
    assert cache.get_bytes(doc) == body
    assert len(session.calls) == 4
    assert cache.get_bytes(doc) == body and len(session.calls) == 4
    assert list(cache.directory.glob('*.pdf'))


def test_missing_store_keeps_source_stop_and_canonical_validation_first(tmp_path):
    doc, _, _ = fixture()
    cache = OfficialPdfCache(tmp_path/'lru', original_store_directory=tmp_path/'missing',
        session_factory=lambda: Session([]))
    (cache.directory/'.source-stopped').write_text('audit retained')
    with pytest.raises(OriginalUnavailable): cache.get_bytes(doc)
    altered = deepcopy(doc)
    altered['scopes'][0]['dosage'] = '250 мг'
    with patch.object(cache.original_store, 'get_bytes', side_effect=AssertionError('validation must run first')):
        with pytest.raises(ValueError): cache.get_bytes(altered)
    assert (cache.directory/'.source-stopped').read_text() == 'audit retained'


@pytest.mark.parametrize('problem', ['content', 'length', 'mode', 'symlink', 'fifo', 'directory',
    'store_mode', 'store_symlink', 'no_eof', 'no_header'])
def test_present_bad_store_never_uses_even_a_valid_lru_or_network(tmp_path, problem):
    doc, _, body, directory, file = store_fixture(tmp_path)
    if problem == 'content': private_file(file, body.replace(b'q Q', b'q q'))
    elif problem == 'length': private_file(file, body+b'x')
    elif problem == 'mode': file.chmod(0o644)
    elif problem == 'symlink':
        other = private_file(tmp_path/'other', body)
        file.unlink(); file.symlink_to(other)
    elif problem == 'fifo': file.unlink(); os.mkfifo(file, 0o600)
    elif problem == 'directory': file.unlink(); file.mkdir(mode=0o700)
    elif problem == 'store_mode': directory.chmod(0o755)
    elif problem == 'store_symlink':
        actual = tmp_path/'actual'; directory.rename(actual); directory.symlink_to(actual, target_is_directory=True)
    elif problem == 'no_eof': private_file(file, body.replace(b'%%EOF', b'xxxxxx'))
    elif problem == 'no_header': private_file(file, b'xxxxx'+body[5:])
    cache = OfficialPdfCache(tmp_path/'lru', original_store_directory=directory,
        session_factory=lambda: pytest.fail('bad retained originals must fail closed'))
    cached = private_file(cache.directory/(doc['original_sha256']+'.pdf'), body)
    mtime = cached.stat().st_mtime_ns
    with pytest.raises(OriginalUnavailable): cache.get_bytes(doc)
    assert cached.stat().st_mtime_ns == mtime


@pytest.mark.parametrize('race', ['entry_swap', 'truncate', 'mtime', 'directory_swap'])
def test_stable_fd_and_entry_checks_detect_real_read_races(tmp_path, race):
    doc, _, _, directory, file = store_fixture(tmp_path)
    original_read = os.read
    happened = False
    def change(fd, count):
        nonlocal happened
        chunk = original_read(fd, count)
        if chunk and not happened:
            happened = True
            if race == 'entry_swap':
                file.rename(directory/'old-original')
                private_file(file, chunk)
            elif race == 'truncate':
                file.write_bytes(b'%PDF-\n%%EOF')
            elif race == 'mtime': os.utime(file, ns=(file.stat().st_atime_ns, file.stat().st_mtime_ns+1))
            else:
                directory.rename(tmp_path/'old-store')
                directory.mkdir(mode=0o700)
        return chunk
    with patch('api.instruction_original_store.os.read', side_effect=change):
        with pytest.raises(OriginalStoreError):
            PermanentOriginalStore(directory).get_bytes(doc, deadline=time.monotonic()+3)


def test_store_read_deadline_and_size_guard_are_bounded(tmp_path):
    doc, _, _, directory, _ = store_fixture(tmp_path)
    with pytest.raises(OriginalStoreError, match='deadline'):
        PermanentOriginalStore(directory).get_bytes(doc, deadline=time.monotonic()-1)
    doc['original_bytes'] = MAX_FILE_BYTES+1
    with pytest.raises(OriginalStoreError): PermanentOriginalStore(directory).get_bytes(doc, deadline=time.monotonic()+1)


def test_runtime_opens_only_readonly_nofollow_nonblocking_descriptors(tmp_path):
    doc, _, body, directory, _ = store_fixture(tmp_path)
    original = os.open
    flags = []
    def checked(path, mode, *args, **kwargs):
        flags.append(mode)
        assert mode & os.O_ACCMODE == os.O_RDONLY
        assert mode & os.O_NOFOLLOW and mode & os.O_NONBLOCK
        assert not mode & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        return original(path, mode, *args, **kwargs)
    with patch('api.instruction_original_store.os.open', side_effect=checked):
        assert PermanentOriginalStore(directory).get_bytes(doc, deadline=time.monotonic()+1) == body
    assert len(flags) == 2


def source_fixture(tmp_path):
    _, _, body = fixture()
    source = tmp_path/'reviewed-unpack'
    source.mkdir(mode=0o700)
    (source/'pdf').mkdir(mode=0o700)
    digest = hashlib.sha256(body).hexdigest()
    file = private_file(source/'pdf'/(digest+'.pdf'), body)
    manifest = {'schema': 'aptekaa_instruction_source_archive_v1',
        'files': [{'kind': 'original_pdf', 'path': 'pdf/'+digest+'.pdf', 'sha256': digest, 'bytes': len(body)}],
        'counts': {'unique_pdf': 1, 'unique_pdf_bytes': len(body)}}
    raw = json.dumps(manifest).encode()
    private_file(source/'manifest.json', raw)
    plan = {'schema': SCHEMA, 'sources': [{'kind': 'immutable_source_archive_unpack_v1',
        'directory': str(source), 'manifest_sha256': hashlib.sha256(raw).hexdigest()}],
        'budget_bytes': STORE_BUDGET_BYTES, 'expected_unique_pdf': 1, 'expected_unique_pdf_bytes': len(body)}
    return plan, source, file, body


def test_seed_default_plan_writes_nothing_then_hardlinks_and_records_truth(tmp_path):
    plan, _, source, body = source_fixture(tmp_path)
    target = tmp_path/'store'
    before = source.stat()
    preview = seed(plan, target)
    assert preview['mode'] == 'read_only_plan' and not target.exists()
    report = seed(plan, target, apply=True)
    assert report['hardlinked'] == report['final_hash_verified_pdf'] == 1 and report['copied'] == 0
    created = target/source.name
    assert created.read_bytes() == body and created.stat().st_ino == before.st_ino
    after = source.stat()
    assert (before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns)
    assert after.st_nlink == before.st_nlink+1
    assert report['source_changes'][0]['before']['nlink'] == before.st_nlink
    assert report['source_changes'][0]['after']['ctime_ns'] == after.st_ctime_ns
    assert seed(plan, target, apply=True)['hardlinked'] == 0
    assert not list(target.glob('.seed-*')) and stat.S_IMODE(target.stat().st_mode) == 0o700


@pytest.mark.parametrize('problem', ['source_mode', 'source_symlink', 'source_directory', 'manifest_sha',
    'manifest_symlink', 'source_hash', 'source_stopped_marker', 'unknown_source_kind', 'count', 'size', 'budget',
    'existing_unknown', 'existing_bad', 'existing_symlink', 'store_mode', 'store_symlink'])
def test_seed_refuses_unsafe_inputs_without_overwrite_or_source_changes(tmp_path, problem):
    plan, source_root, source, body = source_fixture(tmp_path)
    target = tmp_path/'store'
    target.mkdir(mode=0o700)
    if problem == 'source_mode': source.chmod(0o644)
    elif problem == 'source_symlink':
        other = private_file(tmp_path/'other', body); source.unlink(); source.symlink_to(other)
    elif problem == 'source_directory': source_root.chmod(0o755)
    elif problem == 'manifest_sha': plan['sources'][0]['manifest_sha256'] = 'f'*64
    elif problem == 'manifest_symlink':
        original = source_root/'manifest.json'; other = tmp_path/'manifest'; original.rename(other); original.symlink_to(other)
    elif problem == 'source_hash': private_file(source, body.replace(b'q Q', b'q q'))
    elif problem == 'source_stopped_marker': private_file(source_root/'.source-stopped', b'preserve source stop')
    elif problem == 'unknown_source_kind': plan['sources'][0]['kind'] = 'lru_cache'
    elif problem == 'count': plan['expected_unique_pdf'] = 2
    elif problem == 'size': plan['expected_unique_pdf_bytes'] += 1
    elif problem == 'budget': plan['budget_bytes'] = STORE_BUDGET_BYTES+1
    elif problem == 'existing_unknown': private_file(target/'unknown.pdf', b'keep untouched')
    elif problem == 'existing_bad': private_file(target/source.name, b'keep untouched')
    elif problem == 'existing_symlink': (target/source.name).symlink_to(source)
    elif problem == 'store_mode': target.chmod(0o755)
    else:
        target.rename(tmp_path/'real-store'); target.symlink_to(tmp_path/'real-store', target_is_directory=True)
    original = source.lstat()
    with pytest.raises((ValueError, OSError)):
        seed(plan, target, apply=True)
    assert source.lstat().st_mtime_ns == original.st_mtime_ns
    if problem == 'existing_unknown': assert (target/'unknown.pdf').read_bytes() == b'keep untouched'
    if problem == 'existing_bad': assert (target/source.name).read_bytes() == b'keep untouched'


def test_disk_and_inode_reserve_refuse_before_mutation(tmp_path):
    plan, _, _, _ = source_fixture(tmp_path)
    target = tmp_path/'store'
    actual = os.statvfs(tmp_path)
    values = list(actual)
    values[4] = 0
    with patch('scripts.seed_instruction_original_store.os.statvfs', return_value=os.statvfs_result(values)):
        with pytest.raises(ValueError, match='free disk'): seed(plan, target, apply=True)
    assert not target.exists()
    values = list(actual); values[7] = 0
    with patch('scripts.seed_instruction_original_store.os.statvfs', return_value=os.statvfs_result(values)):
        with pytest.raises(ValueError, match='inode'): seed(plan, target, apply=True)
    assert not target.exists()


def test_cross_filesystem_copy_requires_explicit_permission_and_is_still_verified(tmp_path):
    plan, _, source, body = source_fixture(tmp_path)
    real_link = os.link
    def cross_source(src, dst, **kwargs):
        if str(dst).startswith('.seed-'): raise OSError(errno.EXDEV, 'fixture cross filesystem')
        return real_link(src, dst, **kwargs)
    with patch('scripts.seed_instruction_original_store.os.link', side_effect=cross_source):
        with pytest.raises(OSError): seed(plan, tmp_path/'no-copy', apply=True)
        result = seed(plan, tmp_path/'copy', apply=True, allow_copy=True)
    assert result['copied'] == 1 and result['hardlinked'] == 0
    created = tmp_path/'copy'/source.name
    assert created.read_bytes() == body and created.stat().st_ino != source.stat().st_ino
    assert source.stat().st_nlink == 1


def test_final_publication_never_replaces_a_racing_existing_file(tmp_path):
    plan, _, source, _ = source_fixture(tmp_path)
    target = tmp_path/'store'
    real_link = os.link
    def race(src, dst, **kwargs):
        if str(dst) == source.name:
            private_file(target/source.name, b'other writer: preserve')
        return real_link(src, dst, **kwargs)
    with patch('scripts.seed_instruction_original_store.os.link', side_effect=race):
        with pytest.raises(FileExistsError): seed(plan, target, apply=True)
    assert (target/source.name).read_bytes() == b'other writer: preserve'
    assert not list(target.glob('.seed-*'))


def test_seed_lock_has_a_deadline_and_cannot_publish_concurrently(tmp_path):
    plan, _, source, _ = source_fixture(tmp_path)
    target = tmp_path/'store'
    target.mkdir(mode=0o700)
    fd = os.open(target/'.seed.lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with patch('scripts.seed_instruction_original_store.MAX_SECONDS', 0.1):
            with pytest.raises(ValueError, match='deadline'):
                seed(plan, target, apply=True)
        assert not (target/source.name).exists()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_source_proof_requires_full_sha_again_after_preflight(tmp_path):
    plan, _, source, body = source_fixture(tmp_path)
    real_link = os.link
    def change_source(src, dst, **kwargs):
        result = real_link(src, dst, **kwargs)
        if str(dst).startswith('.seed-'):
            source.write_bytes(body.replace(b'q Q', b'q q'))
        return result
    target = tmp_path/'store'
    with patch('scripts.seed_instruction_original_store.os.link', side_effect=change_source):
        with pytest.raises(ValueError): seed(plan, target, apply=True)
    assert not (target/source.name).exists() and not list(target.glob('.seed-*'))


def test_store_cannot_be_inside_source_unpack_or_known_lru_volume(tmp_path):
    plan, source, _, _ = source_fixture(tmp_path)
    for target in (source/'pdf', tmp_path/'deploy_instruction_pdf_cache'/'_data',
                   tmp_path/'aptekaa-official-instruction-pdfs'):
        with pytest.raises(ValueError): seed(plan, target, apply=True)


@pytest.mark.parametrize('problem', ['schema', 'traversal', 'unknown_kind', 'duplicate', 'boolean_count'])
def test_even_pinned_manifest_must_obey_safe_schema_and_membership(tmp_path, problem):
    plan, source, _, _ = source_fixture(tmp_path)
    path = source/'manifest.json'
    manifest = json.loads(path.read_text())
    if problem == 'schema': manifest['schema'] = 'unreviewed_archive_variant'
    elif problem == 'traversal': manifest['files'][0]['path'] = 'pdf/../secret'
    elif problem == 'unknown_kind': manifest['files'][0]['kind'] = 'new_unsupported_kind'
    elif problem == 'duplicate': manifest['files'].append(deepcopy(manifest['files'][0]))
    else: manifest['counts']['unique_pdf'] = True
    raw = json.dumps(manifest).encode()
    private_file(path, raw)
    plan['sources'][0]['manifest_sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError): seed(plan, tmp_path/'store', apply=True)
    assert not (tmp_path/'store').exists()
