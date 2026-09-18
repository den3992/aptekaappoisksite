"""
SEO endpoints: robots.txt + sitemap (index + per-section).

До Phase 8 здесь же был bot-rewrite SSR-рендер (~1150 строк render_*_for_bot),
но после миграции на Next.js SSR он стал мёртвым кодом и удалён.

CANONICAL_HOST — продакшен-домен (aptekaa.ru).
"""
from __future__ import annotations

import os
import html
from typing import Optional, List, Tuple
from urllib.parse import quote
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse, HTMLResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from .pharmacies_seed import CITIES, CATEGORIES, PHARMACIES

CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "aptekaa.ru")
DEFAULT_CITY = "msk"
SITEMAP_CHUNK_SIZE = 10000
REAL_SOURCES = ["gorzdrav", "apteka366", "rigla", "maksavit", "aptechestvo", "zdorovie", "magnit", "farmakopeika"]
MATCH_OK = ["matched", "mnn_match", "needs_review"]


def _indexable_pairs_pipeline():
    """Canonical city/slug pairs satisfying the shared >=2-network rule."""
    return [
        {"$match": {
            "source": {"$in": REAL_SOURCES},
            "price": {"$gt": 0},
            "match_status": {"$in": MATCH_OK},
        }},
        {"$group": {"_id": {"city": "$city", "slug": "$slug"}, "nets": {"$addToSet": "$source"}}},
        {"$match": {"$expr": {"$gte": [{"$size": "$nets"}, 2]}}},
        {"$lookup": {
            "from": "medications", "localField": "_id.slug", "foreignField": "slug", "as": "med",
        }},
        {"$unwind": "$med"},
        {"$match": {"med.is_canonical": {"$ne": False}}},
    ]

