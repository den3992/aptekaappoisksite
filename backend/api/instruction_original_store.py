"""Read-only, SHA-addressed retained originals, independent of network LRU."""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import stat
import time

STORE_DIRECTORY = '/var/lib/aptekaa-instruction-originals'
STORE_BUDGET_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
_SHA = re.compile(r'[a-f0-9]{64}')


class OriginalStoreError(ValueError):
    """A present retained original or its private directory is unsafe."""


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def open_private_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
            raise OriginalStoreError('retained original directory must be private0700')
        path_info = os.stat(path, follow_symlinks=False)
        if (path_info.st_dev, path_info.st_ino, path_info.st_mode) != (info.st_dev, info.st_ino, info.st_mode):
            raise OriginalStoreError('retained original directory changed during open')
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_checked_fd(fd, *, expected_bytes, expected_sha256, deadline, clock=time.monotonic,
                    return_body=True):
    """Bounded regular-file read, with stable descriptor and exact full digest."""
    if (type(expected_bytes) is not int or not 20 <= expected_bytes <= MAX_FILE_BYTES
            or not isinstance(expected_sha256, str) or not _SHA.fullmatch(expected_sha256)):
        raise OriginalStoreError('retained original identity is outside fixed bounds')
    before = os.fstat(fd)
    if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size != expected_bytes):
        raise OriginalStoreError('retained original must be regular0600 and exact length')
    if clock() >= deadline:
        raise OriginalStoreError('retained original read deadline exceeded')
    os.lseek(fd, 0, os.SEEK_SET)
    digest, size, prefix, trailer = hashlib.sha256(), 0, b'', b''
    # BytesIO.getvalue shares its completed immutable buffer on the installed
    # CPython runtime; avoid retaining a second whole-file bytearray copy.
    with io.BytesIO() as output:
        while True:
            if clock() >= deadline:
                raise OriginalStoreError('retained original read deadline exceeded')
            chunk = os.read(fd, min(CHUNK_BYTES, expected_bytes + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > expected_bytes:
                raise OriginalStoreError('retained original grew beyond expected length')
            if not prefix:
                prefix = chunk[:5]
            trailer = (trailer + chunk)[-1024:]
            digest.update(chunk)
            if return_body:
                output.write(chunk)
        if (size != expected_bytes or prefix != b'%PDF-' or b'%%EOF' not in trailer
                or digest.hexdigest() != expected_sha256):
            raise OriginalStoreError('retained original bytes differ from verified PDF')
        after = os.fstat(fd)
        if signature(before) != signature(after) or clock() >= deadline:
            raise OriginalStoreError('retained original descriptor changed or deadline expired')
        return (output.getvalue() if return_body else None), after


class PermanentOriginalStore:
    def __init__(self, directory=STORE_DIRECTORY, *, clock=time.monotonic):
        # Production uses this fixed default. The constructor override exists
        # for offline tests and is never taken from a document, URL or request.
        self.directory = Path(directory)
        self.clock = clock

    def get_bytes(self, document, *, deadline):
        sha, size = document['original_sha256'], document['original_bytes']
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise OriginalStoreError('invalid SHA-addressed retained original filename')
        directory_fd = file_fd = None
        try:
            try:
                directory_fd = open_private_directory(self.directory)
            except FileNotFoundError:
                return None
            name = sha + '.pdf'
            try:
                file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            except FileNotFoundError:
                return None
            body, checked = read_checked_fd(file_fd, expected_bytes=size, expected_sha256=sha,
                deadline=deadline, clock=self.clock)
            entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if signature(entry) != signature(checked):
                raise OriginalStoreError('retained original directory entry changed during read')
            current_directory = os.stat(self.directory, follow_symlinks=False)
            held_directory = os.fstat(directory_fd)
            if ((current_directory.st_dev, current_directory.st_ino, current_directory.st_mode)
                    != (held_directory.st_dev, held_directory.st_ino, held_directory.st_mode)):
                raise OriginalStoreError('retained original directory changed during read')
            return body
        except OriginalStoreError:
            raise
        except OSError:
            raise OriginalStoreError('retained original could not be verified safely') from None
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if directory_fd is not None:
                os.close(directory_fd)
