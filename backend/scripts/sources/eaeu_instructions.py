"""Public EAEU registry metadata reader, with resumable local checkpoints.

The endpoints and collection below are used by the official public SPA:
https://pharma.eaeunion.org/pharma/registers/26/assets/env.json
This adapter uses only its public collection, never an admin/expert collection.
Metadata candidates are NOT verified instruction documents. An attached PDF can
be a dossier project; publication needs an exact identity/version review.
No PDF is downloaded by ``fetch_metadata``. ``download_pdf`` reproduces the
official public download workflow for one explicitly selected source attachment.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlencode

import requests

ORIGIN = "https://pharma.eaeunion.org"
PUBLIC_COLLECTION = "kbdread.service-prop-26-drugRegistrationDetailsTypePublicList"
REGISTRY_BASE = ORIGIN + "/pharma/registers/26/ru/register/registered-medicinal-products/"
DOWNLOAD_BASE = ORIGIN + "/platformsvc/nonauthorizedplatform"
DOWNLOAD_JOB = "5f9495fb-6dd8-43b5-aa74-1e44cf219130"
ATTACHMENT_URI = "/cdb/public/api/registry/P.MM.01/drug-monitoring-items/"
# Keep the source's actual dose objects and file paths. Exclude application
# histories/contact details and unrelated formulation descriptions from bulk I/O.
FIELDS = {
    "_id": 1, "version": 1, "auditInformation": 1,
    "resourceItemStatusDetails": 1, "registrationNumberId": 1,
    "drugDetails.dosageFormDetails": 1,
    "drugDetails.drugNameDetails": 1,
    "drugDetails.packageFormDetails.packageDetails.dosageFormName": 1,
    "drugDetails.packageFormDetails.packageDetails.drugDosageDetails.dosageUnitDetails": 1,
    "drugDetails.packageFormDetails.packageDetails.drugDosageDetails.substanceDetails.drugSubstanceRoleCode": 1,
    "drugDetails.packageFormDetails.packageDetails.drugDosageDetails.substanceDetails.activeSubstanceDetails": 1,
    "drugDetails.packageFormDetails.packageDetails.drugDosageDetails.substanceDetails.substanceMeasure": 1,
    "drugDetails.packageFormDetails.packageDetails.drugDosageDetails.substanceDetails.substanceText": 1,
    "drugDetails.manufacturingAuthorizationHolderDetails.businessEntityName": 1,
    "drugDetails.manufacturingAuthorizationHolderDetails.businessEntityBriefName": 1,
    "drugDetails.manufacturingAuthorizationHolderDetails.manufacturingAreaDetails.businessEntityName": 1,
    "drugDetails.manufacturingAuthorizationHolderDetails.manufacturingAreaDetails.businessEntityBriefName": 1,
    "drugDetails.manufacturingAuthorizationHolderDetails.manufacturingAreaDetails.manufactureStageDetails": 1,
    "drugCountryRegistrationDetails.unifiedCountryCode": 1,
    "drugCountryRegistrationDetails.countryKindCode": 1,
    "drugCountryRegistrationDetails.drugTradeName": 1,
    "drugCountryRegistrationDetails.drugRegistrationCertificateDetails": 1,
    "drugCountryRegistrationDetails.drugDocumentsDetails": 1,
}


class EaeuSourceError(RuntimeError):
    pass


class EaeuAccessError(EaeuSourceError):
    """Stop the source; never retry 401/403 or an actual browser challenge."""


class _Limiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.next_at = 0.0

    def run(self, operation, delay=0):
        with self.lock:
            target = max(self.next_at, time.monotonic() + delay)
            while time.monotonic() < target:
                time.sleep(target - time.monotonic())
            self.next_at = time.monotonic() + 1.0
            return operation()


_LIMITER = _Limiter()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _list(value: Any) -> list:
    return value if isinstance(value, list) else [value] if isinstance(value, dict) else []


def _date(value: Any):
    return value.get("$date") if isinstance(value, Mapping) else value


def normalize_record(record: Mapping[str, Any], retrieved_at: str) -> dict:
    """Return factual metadata, with Russian attachments kept separate.

    Dose measures remain verbatim objects with official unit classifier codes.
    A manufacturer must explicitly list stage 25 (finished medicinal product).
    This function does not infer aliases, old RU equivalence, or approval status.
    """
    oid = record.get("_id", {}).get("$oid")
    if not isinstance(oid, str) or not re.fullmatch(r"[a-f0-9]{24}", oid):
        raise EaeuSourceError("EAEU record has no valid public id")
    drug = record.get("drugDetails") or {}
    manufacturers = []
    for holder in _list(drug.get("manufacturingAuthorizationHolderDetails")):
        for area in _list(holder.get("manufacturingAreaDetails")):
            stages = _list(area.get("manufactureStageDetails"))
            if any(str(stage.get("manufacturingStageCode")) == "25" for stage in stages):
                name = area.get("businessEntityName") or area.get("businessEntityBriefName")
                if isinstance(name, str) and name not in manufacturers:
                    manufacturers.append(name)
    packages = []
    for package_form in _list(drug.get("packageFormDetails")):
        for package in _list(package_form.get("packageDetails")):
            dose = package.get("drugDosageDetails")
            if isinstance(dose, dict):
                packages.append({"form": package.get("dosageFormName"), "dosage": dose})
    ru_registrations = []
    for country in _list(record.get("drugCountryRegistrationDetails")):
        if (country.get("unifiedCountryCode") or {}).get("value") != "RU":
            continue
        certificate = country.get("drugRegistrationCertificateDetails") or {}
        docs = []
        for group in _list(country.get("drugDocumentsDetails")):
            for document in _list(group.get("drugDocumentList")):
                if document.get("drugKindCode") not in ("USAGE_INSTRUCTION", "GENERAL_CHARACTERISTIC"):
                    continue
                file = document.get("uploadedFile") or {}
                path = file.get("path")
                if not isinstance(path, str) or not path or ".." in path or path.startswith(("/", "http:" ,"https:")):
                    continue
                docs.append({
                    "kind": document.get("drugKindCode"), "name": document.get("docName"),
                    "file_name": file.get("name"), "mime_type": file.get("type"),
                    "size": file.get("size"), "uploaded_file_path": path,
                    "created_at": _date(document.get("docCreationDate")),
                    "valid_until": _date(document.get("docValidityDate")),
                    "uploaded_at": _date(document.get("createdCustomDate")),
                    "review_flags": ["source_document_name_mentions_project"]
                        if re.search(r"проект|draft", str(document.get("docName") or ""), re.I) else [],
                    "download_request": {
                        "job_id": DOWNLOAD_JOB,
                        "payload": {"uri": ATTACHMENT_URI + oid + "/files?" + urlencode({"file": path}), "gp": "g"},
                    },
                    "direct_pdf_url": None,
                    "verification_status": "candidate",
                })
        ru_registrations.append({
            "country": "RU", "trade_name": country.get("drugTradeName"),
            "registration_number": certificate.get("registrationCertificateId"),
            "registration_status_code": certificate.get("registrationStatusCode"),
            "registration_status": certificate.get("registrationStatusName"),
            "registered_at": _date(certificate.get("docCreationDate")),
            "valid_until": _date(certificate.get("docValidityDate")),
            "cancelled_at": _date(certificate.get("docCancellationDate")),
            "documents": docs,
        })
    return {
        "record_id": oid, "source_url": REGISTRY_BASE + oid,
        "provider": "eaeu", "retrieved_at": retrieved_at,
        "metadata_sha256": hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest(),
        "source_version": record.get("version"),
        "form": (drug.get("dosageFormDetails") or {}).get("dosageFormName"),
        "manufacturers": manufacturers, "package_dosages": packages,
        "russian_registrations": ru_registrations,
        "text_imported": False, "pdf_downloaded": False,
    }


def rechunk_checkpoints(source_dir, target_dir, *, page_size=250) -> dict:
    """Reuse completed larger pages without another network request.

    A derived checkpoint explicitly retains its parent file/hash/request, so a
    smaller logical page is never presented as a separate physical API fetch.
    Use a distinct target directory and the same ordering/projection.
    """
    if type(page_size) is not int or not 1 <= page_size <= 500:
        raise ValueError("page_size must be between 1 and 500")
    source_dir, target_dir = Path(source_dir), Path(target_dir)
    if source_dir.resolve() == target_dir.resolve():
        raise ValueError("Checkpoint source and target directories must differ")
    target_dir.mkdir(parents=True, exist_ok=True)
    count, pages = 0, 0
    for path in sorted(source_dir.glob("page-*.json")):
        saved = json.loads(path.read_text(encoding="utf-8"))
        request = saved.get("request") or {}
        source_page_size = request.get("page_size", 0)
        source_skip = request.get("skip", -1)
        if (request.get("collection") != PUBLIC_COLLECTION or request.get("fields") != FIELDS
                or request.get("sort") != {"_id": 1} or type(source_skip) is not int or source_skip < 0
                or source_page_size < page_size or source_page_size % page_size or source_skip % page_size):
            raise EaeuSourceError("Checkpoint cannot be safely split into the requested page size")
        payload = saved.get("payload")
        EaeuInstructionClient._validate_page(payload, source_page_size)
        for offset in range(0, len(payload["result"]), page_size):
            skip = source_skip + offset
            derived = {
                "request": {**request, "page_size": page_size, "skip": skip},
                "retrieved_at": saved["retrieved_at"],
                "derived_from": {"checkpoint": str(path.resolve()),
                    "sha256": hashlib.sha256(_canonical(saved).encode("utf-8")).hexdigest(),
                    "original_request": request},
                "payload": {**payload, "result": payload["result"][offset:offset + page_size]},
            }
            target = target_dir / f"page-{page_size:03d}-{skip:06d}.json"
            if target.exists() and json.loads(target.read_text(encoding="utf-8")) != derived:
                raise EaeuSourceError("A different target checkpoint already exists")
            target.write_text(_canonical(derived), encoding="utf-8")
            count += len(derived["payload"]["result"])
            pages += 1
    return {"pages": pages, "records": count, "page_size": page_size}


class EaeuInstructionClient:
    """One process/worker, <=1 request start/s across this source's clients."""

    def __init__(self, *, session=None, limiter=None, max_attempts=3):
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        self._session = session if session is not None else requests.Session()
        self._limiter = limiter if limiter is not None else _LIMITER
        self._max_attempts = max_attempts
        self._stopped = False

    def _request(self, method, url, *, expect_pdf=False, **kwargs):
        if self._stopped:
            raise EaeuAccessError("EAEU source stopped after an access denial/challenge")
        if not url.startswith(ORIGIN + "/"):
            raise EaeuSourceError("EAEU source origin is fixed")
        delay = 0
        for attempt in range(self._max_attempts):
            try:
                response = self._limiter.run(lambda: self._session.request(
                    method, url, timeout=(10, 60), allow_redirects=False, **kwargs), delay=delay)
            except requests.RequestException:
                if attempt + 1 == self._max_attempts:
                    raise EaeuSourceError("EAEU request failed after bounded retries") from None
                delay = 2 ** attempt
                continue
            media_type = response.headers.get("Content-Type", "").lower()
            prefix = response.content[:4096].lstrip().lower()
            safe_prefix = re.sub(r"\s+", " ", response.content[:180].decode("utf-8", errors="replace")).strip()
            if response.status_code in (401, 403):
                status = response.status_code
                response.close()
                self._stopped = True
                raise EaeuAccessError(f"EAEU HTTP {status} access_denied: {safe_prefix}")
            if not response.content.startswith(b"%PDF-") and re.search(rb"captcha|cf-chl|challenge-platform|checking your browser", prefix, re.I):
                status = response.status_code
                response.close()
                self._stopped = True
                raise EaeuAccessError(f"EAEU HTTP {status} browser_challenge: {safe_prefix}")
            if response.status_code == 429 or 500 <= response.status_code < 600:
                status = response.status_code
                retry_after = response.headers.get("Retry-After", "")
                response.close()
                if attempt + 1 == self._max_attempts:
                    raise EaeuSourceError(f"EAEU HTTP {status} transient_error after bounded retries: {safe_prefix}")
                delay = min(30, max(2 ** attempt, int(retry_after) if str(retry_after).isdigit() else 0))
                continue
            if "text/html" in media_type or prefix.startswith((b"<html", b"<!doctype html")):
                status = response.status_code
                response.close()
                raise EaeuSourceError(f"EAEU HTTP {status} unexpected_html: {safe_prefix}")
            if response.status_code != 200:
                status = response.status_code
                response.close()
                raise EaeuSourceError(f"EAEU HTTP {status}; request stopped")
            return response
        raise EaeuSourceError("EAEU bounded request failed")

    def fetch_page(self, *, skip=0, page_size=500) -> dict:
        if type(skip) is not int or skip < 0 or type(page_size) is not int or not 1 <= page_size <= 500:
            raise ValueError("skip must be >=0; page_size must be between 1 and 500")
        response = self._request("POST", ORIGIN + "/spd2/find", params={
            "collection": PUBLIC_COLLECTION, "limit": page_size, "skip": skip,
            "sort": _canonical({"_id": 1}), "fields": _canonical(FIELDS),
        }, data="{}", headers={"Content-Type": "text/plain"})
        try:
            payload = response.json()
        except ValueError:
            raise EaeuSourceError("EAEU returned invalid JSON") from None
        finally:
            response.close()
        self._validate_page(payload, page_size)
        return payload

    @staticmethod
    def _validate_page(payload, page_size):
        if not isinstance(payload, dict) or not isinstance(payload.get("result"), list):
            raise EaeuSourceError("EAEU page result is missing")
        if type(payload.get("matchedDocuments")) is not int or payload["matchedDocuments"] < 0:
            raise EaeuSourceError("EAEU page total is missing")
        if len(payload["result"]) > page_size or any(not isinstance(row, dict) for row in payload["result"]):
            raise EaeuSourceError("EAEU page result is invalid")

    def fetch_metadata(self, checkpoint_dir, output_path, *, page_size=500, max_pages=100, on_progress=None):
        """Read public metadata to JSONL, resuming matching raw page checkpoints.

        A max_pages truncation is explicit in the returned summary. Never treat
        a truncated or changed-total run as full registry coverage.
        """
        if type(max_pages) is not int or not 1 <= max_pages <= 1000:
            raise ValueError("max_pages must be between 1 and 1000")
        if type(page_size) is not int or not 1 <= page_size <= 500:
            raise ValueError("page_size must be between 1 and 500")
        checkpoint_dir = Path(checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp = output_path.with_suffix(output_path.suffix + ".partial")
        count, expected_total, ids = 0, None, set()
        complete = False
        with temp.open("w", encoding="utf-8") as output:
            for page_index in range(max_pages):
                skip = page_index * page_size
                path = checkpoint_dir / f"page-{page_size:03d}-{skip:06d}.json"
                request = {"collection": PUBLIC_COLLECTION, "skip": skip,
                           "page_size": page_size, "fields": FIELDS, "sort": {"_id": 1}}
                if path.exists():
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    if saved.get("request") != request:
                        raise EaeuSourceError("EAEU checkpoint request differs; use a new directory")
                else:
                    payload = self.fetch_page(skip=skip, page_size=page_size)
                    saved = {"request": request, "retrieved_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
                    temporary = path.with_suffix(".partial")
                    temporary.write_text(_canonical(saved), encoding="utf-8")
                    temporary.replace(path)
                payload = saved["payload"]
                self._validate_page(payload, page_size)
                if expected_total is None:
                    expected_total = payload["matchedDocuments"]
                elif expected_total != payload["matchedDocuments"]:
                    raise EaeuSourceError("EAEU total changed during pagination; snapshot needs review")
                for record in payload["result"]:
                    metadata = normalize_record(record, saved["retrieved_at"])
                    if metadata["record_id"] in ids:
                        raise EaeuSourceError("EAEU pagination repeated a record; snapshot needs review")
                    ids.add(metadata["record_id"])
                    output.write(_canonical(metadata) + "\n")
                    count += 1
                if on_progress is not None:
                    on_progress({"records": count, "expected_records": expected_total,
                                 "page": page_index + 1, "page_size": page_size})
                if skip + len(payload["result"]) >= expected_total:
                    complete = True
                    break
                if len(payload["result"]) < page_size:
                    raise EaeuSourceError("EAEU pagination ended before the declared total")
        temp.replace(output_path)
        return {"records": count, "expected_records": expected_total,
                "complete": complete, "output_path": str(output_path), "pdf_downloaded": 0}

    def download_pdf(self, candidate, destination, *, max_bytes=25_000_000, max_polls=30):
        """Download one candidate through the exact official public workflow.

        Result is an original artifact needing review, never an approval signal.
        ``download_url`` is a temporary workflow URL, not a durable public link.
        """
        download_request = candidate.get("download_request") or {}
        payload = download_request.get("payload") or {}
        uri = payload.get("uri", "")
        resource = re.fullmatch(re.escape(ATTACHMENT_URI) + r"([a-f0-9]{24})/files\?(.+)", str(uri))
        query = parse_qs(resource.group(2)) if resource else {}
        actual_path = candidate.get("uploaded_file_path")
        if (download_request.get("job_id") != DOWNLOAD_JOB or payload.get("gp") != "g"
                or not resource or list(query) != ["file"] or query["file"] != [actual_path]
                or not isinstance(actual_path, str) or ".." in actual_path
                or actual_path.startswith(("/", "http:", "https:"))):
            raise EaeuSourceError("Candidate has no verified public attachment request")
        declared_size = candidate.get("size")
        if type(max_bytes) is not int or not 1 <= max_bytes <= 100_000_000:
            raise ValueError("max_bytes must be between 1 and 100000000")
        if type(declared_size) is int and declared_size > max_bytes:
            raise EaeuSourceError("Declared EAEU attachment exceeds the download limit")
        response = self._request("POST", DOWNLOAD_BASE + "/executewithjson", params={"jobid": DOWNLOAD_JOB, "operation": "update"},
                                 data=_canonical(payload), headers={"Content-Type": "plain/text;charset=utf-8"})
        try:
            instance_id = response.json()
        finally:
            response.close()
        if not isinstance(instance_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", instance_id):
            raise EaeuSourceError("EAEU download workflow id is invalid")
        for _ in range(max_polls):
            response = self._request("GET", DOWNLOAD_BASE + "/status", params={"instanceid": instance_id})
            try:
                status = response.json()
            finally:
                response.close()
            if status.get("status") != 2:
                break
        else:
            raise EaeuSourceError("EAEU download workflow exceeded bounded polling")
        if status.get("status") != 0 or status.get("instanceid") != instance_id:
            raise EaeuSourceError("EAEU download workflow failed")
        response = self._request("GET", DOWNLOAD_BASE + "/gettoken", params={"instanceid": instance_id})
        try:
            token = response.json()
        finally:
            response.close()
        file_id = next((value.get("stringvalue") for value in token.get("parameters", []) if value.get("name") == "fileid"), None)
        if not isinstance(file_id, str) or not file_id:
            raise EaeuSourceError("EAEU download workflow has no file id")
        params = {"id": file_id, "instanceid": instance_id}
        response = self._request("GET", DOWNLOAD_BASE + "/filedownload", params=params, expect_pdf=True)
        try:
            body = response.content
            if len(body) > max_bytes or not body.startswith(b"%PDF-"):
                raise EaeuSourceError("EAEU attachment is oversized or not a PDF")
        finally:
            response.close()
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        return {"path": str(destination), "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "download_url": DOWNLOAD_BASE + "/filedownload?" + urlencode(params),
                "download_url_is_temporary": True, "verification_status": "candidate"}
