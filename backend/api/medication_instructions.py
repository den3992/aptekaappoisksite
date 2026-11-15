"""Verified, variant-specific medication instructions; no writes or source fetching."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from collections import OrderedDict
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .async_cache import AsyncTTLValue


logger = logging.getLogger(__name__)
REQUIRED_SECTIONS = frozenset({
    "composition", "indications", "contraindications", "administration",
    "side_effects", "interactions", "overdose", "storage",
})
MAX_DOCUMENTS = 32
MAX_BINDINGS = 128
MAX_SECTIONS = 128
MAX_TEXT_LENGTH = 500_000


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")
        if tag in {"td", "th"}:
            # Preserve cell boundaries in dosage and other source tables.
            self.parts.append(" | ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("text must be a string")
    parser = _TextParser()
    parser.feed(value)
    parser.close()
    return "\n".join(
        line for line in (re.sub(r"\s+", " ", part).strip() for part in "".join(parser.parts).splitlines())
        if line
    )


def _identity(value) -> str:
    text = str(value or "").replace("®", "").replace("™", "")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def _ru(value) -> str:
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).upper()
    # N and the number sign are spelling variants of the number marker only.
    # Never strip letters/digits, procedure suffixes, or registration prefixes.
    return re.sub(r"^((?:ЛП|ЛСР|П|Р)-?)(?:NO|N)(?=[(\d])", r"\1N", text)


def _gtin(value) -> str:
    value = str(value or "").strip()
    if not re.fullmatch(r"(?:[0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14})", value):
        return ""
    # GS1 identifiers with leading zeroes denote the same trade item.
    return value.zfill(14)


def _required_text(value, field) -> str:
    value = plain_text(value) if isinstance(value, str) else ""
    if not value:
        raise ValueError(f"{field} is required")
    return value


def _object(value, field) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _url(value, field) -> str:
    value = _required_text(value, field)
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{field} must be a public HTTP(S) URL without credentials")
    return value


def _timestamp(value, field) -> str:
    value = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field} must be ISO 8601") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return value


def _sha256(value, field) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", value):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return value.lower()


def _sections(sections) -> list[dict]:
    if not isinstance(sections, list) or not 1 <= len(sections) <= MAX_SECTIONS:
        raise ValueError("sections must be a bounded nonempty list")
    result, seen = [], set()
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("section must be an object")
        key = _required_text(section.get("key"), "section.key")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in seen:
            raise ValueError("section keys must be unique ASCII identifiers")
        seen.add(key)
        result.append({
            "key": key, "title": _required_text(section.get("title"), "section.title"),
            "text": _required_text(section.get("text"), "section.text"),
        })
    if sum(len(section["text"]) for section in result) > MAX_TEXT_LENGTH:
        raise ValueError("instruction text is too large")
    return result


def instruction_content_hash(sections: list[dict]) -> str:
    """Hash the complete ordered list after deterministic HTML-to-text conversion."""
    payload = json.dumps(_sections(sections), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_document(document: dict) -> dict:
    """Return a validated plain-text copy; reject draft, partial or unscoped data."""
    if not isinstance(document, dict):
        raise ValueError("document must be an object")
    verification = _object(document.get("verification"), "verification")
    if verification.get("status") != "verified":
        raise ValueError("document is not verified")
    verified_at = _timestamp(verification.get("verified_at"), "verification.verified_at")
    verified_by = _required_text(verification.get("verified_by"), "verification.verified_by")
    completeness = _object(document.get("completeness"), "completeness")
    sections = _sections(document.get("sections"))
    keys = {section["key"] for section in sections}
    declared_required = completeness.get("required_sections")
    if (
        completeness.get("is_complete") is not True
        or completeness.get("full_document_confirmed") is not True
        or completeness.get("missing_sections") != []
        or not isinstance(declared_required, list)
        or any(not isinstance(key, str) for key in declared_required)
        or not REQUIRED_SECTIONS.issubset(set(declared_required))
        or not set(declared_required).issubset(keys)
    ):
        raise ValueError("document does not contain every required source section")
    content_hash = _sha256(document.get("content_hash"), "content_hash")
    if content_hash != instruction_content_hash(sections):
        raise ValueError("content_hash does not match all sections")
    source = _object(document.get("source"), "source")
    source = {
        **{key: _required_text(source.get(key), f"source.{key}") for key in (
            "name", "provider", "source_document_id", "rights_basis",
        )},
        "url": _url(source.get("url"), "source.url"),
        "kind": source.get("kind", "licensed_reference"),
    }
    if document.get("source", {}).get("source_product_id") is not None:
        source["source_product_id"] = str(document["source"]["source_product_id"])
    identity_input = _object(document.get("identity"), "identity")
    identity = identity_input
    manufacturers = identity.get("manufacturers", [])
    if identity.get("manufacturer") and not manufacturers:
        manufacturers = [identity["manufacturer"]]
    if not isinstance(manufacturers, list):
        raise ValueError("identity.manufacturers must be a list")
    identity = {
        "trade_name": _required_text(identity.get("trade_name"), "identity.trade_name"),
        "manufacturers": [_required_text(item, "identity.manufacturers") for item in manufacturers],
        **{
            key: _required_text(identity_input[key], f"identity.{key}")
            for key in ("form", "dosage") if identity_input.get(key)
        },
    }
    numbers = document.get("registration_numbers")
    if not isinstance(numbers, list) or any(not isinstance(number, str) or not _ru(number) for number in numbers):
        raise ValueError("registration_numbers must be a list of registration numbers")
    # Normalize only comparison keys; retain official typography for display.
    display_numbers = {}
    for number in numbers:
        display_numbers.setdefault(_ru(number), number.strip())
    numbers = list(display_numbers.values())
    number_keys = set(display_numbers)
    scopes = document.get("scopes")
    if not isinstance(scopes, list) or not scopes or len(scopes) > 10000:
        raise ValueError("explicit product scopes are required")
    validated_scopes = []
    for scope in scopes:
        if not isinstance(scope, dict):
            raise ValueError("scope must be an object")
        gtin, number = _gtin(scope.get("gtin")), _ru(scope.get("ru_number"))
        if scope.get("gtin") and not gtin:
            raise ValueError("scope.gtin is invalid")
        if number and number not in number_keys:
            raise ValueError("scope RU is absent from registration_numbers")
        form, dosage = plain_text(scope.get("form") or ""), plain_text(scope.get("dosage") or "")
        if not gtin and not (number and form and dosage):
            raise ValueError("scope requires exact GTIN or RU + form + dosage")
        registration_wide = scope.get("manufacturer_scope") == "registration-wide"
        if not gtin and not identity["manufacturers"] and not (
            registration_wide and source["kind"] == "official_registry"
        ):
            raise ValueError("RU scope manufacturer identity is ambiguous")
        validated_scopes.append({
            "gtin": gtin or None, "ru_number": number or None, "form": form or None,
            "dosage": dosage or None,
            **({"manufacturer_scope": "registration-wide"} if registration_wide else {}),
        })
    approved_at = document.get("approved_at")
    if approved_at is not None:
        try:
            datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("approved_at must be an ISO date or null") from None
    return {
        "id": _required_text(document.get("id"), "id"),
        "title": _required_text(document.get("title"), "title"),
        "registration_numbers": numbers,
        "version": _required_text(document.get("version"), "version"),
        "approved_at": approved_at,
        "retrieved_at": _timestamp(document.get("retrieved_at"), "retrieved_at"),
        "source": source, "original_url": _url(document.get("original_url"), "original_url"),
        "original_sha256": _sha256(document.get("original_sha256"), "original_sha256"),
        "content_hash": content_hash, "identity": identity, "scopes": validated_scopes,
        "sections": sections,
        "verification": {"status": "verified", "verified_at": verified_at, "verified_by": verified_by},
        "completeness": {
            "is_complete": True, "full_document_confirmed": True,
            "required_sections": declared_required, "missing_sections": [],
        },
    }


def _variant(med, variant) -> dict:
    return {
        "gtin": str(variant.get("gtin") or "").strip() or None,
        "ru_number": str(variant.get("ru_number") or "").strip() or None,
        "pack_size": str(variant.get("pack_size") or "").strip() or None,
        "form": str(variant.get("form") or med.get("form") or "").strip() or None,
        "dosage": str(variant.get("dosage") or med.get("dosage") or "").strip() or None,
    }


def _variant_key(variant) -> tuple:
    return (
        _gtin(variant.get("gtin")), _ru(variant.get("ru_number")),
        *(_identity(variant.get(key)) for key in ("pack_size", "form", "dosage")),
    )


def medication_identity_fingerprint(med: dict) -> str:
    payload = {
        **{key: _identity(med.get(key)) for key in ("slug", "name", "manufacturer", "form", "dosage")},
        "ru_number": _ru(med.get("ru_number")), "canonical": med.get("is_canonical") is not False,
        "variants": sorted(_variant_key(_variant(med, variant)) for variant in (med.get("variants") or [])),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def match_document_to_medication(document: dict, med: dict) -> dict:
    document = validate_document(document)
    variants = med.get("variants") or []
    result = {
        "matched": False, "identity_fingerprint": medication_identity_fingerprint(med),
        "bindings": [], "total_variants": len(variants), "covered_variants": 0,
        "fully_covered": False, "reasons": [],
    }
    if not med.get("slug") or med.get("is_canonical") is False:
        result["reasons"].append("medication is not canonical")
        return result
    identity = document["identity"]
    if _identity(med.get("name")) != _identity(identity["trade_name"]):
        result["reasons"].append("trade name differs")
        return result
    if identity["manufacturers"] and _identity(med.get("manufacturer")) not in {
        _identity(value) for value in identity["manufacturers"]
    }:
        result["reasons"].append("explicit manufacturer differs")
        return result
    for raw_variant in variants:
        variant = _variant(med, raw_variant)
        for scope in document["scopes"]:
            if scope["gtin"]:
                if _gtin(variant["gtin"]) != scope["gtin"]:
                    continue
                if variant["ru_number"] and document["registration_numbers"] and _ru(variant["ru_number"]) not in {_ru(number) for number in document["registration_numbers"]}:
                    continue
            elif not variant["ru_number"] or _ru(variant["ru_number"]) != scope["ru_number"]:
                continue
            if scope["ru_number"] and variant["ru_number"] and _ru(variant["ru_number"]) != scope["ru_number"]:
                continue
            if any(
                (scope[key] or identity.get(key))
                and _identity(scope[key] or identity.get(key)) != _identity(variant[key])
                for key in ("form", "dosage")
            ):
                continue
            result["bindings"].append(variant)
            break
    result["covered_variants"] = len(result["bindings"])
    result["matched"] = bool(result["bindings"])
    result["fully_covered"] = bool(variants) and len(result["bindings"]) == len(variants)
    if not result["matched"]:
        result["reasons"].append("no exact variant scope matched")
    return result


class MedicationInstructionService:
    """Bounded city-independent cache; failed loads never become cached emptiness."""
    def __init__(self, db, *, capacity=64, ttl=60, load_timeout=3):
        if capacity < 1 or ttl <= 0 or load_timeout <= 0:
            raise ValueError("instruction cache bounds must be positive")
        self.db, self.capacity, self.ttl, self.load_timeout = db, capacity, ttl, load_timeout
        self.cache = OrderedDict()

    async def _load(self, med):
        fingerprint = medication_identity_fingerprint(med)
        rows = await self.db.medication_instruction_bindings.find({
            "medicine_slug": med["slug"], "identity_fingerprint": fingerprint,
            "status": "verified", "active": True,
        }, {"_id": 0}).max_time_ms(1500).to_list(MAX_BINDINGS + 1)
        if len(rows) > MAX_BINDINGS:
            raise ValueError("too many instruction bindings")
        ids = list(dict.fromkeys(row.get("document_id") for row in rows if row.get("document_id")))
        if len(ids) > MAX_DOCUMENTS:
            raise ValueError("too many instruction documents")
        if not ids:
            return []
        documents = await self.db.instruction_documents.find({"id": {"$in": ids}}, {"_id": 0}).max_time_ms(1500).to_list(MAX_DOCUMENTS + 1)
        if len(documents) > MAX_DOCUMENTS or len({doc.get("id") for doc in documents}) != len(documents):
            raise ValueError("ambiguous instruction document ids")
        published = []
        for raw_document in documents:
            try:
                document = validate_document(raw_document)
                matched = match_document_to_medication(document, med)
            except (ValueError, TypeError, KeyError):
                logger.warning("Rejected invalid instruction document for %s", med.get("slug"))
                continue
            allowed = {_variant_key(binding): binding for binding in matched["bindings"]}
            bound = {}
            for row in rows:
                if (
                    row.get("document_id") != document["id"] or row.get("status") != "verified"
                    or row.get("active") is not True or row.get("identity_fingerprint") != fingerprint
                    or row.get("medicine_slug") != med["slug"]
                ):
                    continue
                for binding in row.get("variant_bindings") or []:
                    key = _variant_key(binding)
                    if key in allowed:
                        bound[key] = allowed[key]
            if bound:
                published.append({
                    **{key: document[key] for key in (
                        "id", "title", "registration_numbers", "version", "approved_at", "retrieved_at",
                        "original_url", "sections",
                    )},
                    "source": {key: document["source"][key] for key in ("name", "url")},
                    "bindings": list(bound.values()),
                })
        return published

    async def attach(self, med: dict) -> dict:
        variants = med.get("variants") or []
        med["instructions"] = []
        med["instruction_coverage"] = {
            "total_variants": len(variants), "covered_variants": 0, "fully_covered": False,
        }
        if not med.get("slug"):
            return med
        key = (med["slug"], medication_identity_fingerprint(med))
        if key not in self.cache:
            self.cache[key] = AsyncTTLValue(
                lambda: self._load(med), ttl=self.ttl, load_timeout=self.load_timeout,
                name="medication instructions",
            )
        self.cache.move_to_end(key)
        while len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
        try:
            instructions = await self.cache[key].get()
        except Exception:
            logger.warning("Instruction lookup failed for %s; showing zero verified coverage", med.get("slug"), exc_info=True)
            return med
        keys = {_variant_key(binding) for instruction in instructions for binding in instruction["bindings"]}
        covered = sum(_variant_key(_variant(med, variant)) in keys for variant in variants)
        med["instructions"] = instructions
        med["instruction_coverage"] = {
            "total_variants": len(variants), "covered_variants": covered,
            "fully_covered": bool(variants) and covered == len(variants),
        }
        return med


async def attach_medication_instructions(db, med: dict) -> dict:
    """One-shot helper; API routers reuse MedicationInstructionService instead."""
    return await MedicationInstructionService(db).attach(med)
