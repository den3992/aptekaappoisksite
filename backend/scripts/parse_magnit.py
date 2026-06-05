"""
Парсер цен «Магнит Аптека» (apteka.magnit.ru) → prices_real, source="magnit".

Федеральная сеть (вся РФ). Мультигород: цена И наличие задаются городом через
FIAS → shopGroupCode. Этап 1: цена + суммарный остаток по городу (quantity),
БЕЗ карты по аптекам (seed без координат, маркеров нет).

Реверс (см. память 2026-06-05):
- Город: GET /webgate/v1/shop-group/by-fias-id/<FIAS> (заголовок X-Device-Platform: web)
  → {shopGroupCode, title}. FIAS городов захардкожены ниже (проверены).
- Каталог: sitemap https://apteka.magnit.ru/sitemap-parts/products-0.xml → ~15.6k
  /product/<goodId>-<slug>. slug = транслит (name+форма+дозировка+фасовка).
- Цена+наличие: GET /webgate/v2/goods/<goodId>/stores/<shopGroupCode>?storetype=apteka&catalogtype=3
  → price (в КОПЕЙКАХ, /100), quantity (остаток по городу), name (кириллица), isMissing.
- У сайта НЕТ рабочего товарного поиска по URL → матчинг через sitemap-индекс:
  транслитерируем наше название, находим кандидатов по бренд-токенам + дозировке
  в slug, валидируем по КИРИЛЛИЧЕСКОМУ name из goods через match_products (gorzdrav).

Запуск:
  python -m scripts.parse_magnit                      # все канонические, все города
  python -m scripts.parse_magnit --city msk,ekb
  python -m scripts.parse_magnit --limit 100
  python -m scripts.parse_magnit --slug nurofen-...
  python -m scripts.parse_magnit --popular
  python -m scripts.parse_magnit --from-priced        # только слаги, у к-рых уже есть цена любой сети
  python -m scripts.parse_magnit --update-only
  python -m scripts.parse_magnit --rematch
"""
from __future__ import annotations

import os
import re
import sys
import asyncio
import argparse
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from motor.motor_asyncio import AsyncIOMotorClient

from scripts.parse_gorzdrav import (
    MONGO_URL, DB_NAME, POPULAR_MNN,
    REQUEST_DELAY,
    match_products, extract_pack,
    log,
)

SOURCE = "magnit"
BASE = "https://apteka.magnit.ru"

# Город → (название, FIAS aoguid). Проверены через shop-group API (10 шт).
# TODO: Ростов-на-Дону, Воронеж — найти верный FIAS и добавить.
MAGNIT_FIAS = {
    "msk":  ("Москва",            "0c5b2444-70a0-4932-980c-b4dc0d3f02b5"),
    "spb":  ("Санкт-Петербург",   "c2deb16a-0330-4f05-821f-1d09c93331e6"),
    "krd":  ("Краснодар",         "7dfa745e-aa19-4688-b121-b655c11e482f"),
    "nn":   ("Нижний Новгород",   "555e7d61-d9a7-4ba6-9770-6caa8198c483"),
    "ekb":  ("Екатеринбург",      "2763c110-cb8b-416a-9dac-ad28a55b4402"),
    "kzn":  ("Казань",            "93b3df57-4c89-44df-ac42-96f05e9cd3b9"),
    "nsk":  ("Новосибирск",       "8dea00e3-9aab-4d8e-887c-ef2aaa546456"),
    "sam":  ("Самара",            "bb035cc3-1dc2-4627-9d25-a1bf2d4b936b"),
    "chel": ("Челябинск",         "a376e68d-724a-4472-be7c-891bdb09ae32"),
    "ufa":  ("Уфа",               "7339e834-2cb4-4734-a4c7-1fca2c66e562"),
}
DEFAULT_CITIES = list(MAGNIT_FIAS.keys())

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Encoding": "gzip",
    "X-Device-Platform": "web",
    "X-Device-Type": "desktop",
}
SITEMAP_URL = f"{BASE}/sitemap-parts/products-0.xml"
CONCURRENCY = 14       # одновременных HTTP-запросов к webgate (общий лимит)
MED_CONCURRENCY = 8    # препаратов в обработке одновременно

CHANGED_SLUGS: set[str] = set()

