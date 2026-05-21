#!/usr/bin/env python3
"""Valenta Pharm (valentapharm.com) scraper.

Strategy:
  1. Fetch /products/ root, collect category URLs.
  2. Fetch all category pages in parallel.
  3. Parse <a class="product-item"> blocks (href, h5 title, img src).
  4. Strip <sup>®</sup>/HTML entities from title to get trade name.
  5. Download images in parallel, save as val_<slug>.webp.
  6. Bulk-match to DB and apply.
"""
import os, re, json, sys, html
sys.path.insert(0, os.path.dirname(__file__))
from fetch_lib import parallel_fetch, fetch_one, save_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

HOST = "https://www.valentapharm.com"
IMG_DIR = "/tmp/val_img"
MANIFEST = "/tmp/val_products.json"
PREFIX = "val_"

CATEGORIES = [
    "/products/antibacterial-drug/",
    "/products/antihistamines/",
    "/products/cough_and_cold/",
    "/products/gastroenterology/",
    "/products/plasters/",
    "/products/psychoneurology/",
    "/products/women-health/",
]

ITEM_RE = re.compile(
    r'<a\s+class="product-item"\s+href="([^"]+)">'
    r'\s*<h5\s+class="product-item-title">([^<]*(?:<[^>]+>[^<]*)*?)</h5>'
    r'(?:(?!</a>).)*?'
    r'<img\s+src="(/upload/[^"]+)"',
    re.S
)


def clean_title(raw):
    """Remove HTML tags, decode entities, normalize whitespace."""
    t = re.sub(r"<[^>]+>", "", raw)
    t = html.unescape(t)
    t = re.sub(r"[®™]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_base_trade(title):
    """Drop trailing form descriptors so we get the brand. 'Граммидин спрей' -> 'Граммидин'.
    But keep multi-word brand names like 'Антарейт Валента'.
    """
    t = title
    # Strip form-descriptor suffix
    t = re.sub(
        r"\s+(таблет\w*|капс\w*|раствор\w*|мазь|крем|сироп|спрей|капли|гель|порош\w*|"
        r"суспенз\w*|гран\w*|пастил\w*|свеч\w*|супп\w*|плёнк\w*|пленк\w*|драже|"
        r"вакцин\w*|для\s.*|со\s.*|плюс|форте|экспресс)$",
        "", t, flags=re.I
    ).strip()
    return t


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    # 1+2) Fetch all category pages in parallel
    print(f"[1/5] Fetching {len(CATEGORIES)} category pages in parallel ...")
    urls = [HOST + c for c in CATEGORIES]
    pages = parallel_fetch(urls, workers=10, timeout=10)
    ok = sum(1 for v in pages.values() if v)
    print(f"  fetched {ok}/{len(urls)}")

    # 3) Parse product items
    print("[2/5] Parsing product cards ...")
    cards = []
    seen = set()
    for url, html_txt in pages.items():
        if not html_txt:
            continue
        for href, title_raw, img_src in ITEM_RE.findall(html_txt):
            slug = href.strip("/").split("/")[-1]
            if slug in seen:
                continue
            seen.add(slug)
            title = clean_title(title_raw)
            cards.append({
                "slug": slug,
                "title": title,
                "trade_name": extract_base_trade(title),
                "image_url": HOST + img_src,
            })
    print(f"  parsed {len(cards)} unique product cards")

    # 4) Download images in parallel
    print("[3/5] Downloading + converting images ...")
    from concurrent.futures import ThreadPoolExecutor
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
    print(f"  downloaded {len(success)}/{len(cards)}")
    for c in cards:
        c["image_local"] = success.get(c["slug"])

    # 5) Bulk match
    print("[4/5] Bulk matching trade names ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
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
    print(f"  plan: {len(plan)} Valenta products -> {matched} DB slugs")
    json.dump({"cards": cards, "plan": plan}, open(MANIFEST, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    if not plan:
        return

    # 6) Apply
    print("[5/5] Applying ...")
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): Valenta scrape ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
