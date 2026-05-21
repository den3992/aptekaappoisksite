#!/usr/bin/env python3
"""Berlin-Chemie (berlin-chemie.ru) static-HTML scraper via sitemap.

Sitemap: berlin-chemie.ru/wp-sitemap-posts-medicines-1.xml -> 104 URLs.
Each /medicine/<slug>/ page has H1 (brand name + ®) and a wp-content image.
Variant pages (/medicine/<brand>/<variant>/) also have unique images per dosage.
"""
import os, re, sys, json, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup
from fetch_lib import parallel_fetch, parallel_download_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

SITEMAP = "https://berlin-chemie.ru/wp-sitemap-posts-medicines-1.xml"
HOST = "https://berlin-chemie.ru"
IMG_DIR = "/tmp/bc_img"
MANIFEST = "/tmp/bc_products.json"
PREFIX = "bc_"
# skip instruction-only pages
SKIP_SLUG_RE = re.compile(r"^instrukcziya")


def get_urls():
    r = urllib.request.urlopen(SITEMAP, timeout=20).read().decode("utf-8")
    return re.findall(r"<loc>([^<]+)</loc>", r)


def parse_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None
    raw = h1.get_text(strip=True)
    # Variant pages: "Инструкция Мезим®форте" -> "Мезим форте"
    raw = re.sub(r"^Инструкци[яи]\s*", "", raw, flags=re.I)
    # Replace ® / ™ with a space so glued tokens split: "Мезим®форте" -> "Мезим форте"
    raw = re.sub(r"[®™]", " ", raw)
    trade = re.sub(r"\s+", " ", raw).strip()
    img_url = None
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        cls = " ".join(img.get("class", []))
        if not src: continue
        sl = src.lower()
        if any(s in sl for s in ("logo", "icon", "sprite", "banner", "watch", "/loader", "svg")):
            continue
        if "wp-content/uploads" in src or "wp-image" in cls:
            if src.startswith("/"): src = HOST + src
            elif not src.startswith("http"): src = HOST + "/" + src
            img_url = src
            break
    if not img_url:
        return None
    slug = url.rstrip("/").split("/")[-1]
    if SKIP_SLUG_RE.match(slug):
        return None
    return {"slug": slug, "trade_name": trade, "image_url": img_url, "href": url}


def main():
    print("[1/5] Fetching sitemap ...")
    urls = get_urls()
    urls = [u for u in urls if not SKIP_SLUG_RE.match(u.rstrip("/").split("/")[-1])]
    print(f"  product URLs: {len(urls)}")

    print("[2/5] Fetching product pages ...")
    pages = parallel_fetch(urls, workers=10, timeout=15)
    print(f"  fetched: {sum(1 for v in pages.values() if v)}/{len(urls)}")

    cards = []
    for u, html in pages.items():
        if not html: continue
        c = parse_page(html, u)
        if c: cards.append(c)
    print(f"  parsed cards with image: {len(cards)}")

    print("[3/5] Downloading images ...")
    items = [(c["slug"], c["image_url"], f"{PREFIX}{c['slug']}.webp") for c in cards]
    res = parallel_download_webp(items, IMG_DIR, workers=12, timeout=15)
    for c in cards:
        c["image_local"] = res.get(c["slug"])
    ok = sum(1 for c in cards if c["image_local"])
    print(f"  downloaded: {ok}/{len(cards)}")

    print("[4/5] Matching to DB (manufacturer=Берлин/менарини) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(
        trade_names,
        manufacturer_pattern="берлин|berlin|менарини|menarini",
    )
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
               commit_msg=f"feat(images): Berlin-Chemie via sitemap ({len(plan)} products, {matched} cards)")


if __name__ == "__main__":
    main()
