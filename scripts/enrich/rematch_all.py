#!/usr/bin/env python3
"""Re-run matching for every prior manifest using the upgraded match_lib that
also matches against the `name` field (3rd tier).

Reads each /tmp/<prefix>_products.json (or _manifest.json), pulls already-
downloaded WebP files from /tmp/<prefix>_img/, re-runs find_db_matches_bulk,
and applies image_url for any newly-matched cards that still have no image.

Skips manifests whose images are no longer on disk (re-download is out of
scope; we apply only what we can SCP).
"""
import os, sys, json, glob, re
sys.path.insert(0, os.path.dirname(__file__))
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

# (manifest path, image_dir, prefix, manufacturer_pattern, exclude_manufacturers, commit_tag)
JOBS = [
    ("/tmp/sx_products.json",  "/tmp/sx_img",  "sx_",  "сотекс|sotex",                              None,        "Sotex"),
    ("/tmp/mg_products.json",  "/tmp/mg_img",  "mg_",  "микроген|microgen|имбио|аллерген|биомед|иммунопрепарат", None, "Microgen"),
    ("/tmp/bc_products.json",  "/tmp/bc_img",  "bc_",  "берлин|berlin|менарини|menarini",            None,        "Berlin-Chemie"),
    ("/tmp/bz_products.json",  "/tmp/bz_img",  "bz_",  "биосинтез|biosintez",                        None,        "Biosintez"),
    ("/tmp/av_products.json",  "/tmp/av_img",  "av_",  "авва|avva",                                  None,        "Avva-Rus"),
    ("/tmp/akr_products.json", "/tmp/akr_img", "akr_", "акрихин|akrikhin",                           None,        "Akrikhin"),
    ("/tmp/dh2_products.json", "/tmp/dh2_img", "dh2_", "дальхим|dalkhim",                            None,        "Dalkhim"),
    ("/tmp/vt_products.json",  "/tmp/vt_img",  "vt_",  "вертекс|vertex",                             None,        "Vertex"),
    ("/tmp/vp_products.json",  "/tmp/vp_img",  "vp_",  "верофарм|veropharm",                         None,        "Veropharm"),
    ("/tmp/end_products.json", "/tmp/end_img", "end_", "эндокринный завод|endopharm|эндофарм|мэз",   None,        "Endopharm"),
    ("/tmp/dh_products.json",  "/tmp/dh_img",  "dh_",  "дальхим|dalkhim",                            None,        "Dalkhim-v1"),
]


def rematch_one(manifest_path, img_dir, prefix, mfg_pattern, exclude, tag):
    if not os.path.exists(manifest_path):
        print(f"  [skip] no manifest: {manifest_path}")
        return 0
    data = json.load(open(manifest_path))
    cards = data["cards"] if isinstance(data, dict) and "cards" in data else data
    # Keep only cards that still have a local file on disk
    have = []
    for c in cards:
        local = c.get("image_local")
        if not local or not os.path.exists(local):
            # try guess from filename convention
            slug = c.get("slug") or c.get("rls_id")
            if not slug: continue
            guess = os.path.join(img_dir, f"{prefix}{slug}.webp")
            if not os.path.exists(guess): continue
            local = guess
        c["image_local"] = local
        have.append(c)
    if not have:
        print(f"  [skip] {tag}: 0 local images on disk")
        return 0

    trade_names = sorted({c.get("trade_name") or c.get("trade_clean") for c in have if (c.get("trade_name") or c.get("trade_clean"))})
    if not trade_names:
        print(f"  [skip] {tag}: no trade names in manifest")
        return 0

    print(f"  [{tag}] images={len(have)} unique_names={len(trade_names)} ...")
    matches = find_db_matches_bulk(
        trade_names,
        manufacturer_pattern=mfg_pattern,
        exclude_manufacturers=exclude,
    )
    plan = []
    matched = 0
    for c in have:
        trade = c.get("trade_name") or c.get("trade_clean")
        if not trade: continue
        docs = matches.get(trade, [])
        slugs = [d["slug"] for d in docs if not d.get("image_url")]
        if not slugs: continue
        slug_id = c.get("slug") or c.get("rls_id")
        if not slug_id: continue
        plan.append({
            "image_local": c["image_local"],
            "image_url": f"/img/meds/{prefix}{slug_id}.webp",
            "slugs": slugs,
            "trade": trade,
        })
        matched += len(slugs)
    print(f"     plan: {len(plan)} products -> {matched} candidate slugs")
    if not plan:
        return 0
    apply_plan(plan, prefix=prefix,
               commit_msg=f"feat(images): {tag} rematch (name-field tier) ({len(plan)} products, {matched} cards)")
    return matched


def main():
    print(f"Re-matching {len(JOBS)} prior manifests with the upgraded matcher ...")
    total = 0
    for job in JOBS:
        print(f"\n>>> {job[5]}")
        try:
            total += rematch_one(*job)
        except Exception as e:
            print(f"  ERROR: {e!r}")
    print(f"\nDONE. Candidate slugs across all jobs: {total}")
    print("(Effective new updates shown in each apply_plan's 'updated' count.)")


if __name__ == "__main__":
    main()
