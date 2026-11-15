"""Archive public Ozon product/PDF evidence at <=1 request/second; never approve or publish."""
from __future__ import annotations

import argparse
import gzip
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET

from api.medication_instructions import _ru
from scripts.sources.renewal_instructions import _supervised_extract_job


ORIGIN = "https://ozonpharm.ru"
USER_AGENT = "Aptekaa-Instruction-Verification/1.0"
MAX_PDF_BYTES = 32 * 1024 * 1024
SEED_PDF = ORIGIN + "/wp-content/uploads/2024/06/b9a03f45dab5550bdaf9e2af9ca42e02-3.pdf"


class OzonSourceError(RuntimeError):
    pass


class OzonAccessError(OzonSourceError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def public_url(value, base=ORIGIN):
    url = urlsplit(urljoin(base, value))
    if url.scheme != "https" or url.hostname not in {"ozonpharm.ru", "www.ozonpharm.ru"} or url.port not in {None, 443} or url.username or url.password or url.query:
        raise OzonSourceError("URL is outside the public Ozon origin")
    return urlunsplit((url.scheme, url.netloc, quote(url.path, safe="/%:@!$&'()*+,;=-._~"), "", ""))


def digest(value):
    return hashlib.sha256(value).hexdigest()


def read_jsonl(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class OzonClient:
    def __init__(self, opener=None, delay=1, clock=time.monotonic, sleep=time.sleep):
        if delay < 1:
            raise ValueError("Ozon rate limit must be <=1 request per second")
        self.opener = opener or build_opener(_NoRedirect())
        self.delay, self.clock, self.sleep = delay, clock, sleep
        self.last_request, self.stopped, self.robots = None, False, None

    def get(self, value, *, limit=3 * 1024 * 1024):
        if self.stopped:
            raise OzonAccessError("Ozon source was stopped after an access restriction")
        url = public_url(value)
        for _ in range(4):
            if self.robots and not self.robots.can_fetch(USER_AGENT, url):
                raise OzonSourceError("robots.txt disallows this URL")
            if self.last_request is not None:
                self.sleep(max(0, self.delay - (self.clock() - self.last_request)))
            self.last_request = self.clock()
            try:
                response = self.opener.open(Request(url, headers={"User-Agent": USER_AGENT}), timeout=30)
            except HTTPError as error:
                response = error
            except (URLError, TimeoutError, ConnectionError) as error:
                # Do not log proxy configuration, credentials or a full transport URL.
                raise OzonSourceError("Ozon public HTTPS transport is unavailable") from error
            try:
                if response.status in {401, 403, 429}:
                    self.stopped = True
                    raise OzonAccessError(f"Ozon returned HTTP {response.status}; source stopped")
                if response.status in {301, 302, 303, 307, 308}:
                    url = public_url(response.headers.get("Location", ""), url)
                    continue
                if response.status != 200:
                    raise OzonSourceError(f"Ozon returned HTTP {response.status}")
                if int(response.headers.get("Content-Length", "0")) > limit:
                    raise OzonSourceError("source response exceeds size limit")
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise OzonSourceError("source response exceeds size limit")
                declared_length = response.headers.get("Content-Length")
                if declared_length and int(declared_length) != len(body):
                    raise OzonSourceError("source response length differs from Content-Length")
                sample = body[:250000].decode("utf-8", errors="replace")
                if (re.search(r"<title[^>]*>[^<]*(?:captcha|access denied|just a moment|доступ запрещ)", sample, re.I)
                        or re.search(r'id=[\"\'](?:challenge-form|dCaptcha)[\"\']', sample, re.I)):
                    self.stopped = True
                    raise OzonAccessError("Ozon returned a browser challenge; source stopped")
                from datetime import datetime, timezone
                return body, {"url": url, "sha256": digest(body), "retrieved_at": datetime.now(timezone.utc).isoformat(),
                              "content_type": response.headers.get("Content-Type"), "last_modified": response.headers.get("Last-Modified")}
            finally:
                response.close()
        raise OzonSourceError("too many redirects")


class ProductParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h1, self.depth, self.links, self.link = [], 0, [], None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "h1": self.depth += 1
        if tag == "a": self.link = {"href": values.get("href", ""), "text": [values.get("title", ""), values.get("aria-label", "")]}

    def handle_endtag(self, tag):
        if tag == "h1": self.depth = max(0, self.depth - 1)
        if tag == "a" and self.link:
            self.link["text"] = " ".join(" ".join(self.link["text"]).split())
            self.links.append(self.link)
            self.link = None

    def handle_data(self, data):
        if self.depth: self.h1.append(data)
        if self.link: self.link["text"].append(data)


def parse_product_html(body, url):
    parser = ProductParser()
    parser.feed(body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body)
    pdfs = {}
    for link in parser.links:
        if not re.search(r"инструкц|instruk|лист[ао]к[\s-]*вкладыш|информаци[яю]\s+для\s+(?:пациент|работник)|общ[а-я]+\s+характеристик|охлп", link["text"] + " " + link["href"], re.I):
            continue
        try:
            target = public_url(link["href"], url)
        except OzonSourceError:
            continue
        path = urlsplit(target).path.lower()
        if path.startswith("/wp-content/uploads/") and path.endswith(".pdf"):
            # Actual product-page PDF links only; do not guess filenames or endpoints.
            pdfs[target] = {"url": target, "label": link["text"]}
    return {"product_url": public_url(url), "title": " ".join(" ".join(parser.h1).split()), "pdf_links": list(pdfs.values())}


def _label(value):
    return " ".join(re.findall(r"[a-zа-я0-9]+", unicodedata.normalize("NFKC", str(value)).casefold().replace("ё", "е")))


def load_catalog(path):
    meds = []
    for row in read_jsonl(Path(path)):
        med = row.get("medication", row)
        if med.get("is_canonical") is not False and "озон" in _label(med.get("manufacturer", "")):
            meds.append(med)
    return meds


def relevant_slugs(title, medications):
    title = _label(title)
    return [med["slug"] for med in medications if title == _label(med.get("name", "")) or title.startswith(_label(med.get("name", "")) + " ")]


def registration_numbers(text):
    """Extract header evidence only; no inference from ingredient/name or publication."""
    header = text[:8000]
    pattern = re.compile(r"регистрационн(?:ый|ое)\s+(?:номер|удостоверение)\s*[:№]?\s*", re.I)
    number = re.compile(
        r"(?:ЛП|ЛСР|П|Р)\s*(?:[-–—]\s*)?(?:[N№]\s*)?"
        r"(?:\([0-9]{4,12}\)(?:\s*[-–—]\s*\([А-ЯA-Z]{1,5}[-–—][А-ЯA-Z]{1,5}\))?"
        r"|[0-9]{4,12}(?:/[0-9]{1,4})?(?:[-–—][А-ЯA-Z]{1,5})?)"
        r"(?=$|[\s.,;:])", re.I,
    )
    result = []
    for match in pattern.finditer(header):
        candidate = number.match(header, match.end())
        if candidate:
            value = candidate.group(0).strip()
            if value not in result: result.append(value)
    return result


def discover(client, directory):
    directory.mkdir(parents=True, exist_ok=True)
    body, metadata = client.get(ORIGIN + "/robots.txt")
    (directory / "robots.txt").write_bytes(body)
    robot = RobotFileParser()
    robot.parse(body.decode().splitlines())
    client.robots = robot
    pending = [public_url(url) for url in robot.site_maps() or []]
    if not pending:
        raise OzonSourceError("robots.txt does not advertise public sitemaps")
    visited, products, sources = set(), set(), [metadata]
    while pending:
        url = pending.pop(0)
        if url in visited: continue
        if len(visited) >= 40: raise OzonSourceError("sitemap tree exceeds limit")
        visited.add(url)
        body, metadata = client.get(url, limit=16 * 1024 * 1024)
        (directory / ("sitemap-" + digest(url.encode())[:16] + ".xml")).write_bytes(body)
        sources.append(metadata)
        root = ET.fromstring(body)
        urls = []
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == "loc" and element.text:
                try: urls.append(public_url(element.text))
                except OzonSourceError: pass
        if root.tag.rsplit("}", 1)[-1] == "sitemapindex": pending.extend(urls)
        else: products.update(urls)
    save_json(directory / "discovered-urls.json", {"sources": sources, "urls": sorted(products)})
    return sorted(products)


def configure_robots(client, directory):
    robot = RobotFileParser()
    robot.parse((directory / "robots.txt").read_text().splitlines())
    client.robots = robot


def download_one(client, directory, row, medications):
    body, metadata = client.get(row["url"], limit=MAX_PDF_BYTES)
    if not body.startswith(b"%PDF-"):
        raise OzonSourceError("advertised instruction is not a PDF")
    if b"%%EOF" not in body[-1024:]:
        raise OzonSourceError("PDF has no complete EOF trailer")
    folder = directory / "pdfs"
    folder.mkdir(exist_ok=True)
    path = folder / (digest(row["url"].encode()) + "-" + digest(body) + ".pdf")
    temporary = path.with_suffix(".pdf.tmp")
    temporary.write_bytes(body)
    temporary.replace(path)
    record = {**row, **metadata, "url": row["url"], "fetch_url": metadata["url"],
              "original_file": str(path.resolve()), "bytes": len(body), "has_pdf_eof": True,
              "verification_status": "draft"}
    try:
        target = directory / "extractions"
        target.mkdir(exist_ok=True)
        extraction_path = target / (path.stem + ".json")
        # The shared supervisor enforces 512 MiB real RSS and 120 s wall time;
        # parsing never occurs in this network/archive process.
        outcome = _supervised_extract_job((str(path.resolve()), str(extraction_path.resolve())))
        record["extraction_peak_rss_kib"] = outcome.get("peak_rss_kib")
        if outcome.get("error_type"):
            record["extraction_error_type"] = outcome["error_type"]
        else:
            if extraction_path.stat().st_size > MAX_PDF_BYTES:
                raise OzonSourceError("saved extraction exceeds size limit")
            extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
            if extraction.get("original_sha256") != metadata["sha256"]:
                raise OzonSourceError("saved extraction refers to a different original")
            numbers = registration_numbers(extraction["text"])
            normalized = {_ru(number) for number in numbers}
            candidates = [med["slug"] for med in medications if any(_ru(variant.get("ru_number")) in normalized for variant in med.get("variants") or [])]
            record.update({"extraction_file": str(extraction_path.resolve()), "registration_numbers_extracted": numbers,
                           "candidate_slugs_exact_ru": candidates, "missing_sections": extraction["missing_sections"],
                           "pages_requiring_review": extraction["pages_requiring_review"], "characters": extraction["characters"]})
    except Exception as error:
        record["extraction_error_type"] = type(error).__name__
    with (directory / "pdf-downloads.jsonl").open("a") as output: output.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def collect(client, directory, medications, max_products=None, max_pdfs=None):
    configure_robots(client, directory)
    completed_pdfs = {row["url"] for row in read_jsonl(directory / "pdf-downloads.jsonl")}
    completed_products = {row["product_url"] for row in read_jsonl(directory / "products.jsonl")}
    urls = json.loads((directory / "discovered-urls.json").read_text())["urls"]
    # Sitemap page type is observed and recorded; simple catalog routes are preferred.
    urls.sort(key=lambda url: (not bool(re.search(r"/product|/preparat|/catalog", url)), url))
    product_count = pdf_count = 0
    for url in urls:
        if url in completed_products or urlsplit(url).path.lower().endswith(".pdf"): continue
        if max_products is not None and product_count >= max_products: break
        body, metadata = client.get(url)
        row = {**parse_product_html(body, url), **metadata}
        row["catalog_slugs"] = relevant_slugs(row["title"], medications)
        folder = directory / "products"
        folder.mkdir(exist_ok=True)
        path = folder / (digest(url.encode()) + ".html.gz")
        path.write_bytes(gzip.compress(body))
        row["original_html"] = str(path.resolve())
        with (directory / "products.jsonl").open("a") as output: output.write(json.dumps(row, ensure_ascii=False) + "\n")
        product_count += 1
        for link in row["pdf_links"]:
            if link["url"] in completed_pdfs or not row["catalog_slugs"]: continue
            if max_pdfs is not None and pdf_count >= max_pdfs: continue
            download_one(client, directory, {**link, "product_url": url, "product_title": row["title"], "candidate_slugs_by_title": row["catalog_slugs"]}, medications)
            completed_pdfs.add(link["url"])
            pdf_count += 1
        if product_count % 20 == 0: print(json.dumps({"products": product_count, "new_pdfs": pdf_count}), flush=True)
    return {"products_this_run": product_count, "pdfs_this_run": pdf_count}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["discover", "seed", "collect"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--max-products", type=int)
    parser.add_argument("--max-pdfs", type=int)
    args = parser.parse_args(argv)
    args.directory.mkdir(parents=True, exist_ok=True)
    client, medications = OzonClient(), load_catalog(args.manifest)
    try:
        if args.phase == "discover": result = {"discovered_urls": len(discover(client, args.directory))}
        elif args.phase == "seed":
            configure_robots(client, args.directory)
            result = download_one(client, args.directory, {"url": SEED_PDF, "discovered_from": "observed official public PDF search result"}, medications)
        else: result = collect(client, args.directory, medications, args.max_products, args.max_pdfs)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except OzonSourceError as error:
        result = {"error": str(error), "source_stopped": isinstance(error, OzonAccessError)}
        save_json(args.directory / "source-error.json", result)
        print(json.dumps(result), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
