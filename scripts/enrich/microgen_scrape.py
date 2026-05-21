#!/usr/bin/env python3
"""Microgen (microgen.ru) static-HTML scraper via sitemap.

Sitemap: https://microgen.ru/sitemap-iblock-7.xml -> 134 URLs, of which ~126 are
product pages (depth > 5).
Each product page has an H1 (trade name) and an image in
.product or iblock-upload path. We grab the first non-logo image.
"""
import os, re, sys, json
sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup
from fetch_lib import parallel_fetch, parallel_download_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

SITEMAP = "https://microgen.ru/sitemap-iblock-7.xml"
HOST = "https://microgen.ru"
IMG_DIR = "/tmp/mg_img"
MANIFEST = "/tmp/mg_products.json"
PREFIX = "mg_"
SKIP_IMG = ("logo", "icon", "banner", "sprite", "flag", "bg-", "hotline",
            "product-card__info", "watch")


def get_product_urls():
    import urllib.request
    r = urllib.request.urlopen(SITEMAP, timeout=20)
    text = r.read().decode("utf-8")
    locs = re.findall(r"<loc>([^<]+)</loc>", text)
    # Product pages have at least one segment past /products/<category>/
    return [l for l in locs if l.count("/") >= 6 and "/products/" in l]


def parse_product(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None
    trade = h1.get_text(strip=True)
    img_url = None
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if not src: continue
        if any(s in src.lower() for s in SKIP_IMG): continue
        if not src.startswith("http"): src = HOST + src
        img_url = src
        break
    if not img_url:
        return None
    slug = url.rstrip("/").split("/")[-1]
    return {"slug": slug, "trade_name": trade, "image_url": img_url, "href": url}


def main():
    print("[1/5] Fetching sitemap ...")
    urls = get_product_urls()
    print(f"  product URLs: {len(urls)}")

    print("[2/5] Parallel fetching product pages ...")
    pages = parallel_fetch(urls, workers=10, timeout=15)
    print(f"  fetched: {sum(1 for v in pages.values() if v)}/{len(urls)}")

    cards = []
    for u, html in pages.items():
        if not html: continue
        c = parse_product(html, u)
        if c: cards.append(c)
    print(f"  parsed cards with image: {len(cards)}")

    print("[3/5] Downloading images ...")
    items = [(c["slug"], c["image_url"], f"{PREFIX}{c['slug']}.webp") for c in cards]
    res = parallel_download_webp(items, IMG_DIR, workers=12, timeout=15)
    for c in cards:
        c["image_local"] = res.get(c["slug"])
    ok = sum(1 for c in cards if c["image_local"])
    print(f"  downloaded: {ok}/{len(cards)}")

    print("[4/5] Matching to DB (manufacturer=Микроген) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, manufacturer_pattern="микроген|microgen|имбио|аллерген|биомед|иммунопрепарат")
    plan, matched = [], 0
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

    if not plan:
        return
    print("[5/5] Applying plan ...")
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): Microgen via sitemap ({len(plan)} products, {matched} cards)")


if __name__ == "__main__":
    main()
