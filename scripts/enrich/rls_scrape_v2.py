#!/usr/bin/env python3
"""RLS.net scraper v2 — parallel, large-scale.

Improvements over v1:
  - parallel fetch of all 64 letter index pages
  - parallel fetch of all drug pages (no sleep)
  - bulk DB matching with EXCLUDED manufacturer list
  - resume from existing manifest
"""
import os, re, json, sys, urllib.parse, time
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(__file__))
from fetch_lib import parallel_fetch, fetch_one, save_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

HOST = "https://www.rlsnet.ru"
IMG_DIR = "/tmp/rls_img"
MANIFEST = "/tmp/rls_products_v2.json"
PREFIX = "rls_"
TARGET_PHOTOS = int(os.environ.get("RLS_TARGET", "2000"))
WORKERS = 20

LETTER_INDEXES = list("12") + list("abcdefghijklmnopqrstuvwxyz")

# Excluded manufacturers (already processed by manufacturer scrapers)
EXCLUDE_MFG = "|".join([
    "ОЗОН", "ВЕЛФАРМ", "КАНОНФАРМА", "ОБНОВЛЕНИЕ", "PFK OBNOVLENIE",
    "ГРОТЕКС", "ФАРМСТАНДАРТ", "ВЕРТЕКС", "ИЗВАРИНО", "ОТИСИФАРМ",
    "МЕДИСОРБ", "АКРИХИН", "ВИФИТЕХ", "АВВА РУС", "ВАЛЕНТА",
    "ВЕРОФАРМ", "МИКРОГЕН", "МАТЕРИА МЕДИКА", "ФИРН М", "ЦИТОМЕД",
    "БИОНОРИКА", "НИАРМЕДИК", "ЭНДОФАРМ", "ЭНДОКРИННЫЙ ЗАВОД",
    "СИНТЕЗ",  # bnp_ (Кетопрофен-АКОС и др. — синтез делал)
])


def get_drug_urls():
    """Fetch all letter index pages in parallel, collect unique drug URLs."""
    urls = [f"{HOST}/drugs/ukazatel/{idx}" for idx in LETTER_INDEXES]
    print(f"  fetching {len(urls)} indexes ...")
    pages = parallel_fetch(urls, workers=10, timeout=15)
    drug_urls = set()
    for u, html in pages.items():
        if not html:
            continue
        for m in re.findall(r'href="(https://www\.rlsnet\.ru/drugs/[a-z0-9][a-z0-9\-]+)"', html):
            drug_urls.add(m)
    return sorted(drug_urls)


def extract_packing(html):
    m = re.search(r'<img\s+class="img"\s+src="(https://app\.rlsnet\.ru/api/storage/packing/[^"]+)"\s+alt="([^"]+)"', html)
    if not m:
        return None
    return m.group(1), m.group(2)


def extract_trade_name(html):
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
    if not m:
        return None
    title = m.group(1)
    name = re.split(r"\s+[\u2014\u2013\-]\s+инструкц", title, maxsplit=1)[0].strip()
    return name


