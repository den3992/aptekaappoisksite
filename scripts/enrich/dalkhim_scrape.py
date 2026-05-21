#!/usr/bin/env python3
"""Dalkhim Pharm (dalkhimpharm.ru) scraper.

Catalog at /catalog/. Each product card:
  <div class="title"><a href="https://dalkhimpharm.ru/catalog/<slug>/">Trade <span>... </span></a></div>
  <div class="pic"><a href="..."><img src="https://dalkhimpharm.ru/wp-content/uploads/.../Pachka-Trade-575h421-400x293.jpg" alt=""></a></div>
"""
import os, re, json, sys
sys.path.insert(0, os.path.dirname(__file__))
from fetch_lib import fetch_one, save_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan
from concurrent.futures import ThreadPoolExecutor

HOST = "https://dalkhimpharm.ru"
CATALOG = HOST + "/catalog/"
IMG_DIR = "/tmp/dh_img"
MANIFEST = "/tmp/dh_products.json"
PREFIX = "dh_"

ITEM_RE = re.compile(
    r'<div class="title"><a href="(https://dalkhimpharm\.ru/catalog/[^"]+/)">\s*'
    r'([^<]+?)\s*<span>(?:[^<]*)</span></a></div>\s*'
    r'<div class="pic"><a [^>]+><img\s+src="([^"]+\.(?:jpg|jpeg|png|webp))"',
    re.S
)


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    print("[1/5] Fetching catalog ...")
    html = fetch_one(CATALOG, timeout=15)
    items = ITEM_RE.findall(html)
    print(f"  parsed: {len(items)}")

    cards = []
    seen = set()
    for href, name, img in items:
        slug = href.rstrip("/").split("/")[-1]
        if slug in seen: continue
        seen.add(slug)
        trade = re.sub(r"[®™]", "", name).strip()
        cards.append({"slug": slug, "trade_name": trade, "image_url": img})
    print(f"  unique: {len(cards)}")

    print("[2/5] Downloading images ...")
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

    print("[3/5] Bulk matching (Dalkhim only) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, manufacturer_pattern="дальхимфарм|dalkhim")
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
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): Dalkhim ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
