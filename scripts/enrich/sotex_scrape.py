#!/usr/bin/env python3
"""Sotex (sotex.ru) scraper via Playwright.

Catalog is SPA. Two obstacles handled here:
  1. Age/profession verification modal blocks clicks  -> click [data-is-pro]
  2. Show-more button appends 12 cards at a time      -> click until hidden
"""
import os, re, json, sys
sys.path.insert(0, os.path.dirname(__file__))
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan
from fetch_lib import parallel_download_webp

IMG_DIR = "/tmp/sx_img"
MANIFEST = "/tmp/sx_products.json"
PREFIX = "sx_"
HOST = "https://sotex.ru"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"


def scrape_cards():
    from playwright.sync_api import sync_playwright
    cards, seen = [], set()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(ignore_https_errors=True, user_agent=UA)
        page = ctx.new_page()
        page.goto(f"{HOST}/catalog/", timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        # Dismiss "are you a healthcare professional?" modal
        try:
            page.click('[data-is-pro]', timeout=5000)
            page.wait_for_timeout(800)
        except Exception as e:
            print(f"  (modal dismiss skipped: {e})")
        # Click show-more until it disappears
        for i in range(30):
            try:
                btn = page.locator('[data-show-more-btn]').first
                if not btn.is_visible(timeout=2500):
                    break
                btn.click(timeout=5000)
                page.wait_for_timeout(1100)
            except Exception:
                break
        # Extract
        data = page.eval_on_selector_all('.product-card',
            '''els => els.map(e => {
                const a = e.querySelector('a.product-card__overlink, a');
                const img = e.querySelector('img');
                return {
                    href: a ? a.href : null,
                    img: img ? (img.dataset.src || img.getAttribute('data-src') || img.src) : null,
                    text: e.innerText.trim().substring(0, 250)
                };
            })''')
        for d in data:
            if not d.get("img") or not d.get("text"): continue
            # First non-label line is the trade name
            lines = [l.strip() for l in d["text"].split("\n") if l.strip()]
            skip_lower = {"рецептурный", "препарат", "безрецептурный",
                          "рецептурный\nпрепарат"}
            trade = None
            for l in lines:
                low = l.lower()
                if low in skip_lower or low in ("рецептурный препарат",): continue
                trade = re.sub(r"[®™]", "", l).strip()
                break
            if not trade: continue
            slug = (d["href"] or "").rstrip("/").split("/")[-1] or trade.lower()
            if slug in seen: continue
            seen.add(slug)
            cards.append({
                "slug": slug,
                "trade_name": trade,
                "image_url": d["img"],
                "href": d["href"],
            })
        b.close()
    return cards


def main():
    print("[1/4] Scraping Sotex catalog ...")
    cards = scrape_cards()
    print(f"  total unique cards: {len(cards)}")
    if not cards:
        return

    print("[2/4] Downloading images as WebP ...")
    items = [(c["slug"], c["image_url"], f"{PREFIX}{c['slug']}.webp") for c in cards]
    res = parallel_download_webp(items, IMG_DIR, workers=12, timeout=15)
    for c in cards:
        c["image_local"] = res.get(c["slug"])
    ok = sum(1 for c in cards if c["image_local"])
    print(f"  downloaded: {ok}/{len(cards)}")

    print("[3/4] Matching trade names to DB (manufacturer=Сотекс) ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, manufacturer_pattern="сотекс|sotex")
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

    if not plan:
        return
    print("[4/4] Applying plan ...")
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): Sotex via Playwright ({len(plan)} products, {matched} cards)")


if __name__ == "__main__":
    main()
