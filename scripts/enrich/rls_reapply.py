#!/usr/bin/env python3
"""Reapply RLS scrape: build plan from /tmp/rls_products_v2.json and apply."""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(__file__))
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

MANIFEST = "/tmp/rls_products_v2.json"
PREFIX = "rls_"

EXCLUDE_MFG = "|".join([
    "ОЗОН", "ВЕЛФАРМ", "КАНОНФАРМА", "ОБНОВЛЕНИЕ", "PFK OBNOVLENIE",
    "ГРОТЕКС", "ФАРМСТАНДАРТ", "ВЕРТЕКС", "ИЗВАРИНО", "ОТИСИФАРМ",
    "МЕДИСОРБ", "АКРИХИН", "ВИФИТЕХ", "АВВА РУС", "ВАЛЕНТА",
    "ВЕРОФАРМ", "МИКРОГЕН", "МАТЕРИА МЕДИКА", "ФИРН М", "ЦИТОМЕД",
    "БИОНОРИКА", "НИАРМЕДИК", "ЭНДОФАРМ", "ЭНДОКРИННЫЙ ЗАВОД",
    "СИНТЕЗ",
])

cards = json.load(open(MANIFEST))
candidates = [c for c in cards if c.get("image_local") and os.path.exists(c["image_local"])]
for c in candidates:
    c["trade_clean"] = re.sub(r"[®™]", "", c["trade_name"]).strip()

trade_names = sorted({c["trade_clean"] for c in candidates})
print(f"candidates: {len(candidates)}, unique trade names: {len(trade_names)}")
matches = find_db_matches_bulk(trade_names, exclude_manufacturers=EXCLUDE_MFG)
plan = []
matched_count = 0
for c in candidates:
    docs = matches.get(c["trade_clean"], [])
    slugs = [d["slug"] for d in docs if not d.get("image_url")]
    if not slugs:
        continue
    plan.append({
        "image_local": c["image_local"],
        "image_url": f"/img/meds/{PREFIX}{c['rls_id']}.webp",
        "slugs": slugs,
        "trade": c["trade_clean"],
    })
    matched_count += len(slugs)

print(f"plan: {len(plan)} products -> {matched_count} DB slugs")
apply_plan(plan, prefix=PREFIX,
           commit_msg=f"feat(images): RLS scale (+{len(plan)} photos, +{matched_count} cards)")