# --- Транслитерация (схема Магнита) ---
_TRANS = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z',
    'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
    'щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
}
def translit(s: str) -> str:
    out = []
    for ch in (s or "").lower():
        if ch in _TRANS: out.append(_TRANS[ch])
        elif ch.isalnum(): out.append(ch)
        else: out.append(' ')
    return re.sub(r'\s+', ' ', ''.join(out)).strip()

_STOP = {"tabletki","kapsuly","rastvor","maz","krem","gel","sirop","poroshok",
         "suspenziya","svechi","sprey","kapli","dlya","pokrytye","obolochkoy",
         "plenochnoy","prigotovleniya","naruzhnogo","primeneniya","vnutrivennogo",
         "vnutrimyshechnogo","vvedeniya","flakon","ampuly","p","o","n"}
def tok(s: str) -> set:
    return {t for t in re.split(r'[ _]+', s) if len(t) >= 3 and t not in _STOP}

def norm_dose(dosage: str) -> set:
    """'400 мг' -> {'400mg'}; '100 мг/5 мл' -> {'100mg','5ml'}."""
    d = (dosage or "").lower()
    d = d.replace("мкг","mkg").replace("мг","mg").replace("мл","ml").replace("ме","me").replace("г","g").replace("%","percent")
    return set(re.findall(r'\d+(?:mkg|mg|ml|me|g|percent)', d.replace(" ", "")))


def parse_sitemap(xml: str) -> list[tuple[str, str]]:
    rows = []
    for u in re.findall(r"<loc>([^<]+)</loc>", xml):
        m = re.search(r"/product/(\d+)-(.+)$", u)
        if m:
            rows.append((m.group(1), m.group(2)))
    return rows


def build_index(rows: list[tuple[str, str]]):
    """Инвертированный индекс: бренд-токен -> [(goodId, slug, slug_tokens, slug_doses)]."""
    idx: dict[str, list] = {}
    for gid, slug in rows:
        st = tok(slug)
        sd = set(re.findall(r'\d+(?:mkg|mg|ml|me|g|percent)', slug.replace("_", "")))
        entry = (gid, slug, st, sd)
        for t in list(st)[:6]:
            idx.setdefault(t, []).append(entry)
    return idx


def find_candidates(med: dict, index) -> list[tuple[str, str]]:
    """Транслит-кандидаты: ВСЕ значимые токены имени в slug + дозировка. (goodId, slug)."""
    name_t = tok(translit(med.get("name", "")))
    if not name_t:
        return []
    doses = norm_dose(med.get("dosage", ""))
    # сколько токенов имени обязаны совпасть (для коротких имён — все)
    need = len(name_t) if len(name_t) <= 3 else max(2, int(len(name_t) * 0.7))
    seen = {}
    # ищем по самому редкому (длинному) токену имени, чтобы не сканировать всё
    anchor = max(name_t, key=len)
    for gid, slug, st, sd in index.get(anchor, []):
        if gid in seen:
            continue
        if len(name_t & st) < need:
            continue
        # дозировка: если есть у нас — требуем совпадение (slug без дозы отбрасываем)
        if doses:
            if not sd or not (doses & sd):
                continue
        seen[gid] = slug
    return list(seen.items())


async def fetch_goods(client: httpx.AsyncClient, good_id: str, sgc: str) -> dict | None:
    url = f"{BASE}/webgate/v2/goods/{good_id}/stores/{sgc}?storetype=apteka&catalogtype=3"
    for attempt in range(3):
        try:
            r = await client.get(url, timeout=25)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(1 + attempt * 2)
                continue
            log.warning(f"[magnit] goods {good_id} fail: {e}")
            return None
    return None


async def shop_group(client: httpx.AsyncClient, fias: str) -> str | None:
    try:
        r = await client.get(f"{BASE}/webgate/v1/shop-group/by-fias-id/{fias}", timeout=20)
        r.raise_for_status()
        return r.json().get("shopGroupCode")
    except Exception as e:
        log.error(f"[magnit] shop_group {fias} fail: {e}")
        return None


