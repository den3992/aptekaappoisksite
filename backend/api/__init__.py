"""
Catalog API: cities, categories, search, medication detail, pharmacies.

Mounted into the main FastAPI app via include_router from server.py.
All routes under /api/*.
"""
from __future__ import annotations

import re
import math
import base64
import time
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import Response, APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorDatabase

from .pharmacies_seed import (
    CITIES,
    PHARMACIES,
    CATEGORIES,
    pharmacies_by_city,
    find_pharmacy_by_id,
    find_pharmacy,
)
from .price_indexing import REAL_SOURCES, MATCH_OK, availability_cutoff, indexable_pairs_pipeline


# ---------- Helpers for analogs filtering ----------
# Map raw `form` strings from ЕСКЛП to a small set of comparable groups,
# so that on a "tablets" SKU we only show analogs that are also tablets.
_FORM_GROUP_PATTERNS = [
    ('ophthalmic',  re.compile(r'(КАПЛИ|МАЗЬ|ГЕЛЬ|РАСТВОР).*ГЛАЗ', re.I)),
    ('nasal',       re.compile(r'(КАПЛИ|СПРЕЙ|МАЗЬ|АЭРОЗОЛЬ|РАСТВОР).*НАЗАЛ', re.I)),
    ('otic',        re.compile(r'(КАПЛИ|МАЗЬ).*УШ', re.I)),
    ('inhalation',  re.compile(r'ИНГАЛЯЦ|АЭРОЗОЛЬ.*ИНГ', re.I)),
    ('suppository', re.compile(r'СУППОЗИТОР|СВЕЧИ', re.I)),
    ('injection',   re.compile(r'ИНЪЕКЦ|ИНФУЗ|ЛИОФИЛИЗАТ', re.I)),
    ('oral_liquid', re.compile(r'СИРОП|СУСПЕНЗИ.*ВНУТР|РАСТВОР.*ВНУТР|РАСТВОР.*ПРИЕМА|РАСТВОР.*ПРИЁМА|КАПЛИ.*ВНУТР|КАПЛИ.*ПРИЕМА|КАПЛИ.*ПРИЁМА|НАСТОЙК|ЭКСТРАКТ.*ВНУТР|ЭЛИКСИР', re.I)),
    ('topical',     re.compile(r'МАЗЬ|ГЕЛЬ|КРЕМ|ЛИНИМЕНТ|ЛОСЬОН|ШАМПУН|АЭРОЗОЛЬ|СПРЕЙ|ПАСТА|ПЛАСТЫР|ЭМУЛЬС', re.I)),
    ('oral_solid',  re.compile(r'ТАБЛЕТК|КАПСУЛ|ДРАЖЕ|ПАСТИЛК|ГРАНУЛ|ПОРОШОК.*ВНУТР|ПОРОШОК.*ПРИЕМА|ПОРОШОК.*ПРИЁМА|ЛЕПЕШК|САШЕ|КАРАМЕЛЬ', re.I)),
]


def form_group(form_value):
    """Return a canonical form group for an ЕСКЛП `form` string.

    Order of patterns matters — site-specific routes (eye/nose/ear/inhaler)
    are matched first, so e.g. "КАПЛИ ГЛАЗНЫЕ" is ophthalmic, not oral_liquid.
    """
    if not form_value:
        return 'other'
    s = form_value.strip()
    for grp, rx in _FORM_GROUP_PATTERNS:
        if rx.search(s):
            return grp
    return 'other'


def _parse_dose_first(dosage):
    """Pick the first numeric token from a dosage string (e.g. "500 мг + 30 мг" → 500.0).

    Returns float or None.
    """
    if not dosage:
        return None
    m = re.search(r'(\d+(?:[.,]\d+)?)', str(dosage))
    if not m:
        return None
    try:
        return float(m.group(1).replace(',', '.'))
    except ValueError:
        return None
_SEARCH_FORM_PRIORITY = [
    (0, re.compile(r'ТАБЛЕТК', re.I)),
    (1, re.compile(r'КАПСУЛ', re.I)),
    (2, re.compile(r'РАСТВОР', re.I)),
]

def _search_form_priority(form: str) -> int:
    if not form:
        return 99
    for priority, rx in _SEARCH_FORM_PRIORITY:
        if rx.search(form):
            return priority
    return 2

