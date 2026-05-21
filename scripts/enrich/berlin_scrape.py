#!/usr/bin/env python3
"""Berlin-Chemie (berlin-chemie.ru) scraper via Playwright.

1. Visit /medications/ → collect .medication-item href + name
2. For each product → fetch /medicine/<slug>/ and grab first /wp-content/uploads/ image
3. Match to DB by trade name (manufacturer filter: berlin-chemie / menarini).
"""
import os, re, json, sys, urllib.parse, urllib.request, time
from io import BytesIO
from PIL import Image
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

HOST = "https://berlin-chemie.ru"
IMG_DIR = "/tmp/bc_img"
MANIFEST = "/tmp/bc_products.json"
PREFIX = "bc_"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"


def fetch_bin(url, timeout=20):
    safe = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")
    req = urllib.request.Request(safe, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


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


def scrape():
    from playwright.sync_api import sync_playwright
    cards = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(user_agent=UA).new_page()
        page.goto(f"{HOST}/medications/?lang=ru", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(1000)
        items = page.eval_on_selector_all('.medication-item',
            '''els => els.map(e => {
                const a = e.querySelector('a') || e;
                return { href: a.href, name: (a.innerText || a.textContent).trim() };
            }).filter(o => o.href && o.name)''')
        print(f"  product links: {len(items)}")
        # Now fetch each product page and extract image
        for i, it in enumerate(items):
            try:
                page.goto(it["href"], timeout=20000, wait_until="domcontentloaded")
                page.wait_for_timeout(500)
                img = page.eval_on_selector_all(
                    'img[src*="/wp-content/uploads/"]',
                    'els => els.length ? els[0].src : null'
                )
                if img:
                    trade = re.sub(r"[®™]", "", it["name"]).strip()
                    # Extract slug from path (strip query string)
                    path = urllib.parse.urlparse(it["href"]).path.rstrip("/")
                    slug = path.split("/")[-1] or re.sub(r"\W+", "-", trade.lower())[:30]
                    cards.append({"slug": slug, "trade_name": trade,
                                   "image_url": img, "href": it["href"]})
                    print(f"    [{i+1}/{len(items)}] {trade!r:35s} img: ...{img[-50:]}")
                else:
                    print(f"    [{i+1}/{len(items)}] {it['name']!r:35s} (no img)")
            except Exception as e:
                print(f"    [{i+1}/{len(items)}] FAIL {it['name']!r}: {str(e)[:80]}")
        browser.close()
    return cards


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    print("[1/5] Scraping Berlin-Chemie via Playwright ...")
    cards = scrape()
    print(f"  total: {len(cards)}")

    print("[2/5] Downloading images ...")
    def _dl(card):
        out = os.path.join(IMG_DIR, f"{PREFIX}{card['slug']}.webp")
        try:
            raw = fetch_bin(card["image_url"], timeout=20)
        except Exception:
            return card["slug"], None
        if save_webp(raw, out, max_width=800):
            return card["slug"], out
        return card["slug"], None
    success = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        for slug, path in ex.map(_dl, cards):
            if path: success[slug] = path
    print(f"  downloaded: {len(success)}/{len(cards)}")
    for c in cards:
        c["image_local"] = success.get(c["slug"])

    print("[3/5] Bulk matching (Berlin-Chemie / Menarini) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names,
                                    manufacturer_pattern="берлин|berlin|menarini|менарини")
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
               commit_msg=f"feat(images): Berlin-Chemie via Playwright ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
