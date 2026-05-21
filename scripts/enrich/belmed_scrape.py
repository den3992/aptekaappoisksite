#!/usr/bin/env python3
"""Belmedpreparaty (belmedpreparaty.com) scraper.

Catalog at /produktsiya/all/?PAGEN_1=N (33 pages, 9 items each ≈ 297 products).
Item structure:
  <div class="cat_new_item">
    <div class="item_img"><img src="/upload/iblock/.../<hash>.png" alt=""></div>
    <div class="item_title"><span class="cyr_title">TRADE-NAME</span>...
"""
import os, re, json, sys
sys.path.insert(0, os.path.dirname(__file__))
from fetch_lib import parallel_fetch, fetch_one, save_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan
from concurrent.futures import ThreadPoolExecutor

HOST = "https://belmedpreparaty.com"
IMG_DIR = "/tmp/bm_img"
MANIFEST = "/tmp/bm_products.json"
PREFIX = "bm_"
MAX_PAGES = 35

ITEM_RE = re.compile(
    r'<div class="cat_new_item">\s*'
    r'<div class="item_img">\s*'
    r'<img\s+src="(/upload/iblock/[^"]+\.(?:png|jpg|jpeg|webp))"[^>]*>\s*'
    r'</div>\s*'
    r'<div class="item_title">\s*'
    r'<span class="cyr_title">\s*([^<]+?)\s*</span>',
    re.S
)


def extract_base_trade(title):
    """'АЗИТРОМИЦИН-БЕЛМЕД' -> 'АЗИТРОМИЦИН-БЕЛМЕД' (keep). Drop trailing digits."""
    t = re.sub(r"\s+\d+.*$", "", title).strip()
    return t


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    print(f"[1/5] Fetching {MAX_PAGES} catalog pages in parallel ...")
    urls = [f"{HOST}/produktsiya/all/?PAGEN_1={n}" for n in range(1, MAX_PAGES + 1)]
    pages = parallel_fetch(urls, workers=10, timeout=15)
    print(f"  fetched: {sum(1 for v in pages.values() if v)}/{len(urls)}")

    cards = []
    seen_imgs = set()
    for url, html in pages.items():
        if not html: continue
        for img, name in ITEM_RE.findall(html):
            if img in seen_imgs: continue
            seen_imgs.add(img)
            slug_base = os.path.splitext(os.path.basename(img))[0].lower()
            slug = re.sub(r"[^a-z0-9_-]+", "-", slug_base)[:40]
            trade = re.sub(r"[®™]", "", name).strip()
            cards.append({
                "slug": slug,
                "title": trade,
                "trade_name": extract_base_trade(trade),
                "image_url": HOST + img,
            })
    print(f"  unique products: {len(cards)}")

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

    print("[3/5] Bulk matching (БЕЛМЕДПРЕПАРАТЫ only) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names,
                                    manufacturer_pattern="белмед")
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
               commit_msg=f"feat(images): Belmedpreparaty ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