def make_seo_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter()

    # ----- robots.txt -----
    @router.get("/robots.txt", response_class=PlainTextResponse)
    async def robots():
        host = CANONICAL_HOST
        body = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /api/\n"
            "\n"
            "User-agent: Yandex\n"
            "Allow: /\n"
            "Disallow: /api/\n"
            "Clean-param: utm_source&utm_medium&utm_campaign&utm_content&utm_term&yclid&gclid&v&cb&security\n"
            f"Host: {host}\n"
            "\n"
            f"Sitemap: https://{host}/sitemap.xml\n"
        )
        return PlainTextResponse(body, media_type="text/plain; charset=utf-8")

    # ----- sitemap index -----
    @router.get("/sitemap.xml")
    async def sitemap_index():
        host = f"https://{CANONICAL_HOST}"
        count_rows = await db.prices_real.aggregate(
            _indexable_pairs_pipeline() + [{"$count": "total"}], allowDiskUse=True
        ).to_list(1)
        total = count_rows[0]["total"] if count_rows else 0
        chunks = (total + SITEMAP_CHUNK_SIZE - 1) // SITEMAP_CHUNK_SIZE
        items = [
            f"<sitemap><loc>{host}/sitemap_static.xml</loc></sitemap>",
            f"<sitemap><loc>{host}/sitemap_pharmacies.xml</loc></sitemap>",
            f"<sitemap><loc>{host}/sitemap_categories.xml</loc></sitemap>",
        ]
        for i in range(chunks):
            items.append(
                f"<sitemap><loc>{host}/sitemap_meds_{i + 1}.xml</loc></sitemap>"
            )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(items)
            + "\n</sitemapindex>\n"
        )
        return Response(content=body, media_type="application/xml")

    @router.get("/sitemap_static.xml")
    async def sitemap_static():
        host = f"https://{CANONICAL_HOST}"
        city_rows = await db.prices_real.aggregate(
            _indexable_pairs_pipeline() + [{"$group": {"_id": "$_id.city"}}], allowDiskUse=True
        ).to_list(None)
        cities_with_catalog = {row["_id"] for row in city_rows}
        urls = []
        for c in CITIES:
            paths = ["", "apteki"]
            if c["slug"] in cities_with_catalog:
                paths.extend(["kategorii", "preparaty"])
            for path in paths:
                u = f"{host}/{c['slug']}" if not path else f"{host}/{c['slug']}/{path}"
                urls.append(u)
        # Informational/legal pages exist only at the site root.  Do not put
        # redirecting `/` or nonexistent city-prefixed copies in the sitemap.
        for path in (
            "dlya-aptek", "o-servise", "kontakty",
            "politika-konfidencialnosti", "soglasie-na-obrabotku-pd",
        ):
            urls.append(f"{host}/{path}")
        return _urlset(urls, lastmod_today=False)

    @router.get("/sitemap_categories.xml")
    async def sitemap_categories():
        host = f"https://{CANONICAL_HOST}"
        rows = await db.prices_real.aggregate(
            _indexable_pairs_pipeline() + [
                {"$match": {"med.category": {"$nin": [None, "", "other"]}}},
                {"$group": {"_id": {"city": "$_id.city", "category": "$med.category"}}},
                {"$sort": {"_id.city": 1, "_id.category": 1}},
            ],
            allowDiskUse=True,
        ).to_list(None)
        urls = [f"{host}/{row['_id']['city']}/kategorii/{row['_id']['category']}" for row in rows]
        return _urlset(urls, lastmod_today=False)

    @router.get("/sitemap_pharmacies.xml")
    async def sitemap_pharmacies():
        host = f"https://{CANONICAL_HOST}"
        urls = []
        for p in PHARMACIES:
            urls.append(f"{host}/{p['city']}/apteki/{p['id']}")
        return _urlset(urls, lastmod_today=False)

    @router.get("/sitemap_meds_{idx}.xml")
    async def sitemap_meds(idx: int):
        host = f"https://{CANONICAL_HOST}"
        skip = (idx - 1) * SITEMAP_CHUNK_SIZE
        if idx < 1:
            raise HTTPException(status_code=404, detail="sitemap chunk out of range")
        rows = await db.prices_real.aggregate(
            _indexable_pairs_pipeline() + [
                {"$sort": {"_id.city": 1, "_id.slug": 1}},
                {"$skip": skip},
                {"$limit": SITEMAP_CHUNK_SIZE},
                {"$project": {"_id": 1, "image_url": "$med.image_url"}},
            ],
            allowDiskUse=True,
        ).to_list(None)
        if not rows:
            raise HTTPException(status_code=404, detail="sitemap chunk out of range")
        urls = []
        for row in rows:
            city, slug = row["_id"]["city"], row["_id"]["slug"]
            img = row.get("image_url") or ""
            img_abs = f"{host}{quote(img, safe='/')}" if img.startswith("/") else (img or None)
            # lastmod intentionally omitted until parsers store a truthful
            # content_changed_at instead of their every-run updated_at value.
            urls.append((f"{host}/{city}/preparaty/{slug}", None, img_abs))
        return _urlset(urls)

    # ----- yandex-verification placeholder -----
    @router.get("/yandex_verification.html", response_class=HTMLResponse)
    async def yandex_verification():
        # Replace with real verification file content via env when given.
        code = os.environ.get("YANDEX_VERIFICATION", "")
        return HTMLResponse(f"<html><body>{code}</body></html>")

    return router


def _urlset(urls, lastmod_today: bool = True) -> Response:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Элемент: строка URL, кортеж (url, lastmod|None) или (url, lastmod|None, image|None).
    has_images = any(isinstance(u, tuple) and len(u) >= 3 and u[2] for u in urls)
    items = []
    for u in urls:
        if isinstance(u, tuple):
            loc, lm = u[0], u[1]
            img = u[2] if len(u) >= 3 else None
            lm_tag = f"<lastmod>{lm}</lastmod>" if lm else ""
            img_tag = (
                f"<image:image><image:loc>{html.escape(img)}</image:loc></image:image>"
                if img else ""
            )
            items.append(f"<url><loc>{html.escape(loc)}</loc>{lm_tag}{img_tag}</url>")
        elif lastmod_today:
            items.append(f"<url><loc>{html.escape(u)}</loc><lastmod>{today}</lastmod></url>")
        else:
            items.append(f"<url><loc>{html.escape(u)}</loc></url>")
    urlset_open = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    if has_images:
        urlset_open += ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"'
    urlset_open += ">"
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + urlset_open + "\n"
        + "\n".join(items)
        + "\n</urlset>\n"
    )
    return Response(content=body, media_type="application/xml")


# ===========================
# Server-side render for bots
# ===========================
