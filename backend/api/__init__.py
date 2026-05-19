"""
Catalog API: cities, categories, search, medication detail, pharmacies.

Mounted into the main FastAPI app via include_router from server.py.
All routes under /api/*.
"""
from __future__ import annotations

import re
import math
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
)


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

    # ----- Cities & categories -----

    @router.get("/cities")
    async def list_cities():
        return CITIES

    @router.get("/categories")
    async def list_categories():
        # attach counts from medications collection (canonical-only for accurate UX numbers)
        agg = db.medications.aggregate([
            {"$match": {"is_canonical": {"$ne": False}}},
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
    async def pharmacy_detail(pid: str):
        ph = find_pharmacy_by_id(pid)
        if not ph:
            raise HTTPException(404, "Pharmacy not found")
        return ph

    @router.get("/gorzdrav/stores")
    async def gorzdrav_stores(city: str = Query("msk"), response: Response = None):
        """Лёгкий список Горздрав-аптек для отображения маркеров на карте.
        Возвращает только координаты + минимум данных для маркера.
        Полная инфо (адрес, телефон, часы) — через /gorzdrav/stores/{store_id}."""
        cursor = db.gorzdrav_stores.find(
            {"city": city, "lat": {"$ne": None}, "lng": {"$ne": None}},
            {"_id": 0, "store_id": 1, "lat": 1, "lng": 1},
        )
        items = [doc async for doc in cursor]
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
        rx: Optional[bool] = Query(None),
        prefix: Optional[str] = Query(None, description="Первая буква названия (А–Я / A–Z)"),
        page: int = Query(1, ge=1),
        page_size: int = Query(24, ge=1, le=100),
    ):
        # Hide non-canonical duplicates in listings. Direct URL access still works.
        flt = {"is_canonical": {"$ne": False}}
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
    async def medication_detail(slug: str):
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
        cursor = db.prices.find(
            {"slug": slug},
            {"_id": 0, "pharmacy_id": 1, "price": 1, "qty": 1, "expiry_date": 1, "uploaded_at": 1},
        )
        async for p in cursor:
            ph = find_pharmacy_by_id(p["pharmacy_id"])
            if not ph:
                continue
            real_prices.setdefault(ph["city"], []).append({
                "pharmacy_id": p["pharmacy_id"],
                "price": p["price"],
                "qty": p.get("qty", 0),
                "expiry_date": p.get("expiry_date"),
            })

        # Добавляем цены Горздрав по ВСЕМ упаковкам (если матч есть).
        # Раньше was find_one — теперь find, чтобы при переключении упаковки
        # на фронте можно было показать данные именно для активной фасовки.
        gz_cursor = db.prices_real.find(
            {
                "slug": slug,
                "source": "gorzdrav",
                "match_status": {"$in": ["matched", "mnn_match", "needs_review"]},
                "price": {"$ne": None},
            },
            {"_id": 0, "price": 1, "stores_count": 1, "gz_name": 1, "gz_pack": 1},
        )
        async for gz_entry in gz_cursor:
            real_prices["msk"].append({
                "pharmacy_id": "gorzdrav",
                "price": gz_entry["price"],
                "qty": gz_entry.get("stores_count", 0),
                "gz_name": gz_entry.get("gz_name"),
                "gz_pack": gz_entry.get("gz_pack"),
            })

        med["prices_by_city"] = real_prices
        med["prices_source"] = "real"
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

