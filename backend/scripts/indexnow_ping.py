#!/usr/bin/env python3
"""
IndexNow ping — уведомляет Яндекс/Bing об изменившихся страницах.
Читает список slug-ов из файла (по одному на строку), строит URL
страниц препаратов и батчами шлёт на IndexNow endpoint.

Usage:
    python3 indexnow_ping.py <changed_slugs_file>
    python3 indexnow_ping.py --full-snapshot
"""
import sys
import json
import os
import urllib.request
from datetime import datetime, timezone
from pymongo import MongoClient
from api.price_indexing import indexable_pairs_pipeline

HOST = "aptekaa.ru"
KEY = "3c6a00678b80a261eee94accd64427c7"
KEY_LOCATION = f"https://{HOST}/{KEY}.txt"
ENDPOINT = "https://api.indexnow.org/indexnow"   # шлёт сразу всем партнёрам (Bing, Yandex, Seznam)
BATCH = 10000   # лимит IndexNow на один запрос
CITIES = ["msk", "spb", "krd", "nn", "ekb", "kzn", "nsk", "sam", "chel", "ufa", "rnd", "vrn"]
def indexable_urls(slugs):
    """Return only city/slug pairs that the live page marks indexable."""
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        raise RuntimeError("MONGO_URL is required; refusing to submit unfiltered URLs")
    db_name = os.environ.get("DB_NAME", "aptekaa")
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=10000)[db_name]
    pipeline = indexable_pairs_pipeline(slugs=slugs)
    pairs = db.prices_real.aggregate(pipeline, allowDiskUse=True)
    urls = sorted(
        f"https://{HOST}/{row['_id']['city']}/preparaty/{row['_id']['slug']}"
        for row in pairs
    )
    return db, urls


def previously_indexable_urls(db, slugs=None):
    query = {"slug": {"$in": slugs}} if slugs is not None else {}
    rows = db.indexnow_state.find(query, {"_id": 0, "urls": 1})
    return {url for row in rows for url in (row.get("urls") or [])}


def save_indexable_state(db, slugs, current_urls):
    if slugs is None:
        db.indexnow_state.update_many({}, {"$set": {"urls": []}})
        slugs = sorted({url.rstrip("/").rsplit("/", 1)[-1] for url in current_urls})
    by_slug = {slug: [] for slug in slugs}
    for url in current_urls:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if slug in by_slug:
            by_slug[slug].append(url)
    now = datetime.now(timezone.utc)
    for slug, urls in by_slug.items():
        db.indexnow_state.update_one(
            {"slug": slug},
            {"$set": {"slug": slug, "urls": sorted(urls), "updated_at": now}},
            upsert=True,
        )


def submit(urls):
    payload = json.dumps({
        "host": HOST,
        "key": KEY,
        "keyLocation": KEY_LOCATION,
        "urlList": urls,
    }).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status


def main():
    if len(sys.argv) < 2:
        print("usage: indexnow_ping.py <changed_slugs_file>")
        sys.exit(1)
    full_snapshot = sys.argv[1] == "--full-snapshot"
    if full_snapshot:
        slugs = None
    else:
        path = sys.argv[1]
        try:
            with open(path) as f:
                slugs = [ln.strip() for ln in f if ln.strip()]
        except FileNotFoundError:
            print(f"no file {path} — nothing to submit")
            return
        if not slugs:
            print("0 changed slugs — nothing to submit")
            return
    # Sending every slug to every city caused Yandex to crawl thousands of
    # pages that immediately answered with noindex.  Submit only the pairs
    # that satisfy the exact same >=2-network rule as sitemap and metadata.
    db, current_urls = indexable_urls(slugs)
    previous_urls = previously_indexable_urls(db, slugs)
    # Submit both newly indexable URLs and URLs which just became noindex, so
    # Yandex learns about removals instead of keeping stale search results.
    urls = sorted(set(current_urls) | previous_urls)
    scope = "full snapshot" if full_snapshot else f"{len(slugs)} changed slugs"
    print(f"IndexNow: {scope} -> {len(current_urls)} current, "
          f"{len(previous_urls - set(current_urls))} deindexed city URLs")
    if not urls:
        print("0 indexable URLs — nothing to submit")
        return
    total = 0
    all_ok = True
    for i in range(0, len(urls), BATCH):
        chunk = urls[i:i + BATCH]
        try:
            status = submit(chunk)
            total += len(chunk)
            print(f"submitted {len(chunk)} urls -> HTTP {status}")
        except Exception as e:
            all_ok = False
            print(f"batch failed: {e}")
    if all_ok:
        save_indexable_state(db, slugs, current_urls)
    print(f"IndexNow: {total} urls submitted total")


if __name__ == "__main__":
    main()
