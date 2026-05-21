#!/usr/bin/env python3
"""Avva-Rus (avva-rus.ru) static-HTML scraper via sitemap.

Sitemap: /sitemap.xml — filter URLs under /production/ (one level deep) for product pages.
Each page has H1 trade name and first iblock image is the pack photo.
"""
import os, re, sys, json, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup
from fetch_lib import parallel_fetch, parallel_download_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

SITEMAP = "https://avva-rus.ru/sitemap.xml"
HOST = "https://www.avva-rus.ru"
IMG_DIR = "/tmp/av_img"
MANIFEST = "/tmp/av_products.json"
PREFIX = "av_"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"}
SKIP_IMG = ("logo", "icon", "sprite", "banner", "mc.yandex", "mail.ru", "/menu/",
            "/build/", "contraindications", "watch")


def get_urls():
    req = urllib.request.Request(SITEMAP, headers=UA)
    text = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
    locs = re.findall(r"<loc>([^<]+)</loc>", text)
    # Keep /production/<slug>/ (exactly one extra segment)
    return [l for l in locs if re.match(r"^https://(?:www\.)?avva-rus\.ru/production/[^/]+/$", l)
            and not l.endswith("/production/")]


def parse_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None
    raw = h1.get_text(" ", strip=True)
    # Strip ® and dosage hints to get the brand stem
    trade = re.sub(r"[®™]", " ", raw)
    trade = re.sub(r"\s+", " ", trade).strip()
    img_url = None
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if not src: continue
        sl = src.lower()
        if any(s in sl for s in SKIP_IMG): continue
        if "/upload/" in src and "iblock" in src:
            if src.startswith("/"): src = HOST + src
            img_url = src
            break
    if not img_url:
        return None
    slug = url.rstrip("/").split("/")[-1]
    return {"slug": slug, "trade_name": trade, "image_url": img_url, "href": url}


def main():
    print("[1/5] Sitemap ...")
    urls = get_urls()
    print(f"  product URLs: {len(urls)}")

    print("[2/5] Fetch ...")
    pages = parallel_fetch(urls, workers=10, timeout=15)
    print(f"  fetched: {sum(1 for v in pages.values() if v)}/{len(urls)}")

    cards = [c for u, html in pages.items() if html and (c := parse_page(html, u))]
    print(f"  parsed cards: {len(cards)}")

    print("[3/5] Downloading ...")
    items = [(c["slug"], c["image_url"], f"{PREFIX}{c['slug']}.webp") for c in cards]
    res = parallel_download_webp(items, IMG_DIR, workers=12, timeout=15)
    for c in cards:
        c["image_local"] = res.get(c["slug"])
    ok = sum(1 for c in cards if c["image_local"])
    print(f"  downloaded: {ok}/{len(cards)}")

    print("[4/5] Matching (manufacturer=Авва Рус) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, manufacturer_pattern="авва|avva")
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
               commit_msg=f"feat(images): Avva-Rus catalog ({len(plan)} products, {matched} cards)")


if __name__ == "__main__":
    main()
