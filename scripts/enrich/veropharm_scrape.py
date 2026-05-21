#!/usr/bin/env python3
"""Veropharm (products.veropharm.ru) static-HTML scraper."""
import os, re, sys, json, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup
from fetch_lib import parallel_fetch, parallel_download_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

HOST = "https://products.veropharm.ru"
CATS = ['/products/plasters/', '/products/gastroenterology/', '/products/heart-vessels-and-circulation/',
        '/products/oncology/', '/products/intensive-care/', '/products/infections/',
        '/products/nervous-system/', '/products/cold/', '/products/female-health/', '/products/vision/']
IMG_DIR = "/tmp/vp_img"
MANIFEST = "/tmp/vp_products.json"
PREFIX = "vp_"
UA = {"User-Agent": "Mozilla/5.0"}


def get_urls():
    products = set()
    for c in CATS:
        try:
            req = urllib.request.Request(HOST + c, headers=UA)
            html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "replace")
        except Exception:
            continue
        for h in re.findall(r'href="([^"]+)"', html):
            if h.startswith(HOST): h = h[len(HOST):]
            if h.startswith('/products/') and h.count('/') == 4:
                products.add(HOST + h)
    return sorted(products)


def parse_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None
    trade = re.sub(r"[®™]", " ", h1.get_text(" ", strip=True))
    trade = re.sub(r"\s+", " ", trade).strip()
    img_url = None
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if "/upload/resize_cache/iblock/" in src and "350_350" in src:
            if src.startswith("/"): src = HOST + src
            img_url = src
            break
    if not img_url:
        return None
    slug = url.rstrip("/").split("/")[-1]
    return {"slug": slug, "trade_name": trade, "image_url": img_url, "href": url}


def main():
    urls = get_urls()
    print(f"product URLs: {len(urls)}")
    pages = parallel_fetch(urls, workers=10, timeout=15)
    cards = [c for u, html in pages.items() if html and (c := parse_page(html, u))]
    print(f"parsed: {len(cards)}")
    items = [(c["slug"], c["image_url"], f"{PREFIX}{c['slug']}.webp") for c in cards]
    res = parallel_download_webp(items, IMG_DIR, workers=12, timeout=15)
    for c in cards:
        c["image_local"] = res.get(c["slug"])
    ok = sum(1 for c in cards if c["image_local"])
    print(f"downloaded: {ok}/{len(cards)}")

    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    matches = find_db_matches_bulk(trade_names, manufacturer_pattern="верофарм|veropharm")
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
    print(f"plan: {len(plan)} products -> {matched} DB slugs")
    json.dump({"cards": cards, "plan": plan}, open(MANIFEST, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    if not plan: return
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): Veropharm catalog ({len(plan)} products, {matched} cards)")


if __name__ == "__main__":
    main()
