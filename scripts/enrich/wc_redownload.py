#!/usr/bin/env python3
"""Re-download missing files from existing /tmp/wc_manifest.json"""
import os, sys, json, re, urllib.request, urllib.parse, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from fetch_lib import save_webp

UA = "AptekaA-ImageEnricher/1.0 (medical-aggregator; mailto:noreply@aptekaa.ru)"
IMG_DIR = "/tmp/wc_img"
MANIFEST = "/tmp/wc_manifest.json"
PREFIX = "wc_"


def slugify(t):
    s = t.replace("File:", "")
    s = os.path.splitext(s)[0]
    s = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9]+", "_", s).strip("_")
    return s[:60].lower()


def fetch_bin(url, timeout=25, retries=4):
    safe = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")
    delay = 1.0
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(safe, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except Exception as e:
            last_err = e
            raise
    raise last_err


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    m = json.load(open(MANIFEST))
    todo = []
    for r in m:
        b = r.get("best")
        if not b: continue
        url = b.get("thumburl") or b.get("url")
        local = os.path.join(IMG_DIR, f"{PREFIX}{slugify(b['title'])}.webp")
        if os.path.exists(local): continue
        todo.append((r["name"], url, local, b["title"]))
    print(f"To download: {len(todo)}")

    def _dl(item):
        name, url, local, title = item
        try:
            raw = fetch_bin(url)
        except Exception as e:
            return name, None, str(e)[:80]
        if save_webp(raw, local, max_width=800):
            return name, local, None
        return name, None, "save_webp failed"

    ok = 0
    with ThreadPoolExecutor(max_workers=2) as ex:
        for n, p, err in ex.map(_dl, todo):
            if p:
                ok += 1
                print(f"  OK  {n!r}")
            else:
                print(f"  FAIL {n!r}: {err}")
            # tiny delay to be polite to wikimedia
            time.sleep(0.5)
    print(f"DONE: {ok}/{len(todo)}")


if __name__ == "__main__":
    main()