def good_to_listing(good_id: str, j: dict) -> dict:
    """webgate goods JSON -> листинг для match_products (name + attributes)."""
    name = j.get("name", "")
    mfr = ""
    det = j.get("details") or {}
    if isinstance(det, dict):
        mfr = det.get("manufacturer") or det.get("vendor") or ""
    attrs = [{"code": "manufacturer", "value": mfr}] if mfr else []
    return {"name": name, "extId": good_id, "attributes": attrs, "_raw": j}


def good_price_qty(j: dict):
    price = j.get("price")
    if isinstance(price, (int, float)) and price > 0:
        price = int(round(price / 100))  # копейки → рубли
    else:
        price = None
    qty = 0
    def walk(o):
        nonlocal qty
        if isinstance(o, dict):
            if isinstance(o.get("quantity"), int):
                qty = max(qty, o["quantity"])
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o[:60]: walk(v)
    walk(j)
    missing = bool(j.get("isMissing"))
    return price, qty, missing


async def _save_row(db, med_id, slug, city, pack, gid, name, status, price, qty, missing):
    _prev = await db.prices_real.find_one(
        {"medication_id": med_id, "source": SOURCE, "city": city, "gz_pack": pack},
        {"_id": 0, "price": 1})
    if _prev is None or _prev.get("price") != price:
        CHANGED_SLUGS.add(slug)
    await db.prices_real.update_one(
        {"medication_id": med_id, "source": SOURCE, "city": city, "gz_pack": pack},
        {"$set": {
            "medication_id": med_id, "slug": slug, "source": SOURCE, "city": city,
            "gz_pack": pack, "match_status": status, "gz_ext_id": gid, "gz_name": name,
            "gz_url_key": f"/product/{gid}", "price": price, "stores_count": qty,
            "is_missing": missing, "updated_at": datetime.now(timezone.utc),
        }}, upsert=True)


async def process_med(client, db, med, index, sgcs, match_city, sem) -> None:
    """Матчинг ОДИН раз (по match_city), затем цена по каждому городу."""
    med_id = med["_id"]
    slug = med.get("slug", str(med_id))
    cities = list(sgcs.keys())

    cands = find_candidates(med, index)
    if not cands:
        for c in cities:
            await db.prices_real.update_one(
                {"medication_id": med_id, "source": SOURCE, "city": c},
                {"$set": {"medication_id": med_id, "slug": slug, "source": SOURCE,
                          "city": c, "match_status": "not_found",
                          "updated_at": datetime.now(timezone.utc)}}, upsert=True)
        return

    # тянем goods кандидатов ПО match_city → кириллич. имя + цена match_city
    raws = {}
    async def pull(gid):
        async with sem:
            j = await fetch_goods(client, gid, sgcs[match_city])
            await asyncio.sleep(REQUEST_DELAY)
            if j:
                raws[gid] = j
    await asyncio.gather(*(pull(gid) for gid, _ in cands))
    listings = [good_to_listing(gid, raws[gid]) for gid, _ in cands if gid in raws]
    if not listings:
        return
    matches = match_products(med, listings, allow_combo=False)
    if not matches:
        for c in cities:
            await db.prices_real.update_one(
                {"medication_id": med_id, "source": SOURCE, "city": c},
                {"$set": {"medication_id": med_id, "slug": slug, "source": SOURCE,
                          "city": c, "match_status": "no_match",
                          "gz_top_candidate": listings[0].get("name", "")[:80],
                          "updated_at": datetime.now(timezone.utc)}}, upsert=True)
        return

    # confirmed: по одному goodId на упаковку
    confirmed = []  # (gid, pack, name, status)
    seen_packs = set()
    for item, status in matches:
        gid = item.get("extId", "")
        name = item.get("name", "")
        pack = extract_pack(name)
        if not pack or pack in seen_packs:
            continue
        seen_packs.add(pack)
        confirmed.append((gid, pack, name, status))

    # цена по каждому городу (match_city переиспользует raws)
    for city in cities:
        sgc = sgcs[city]
        saved_packs = set()
        for gid, pack, name, status in confirmed:
            if city == match_city:
                j = raws.get(gid)
            else:
                async with sem:
                    j = await fetch_goods(client, gid, sgc)
                    await asyncio.sleep(REQUEST_DELAY)
            if not j:
                continue
            price, qty, missing = good_price_qty(j)
            if price is None:
                continue
            await _save_row(db, med_id, slug, city, pack, gid, name, status, price, qty, missing)
            saved_packs.add(pack)
        if saved_packs:
            await db.prices_real.delete_many({
                "medication_id": med_id, "source": SOURCE, "city": city,
                "gz_pack": {"$nin": list(saved_packs), "$ne": None}})


