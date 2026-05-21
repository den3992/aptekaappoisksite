#!/usr/bin/env python3
"""Apply all currently-downloaded /tmp/wc_img/*.webp files to DB.

Uses /tmp/wc_manifest.json + /tmp/wc_names.json to map name → slugs.
Skips records that already have an image_url (won't overwrite).
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(__file__))
from apply_lib import apply_plan

MANIFEST = "/tmp/wc_manifest.json"
NAMES = "/tmp/wc_names.json"
IMG_DIR = "/tmp/wc_img"
PREFIX = "wc_"


def slugify(t):
    s = t.replace("File:", "")
    s = os.path.splitext(s)[0]
    s = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9]+", "_", s).strip("_")
    return s[:60].lower()


def main():
    m = json.load(open(MANIFEST))
    names_data = json.load(open(NAMES))
    name_to_slugs = {r["name"]: r["slugs"] for r in names_data}

    plan = []
    matched = 0
    for r in m:
        b = r.get("best")
        if not b: continue
        local = os.path.join(IMG_DIR, f"{PREFIX}{slugify(b['title'])}.webp")
        if not os.path.exists(local):
            continue
        slugs = name_to_slugs.get(r["name"], [])
        if not slugs: continue
        plan.append({
            "image_local": local,
            "image_url": f"/img/meds/{os.path.basename(local)}",
            "slugs": slugs,
            "trade": r["name"],
        })
        matched += len(slugs)
    print(f"plan: {len(plan)} photos -> {matched} DB cards")
    if not plan:
        return
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): Wikimedia Commons ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
