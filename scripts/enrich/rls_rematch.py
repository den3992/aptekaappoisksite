#!/usr/bin/env python3
"""Re-match the RLS v2 manifest with the upgraded matcher (name-field tier)."""
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
    "СИНТЕЗ", "ДАЛЬХИМ", "БИОСИНТЕЗ", "БЕРЛИН",
])


def main():
    data = json.load(open(MANIFEST))
    have = [d for d in data if d.get("image_local") and os.path.exists(d["image_local"])]
    print(f"RLS entries with on-disk image: {len(have)}")
    for c in have:
        c["trade_clean"] = re.sub(r"[®™]", "", c.get("trade_name", "")).strip()
    trade_names = sorted({c["trade_clean"] for c in have if c["trade_clean"]})
    print(f"unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, exclude_manufacturers=EXCLUDE_MFG)
    plan, matched = [], 0
    for c in have:
        docs = matches.get(c["trade_clean"], [])
        slugs = [d["slug"] for d in docs if not d.get("image_url")]
        if not slugs: continue
        plan.append({
            "image_local": c["image_local"],
            "image_url": f"/img/meds/{PREFIX}{c['rls_id']}.webp",
            "slugs": slugs,
            "trade": c["trade_clean"],
        })
        matched += len(slugs)
    print(f"plan: {len(plan)} RLS products -> {matched} candidate slugs")
    if not plan: return
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): RLS rematch (name-field tier) ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
