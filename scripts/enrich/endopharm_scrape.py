#!/usr/bin/env python3
"""Endopharm (endopharm.ru) scraper.

Nuxt SSR catalog at /catalog. Item structure (after class hash):
  <a href="/catalog/<slug>" class="_card_..."><div class="_picture_..."><img src="https://api.endopharm.ru/upload/webp/.../<hash>.webp"></div>
   <div class="_content_..."><div class="_text_..."><div class="_text__top_..."><div class="_title_...">Trade®</div>
"""
import os, re, json, sys
sys.path.insert(0, os.path.dirname(__file__))
from fetch_lib import fetch_one, save_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan
from concurrent.futures import ThreadPoolExecutor

HOST = "https://endopharm.ru"
CATALOG = HOST + "/catalog"
IMG_DIR = "/tmp/end_img"
MANIFEST = "/tmp/end_products.json"
PREFIX = "end_"

ITEM_RE = re.compile(
    r'<a href="(/catalog/[^"]+)"\s+class="_card_[^"]+">'
    r'<div class="_picture_[^"]+">(?:<!---->)?'
    r'<img src="(https://api\.endopharm\.ru/upload/[^"]+\.webp)"[^>]*></div>'
    r'<div class="_content_[^"]+">'
    r'<div class="_text_[^"]+">'
    r'<div class="_text__top_[^"]+">(?:<!---->)?'
    r'<div class="_title_[^"]+">\s*([^<]+?)\s*</div>',
    re.S
)


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    print("[1/5] Fetching catalog ...")
    # Try with bigger page size
    html = fetch_one(CATALOG + "?perPage=500", timeout=20)
    items = ITEM_RE.findall(html)
    print(f"  parsed items: {len(items)}")

    cards = []
    seen = set()
    for href, img, name in items:
        slug = href.rstrip("/").split("/")[-1].strip()
        if slug in seen: continue
        seen.add(slug)
        trade = re.sub(r"[®™]", "", name).strip()
        if not trade: continue
        # Sanitize slug for filename
        fslug = re.sub(r"[^a-z0-9_-]+", "-", slug.lower())[:60]
        cards.append({"slug": slug, "fslug": fslug, "trade_name": trade, "image_url": img})
    print(f"  unique: {len(cards)}")

    print("[2/5] Downloading images ...")
    def _dl(card):
        out = os.path.join(IMG_DIR, f"{PREFIX}{card['fslug']}.webp")
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

    print("[3/5] Bulk matching (Endopharm only) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names,
                                    manufacturer_pattern="эндокринный завод|endopharm|эндофарм|мэз")
    plan = []
    matched = 0
    for c in cards:
        if not c["image_local"]: continue
        docs = matches.get(c["trade_name"], [])
        slugs = [d["slug"] for d in docs if not d.get("image_url")]
        if not slugs: continue
        plan.append({
            "image_local": c["image_local"],
            "image_url": f"/img/meds/{PREFIX}{c['fslug']}.webp",
            "slugs": slugs,
            "trade": c["trade_name"],
        })
        matched += len(slugs)
    print(f"  plan: {len(plan)} products -> {matched} DB slugs")
    json.dump({"cards": cards, "plan": plan}, open(MANIFEST, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    if not plan: return
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): Endopharm ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