# ------------------------------------------------------


def make_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter()

    # One definition of an indexable city/medicine pair.  The same rule is
    # used by sitemap, metadata and IndexNow: a real positive price from at
    # least two independent pharmacy networks in that city.
    _real_sources = REAL_SOURCES
    _match_statuses = MATCH_OK
    _city_slug_cache = {}
    _city_slug_cache_ttl = 300

    async def _indexable_slugs(city: str) -> list[str]:
        now = time.monotonic()
        cached = _city_slug_cache.get(city)
        if cached and now - cached[0] < _city_slug_cache_ttl:
            return cached[1]
        pipeline = indexable_pairs_pipeline(city=city) + [
            {"$project": {"_id": 0, "slug": "$_id.slug"}},
        ]
        slugs = [row["slug"] async for row in db.prices_real.aggregate(pipeline) if row.get("slug")]
        _city_slug_cache[city] = (now, slugs)
        return slugs

    # ----- Cities & categories -----

    @router.get("/cities")
    async def list_cities():
        return CITIES

    @router.get("/categories")
    async def list_categories(city: Optional[str] = Query(None)):
        # attach counts from medications collection (canonical-only for accurate UX numbers)
        match = {"is_canonical": {"$ne": False}}
        if city:
            match["slug"] = {"$in": await _indexable_slugs(city)}
        agg = db.medications.aggregate([
            {"$match": match},
            {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        ])
        counts = {row["_id"]: row["count"] async for row in agg}
        out = []
        for c in CATEGORIES:
            out.append({**c, "count": counts.get(c["slug"], 0)})
        return out

    # ----- Pharmacies -----

    @router.get("/pharmacies")
    async def list_pharmacies(city: str = Query("msk")):
        return pharmacies_by_city(city)

    @router.get("/pharmacies/{pid}")
    async def pharmacy_detail(pid: str, city: str = Query("msk")):
        ph = find_pharmacy(pid, city)
        if not ph:
            raise HTTPException(404, "Pharmacy not found")
        return ph

    @router.get("/gorzdrav/stores")
    async def gorzdrav_stores(city: str = Query("msk"), response: Response = None):
        """Лёгкий список Горздрав-аптек для отображения маркеров на карте.
        Возвращает только координаты + минимум данных для маркера.
        Полная инфо (адрес, телефон, часы) — через /gorzdrav/stores/{store_id}."""
        cursor = db.gorzdrav_stores.find(
            {"city": city, "active": {"$ne": False},
             "lat": {"$ne": None}, "lng": {"$ne": None}},
            {"_id": 0, "store_id": 1, "idx": 1, "lat": 1, "lng": 1, "name": 1,
             "source": 1},
        )
        items = []
        async for doc in cursor:
            # Аптеки 36,6 физически входят в сеть пунктов выдачи Горздрава, но
            # это отдельный бренд со своей ценой. Ригла — отдельная сеть со
            # своим реестром (source='rigla'). Помечаем brand, чтобы фронт
            # красил маркеры ценой/наличием соответствующей сети.
            _src = doc.pop("source", None)
            _name = doc.pop("name", None)
            if _src == "rigla":
                doc["brand"] = "rigla"
            elif _src == "maksavit":
                doc["brand"] = "maksavit"
            elif _src == "magnit":
                doc["brand"] = "magnit"
            elif _src == "zdorovie":
                doc["brand"] = "zdorovie"
            elif _name == "36,6":
                doc["brand"] = "apteka366"
            else:
                doc["brand"] = "gorzdrav"
            items.append(doc)
        if response is not None:
            # Список меняется редко (раз в сутки при cron-парсинге),
            # поэтому кэшируем у клиента и на CDN на 10 минут.
            response.headers["Cache-Control"] = "public, max-age=600, s-maxage=600"
        return items

    @router.get("/gorzdrav/stores/bulk")
    async def gorzdrav_stores_bulk(ids: str, response: Response = None):
        """Bulk-выдача полных деталей для списка store_id, через запятую.
        Используется для динамического списка "аптеки в видимой области карты" —
        фронт считает 15 ближайших к центру карты, потом одним запросом
        получает их полные данные."""
        store_ids = [s.strip() for s in (ids or "").split(",") if s.strip()][:50]
        if not store_ids:
            return []
        cursor = db.gorzdrav_stores.find(
            {"store_id": {"$in": store_ids}},
            {"_id": 0, "store_id": 1, "full_name": 1, "address": 1,
             "phone": 1, "hours": 1, "is_24h": 1, "lat": 1, "lng": 1},
        )
        items = [doc async for doc in cursor]
        if response is not None:
            response.headers["Cache-Control"] = "public, max-age=600"
        return items

    @router.get("/gorzdrav/stores/{store_id}")
    async def gorzdrav_store_detail(store_id: str, response: Response = None):
        """Полная инфо по одной Горздрав-аптеке. Запрашивается по клику на маркер."""
        doc = await db.gorzdrav_stores.find_one(
            {"store_id": store_id},
            {"_id": 0, "store_id": 1, "full_name": 1, "address": 1,
             "phone": 1, "hours": 1, "is_24h": 1, "lat": 1, "lng": 1},
        )
        if not doc:
            raise HTTPException(404, "Store not found")
        if response is not None:
            response.headers["Cache-Control"] = "public, max-age=600"
        return doc

    # ----- Search -----

    class MedListItem(BaseModel):
        slug: str
        name: str
        mnn: Optional[str] = None
        form: Optional[str] = None
        dosage: Optional[str] = None
        manufacturer: Optional[str] = None
        manufacturer_country: Optional[str] = None
        category: str = "other"
        rx: bool = False
        vital: bool = False
        limit_price: Optional[float] = None
        # variants summary
        variants_count: int = 0

    class SearchResponse(BaseModel):
        query: Optional[str] = None
        total: int
        page: int
        page_size: int
        items: List[MedListItem]

    @router.get("/search", response_model=SearchResponse)
    async def search_meds(
        q: Optional[str] = Query(None, description="Поисковый запрос"),
        category: Optional[str] = Query(None),
        city: Optional[str] = Query(None, description="Только индексируемые препараты этого города"),
        rx: Optional[bool] = Query(None),
        prefix: Optional[str] = Query(None, description="Первая буква названия (А–Я / A–Z)"),
        page: int = Query(1, ge=1),
        page_size: int = Query(24, ge=1, le=100),
    ):
        # Hide non-canonical duplicates in listings. Direct URL access still works.
        flt = {"is_canonical": {"$ne": False}}
        if city:
            flt["slug"] = {"$in": await _indexable_slugs(city)}
        sort = None
        if q and q.strip():
            term = q.strip()
            # Use text index for non-trivial queries
            if len(term) >= 2:
                flt["$text"] = {"$search": term}
                # Tiebreak ordering on slug so skip/limit pagination is stable
                # across pages even when many docs share the same textScore.
                sort = [("score", {"$meta": "textScore"}), ("slug", 1)]
        if category:
            flt["category"] = category
        if rx is not None:
            flt["rx"] = rx
        if prefix and prefix.strip():
            ch = prefix.strip()[:1]
            flt["name"] = {"$regex": f"^{re.escape(ch)}", "$options": "i"}

        projection = {
            "_id": 0,
            "slug": 1, "name": 1, "mnn": 1, "form": 1, "dosage": 1,
            "manufacturer": 1, "manufacturer_country": 1, "category": 1,
            "rx": 1, "vital": 1, "limit_price": 1, "variants": 1,
        }
        if sort:
            projection["score"] = {"$meta": "textScore"}

        cursor = db.medications.find(flt, projection)
        if sort:
            cursor = cursor.sort(sort)
        else:
            cursor = cursor.sort([("name", 1)])

        total = await db.medications.count_documents(flt)
        cursor = cursor.skip((page - 1) * page_size).limit(page_size)

        items = []
        async for doc in cursor:
            doc.pop("score", None)
            doc["variants_count"] = len(doc.pop("variants", []) or [])
            items.append(doc)
        items.sort(key=lambda d: (
            _search_form_priority(d.get("form", "")),
            _parse_dose_first(d.get("dosage")) or float("inf"),
        ))
        return SearchResponse(
            query=q, total=total, page=page, page_size=page_size, items=items
        )

    # Lightweight typeahead for search box / chatbot
    @router.get("/search/suggest")
    async def search_suggest(q: str = Query(...), limit: int = Query(8, ge=1, le=100)):
        term = q.strip()
        if len(term) < 2:
            return []
        # Prefix-style search: case‑insensitive on first chars
        pattern = re.escape(term)
        cursor = db.medications.find(
            {"$and": [
                {"is_canonical": {"$ne": False}},
                {"$or": [
                    {"name": {"$regex": f"^{pattern}", "$options": "i"}},
                    {"mnn": {"$regex": f"^{pattern.upper()}", "$options": "i"}},
                ]},
            ]},
            {"_id": 0, "slug": 1, "name": 1, "mnn": 1, "dosage": 1, "form": 1},
        ).limit(min(limit * 5, 300))
        docs = [doc async for doc in cursor]
        docs.sort(key=lambda d: (
            _search_form_priority(d.get("form", "")),
            _parse_dose_first(d.get("dosage")) or float("inf"),
        ))
        return docs[:limit]

    # ----- Medication detail -----

    @router.get("/medications/{slug}")
    async def medication_detail(slug: str, city: str = Query(None)):
        med = await db.medications.find_one({"slug": slug}, {"_id": 0})
        if not med:
            raise HTTPException(404, "Medication not found")

        # Manual "out of stock everywhere" override (debug / testing).
        # Set medications.force_empty_stock=true on a SKU to make it look
        # as if no pharmacy in our network currently carries it.
        if med.get("force_empty_stock"):
            med["prices_by_city"] = {"msk": [], "spb": []}
            med["prices_source"] = "real"
            return med

        real_prices = {"msk": [], "spb": []}
        is_curated_priority = med.get("curated_source") == "priority_medications_2026-09"
        current_cutoff = availability_cutoff()
        cursor = db.prices.find(
            {"slug": slug},
            {"_id": 0, "pharmacy_id": 1, "price": 1, "qty": 1, "expiry_date": 1,
             "uploaded_at": 1, "pack_size": 1},
        )
        async for p in cursor:
            ph = find_pharmacy_by_id(p["pharmacy_id"])
            if not ph:
                continue
            if not (isinstance(p.get("price"), (int, float)) and p["price"] > 0):
                continue  # цена 0/None = нет реальной цены → не показываем и не индексируем
            uploaded_at = p.get("uploaded_at")
            uploaded_compare = (
                uploaded_at.replace(tzinfo=timezone.utc)
                if hasattr(uploaded_at, "tzinfo") and uploaded_at.tzinfo is None
                else uploaded_at
            )
            real_prices.setdefault(ph["city"], []).append({
                "pharmacy_id": p["pharmacy_id"],
                "price": p["price"],
                "qty": p.get("qty", 0),
                "expiry_date": p.get("expiry_date"),
                "pack_size": p.get("pack_size"),
                "observed_at": uploaded_at.isoformat() if hasattr(uploaded_at, "isoformat") else uploaded_at,
                "availability_confirmed": bool(
                    (p.get("qty") or 0) > 0 and uploaded_compare and uploaded_compare >= current_cutoff
                ),
            })

        # Добавляем цены аптечных сетей (Горздрав + Аптека 36,6) по ВСЕМ
        # упаковкам — фронт показывает их как сравнение цен по сетям. find
        # (а не find_one) — чтобы при переключении упаковки показать данные
        # именно для активной фасовки. pharmacy_id = имя источника.
        for _src in (
            "gorzdrav", "apteka366", "rigla", "maksavit", "aptechestvo",
            "zdorovie", "magnit", "farmakopeika", "rigla_archive",
        ):
            net_cursor = db.prices_real.find(
                {
                    "slug": slug,
                    "source": _src,
                    "match_status": {"$in": ["matched"] if is_curated_priority else _match_statuses},
                    "price": {"$gt": 0},
                    **({"identity_verified": True} if is_curated_priority else {}),
                },
                {"_id": 0, "price": 1, "stores_count": 1, "gz_name": 1,
                 "gz_pack": 1, "store_bitmap": 1, "city": 1, "updated_at": 1,
                 "source_url": 1, "identity_verified": 1, "price_parse_version": 1,
                 "availability_observed_at": 1, "archive_observation": 1},
            )
            async for gz_entry in net_cursor:
                if _src == "zdorovie" and gz_entry.get("price_parse_version") != 2:
                    continue
                _bm = gz_entry.get("store_bitmap")
                _city = gz_entry.get("city") or "msk"  # legacy без city → msk
                _availability_at = gz_entry.get("availability_observed_at")
                _price_at = gz_entry.get("updated_at")
                _availability_compare = (
                    _availability_at.replace(tzinfo=timezone.utc)
                    if hasattr(_availability_at, "tzinfo") and _availability_at.tzinfo is None
                    else _availability_at
                )
                _availability_fresh = bool(
                    _availability_compare and _availability_compare >= current_cutoff
                )
                _price_compare = (
                    _price_at.replace(tzinfo=timezone.utc)
                    if hasattr(_price_at, "tzinfo") and _price_at.tzinfo is None
                    else _price_at
                )
                _price_fresh = bool(_price_compare and _price_compare >= current_cutoff)
                _availability_confirmed = bool(
                    _availability_fresh and _price_fresh and (gz_entry.get("stores_count") or 0) > 0
                )
                real_prices.setdefault(_city, []).append({
                    "pharmacy_id": _src,
                    "price": gz_entry["price"],
                    "qty": gz_entry.get("stores_count", 0),
                    "gz_name": gz_entry.get("gz_name"),
                    "gz_pack": gz_entry.get("gz_pack"),
                    "store_bitmap": base64.b64encode(_bm).decode() if _availability_confirmed and _bm and any(_bm) else None,
                    "observed_at": gz_entry["updated_at"].isoformat() if hasattr(gz_entry.get("updated_at"), "isoformat") else gz_entry.get("updated_at"),
                    "source_url": gz_entry.get("source_url"),
                    "availability_confirmed": _availability_confirmed,
                    "availability_observed_at": _availability_at.isoformat() if hasattr(_availability_at, "isoformat") else _availability_at,
                    "identity_verified": bool(gz_entry.get("identity_verified")),
                    "archive_observation": bool(gz_entry.get("archive_observation")),
                })

        med["prices_by_city"] = real_prices
        med["prices_source"] = "real"
        indexable_rows = [
            row async for row in db.prices_real.aggregate(indexable_pairs_pipeline(slugs=[slug]))
        ]
        indexable_cities = {row["_id"]["city"] for row in indexable_rows}
        med["prices_updated_at_by_city"] = {
            city_id: max(
                (row.get("observed_at") for row in rows if row.get("observed_at") and row.get("availability_confirmed")),
                default=None,
            )
            for city_id, rows in real_prices.items()
        }
        med["seo_indexable_by_city"] = {
            city_id: True for city_id in indexable_cities
        }
        if city:
            # Shared SEO predicate used by sitemap, city-aware listings and
            # IndexNow.  Local store rows must not masquerade as independent
            # pharmacy networks here.
            med["seo_indexable"] = city in indexable_cities

        # Отзывы (UGC): агрегат + первая страница для SSR/schema. Блок и звёзды
        # в выдаче показываются ТОЛЬКО при count>=1 (иначе фронт ничего не рисует
        # — не плодим тонкость на пустых страницах). Один пул на канонический
        # препарат (по slug), общий для всех городов.
        try:
            r_pipeline = [
                {"$match": {"slug": slug, "status": "published"}},
                {"$facet": {
                    "stats": [{"$group": {"_id": None, "count": {"$sum": 1}, "avg": {"$avg": "$rating"}}}],
                    "dist": [{"$group": {"_id": "$rating", "n": {"$sum": 1}}}],
                    "items": [
                        {"$sort": {"created_at": -1}},
                        {"$limit": 5},
                        {"$project": {"_id": 0, "id": 1, "rating": 1, "text": 1, "photos": 1, "created_at": 1}},
                    ],
                }},
            ]
            r_doc = await db.reviews.aggregate(r_pipeline).to_list(1)
            r_doc = r_doc[0] if r_doc else {"stats": [], "dist": [], "items": []}
            r_stats = r_doc["stats"][0] if r_doc["stats"] else {"count": 0, "avg": 0}
            r_count = int(r_stats.get("count", 0))
            if r_count:
                r_dist = {str(i): 0 for i in range(1, 6)}
                for d in r_doc["dist"]:
                    r_dist[str(d["_id"])] = d["n"]
                r_items = []
                for it in r_doc["items"]:
                    ca = it.get("created_at")
                    r_items.append({
                        "id": it["id"], "rating": it["rating"], "text": it["text"],
                        "photos": it.get("photos") or [],
                        "created_at": ca.isoformat() if hasattr(ca, "isoformat") else ca,
                    })
                med["reviews"] = {
                    "count": r_count,
                    "avg": round(float(r_stats.get("avg") or 0), 1),
                    "dist": r_dist,
                    "items": r_items,
                }
        except Exception:
            pass

        # Гео-сводка по конкретному городу (SEO #1: локальный контент). Городской
        # уровень (все упаковки/сети), НЕ зависит от активной упаковки → стабильно
        # в SSR и при гидрации. Раскодируем store_bitmap (бит idx = аптека есть)
        # × gorzdrav_stores → число аптек + реальные адреса. Сети без по-аптечных
        # координат (Аптечество/Здоровье) дают только цену, без адресов.
        if city:
            try:
                city_entries = real_prices.get(city, [])
                idx_brand = {}      # idx -> {brand, price}
                price_list = []
                for e in city_entries:
                    pr = e.get("price")
                    pr = pr if (isinstance(pr, (int, float)) and pr > 0) else None
                    if pr is not None and e.get("availability_confirmed"):
                        price_list.append(pr)
                    bm_b64 = e.get("store_bitmap")
                    brand = e.get("pharmacy_id")
                    if not bm_b64:
                        continue
                    bm = base64.b64decode(bm_b64)
                    for byte_i, byte in enumerate(bm):
                        if not byte:
                            continue
                        for bit in range(8):
                            if byte & (1 << bit):
                                idx = byte_i * 8 + bit
                                cur = idx_brand.get(idx)
                                if cur is None:
                                    idx_brand[idx] = {"brand": brand, "price": pr}
                                elif pr is not None and (cur["price"] is None or pr < cur["price"]):
                                    idx_brand[idx] = {"brand": brand, "price": pr}
                if price_list:
                    stores = []
                    if idx_brand:
                        st_cursor = db.gorzdrav_stores.find(
                            {"city": city, "idx": {"$in": list(idx_brand.keys())},
                             "address": {"$nin": [None, ""]}, "active": {"$ne": False}},
                            {"_id": 0, "idx": 1, "name": 1, "full_name": 1, "address": 1},
                        )
                        async for s in st_cursor:
                            ib = idx_brand.get(s["idx"]) or {}
                            stores.append({
                                "name": s.get("full_name") or s.get("name"),
                                "address": s.get("address"),
                                "brand": ib.get("brand"),
                                "price": ib.get("price"),
                            })
                        stores.sort(key=lambda x: (x["price"] is None, x["price"] or 0))
                    med["geo"] = {
                        "city": city,
                        "count": len(idx_brand),
                        "min_price": min(price_list),
                        "max_price": max(price_list),
                        "stores": stores[:5],
                    }
            except Exception:
                pass

        return med

    @router.get("/medications/{slug}/analogs")
    async def medication_analogs(slug: str, limit: int = 8):
        med = await db.medications.find_one(
            {"slug": slug},
            {"_id": 0, "mnn": 1, "form": 1, "dosage": 1, "category": 1},
        )
        if not med:
            raise HTTPException(404, "Medication not found")
        # Strict analogs: same MNN + same form group. No category fallback.
        if not med.get("mnn"):
            return []
        target_grp = form_group(med.get("form"))
        target_dose = _parse_dose_first(med.get("dosage"))

        proj = {"_id": 0, "slug": 1, "name": 1, "manufacturer": 1,
                "dosage": 1, "form": 1, "rx": 1, "category": 1, "mnn": 1}
        # Wider DB query (by mnn only); filter form_group in Python (varied raw strings).
        cursor = db.medications.find(
            {"slug": {"$ne": slug}, "is_canonical": {"$ne": False},
             "mnn": med["mnn"]},
            proj,
        )
        items = [
            d async for d in cursor
            if form_group(d.get("form")) == target_grp
        ]
        # Sort by closeness of dosage (ascending |Δ|), then by name.
        def _key(d):
            dose = _parse_dose_first(d.get("dosage"))
            diff = abs(dose - target_dose) if (dose is not None and target_dose is not None) else 1e9
            return (diff, d.get("name") or "", d.get("slug") or "")
        items.sort(key=_key)
        return items[:limit]

    return router
