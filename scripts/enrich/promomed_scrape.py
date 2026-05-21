#!/usr/bin/env python3
"""Promomed (promomed.ru) scraper.

Pagination /catalog/?PAGEN_1=N (pages 1..6). Each product card:
  <a href="/catalog/<slug>/">
    <img src="/upload/iblock/.../<name>.png">
    ...
    <h3 class="card-product-preview__title">АЗАЦИТИДИН-ПРОМОМЕД</h3>
"""
import os, re, json, sys
sys.path.insert(0, os.path.dirname(__file__))
from fetch_lib import parallel_fetch, fetch_one, save_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan
from concurrent.futures import ThreadPoolExecutor

HOST = "https://promomed.ru"
IMG_DIR = "/tmp/pm_img"
MANIFEST = "/tmp/pm_products.json"
PREFIX = "pm_"

# Card structure
CARD_RE = re.compile(
    r'<img\s+src="(/upload/iblock/[^"]+\.(?:png|jpg|jpeg|webp))"'
    r'(?:(?!card-product-preview__title).)*?'
    r'<h3 class="card-product-preview__title">\s*([^<]+?)\s*</h3>',
    re.S
)

# Placeholder filter
PLACEHOLDER_TOKENS = ("Заглушка", "%D0%97%D0%B0%D0%B3", "%D0%9B%D0%BE%D0%B3",
                       "logo", "Лого", "Аптека.", "Здравсити", "Еаптека", "Ригла")


def is_placeholder(url):
    return any(t in url for t in PLACEHOLDER_TOKENS)


def clean_title(s):
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[®™]", "", s).strip()
    return s


def extract_base_trade(title):
    # Strip "-ПРОМОМЕД" suffix typical for genericised generics
    t = re.sub(r"[\s-]+ПРОМОМЕД$", "", title, flags=re.I).strip()
    return t


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    print("[1/5] Fetching all catalog pages (parallel) ...")
    urls = [f"{HOST}/catalog/"] + [f"{HOST}/catalog/?PAGEN_1={n}" for n in range(2, 7)]
    pages = parallel_fetch(urls, workers=10, timeout=15)
    print(f"  fetched: {sum(1 for v in pages.values() if v)}/{len(urls)}")

    cards = []
    seen = set()
    for url, html in pages.items():
        if not html:
            continue
        for img, title in CARD_RE.findall(html):
            if is_placeholder(img):
                continue
            t = clean_title(title)
            if not t:
                continue
            # slug = image filename basename
            slug = os.path.splitext(os.path.basename(img))[0].lower()
            slug = re.sub(r"[^a-z0-9_-]+", "", slug)[:40]
            if not slug or slug in seen:
                continue
            seen.add(slug)
            cards.append({
                "slug": slug,
                "title": t,
                "trade_name": extract_base_trade(t),
                "image_url": HOST + img,
            })
    print(f"  unique products: {len(cards)}")

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

    print("[3/5] Bulk matching (Promomed-only manufacturer) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, manufacturer_pattern="биохимик|промомед|promomed")
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
               commit_msg=f"feat(images): Promomed scrape ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
