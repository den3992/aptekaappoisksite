#!/usr/bin/env python3
"""
IndexNow ping — уведомляет Яндекс/Bing об изменившихся страницах.
Читает список slug-ов из файла (по одному на строку), строит URL
страниц препаратов и батчами шлёт на IndexNow endpoint.

Usage:
    python3 indexnow_ping.py <changed_slugs_file>
"""
import sys
import json
import os
import urllib.request
from pymongo import MongoClient

HOST = "aptekaa.ru"
KEY = "3c6a00678b80a261eee94accd64427c7"
KEY_LOCATION = f"https://{HOST}/{KEY}.txt"
ENDPOINT = "https://api.indexnow.org/indexnow"   # шлёт сразу всем партнёрам (Bing, Yandex, Seznam)
BATCH = 10000   # лимит IndexNow на один запрос
CITIES = ["msk", "spb", "krd", "nn", "ekb", "kzn", "nsk", "sam", "chel", "ufa", "rnd", "vrn"]
SOURCES = ["gorzdrav", "apteka366", "rigla", "maksavit", "aptechestvo", "zdorovie", "magnit", "farmakopeika"]
MATCH_OK = ["matched", "mnn_match", "needs_review"]


def indexable_urls(slugs):
    """Return only city/slug pairs that the live page marks indexable."""
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        raise RuntimeError("MONGO_URL is required; refusing to submit unfiltered URLs")
    db_name = os.environ.get("DB_NAME", "aptekaa")
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=10000)[db_name]
    pipeline = [
        {"$match": {
            "slug": {"$in": slugs},
            "city": {"$in": CITIES},
            "source": {"$in": SOURCES},
            "price": {"$gt": 0},
            "match_status": {"$in": MATCH_OK},
        }},
        {"$group": {"_id": {"city": "$city", "slug": "$slug"}, "nets": {"$addToSet": "$source"}}},
        {"$match": {"$expr": {"$gte": [{"$size": "$nets"}, 2]}}},
    ]
    pairs = db.prices_real.aggregate(pipeline, allowDiskUse=True)
    return sorted(
        f"https://{HOST}/{row['_id']['city']}/preparaty/{row['_id']['slug']}"
        for row in pairs
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
    urls = indexable_urls(slugs)
    print(f"IndexNow: {len(slugs)} changed slugs -> {len(urls)} indexable city URLs")
    if not urls:
        print("0 indexable URLs — nothing to submit")
        return
    total = 0
    for i in range(0, len(urls), BATCH):
        chunk = urls[i:i + BATCH]
        try:
            status = submit(chunk)
            total += len(chunk)
            print(f"submitted {len(chunk)} urls -> HTTP {status}")
        except Exception as e:
            print(f"batch failed: {e}")
    print(f"IndexNow: {total} urls submitted total")


if __name__ == "__main__":
    main()
