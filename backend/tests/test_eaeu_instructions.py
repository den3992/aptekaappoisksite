"""Offline synthetic fixtures for the official public registry adapter."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.sources.eaeu_instructions import (
    ATTACHMENT_URI, DOWNLOAD_BASE, DOWNLOAD_JOB, EaeuAccessError,
    EaeuInstructionClient, EaeuSourceError, PUBLIC_COLLECTION, normalize_record,
    rechunk_checkpoints,
)


def record(oid="0123456789abcdef01234567"):
    document = {"drugKindCode": "USAGE_INSTRUCTION", "docName": "Fixture instruction.pdf",
                "uploadedFile": {"name": "fixture.pdf", "type": "application/pdf", "size": 20,
                                 "path": "fixture-folder/fixture.pdf"}}
    country = {"unifiedCountryCode": {"value": "RU"}, "countryKindCode": "01",
               "drugTradeName": "Fixture Brand", "drugRegistrationCertificateDetails": {
                   "registrationCertificateId": "FIXTURE-RU", "registrationStatusCode": "03",
                   "registrationStatusName": "registered fixture"},
               "drugDocumentsDetails": {"drugDocumentList": [document]}}
    foreign = copy.deepcopy(country)
    foreign["unifiedCountryCode"]["value"] = "KZ"
    foreign["drugRegistrationCertificateDetails"]["registrationCertificateId"] = "FIXTURE-KZ"
    return {"_id": {"$oid": oid}, "version": 7, "drugDetails": {
        "dosageFormDetails": {"dosageFormName": "Fixture form"},
        "packageFormDetails": [{"packageDetails": [{"dosageFormName": "Fixture form", "drugDosageDetails": {
            "dosageUnitDetails": {"dosageUnitMeasure": {"value": "17", "substanceMeasureCode": "fixture-unit"}}}}]}],
        "manufacturingAuthorizationHolderDetails": [{
            "businessEntityName": "Fixture Holder", "manufacturingAreaDetails": [
                {"businessEntityName": "Fixture Manufacturer", "manufactureStageDetails": [{"manufacturingStageCode": "25"}]},
                {"businessEntityName": "Fixture Packer", "manufactureStageDetails": [{"manufacturingStageCode": "60"}]},
            ]}],
    }, "drugCountryRegistrationDetails": [country, foreign]}


class Response:
    def __init__(self, payload=None, *, content=None, status=200, media="application/json"):
        self.payload = payload
        self.status_code = status
        self.headers = {"Content-Type": media}
        self.content = json.dumps(payload).encode() if content is None else content
        self.closed = False

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


class Limiter:
    def __init__(self):
        self.delays = []

    def run(self, operation, delay=0):
        self.delays.append(delay)
        return operation()


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


class EaeuMetadataTests(unittest.TestCase):
    def test_only_russian_registration_and_actual_paths_are_candidates(self):
        normalized = normalize_record(record(), "2026-11-15T10:00:00+00:00")
        self.assertEqual(len(normalized["russian_registrations"]), 1)
        registration = normalized["russian_registrations"][0]
        self.assertEqual(registration["registration_number"], "FIXTURE-RU")
        doc = registration["documents"][0]
        self.assertEqual(doc["uploaded_file_path"], "fixture-folder/fixture.pdf")
        self.assertIsNone(doc["direct_pdf_url"])
        self.assertEqual(doc["download_request"]["payload"]["uri"], ATTACHMENT_URI +
                         "0123456789abcdef01234567/files?file=fixture-folder%2Ffixture.pdf")
        self.assertEqual(doc["verification_status"], "candidate")
        self.assertFalse(normalized["pdf_downloaded"])
        self.assertFalse(normalized["text_imported"])

    def test_finished_product_manufacturer_not_holder_or_packer(self):
        metadata = normalize_record(record(), "2026-11-15T10:00:00+00:00")
        self.assertEqual(metadata["manufacturers"], ["Fixture Manufacturer"])
        self.assertEqual(metadata["package_dosages"][0]["dosage"]["dosageUnitDetails"]
                         ["dosageUnitMeasure"]["value"], "17")

    def test_long_brief_pair_is_same_explicit_finished_area_not_holder_or_packer(self):
        raw = record()
        holder = raw['drugDetails']['manufacturingAuthorizationHolderDetails'][0]
        holder['businessEntityBriefName'] = 'Fixture Holder Brief'
        area = holder['manufacturingAreaDetails'][0]
        area['businessEntityBriefName'] = 'Fixture Manufacturer Brief'
        holder['manufacturingAreaDetails'][1]['businessEntityBriefName'] = 'Fixture Packer Brief'
        normalized = normalize_record(raw, '2026-11-15T10:00:00+00:00')
        entities = normalized['manufacturer_entities']
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]['source_pointer'], '/drugDetails/manufacturingAuthorizationHolderDetails/0/manufacturingAreaDetails/0')
        self.assertEqual(entities[0]['name'], 'Fixture Manufacturer')
        self.assertEqual(entities[0]['brief_name'], 'Fixture Manufacturer Brief')
        self.assertEqual(entities[0]['raw_entity'], area)
        self.assertEqual(entities[0]['source_entity_sha256'], hashlib.sha256(json.dumps(area,
            ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest())

    def test_explicit_certificate_cancel_date_is_not_hidden_by_registered_status(self):
        raw = record()
        certificate = raw['drugCountryRegistrationDetails'][0]['drugRegistrationCertificateDetails']
        certificate['certificateCancelDate'] = {'$date': '2025-01-01T00:00:00Z'}
        normalized = normalize_record(raw, '2026-11-15T10:00:00+00:00')
        self.assertEqual(normalized['russian_registrations'][0]['cancelled_at'], '2025-01-01T00:00:00Z')
        self.assertEqual(normalized['russian_registrations'][0]['registration_status_code'], '03')
        certificate['docCancellationDate'] = {'$date': '2025-01-02T00:00:00Z'}
        with self.assertRaisesRegex(EaeuSourceError, 'conflicting explicit cancellation dates'):
            normalize_record(raw, '2026-11-15T10:00:00+00:00')

    def test_project_filename_flag_and_malicious_path_rejected(self):
        raw = record()
        doc = raw["drugCountryRegistrationDetails"][0]["drugDocumentsDetails"]["drugDocumentList"][0]
        doc["docName"] = "Проект fixture.pdf"
        metadata = normalize_record(raw, "2026-11-15T10:00:00+00:00")
        self.assertTrue(metadata["russian_registrations"][0]["documents"][0]["review_flags"])
        doc["uploadedFile"]["path"] = "../private/fixture.pdf"
        self.assertEqual(normalize_record(raw, "date")["russian_registrations"][0]["documents"], [])

    def test_checkpoint_resume_has_no_network_and_total_is_truthful(self):
        session = Session([Response({"result": [record()], "matchedDocuments": 1})])
        client = EaeuInstructionClient(session=session, limiter=Limiter())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"metadata.jsonl"
            summary = client.fetch_metadata(Path(directory)/"raw", output, page_size=1)
            self.assertTrue(summary["complete"])
            self.assertEqual(summary["records"], 1)
            self.assertEqual(json.loads(output.read_text())["record_id"], "0123456789abcdef01234567")
            summary = client.fetch_metadata(Path(directory)/"raw", output, page_size=1)
            self.assertTrue(summary["complete"])
            self.assertEqual(len(session.calls), 1)
            self.assertEqual(session.calls[0]["params"]["collection"], PUBLIC_COLLECTION)

    def test_max_pages_truncation_not_called_complete(self):
        session = Session([Response({"result": [record()], "matchedDocuments": 2})])
        client = EaeuInstructionClient(session=session, limiter=Limiter())
        with tempfile.TemporaryDirectory() as directory:
            summary = client.fetch_metadata(Path(directory)/"raw", Path(directory)/"out", page_size=1, max_pages=1)
            self.assertFalse(summary["complete"])
            self.assertEqual(summary["expected_records"], 2)

    def test_rechunk_reuses_source_pages_with_explicit_derivation_and_no_network(self):
        session = Session([Response({"result": [record(), record("0123456789abcdef01234568")], "matchedDocuments": 2})])
        client = EaeuInstructionClient(session=session, limiter=Limiter())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/"raw"
            target = Path(directory)/"split"
            client.fetch_metadata(source, Path(directory)/"original.jsonl", page_size=2)
            result = rechunk_checkpoints(source, target, page_size=1)
            self.assertEqual(result["records"], 2)
            self.assertEqual(result["pages"], 2)
            summary = client.fetch_metadata(target, Path(directory)/"derived.jsonl", page_size=1)
            self.assertTrue(summary["complete"])
            self.assertEqual(len(session.calls), 1)
            derived = json.loads((target/"page-001-000000.json").read_text())
            self.assertEqual(derived["derived_from"]["original_request"]["page_size"], 2)

    def test_changed_total_or_duplicate_ids_fail_closed(self):
        for payload in ({"result": [record("0123456789abcdef01234568")], "matchedDocuments": 3},
                        {"result": [record()], "matchedDocuments": 2}):
            session = Session([Response({"result": [record()], "matchedDocuments": 2}), Response(payload)])
            client = EaeuInstructionClient(session=session, limiter=Limiter())
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(EaeuSourceError):
                    client.fetch_metadata(Path(directory)/"raw", Path(directory)/"out", page_size=1)

    def test_overfull_final_page_is_rejected_without_claiming_complete(self):
        session = Session([Response({"result": [record(), record("0123456789abcdef01234568")], "matchedDocuments": 1})])
        client = EaeuInstructionClient(session=session, limiter=Limiter())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"out"
            with self.assertRaisesRegex(EaeuSourceError, "exceeds the declared total"):
                client.fetch_metadata(Path(directory)/"raw", output, page_size=2)
            self.assertFalse(output.exists())

    def test_403_or_challenge_stops_source_without_retry(self):
        for response in (Response(status=403), Response(status=500, media="text/html", content=b"<html>CAPTCHA</html>")):
            session = Session([response])
            client = EaeuInstructionClient(session=session, limiter=Limiter())
            with self.assertRaises(EaeuAccessError):
                client.fetch_page()
            with self.assertRaises(EaeuAccessError):
                client.fetch_page()
            self.assertEqual(len(session.calls), 1)

    def test_html_gateway_errors_retry_without_becoming_challenges(self):
        limiter = Limiter()
        responses = [Response(status=502, media="text/html", content=b"<html><h1>502 Bad Gateway</h1></html>"),
                     Response({"result": [record()], "matchedDocuments": 1})]
        session = Session(responses)
        client = EaeuInstructionClient(session=session, limiter=limiter)
        self.assertEqual(len(client.fetch_page()["result"]), 1)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(limiter.delays, [0, 1])
        self.assertTrue(responses[0].closed)

    def test_diagnostic_error_reports_actual_status_and_class(self):
        session = Session([Response(status=504, media="text/html", content=b"<html>504 Gateway Timeout</html>")])
        client = EaeuInstructionClient(session=session, limiter=Limiter(), max_attempts=1)
        with self.assertRaisesRegex(EaeuSourceError, "HTTP 504 transient_error"):
            client.fetch_page()
        self.assertEqual(len(session.calls), 1)

    def test_pdf_endpoint_html_captcha_stops_following_candidates(self):
        session = Session([Response(status=200, media="text/html", content=b"<html>CAPTCHA</html>")])
        client = EaeuInstructionClient(session=session, limiter=Limiter())
        with self.assertRaisesRegex(EaeuAccessError, "browser_challenge"):
            client._request("GET", DOWNLOAD_BASE + "/filedownload", expect_pdf=True)
        with self.assertRaises(EaeuAccessError):
            client.fetch_page()
        self.assertEqual(len(session.calls), 1)

    def test_one_selected_pdf_uses_official_workflow_and_checks_magic(self):
        candidate = normalize_record(record(), "date")["russian_registrations"][0]["documents"][0]
        instance = "12345678-abcd-4321-aaaa-012345678901"
        session = Session([
            Response(instance), Response({"instanceid": instance, "status": 0}),
            Response({"parameters": [{"name": "fileid", "stringvalue": "fixture-file"}]}),
            Response(content=b"%PDF-fixture-only", media="application/octet-stream"),
        ])
        client = EaeuInstructionClient(session=session, limiter=Limiter())
        with tempfile.TemporaryDirectory() as directory:
            result = client.download_pdf(candidate, Path(directory)/"fixture.pdf")
            self.assertEqual(Path(result["path"]).read_bytes(), b"%PDF-fixture-only")
            self.assertTrue(result["download_url_is_temporary"])
            self.assertEqual(result["verification_status"], "candidate")
        self.assertEqual(session.calls[0]["url"], DOWNLOAD_BASE + "/executewithjson")
        self.assertEqual(session.calls[0]["params"]["jobid"], DOWNLOAD_JOB)
        self.assertEqual(json.loads(session.calls[0]["data"])["uri"], ATTACHMENT_URI +
                         "0123456789abcdef01234567/files?file=fixture-folder/fixture.pdf")
        self.assertTrue(all(not call["allow_redirects"] for call in session.calls))

    def test_pdf_request_cannot_change_source_resource_or_exceed_declared_limit(self):
        candidate = normalize_record(record(), "date")["russian_registrations"][0]["documents"][0]
        session = Session([])
        client = EaeuInstructionClient(session=session, limiter=Limiter())
        with self.assertRaises(EaeuSourceError):
            client.download_pdf(candidate, "unused", max_bytes=10)
        candidate["download_request"]["payload"]["uri"] = ATTACHMENT_URI + "../private"
        with self.assertRaises(EaeuSourceError):
            client.download_pdf(candidate, "unused")
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
