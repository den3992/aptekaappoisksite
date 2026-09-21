"""Collect source-linked Moscow price observations for the priority catalogue.

The collector is deliberately conservative: it searches trusted Russian
pharmacy/aggregator pages, verifies the exact trade name and dosage, and saves
the result as a historical observation.  It never marks an item as currently
available; availability is maintained by the dedicated pharmacy parsers.

Run without ``--apply`` for a preview.  Network search is rate-limited.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlparse

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from scripts.parse_gorzdrav import curated_identity_verified, extract_pack

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "priority_medications_2026-09"
SEARCH_URL = "https://search.brave.com/search?q="
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}
TRUSTED_DOMAINS = {
    "009.xn--p1ai": "009",
    "uteka.ru": "uteka",
    "www.eapteka.ru": "eapteka",
    "eapteka.ru": "eapteka",
    "zdravcity.ru": "zdravcity",
    "www.zdravcity.ru": "zdravcity",
    "asna.ru": "asna",
    "www.asna.ru": "asna",
    "aptekamos.ru": "aptekamos",
    "www.aptekamos.ru": "aptekamos",
}

_TRANSLIT = str.maketrans({
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z",
    "и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r",
    "с":"s","т":"t","у":"u","ф":"f","х":"kh","ц":"ts","ч":"ch","ш":"sh",
    "щ":"shch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
})


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", text)


def numbers(value: object) -> list[str]:
    return [part.replace(",", ".").lstrip("0") or "0" for part in re.findall(r"\d+(?:[.,]\d+)?", str(value or ""))]


def pack_count(value: object) -> Optional[str]:
    match = re.match(r"^\s*(\d+(?:[.,]\d+)?)", str(value or ""))
    return (match.group(1).replace(",", ".").lstrip("0") or "0") if match else None


def strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def search_results(text: str) -> list[dict]:
    starts = list(re.finditer(r'<div class="snippet [^"]*"[^>]*data-pos="\d+"', text))
    rows = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        chunk = text[match.start():end]
        link = re.search(r'<a href="(https?://[^"]+)"[^>]*class="[^"]*\bl1\b', chunk)
        title = re.search(r'<div class="title [^"]*" title="([^"]+)"', chunk)
        if not link or not title:
            continue
        rows.append({
            "url": html.unescape(link.group(1)),
            "title": html.unescape(title.group(1)),
            "text": strip_tags(chunk),
        })
    return rows


def iter_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json(child)


def json_ld_product(page: str) -> Optional[dict]:
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page,
        flags=re.I | re.S,
    )
    for raw in scripts:
        try:
            payload = json.loads(html.unescape(raw.strip()))
        except (json.JSONDecodeError, ValueError):
            continue
        for node in iter_json(payload):
            kind = node.get("@type")
            if kind == "Product" or (isinstance(kind, list) and "Product" in kind):
                offers = node.get("offers") or {}
                offer_nodes = offers if isinstance(offers, list) else [offers]
                prices = []
                for offer in offer_nodes:
                    if not isinstance(offer, dict):
                        continue
                    raw_price = offer.get("lowPrice", offer.get("price"))
                    try:
                        price = float(str(raw_price).replace(" ", "").replace(",", "."))
                    except (TypeError, ValueError):
                        continue
                    if price > 0:
                        prices.append(price)
                if prices:
                    brand = node.get("manufacturer") or node.get("brand") or ""
                    if isinstance(brand, list):
                        brand = brand[0] if brand else ""
                    if isinstance(brand, dict):
                        brand = brand.get("name") or ""
                    return {"title": node.get("name") or "", "producer": brand, "price": min(prices)}
    return None


def translit_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold().translate(_TRANSLIT))


def load_009_product_urls(session: requests.Session) -> list[str]:
    urls = []
    for index in range(4):
        response = session.get(f"https://009.xn--p1ai/sitemap_{index}.xml", timeout=60)
        response.raise_for_status()
        urls.extend(re.findall(r"<loc>(https://009\.xn--p1ai/product/[^<]+)</loc>", response.text))
    return urls


def candidates_009(med: dict, urls: list[str]) -> list[str]:
    key = translit_key(med.get("name"))
    aliases = {key, key.replace("ts", "c"), key.replace("kh", "h")}
    matches = []
    for url in urls:
        path_key = translit_key(urlparse(url).path.rsplit("/", 1)[-1])
        if any(alias and alias in path_key for alias in aliases):
            matches.append((len(path_key), url))
    return [url for _, url in sorted(matches)[:20]]


def decode_nuxt(page: str) -> list[dict]:
    match = re.search(r'id="__NUXT_DATA__">(.*?)</script>', page, flags=re.S)
    if not match:
        return []
    try:
        flat = json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return []
    cache = {}

    def decode(value, depth=0):
        if depth > 50:
            return None
        if isinstance(value, bool) or value is None or isinstance(value, (str, float)):
            return value
        if isinstance(value, int):
            if value < 0 or value >= len(flat):
                return value
            if value in cache:
                return cache[value]
            raw = flat[value]
            if isinstance(raw, dict):
                out = {}
                cache[value] = out
                out.update({key: decode(child, depth + 1) for key, child in raw.items()})
                return out
            if isinstance(raw, list):
                if len(raw) == 2 and raw[0] in {"ShallowReactive", "Reactive", "Ref"}:
                    return decode(raw[1], depth + 1)
                out = []
                cache[value] = out
                out.extend(decode(child, depth + 1) for child in raw)
                return out
            return raw
        if isinstance(value, list):
            return [decode(child, depth + 1) for child in value]
        if isinstance(value, dict):
            return {key: decode(child, depth + 1) for key, child in value.items()}
        return value

    products = []
    seen = set()
    for index, raw in enumerate(flat):
        if not isinstance(raw, dict) or "productId" not in raw or "fullTitle" not in raw:
            continue
        product = decode(index)
        product_id = product.get("productId")
        if product_id in seen:
            continue
        seen.add(product_id)
        products.append(product)
    return products


def page_observation(url: str, page: str) -> Optional[dict]:
    if urlparse(url).netloc.removeprefix("www.") == "uteka.ru":
        product_id = re.search(r"-(\d+)/?(?:\?.*)?$", url)
        products = decode_nuxt(page)
        if product_id:
            products.sort(key=lambda item: str(item.get("productId")) != product_id.group(1))
        for product in products:
            price = product.get("minPrice") or product.get("lastPrice")
            if isinstance(price, (int, float)) and price > 0:
                return {
                    "title": product.get("fullTitle") or product.get("title") or "",
                    "producer": product.get("producer") or "",
                    "price": float(price),
                    "source_date": product.get("lastDate"),
                }
    return json_ld_product(page)


def exact_match(med: dict, observation: dict, pack: str) -> bool:
    title = str(observation.get("title") or "")
    actual_pack = extract_pack(title)
    if not actual_pack:
        return False
    candidate = dict(med)
    candidate["curated_source"] = SOURCE
    item = {
        "name": title,
        "attributes": [{"code": "manufacturer", "value": observation.get("producer") or ""}],
    }
    return curated_identity_verified(candidate, item, actual_pack, "matched")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--slug", default="")
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--medications-json", default="",
                        help="Read medication documents from this JSON file, or '-' for stdin.")
    parser.add_argument("--output-json", default="",
                        help="Write verified observations to a JSON file.")
    parser.add_argument("--import-json", default="",
                        help="Import previously verified observations instead of searching.")
    parser.add_argument("--source-009", action="store_true",
                        help="Discover exact product pages from the 009.rf sitemap instead of web search.")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    db = None
    if args.apply or not args.medications_json:
        db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

    if args.import_json:
        if not args.apply or db is None:
            raise SystemExit("--import-json requires --apply and database environment variables")
        documents = json.loads(open(args.import_json, encoding="utf-8").read())
        imported = 0
        for document in documents:
            med = db.medications.find_one(
                {"slug": document.get("slug"), "curated_source": SOURCE},
                {"_id": 0, "slug": 1, "name": 1, "dosage": 1, "form": 1,
                 "manufacturer": 1, "mnn": 1, "variants": 1, "curated_source": 1},
            )
            observation = {
                "title": document.get("gz_name"),
                "producer": document.get("source_manufacturer"),
            }
            if not med or not exact_match(med, observation, document.get("gz_pack") or ""):
                print(f"REJECT {document.get('slug')}: identity could not be reverified")
                continue
            if isinstance(document.get("updated_at"), str):
                document["updated_at"] = datetime.fromisoformat(document["updated_at"].replace("Z", "+00:00"))
            db.prices_real.update_one(
                {"slug": document["slug"], "source": document["source"], "city": "msk",
                 "external_price_observation": True},
                {"$set": document},
                upsert=True,
            )
            imported += 1
        print(f"IMPORTED {imported}/{len(documents)} observations")
        return

    if args.medications_json:
        raw = sys.stdin.read() if args.medications_json == "-" else open(args.medications_json, encoding="utf-8").read()
        meds = json.loads(raw)
        if args.slug:
            meds = [med for med in meds if med.get("slug") == args.slug]
        if args.limit:
            meds = meds[:args.limit]
    else:
        query = {"curated_source": SOURCE}
        if args.slug:
            query["slug"] = args.slug
        cursor = db.medications.find(query, {"_id": 0, "slug": 1, "name": 1, "dosage": 1,
                                             "form": 1, "manufacturer": 1, "mnn": 1,
                                             "variants": 1, "curated_source": 1}).sort("slug", 1)
        meds = list(cursor.limit(args.limit) if args.limit else cursor)
    session = requests.Session()
    session.headers.update(HEADERS)
    product_urls_009 = load_009_product_urls(session) if args.source_009 else []
    found = 0
    now = datetime.now(timezone.utc)
    documents = []

    for med in meds:
        pack = ((med.get("variants") or [{}])[0]).get("pack_size") or ""
        query_text = " ".join(filter(None, [med.get("name"), med.get("dosage"), pack,
                                             med.get("manufacturer"), "цена Москва купить"] ))
        if args.source_009:
            result_rows = [{"url": url, "title": "", "text": ""}
                           for url in candidates_009(med, product_urls_009)]
        else:
            response = None
            last_error = None
            for attempt in range(3):
                try:
                    response = session.get(SEARCH_URL + quote(query_text), timeout=30)
                    response.raise_for_status()
                    break
                except requests.RequestException as exc:
                    last_error = exc
                    response = None
                    if attempt < 2:
                        time.sleep(15 * (attempt + 1))
            if response is None:
                print(f"ERROR {med['slug']}: search failed: {last_error}")
                continue
            result_rows = search_results(response.text)

        selected = None
        for result in result_rows:
            host = urlparse(result["url"]).netloc.casefold()
            source = TRUSTED_DOMAINS.get(host)
            if not source or (not args.source_009 and norm(med.get("name")) not in norm(result.get("title"))):
                continue
            try:
                page_response = session.get(result["url"], timeout=30)
                page_response.raise_for_status()
                observation = page_observation(result["url"], page_response.text)
            except requests.RequestException:
                continue
            if observation and exact_match(med, observation, pack):
                selected = {**observation, "url": result["url"], "source": source}
                break

        if not selected:
            print(f"MISS  {med['slug']}")
            time.sleep(args.delay)
            continue

        observed_at = now
        if selected.get("source_date"):
            try:
                observed_at = datetime.fromisoformat(str(selected["source_date"]).replace("Z", "+00:00"))
            except ValueError:
                pass
        document = {
            "slug": med["slug"],
            "source": selected["source"],
            "city": "msk",
            "price": selected["price"],
            "stores_count": 0,
            "match_status": "matched",
            "gz_name": selected["title"],
            "gz_pack": extract_pack(selected["title"]),
            "source_manufacturer": selected.get("producer") or "",
            "source_url": selected["url"],
            "updated_at": observed_at,
            "external_price_observation": True,
            "identity_verified": True,
        }
        documents.append(document)
        print(f"FOUND {med['slug']}: {selected['price']:.0f} ₽ | {selected['source']} | {selected['url']}")
        if args.apply and db is not None:
            db.prices_real.update_one(
                {"slug": med["slug"], "source": selected["source"], "city": "msk",
                 "external_price_observation": True},
                {"$set": document},
                upsert=True,
            )
        found += 1
        time.sleep(args.delay)

    print(f"RESULT found={found}/{len(meds)} applied={args.apply}")
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as handle:
            json.dump(documents, handle, ensure_ascii=False, indent=2, default=str)
        print(f"OUTPUT {args.output_json}: {len(documents)} observations")


if __name__ == "__main__":
    main()
