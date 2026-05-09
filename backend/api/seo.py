"""
SEO endpoints: robots.txt, sitemap (index + per-section), and a server-side
HTML pre-render for search bots (Yandex/Google/Bing/Mail.ru).

The strategy:
- Real users: receive the React SPA (ScriptSrc bundle, fast first paint via JS)
- Crawlers: detected by User-Agent → we render a static HTML with the right
  <title>, meta description, h1/h2, schema.org, canonical, navigation links,
  visible content in plaintext. Same data, different transport. Not cloaking.

CANONICAL_HOST is the production domain (e.g. aptekaa.ru). For preview we
fallback to the current host.
"""
from __future__ import annotations

import os
import re
import html
from typing import Optional, List, Tuple
from urllib.parse import quote
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse, HTMLResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from .pharmacies_seed import CITIES, CATEGORIES, PHARMACIES, find_pharmacy_by_id

CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "aptekaa.ru")
DEFAULT_CITY = "msk"

# Bots we render server-side for. Conservative list.
BOT_RE = re.compile(
    r"yandex|googlebot|bingbot|mail\.ru_bot|duckduckbot|baiduspider|"
    r"facebookexternalhit|twitterbot|telegrambot|whatsapp|slackbot|"
    r"applebot|petalbot|seznambot|ahrefsbot|semrushbot",
    re.I,
)


def is_bot(request: Request) -> bool:
    ua = request.headers.get("user-agent", "")
    return bool(BOT_RE.search(ua))


def base_url(request: Request) -> str:
    """Always return the canonical https://aptekaa.ru host for canonical URLs."""
    return f"https://{CANONICAL_HOST}"


def city_name(slug: str) -> str:
    for c in CITIES:
        if c["slug"] == slug:
            return c["name"]
    return "Москва"


def category_title(slug: str) -> Optional[str]:
    for c in CATEGORIES:
        if c["slug"] == slug:
            return c["title"]
    return None


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
            "Disallow: /admin/\n"
            "Disallow: /static/admin/\n"
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
        # Count meds for chunking
        total = await db.medications.count_documents({})
        chunks = max(1, (total + 49999) // 50000)
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
        per = 50000
        skip = (idx - 1) * per
        cursor = db.medications.find({}, {"_id": 0, "slug": 1}).skip(skip).limit(per)
        urls = []
        async for d in cursor:
            slug = d.get("slug")
            if not slug:
                continue
            for c in CITIES:
                urls.append(f"{host}/{c['slug']}/preparaty/{slug}")
        return _urlset(urls, lastmod_today=False)

    # ----- yandex-verification placeholder -----
    @router.get("/yandex_verification.html", response_class=HTMLResponse)
    async def yandex_verification():
        # Replace with real verification file content via env when given.
        code = os.environ.get("YANDEX_VERIFICATION", "")
        return HTMLResponse(f"<html><body>{code}</body></html>")

    return router


def _urlset(urls: List[str], lastmod_today: bool = True) -> Response:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = []
    for u in urls:
        if lastmod_today:
            items.append(f"<url><loc>{html.escape(u)}</loc><lastmod>{today}</lastmod></url>")
        else:
            items.append(f"<url><loc>{html.escape(u)}</loc></url>")
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(items)
        + "\n</urlset>\n"
    )
    return Response(content=body, media_type="application/xml")


# ===========================
# Server-side render for bots
# ===========================

def render_seo_html(
    title: str,
    description: str,
    canonical_url: str,
    h1: str,
    body_html: str,
    schema_jsonld: Optional[str] = None,
    breadcrumbs: Optional[List[Tuple[str, str]]] = None,
    image: Optional[str] = None,
) -> str:
    yandex_ver = os.environ.get("YANDEX_VERIFICATION", "")
    yandex_meta = f'<meta name="yandex-verification" content="{yandex_ver}">' if yandex_ver else ""
    google_ver = os.environ.get("GOOGLE_VERIFICATION", "")
    google_meta = f'<meta name="google-site-verification" content="{google_ver}">' if google_ver else ""
    crumbs_html = ""
    if breadcrumbs:
        crumbs_jsonld = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": name, "item": url}
                for i, (name, url) in enumerate(breadcrumbs)
            ],
        }
        import json
        crumbs_html = (
            '<nav aria-label="breadcrumbs"><ol>'
            + "".join(
                f'<li><a href="{html.escape(url)}">{html.escape(name)}</a></li>'
                for name, url in breadcrumbs
            )
            + "</ol></nav>\n"
            + f'<script type="application/ld+json">{json.dumps(crumbs_jsonld, ensure_ascii=False)}</script>'
        )
    schema_block = (
        f'<script type="application/ld+json">{schema_jsonld}</script>'
        if schema_jsonld
        else ""
    )
    og_image = f'<meta property="og:image" content="{html.escape(image)}">' if image else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="{html.escape(canonical_url)}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{html.escape(canonical_url)}">
