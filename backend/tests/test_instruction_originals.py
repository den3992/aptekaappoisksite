"""Offline original-PDF transport, exact bindings, import isolation and rollback."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from api import make_router
from api.instruction_original_delivery import OfficialPdfCache, OriginalUnavailable
from api.medication_original_pdfs import MedicationOriginalService, canonical_hash, match_original_to_medication, validate_original_document
from api.medication_instructions import medication_identity_fingerprint
from scripts.import_medication_instructions import apply_plan, build_plan, rollback_batch
from scripts.import_medication_originals import OriginalCollections, validate_archive
from test_instruction_import import Collection, matches
from test_instruction_original_binary import pdf_bytes, project_pdf_bytes
from test_instruction_original_evidence import original_document, original_medication


def fixture(body=None):
    body = body if body is not None else pdf_bytes()
    doc = original_document()
    doc['original_bytes'] = len(body)
    doc['original_sha256'] = hashlib.sha256(body).hexdigest()
    doc['evidence']['original_sha256'] = doc['original_sha256']
    snapshot = doc['evidence']['registry_snapshot']
    snapshot['russian_registrations'][0]['documents'][0]['size'] = len(body)
    doc['evidence']['registry_snapshot_sha256'] = canonical_hash(snapshot)
    return doc, original_medication(), body


class Clock:
    def __init__(self):
        self.value = 100
    def now(self):
        return self.value
    def sleep(self, delay):
        self.value += delay


class Reply:
    def __init__(self, body, status=200, declared=None):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status_code = status
        self.headers = {'Content-Length': str(len(self.body) if declared is None else declared)}
        self.closed = False
    def iter_content(self, chunk_size):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]
    def close(self):
        self.closed = True


class Session:
    def __init__(self, replies):
        self.replies, self.calls, self.closed = replies, [], False
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.replies.pop(0)
    def close(self):
        self.closed = True


def workflow(body):
    instance = '01234567-89ab-cdef-0123-456789abcdef'
    return [Reply(instance), Reply({'status': 0, 'instanceid': instance}),
            Reply({'parameters': [{'name': 'fileid', 'stringvalue': 'ephemeral-private-file-id'}]}), Reply(body)]


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.doc, self.med, self.body = fixture()
        self.clock = Clock()

    def cache(self, session):
        return OfficialPdfCache(self.folder, session_factory=lambda: session,
                                clock=self.clock.now, sleep=self.clock.sleep)

    def test_whole_pdf_hash_checked_and_cached_without_persisting_workflow_tokens(self):
        session = Session(workflow(self.body))
        cache = self.cache(session)
        self.assertEqual(cache.get_bytes(self.doc), self.body)
        self.assertEqual(len(session.calls), 4)
        self.assertTrue(session.closed)
        self.assertGreaterEqual(self.clock.value, 103)
        for _, url, options in session.calls:
            self.assertTrue(url.startswith('https://pharma.eaeunion.org/platformsvc/nonauthorizedplatform/'))
            self.assertFalse(options['allow_redirects'])
            self.assertTrue(options['stream'])
            self.assertIsNot(options.get('verify'), False)
        self.assertIn('application/octet-stream', session.calls[-1][2]['headers']['Accept'])
        self.assertEqual(cache.get_bytes(self.doc), self.body)
        self.assertEqual(len(session.calls), 4)
        self.assertFalse(any(b'ephemeral-private-file-id' in path.read_bytes() for path in self.folder.iterdir() if path.is_file()))

    def test_changed_source_never_returns_or_caches_new_content_under_old_hash(self):
        session = Session(workflow(self.body.replace(b'q Q', b'q q')))
        with self.assertRaisesRegex(OriginalUnavailable, 'verified version'):
            self.cache(session).get_bytes(self.doc)
        self.assertEqual(list(self.folder.glob('*.pdf')), [])

    def test_redirect_oversized_and_truncated_responses_fail_closed(self):
        for reply in [Reply({}, status=302), Reply({}, declared=900000), Reply({}, declared=99)]:
            with self.subTest(status=reply.status_code), self.assertRaises(OriginalUnavailable):
                self.cache(Session([reply])).get_bytes(self.doc)

    def test_access_denial_stops_future_network_requests(self):
        denied = Session([Reply({}, status=403)])
        with self.assertRaises(OriginalUnavailable):
            self.cache(denied).get_bytes(self.doc)
        second = Session([])
        with self.assertRaises(OriginalUnavailable):
            self.cache(second).get_bytes(self.doc)
        self.assertEqual(second.calls, [])

    def test_actual_challenge_on_error_status_stops_but_plain_502_does_not(self):
        for body, stopped in [(b'<html>ordinary bad gateway</html>', False),
                              (b'<html>Checking your browser: CAPTCHA</html>', True)]:
            with tempfile.TemporaryDirectory() as directory:
                cache = OfficialPdfCache(directory, session_factory=lambda: Session([Reply(body, status=502)]),
                                         clock=self.clock.now, sleep=self.clock.sleep)
                with self.assertRaises(OriginalUnavailable):
                    cache.get_bytes(self.doc)
                self.assertEqual((Path(directory) / '.source-stopped').exists(), stopped)

    def test_temporary_credentials_and_unproven_variant_changes_are_rejected(self):
        for change in ['dose', 'form', 'manufacturer', 'workflow_token', 'inline_sections']:
            doc = copy.deepcopy(self.doc)
            if change == 'dose': doc['scopes'][0]['dosage'] = '250 мг'
            elif change == 'form': doc['scopes'][0]['form'] = 'капсулы'
            elif change == 'manufacturer': doc['identity']['manufacturers'].append('Чужой изготовитель')
            elif change == 'workflow_token': doc['evidence']['download_url'] = 'https://example.org/?token=private'
            else: doc['sections'] = [{'text': 'Unreviewed text'}]
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_original_document(doc)


class OriginalProjectMarkerTests(unittest.TestCase):
    def test_attachment_markers_cannot_be_overridden_by_stale_true_claims(self):
        for field in ['name', 'file_name', 'uploaded_file_path']:
            for marker in ['_PrOjEcT_', '_proekt_', 'ПРОЕКТ', 'draft']:
                if field == 'uploaded_file_path' and marker == 'ПРОЕКТ':
                    continue  # The observed-path ASCII guard already rejects it.
                doc, _, _ = fixture()
                snapshot = doc['evidence']['registry_snapshot']
                attachment = snapshot['russian_registrations'][0]['documents'][0]
                attachment[field] = ('fixture-folder/fixture_' + marker + '_final.pdf' if field == 'uploaded_file_path'
                                     else 'fixture_' + marker + '_final_штамп.pdf')
                if field == 'uploaded_file_path':
                    doc['source']['uploaded_file_path'] = attachment[field]
                doc['evidence']['registry_snapshot_sha256'] = canonical_hash(snapshot)
                self.assertIs(doc['evidence']['not_unapproved_project'], True)
                with self.subTest(field=field, marker=marker), self.assertRaisesRegex(ValueError, 'project/draft marker'):
                    validate_original_document(doc)

    def test_any_nonempty_review_flags_block_even_without_a_known_project_marker(self):
        for flags in [['independent_review_required'], {'unresolved': True}, 'needs_review']:
            doc, _, _ = fixture()
            snapshot = doc['evidence']['registry_snapshot']
            snapshot['russian_registrations'][0]['documents'][0]['review_flags'] = flags
            doc['evidence']['registry_snapshot_sha256'] = canonical_hash(snapshot)
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, 'unresolved review flags'):
                validate_original_document(doc)

    def test_benign_legacy_payload_validation_is_idempotent(self):
        doc, _, _ = fixture()
        first = validate_original_document(doc)
        self.assertEqual(first, validate_original_document(first))


class OriginalImportTests(unittest.TestCase):
    def test_actual_project_pdf_blocks_eaeu_original_despite_valid_old_metadata_claims(self):
        doc, _, body = fixture(project_pdf_bytes())
        validate_original_document(doc)
        self.assertEqual(doc['source']['kind'], 'official_registry')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'original.pdf'
            path.write_bytes(body)
            with self.assertRaisesRegex(ValueError, 'physical first page.*project/draft'):
                validate_archive(doc, path)

    def test_import_and_rollback_touch_only_original_collections(self):
        doc, med, body = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'original.pdf'
            path.write_bytes(body)
            database = SimpleNamespace(medications=Collection([med], read_only=True), prices=Collection(read_only=True),
                instruction_documents=Collection(read_only=True), medication_instruction_bindings=Collection(read_only=True),
                instruction_original_documents=Collection(), medication_original_bindings=Collection())
            namespace = OriginalCollections(database)
            plan = build_plan([{'document': doc, 'original_file': str(path)}], [med],
                              validator=validate_original_document, matcher=match_original_to_medication,
                              archive_validator=validate_archive)
            result = apply_plan(namespace, plan, validator=validate_original_document,
                                matcher=match_original_to_medication, archive_validator=validate_archive)
            self.assertEqual(result['added_documents'], 1)
            self.assertEqual(result['added_bindings'], 1)
            rollback = rollback_batch(namespace, result['batch_id'])
            self.assertEqual(rollback['disabled_bindings'], 1)
            self.assertEqual(len(database.instruction_original_documents.rows), 1)
            self.assertFalse(database.medications.writes or database.prices.writes)
            self.assertFalse(database.instruction_documents.writes or database.medication_instruction_bindings.writes)

    def test_old_ru_other_manufacturer_and_changed_strength_do_not_match(self):
        doc, med, _ = fixture()
        for field, value in [('manufacturer', 'Чужой'), ('dosage', '250 мг'), ('form', 'капсулы')]:
            changed = {**med, field: value}
            self.assertFalse(match_original_to_medication(doc, changed)['matched'])
        changed = copy.deepcopy(med)
        changed['variants'][0]['ru_number'] = 'ЛП-000001'
        self.assertFalse(match_original_to_medication(doc, changed)['matched'])


class AsyncCollection:
    def __init__(self, rows):
        self.rows = rows
    async def find_one(self, query, projection=None, max_time_ms=None):
        assert max_time_ms == 1500
        return next((copy.deepcopy(row) for row in self.rows if matches(row, query)), None)
    def find(self, query, projection=None):
        rows = [copy.deepcopy(row) for row in self.rows if matches(row, query)]
        class Cursor:
            def max_time_ms(inner, milliseconds):
                assert milliseconds == 1500
                return inner
            async def to_list(inner, limit):
                return rows[:limit]
        return Cursor()


class OriginalEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_coverage_is_separate_and_stale_identity_is_not_reused(self):
        doc, med, _ = fixture()
        match = match_original_to_medication(doc, med)
        binding = {'document_id': doc['id'], 'record_type': 'binding', 'status': 'verified', 'active': True,
                   'medicine_slug': med['slug'], 'identity_fingerprint': medication_identity_fingerprint(med),
                   'variant_bindings': match['bindings']}
        db = SimpleNamespace(instruction_original_documents=AsyncCollection([doc]),
                             medication_original_bindings=AsyncCollection([binding]))
        med['instructions'] = []
        med['instruction_coverage'] = {'covered_variants': 0, 'fully_covered': False}
        service = MedicationOriginalService(db)
        result = await service.attach(copy.deepcopy(med))
        self.assertEqual(result['instruction_original_coverage']['covered_variants'], 1)
        self.assertTrue(result['instruction_original_coverage']['fully_covered'])
        self.assertEqual(result['instruction_coverage']['covered_variants'], 0)
        self.assertEqual(result['instructions'], [])
        self.assertNotIn('evidence', result['instruction_originals'][0])
        changed = copy.deepcopy(med)
        changed['dosage'] = '250 мг'
        result = await service.attach(changed)
        self.assertEqual(result['instruction_originals'], [])

    async def test_rolled_back_original_cannot_be_served_and_active_pdf_has_exact_bytes(self):
        doc, _, body = fixture()
        binding = {'document_id': doc['id'], 'record_type': 'binding', 'status': 'verified', 'active': True, 'binding_id': 'one'}
        db = SimpleNamespace(instruction_original_documents=AsyncCollection([doc]),
                             medication_original_bindings=AsyncCollection([binding]))
        with tempfile.TemporaryDirectory() as directory, patch('api.OfficialPdfCache') as constructor:
            constructor.return_value.get_bytes.return_value = body
            router = make_router(db)
            endpoint = next(route.endpoint for route in router.routes if route.path == '/instructions/originals/{document_id}.pdf')
            response = await endpoint(doc['id'], download=True)
            self.assertEqual(response.body, body)
            self.assertIn('attachment', response.headers['content-disposition'])
            self.assertEqual(response.headers['content-type'], 'application/pdf')
            self.assertEqual(response.headers['etag'], '"' + doc['original_sha256'] + '"')
            binding['active'] = False
            with self.assertRaises(HTTPException) as failure:
                await endpoint(doc['id'])
            self.assertEqual(failure.exception.status_code, 404)
            self.assertEqual(constructor.return_value.get_bytes.call_count, 1)

    async def test_unknown_or_malformed_internal_id_never_fetches_a_source(self):
        db = SimpleNamespace(instruction_original_documents=AsyncCollection([]))
        with patch('api.OfficialPdfCache') as constructor:
            router = make_router(db)
            endpoint = next(route.endpoint for route in router.routes if route.path == '/instructions/originals/{document_id}.pdf')
            for identifier in ['https://evil.test/doc', '../secret', 'unknown-id']:
                with self.subTest(identifier=identifier), self.assertRaises(HTTPException) as failure:
                    await endpoint(identifier)
                self.assertEqual(failure.exception.status_code, 404)
            constructor.return_value.get_bytes.assert_not_called()

    async def test_full_delivery_slots_fail_fast_and_release_after_network_threads_finish(self):
        doc, _, body = fixture()
        binding = {'document_id': doc['id'], 'record_type': 'binding', 'status': 'verified', 'active': True}
        db = SimpleNamespace(instruction_original_documents=AsyncCollection([doc]),
                             medication_original_bindings=AsyncCollection([binding]))
        release, started = threading.Event(), []
        def blocked(document):
            started.append(document['id'])
            release.wait(5)
            return body
        with patch('api.OfficialPdfCache') as constructor:
            constructor.return_value.get_bytes.side_effect = blocked
            endpoint = next(route.endpoint for route in make_router(db).routes
                            if route.path == '/instructions/originals/{document_id}.pdf')
            first = [asyncio.create_task(endpoint(doc['id'])) for _ in range(2)]
            try:
                for _ in range(100):
                    if len(started) == 2:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(len(started), 2)
                with self.assertRaises(HTTPException) as failure:
                    await endpoint(doc['id'])
                self.assertEqual(failure.exception.status_code, 503)
                self.assertEqual(len(started), 2)
            finally:
                release.set()
                await asyncio.gather(*first)
            self.assertEqual((await endpoint(doc['id'])).body, body)


if __name__ == '__main__':
    unittest.main()
