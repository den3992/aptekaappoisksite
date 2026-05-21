#!/usr/bin/env python3
"""Wikimedia Commons scraper.

For each unique medication NAME without image:
  1. Build query variants (Russian trade, Russian MNN, Latin/English MNN translit).
  2. Search Commons (File namespace) with each variant; take first matching candidate
     that has packaging/box keywords in filename or filtered by relevant categories.
  3. Fetch imageinfo (thumbnail URL 600px, license, artist).
  4. Skip files with license != CC* / Public Domain.
  5. Download thumbnail → WebP, save as wc_<slug>.webp.
  6. Bulk-match by NAME against DB (records without image_url), apply image_url.

Notes:
  - All Commons content is freely licensed (mostly CC-BY-SA, CC0, PD).
  - License/Artist is stored in the manifest for attribution if needed later.
"""
import os, re, json, sys, urllib.parse, urllib.request, urllib.error, time
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(__file__))
from fetch_lib import save_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan
from mnn_translit import search_variants
import json as _json

UA = "AptekaA-ImageEnricher/1.0 (medical-aggregator; mailto:noreply@aptekaa.ru)"
API = "https://commons.wikimedia.org/w/api.php"
IMG_DIR = "/tmp/wc_img"
NAMES_FILE = "/tmp/wc_names.json"
MANIFEST = "/tmp/wc_manifest.json"
PREFIX = "wc_"

# Strong markers that the file IS a packaging/pill/vial photo (REQUIRED — at least one must match).
GOOD_KEYWORDS = [
    # English
    "pack", "packag", "box", "blister", "tablet", "capsule", "pill",
    "bottle", "vial", "ampoule", "syringe", "sachet", "tube", "spray",
    "tabletten", "kapseln", "schachtel", "verpackung",
    # Russian
    "упаков", "блистер", "таблет", "капсул", "флакон", "ампул", "коробк",
    "пакет", "тюбик", "шприц", "мазь", "крем", "сироп", "раствор",
    "пастил", "суспенз", "гранул", "капли", "спрей",
]
# Strong markers that the file is NOT a packaging photo (REJECT if any matches).
BAD_KEYWORDS = [
    # Chemistry / structure
    "skeletal", "molecule", "structure", "formula", "synthesis", "compound",
    "ball-and-stick", "ball_and_stick", "ball and stick",
    "3d-balls", "3d_balls", "3d-xray", "3d_xray", "3d-spacefill", "3d-balls",
    "xray", "x-ray", "x_ray", "crystal", "crystallin", "from-xtal", "from_xtal",
    "spacefill", "wireframe", "stickball", "stick-ball", "ball-stick",
    "model", "конфигурац", "молекул", "формула", "схем", "график",
    # Documents
    ".svg", ".pdf", "graph", "plot", "chart", "diagram", "диаграмм",
    "патент", "patent", "history", "1960s", "1970s", "1980s", "1990s",
    "factory", "plants", "production", "industri", "завод",
    # Non-product
    "logo", "лого", "instagram", "twitter", "facebook",
    # Brand artifacts not packaging
    "ad ", "advertis", "реклам",
]
GOOD_LICENSES = ["CC0", "CC BY", "CC-BY", "CC-PD", "PD", "Public domain", "Public Domain"]


def fetch_json(url, timeout=12, retries=4):
    delay = 1.0
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise last_err


def fetch_bin(url, timeout=20, retries=4):
    delay = 1.0
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise last_err


def search_commons(query, limit=10):
    qs = urllib.parse.urlencode({
        "action": "query", "format": "json", "list": "search",
        "srsearch": query, "srnamespace": "6", "srlimit": str(limit),
    })
    try:
        data = fetch_json(f"{API}?{qs}")
    except Exception:
        return []
    return [s["title"] for s in data.get("query", {}).get("search", [])]


def get_imageinfo(titles):
    """Bulk imageinfo for up to 50 titles."""
    qs = urllib.parse.urlencode({
        "action": "query", "format": "json",
        "titles": "|".join(titles),
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": "600",
    })
    try:
        data = fetch_json(f"{API}?{qs}")
    except Exception:
        return {}
    out = {}
    for pid, page in data.get("query", {}).get("pages", {}).items():
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            continue
        title = page.get("title", "")
        em = info.get("extmetadata") or {}
        out[title] = {
            "title": title,
            "url": info.get("url"),
            "thumburl": info.get("thumburl"),
            "thumbwidth": info.get("thumbwidth"),
            "mime": info.get("mime"),
            "width": info.get("width"),
            "height": info.get("height"),
            "license": (em.get("LicenseShortName") or {}).get("value"),
            "artist": (em.get("Artist") or {}).get("value"),
            "category": (em.get("Categories") or {}).get("value"),
            "objectName": (em.get("ObjectName") or {}).get("value"),
        }
    return out


def is_good_file(meta):
    """Decide whether a Commons file is usable as a medication photo.

    STRICT rules:
      - must be raster image (no svg/pdf)
      - must have valid Commons-friendly license
      - title MUST contain at least one GOOD keyword
      - title MUST NOT contain any BAD keyword
      - sane dimensions (>=300px on each side)
    """
    title = (meta.get("title") or "").lower()
    if not meta.get("mime", "").startswith("image/"):
        return False
    if meta.get("mime") == "image/svg+xml":
        return False
    lic = (meta.get("license") or "").upper()
    if not any(l.upper() in lic for l in GOOD_LICENSES):
        return False
    if any(b in title for b in BAD_KEYWORDS):
        return False
    if not any(g in title for g in GOOD_KEYWORDS):
        return False
    if (meta.get("width") or 0) < 300 or (meta.get("height") or 0) < 300:
        return False
    return True


