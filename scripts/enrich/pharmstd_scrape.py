#!/usr/bin/env python3
"""Pharmstandard (pharmstd.ru) scraper. RUNS ON REMOTE SERVER (Russian IP).

Catalog at /index.php?page=11&pg=1&all=l (Windows-1251 encoded).
Item pattern: <img src="/upload/300spravo4nik_lekarstva/pr_<id>.jpg"> ... <p class="zag">Name</p>
"""
import os, re, json, sys, urllib.request, subprocess
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remote_lib import find_db_matches_bulk, apply_plan

HOST = "https://pharmstd.ru"
CATALOG = HOST + "/index.php?page=11&pg=1&all=l"
IMG_DIR = "/tmp/ps_img"
MANIFEST = "/tmp/ps_products.json"
PREFIX = "ps_"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"

ITEM_RE = re.compile(
    r'<img src="(/upload/300spravo4nik_lekarstva/pr_\d+\.jpg)"[^>]*>\s*'
    r'</span>\s*<p class="zag">([^<]+)</p>',
    re.S
)


def fetch(url, binary=False, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if binary:
        return data
    return data.decode("cp1251", "replace")


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
    t = re.sub(r"\s+", " ", title).strip()
    # Strip parenthetical form descriptors
    t = re.sub(
        r"\s*\((?:раствор|таблет|капс|мазь|крем|сироп|спрей|капли|гель|порош|сусп|"
        r"гран|пастил|свеч|супп|плёнк|пленк|драже|концентр|инъекц|ампул)[^)]*\)",
        "", t, flags=re.I
    ).strip()
    # Trailing form descriptor / dosage / numbers
    t = re.sub(
        r"\s+(таблет\w*|капс\w*|раствор|мазь|крем|сироп|спрей|капли|гель|порош\w*|"
        r"суспенз\w*|гран\w*|пастил\w*|свеч\w*|супп\w*|плёнк\w*|пленк\w*|драже|"
        r"кардио|форте|плюс|экспресс|с\s.*|для\s.*|\d.*)$",
        "", t, flags=re.I
    ).strip()
    return t


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    print("[1/5] Fetching catalog ...")
    html_text = fetch(CATALOG)
    print(f"  bytes: {len(html_text)}")

    items = ITEM_RE.findall(html_text)
    print(f"[2/5] Parsed items: {len(items)}")
    seen = set()
    cards = []
    for img, title in items:
        m = re.search(r"pr_(\d+)\.jpg", img)
        if not m: continue
        pid = m.group(1)
        if pid in seen: continue
        seen.add(pid)
        clean = re.sub(r"\s+", " ", title).strip()
        cards.append({
            "id": pid, "title": clean,
            "trade_name": extract_base_trade(clean),
            "image_url": HOST + img,
        })
    print(f"  unique: {len(cards)}")

    print("[3/5] Downloading images (parallel) ...")
    def _dl(card):
        out = os.path.join(IMG_DIR, f"{PREFIX}{card['id']}.webp")
        try:
            raw = fetch(card["image_url"], binary=True)
        except Exception:
            return card["id"], None
        if save_webp(raw, out):
            return card["id"], out
        return card["id"], None
    success = {}
    with ThreadPoolExecutor(max_workers=15) as ex:
        for pid, path in ex.map(_dl, cards):
            if path: success[pid] = path
    print(f"  downloaded {len(success)}/{len(cards)}")
    for c in cards:
        c["image_local"] = success.get(c["id"])

    print("[4/5] Bulk matching ...")
    trade_names = sorted({c["trade_name"] for c in cards if c["image_local"]})
    print(f"  unique trade names: {len(trade_names)}")
    matches = find_db_matches_bulk(trade_names, manufacturer_pattern="фармстандарт")
    plan = []
    matched = 0
    for c in cards:
        if not c["image_local"]: continue
        docs = matches.get(c["trade_name"], [])
        slugs = [d["slug"] for d in docs if not d.get("image_url")]
        if not slugs: continue
        plan.append({
            "image_local": c["image_local"],
            "image_url": f"/img/meds/{PREFIX}{c['id']}.webp",
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
               commit_msg=f"feat(images): Pharmstandard scrape ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
