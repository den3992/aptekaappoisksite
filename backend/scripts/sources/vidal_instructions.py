"""Read-only adapter for a *licensed* Vidal API account.

Contract: ``normalize_product`` returns a draft canonical instruction document.
It copies provider text, never creates medical advice, and never verifies itself.
``completeness`` only reports presence of the eight required sections; it does
not establish that a monograph is an entire approved instruction. Missing dates,
manufacturers, GTIN links, or sections are left missing for the core validator.

API schema: https://www.vidal.ru/doc/api/rest (checked 2026-11-15).
Access and redistribution rights must be supplied by the operator through
VIDAL_API_TOKEN and VIDAL_RIGHTS_BASIS; public website access is not a license.
This module has no database writes or command-line entry point.
"""
from __future__ import annotations

import html
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable, Mapping
from urllib.parse import urljoin, urlsplit

import requests

from api.medication_instructions import instruction_content_hash


API_BASE = "https://www.vidal.ru/api/rest/v1"
REQUIRED_SECTIONS = (
    "composition", "indications", "contraindications", "administration",
    "side_effects", "interactions", "overdose", "storage",
)
SECTION_FIELDS = (
    ("indications", "Показания к применению", "indication"),
    ("contraindications", "Противопоказания", "contraIndication"),
    ("administration", "Способ применения и дозы", "dosage"),
    ("side_effects", "Побочные действия", "sideEffects"),
    ("interactions", "Взаимодействие с другими препаратами", "interaction"),
    ("overdose", "Передозировка", "overDosage"),
    ("pregnancy_lactation", "Беременность и грудное вскармливание", "lactation"),
    ("special_instructions", "Особые указания", "specialInstruction"),
    ("pharmacodynamics", "Фармакологическое действие", "phInfluence"),
    ("pharmacokinetics", "Фармакокинетика", "phKinetics"),
    ("renal_impairment", "Нарушения функции почек", "renalInsuf"),
    ("hepatic_impairment", "Нарушения функции печени", "hepatoInsuf"),
    ("children", "Применение у детей", "childInsuf"),
    ("elderly", "Применение у пожилых пациентов", "elderlyInsuf"),
    ("dispensing", "Условия отпуска", "pharmDelivery"),
)


class VidalError(RuntimeError):
    """Safe operational error: messages never contain headers or response text."""


class VidalAccessError(VidalError):
    """Credentials, access denial, or challenge; do not retry or work around."""


class VidalProtocolError(VidalError):
    """Unexpected provider schema or response; do not silently accept it."""