async def build_med_query(db, args):
    query = {"is_canonical": True}
    if args.slug:
        query["slug"] = args.slug
    if args.popular:
        query["mnn"] = {"$in": list(POPULAR_MNN)}
    if args.from_priced:
        priced = await db.prices_real.distinct("slug",
            {"match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
             "price": {"$ne": None}})
        query["slug"] = {"$in": priced}
        log.info(f"[magnit] --from-priced: {len(priced)} слагов")
    if args.update_only:
        ms = await db.prices_real.distinct("slug",
            {"source": SOURCE,
             "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
             "price": {"$ne": None}})
        query["slug"] = {"$in": ms}
    return query


async def main(args):
    cities = [c.strip() for c in args.city.split(",") if c.strip()]
    bad = [c for c in cities if c not in MAGNIT_FIAS]
    if bad:
        log.error(f"[magnit] неизвестные города: {bad} (есть: {list(MAGNIT_FIAS)})")
        return
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        log.info("[magnit] загрузка sitemap...")
        r = await client.get(SITEMAP_URL, timeout=60)
        rows = parse_sitemap(r.text)
        log.info(f"[magnit] товаров в sitemap: {len(rows)}")
        index = build_index(rows)
        log.info(f"[magnit] индекс: {len(index)} токенов")

        # shopGroupCode по каждому городу
        sgcs = {}
        for city in cities:
            sgc = await shop_group(client, MAGNIT_FIAS[city][1])
            if sgc:
                sgcs[city] = sgc
            else:
                log.error(f"[magnit] {city}: нет shopGroupCode, пропуск города")
        if not sgcs:
            log.error("[magnit] ни одного города — выход")
            return
        match_city = "msk" if "msk" in sgcs else next(iter(sgcs))
        log.info(f"[magnit] города: {list(sgcs)}; матчинг по {match_city}")

        query = await build_med_query(db, args)
        cur = db.medications.find(query, {"name":1,"dosage":1,"form":1,"manufacturer":1,"slug":1,"mnn":1})
        if args.limit:
            cur = cur.limit(args.limit)
        meds = await cur.to_list(length=None)
        log.info(f"[magnit] препаратов: {len(meds)}")

        sem = asyncio.Semaphore(CONCURRENCY)         # лимит HTTP к webgate
        med_sem = asyncio.Semaphore(MED_CONCURRENCY)  # параллелизм по препаратам
        done = [0]
        total = len(meds)
        async def worker(med):
            async with med_sem:
                try:
                    await process_med(client, db, med, index, sgcs, match_city, sem)
                except Exception as e:
                    log.warning(f"[magnit] med {med.get('slug')} err: {e}")
            done[0] += 1
            if done[0] % 200 == 0:
                log.info(f"[magnit] прогресс {done[0]}/{total}")
        await asyncio.gather(*(worker(m) for m in meds))

    stats = {}
    async for doc in db.prices_real.aggregate([
        {"$match": {"source": SOURCE}},
        {"$group": {"_id": {"c":"$city","s":"$match_status"}, "n": {"$sum":1}}}]):
        stats[f"{doc['_id'].get('c')}/{doc['_id'].get('s')}"] = doc["n"]
    log.info(f"[magnit] Готово. {stats}")

    out = os.environ.get("INDEXNOW_CHANGED_FILE_MAGNIT", "/tmp/indexnow_changed_magnit.txt")
    try:
        with open(out, "w") as f:
            for s in sorted(CHANGED_SLUGS): f.write(s+"\n")
        log.info(f"[magnit] IndexNow: {len(CHANGED_SLUGS)} slug -> {out}")
    except Exception as e:
        log.warning(f"[magnit] IndexNow write fail: {e}")
    client_db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--city", type=str, default=",".join(DEFAULT_CITIES))
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--slug", type=str, default="")
    p.add_argument("--popular", action="store_true")
    p.add_argument("--from-priced", action="store_true")
    p.add_argument("--update-only", action="store_true")
    p.add_argument("--rematch", action="store_true")
    asyncio.run(main(p.parse_args()))
