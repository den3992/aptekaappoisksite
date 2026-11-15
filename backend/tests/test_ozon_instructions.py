"""Offline public-source safety and exact registration-evidence fixtures."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.robotparser import RobotFileParser

from scripts.sources.ozon_instructions import (
    ORIGIN, OzonAccessError, OzonClient, OzonSourceError, digest, discover,
    download_one, main, parse_product_html, public_url, registration_numbers,
    relevant_slugs,
)


class Response(io.BytesIO):
    def __init__(self, body=b"fixture", status=200, headers=None):
        super().__init__(body)
        self.status, self.headers = status, headers or {}


class Opener:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def open(self, request, timeout):
        self.calls.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class Clock:
    def __init__(self):
        self.value, self.sleeps = 0, []

    def now(self):
        return self.value

    def sleep(self, value):
        self.sleeps.append(value)
        self.value += value


def client(opener):
    clock = Clock()
    return OzonClient(opener, clock=clock.now, sleep=clock.sleep), clock


class OzonTests(unittest.TestCase):
    def test_only_actual_instruction_links_on_official_upload_path(self):
        page = '''<h1>Хлоропирамин ОЗОН 25 мг</h1>
        <a href="/wp-content/uploads/2024/06/actual.pdf">Инструкция</a>
        <a href="/wp-content/uploads/2024/06/patient.pdf">Листок-вкладыш</a>
        <a href="/wp-content/uploads/2024/06/certificate.pdf">Сертификат</a>
        <a href="https://foreign.test/wp-content/uploads/instruction.pdf">Инструкция</a>
        <a href="/private/instruction.pdf">Инструкция</a>
        <a href="/download?role=doctor">Инструкция</a>'''
        result = parse_product_html(page, ORIGIN + "/catalog/product/")
        self.assertEqual(result["title"], "Хлоропирамин ОЗОН 25 мг")
        self.assertEqual([row["url"].rsplit("/", 1)[1] for row in result["pdf_links"]], ["actual.pdf", "patient.pdf"])
        self.assertNotIn("verification", result)

    def test_origin_boundary_and_no_auth_or_role_claim(self):
        for url in ["http://ozonpharm.ru/file.pdf", "https://other.test/file.pdf",
                    ORIGIN + "/?role=doctor", "https://user:secret@ozonpharm.ru/file.pdf",
                    "https://ozonpharm.ru:8443/file.pdf"]:
            with self.assertRaises(OzonSourceError):
                public_url(url)
        opener = Opener(Response())
        source, _ = client(opener)
        source.get(ORIGIN + "/robots.txt")
        request = opener.calls[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertNotIn("Cookie", request.headers)
        self.assertNotIn("Authorization", request.headers)

    def test_every_request_and_redirect_obeys_one_per_second(self):
        opener = Opener(Response(status=302, headers={"Location": "/robots.txt"}), Response(), Response())
        source, clock = client(opener)
        source.get(ORIGIN + "/redirect")
        source.get(ORIGIN + "/other")
        self.assertEqual(clock.sleeps, [1, 1])
        self.assertEqual(len(opener.calls), 3)

    def test_restriction_or_challenge_permanently_stops_client(self):
        for response in [Response(status=401), Response(status=403), Response(status=429),
                         Response(b'<form id="challenge-form">')]:
            opener = Opener(response)
            source, _ = client(opener)
            with self.assertRaises(OzonAccessError):
                source.get(ORIGIN + "/robots.txt")
            with self.assertRaises(OzonAccessError):
                source.get(ORIGIN + "/robots.txt")
            self.assertEqual(len(opener.calls), 1)

    def test_cross_origin_redirect_and_robots_denial_are_not_followed(self):
        opener = Opener(Response(status=302, headers={"Location": "https://foreign.test/file"}))
        source, _ = client(opener)
        with self.assertRaises(OzonSourceError):
            source.get(ORIGIN + "/robots.txt")
        self.assertEqual(len(opener.calls), 1)
        robot = RobotFileParser()
        robot.parse(["User-agent: *", "Disallow: /private/"])
        source.robots = robot
        with self.assertRaisesRegex(OzonSourceError, "robots"):
            source.get(ORIGIN + "/private/file.pdf")
        self.assertEqual(len(opener.calls), 1)

    def test_truncated_response_and_unavailable_transport_fail_closed(self):
        opener = Opener(Response(b"short", headers={"Content-Length": "1000"}))
        source, _ = client(opener)
        with self.assertRaisesRegex(OzonSourceError, "Content-Length"):
            source.get(ORIGIN + "/robots.txt")
        source, _ = client(Opener(URLError("sensitive transport configuration")))
        with self.assertRaisesRegex(OzonSourceError, "HTTPS transport is unavailable") as error:
            source.get(ORIGIN + "/robots.txt")
        self.assertNotIn("sensitive", str(error.exception))

    def test_registration_number_is_exact_header_token_not_trailing_text(self):
        text = "Регистрационный номер: ЛП-002922 Торговое наименование: Хлоропирамин\n"
        text += "Регистрационное удостоверение: ЛСР-004912/09\n"
        text += "Регистрационный номер: ЛП-№(000015)-(РГ-RU)\n"
        text += "Регистрационный номер: Р N000777/01\n"
        self.assertEqual(registration_numbers(text), ["ЛП-002922", "ЛСР-004912/09", "ЛП-№(000015)-(РГ-RU)", "Р N000777/01"])
        self.assertEqual(registration_numbers("Упоминание ЛП-002922 в тексте"), [])
        self.assertEqual(registration_numbers("Регистрационный номер: ЛП-002922ABC"), [])

    def test_sitemap_discovery_uses_advertised_public_urls_and_archives(self):
        opener = Opener(Response(("User-agent: *\nSitemap: " + ORIGIN + "/products.xml").encode()),
                        Response(("<urlset><url><loc>" + ORIGIN + "/catalog/product/</loc></url>"
                                  "<url><loc>https://foreign.test/product/</loc></url></urlset>").encode()))
        source, _ = client(opener)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.assertEqual(discover(source, path), [ORIGIN + "/catalog/product/"])
            self.assertTrue((path / "robots.txt").exists())
            self.assertEqual(len(list(path.glob("sitemap-*.xml"))), 1)
            self.assertEqual(len(json.loads((path / "discovered-urls.json").read_text())["sources"]), 2)

    def test_pdf_archive_is_draft_and_candidates_use_variant_ru_only(self):
        body = b"%PDF-offline-fixture\n%%EOF"
        source, _ = client(Opener(Response(body)))
        meds = [{"slug": "exact", "ru_number": "wrong-top-level", "variants": [{"ru_number": "ЛП-002922"}]},
                {"slug": "not-exact", "ru_number": "ЛП-002922", "variants": [{"ru_number": "ЛП-002922-ГП"}]}]
        extraction = {"text": "Регистрационный номер: ЛП-002922\n", "missing_sections": [],
                      "pages_requiring_review": [], "characters": 80, "original_sha256": digest(body)}
        def supervised(job):
            Path(job[1]).write_text(json.dumps(extraction), encoding="utf-8")
            return {"original_file": job[0], "extraction_file": job[1], "peak_rss_kib": 12345}
        with tempfile.TemporaryDirectory() as directory, patch("scripts.sources.ozon_instructions._supervised_extract_job", side_effect=supervised) as worker:
            record = download_one(source, Path(directory), {"url": ORIGIN + "/wp-content/uploads/instruction.pdf"}, meds)
            self.assertEqual(record["verification_status"], "draft")
            self.assertEqual(record["candidate_slugs_exact_ru"], ["exact"])
            self.assertEqual(record["sha256"], digest(body))
            self.assertEqual(Path(record["original_file"]).read_bytes(), body)
            self.assertEqual(list(Path(directory).glob("pdfs/*.tmp")), [])
            self.assertEqual(record["extraction_peak_rss_kib"], 12345)
            self.assertTrue(record["has_pdf_eof"])
            worker.assert_called_once_with((record["original_file"], record["extraction_file"]))
            self.assertNotIn("document", record)
            self.assertNotIn("active", record)

    def test_incomplete_pdf_is_not_archived_or_sent_to_worker(self):
        source, _ = client(Opener(Response(b"%PDF-incomplete")))
        with tempfile.TemporaryDirectory() as directory, patch("scripts.sources.ozon_instructions._supervised_extract_job") as worker:
            with self.assertRaisesRegex(OzonSourceError, "EOF"):
                download_one(source, Path(directory), {"url": ORIGIN + "/wp-content/uploads/instruction.pdf"}, [])
            worker.assert_not_called()
            self.assertFalse((Path(directory) / "pdf-downloads.jsonl").exists())

    def test_worker_timeout_preserves_draft_archive_without_reading_stale_extraction(self):
        body = b"%PDF-offline-fixture\n%%EOF"
        source, _ = client(Opener(Response(body)))
        with tempfile.TemporaryDirectory() as directory, patch("scripts.sources.ozon_instructions._supervised_extract_job", return_value={"error_type": "worker_timeout", "peak_rss_kib": 512000}):
            record = download_one(source, Path(directory), {"url": ORIGIN + "/wp-content/uploads/instruction.pdf"}, [])
            self.assertEqual(record["extraction_error_type"], "worker_timeout")
            self.assertEqual(record["verification_status"], "draft")
            self.assertTrue(Path(record["original_file"]).exists())
            self.assertNotIn("extraction_file", record)
            self.assertNotIn("candidate_slugs_exact_ru", record)

    def test_title_selection_is_only_a_boundary_respecting_hint(self):
        meds = [{"slug": "exact", "name": "Хлоропирамин"}]
        self.assertEqual(relevant_slugs("Хлоропирамин 25 мг", meds), ["exact"])
        self.assertEqual(relevant_slugs("Хлоропираминплюс 25 мг", meds), [])

    def test_main_records_transport_failure_without_retry_or_traceback(self):
        source, _ = client(Opener(URLError("proxy secret")))
        with tempfile.TemporaryDirectory() as directory, patch("scripts.sources.ozon_instructions.OzonClient", return_value=source), patch("builtins.print"):
            path = Path(directory)
            manifest = path / "manifest.jsonl"
            manifest.write_text("")
            result = main(["discover", "--directory", str(path), "--manifest", str(manifest)])
            self.assertEqual(result, 2)
            evidence = json.loads((path / "source-error.json").read_text())
            self.assertEqual(evidence, {"error": "Ozon public HTTPS transport is unavailable", "source_stopped": False})


if __name__ == "__main__":
    unittest.main()