def score_file(meta):
    """Higher = better fit as a packaging photo."""
    title = (meta.get("title") or "").lower()
    score = 0
    for kw in GOOD_KEYWORDS:
        if kw in title:
            score += 5
    # Square-ish photos slightly preferred
    w, h = meta.get("width") or 1, meta.get("height") or 1
    aspect = max(w, h) / min(w, h)
    if aspect < 2:
        score += 1
    # CC0 preferred
    if "CC0" in (meta.get("license") or "").upper():
        score += 2
    return score


def find_best_for(name, mnn):
    """Try variants in order, score candidates, return best meta or None."""
    candidates_total = []
    for query, prio in search_variants(name, mnn):
        titles = search_commons(query, limit=8)
        if not titles:
            continue
        infos = get_imageinfo(titles[:8])
        for t, m in infos.items():
            if not is_good_file(m):
                continue
            m["_score"] = score_file(m) + prio
            candidates_total.append(m)
        if candidates_total:
            break  # don't waste API calls if we already have hits
    if not candidates_total:
        return None
    candidates_total.sort(key=lambda x: -x["_score"])
    return candidates_total[0]


def slugify_filename(title):
    """Wikimedia title -> safe local slug."""
    s = title.replace("File:", "")
    s = os.path.splitext(s)[0]
    s = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9]+", "_", s).strip("_")
    return s[:60].lower()


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    if not os.path.exists(NAMES_FILE):
        print(f"ERROR: {NAMES_FILE} not found. Run prepare-names step first.")
        return
    names_data = json.load(open(NAMES_FILE))
    print(f"Loaded {len(names_data)} unique names without image")

    # Resume from manifest
    manifest = {}
    if os.path.exists(MANIFEST):
        try:
            manifest = {m["name"]: m for m in json.load(open(MANIFEST))}
        except Exception:
            manifest = {}
    print(f"Resume cache: {len(manifest)} names already searched")

    LIMIT = int(os.environ.get("WC_LIMIT", "200"))
    pending = [n for n in names_data if n["name"] not in manifest][:LIMIT]
    print(f"Searching Commons for {len(pending)} names (limit={LIMIT})...")

    def worker(rec):
        name, mnn = rec["name"], rec.get("mnn", "")
        try:
            best = find_best_for(name, mnn)
        except Exception as e:
            return name, {"name": name, "mnn": mnn, "error": str(e)[:120], "best": None}
        return name, {"name": name, "mnn": mnn, "best": best}

    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:  # rate-friendly
        futures = [ex.submit(worker, r) for r in pending]
        for fut in as_completed(futures):
            name, entry = fut.result()
            manifest[name] = entry
            done += 1
            if done % 25 == 0:
                with_hit = sum(1 for v in manifest.values() if v.get("best"))
                print(f"  searched {done}/{len(pending)}  total_hits={with_hit}  elapsed={time.time()-t0:.1f}s")
                json.dump(list(manifest.values()), open(MANIFEST, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
    json.dump(list(manifest.values()), open(MANIFEST, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    with_hit = sum(1 for v in manifest.values() if v.get("best"))
    print(f"DONE search: hits={with_hit}/{len(manifest)}")

    # Download all best thumbnails
    print("\n[Download] preparing list ...")
    to_dl = []
    for entry in manifest.values():
        best = entry.get("best")
        if not best:
            continue
        url = best.get("thumburl") or best.get("url")
        if not url:
            continue
        local = os.path.join(IMG_DIR, f"{PREFIX}{slugify_filename(best['title'])}.webp")
        to_dl.append((entry["name"], url, local, best["title"]))
    print(f"  candidates to download: {len(to_dl)}")

    def _dl(item):
        name, url, local, title = item
        if os.path.exists(local):
            return name, local
        try:
            raw = fetch_bin(url, timeout=25)
        except Exception:
            return name, None
        if save_webp(raw, local, max_width=800):
            return name, local
        return name, None

    name_to_local = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        for n, p in ex.map(_dl, to_dl):
            if p:
                name_to_local[n] = p
    print(f"  downloaded: {len(name_to_local)}")

    # Bulk match by NAME (DB has medication.name field, but our match_lib matches
    # by label_name. For Wikimedia we just use the manifest -> name-based slug list
    # built BEFORE search.)
    print("\n[Apply] building update ops ...")
    name_to_slugs = {r["name"]: r["slugs"] for r in names_data}
    plan = []
    matched = 0
    for name, local in name_to_local.items():
        slugs = name_to_slugs.get(name, [])
        if not slugs:
            continue
        # Use a stable URL: image_local basename
        url_path = f"/img/meds/{os.path.basename(local)}"
        plan.append({
            "image_local": local,
            "image_url": url_path,
            "slugs": slugs,
            "trade": name,
        })
        matched += len(slugs)
    print(f"  plan: {len(plan)} photos -> {matched} DB cards")

    if not plan:
        return

    apply_plan(plan, prefix=PREFIX,
               commit_msg=f"feat(images): Wikimedia Commons ({len(plan)} photos, {matched} cards)")


if __name__ == "__main__":
    main()
