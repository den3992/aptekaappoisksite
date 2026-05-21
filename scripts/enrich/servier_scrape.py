#!/usr/bin/env python3
"""Servier (servier.ru) scraper.

Catalog at /lekarstvennye-preparaty/. Each product:
  <a class="fancybox" href=".../wp-content/uploads/.../<slug>.png">
    <img src="same_url" alt="">
  </a>
  ...
  <div class="product-item_title">Арифам®</div>

Pattern: image URL is /wp-content/uploads/YYYY/MM/<slug>.png
Title appears after the slider in product-item_title.
"""
import os, re, json, sys
sys.path.insert(0, os.path.dirname(__file__))
from fetch_lib import parallel_fetch, fetch_one, save_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan
from concurrent.futures import ThreadPoolExecutor

CATALOG = "https://servier.ru/lekarstvennye-preparaty/"
IMG_DIR = "/tmp/sv_img"
MANIFEST = "/tmp/sv_products.json"
PREFIX = "sv_"

PRODUCT_BLOCK_RE = re.compile(
    r'<div class="slider product-slider">(.+?)<div class="product-item_title">\s*[\u200b\s]*([^<]+?)\s*</div>',
    re.S
)
IMG_RE = re.compile(r'<img\s+src="([^"]+\.(?:png|jpg|jpeg|webp))"', re.S)


def clean(s):
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[®™]", "", s).strip()
    return s


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    print("[1/5] Fetching catalog ...")
    html = fetch_one(CATALOG, timeout=15)
    blocks = PRODUCT_BLOCK_RE.findall(html)
    print(f"  product blocks: {len(blocks)}")

    cards = []
    seen = set()
    for slider, title in blocks:
        # take first image of the slider as canonical
        imgs = IMG_RE.findall(slider)
        if not imgs:
            continue
        title_clean = clean(title)
        if not title_clean or title_clean in seen:
            continue
        seen.add(title_clean)
        slug = re.sub(r"[^a-z0-9_]", "", os.path.splitext(os.path.basename(imgs[0]))[0].lower())[:40] or f"sv_{len(cards)}"
        cards.append({
            "slug": slug,
            "title": title_clean,
            "trade_name": title_clean,
            "image_url": imgs[0],
        })
    print(f"  unique cards: {len(cards)}")

    print("[2/5] Downloading images ...")
    def _dl(card):
        out = os.path.join(IMG_DIR, f"{PREFIX}{card['slug']}.webp")
        try:
            raw = fetch_one(card["image_url"], binary=True, timeout=15)
        except Exception:
            return card["slug"], None
        if save_webp(raw, out):
            return card["slug"], out
        return card["slug"], None
    success = {}
    with ThreadPoolExecutor(max_workers=15) as ex:
        for slug, path in ex.map(_dl, cards):
            if path:
                success[slug] = path
    print(f"  downloaded: {len(success)}/{len(cards)}")
    for c in cards:
        c["image_local"] = success.get(c["slug"])

    print("[3/5] Bulk matching ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    matches = find_db_matches_bulk(trade_names)
    plan = []
    matched = 0
    for c in cards:
        if not c["image_local"]:
            continue
        docs = matches.get(c["trade_name"], [])
        slugs = [d["slug"] for d in docs if not d.get("image_url")]
        if not slugs:
            continue
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

    if not plan:
        return

    print("[5/5] Applying ...")
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): Servier scrape ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
