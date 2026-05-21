#!/usr/bin/env python3
"""Pharmasyntez (pharmasyntez.com) scraper.

Catalog at /products/ — single HTML page with all products.
Item pattern:
  <a href="/products/<group>/<slug>/">
    <div ... style="background-image: url('/upload/.../<hash>.png');"></div>
    <div class="name">Trade®</div>
    <div class="mnn">MNN text</div>
"""
import os, re, json, sys
sys.path.insert(0, os.path.dirname(__file__))
from fetch_lib import fetch_one, save_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan
from concurrent.futures import ThreadPoolExecutor

HOST = "https://pharmasyntez.com"
CATALOG = HOST + "/products/"
IMG_DIR = "/tmp/psn_img"
MANIFEST = "/tmp/psn_products.json"
PREFIX = "psn_"

ITEM_RE = re.compile(
    r'<a\s+href="(/products/[^"]+/[^"]+/)">\s*'
    r'<div\s+class="box-1">\s*'
    r'<div\s+class="square-picture"\s+style="background-image:\s*url\(\'(/upload/[^\']+)\'\);"></div>\s*'
    r'<div\s+class="name">\s*([^<]+?)\s*</div>',
    re.S
)


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    print("[1/5] Fetching catalog ...")
    html = fetch_one(CATALOG, timeout=20)
    print(f"  bytes: {len(html)}")
    items = ITEM_RE.findall(html)
    print(f"[2/5] Parsed items: {len(items)}")

    cards = []
    seen = set()
    for href, img, name in items:
        slug = href.rstrip("/").split("/")[-1]
        if slug in seen: continue
        seen.add(slug)
        trade = re.sub(r"[®™]", "", name).strip()
        cards.append({
            "slug": slug,
            "trade_name": trade,
            "image_url": HOST + img,
            "href": HOST + href,
        })
    print(f"  unique: {len(cards)}")

    print("[3/5] Downloading images (parallel) ...")
    def _dl(card):
        out = os.path.join(IMG_DIR, f"{PREFIX}{card['slug']}.webp")
        try:
            raw = fetch_one(card["image_url"], binary=True, timeout=20)
        except Exception:
            return card["slug"], None
        if save_webp(raw, out, max_width=800):
            return card["slug"], out
        return card["slug"], None
    success = {}
    with ThreadPoolExecutor(max_workers=15) as ex:
        for slug, path in ex.map(_dl, cards):
            if path: success[slug] = path
    print(f"  downloaded: {len(success)}/{len(cards)}")
    for c in cards:
        c["image_local"] = success.get(c["slug"])

    print("[4/5] Bulk matching (Pharmasyntez group manufacturers) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, manufacturer_pattern="фармасинтез|pharmasyntez")
    plan = []
    matched = 0
    for c in cards:
        if not c["image_local"]: continue
        docs = matches.get(c["trade_name"], [])
        slugs = [d["slug"] for d in docs if not d.get("image_url")]
        if not slugs: continue
        plan.append({
            "image_local": c["image_local"],
            "image_url": f"/img/meds/{PREFIX}{c['slug']}.webp",
            "slugs": slugs,
            "trade": c["trade_name"],
        })
        matched += len(slugs)
    print(f"  plan: {len(plan)} products -> {matched} DB slugs")
    json.dump({"cards": cards, "plan": plan}, open(MANIFEST, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    if not plan: return

    print("[5/5] Applying ...")
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): Pharmasyntez ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
