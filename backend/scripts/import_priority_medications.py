"""Safely upsert the user-approved priority medication cards.

The input intentionally contains only catalogue facts (name, MNN, form,
dosage, manufacturer and pack sizes).  It does not create offers, prices or
editorial descriptions.

Usage:
    python -m scripts.import_priority_medications          # preview only
    python -m scripts.import_priority_medications --apply  # write changes
"""
from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
import uuid
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

from scripts.import_mdlp import detect_category, slugify


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "priority_medications_2026-09.json"
SOURCE = "priority_medications_2026-09"


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", text)


def form_group(value: object) -> str:
    text = norm(value)
    if "дисперг" in text or "растворим" in text:
        return "orally-disintegrating-tablets"
    if "таблет" in text:
        return "tablets"
    if "капсул" in text:
        return "capsules"
    if "спрей" in text:
        return "spray"
    if "маз" in text:
        return "ointment"
    if "суспенз" in text and "внутр" not in text:
        return "suspension"
    if any(part in text for part in ("инъек", "инфуз", "внутривен", "внутримыш", "лиофилизат")):
        return "parenteral"
    if "порош" in text and "приемавнутр" in text:
        return "oral-powder"
    if "капл" in text:
        return "drops"
    return text


def curated_key(item: dict) -> str:
    return "|".join(norm(item.get(k)) for k in ("name", "dosage", "form", "manufacturer"))


def target_group(item: dict) -> tuple[str, str, str]:
    return norm(item.get("name")), norm(item.get("dosage")), form_group(item.get("form"))


def manufacturer_matches(left: object, right: object) -> bool:
    def key(value: object) -> str:
        transliterated = slugify(str(value or "")).replace("-", "")
        for prefix in ("ooo", "oao", "zao", "ao"):
            if transliterated.startswith(prefix):
                transliterated = transliterated[len(prefix):]
                break
        aliases = (
            (("farmasintez", "farmsintez"), "pharmasyntez"),
            (("astrazen",), "astrazeneca"),
            (("ebeve", "ebewe"), "ebewe"),
            (("farmkoncept",), "farmkoncept"),
            (("cheplafarm", "cheplapharm"), "cheplapharm"),
        )
        for needles, canonical in aliases:
            if any(needle in transliterated for needle in needles):
                return canonical
        return transliterated

    a, b = key(left), key(right)
    if not a or not b:
        return False
    return a in b or b in a


def candidate_query(name: str) -> dict:
    # Official registry spelling sometimes swaps a space and a hyphen.
    pieces = [re.escape(p) for p in re.split(r"[\s\-]+", name.strip()) if p]
    pattern = r"^[\s\-]*" + r"[\s\-]+".join(pieces) + r"[\s\-]*$"
    return {"name": {"$regex": pattern, "$options": "i"}, "is_canonical": {"$ne": False}}


def choose_candidate(item: dict, candidates: list[dict], group_size: int) -> dict | None:
    compatible = []
    for doc in candidates:
        if norm(doc.get("dosage")) != norm(item.get("dosage")):
            continue
        if form_group(doc.get("form")) != form_group(item.get("form")):
            continue
        compatible.append(doc)

    if not compatible:
        return None

    manufacturer_hits = [
        doc for doc in compatible
        if manufacturer_matches(doc.get("manufacturer"), item.get("manufacturer"))
    ]
    if len(manufacturer_hits) == 1:
        return manufacturer_hits[0]
    if group_size == 1 and len(compatible) == 1:
        return compatible[0]
    return None


def merge_variants(existing: list[dict], pack_sizes: list[str], key: str) -> list[dict]:
    by_pack = {norm(v.get("pack_size")): v for v in (existing or []) if v.get("pack_size")}
    merged = []
    for index, pack_size in enumerate(pack_sizes, start=1):
        old = by_pack.get(norm(pack_size))
        if old:
            variant = dict(old)
            variant["pack_size"] = pack_size
        else:
            variant = {
                "pack_size": pack_size,
                "curated_variant_id": f"{key}:{index}",
            }
        merged.append(variant)
    return merged


