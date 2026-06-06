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
import urllib.request

HOST = "aptekaa.ru"
KEY = "3c6a00678b80a261eee94accd64427c7"
KEY_LOCATION = f"https://{HOST}/{KEY}.txt"
ENDPOINT = "https://api.indexnow.org/indexnow"   # шлёт сразу всем партнёрам (Bing, Yandex, Seznam)
BATCH = 10000   # лимит IndexNow на один запрос


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
    # Один и тот же slug индексируется отдельно для каждого города — у Яндекса
    # разные региональные страницы. Пинаем все обслуживаемые города. (Если в
    # каком-то городе у slug нет цены — страница noindex, Яндекс её просто
    # пропустит, вреда нет.)
    cities = ["msk", "spb", "krd", "nn", "ekb", "kzn", "nsk", "sam", "chel", "ufa", "rnd", "vrn"]
    urls = []
    for s in slugs:
        for c in cities:
            urls.append(f"https://{HOST}/{c}/preparaty/{s}")
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
