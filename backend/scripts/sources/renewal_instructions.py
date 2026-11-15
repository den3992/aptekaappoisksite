"""Read public Renewal product/PDF links; no authentication, role claims or writes to Mongo.

One network worker, at most one request per second, with resumable local files.
Only links present in robots/sitemaps/product HTML are followed. A 401/403/429
or an actual browser challenge stops the source instead of attempting a bypass.
The resulting queue is evidence, not automatic permission to publish medicine text.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
from html.parser import HTMLParser
from html import unescape
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET


ORIGIN = 'https://www.renewal.ru'
MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_HTML_BYTES = 3 * 1024 * 1024
USER_AGENT = 'Aptekaa-Instruction-Verification/1.0'


@dataclass(frozen=True)
class Provider:
    key: str
    origin: str
    allowed_hosts: tuple[str, ...]
    product_prefix: str
    pdf_prefixes: tuple[str, ...]
    manufacturer_tokens: tuple[str, ...]
    upgrade_allowlisted_http_redirects: bool = False

    @classmethod
    def from_file(cls, path):
        value = json.loads(Path(path).read_text())
        for key in ['allowed_hosts', 'pdf_prefixes', 'manufacturer_tokens']:
            value[key] = tuple(value[key])
        result = cls(**value)
        parsed = urlsplit(result.origin)
        if parsed.scheme != 'https' or parsed.hostname not in result.allowed_hosts or parsed.path not in {'', '/'} or parsed.query:
            raise ValueError('provider origin must be a public HTTPS origin on its explicit host allowlist')
        return result


RENEWAL = Provider('renewal', ORIGIN, ('www.renewal.ru', 'renewal.ru'), '/products/', ('/upload/',), ('обновление',))


class RenewalSourceError(RuntimeError):
    pass


class RenewalAccessError(RenewalSourceError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def public_url(value, base=None, provider=RENEWAL):
    parsed = urlsplit(urljoin(base or provider.origin, value))
    try:
        port = parsed.port
    except ValueError:
        raise RenewalSourceError('link has an invalid public HTTPS port') from None
    if (parsed.scheme != 'https' or parsed.hostname not in provider.allowed_hosts or port not in {None, 443}
            or parsed.username or parsed.password or parsed.query):
        raise RenewalSourceError('link is not a public canonical provider URL')
    # Public PDF names may contain a literal percent sign (e.g. "0,1% 10 мл").
    # Preserve existing escapes, but encode raw percent signs before quoting.
    path = re.sub(r'%(?![0-9a-fA-F]{2})', '%25', parsed.path)
    return urlunsplit(('https', parsed.netloc, quote(path, safe="/%:@!$&'()*+,;=-._~"), '', ''))


def is_challenge(body):
    text = body[:250000].decode('utf-8', errors='replace')
    return bool(re.search(r'<title[^>]*>[^<]*(?:captcha|access denied|just a moment|доступ запрещ)', text, re.I)
                or re.search(r'id=[\"\'](?:challenge-form|dCaptcha)[\"\']', text, re.I))


class RenewalClient:
    def __init__(self, opener=None, delay=1.0, provider=RENEWAL):
        if delay < 1:
            raise ValueError('Renewal requests must be at least one second apart')
        self.opener = opener or build_opener(_NoRedirect())
        self.provider = provider
        self.delay, self.last_request = delay, 0.0
        self.robots = None

    def get(self, url, *, limit=MAX_HTML_BYTES):
        url = public_url(url, provider=self.provider)
        transport_upgrades = []
        for _ in range(4):
            if self.robots and not self.robots.can_fetch(USER_AGENT, url):
                raise RenewalSourceError('robots.txt disallows this URL')
            time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
            try:
                response = self.opener.open(request, timeout=30)
            except HTTPError as error:
                response = error
            try:
                status = response.status
                if status in {401, 403, 429}:
                    raise RenewalAccessError(f'official source returned HTTP {status}; source stopped')
                if status in {301, 302, 303, 307, 308}:
                    location = urljoin(url, response.headers.get('Location', ''))
                    target = urlsplit(location)
                    if (self.provider.upgrade_allowlisted_http_redirects
                            and target.scheme == 'http' and target.hostname in self.provider.allowed_hosts
                            and target.port is None and not target.username and not target.password and not target.query):
                        upgraded = urlunsplit(target._replace(scheme='https'))
                        transport_upgrades.append({'advertised_location': location, 'requested_https': upgraded})
                        location = upgraded
                    url = public_url(location, url, self.provider)
                    continue
                if status != 200:
                    raise RenewalSourceError(f'official source returned HTTP {status}')
                if int(response.headers.get('Content-Length', '0')) > limit:
                    raise RenewalSourceError('source response exceeds size limit')
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise RenewalSourceError('source response exceeds size limit')
                if is_challenge(body):
                    raise RenewalAccessError('official source requires a browser challenge; source stopped')
                declared_length = response.headers.get('Content-Length')
                if declared_length and int(declared_length) != len(body):
                    raise RenewalSourceError('source response length differs from Content-Length')
                metadata = {'url': url, 'retrieved_at': now(), 'sha256': digest(body),
                              'content_type': response.headers.get('Content-Type'),
                              'declared_bytes': int(declared_length) if declared_length else None,
                              'last_modified': response.headers.get('Last-Modified')}
                if transport_upgrades:
                    metadata['https_transport_upgrades'] = transport_upgrades
                return body, metadata
            finally:
                response.close()
        raise RenewalSourceError('too many source redirects')


class ProductParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h1_depth = 0
        self.h1 = []
        self.title_depth = 0
        self.document_title = []
        self.og_title = ''
        self.div_document_context = []
        self.link = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'h1':
            self.h1_depth += 1
        if tag == 'title':
            self.title_depth += 1
        if tag == 'meta' and values.get('property', '').lower() == 'og:title':
            self.og_title = unescape(values.get('content', ''))
        if tag == 'div':
            # Observed Vertex product tab 2 contains patient documents; tab 5
            # contains research articles and must not be treated as instructions.
            product_tab = (values.get('data-index') if 'product-information__content-box' in values.get('class', '').split()
                           else self.div_document_context[-1] if self.div_document_context else None)
            self.div_document_context.append(product_tab)
        if tag == 'a':
            self.link = {'href': values.get('href', ''), 'text': [values.get('title', ''), values.get('aria-label', '')],
                         'vertex_document_tab': bool(self.div_document_context and self.div_document_context[-1] == '2'),
                         'vertex_research_tab': bool(self.div_document_context and self.div_document_context[-1] == '5')}

    def handle_endtag(self, tag):
        if tag == 'h1':
            self.h1_depth = max(0, self.h1_depth - 1)
        if tag == 'title':
            self.title_depth = max(0, self.title_depth - 1)
        if tag == 'div' and self.div_document_context:
            self.div_document_context.pop()
        if tag == 'a' and self.link:
            self.link['text'] = ' '.join(' '.join(self.link['text']).split())
            self.links.append(self.link)
            self.link = None

    def handle_data(self, data):
        if self.h1_depth:
            self.h1.append(data)
        if self.title_depth:
            self.document_title.append(data)
        if self.link:
            self.link['text'].append(data)


def parse_product_html(html, url, provider=RENEWAL):
    parser = ProductParser()
    parser.feed(html)
    links = {}
    for link in parser.links:
        if provider.key == 'vertex' and link['vertex_research_tab']:
            continue
        if not (provider.key == 'vertex' and link['vertex_document_tab']) and not re.search(r'инструкц|instruk|лист[ао]к[\s-]*вкладыш|информаци[яю]\s+для\s+(?:пациент|работник)|общ[а-я]+\s+характеристик|охлп', link['text'] + ' ' + link['href'], re.I):
            continue
        try:
            target = public_url(link['href'], url, provider)
        except RenewalSourceError:
            continue
        if not urlsplit(target).path.lower().endswith('.pdf') or not urlsplit(target).path.startswith(provider.pdf_prefixes):
            continue
        links[target] = {'url': target, 'label': link['text']}
    title = ' '.join(' '.join(parser.h1).split())
    if not title and provider.key == 'vertex':
        title = ' '.join(' '.join(parser.document_title).split()) or parser.og_title.strip()
    return {'product_url': public_url(url, provider=provider), 'title': title, 'pdf_links': list(links.values())}


def label(value):
    # Matching only: source text is retained unchanged in published sections.
    value = unicodedata.normalize('NFKC', str(value).replace('®', '').replace('™', '')).casefold().replace('ё', 'е')
    return ' '.join(re.findall(r'[a-zа-я0-9]+', value))


def load_catalog(path):
    records = [json.loads(line) for line in Path(path).open() if line.strip()]
    return [record.get('medication', record) for record in records]


def relevant_slugs(title, medications, provider=RENEWAL):
    title = label(title)
    return [med['slug'] for med in medications if any(label(token) in label(med.get('manufacturer', '')) for token in provider.manufacturer_tokens)
            and (title == label(med.get('name', '')) or title.startswith(label(med.get('name', '')) + ' '))]


def read_jsonl(path):
    return [json.loads(line) for line in path.open() if line.strip()] if path.exists() else []


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def robots_lines(text):
    # Some official robots files contain literal backslash escapes in one line.
    # Only normalize those escapes for parsing; retain original bytes and hash.
    if '\n' not in text.strip() and ('\\r\\n' in text or '\\n' in text):
        text = text.replace('\\r\\n', '\n').replace('\\n', '\n')
    return text.splitlines()


def discover(client, directory):
    directory.mkdir(parents=True, exist_ok=True)
    provider = client.provider
    robot_body, robot_meta = client.get(provider.origin.rstrip('/') + '/robots.txt')
    (directory / 'robots.txt').write_bytes(robot_body)
    robot = RobotFileParser()
    robot.parse(robots_lines(robot_body.decode()))
    client.robots = robot
    ignored = []

    def supported_url(value, found_in):
        try:
            return public_url(value, provider=provider)
        except RenewalSourceError as error:
            ignored.append({'url': value, 'found_in': found_in, 'reason': str(error)})
            return None

    pending = [target for url in (robot.site_maps() or [])
               if (target := supported_url(url, robot_meta['url']))]
    if not pending:
        raise RenewalSourceError('official robots.txt does not advertise a sitemap')
    visited, products, sources = set(), set(), [robot_meta]
    while pending:
        url = pending.pop(0)
        if url in visited:
            continue
        if len(visited) >= 32:
            raise RenewalSourceError('unexpected sitemap tree size')
        visited.add(url)
        body, metadata = client.get(url, limit=16 * 1024 * 1024)
        (directory / ('sitemap-' + digest(url.encode())[:16] + '.xml')).write_bytes(body)
        sources.append(metadata)
        root = ET.fromstring(body)
        urls = []
        for element in root.iter():
            if element.tag.endswith('}loc') and element.text:
                if target := supported_url(element.text, metadata['url']):
                    urls.append(target)
        if root.tag.endswith('}sitemapindex'):
            pending.extend(urls)
        else:
            products.update(url for url in urls if urlsplit(url).path.startswith(provider.product_prefix) and urlsplit(url).path != provider.product_prefix)
    save_json(directory / 'product-urls.json', {'sources': sources, 'ignored_source_urls': ignored, 'urls': sorted(products)})
    return sorted(products)


def write_queue(directory, records):
    queue = {}
    for row in records.values():
        for link in row['pdf_links']:
            entry = queue.setdefault(link['url'], {'url': link['url'], 'products': [], 'catalog_slugs': []})
            entry['products'].append({key: row.get(key) for key in ['product_url', 'title', 'retrieved_at', 'original_html']})
            entry['catalog_slugs'] = sorted(set(entry['catalog_slugs'] + row['catalog_slugs']))
    temporary = directory / 'pdf-queue.jsonl.tmp'
    temporary.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in queue.values()))
    temporary.replace(directory / 'pdf-queue.jsonl')
    return list(queue.values())


def reparse_products(directory, medications, provider=RENEWAL):
    records = {}
    for row in read_jsonl(directory / 'products.jsonl'):
        if row.get('original_html'):
            html = gzip.decompress(Path(row['original_html']).read_bytes()).decode('utf-8', errors='replace')
            row.update(parse_product_html(html, row['product_url'], provider))
            row['catalog_slugs'] = relevant_slugs(row['title'], medications, provider)
        records[row['product_url']] = row
    temporary = directory / 'products.jsonl.tmp'
    temporary.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in records.values()))
    temporary.replace(directory / 'products.jsonl')
    queue = write_queue(directory, records)
    print(json.dumps({'phase': 'reparse', 'product_pages': len(records), 'unique_pdf_links': len(queue),
                      'relevant_pdfs': sum(bool(row['catalog_slugs']) for row in queue)}), flush=True)
    return queue


def fetch_products(client, directory, medications, limit=None):
    robot = RobotFileParser()
    robot.parse(robots_lines((directory / 'robots.txt').read_text()))
    client.robots = robot
    urls = json.loads((directory / 'product-urls.json').read_text())['urls']
    archive = directory / 'products'
    archive.mkdir(exist_ok=True)
    records = {row['product_url']: row for row in read_jsonl(directory / 'products.jsonl')}
    pending = [url for url in urls if url not in records]
    for index, url in enumerate(pending[:limit], 1):
        try:
            body, metadata = client.get(url)
            path = archive / (digest(url.encode()) + '.html.gz')
            path.write_bytes(gzip.compress(body))
            row = {**parse_product_html(body.decode('utf-8', errors='replace'), url, client.provider), **metadata,
                   'original_html': str(path.resolve())}
            row['catalog_slugs'] = relevant_slugs(row['title'], medications, client.provider)
        except RenewalAccessError:
            raise
        except RenewalSourceError as error:
            row = {'product_url': url, 'error': str(error), 'retrieved_at': now(), 'pdf_links': [], 'catalog_slugs': []}
        with (directory / 'products.jsonl').open('a') as output:
            output.write(json.dumps(row, ensure_ascii=False) + '\n')
        records[url] = row
        if index % 20 == 0:
            write_queue(directory, records)
            print(json.dumps({'phase': 'products', 'completed': len(records), 'total': len(urls)}, ensure_ascii=False), flush=True)
    queue = write_queue(directory, records)
    print(json.dumps({'phase': 'queue', 'product_pages': len(records), 'unique_pdf_links': len(queue),
                      'relevant_pdfs': sum(bool(row['catalog_slugs']) for row in queue)}), flush=True)
    return queue


def download_pdfs(client, directory, limit=None):
    robot = RobotFileParser()
    robot.parse(robots_lines((directory / 'robots.txt').read_text()))
    client.robots = robot
    archive = directory / 'pdfs'
    archive.mkdir(exist_ok=True)
    completed = {public_url(row['url'], provider=client.provider): row for row in read_jsonl(directory / 'pdf-downloads.jsonl')}
    queue = [row for row in read_jsonl(directory / 'pdf-queue.jsonl') if row['catalog_slugs']]
    pending = [row for row in queue if public_url(row['url'], provider=client.provider) not in completed]
    for index, row in enumerate(pending[:limit], 1):
        try:
            body, metadata = client.get(row['url'], limit=MAX_PDF_BYTES)
            if not body.startswith(b'%PDF-'):
                raise RenewalAccessError('advertised instruction returned non-PDF data; source stopped')
            if b'%%EOF' not in body[-1024:]:
                raise RenewalSourceError('PDF has no complete EOF trailer')
            path = archive / (digest(row['url'].encode()) + '.pdf')
            temporary = path.with_suffix('.pdf.tmp')
            temporary.write_bytes(body)
            temporary.replace(path)
            record = {**row, **metadata, 'url': row['url'], 'fetch_url': metadata['url'], 'original_file': str(path.resolve()), 'bytes': len(body), 'has_pdf_eof': True}
        except RenewalAccessError:
            raise
        except RenewalSourceError as error:
            record = {**row, 'error': str(error), 'retrieved_at': now()}
        with (directory / 'pdf-downloads.jsonl').open('a') as output:
            output.write(json.dumps(record, ensure_ascii=False) + '\n')
        completed[public_url(row['url'], provider=client.provider)] = record
        if index % 20 == 0:
            print(json.dumps({'phase': 'download', 'completed': len(completed), 'total': len(queue)}), flush=True)
    return list(completed.values())


def _pdf_worker_limit():
    import resource
    # macOS cannot lower RLIMIT_AS below its reserved VM map. Parent supervision
    # measures real RSS and kills a child above 512 MiB; DATA is an extra guard.
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    try:
        resource.setrlimit(resource.RLIMIT_DATA, (384 * 1024 * 1024, 384 * 1024 * 1024))
    except (OSError, ValueError):
        pass


def extraction_diagnostics(report):
    """Conservative review context; heading recognition is never completeness."""
    text = report.get('text', '')
    heading_only = [section['key'] for section in report.get('sections', [])
                    if label(section.get('text', '')) == label(section.get('title', ''))]
    repeated_composition = any(section['key'].startswith('composition_') for section in report.get('sections', []))
    candidate_type = ('patient_leaflet' if re.search(r'листок[\s-]*вкладыш|информация\s+для\s+пациент', text[:5000], re.I)
                      else 'smpc' if re.search(r'общая\s+характеристика\s+лекарственного\s+препарата', text[:5000], re.I)
                      else 'medical_instruction' if re.search(r'инструкция\s+по\s+медицинскому', text[:5000], re.I)
                      else 'unclassified')
    extracted_type = report.get('document_type', 'medical_instruction')
    return {
        'document_type_candidate': candidate_type, 'classification_is_approval': False,
        'extracted_document_type': extracted_type,
        'required_profile_sections_present': not report.get('missing_sections'),
        'old_headers_present': not report.get('missing_sections') if extracted_type == 'medical_instruction' else None,
        'section_review_reasons': report.get('section_review_reasons', []),
        'heading_only_sections': heading_only,
        'clinical_table_order_review': bool(heading_only or repeated_composition),
        'repeated_composition_headings': repeated_composition,
        'registration_numbers_in_text': list(dict.fromkeys(re.findall(
            r'(?:ЛП\s*-\s*(?:№\s*)?\(\d{4,8}\)\s*-\s*\(РГ\s*-\s*RU\)|Л[ПС]Р?\s*-\s*\d{4,8}(?:/\d{2,4})?|[ПР]\s*N\s*\d{4,8}(?:/\d{2,4})?)', text[:7000], re.I))),
        'verification_status': 'needs_identity_and_full_source_review',
    }


def review_extractions(directory):
    records = []
    for path in sorted((directory / 'extractions').glob('*.json')):
        report = json.loads(path.read_text())
        records.append({
            'extraction_file': str(path.resolve()), 'original_file': report['original_file'],
            'page_count': report['page_count'], 'characters': report['characters'],
            'missing_profile_sections': report['missing_sections'],
            'missing_old_profile_sections': report['missing_sections'] if report.get('document_type', 'medical_instruction') == 'medical_instruction' else [],
            'pages_requiring_review': report['pages_requiring_review'],
            **extraction_diagnostics(report),
        })
    temporary = directory / 'extraction-review.jsonl.tmp'
    temporary.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in records))
    temporary.replace(directory / 'extraction-review.jsonl')
    print(json.dumps({'phase': 'review', 'extractions': len(records),
                      'heading_only_review': sum(bool(row['heading_only_sections']) for row in records),
                      'clinical_table_order_review': sum(row['clinical_table_order_review'] for row in records)}), flush=True)
    return records


def _extract_job(job):
    from scripts.extract_instruction_pdf import extract_pdf
    original, destination = job
    try:
        _pdf_worker_limit()
        report = extract_pdf(Path(original))
        save_json(Path(destination), report)
        return {'original_file': original, 'extraction_file': destination, 'missing_sections': report['missing_sections'],
                'pages_requiring_review': report['pages_requiring_review'], 'characters': report['characters'],
                **extraction_diagnostics(report)}
    except Exception as error:
        return {'original_file': original, 'error_type': type(error).__name__}


def _worker_rss_kib(pid):
    """Linux slim images lack ps; both paths measure resident memory in KiB."""
    if sys.platform.startswith('linux'):
        for attempt in range(3):
            try:
                status = Path(f'/proc/{pid}/status').read_text()
            except OSError:
                return None
            match = re.search(r'^VmRSS:\s+(\d+)\s+kB\s*$', status, re.M)
            if match:
                return int(match.group(1))
            state = re.search(r'^State:\s+([A-Z])\b', status, re.M)
            if state and state.group(1) in {'Z', 'X'}:
                return 0  # A confirmed exited task has no resident address space.
            # Linux may briefly expose no mm during exec/binfmt setup. Obtain a
            # real sample; a running task without one still fails closed after
            # at most two 10 ms delays. Existing RSS/CPU/wall bounds are unchanged.
            if attempt < 2:
                time.sleep(0.01)
        return None
    try:
        sample = subprocess.run(['ps', '-o', 'rss=', '-p', str(pid)], capture_output=True, text=True)
    except OSError:
        return None
    return int(sample.stdout.strip()) if sample.returncode == 0 and sample.stdout.strip().isdigit() else None


def _supervised_extract_job(job):
    original, destination = job
    command = [sys.executable, '-m', 'scripts.sources.renewal_instructions', 'extract-one',
               '--directory', str(Path(destination).parent.parent), '--input-pdf', original, '--output', destination]
    started, peak = time.monotonic(), 0
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    reason = None
    while child.poll() is None:
        rss = _worker_rss_kib(child.pid)
        if rss is None:
            if child.poll() is not None:
                break
            reason = 'worker_memory_monitor_unavailable'
        else:
            peak = max(peak, rss)
        if peak > 512 * 1024:
            reason = 'worker_rss_limit'
        elif time.monotonic() - started > 120:
            reason = 'worker_timeout'
        if reason:
            child.kill()
            child.wait()
            break
        time.sleep(0.1)
    output = child.stdout.read()
    child.stdout.close()
    if reason or child.returncode:
        return {'original_file': original, 'error_type': reason or 'worker_exit', 'peak_rss_kib': peak}
    try:
        result = json.loads(output)
    except (ValueError, UnicodeError):
        result = {'original_file': original, 'error_type': 'invalid_worker_report'}
    return {**result, 'peak_rss_kib': peak}


def extract_downloads(directory, workers=4, reextract=False):
    if not 1 <= workers <= 4:
        raise ValueError('at most four bounded PDF workers are supported')
    target = directory / 'extractions'
    target.mkdir(exist_ok=True)
    jobs = [(row['original_file'], str((target / (Path(row['original_file']).stem + '.json')).resolve()))
            for row in read_jsonl(directory / 'pdf-downloads.jsonl') if row.get('original_file')]
    pending = [job for job in jobs if reextract or not Path(job[1]).exists()]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, result in enumerate(pool.map(_supervised_extract_job, pending), 1):
            with (directory / 'extraction-results.jsonl').open('a') as output:
                output.write(json.dumps(result, ensure_ascii=False) + '\n')
            if index % 20 == 0:
                print(json.dumps({'phase': 'extract', 'completed': index, 'total': len(pending)}), flush=True)
    review_extractions(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['discover', 'products', 'reparse', 'download', 'extract', 'review', 'extract-one', 'collect'])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-products', type=int)
    parser.add_argument('--max-pdfs', type=int)
    parser.add_argument('--reextract', action='store_true', help='Recreate local draft extraction reports from preserved PDFs; no network')
    parser.add_argument('--provider-config', type=Path, help='Explicit public provider hosts/prefixes/manufacturer hints; default Renewal')
    parser.add_argument('--input-pdf', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.phase in {'products', 'reparse', 'collect'} and not args.manifest:
        parser.error('--manifest is required for product selection')
    client = RenewalClient(provider=Provider.from_file(args.provider_config) if args.provider_config else RENEWAL)
    if args.phase == 'extract-one':
        if not args.input_pdf or not args.output:
            parser.error('extract-one requires --input-pdf and --output')
        print(json.dumps(_extract_job((str(args.input_pdf), str(args.output))), ensure_ascii=False))
        return 0
    try:
        if args.phase in {'discover', 'collect'}:
            urls = discover(client, args.directory)
            print(json.dumps({'phase': 'discover', 'product_urls': len(urls)}), flush=True)
        if args.phase in {'products', 'collect'}:
            fetch_products(client, args.directory, load_catalog(args.manifest), args.max_products)
        if args.phase == 'reparse':
            reparse_products(args.directory, load_catalog(args.manifest), client.provider)
        if args.phase in {'download', 'collect'}:
            download_pdfs(client, args.directory, args.max_pdfs)
        if args.phase in {'extract', 'collect'}:
            extract_downloads(args.directory, args.workers, args.reextract)
        if args.phase == 'review':
            review_extractions(args.directory)
    except RenewalAccessError as error:
        save_json(args.directory / 'source-stopped.json', {'error': str(error), 'at': now()})
        print(json.dumps({'source_stopped': str(error)}), flush=True)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