def verify_import(db, items: list[dict], api_base: str, site_base: str | None) -> None:
    errors = []
    checked = 0
    source_count = db.medications.count_documents({"curated_source": SOURCE})
    if source_count != len(items):
        errors.append(f"source count is {source_count}, expected {len(items)}")

    for item in items:
        key = curated_key(item)
        docs = list(db.medications.find({"curated_source": SOURCE, "curated_key": key}))
        if len(docs) != 1:
            errors.append(f"{item['name']} {item.get('dosage')}: found {len(docs)} documents")
            continue
        doc = docs[0]
        for field in (
            "name", "mnn", "form", "dosage", "manufacturer",
            "manufacturer_country", "image_url", "rx",
        ):
            if doc.get(field) != item.get(field):
                errors.append(
                    f"{doc['slug']}: {field}={doc.get(field)!r}, expected {item.get(field)!r}"
                )
        actual_packs = [variant.get("pack_size") for variant in (doc.get("variants") or [])]
        if actual_packs != item["pack_sizes"]:
            errors.append(f"{doc['slug']}: packs={actual_packs!r}, expected {item['pack_sizes']!r}")

        url = f"{api_base.rstrip('/')}/api/medications/{doc['slug']}"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if response.status != 200 or payload.get("slug") != doc["slug"]:
                errors.append(f"{doc['slug']}: API returned an unexpected response")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            errors.append(f"{doc['slug']}: API check failed: {exc}")

        if site_base:
            page_url = f"{site_base.rstrip('/')}/msk/preparaty/{doc['slug']}"
            request = urllib.request.Request(page_url, headers={"User-Agent": "AptekaaImportVerifier/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    html = response.read().decode("utf-8", errors="replace")
                if response.status != 200 or item["name"].split()[0].lower() not in html.lower():
                    errors.append(f"{doc['slug']}: public page returned unexpected content")
            except (urllib.error.URLError, TimeoutError) as exc:
                errors.append(f"{doc['slug']}: public page check failed: {exc}")
        checked += 1

    if errors:
        print("VERIFY FAILED")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)
    print(f"VERIFY OK: {checked} cards; database fields, packs and detail API all match")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="delete cards from this curated source that are absent from the manifest",
    )
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--api-base", default="http://127.0.0.1:8001")
    parser.add_argument("--site-base")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    items = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(items, list) or not items:
        raise SystemExit("Input must be a non-empty JSON array")

    keys = [curated_key(item) for item in items]
    if len(keys) != len(set(keys)):
        duplicates = [key for key, count in Counter(keys).items() if count > 1]
        raise SystemExit(f"Duplicate curated keys: {duplicates}")

    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    if args.verify:
        verify_import(db, items, args.api_base, args.site_base)
        return
    group_counts = Counter(target_group(item) for item in items)
    batch_id = f"{SOURCE}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    used_slugs: set[str] = set()
    plan = []
    stale_docs = list(db.medications.find({
        "curated_source": SOURCE,
        "curated_key": {"$nin": keys},
    }))

    for item in items:
        key = curated_key(item)
        existing = db.medications.find_one({"curated_source": SOURCE, "curated_key": key})
        match_reason = "curated_key"
        candidates = []
        if not existing:
            candidates = list(db.medications.find(candidate_query(item["name"])))
            existing = choose_candidate(item, candidates, group_counts[target_group(item)])
            match_reason = "catalog_match" if existing else "new"

        if existing:
            slug = existing["slug"]
        else:
            suffix = item.get("slug_suffix")
            slug = slugify(item["name"], item.get("dosage"), item.get("form"), suffix)
            base = slug
            serial = 2
            while slug in used_slugs or db.medications.find_one({"slug": slug}, {"_id": 1}):
                slug = f"{base}-{serial}"
                serial += 1
        used_slugs.add(slug)

        variants = merge_variants((existing or {}).get("variants") or [], item["pack_sizes"], key)
        official_manufacturer = None
        if existing and existing.get("manufacturer") and not manufacturer_matches(
            existing.get("manufacturer"), item.get("manufacturer")
        ):
            official_manufacturer = existing["manufacturer"]

        update = {
            "slug": slug,
            "name": item["name"],
            "label_name": " ".join(filter(None, [item["name"], item.get("dosage"), item.get("form")])),
            "mnn": item.get("mnn"),
            "form": item.get("form"),
            "dosage": item.get("dosage"),
            "manufacturer": item.get("manufacturer"),
            "manufacturer_country": item.get("manufacturer_country"),
            "image_url": item.get("image_url"),
            "category": (existing or {}).get("category") or detect_category(item.get("mnn")),
            "rx": item.get("rx"),
            "variants": variants,
            "is_canonical": True,
            "canonical_slug": slug,
            "curated_source": SOURCE,
            "curated_key": key,
            "curated_updated_at": datetime.now(timezone.utc),
        }
        if official_manufacturer:
            update["manufacturer_official"] = official_manufacturer

        plan.append({
            "action": "update" if existing else "insert",
            "reason": match_reason,
            "slug": slug,
            "name": item["name"],
            "dosage": item.get("dosage"),
            "manufacturer": item.get("manufacturer"),
            "packs": item["pack_sizes"],
            "existing_id": existing.get("_id") if existing else None,
            "candidates": [
                {
                    "slug": doc.get("slug"),
                    "dosage": doc.get("dosage"),
                    "form": doc.get("form"),
                    "manufacturer": doc.get("manufacturer"),
                    "packs": [v.get("pack_size") for v in (doc.get("variants") or [])],
                }
                for doc in candidates
                if norm(doc.get("dosage")) == norm(item.get("dosage"))
                and form_group(doc.get("form")) == form_group(item.get("form"))
            ],
            "update": update,
            "backup": existing,
        })

    # A card can be re-matched by name/dose/form when its approved
    # manufacturer changes. Do not prune that same document after updating it.
    matched_existing_ids = {
        row["existing_id"] for row in plan if row["existing_id"] is not None
    }
    stale_docs = [
        doc for doc in stale_docs if doc["_id"] not in matched_existing_ids
    ]

    print(f"Batch: {batch_id}")
    print(f"Cards: {len(plan)} (updates={sum(p['action'] == 'update' for p in plan)}, inserts={sum(p['action'] == 'insert' for p in plan)})")
    print(f"Stale cards: {len(stale_docs)}")
    for doc in stale_docs:
        print(f"PRUNE  {doc.get('slug')} | {doc.get('name')} | {doc.get('dosage') or '—'}")
    for row in plan:
        print(
            f"{row['action'].upper():6} {row['reason']:13} {row['slug']} | "
            f"{row['name']} | {row['dosage'] or '—'} | {row['manufacturer']} | {', '.join(row['packs'])}"
        )
        if row["action"] == "insert" and row["candidates"]:
            for candidate in row["candidates"]:
                print(
                    "       AMBIGUOUS     "
                    f"{candidate['slug']} | {candidate['manufacturer']} | "
                    f"{', '.join(p or '—' for p in candidate['packs'])}"
                )

    if not args.apply:
        print("PREVIEW ONLY: re-run with --apply to write changes")
        return
    if stale_docs and not args.prune:
        raise SystemExit("Stale curated cards found; re-run with --apply --prune after reviewing the list")

    now = datetime.now(timezone.utc)
    for row in plan:
        db.curated_import_backups.insert_one({
            "batch_id": batch_id,
            "source": SOURCE,
            "slug": row["slug"],
            "action": row["action"],
            "backed_up_at": now,
            "document": row["backup"],
        })
        if row["existing_id"] is not None:
            db.medications.update_one({"_id": row["existing_id"]}, {"$set": row["update"]})
        else:
            db.medications.insert_one(row["update"])
        if row["update"].get("mnn"):
            db.mnn_index.update_one(
                {"mnn": row["update"]["mnn"].upper()},
                {"$addToSet": {"slugs": row["slug"]}},
                upsert=True,
            )

    for doc in stale_docs:
        slug = doc["slug"]
        db.curated_import_backups.insert_one({
            "batch_id": batch_id,
            "source": SOURCE,
            "slug": slug,
            "action": "prune",
            "backed_up_at": now,
            "document": doc,
        })
        identity_filters = [
            {"slug": slug},
            {"medication_id": doc["_id"]},
            {"medication_id": str(doc["_id"])},
        ]
        db.prices.delete_many({"$or": identity_filters})
        db.prices_real.delete_many({"$or": identity_filters})
        db.reviews.delete_many({"slug": slug})
        db.indexnow_state.delete_many({"slug": slug})
        db.mnn_index.update_many({}, {"$pull": {"slugs": slug}})
        db.medications.delete_one({"_id": doc["_id"]})
    db.mnn_index.delete_many({"slugs": {"$size": 0}})

    print(f"APPLIED: {len(plan)} cards; pruned={len(stale_docs)}; backup batch={batch_id}")


if __name__ == "__main__":
    main()
