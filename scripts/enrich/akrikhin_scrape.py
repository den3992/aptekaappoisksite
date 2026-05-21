#!/usr/bin/env python3
"""Akrikhin (akrikhin.ru) static-HTML scraper.

Catalog: /catalog/page{1..N}/ — each lists multiple product cards.
Product pages live at /catalog/(retsepturnye|bezretsepturnye)/<slug>/.
Each product page has the page <title> = trade name + form + dose, and image at
/upload/resize_cache/akrikhin.pim/assets/<EAN>/IMG_PACK_FRONT/650_650_1/<EAN>_1.jpg.
"""
import os, re, sys, json, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup
from fetch_lib import parallel_fetch, parallel_download_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

HOST = "https://akrikhin.ru"
IMG_DIR = "/tmp/akr_img"
MANIFEST = "/tmp/akr_products.json"
PREFIX = "akr_"
UA = {"User-Agent": "Mozilla/5.0 Firefox/120"}


def get_product_urls(max_pages=20):
    seen = set()
    for n in range(1, max_pages + 1):
        url = f"{HOST}/catalog/page{n}/" if n > 1 else f"{HOST}/catalog/"
        req = urllib.request.Request(url, headers=UA)
        try:
            html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
        except Exception:
            break
        soup = BeautifulSoup(html, "html.parser")
        added = 0
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if re.match(r"^/catalog/(retsepturnye|bezretsepturnye)/[^/]+/$", h):
                full = HOST + h
                if full not in seen:
                    seen.add(full)
                    added += 1
        print(f"  page {n}: added {added} (cumulative {len(seen)})")
        if not added:
            break
    return sorted(seen)


def parse_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title else None
    if not title:
        return None
    # Trade name = first segment of title before form/dose
    trade = re.sub(r"[®™]", " ", title)
    # Heuristic: take everything before opening parenthesis or comma or known form keyword
    trade = re.split(r"\s+\(|\s+,|\s+(?:таблет|капс|раствор|мазь|крем|гель|капли|спрей|сироп|сусп|порошок|инъекц|лиоф|глазн|вагинал|пастил)", trade, 1, re.I)[0]
    trade = re.sub(r"\s+", " ", trade).strip()
    if not trade:
        return None
    img_url = None
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if "akrikhin.pim" in src and "IMG_PACK_FRONT" in src and "650_650" in src:
            if src.startswith("/"): src = HOST + src
            img_url = src
            break
    if not img_url:
        # fallback: any IMG_PACK
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src") or ""
            if "akrikhin.pim" in src and "650_650" in src:
                if src.startswith("/"): src = HOST + src
                img_url = src
                break
    if not img_url:
        return None
    slug = url.rstrip("/").split("/")[-1]
    return {"slug": slug, "trade_name": trade, "image_url": img_url, "href": url}


def main():
    print("[1/5] Discovering product URLs ...")
    urls = get_product_urls()
    print(f"  total products: {len(urls)}")

    print("[2/5] Fetch product pages ...")
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

    print("[4/5] Matching (manufacturer=Акрихин) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, manufacturer_pattern="акрихин|akrikhin")
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
               commit_msg=f"feat(images): Akrikhin catalog ({len(plan)} products, {matched} cards)")


if __name__ == "__main__":
    main()
