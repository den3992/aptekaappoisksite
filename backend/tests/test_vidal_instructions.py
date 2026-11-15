"""Offline provider fixtures only; no real medical texts or network calls."""
import copy
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

import requests

from scripts.sources.vidal_instructions import (
    API_BASE, REQUIRED_SECTIONS, VidalAccessError, VidalError,
    VidalInstructionClient, VidalProtocolError, VidalRateLimiter,
    normalize_product,
)


class Clock:
    def __init__(self):
        self.now = 10.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Response:
    def __init__(self, payload=None, status=200, headers=None, text=None):
        self.payload = payload
        self.status_code = status
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.text = json.dumps(payload) if text is None else text
        self.closed = False

    def json(self):
        if self.payload is None:
            raise ValueError("fixture invalid JSON")
        return self.payload

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses, clock):
        self.responses = list(responses)
        self.clock = clock
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, "at": self.clock(), **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def page(products=None, page_number=1, page_count=1):
    return Response({"success": True, "products": products or [],
                     "pagination": {"page": page_number, "pageCount": page_count}})


def fixture_product():
    return {
        "id": 17, "rusName": "Fixture Brand®", "rusNameClear": "Fixture Brand",
        "registrationNumber": "FIXTURE-RU-1", "regPreviousNumber": "FIXTURE-OLD-1",
        "isValid": True, "productTypeCode": "DRUG",
        "productUrl": "/drugs/fixture-brand", "composition": "<p>Fixture composition</p>",
        "zipInfo": "Fixture form and strength", "fullForm": ["Fixture form"],
        "forms": "[]", "updatedAt": "2026-11-01T10:00:00+00:00",
        "companies": [
            {"isManufacturer": True, "company": {"name": "Fixture Manufacturer"}},
            {"isRegistrationCertificate": True, "company": {"name": "Fixture Holder"}},
        ],
        "productPackages": [
            {"productId": 17, "barCode": "01234567890128"},
            {"productId": 999, "barCode": "99999999999999"},
            {"barCode": "11111111111111"},
        ],
        "document": {
            "documentId": 101, "updatedAt": "2026-11-02T10:00:00+00:00",
            "indication": "<p>Fixture indication</p>",
            "contraIndication": "<p>Fixture contraindication</p>",
            "dosage": "<p>Fixture administration</p>",
            "sideEffects": "<p>Fixture side effects</p>",
            "interaction": "<p>Fixture interaction</p>",
            "overDosage": "<p>Fixture overdose</p>",
            "storageCondition": "<p>Fixture storage</p>",
            "storageTime": "Fixture shelf life", "lactation": "Fixture lactation",
            "pregnancyUsing": "FixtureCode", "specialInstruction": "Fixture instructions",
        },
    }


class VidalClientTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.limiter = VidalRateLimiter(clock=self.clock, sleep=self.clock.sleep)

    def client(self, responses):
        session = Session(responses, self.clock)
        client = VidalInstructionClient("fixture-secret-token", "fixture configured agreement",
                                        session=session, limiter=self.limiter)
        return client, session

    def test_exact_filter_and_token_header_never_query_string(self):
        client, session = self.client([page(), page()])
        self.assertEqual(client.find_by_barcode("01234567890128"), [])
        self.assertEqual(client.find_by_registration_number("FIXTURE-RU-1"), [])
        self.assertEqual(session.calls[0]["params"]["filter[barCode]"], "01234567890128")
        self.assertEqual(session.calls[1]["params"]["filter[registrationNumber]"], "FIXTURE-RU-1")
        self.assertEqual(session.calls[0]["headers"]["X-Token"], "fixture-secret-token")
        for call in session.calls:
            self.assertEqual(call["url"], API_BASE + "/product/list")
            self.assertNotIn("fixture-secret-token", call["url"] + str(call["params"]))
            self.assertEqual(call["timeout"], (5, 20))
            self.assertFalse(call["allow_redirects"])
        self.assertGreaterEqual(session.calls[1]["at"] - session.calls[0]["at"], .5)

    def test_env_requires_explicit_token_and_rights(self):
        for env in ({}, {"VIDAL_API_TOKEN": "secret"}, {"VIDAL_RIGHTS_BASIS": "agreement"}):
            with self.assertRaises(VidalAccessError):
                VidalInstructionClient.from_env(env)

    def test_401_403_stop_client_without_retry_and_without_echoing_body(self):
        for status in (401, 403):
            client, session = self.client([Response({"error": "fixture-secret-token"}, status=status)])
            with self.assertRaises(VidalAccessError) as caught:
                client.find_by_registration_number("FIXTURE-RU-1")
            self.assertNotIn("fixture-secret-token", str(caught.exception))
            with self.assertRaises(VidalAccessError):
                client.get_product(17)
            self.assertEqual(len(session.calls), 1)

    def test_html_or_json_challenge_never_retried_even_500(self):
        challenge_responses = [
            Response(status=503, headers={"Content-Type": "text/html"}, text="<html>captcha</html>"),
            Response({"success": False, "errorMsg": "CAPTCHA required"}, status=500),
            Response({"success": False, "message": "browser challenge"}),
        ]
        for response in challenge_responses:
            client, session = self.client([response])
            with self.assertRaises(VidalAccessError):
                client.get_product(17)
            self.assertEqual(len(session.calls), 1)

    def test_bounded_backoff_and_shared_rate_limit_for_every_attempt(self):
        client, session = self.client([
            Response({"success": False}, status=429, headers={"Retry-After": "2"}),
            Response({"success": False}, status=503), page(),
        ])
        self.assertEqual(client.find_by_registration_number("FIXTURE-RU-1"), [])
        self.assertEqual([call["at"] for call in session.calls], [10, 12, 14])
        other, other_session = self.client([page()])
        other.find_by_registration_number("FIXTURE-RU-1")
        self.assertEqual(other_session.calls[0]["at"], 14.5)

    def test_html_502_is_a_transient_error_without_permanent_access_stop(self):
        client, session = self.client([
            Response(status=502, headers={"Content-Type": "text/html"}, text="<html>502 Bad Gateway</html>"), page(),
        ])
        self.assertEqual(client.find_by_registration_number("FIXTURE-RU-1"), [])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[1]["at"], 11)

    def test_unexpected_html_is_protocol_error_without_claiming_access_denial(self):
        client, session = self.client([
            Response(headers={"Content-Type": "text/html"}, text="<html>Unexpected page</html>"), page(),
        ])
        with self.assertRaises(VidalProtocolError):
            client.find_by_registration_number("FIXTURE-RU-1")
        self.assertEqual(client.find_by_registration_number("FIXTURE-RU-1"), [])
        self.assertEqual(len(session.calls), 2)

    def test_network_retry_is_bounded_and_sanitized(self):
        client, session = self.client([requests.Timeout("fixture-secret-token") for _ in range(3)])
        with self.assertRaises(VidalError) as caught:
            client.get_product(17)
        self.assertEqual(len(session.calls), 3)
        self.assertNotIn("fixture-secret-token", str(caught.exception))

    def test_transient_error_is_bounded_and_closes_every_response(self):
        responses = [Response({"success": False}, status=503) for _ in range(3)]
        client, session = self.client(responses)
        with self.assertRaises(VidalError):
            client.get_product(17)
        self.assertEqual(len(session.calls), 3)
        self.assertTrue(all(response.closed for response in responses))

    def test_redirect_is_not_followed_and_other_statuses_not_retried(self):
        client, session = self.client([Response(status=302, headers={"Location": "https://other.example/"})])
        with self.assertRaises(VidalError):
            client.get_product(17)
        self.assertEqual(len(session.calls), 1)

    def test_pagination_preserves_all_candidates_and_rejects_truncation(self):
        client, session = self.client([page([{"id": 1}], 1, 2), page([{"id": 2}], 2, 2)])
        self.assertEqual(client.find_by_registration_number("FIXTURE-RU-1"), [{"id": 1}, {"id": 2}])
        self.assertEqual(session.calls[1]["params"]["page"], 2)
        client, _ = self.client([page([{"id": 1}], 1, 2)])
        with self.assertRaises(VidalProtocolError):
            client.find_by_registration_number("FIXTURE-RU-1", max_pages=1)

    def test_unexpected_schema_and_wrong_document_identity_fail_closed(self):
        for response in (Response({"success": True, "products": []}),
                         Response({"success": False}), Response(None)):
            client, _ = self.client([response])
            with self.assertRaises(VidalProtocolError):
                client.find_by_registration_number("FIXTURE-RU-1")
        client, _ = self.client([Response({"success": True, "document": {"documentId": 102}})])
        with self.assertRaises(VidalProtocolError):
            client.get_document(101)

    def test_one_limiter_serializes_concurrent_clients(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        class BlockingSession:
            def get(inner, url, **kwargs):
                calls.append(self.clock())
                entered.set()
                release.wait(2)
                return Response({"success": True, "product": {"id": 17}})

        first = VidalInstructionClient("a", "agreement", session=BlockingSession(), limiter=self.limiter)
        second = VidalInstructionClient("b", "agreement", session=BlockingSession(), limiter=self.limiter)
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(first.get_product, 17)
            self.assertTrue(entered.wait(2))
            two = pool.submit(second.get_product, 17)
            self.assertEqual(len(calls), 1)
            release.set()
            one.result(2)
            two.result(2)
        self.assertEqual(calls, [10, 10.5])


class VidalNormalizationTests(unittest.TestCase):
    def normalize(self, product=None, **kwargs):
        return normalize_product(product or fixture_product(), rights_basis="fixture configured agreement",
                                 retrieved_at="2026-11-15T08:00:00+00:00", **kwargs)

    def test_canonical_draft_and_scope_are_never_invented(self):
        doc = self.normalize()
        self.assertEqual(doc["verification"]["status"], "draft")
        self.assertIsNone(doc["approved_at"])
        self.assertFalse(doc["source_scope"]["full_official_document_confirmed"])
        self.assertEqual(doc["source"]["rights_basis"], "fixture configured agreement")
        self.assertEqual(doc["identity"]["manufacturers"], ["Fixture Manufacturer"])
        self.assertEqual(doc["source_scope"]["holders"], ["Fixture Holder"])
        self.assertEqual(doc["registration_numbers"], ["FIXTURE-RU-1"])
        self.assertEqual(doc["scopes"], [{"gtin": "01234567890128"}])
        self.assertNotIn("dosage", doc["identity"])
        self.assertNotIn("Fixture Holder", doc["identity"]["manufacturers"])
        self.assertEqual(doc["original_url"], "https://www.vidal.ru/drugs/fixture-brand")
        self.assertEqual(doc["version"], "2026-11-02T10:00:00+00:00")

    def test_full_minimum_and_missing_sections_are_reported_truthfully(self):
        doc = self.normalize()
        self.assertTrue(doc["completeness"]["is_complete"])
        self.assertEqual(doc["completeness"]["required_sections"], list(REQUIRED_SECTIONS))
        self.assertEqual(doc["completeness"]["missing_sections"], [])
        product = fixture_product()
        product["document"]["dosage"] = "<p>&nbsp;</p><script>fixture hidden text</script>"
        doc = self.normalize(product)
        self.assertFalse(doc["completeness"]["is_complete"])
        self.assertEqual(doc["completeness"]["missing_sections"], ["administration"])

    def test_retains_additional_sections_and_codes_without_interpreting_them(self):
        doc = self.normalize()
        texts = {section["key"]: section["text"] for section in doc["sections"]}
        self.assertEqual(texts["shelf_life"], "Fixture shelf life")
        self.assertEqual(texts["pregnancy_lactation"], "Fixture lactation")
        self.assertEqual(doc["source_scope"]["restrictions"]["pregnancyUsing"], "FixtureCode")
        self.assertTrue(all("<" not in text for text in texts.values()))

    def test_wrong_linked_document_and_missing_rights_are_rejected(self):
        with self.assertRaises(VidalProtocolError):
            self.normalize(document={"documentId": 999})
        with self.assertRaises(VidalAccessError):
            normalize_product(fixture_product(), rights_basis="")

    def test_no_implicit_manufacturer_gtin_or_external_source_url(self):
        product = fixture_product()
        product["companies"] = [{"isRegistrationCertificate": True, "company": {"name": "Holder"}}]
        product["productPackages"] = [{"barCode": "01234567890128"}]
        product["productUrl"] = "https://untrusted.example/fixture"
        doc = self.normalize(product)
        self.assertEqual(doc["identity"]["manufacturers"], [])
        self.assertEqual(doc["scopes"], [])
        self.assertEqual(doc["source"]["url"], "")

    def test_original_hash_is_deterministic_and_detects_changes(self):
        product = fixture_product()
        first = self.normalize(product)["original_sha256"]
        reordered = dict(reversed(list(product.items())))
        self.assertEqual(first, self.normalize(reordered)["original_sha256"])
        changed = copy.deepcopy(product)
        changed["document"]["sideEffects"] = "Changed fixture text"
        self.assertNotEqual(first, self.normalize(changed)["original_sha256"])


if __name__ == "__main__":
    unittest.main()
