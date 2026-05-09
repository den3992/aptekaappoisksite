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

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorDatabase

from .pharmacies_seed import (
    CITIES,
    PHARMACIES,
    CATEGORIES,
    pharmacies_by_city,
    find_pharmacy_by_id,
)


def make_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter()

    # ----- Cities & categories -----

    @router.get("/cities")
    async def list_cities():
        return CITIES

    @router.get("/categories")
    async def list_categories():
        # attach counts from medications collection
        agg = db.medications.aggregate([
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
        page: int = Query(1, ge=1),
        page_size: int = Query(24, ge=1, le=100),
    ):
        flt = {}
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
        return SearchResponse(
            query=q, total=total, page=page, page_size=page_size, items=items
        )

    # Lightweight typeahead for search box / chatbot
    @router.get("/search/suggest")
    async def search_suggest(q: str = Query(...), limit: int = Query(8, ge=1, le=20)):
        term = q.strip()
        if len(term) < 2:
            return []
        # Prefix-style search: case‑insensitive on first chars
        pattern = re.escape(term)
        cursor = db.medications.find(
            {"$or": [
                {"name": {"$regex": f"^{pattern}", "$options": "i"}},
                {"mnn": {"$regex": f"^{pattern.upper()}", "$options": "i"}},
            ]},
            {"_id": 0, "slug": 1, "name": 1, "mnn": 1, "dosage": 1, "form": 1},
        ).limit(limit)
        return [doc async for doc in cursor]

    # ----- Medication detail -----

    @router.get("/medications/{slug}")
    async def medication_detail(slug: str):
        med = await db.medications.find_one({"slug": slug}, {"_id": 0})
        if not med:
            raise HTTPException(404, "Medication not found")

        # Build mock prices for now (per-pharmacy, deterministic per slug)
        med["prices_by_city"] = _mock_prices(slug)
        return med

    @router.get("/medications/{slug}/analogs")
    async def medication_analogs(slug: str, limit: int = 8):
        med = await db.medications.find_one(
            {"slug": slug}, {"_id": 0, "mnn": 1, "category": 1}
        )
        if not med:
            raise HTTPException(404, "Medication not found")
        flt = {"slug": {"$ne": slug}}
        if med.get("mnn"):
            flt["mnn"] = med["mnn"]
        else:
            flt["category"] = med.get("category", "other")
        cursor = db.medications.find(
            flt,
            {"_id": 0, "slug": 1, "name": 1, "manufacturer": 1, "dosage": 1,
             "form": 1, "rx": 1, "category": 1, "mnn": 1},
        ).sort([("name", 1), ("slug", 1)]).limit(limit)
        return [d async for d in cursor]

    return router


# ===========================
# Mock prices (deterministic)
# ===========================

def _mock_prices(slug: str) -> dict:
    """Return prices_by_city = {msk: [...], spb: [...]}.

    The price is deterministic per slug so reloading does not jiggle the UI.
    Real prices will come from FTP price-list ingestion later.
    """
    msk_ids = [p["id"] for p in PHARMACIES if p["city"] == "msk"]
    spb_ids = [p["id"] for p in PHARMACIES if p["city"] == "spb"]
    # Deterministic seed from slug
    h = sum(ord(c) for c in slug) or 1
    base = 60 + (h % 280)  # 60..340 ₽
    out = {}
    for city, ids in (("msk", msk_ids), ("spb", spb_ids)):
        rows = []
        for i, pid in enumerate(ids):
            seed = (h * 1664525 + i * 1013904223) % (2**31)
            price = round((base * (0.85 + (seed % 1000) / 1000 * 0.4)) / 5) * 5
            qty = (seed // 1000) % 30 + 1
            rows.append({"pharmacy_id": pid, "price": price, "qty": qty})
        out[city] = rows
    return out
