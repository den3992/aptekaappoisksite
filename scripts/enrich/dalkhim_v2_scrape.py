#!/usr/bin/env python3
"""Dalkhim Pharm v2 (dalkhimpharm.ru) scraper via sitemap.

Sitemap: /wp-sitemap-posts-tovar-1.xml -> ~138 product URLs.
Each /catalog/<slug>/ page has H1 trade name + form, and a main wp-content image.
"""
import os, re, sys, json, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup
from fetch_lib import parallel_fetch, parallel_download_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

SITEMAP = "https://dalkhimpharm.ru/wp-sitemap-posts-tovar-1.xml"
HOST = "https://dalkhimpharm.ru"
IMG_DIR = "/tmp/dh2_img"
MANIFEST = "/tmp/dh2_products.json"
PREFIX = "dh2_"
UA = {"User-Agent": "Mozilla/5.0 Firefox/120"}
FORM_KEYS = r"таблет|капс|раствор|мазь|крем|сироп|капли|гель|спрей|порош|инъекц|субст|лиоф|линимент|суспензи|плёнк|пленк|пастил|настой|настойк|жидкос|сухой"


def get_urls():
    req = urllib.request.Request(SITEMAP, headers=UA)
    text = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    return re.findall(r"<loc>([^<]+)</loc>", text)


def parse_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None
    raw = h1.get_text(" ", strip=True)
    raw = re.sub(r"[®™]", " ", raw)
    # H1 like "Дексаметазонраствор для инъекций..."; insert space before form keyword if glued.
    raw = re.sub(rf"([а-яё])({FORM_KEYS})", r"\1 \2", raw, flags=re.I)
    # Cut at first form keyword or comma
    trade = re.split(rf"\s+({FORM_KEYS})|\s+,|\s+\(", raw, 1, re.I)[0]
    trade = re.sub(r"\s+", " ", trade).strip()
    if not trade:
        return None
    img_url = None
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        sl = src.lower()
        if "wp-content/uploads" not in src: continue
        if any(s in sl for s in ("iclose", "lupa", "iphone", "logo", "sprite", "icon-")):
            continue
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
    cards = [c for u, html in pages.items() if html and (c := parse_page(html, u))]
    print(f"  parsed cards: {len(cards)}")

    print("[3/5] Downloading ...")
    items = [(c["slug"], c["image_url"], f"{PREFIX}{c['slug']}.webp") for c in cards]
    res = parallel_download_webp(items, IMG_DIR, workers=12, timeout=15)
    for c in cards:
        c["image_local"] = res.get(c["slug"])
    ok = sum(1 for c in cards if c["image_local"])
    print(f"  downloaded: {ok}/{len(cards)}")

    print("[4/5] Matching (manufacturer=Дальхимфарм) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, manufacturer_pattern="дальхим|dalkhim")
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
               commit_msg=f"feat(images): Dalkhim sitemap v2 ({len(plan)} products, {matched} cards)")


if __name__ == "__main__":
    main()
