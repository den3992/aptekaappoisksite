#!/usr/bin/env python3
"""RLS.net scraper.
Walks /drugs/ukazatel/c{X} index pages, visits each drug page,
extracts the packing image (https://app.rlsnet.ru/api/storage/packing/{ext}/{id}_a.{ext}),
downloads it, converts to .webp, and saves a manifest with trade_name + alt text
so we can match against MongoDB on the remote.

Output:
  /tmp/rls_img/rls_<rls_id>.webp
  /tmp/rls_products.json
"""
import json, os, re, time, urllib.request, urllib.error, urllib.parse
from PIL import Image
from io import BytesIO

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
HOST = "https://www.rlsnet.ru"
IMG_DIR = "/tmp/rls_img"
MANIFEST = "/tmp/rls_products.json"

# Cyrillic block in URL: ca..f9 (each is one letter A..Я + numeric prefix used by RLS)
LETTER_INDEXES = [f"c{c}" for c in "0123456789abcdef"] + [f"d{c}" for c in "0123456789abcdef"] + \
                 [f"e{c}" for c in "0123456789abcdef"] + [f"f{c}" for c in "0123456789abcdef"]

TARGET_COUNT = int(os.environ.get("RLS_TARGET", "10"))


def fetch(url, binary=False, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if binary else r.read().decode("utf-8", "replace")


def get_drug_urls():
    """Walk first few index pages until we accumulate ~3000 drug URLs."""
    urls = []
    seen = set()
    for idx in LETTER_INDEXES:
        try:
            html = fetch(f"{HOST}/drugs/ukazatel/{idx}")
        except Exception as e:
            print(f"  idx {idx} fail: {e}")
            continue
        for m in re.findall(r'href="(https://www\.rlsnet\.ru/drugs/[a-z0-9][a-z0-9\-]+)"', html):
            if m not in seen:
                seen.add(m)
                urls.append(m)
        if len(urls) >= 3000:
            break
        time.sleep(0.15)
    return urls


def extract_packing(html):
    """Returns (img_url, alt_text) or None."""
    m = re.search(r'<img\s+class="img"\s+src="(https://app\.rlsnet\.ru/api/storage/packing/[^"]+)"\s+alt="([^"]+)"', html)
    if not m:
        return None
    return m.group(1), m.group(2)


def extract_trade_name(html):
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
    if not m:
        return None
    title = m.group(1)
    # Title format: "Нурофен® Экспресс — инструкция по применению..."
    name = re.split(r"\s+[\u2014\u2013\-]\s+инструкц", title, maxsplit=1)[0].strip()
    return name


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    existing = {}
    if os.path.exists(MANIFEST):
        try:
            existing = {p["rls_id"]: p for p in json.load(open(MANIFEST))}
        except Exception:
            existing = {}

    print(f"Already in manifest: {len(existing)}")
    urls = get_drug_urls()
    print(f"Collected drug URLs: {len(urls)}")

    products = list(existing.values())
    ok_count = sum(1 for p in products if p.get("image_local"))
    skipped = 0

    for i, url in enumerate(urls, 1):
        if ok_count >= TARGET_COUNT:
            break
        rls_id = url.rstrip("/").split("-")[-1]
        if rls_id in existing:
            skipped += 1
            continue
        try:
            html = fetch(url)
        except Exception as e:
            print(f"  [{i}] FAIL fetch {url}: {e!s:.80}")
            continue
        packing = extract_packing(html)
        trade_name = extract_trade_name(html) or url.split("/")[-1]
        if not packing:
            existing[rls_id] = {"rls_id": rls_id, "url": url, "trade_name": trade_name,
                                 "image_url": None, "image_local": None, "alt": None}
            continue
        img_url, alt = packing
        ext = os.path.splitext(urllib.parse.urlparse(img_url).path)[1].lower().lstrip(".") or "gif"
        out_webp = f"{IMG_DIR}/rls_{rls_id}.webp"
        try:
            raw = fetch(img_url, binary=True, timeout=30)
            im = Image.open(BytesIO(raw))
            if im.mode in ("P", "RGBA", "LA"):
                im = im.convert("RGBA").convert("RGB")
            else:
                im = im.convert("RGB")
            # Resize to max width 800 keeping aspect ratio
            if im.width > 800:
                ratio = 800 / im.width
                im = im.resize((800, int(im.height * ratio)), Image.LANCZOS)
            im.save(out_webp, "WEBP", quality=85, method=6)
        except Exception as e:
            print(f"  [{i}] download/convert FAIL {rls_id}: {e!s:.100}")
            continue
        entry = {"rls_id": rls_id, "url": url, "trade_name": trade_name,
                 "image_url": img_url, "image_local": out_webp, "alt": alt}
        existing[rls_id] = entry
        products = list(existing.values())
        ok_count = sum(1 for p in products if p.get("image_local"))
        print(f"  [{i}] OK {rls_id}  trade='{trade_name}'  alt='{alt[:60]}'")
        # Save progressively
        json.dump(products, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        time.sleep(0.2)

    json.dump(products, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nDONE: scanned={i}, with_image={ok_count}, skipped(cached)={skipped}")


if __name__ == "__main__":
    main()
