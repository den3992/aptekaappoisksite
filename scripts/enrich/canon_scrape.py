#!/usr/bin/env python3
"""Canonpharma (canonpharma.ru) scraper.

Catalog at /catalog/?PAGEN_1=N (16 cards per page, ~13 pages, ~193 unique items).
Each item:
  <a class="catalog_card" href="/catalog/<slug>/">
    <img class="lazyload" data-src="/upload/iblock/.../<hash>.jpg" alt="Trade Канон"/>
    <span class="catalog_card__title">Trade Канон</span> (may include <sup>®</sup>)

Note: canonpharma.ru blocks our local container (geo); script runs ON REMOTE.
"""
import os, re, json, sys, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remote_lib import find_db_matches_bulk, apply_plan

HOST = "https://canonpharma.ru"
IMG_DIR = "/tmp/cn_img"
MANIFEST = "/tmp/cn_products.json"
PREFIX = "cn_"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
MAX_PAGES = 15

ITEM_RE = re.compile(
    r'<a class="catalog_card" href="(/catalog/[^"]+/)">\s*'
    r'<span class="catalog_card__wrapper">\s*'
    r'<span class="catalog_card__img">\s*'
    r'<img\s+class="lazyload"\s+data-src="(/upload/iblock/[^"]+\.(?:jpg|jpeg|png|webp))"[^>]*/?>\s*'
    r'</span>.*?'
    r'<span class="catalog_card__title">\s*(.+?)\s*</span>',
    re.S
)


def clean_title(raw):
    t = re.sub(r"<[^>]+>", "", raw)
    t = re.sub(r"[®™]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fetch(url, binary=False, timeout=15):
    safe = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")
    req = urllib.request.Request(safe, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def save_webp(raw, out, max_width=800, quality=85):
    try:
        im = Image.open(BytesIO(raw))
        if im.mode in ("P", "RGBA", "LA"):
            im = im.convert("RGBA").convert("RGB")
        else:
            im = im.convert("RGB")
        if im.width > max_width:
            ratio = max_width / im.width
            im = im.resize((max_width, int(im.height * ratio)), Image.LANCZOS)
        im.save(out, "WEBP", quality=quality, method=6)
        return True
    except Exception:
        return False


def extract_base_trade(title):
    """'Анаприлин Канон 10' -> 'Анаприлин Канон'."""
    t = re.sub(r"\s+\d+.*$", "", title).strip()
    # Drop trailing parens like (жевательные таблетки)
    t = re.sub(r"\s*\([^)]+\)$", "", t).strip()
    return t


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    print(f"[1/5] Fetching {MAX_PAGES} pages in parallel ...")
    urls = [f"{HOST}/catalog/?PAGEN_1={n}" for n in range(1, MAX_PAGES + 1)]
    pages = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for u, p in zip(urls, ex.map(lambda u: (u, fetch(u, timeout=15)), urls)):
            pages[p[0]] = p[1]
    print(f"  fetched: {sum(1 for v in pages.values() if v)}/{len(urls)}")

    cards = []
    seen = set()
    for u, html in pages.items():
        if not html: continue
        for href, img, raw_title in ITEM_RE.findall(html):
            slug = href.rstrip("/").split("/")[-1]
            if slug in seen: continue
            seen.add(slug)
            title = clean_title(raw_title)
            cards.append({
                "slug": slug,
                "title": title,
                "trade_name": extract_base_trade(title),
                "image_url": HOST + img,
            })
    print(f"  unique: {len(cards)}")

    print("[2/5] Downloading images ...")
    def _dl(card):
        out = os.path.join(IMG_DIR, f"{PREFIX}{card['slug']}.webp")
        try:
            raw = fetch(card["image_url"], binary=True, timeout=15)
        except Exception:
            return card["slug"], None
        if save_webp(raw, out, max_width=800):
            return card["slug"], out
        return card["slug"], None
    success = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for slug, path in ex.map(_dl, cards):
            if path: success[slug] = path
    print(f"  downloaded: {len(success)}/{len(cards)}")
    for c in cards:
        c["image_local"] = success.get(c["slug"])

    print("[3/5] Bulk matching (КАНОНФАРМА only) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names,
                                    manufacturer_pattern="канонфарма")
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
               commit_msg=f"feat(images): Canonpharma ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
