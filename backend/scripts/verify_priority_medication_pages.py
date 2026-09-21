"""Verify rendered SEO invariants for the approved priority medication pages.

Run from the backend environment after a deployment::

    python -m scripts.verify_priority_medication_pages --city msk

The check is read-only.  It deliberately reports the robots distribution but
does not fail noindex pages: indexability is controlled by real pharmacy data.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from pymongo import MongoClient

from scripts.apply_priority_medication_seo import CONTENT_VERSION, MEDICATIONS, ROOT
from scripts.import_priority_medications import SOURCE, curated_key


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.h1 = ""
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.json_ld: list[dict] = []
        self.visible: list[str] = []
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._script_type = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"title", "h1", "script"}:
            self._capture = tag
            self._buffer = []
            self._script_type = values.get("type") or ""
        if tag == "meta" and values.get("name"):
            self.meta[values["name"].lower()] = values.get("content") or ""
        if tag == "link" and values.get("rel") == "canonical":
            self.canonical = values.get("href") or ""

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)
        elif data.strip():
            self.visible.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag != self._capture:
            return
        value = "".join(self._buffer).strip()
        if tag == "title":
            self.title = value
        elif tag == "h1" and not self.h1:
            self.h1 = re.sub(r"\s+", " ", value)
        elif tag == "script" and self._script_type == "application/ld+json":
            self.json_ld.append(json.loads(value))
        self._capture = None
        self._buffer = []
        self._script_type = ""


def schema_nodes(payloads: list[dict]) -> list[dict]:
    nodes: list[dict] = []
    for payload in payloads:
        graph = payload.get("@graph") if isinstance(payload, dict) else None
        nodes.extend(graph if isinstance(graph, list) else [payload])
    return [node for node in nodes if isinstance(node, dict)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="msk")
    parser.add_argument("--base-url", default="https://aptekaa.ru")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    items = json.loads(MEDICATIONS.read_text(encoding="utf-8"))
    expected_keys = {curated_key(item) for item in items}
    docs = list(db.medications.find(
        {"curated_source": SOURCE},
        {"_id": 0, "slug": 1, "name": 1, "dosage": 1, "rx": 1, "curated_key": 1,
         "enrichment.content_version": 1, "enrichment.medical_details_status": 1},
    ).sort("slug", 1))

    errors: list[str] = []
    actual_keys = {doc.get("curated_key") for doc in docs}
    if len(items) != 62:
        errors.append(f"manifest count changed: expected 62, got {len(items)}")
    if len(docs) != len(items) or actual_keys != expected_keys:
        errors.append(
            f"database/manifest mismatch: db={len(docs)} manifest={len(items)} "
            f"missing={len(expected_keys - actual_keys)} extra={len(actual_keys - expected_keys)}"
        )

    seo_sources: dict[str, set[str]] = {}
    price_cursor = db.prices_real.find(
        {
            "slug": {"$in": [doc["slug"] for doc in docs]},
            "source": {"$in": ["gorzdrav", "apteka366", "rigla", "maksavit", "aptechestvo", "zdorovie", "magnit", "farmakopeika"]},
            "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
            "price": {"$gt": 0},
        },
        {"_id": 0, "slug": 1, "source": 1, "city": 1},
    )
    for offer in price_cursor:
        offer_city = offer.get("city") or "msk"
        if offer_city == args.city:
            seo_sources.setdefault(offer["slug"], set()).add(offer["source"])

    rows: list[tuple[str, PageParser]] = []
    robots = Counter()
    for doc in docs:
        slug = doc["slug"]
        url = f"{args.base_url.rstrip('/')}/{args.city}/preparaty/{slug}"
        try:
            request = Request(url, headers={"User-Agent": "YandexBot/3.0"})
            with urlopen(request, timeout=args.timeout) as response:
                if response.status != 200:
                    errors.append(f"{slug}: HTTP {response.status}")
                    continue
                html = response.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - audit must report every URL
            errors.append(f"{slug}: fetch failed: {exc!r}")
            continue

        page = PageParser()
        try:
            page.feed(html)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{slug}: parse failed: {exc!r}")
            continue
        rows.append((slug, page))
        robots_value = page.meta.get("robots", "")
        robots[robots_value or "indexable"] += 1

        visible = " ".join(page.visible)
        nodes = schema_nodes(page.json_ld)
        types = {node.get("@type") for node in nodes}
        drug = next((node for node in nodes if node.get("@type") == "Drug"), {})
        expected_canonical = url
        checks = [
            (doc["name"].casefold() in page.h1.casefold(), f"H1/name mismatch: {page.h1!r}"),
            (not doc.get("dosage") or doc["dosage"].casefold() in page.h1.casefold(), f"H1/dose mismatch: {page.h1!r}"),
            (page.canonical == expected_canonical, f"canonical mismatch: {page.canonical!r}"),
            ("На странице" in visible, "missing visible contents navigation"),
            ("Источники информации" in visible, "missing visible sources"),
            ({"MedicalWebPage", "Drug", "Product", "BreadcrumbList", "FAQPage"} <= types, f"schema types incomplete: {sorted(types)}"),
            (len(page.meta.get("description", "")) <= 220, "description is longer than 220 characters"),
            ("Наличие в аптеках Москвы показывается" not in visible, "hard-coded Moscow availability text leaked"),
            (doc.get("enrichment", {}).get("content_version") == CONTENT_VERSION, "database content version mismatch"),
        ]
        details_are_source_backed = doc.get("enrichment", {}).get("medical_details_status") == "source-backed"
        checks.append((
            ("Основные области применения" in visible) if details_are_source_backed else ("Подробные медицинские сведения не публикуются" in visible),
            "medical detail provenance marker mismatch",
        ))
        expected_indexable = len(seo_sources.get(slug, set())) >= 2
        checks.append((
            ("noindex" not in robots_value) if expected_indexable else ("noindex" in robots_value),
            f"robots/indexability mismatch: expected_indexable={expected_indexable}, robots={robots_value!r}",
        ))
        if doc.get("rx") is None:
            checks.append(("prescriptionStatus" not in drug, "unknown rx is present in Drug schema"))
        for ok, message in checks:
            if not ok:
                errors.append(f"{slug}: {message}")

    for label, values in (
        ("title", [page.title for _, page in rows]),
        ("description", [page.meta.get("description", "") for _, page in rows]),
    ):
        duplicates = [value for value, count in Counter(values).items() if count > 1]
        if duplicates:
            errors.append(f"duplicate {label}: {duplicates!r}")

    if len(rows) != len(docs):
        errors.append(f"not all database cards were fetched: {len(rows)}/{len(docs)}")
    print(f"CARDS={len(docs)} FETCHED={len(rows)} ROBOTS={dict(robots)}")
    if errors:
        print(f"VERIFY FAILED: {len(errors)} error(s)")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)
    print(f"VERIFY OK: {len(rows)} rendered pages match {CONTENT_VERSION}")


if __name__ == "__main__":
    main()
