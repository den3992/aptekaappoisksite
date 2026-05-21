"""Shared library for parallel HTTP fetching and image-to-WebP conversion."""
import os, subprocess, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from PIL import Image

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"


def fetch_one(url, binary=False, timeout=8):
    # URL-encode any non-ASCII (Cyrillic etc.) in path/query
    safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")
    req = urllib.request.Request(safe_url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def parallel_fetch(urls, workers=15, timeout=8, binary=False):
    """Concurrently fetch list of URLs. Returns dict {url: html_or_bytes_or_None}."""
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_one, u, binary, timeout): u for u in urls}
        for fut in as_completed(futures):
            u = futures[fut]
            try:
                out[u] = fut.result()
            except Exception:
                out[u] = None
    return out


def save_webp(raw_bytes, out_path, max_width=800, quality=85):
    """Save image bytes as WebP. Returns True on success."""
    try:
        im = Image.open(BytesIO(raw_bytes))
        if im.mode in ("P", "RGBA", "LA"):
            im = im.convert("RGBA").convert("RGB")
        else:
            im = im.convert("RGB")
        if im.width > max_width:
            ratio = max_width / im.width
            im = im.resize((max_width, int(im.height * ratio)), Image.LANCZOS)
        im.save(out_path, "WEBP", quality=quality, method=6)
        return True
    except Exception:
        return False


def parallel_download_webp(items, out_dir, workers=15, timeout=10):
    """items: list of (key, image_url, output_filename). Returns dict {key: out_path or None}."""
    os.makedirs(out_dir, exist_ok=True)
    def _job(item):
        key, url, fname = item
        out = os.path.join(out_dir, fname)
        try:
            raw = fetch_one(url, binary=True, timeout=timeout)
        except Exception:
            return key, None
        if save_webp(raw, out):
            return key, out
        return key, None
    res = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, p in ex.map(_job, items):
            res[k] = p
    return res
