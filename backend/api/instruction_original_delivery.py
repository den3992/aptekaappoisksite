"""Bounded, cross-process serialized delivery of immutable official PDF originals."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

import requests

from .medication_original_pdfs import MAX_PDF_BYTES, validate_original_document

ORIGIN = 'https://pharma.eaeunion.org'
BASE = ORIGIN + '/platformsvc/nonauthorizedplatform'
JOB = '5f9495fb-6dd8-43b5-aa74-1e44cf219130'
ATTACHMENT = '/cdb/public/api/registry/P.MM.01/drug-monitoring-items/'


class OriginalUnavailable(ValueError):
    """Credential-free public failure. Remote response bodies/tokens are never logged."""


class OfficialPdfCache:
    def __init__(self, directory='/tmp/aptekaa-official-instruction-pdfs', *, max_bytes=128 * 1024 * 1024,
                 deadline_seconds=25, session_factory=requests.Session, clock=time.monotonic, sleep=time.sleep):
        if not MAX_PDF_BYTES <= max_bytes <= 512 * 1024 * 1024 or not 5 <= deadline_seconds <= 30:
            raise ValueError('cache and deadline must be bounded')
        self.directory = Path(directory)
        self.max_bytes, self.deadline_seconds = max_bytes, deadline_seconds
        self.session_factory, self.clock, self.sleep = session_factory, clock, sleep
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)

    def _remaining(self, deadline):
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise OriginalUnavailable('official original deadline exceeded')
        return remaining

    @contextmanager
    def _source_lock(self, deadline):
        # A single lock serializes source requests across both Uvicorn processes,
        # also preventing duplicate simultaneous downloads of the same SHA.
        with (self.directory / '.source.lock').open('a+') as handle:
            acquired = False
            try:
                while not acquired:
                    self._remaining(deadline)
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                    except BlockingIOError:
                        self.sleep(min(0.05, self._remaining(deadline)))
                yield
            finally:
                if acquired:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def _body_is_expected(self, body, doc):
        return (len(body) == doc['original_bytes'] and body.startswith(b'%PDF-')
                and b'%%EOF' in body[-1024:]
                and hashlib.sha256(body).hexdigest() == doc['original_sha256'])

    def _cached(self, doc):
        path = self.directory / (doc['original_sha256'] + '.pdf')
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size != doc['original_bytes']:
                return None
            body = path.read_bytes()
            if not self._body_is_expected(body, doc):
                return None
            path.touch()
            return body
        except OSError:
            return None

    def _request(self, session, method, endpoint, deadline, *, params=None, data=None, pdf=False, max_bytes=512 * 1024):
        if endpoint not in {'executewithjson', 'status', 'gettoken', 'filedownload'}:
            raise OriginalUnavailable('unsupported official source operation')
        stopped = self.directory / '.source-stopped'
        if stopped.exists():
            raise OriginalUnavailable('official source access is temporarily unavailable')
        next_path = self.directory / '.next-request-at'
        try:
            next_at = float(next_path.read_text())
        except (OSError, ValueError):
            next_at = 0
        # monotonic clock is shared by processes on this host; reject stale data
        # across a reboot rather than waiting on an unbounded stored value.
        if next_at - self.clock() > 2:
            next_at = 0
        if next_at > self.clock():
            delay = next_at - self.clock()
            if delay >= self._remaining(deadline):
                raise OriginalUnavailable('official original deadline exceeded')
            self.sleep(delay)
        self._remaining(deadline)
        next_path.write_text(str(self.clock() + 1))
        remaining = self._remaining(deadline)
        response = None
        try:
            response = session.request(method, BASE + '/' + endpoint, params=params,
                data=json.dumps(data, ensure_ascii=False) if data is not None else None,
                headers={'User-Agent': 'Aptekaa-Official-Instructions/1.0',
                         'Content-Type': 'plain/text;charset=utf-8',
                         'Accept-Encoding': 'identity',
                         # The public workflow serves its original as an
                         # octet-stream. Match the SPA's broad content negotiation.
                         'Accept': 'application/pdf, application/octet-stream, */*' if pdf else 'application/json, text/plain, */*'},
                timeout=(min(3, remaining), min(5, remaining)), allow_redirects=False, stream=True)
            if response.status_code in {401, 403}:
                stopped.write_text('official source denied access; manual audit required\n')
                raise OriginalUnavailable('official source access is temporarily unavailable')
            if response.status_code != 200:
                prefix = bytearray()
                for chunk in response.iter_content(chunk_size=1024):
                    self._remaining(deadline)
                    prefix.extend(chunk[:4096 - len(prefix)])
                    if len(prefix) >= 4096:
                        break
                if re.search(rb'captcha|cf-chl|challenge-platform|checking your browser', prefix, re.I):
                    stopped.write_text('official source returned an access challenge; manual audit required\n')
                raise OriginalUnavailable('official source is temporarily unavailable')
            declared = response.headers.get('Content-Length')
            if declared and (not declared.isdigit() or int(declared) > max_bytes):
                raise OriginalUnavailable('official response exceeds the byte limit')
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                self._remaining(deadline)
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise OriginalUnavailable('official response exceeds the byte limit')
            if declared and len(body) != int(declared):
                raise OriginalUnavailable('official response was truncated')
            body = bytes(body)
            if not body.startswith(b'%PDF-') and re.search(rb'captcha|cf-chl|challenge-platform|checking your browser', body[:4096], re.I):
                stopped.write_text('official source returned an access challenge; manual audit required\n')
                raise OriginalUnavailable('official source access is temporarily unavailable')
            if pdf:
                return body
            return json.loads(body)
        except (requests.RequestException, ValueError, TypeError, OSError) as error:
            if isinstance(error, OriginalUnavailable):
                raise
            raise OriginalUnavailable('official original could not be retrieved') from None
        finally:
            if response is not None:
                response.close()

    def _download(self, doc, deadline):
        source = doc['source']
        session = self.session_factory()
        try:
            payload = {'uri': ATTACHMENT + source['record_id'] + '/files?file=' + source['uploaded_file_path'], 'gp': 'g'}
            instance = self._request(session, 'POST', 'executewithjson', deadline,
                params={'jobid': JOB, 'operation': 'update'}, data=payload)
            if not isinstance(instance, str) or not re.fullmatch(r'[a-f0-9-]{36}', instance):
                raise OriginalUnavailable('official workflow returned an invalid response')
            for _ in range(8):
                status = self._request(session, 'GET', 'status', deadline, params={'instanceid': instance})
                if not isinstance(status, dict) or status.get('instanceid') != instance:
                    raise OriginalUnavailable('official workflow returned an invalid response')
                if status.get('status') != 2:
                    break
            else:
                raise OriginalUnavailable('official workflow is still processing')
            if status.get('status') != 0:
                raise OriginalUnavailable('official workflow could not provide this original')
            token = self._request(session, 'GET', 'gettoken', deadline, params={'instanceid': instance})
            if not isinstance(token, dict):
                raise OriginalUnavailable('official workflow returned an invalid response')
            file_id = next((v.get('stringvalue') for v in token.get('parameters', [])
                            if isinstance(v, dict) and v.get('name') == 'fileid'), None)
            if not isinstance(file_id, str) or not 1 <= len(file_id) <= 512:
                raise OriginalUnavailable('official workflow returned an invalid response')
            body = self._request(session, 'GET', 'filedownload', deadline,
                                 params={'id': file_id, 'instanceid': instance}, pdf=True,
                                 max_bytes=doc['original_bytes'])
            if not self._body_is_expected(body, doc):
                # A changed source requires a new audited version; never silently
                # replace the expected hash or return even a partial new PDF.
                raise OriginalUnavailable('official original differs from its verified version')
            return body
        finally:
            session.close()

    def _save(self, doc, body):
        files = [p for p in self.directory.glob('*.pdf') if p.is_file() and not p.is_symlink()]
        total = sum(p.stat().st_size for p in files)
        for old in sorted(files, key=lambda p: p.stat().st_mtime):
            if total + len(body) <= self.max_bytes:
                break
            total -= old.stat().st_size
            old.unlink()  # only this bounded, reconstructible source cache
        fd, name = tempfile.mkstemp(prefix='.pdf-', dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(body)
            temporary.replace(self.directory / (doc['original_sha256'] + '.pdf'))
        finally:
            temporary.unlink(missing_ok=True)

    def get_bytes(self, document):
        doc = validate_original_document(document)
        cached = self._cached(doc)
        if cached is not None:
            return cached
        deadline = self.clock() + self.deadline_seconds
        with self._source_lock(deadline):
            cached = self._cached(doc)
            if cached is not None:
                return cached
            body = self._download(doc, deadline)
            self._save(doc, body)
            return body
