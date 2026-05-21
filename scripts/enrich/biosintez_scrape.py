#!/usr/bin/env python3
"""Biosintez (biosintez.com) static-HTML scraper.

The /products/ index page lists all /products/<numeric>/ items.
Each detail page has H1 trade name and an image in /upload/iblock/...
"""
import os, re, sys, json, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup
from fetch_lib import parallel_fetch, parallel_download_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

HOST = "https://biosintez.com"
INDEX = HOST + "/products/"
IMG_DIR = "/tmp/bz_img"
MANIFEST = "/tmp/bz_products.json"
PREFIX = "bz_"
SKIP_HINTS = ("logo", "icon", "sprite", "available-by-prescription",
              "/Group", "/main_page/img", "/watch", "loader")


def get_product_urls():
    UA = {"User-Agent": "Mozilla/5.0 Firefox/120.0"}
    req = urllib.request.Request(INDEX, headers=UA)
    html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if re.match(r"^/products/\d+/$", h):
            urls.add(HOST + h)
    return sorted(urls)


def parse_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one(".catalog-element-page__title")
    if not title_el:
        return None
    trade = re.sub(r"[®™]", " ", title_el.get_text(" ", strip=True))
    trade = re.sub(r"\s+", " ", trade).strip()
    if not trade:
        return None
    img_url = None
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if not src: continue
        sl = src.lower()
        if any(s in sl for s in SKIP_HINTS): continue
        # Prefer images inside catalog-element-page block, but accept /iblock/
        if "/iblock/" in src:
            if src.startswith("/"): src = HOST + src
            img_url = src
            break
    if not img_url:
        return None
    slug = url.rstrip("/").split("/")[-1]
    return {"slug": slug, "trade_name": trade, "image_url": img_url, "href": url}


def main():
    print("[1/5] Index ...")
    urls = get_product_urls()
    print(f"  product URLs: {len(urls)}")

    print("[2/5] Fetch ...")
    pages = parallel_fetch(urls, workers=10, timeout=15)
    print(f"  fetched: {sum(1 for v in pages.values() if v)}/{len(urls)}")

    cards = [c for u, html in pages.items() if html and (c := parse_page(html, u))]
    print(f"  parsed cards with image: {len(cards)}")

    print("[3/5] Downloading ...")
    items = [(c["slug"], c["image_url"], f"{PREFIX}{c['slug']}.webp") for c in cards]
    res = parallel_download_webp(items, IMG_DIR, workers=12, timeout=15)
    for c in cards:
        c["image_local"] = res.get(c["slug"])
    ok = sum(1 for c in cards if c["image_local"])
    print(f"  downloaded: {ok}/{len(cards)}")

    print("[4/5] Matching (manufacturer=Биосинтез) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, manufacturer_pattern="биосинтез|biosintez")
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
    print("[5/5] Applying ...")
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): Biosintez catalog ({len(plan)} products, {matched} cards)")


if __name__ == "__main__":
    main()