<meta property="og:locale" content="ru_RU">
<meta property="og:site_name" content="АптекаА">
{og_image}
{yandex_meta}
{google_meta}
</head>
<body>
{crumbs_html}
<h1>{html.escape(h1)}</h1>
{body_html}
{schema_block}
</body>
</html>
"""


async def render_med_for_bot(db: AsyncIOMotorDatabase, city: str, slug: str, request: Request) -> HTMLResponse:
    med = await db.medications.find_one({"slug": slug}, {"_id": 0})
    if not med:
        return HTMLResponse(_render_404(request, city), status_code=404)

    cn = city_name(city)
    name = med.get("name") or "Препарат"
    mnn = med.get("mnn") or ""
    form = med.get("form", "").lower()
    dosage = med.get("dosage") or ""
    manufacturer = med.get("manufacturer") or ""
    rx = med.get("rx", False)
    vital = med.get("vital", False)
    limit_price = med.get("limit_price")
    variants = med.get("variants", []) or []

    title_pieces = [name]
    if dosage: title_pieces.append(dosage)
    title_pieces.append(f"купить в {cn_prepositional(cn)}")
    title_pieces.append(f"— цены и наличие в аптеках | АптекаА")
    title = " ".join(title_pieces)

    desc = (
        f"Сравните цены на {name}"
        + (f" ({mnn.lower()})" if mnn else "")
        + (f", {form}" if form else "")
        + (f", {dosage}" if dosage else "")
        + f" в аптеках {cn_genitive(cn)}. Аналоги, наличие, адреса. "
        + ("Отпускается по рецепту. " if rx else "")
        + ("Входит в перечень ЖНВЛП. " if vital else "")
        + "Бесплатный поиск без бронирования."
    )[:300]

    canonical = f"{base_url(request)}/{city}/preparaty/{slug}"

    body = []
    if rx:
        body.append('<p><strong>⚠️ Отпускается по рецепту.</strong> Препарат отпускается строго по назначению врача.</p>')
    if vital:
        body.append('<p>📋 Препарат входит в перечень <strong>ЖНВЛП</strong> (жизненно необходимых и важнейших лекарственных препаратов).</p>')
    if limit_price:
        body.append(f'<p>💰 <strong>Государственная предельная отпускная цена</strong>: {limit_price:.2f} ₽</p>')
    body.append("<h2>Описание препарата</h2>")
    body.append(f"<dl>")
    if mnn: body.append(f"<dt>Международное непатентованное наименование (МНН)</dt><dd>{html.escape(mnn)}</dd>")
    if form: body.append(f"<dt>Лекарственная форма</dt><dd>{html.escape(form)}</dd>")
    if dosage: body.append(f"<dt>Дозировка</dt><dd>{html.escape(dosage)}</dd>")
    if manufacturer: body.append(f"<dt>Производитель</dt><dd>{html.escape(manufacturer)}</dd>")
    if med.get("manufacturer_country"):
        body.append(f"<dt>Страна производства</dt><dd>{html.escape(med['manufacturer_country'])}</dd>")
    if med.get("ru_number"): body.append(f"<dt>Номер регистрационного удостоверения</dt><dd>{html.escape(med['ru_number'])}</dd>")
    body.append("</dl>")

    if variants:
        body.append(f"<h2>Доступные варианты упаковки ({len(variants)})</h2><ul>")
        for v in variants[:50]:
            label = v.get("label_name") or v.get("primary_pack_desc") or v.get("gtin")
            if label:
                body.append(f"<li>{html.escape(str(label))}{' · GTIN ' + str(v.get('gtin')) if v.get('gtin') else ''}</li>")
        body.append("</ul>")

    # Analogs
    analogs_cursor = db.medications.find(
        {"slug": {"$ne": slug}, "mnn": mnn} if mnn else {"slug": {"$ne": slug}, "category": med.get("category", "other")},
        {"_id": 0, "slug": 1, "name": 1, "manufacturer": 1, "dosage": 1},
    ).limit(8)
    analogs = [a async for a in analogs_cursor]
    if analogs:
        body.append(f"<h2>Аналоги {name}</h2><ul>")
        for a in analogs:
            au = f"{base_url(request)}/{city}/preparaty/{a['slug']}"
            label = " · ".join(filter(None, [a.get("name"), a.get("dosage"), a.get("manufacturer")]))
            body.append(f'<li><a href="{au}">{html.escape(label)}</a></li>')
        body.append("</ul>")

    # Pharmacy list (city)
    body.append(f"<h2>Аптеки {cn_genitive(cn)}</h2><ul>")
    for p in PHARMACIES:
        if p["city"] != city:
            continue
        u = f"{base_url(request)}/{city}/apteki/{p['id']}"
        body.append(f'<li><a href="{u}">{html.escape(p["name"])}</a> — {html.escape(p["address"])}</li>')
    body.append("</ul>")

    # Schema.org Drug
    import json as _json
    drug_schema = {
        "@context": "https://schema.org",
        "@type": "Drug",
        "name": name,
        "nonProprietaryName": mnn or None,
        "manufacturer": {"@type": "Organization", "name": manufacturer} if manufacturer else None,
        "dosageForm": form or None,
        "description": desc,
        "prescriptionStatus": "PrescriptionOnly" if rx else "OTC",
        "url": canonical,
    }
    drug_schema = {k: v for k, v in drug_schema.items() if v}
    schema_jsonld = _json.dumps(drug_schema, ensure_ascii=False)

    crumbs = [
        ("Главная", f"{base_url(request)}/{city}"),
        ("Препараты", f"{base_url(request)}/{city}/preparaty"),
        (name, canonical),
    ]

    h1 = " ".join(filter(None, [name, dosage, form])) or name
    return HTMLResponse(render_seo_html(
        title=title,
        description=desc,
        canonical_url=canonical,
        h1=h1,
        body_html="\n".join(body),
        schema_jsonld=schema_jsonld,
        breadcrumbs=crumbs,
    ))


async def render_home_for_bot(db: AsyncIOMotorDatabase, city: str, request: Request) -> HTMLResponse:
    cn = city_name(city)
    title = f"АптекаА — поиск лекарств и сравнение цен в аптеках {cn_genitive(cn)}"
    desc = (
        f"Бесплатный агрегатор цен и наличия лекарств в аптеках {cn_genitive(cn)}. "
        f"Сравнивайте цены, ищите аналоги, находите ближайшие аптеки. Без регистрации."
    )
    canonical = f"{base_url(request)}/{city}"

    total = await db.medications.count_documents({})
    body = [
        f"<p>Сервис АптекаА помогает быстро найти нужное лекарство по выгодной цене в аптеках {cn_genitive(cn)} и Санкт-Петербурга. В каталоге <strong>{total:,}</strong> зарегистрированных лекарственных препаратов.</p>".replace(",", " "),
        "<h2>Категории препаратов</h2><ul>",
    ]
    for cat in CATEGORIES:
        if cat["slug"] == "other":
            continue
        u = f"{base_url(request)}/{city}/kategorii/{cat['slug']}"
        body.append(f'<li><a href="{u}">{html.escape(cat["title"])}</a></li>')
    body.append("</ul>")
    body.append(f'<h2>Аптеки {cn_genitive(cn)}</h2><ul>')
    for p in PHARMACIES:
        if p["city"] != city:
            continue
        u = f"{base_url(request)}/{city}/apteki/{p['id']}"
        body.append(f'<li><a href="{u}">{html.escape(p["name"])}</a> — {html.escape(p["address"])}</li>')
    body.append("</ul>")

    import json as _json
    org_schema = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "АптекаА",
        "url": canonical,
        "potentialAction": {
            "@type": "SearchAction",
            "target": f"{base_url(request)}/{city}/poisk?q={{search_term_string}}",
            "query-input": "required name=search_term_string",
        },
    }
    return HTMLResponse(render_seo_html(
        title=title,
        description=desc,
        canonical_url=canonical,
        h1=f"АптекаА — лекарства в аптеках {cn_genitive(cn)}",
        body_html="\n".join(body),
        schema_jsonld=_json.dumps(org_schema, ensure_ascii=False),
        breadcrumbs=[("Главная", canonical)],
    ))


async def render_pharmacy_for_bot(db, city: str, pid: str, request: Request) -> HTMLResponse:
    p = find_pharmacy_by_id(pid)
    if not p or p["city"] != city:
        return HTMLResponse(_render_404(request, city), status_code=404)
    cn = city_name(city)
    title = f"{p['name']} — адрес, телефон, режим работы | АптекаА"
    desc = (
        f"{p['name']} в {cn_genitive(cn)}: {p['address']}. "
        f"Телефон {p.get('phone', '')}. Режим работы: {p.get('hours', '')}. "
        f"Сравните наличие и цены лекарств в этой аптеке."
    )[:300]
    canonical = f"{base_url(request)}/{city}/apteki/{pid}"
    body = [
        f"<dl>",
        f"<dt>Адрес</dt><dd>{html.escape(p['address'])}</dd>",
        f"<dt>Метро</dt><dd>{html.escape(p.get('metro') or '')}</dd>",
        f"<dt>Телефон</dt><dd>{html.escape(p.get('phone') or '')}</dd>",
        f"<dt>Режим работы</dt><dd>{html.escape(p.get('hours') or '')}</dd>",
        f"</dl>",
    ]
    import json as _json
    pharmacy_schema = {
        "@context": "https://schema.org",
        "@type": "Pharmacy",
        "name": p["name"],
        "address": {"@type": "PostalAddress", "streetAddress": p["address"], "addressLocality": cn, "addressCountry": "RU"},
        "telephone": p.get("phone"),
        "openingHours": p.get("hours"),
        "geo": {"@type": "GeoCoordinates", "latitude": p["lat"], "longitude": p["lng"]},
    }
    return HTMLResponse(render_seo_html(
        title=title,
        description=desc,
        canonical_url=canonical,
        h1=p["name"],
        body_html="\n".join(body),
        schema_jsonld=_json.dumps(pharmacy_schema, ensure_ascii=False),
        breadcrumbs=[
            ("Главная", f"{base_url(request)}/{city}"),
            ("Аптеки", f"{base_url(request)}/{city}/apteki"),
            (p["name"], canonical),
        ],
    ))


async def render_category_for_bot(db, city: str, cat_slug: str, request: Request) -> HTMLResponse:
    cat_title = category_title(cat_slug)
    if not cat_title:
        return HTMLResponse(_render_404(request, city), status_code=404)
    cn = city_name(city)
    title = f"{cat_title} — препараты в аптеках {cn_genitive(cn)} | АптекаА"
    desc = f"Каталог категории «{cat_title}» в аптеках {cn_genitive(cn)}. Сравните цены и наличие препаратов."
    canonical = f"{base_url(request)}/{city}/kategorii/{cat_slug}"

    cursor = db.medications.find({"category": cat_slug}, {"_id": 0, "slug": 1, "name": 1, "dosage": 1, "manufacturer": 1, "rx": 1}).limit(60)
    body = ["<ul>"]
    async for m in cursor:
        u = f"{base_url(request)}/{city}/preparaty/{m['slug']}"
        label = " · ".join(filter(None, [m.get("name"), m.get("dosage"), m.get("manufacturer")]))
        body.append(f'<li><a href="{u}">{html.escape(label)}</a>{" — Отпускается по рецепту" if m.get("rx") else ""}</li>')
    body.append("</ul>")

    return HTMLResponse(render_seo_html(
        title=title,
        description=desc,
        canonical_url=canonical,
        h1=f"{cat_title} в {cn_genitive(cn)}",
        body_html="\n".join(body),
        breadcrumbs=[
            ("Главная", f"{base_url(request)}/{city}"),
            ("Категории", f"{base_url(request)}/{city}/kategorii"),
            (cat_title, canonical),
        ],
    ))


def _render_404(request: Request, city: str) -> str:
    return render_seo_html(
        title="Страница не найдена | АптекаА",
        description="Запрошенная страница не найдена.",
        canonical_url=f"{base_url(request)}/{city}",
        h1="Страница не найдена",
        body_html=f'<p>Перейдите на <a href="{base_url(request)}/{city}">главную</a>.</p>',
    )


def cn_genitive(name: str) -> str:
    """Cheap russian genitive for city names used in our SEO copy."""
    map_ = {
        "Москва": "Москвы",
        "Санкт-Петербург": "Санкт-Петербурга",
    }
    return map_.get(name, name)


def cn_prepositional(name: str) -> str:
    """Russian prepositional case ('в Москве', 'в Санкт-Петербурге')."""
    map_ = {
        "Москва": "Москве",
        "Санкт-Петербург": "Санкт-Петербурге",
    }
    return map_.get(name, name)
