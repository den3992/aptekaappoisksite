#!/usr/bin/env python3
"""OTCPharm (otcpharm.ru) scraper.

Strategy:
  1. Fetch all letter pages /medicaments/?start_with=<letter> in parallel.
  2. Parse each card-product anchor into (slug, trade_name_text, image_url).
  3. Download images in parallel, convert to WebP, save as otc_<slug>.webp.
  4. Extract base trade name from h3 title (strip dosage/form numbers).
  5. Bulk-match against DB by trade name and apply.
"""
import os, re, json, sys
sys.path.insert(0, os.path.dirname(__file__))
from fetch_lib import parallel_fetch, fetch_one, save_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

HOST = "https://otcpharm.ru"
IMG_DIR = "/tmp/otc_img"
MANIFEST = "/tmp/otc_products.json"
PREFIX = "otc_"

# Russian alphabet (without Ё-only letters)
LETTERS = list("АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ")


CARD_RE = re.compile(
    r'<a\s+href="(/medicaments/[^"#?]+/?)"\s+class="card-product"[^>]*>'
    r'(?:(?!</a>).)*?'  # any chars not closing the tag
    r'<img[^>]+src="(/files/iblock/[^"]+\.(?:png|jpg|jpeg|webp))"'
    r'(?:(?!</a>).)*?'
    r'<h3[^>]*class="card-product__title[^"]*"[^>]*>\s*([^<]+?)\s*</h3>',
    re.S
)


def extract_base_trade(title):
    """Strip trailing dosage/numbers/form descriptors.

    'Амиксин 125 мг' -> 'Амиксин'
    'Арбидол Максимум' -> 'Арбидол Максимум' (keep sub-brand alpha words)
    'Компливит Кальций Д3 для малышей' -> 'Компливит Кальций Д3 для малышей'
      ... but we don't want descriptors, so drop tokens at first numeric/dosage
    """
    t = re.sub(r"\s+", " ", title).strip()
    # Drop everything starting from first standalone number / form descriptor
    m = re.search(r"^(.+?)(?:\s+(?:\d|таблет|капс|раствор|р-р|мазь|крем|сироп|спрей|капли|гель|порош|для\s|со\s))",
                  t, re.I)
    return m.group(1).strip() if m else t


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    # 1) Fetch letter pages in parallel
    print(f"[1/5] Fetching {len(LETTERS)} letter pages in parallel ...")
    urls = [f"{HOST}/medicaments/?start_with={l}" for l in LETTERS]
    pages = parallel_fetch(urls, workers=10, timeout=10)
    ok = sum(1 for v in pages.values() if v)
    print(f"  fetched {ok}/{len(urls)} pages")

    # 2) Parse all card-product blocks
    print("[2/5] Parsing product cards ...")
    cards = []
    seen_slugs = set()
    for url, html in pages.items():
        if not html:
            continue
        for href, img, title in CARD_RE.findall(html):
            slug = href.strip("/").split("/")[-1]
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            cards.append({
                "slug": slug,
                "title": title.strip(),
                "trade_name": extract_base_trade(title),
                "image_url": HOST + img,
                "letter_page": url,
            })
    print(f"  parsed {len(cards)} unique product cards")

    # 3) Download images in parallel
    print("[3/5] Downloading + converting images ...")
    from concurrent.futures import ThreadPoolExecutor, as_completed
    def _dl(card):
        out = os.path.join(IMG_DIR, f"{PREFIX}{card['slug']}.webp")
        try:
            raw = fetch_one(card["image_url"], binary=True, timeout=15)
        except Exception as e:
            return card["slug"], None, str(e)[:60]
        if save_webp(raw, out):
            return card["slug"], out, None
        return card["slug"], None, "cwebp/save fail"
    success = {}
    with ThreadPoolExecutor(max_workers=15) as ex:
        for slug, path, err in ex.map(_dl, cards):
            if path:
                success[slug] = path
    print(f"  downloaded {len(success)}/{len(cards)}")
    for c in cards:
        c["image_local"] = success.get(c["slug"])

    # 4) Bulk match
    print("[4/5] Bulk matching trade names against DB ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names)
    plan = []
    matched_count = 0
    for c in cards:
        if not c["image_local"]:
            continue
        docs = matches.get(c["trade_name"], [])
        slugs = [d["slug"] for d in docs if not d.get("image_url")]
        if not slugs:
            continue
        plan.append({
            "image_local": c["image_local"],
            "image_url": f"/img/meds/{PREFIX}{c['slug']}.webp",
            "slugs": slugs,
            "trade": c["trade_name"],
            "src_slug": c["slug"],
        })
        matched_count += len(slugs)
    print(f"  plan: {len(plan)} OTCPharm products -> {matched_count} DB slugs")
    json.dump({"cards": cards, "plan": plan, "match_counts": {k: len(v) for k,v in matches.items()}},
              open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    if not plan:
        print("Nothing to apply.")
        return

    # 5) Apply
    print("[5/5] Applying plan ...")
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): OTCPharm scrape ({len(plan)} photos, {matched_count} cards)")


if __name__ == "__main__":
    main()