class VidalRateLimiter:
    """Serialize every request, including retries, with at most two starts/s.

    The default singleton is shared across clients in this process. The import
    command must use one process/worker; this is not a distributed rate limiter.
    Keeping the lock throughout the request also limits concurrency to one.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self._clock = clock
        self._sleep = sleep
        self._next_start = 0.0
        self._lock = threading.Lock()

    def run(self, operation: Callable[[], Any], *, delay: float = 0) -> Any:
        with self._lock:
            now = self._clock()
            target = max(self._next_start, now + max(0, delay))
            # A loop also handles early-returning sleeps without violating rps.
            while self._clock() < target:
                self._sleep(target - self._clock())
            self._next_start = self._clock() + 0.5
            return operation()


_SHARED_LIMITER = VidalRateLimiter()


class VidalInstructionClient:
    """Bounded synchronous API reader. Requires explicitly configured rights.

    Injecting ``session``/``limiter`` is intended for offline tests only. The
    production origin is fixed, TLS verification remains enabled, and redirects
    are rejected so the token cannot be forwarded to another origin.
    """

    def __init__(self, token: str, rights_basis: str, *, session: Any = None,
                 limiter: VidalRateLimiter | None = None,
                 timeout: tuple[float, float] = (5, 20), max_attempts: int = 3):
        if not isinstance(token, str) or not token.strip():
            raise VidalAccessError("VIDAL_API_TOKEN is required")
        if not isinstance(rights_basis, str) or not rights_basis.strip():
            raise VidalAccessError("VIDAL_RIGHTS_BASIS is required")
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if len(timeout) != 2 or any(value <= 0 or value > 60 for value in timeout):
            raise ValueError("timeout must contain two positive values up to 60s")
        self._token = token.strip()
        self.rights_basis = rights_basis.strip()
        self._session = session if session is not None else requests.Session()
        self._limiter = limiter if limiter is not None else _SHARED_LIMITER
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._access_stopped = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kwargs: Any):
        config = os.environ if env is None else env
        return cls(config.get("VIDAL_API_TOKEN", ""),
                   config.get("VIDAL_RIGHTS_BASIS", ""), **kwargs)

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> dict:
        if self._access_stopped:
            raise VidalAccessError("Vidal client stopped after an access denial or challenge")
        delay = 0.0
        for attempt in range(self._max_attempts):
            response = None
            try:
                response = self._limiter.run(
                    lambda: self._session.get(
                        API_BASE + path, params=dict(params or {}),
                        headers={"X-Token": self._token, "Accept": "application/json"},
                        timeout=self._timeout, allow_redirects=False,
                    ), delay=delay,
                )
            except requests.RequestException:
                # Do not propagate an exception that may echo request headers.
                if attempt + 1 == self._max_attempts:
                    raise VidalError("Vidal network request failed after bounded retries") from None
                delay = float(2 ** attempt)
                continue
            try:
                status = response.status_code
                media_type = response.headers.get("Content-Type", "").lower()
                prefix = response.text[:4096].lstrip().lower()
                if status in (401, 403):
                    self._access_stopped = True
                    raise VidalAccessError("Vidal denied access")
                is_html = "text/html" in media_type or prefix.startswith(("<!doctype html", "<html"))
                if is_html and re.search(r"captcha|cf-chl|challenge-platform|checking your browser", prefix, re.I):
                    self._access_stopped = True
                    raise VidalAccessError("Vidal returned a browser challenge")
                payload = None
                if "json" in media_type or prefix.startswith("{"):
                    try:
                        payload = response.json()
                    except (ValueError, TypeError):
                        pass
                if isinstance(payload, dict):
                    error_hint = " ".join(str(payload.get(key, "")) for key in ("errorMsg", "error", "message"))
                    if re.search(r"captcha|капч|challenge", error_hint, re.I):
                        self._access_stopped = True
                        raise VidalAccessError("Vidal returned a challenge; request stopped")
                if status == 429 or 500 <= status <= 599:
                    if attempt + 1 == self._max_attempts:
                        raise VidalError(f"Vidal HTTP {status} after bounded retries")
                    retry_after = response.headers.get("Retry-After", "")
                    delay = min(30.0, max(float(2 ** attempt),
                                float(retry_after) if re.fullmatch(r"\d+(?:\.\d+)?", retry_after) else 0))
                    continue
                if status != 200:
                    raise VidalError(f"Vidal HTTP {status}; request stopped")
                if is_html:
                    raise VidalProtocolError("Vidal returned unexpected HTML")
                if payload is None:
                    try:
                        payload = response.json()
                    except (ValueError, TypeError):
                        raise VidalProtocolError("Vidal returned invalid JSON") from None
                if not isinstance(payload, dict):
                    raise VidalProtocolError("Vidal response must be a JSON object")
                if payload.get("success") is not True:
                    raise VidalProtocolError("Vidal reported an unsuccessful API response")
                return payload
            finally:
                response.close()
        raise VidalError("Vidal bounded request failed")  # defensive

    def _find(self, filter_name: str, value: str, *, max_pages: int = 20) -> list[dict]:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Exact lookup value must not be empty")
        if not 1 <= max_pages <= 100:
            raise ValueError("max_pages must be between 1 and 100")
        products: list[dict] = []
        for page in range(1, max_pages + 1):
            payload = self._get("/product/list", {filter_name: value.strip(), "page": page, "limit": 100})
            rows = payload.get("products")
            pagination = payload.get("pagination")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise VidalProtocolError("Vidal products must be an array of objects")
            if not isinstance(pagination, dict):
                raise VidalProtocolError("Vidal product pagination is missing")
            page_count = pagination.get("pageCount")
            if type(page_count) is not int or page_count < 0 or pagination.get("page") != page:
                raise VidalProtocolError("Vidal product pagination is invalid")
            products.extend(rows)
            if page_count <= page:
                return products
        raise VidalProtocolError("Vidal lookup exceeded max_pages; partial matches were rejected")

    def find_by_barcode(self, barcode: str, **kwargs: Any) -> list[dict]:
        if not isinstance(barcode, str) or not re.fullmatch(r"\d{8}|\d{12,14}", barcode):
            raise ValueError("Barcode must contain 8, 12, 13 or 14 digits")
        return self._find("filter[barCode]", barcode, **kwargs)

    def find_by_registration_number(self, registration_number: str, **kwargs: Any) -> list[dict]:
        return self._find("filter[registrationNumber]", registration_number, **kwargs)

    @staticmethod
    def _id(value: int | str) -> str:
        if isinstance(value, bool) or not re.fullmatch(r"[1-9]\d*", str(value)):
            raise ValueError("Vidal id must be a positive integer")
        return str(value)

    def get_product(self, product_id: int | str) -> dict:
        product = self._get(f"/product/{self._id(product_id)}/get").get("product")
        if not isinstance(product, dict) or str(product.get("id")) != str(product_id):
            raise VidalProtocolError("Vidal product identity did not match the request")
        return product

    def get_document(self, document_id: int | str) -> dict:
        document = self._get(f"/document/{self._id(document_id)}/get").get("document")
        if not isinstance(document, dict) or str(document.get("documentId")) != str(document_id):
            raise VidalProtocolError("Vidal document identity did not match the request")
        return document


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: Any):
        if tag in ("script", "style", "iframe", "noscript"):
            self.hidden += 1
        if tag in ("td", "th"):
            self.parts.append(" ")
        if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag in ("script", "style", "iframe", "noscript"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_data(self, data: str):
        if not self.hidden:
            self.parts.append(data)


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    parser = _TextExtractor()
    parser.feed(value)
    return "\n".join(line for line in
        (re.sub(r"\s+", " ", html.unescape(part)).strip()
         for part in "".join(parser.parts).splitlines()) if line).strip()


def normalize_product(product: Mapping[str, Any], *, rights_basis: str,
                      retrieved_at: str | None = None,
                      document: Mapping[str, Any] | None = None) -> dict:
    """Copy a Product + linked Document into a non-publishable draft.

    Only package GTINs explicitly linked to this Product become scopes. The API
    does not define a separate, unambiguous strength field, so the adapter never
    guesses RU/form/dose scopes from marketing names or dosing paragraphs.
    Holder companies never become manufacturers. A supplied separate document
    must have the same documentId as the Product's embedded reference.
    """
    if not isinstance(rights_basis, str) or not rights_basis.strip():
        raise VidalAccessError("A configured rights basis is required")
    product_id = product.get("id")
    VidalInstructionClient._id(product_id)
    embedded = product.get("document")
    if not isinstance(embedded, Mapping) or not embedded.get("documentId"):
        raise VidalProtocolError("Product has no linked instruction document")
    chosen = embedded if document is None else document
    if str(chosen.get("documentId")) != str(embedded.get("documentId")):
        raise VidalProtocolError("Document is not linked to the Product")
    sections: list[dict] = []
    composition = _text(product.get("composition"))
    if composition:
        sections.append({"key": "composition", "title": "Состав", "text": composition})
    for key, title, field in SECTION_FIELDS:
        content = _text(chosen.get(field))
        if content:
            sections.append({"key": key, "title": title, "text": content})
    for key, title, field in (("storage", "Условия хранения", "storageCondition"),
                              ("shelf_life", "Срок годности", "storageTime")):
        content = _text(chosen.get(field))
        if content:
            sections.append({"key": key, "title": title, "text": content})
    missing = [key for key in REQUIRED_SECTIONS if key not in {part["key"] for part in sections}]
    manufacturers: list[str] = []
    holders: list[str] = []
    for company_link in product.get("companies") or []:
        if not isinstance(company_link, Mapping):
            continue
        company = company_link.get("company")
        name = _text(company.get("name")) if isinstance(company, Mapping) else ""
        if not name:
            continue
        if company_link.get("isManufacturer") is True and name not in manufacturers:
            manufacturers.append(name)
        if company_link.get("isRegistrationCertificate") is True and name not in holders:
            holders.append(name)
    gtins: list[str] = []
    for package in product.get("productPackages") or []:
        if not isinstance(package, Mapping) or str(package.get("productId")) != str(product_id):
            continue
        gtin = package.get("barCode")
        if isinstance(gtin, str) and re.fullmatch(r"\d{8}|\d{12,14}", gtin) and gtin not in gtins:
            gtins.append(gtin)
    source_url = urljoin("https://www.vidal.ru", str(product.get("productUrl") or ""))
    parsed_url = urlsplit(source_url)
    if (parsed_url.scheme != "https"
            or parsed_url.hostname not in ("vidal.ru", "www.vidal.ru")
            or parsed_url.username is not None or parsed_url.password is not None
            or not parsed_url.path or parsed_url.path == "/"):
        source_url = ""  # missing provenance must remain visible to core validation
    retrieved_at = retrieved_at or datetime.now(timezone.utc).isoformat()
    registration_number = _text(product.get("registrationNumber"))
    version = _text(chosen.get("updatedAt")) or _text(chosen.get("yearEdition"))
    original_sha256 = hashlib.sha256(json.dumps(
        {"product": product, "document": chosen}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {
        "id": f"vidal:{product_id}:{chosen.get('documentId')}",
        "title": _text(product.get("rusNameClear")) or _text(product.get("rusName")),
        "registration_numbers": [registration_number] if registration_number else [],
        "version": version,
        "approved_at": None,
        "retrieved_at": retrieved_at,
        "source": {
            "name": "Видаль", "provider": "vidal", "url": source_url,
            "source_product_id": str(product_id),
            "source_document_id": str(chosen.get("documentId")),
            "rights_basis": rights_basis.strip(),
        },
        "original_url": source_url,
        "original_sha256": original_sha256,
        "content_hash": instruction_content_hash(sections),
        "verification": {"status": "draft", "verified_at": None, "verified_by": None},
        "completeness": {"is_complete": not missing,
                         "full_document_confirmed": False,
                         "required_sections": list(REQUIRED_SECTIONS), "missing_sections": missing},
        "identity": {"trade_name": _text(product.get("rusNameClear")) or _text(product.get("rusName")),
                     "manufacturers": manufacturers},
        "scopes": [{"gtin": gtin} for gtin in gtins],
        "sections": sections,
        "source_scope": {
            "document_kind": "provider_monograph", "full_official_document_confirmed": False,
            "product_is_valid": product.get("isValid"),
            "product_type_code": product.get("productTypeCode"),
            "previous_registration_number": product.get("regPreviousNumber"),
            "registration_closed_at": product.get("dateOfCloseRegistration"),
            "product_updated_at": product.get("updatedAt"),
            "document_updated_at": chosen.get("updatedAt"),
            "holders": holders,
            "zip_info": product.get("zipInfo"), "full_form": product.get("fullForm"),
            "forms": product.get("forms"),
            "restrictions": {key: chosen.get(key) for key in (
                "pregnancyUsing", "nursingUsing", "renalInsufUsing",
                "hepatoInsufUsing", "elderlyInsufUsing", "childInsufUsing",
            ) if key in chosen},
        },
    }
