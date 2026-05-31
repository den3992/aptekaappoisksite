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
            "Clean-param: utm_source&utm_medium&utm_campaign&utm_content&utm_term\n"
            f"Host: {host}\n"
            "\n"
            f"Sitemap: https://{host}/sitemap.xml\n"
        )
        return PlainTextResponse(body, media_type="text/plain; charset=utf-8")

    # ----- sitemap index -----
    @router.get("/sitemap.xml")
    async def sitemap_index():
        host = f"https://{CANONICAL_HOST}"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Каждый чанк не должен превышать 50k URL (лимит протокола sitemap).
        # На каждый slug приходится len(CITIES) URL (по одному на город),
        # поэтому делим лимит на число городов.
        per_chunk_slugs = max(1, 50000 // max(1, len(CITIES)))
        # Sitemap only lists canonical pages (duplicates are hidden via rel=canonical)
        total = await db.medications.count_documents({"is_canonical": {"$ne": False}})
        chunks = max(1, (total + per_chunk_slugs - 1) // per_chunk_slugs)
        items = [
            f"<sitemap><loc>{host}/sitemap_static.xml</loc><lastmod>{now}</lastmod></sitemap>",
            f"<sitemap><loc>{host}/sitemap_pharmacies.xml</loc><lastmod>{now}</lastmod></sitemap>",
            f"<sitemap><loc>{host}/sitemap_categories.xml</loc><lastmod>{now}</lastmod></sitemap>",
        ]
        for i in range(chunks):
            items.append(
                f"<sitemap><loc>{host}/sitemap_meds_{i + 1}.xml</loc><lastmod>{now}</lastmod></sitemap>"
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
        urls = []
        for c in CITIES:
            for path in ("", "kategorii", "preparaty", "apteki",
                         "dlya-aptek", "o-servise", "kontakty"):
                u = f"{host}/{c['slug']}" if not path else f"{host}/{c['slug']}/{path}"
                urls.append(u)
        # Plus root → defaults to msk
        urls.insert(0, f"{host}/")
        return _urlset(urls, lastmod_today=True)

    @router.get("/sitemap_categories.xml")
    async def sitemap_categories():
        host = f"https://{CANONICAL_HOST}"
        urls = []
        for c in CITIES:
            for cat in CATEGORIES:
                urls.append(f"{host}/{c['slug']}/kategorii/{cat['slug']}")
        return _urlset(urls, lastmod_today=True)

    @router.get("/sitemap_pharmacies.xml")
    async def sitemap_pharmacies():
        host = f"https://{CANONICAL_HOST}"
        urls = []
        for p in PHARMACIES:
            urls.append(f"{host}/{p['city']}/apteki/{p['id']}")
        return _urlset(urls, lastmod_today=True)

    @router.get("/sitemap_meds_{idx}.xml")
    async def sitemap_meds(idx: int):
        host = f"https://{CANONICAL_HOST}"
        # len(CITIES) URL на slug; держим чанк ≤ 50k URL (лимит протокола).
        per = max(1, 50000 // max(1, len(CITIES)))
        skip = (idx - 1) * per
        # Чанки за пределами числа канонических препаратов не существуют —
        # отдаём 404, а не пустой 200 (иначе боты держат «мёртвые» sitemap).
        total = await db.medications.count_documents({"is_canonical": {"$ne": False}})
        if idx < 1 or skip >= total:
            raise HTTPException(status_code=404, detail="sitemap chunk out of range")
        # Дата последнего обновления цены по каждому slug — одним запросом.
        # Яндекс по <lastmod> понимает свежесть и приоритет переобхода.
        lastmod_map = {}
        async for row in db.prices_real.aggregate([
            {"$match": {"source": {"$in": ["gorzdrav", "apteka366", "rigla", "maksavit"]},
                        "updated_at": {"$ne": None},
                        "price": {"$ne": None},
                        "match_status": {"$in": ["matched", "mnn_match", "needs_review"]}}},
            {"$group": {"_id": "$slug", "lm": {"$max": "$updated_at"}}},
        ]):
            sl, lm = row.get("_id"), row.get("lm")
            if sl and lm:
                try:
                    lastmod_map[sl] = lm.strftime("%Y-%m-%d")
                except Exception:
                    pass
        # Число канонических препаратов на каждый МНН — для определения,
        # есть ли аналоги. Считаем в Python: Mongo $toLower НЕ понижает
        # кириллицу, а Python .lower() — понижает.
        mnn_count = {}
        async for m in db.medications.find(
            {"is_canonical": {"$ne": False}, "mnn": {"$nin": [None, ""]}},
            {"_id": 0, "mnn": 1},
        ):
            k = (m.get("mnn") or "").strip().lower()
            if k:
                mnn_count[k] = mnn_count.get(k, 0) + 1
        cursor = db.medications.find(
            {"is_canonical": {"$ne": False}},
            {"_id": 0, "slug": 1, "mnn": 1, "image_url": 1},
        ).sort("slug", 1).skip(skip).limit(per)
        urls = []
        async for d in cursor:
            slug = d.get("slug")
            if not slug:
                continue
            # Тупиковая страница = нет цены ни в одной сети И нет аналогов по МНН.
            # Те же страницы отдаются с noindex — в sitemap им не место.
            has_price = slug in lastmod_map
            mnn = (d.get("mnn") or "").strip().lower()
            has_analogs = bool(mnn) and mnn_count.get(mnn, 0) > 1
            if not has_price and not has_analogs:
                continue
            lm = lastmod_map.get(slug)
            # Фото препарата → image sitemap extension (Яндекс.Картинки).
            # Имена файлов могут содержать кириллицу — percent-encode пути.
            img = d.get("image_url") or ""
            img_abs = f"{host}{quote(img, safe='/')}" if img.startswith("/") else (img or None)
            for c in CITIES:
                urls.append((f"{host}/{c['slug']}/preparaty/{slug}", lm, img_abs))
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