def main():
    os.makedirs(IMG_DIR, exist_ok=True)

    # Load existing manifest
    cache = {}
    if os.path.exists(MANIFEST):
        try:
            cache = {p["rls_id"]: p for p in json.load(open(MANIFEST))}
        except Exception:
            cache = {}
    print(f"[1/6] Cached entries: {len(cache)}")

    # Also load OLD manifest (v1) to seed cache
    if os.path.exists("/tmp/rls_products.json"):
        try:
            for p in json.load(open("/tmp/rls_products.json")):
                if p["rls_id"] not in cache:
                    cache[p["rls_id"]] = p
        except Exception:
            pass
    print(f"  total cached after merge: {len(cache)}")

    # Drug URL list (sorted, deterministic)
    print("[2/6] Collecting drug URLs ...")
    drug_urls = get_drug_urls()
    print(f"  total drug URLs: {len(drug_urls)}")

    # Step 1: parallel-fetch drug pages in batches; collect packing-image URLs
    # We stop early once we have >= TARGET_PHOTOS NEW photos.
    print(f"[3/6] Scanning drug pages (parallel x{WORKERS}) until {TARGET_PHOTOS} new photos...")
    BATCH = 200
    pending = [u for u in drug_urls if u.split("-")[-1] not in cache]
    print(f"  pending (not cached): {len(pending)}")

    new_photos = sum(1 for p in cache.values() if p.get("image_local"))
    print(f"  starting with {new_photos} cached photos in IMG_DIR")
    # Recount real photos on disk
    new_photos = 0

    t0 = time.time()
    processed = 0

    def fetch_extract(url):
        rls_id = url.rstrip("/").split("-")[-1]
        try:
            html = fetch_one(url, timeout=8)
        except Exception:
            return rls_id, url, None, None, None
        packing = extract_packing(html)
        trade = extract_trade_name(html) or url.split("/")[-1]
        if not packing:
            return rls_id, url, trade, None, None
        img_url, alt = packing
        return rls_id, url, trade, img_url, alt

    for i in range(0, len(pending), BATCH):
        batch = pending[i:i + BATCH]
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = [ex.submit(fetch_extract, u) for u in batch]
            for fut in as_completed(futs):
                rls_id, url, trade, img_url, alt = fut.result()
                processed += 1
                if rls_id in cache:
                    continue
                cache[rls_id] = {
                    "rls_id": rls_id, "url": url, "trade_name": trade,
                    "image_url": img_url, "image_local": None, "alt": alt,
                }
        # Save progress
        json.dump(list(cache.values()), open(MANIFEST, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        # Count packings found so far
        with_packing = sum(1 for p in cache.values() if p.get("image_url"))
        dt = time.time() - t0
        print(f"  batch {i//BATCH+1}: processed={processed}/{len(pending)} packing_found={with_packing} elapsed={dt:.1f}s")
        if with_packing >= TARGET_PHOTOS + 100:  # +100 buffer for download failures
            print("  reached target packing count; stopping scan")
            break

    print(f"[4/6] Total with packing URL: {sum(1 for p in cache.values() if p.get('image_url'))}")

    # Step 2: parallel download images
    to_dl = [p for p in cache.values()
             if p.get("image_url") and not p.get("image_local")]
    print(f"  to download: {len(to_dl)}")

    def _dl(p):
        ext = os.path.splitext(urllib.parse.urlparse(p["image_url"]).path)[1].lower().lstrip(".") or "gif"
        out_webp = os.path.join(IMG_DIR, f"{PREFIX}{p['rls_id']}.webp")
        if os.path.exists(out_webp):
            return p["rls_id"], out_webp
        try:
            raw = fetch_one(p["image_url"], binary=True, timeout=15)
        except Exception:
            return p["rls_id"], None
        if save_webp(raw, out_webp):
            return p["rls_id"], out_webp
        return p["rls_id"], None

    success = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for rid, path in ex.map(_dl, to_dl):
            if path:
                cache[rid]["image_local"] = path
                success += 1
    print(f"  downloaded: {success}/{len(to_dl)}")
    # Save again
    json.dump(list(cache.values()), open(MANIFEST, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # Step 3: bulk match (with exclusion list)
    print(f"[5/6] Bulk matching with excluded manufacturers ...")
    candidates = [p for p in cache.values() if p.get("image_local")]
    # Strip ® from trade names
    for c in candidates:
        c["trade_clean"] = re.sub(r"[®™]", "", c["trade_name"]).strip()
    trade_names = sorted({c["trade_clean"] for c in candidates})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, exclude_manufacturers=EXCLUDE_MFG)
    plan = []
    matched_count = 0
    for c in candidates:
        docs = matches.get(c["trade_clean"], [])
        slugs = [d["slug"] for d in docs if not d.get("image_url")]
        if not slugs:
            continue
        plan.append({
            "image_local": c["image_local"],
            "image_url": f"/img/meds/{PREFIX}{c['rls_id']}.webp",
            "slugs": slugs,
            "trade": c["trade_clean"],
        })
        matched_count += len(slugs)
    print(f"  plan: {len(plan)} RLS products -> {matched_count} DB slugs")

    if not plan:
        return

    print(f"[6/6] Applying ...")
    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): RLS scale ({len(plan)} photos, {matched_count} cards)")


if __name__ == "__main__":
    main()
