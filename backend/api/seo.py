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



def _title_case(s: Optional[str]) -> str:
    if not s: return ""
    t = str(s).strip()
    if not t: return ""
    return t[0].upper() + t[1:].lower()


_COUNTRY_NORMALIZE = {
    "соединенное королевство": "Великобритания",
    "соединенные штаты": "США",
    "чешская республика": "Чехия",
    "республика северная македония": "Северная Македония",
    "македония": "Северная Македония",
    "киргизская республика": "Киргизия",
    "южно-африканская республика": "ЮАР",
    "объединенные арабские эмираты": "ОАЭ",
    "сан марино": "Сан-Марино",
    "корея": "Южная Корея",
}


def _normalize_country(s: Optional[str]) -> str:
    if not s: return ""
    key = str(s).strip().lower()
    return _COUNTRY_NORMALIZE.get(key, _title_case(s))

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
        # Each sitemap chunk holds 25k slugs × 2 cities = 50k URLs (the per-sitemap limit)
        per_chunk_slugs = 25000
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
        # 25,000 slugs * 2 cities = 50,000 URLs (per-sitemap protocol limit)
        per = 25000
        skip = (idx - 1) * per
        cursor = db.medications.find(
            {"is_canonical": {"$ne": False}},
            {"_id": 0, "slug": 1},
        ).sort("slug", 1).skip(skip).limit(per)
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


def _simplify_pack(s):
    """Mirrors simplifyPack() in MedDetail.jsx for SSR consistency."""
    if not s: return ""
    import re as _re
    txt = str(s).strip()
    # Strip ЕСКЛП encoding artifacts: 'см[3*];^мл' → 'мл'
    txt = _re.sub(r"\s*см\s*\[3\*\]\s*;?\s*\^?\s*мл", " мл", txt, flags=_re.I)
    txt = _re.sub(r"\s*л\s*;\s*\^?\s*дм\s*\[3\*\]", " л", txt, flags=_re.I)
    txt = _re.sub(r"м\s*\[3\*\]", "м³", txt, flags=_re.I)
    txt = _re.sub(r"\[\*\]", "", txt)
    txt = _re.sub(r";\^", " ", txt)
    txt = _re.sub(r"\bусл\.?\s*ед\b", "усл.ед.", txt, flags=_re.I)
    txt = _re.sub(r"\s+", " ", txt).strip()
    # N x <CONTAINER> по M [unit]
    amp = _re.match(r"^(\d+|НЕ УКАЗАНО)\s*[xх×]\s*(АМПУЛ\\S*|ФЛАКОН\\S*|ШПРИЦ\\S*|БАНК\\S*|БЛИСТЕР\\S*|УПАКОВК\\S*|СТРИП\\S*|КАРТРИДЖ\\S*|ТУБ\\S*)[^\d]*\s*по\s*(\d+(?:[\.,]\d+)?)\s*(?:тысяч.?\s*)?(\S+)?", txt, _re.I)
    if amp:
        n = "1" if amp.group(1) == "НЕ УКАЗАНО" else amp.group(1)
        m_val = amp.group(3).replace(",", ".")
        if m_val.endswith(".000"): m_val = m_val[:-4]
        u_raw = (amp.group(4) or "").replace(".", "").replace(",", "").lower()
        synonyms = {"миллиграмм": "мг", "миллилитр": "мл", "грамм": "г"}
        u_raw = synonyms.get(u_raw, u_raw)
        unit = u_raw if u_raw in ("мл","г","мг","мкг","л","шт") else "шт"
        txt = f"{n} × {m_val} {unit}"
    else:
        solo = _re.match(r"^(АМПУЛ\\S*|ФЛАКОН\\S*|ШПРИЦ\\S*|БАНК\\S*|БЛИСТЕР\\S*|УПАКОВК\\S*|СТРИП\\S*|КАРТРИДЖ\\S*|ТУБ\\S*)[^\d]*\s*по\s*(\d+(?:[\.,]\d+)?)\s*(\S+)?", txt, _re.I)
        if solo:
            m_val = solo.group(2).replace(",", ".")
            if m_val.endswith(".000"): m_val = m_val[:-4]
            u_raw = (solo.group(3) or "").replace(".", "").replace(",", "").lower()
            synonyms = {"миллиграмм": "мг", "миллилитр": "мл", "грамм": "г"}
            u_raw = synonyms.get(u_raw, u_raw)
            unit = u_raw if u_raw in ("мл","г","мг","мкг","л","шт") else "шт"
            txt = f"{m_val} {unit}"
    m = _re.search(r"(\d+)\s*[×xх]\s*(\d+(?:[\.,]\d+)?)\s*(шт|табл?\.?|капс?\.?|доз\S*|усл\.?\s*ед\.?)", txt, _re.I)
    if m:
        u = m.group(3).lower()
        if u.startswith("доз"):
            unit = "доз"
        elif u.startswith("усл"):
            unit = "усл.ед."
        else:
            unit = "шт"
        total = int(m.group(1)) * float(m.group(2).replace(",", "."))
        total_str = str(int(total)) if total.is_integer() else str(total)
        return f"{total_str} {unit}"
    m = _re.search(r"(?:по\s+)?(\d+(?:[\.,]\d+)?)\s*(шт|табл?\.?|капс?\.?|доз\S*|усл\.?\s*ед\.?|г|мг|мл|мкг|МЕ|ЕД|м³|%)", txt, _re.I)
    if m:
        v = m.group(1).replace(",", ".")
        u_raw = (m.group(2) or "шт")
        u = u_raw.lower().replace(".", "")
        if u.startswith("табл") or u.startswith("капс"):
            unit = "шт"
        elif u.startswith("доз"):
            unit = "доз"
        elif u.startswith("усл"):
            unit = "усл.ед."
        elif u_raw in ("МЕ", "ЕД"):
            unit = u_raw
        elif u_raw == "м³":
            unit = "м³"
        else:
            unit = u
        fv = float(v)
        vs = str(int(fv)) if fv.is_integer() else v
        return f"{vs} {unit}"
    m = _re.search(r"№\s*(\d+)", txt)
    if m:
        return f"{m.group(1)} шт"
    return txt if len(txt) <= 24 else (txt[:22] + "…")



def _format_pack_list(items):
    """Compact display of unique pack sizes."""
    if not items: return ""
    if len(items) <= 3:
        return ", ".join(items)
    import re as _re
    parsed = []
    for s in items:
        m = _re.match(r"^(\d+(?:\.\d+)?)\s*(.+)$", str(s))
        if m:
            parsed.append((float(m.group(1)), m.group(2).strip(), s))
    if len(parsed) == len(items) and len({p[1] for p in parsed}) == 1:
        parsed.sort()
        lo = parsed[0][0]
        hi = parsed[-1][0]
        unit = parsed[0][1]
        def fmt(x): return str(int(x)) if x.is_integer() else str(x)
        return f"{fmt(lo)}–{fmt(hi)} {unit} ({len(items)} шт)"
    return f"{items[0]}, {items[1]}, … ({len(items)} шт)"


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
    image_path = med.get("image_url") or ""
    image_abs = f"{base_url(request)}{image_path}" if image_path and image_path.startswith("/") else (image_path or None)

    def _pack_sort_key(p):
        import re as _re
        m = _re.match(r"^(\d+(?:[\.,]\d+)?)", p)
        return float(m.group(1).replace(",", ".")) if m else 0.0
    _uniq_packs = sorted({_simplify_pack(v.get("pack_size")) for v in variants if _simplify_pack(v.get("pack_size"))}, key=_pack_sort_key)
    pack_short = _uniq_packs[0] if len(_uniq_packs) == 1 else ""

    title_pieces = [name]
    if dosage: title_pieces.append(dosage)
    if pack_short:
        title_pieces.append(pack_short)
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
        + "Бесплатный поиск без бронирования."
    )[:300]

    enrichment = med.get("enrichment") or {}
    if enrichment.get("summary"):
        desc = f"{enrichment['summary']} Сравните цены и наличие в аптеках {cn_genitive(cn)}."[:300]

    # If this is a non-canonical duplicate, point canonical to the chosen representative.
    # This tells Yandex/Google "the real page is /…/<canonical_slug>" and the duplicate
    # won't compete in search results.
    canonical_slug = med.get("canonical_slug") or slug
    canonical = f"{base_url(request)}/{city}/preparaty/{canonical_slug}"

    body = []
    if rx:
        body.append('<p><strong>⚠️ Отпускается по рецепту.</strong> Препарат отпускается строго по назначению врача.</p>')

    # LLM-enriched block (top-200) — placed early so crawlers see real content first
    if enrichment.get("summary") or enrichment.get("indications") or enrichment.get("how_to_take"):
        body.append("<h2>О препарате</h2>")
        if enrichment.get("summary"):
            body.append(f"<p>{html.escape(enrichment['summary'])}</p>")
        if enrichment.get("indications"):
            body.append("<h3>Показания</h3><ul>")
            for ind in enrichment["indications"][:8]:
                body.append(f"<li>{html.escape(str(ind))}</li>")
            body.append("</ul>")
        if enrichment.get("contraindications"):
            body.append("<h3>Противопоказания</h3><ul>")
            for c in enrichment["contraindications"][:6]:
                body.append(f"<li>{html.escape(str(c))}</li>")
            body.append("</ul>")
        if enrichment.get("how_to_take"):
            body.append(f"<h3>Способ применения</h3><p>{html.escape(enrichment['how_to_take'])}</p>")

    body.append("<h2>Описание препарата</h2>")
    body.append(f"<dl>")
    if mnn: body.append(f"<dt>Международное непатентованное наименование (МНН)</dt><dd>{html.escape(_title_case(mnn))}</dd>")
    if form: body.append(f"<dt>Лекарственная форма</dt><dd>{html.escape(form)}</dd>")
    if dosage: body.append(f"<dt>Дозировка</dt><dd>{html.escape(dosage)}</dd>")
    if manufacturer: body.append(f"<dt>Производитель</dt><dd>{html.escape(manufacturer)}</dd>")
    if med.get("manufacturer_country"):
        body.append(f"<dt>Страна производства</dt><dd>{html.escape(_normalize_country(med['manufacturer_country']))}</dd>")
    if med.get("ru_number"): body.append(f"<dt>Номер регистрационного удостоверения</dt><dd>{html.escape(med['ru_number'])}</dd>")
    body.append("</dl>")

    if variants:
        body.append(f"<h2>Доступные варианты упаковки ({len(variants)})</h2><ul>")
        for v in variants[:50]:
            label = v.get("label_name") or v.get("primary_pack_desc") or v.get("gtin")
            if label:
                body.append(f"<li>{html.escape(str(label))}{' · GTIN ' + str(v.get('gtin')) if v.get('gtin') else ''}</li>")
        body.append("</ul>")

    # Analogs — hide duplicate registrations (only canonical cards as analogs).
    analog_flt = {"slug": {"$ne": slug}, "is_canonical": {"$ne": False}}
    if mnn:
        analog_flt["mnn"] = mnn
    else:
        analog_flt["category"] = med.get("category", "other")
    analogs_cursor = db.medications.find(
        analog_flt,
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

    # Mandatory medical disclaimer (ФЗ-38 «О рекламе», ст. 24).
    # Mirrors what real users see via Footer + MedDetail page, so SSR vs React are
    # consistent (no cloaking). Uses LLM-provided disclaimer if present, otherwise
    # the standard wording matching the React UI.
    disclaimer_text = enrichment.get("disclaimer") or (
        "Имеются противопоказания. Перед применением проконсультируйтесь с врачом "
        "или фармацевтом. Информация на странице носит справочный характер и не "
        "является рекомендацией к применению, не заменяет назначение специалиста. "
        "АптекаА не является аптекой и не осуществляет продажу лекарственных средств."
    )
    body.append(
        '<div role="note" aria-label="Медицинское предупреждение">'
        f'<p><strong>Важно:</strong> {html.escape(disclaimer_text)}</p>'
        '</div>'
    )

    # Pack-size list (visible to bots so they see the assortment)
    if len(_uniq_packs) >= 2:
        chips_html = " · ".join(html.escape(p) for p in _uniq_packs)
        body.append(
            f'<div class="pack-sizes"><strong>Фасовка:</strong> {chips_html}</div>'
        )

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
        "image": image_abs,
        "url": canonical,
    }
    if _uniq_packs:
        drug_schema["isVariantOf"] = {
            "@type": "ProductGroup",
            "name": name,
            "hasVariant": [
                {"@type": "Product", "name": f"{name} {p}", "size": p}
                for p in _uniq_packs
            ],
        }
    drug_schema = {k: v for k, v in drug_schema.items() if v}
    schema_jsonld = _json.dumps(drug_schema, ensure_ascii=False)

    crumbs = [
        ("Главная", f"{base_url(request)}/{city}"),
        ("Препараты", f"{base_url(request)}/{city}/preparaty"),
        (name, canonical),
    ]

    h1 = " ".join(filter(None, [name, dosage])) or name
    if pack_short:
        h1 = f"{h1}, {pack_short}"
    if image_abs:
        body.insert(0, (
            f'<figure><img src="{html.escape(image_abs)}" '
            f'alt="{html.escape(h1)}" loading="eager" '
            f'style="max-width:320px;height:auto;" />'
            f'<figcaption>{html.escape(name)}</figcaption></figure>'
        ))
    return HTMLResponse(render_seo_html(
        title=title,
        description=desc,
        canonical_url=canonical,
        h1=h1,
        body_html="\n".join(body),
        schema_jsonld=schema_jsonld,
        breadcrumbs=crumbs,
        image=image_abs,
    ))


async def render_home_for_bot(db: AsyncIOMotorDatabase, city: str, request: Request) -> HTMLResponse:
    cn = city_name(city)
    title = f"Аптечная справочная {cn_genitive(cn)}: поиск лекарств, цены и наличие в аптеках | АптекаА"
    desc = (
        f"Бесплатная аптечная справочная {cn_genitive(cn)}: цены и наличие лекарств в аптеках, "
        f"аналоги препаратов, адреса и режим работы. Без регистрации."
    )
    canonical = f"{base_url(request)}/{city}"

    total = await db.medications.count_documents({"is_canonical": {"$ne": False}})
    total_str = f"{total:,}".replace(",", " ")
    body = [
        f"<p>АптекаА — бесплатная аптечная справочная по Москве и Санкт-Петербургу. Найдите нужное лекарство, узнайте цены и наличие в ближайших аптеках, посмотрите аналоги препаратов. В каталоге <strong>{total_str}</strong> зарегистрированных лекарственных препаратов.</p>",
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

    cursor = db.medications.find(
        {"category": cat_slug, "is_canonical": {"$ne": False}},
        {"_id": 0, "slug": 1, "name": 1, "dosage": 1, "manufacturer": 1, "rx": 1},
    ).limit(60)
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



# ---------------------------------------------------------------------------
# Index-pages SSR for crawlers (/<city>/preparaty, /<city>/apteki,
# /<city>/kategorii). These URLs are listed in sitemap_static.xml; without
# their own SSR the dispatcher fell through to 404, causing soft-404 warnings
# in Yandex.Webmaster.
# ---------------------------------------------------------------------------

async def render_catalog_index_for_bot(db, city: str, request: Request) -> HTMLResponse:
    cn = city_name(city)
    title = f"Каталог лекарств А–Я — аптеки {cn_genitive(cn)} | АптекаА"
    desc = (
        f"Полный каталог зарегистрированных лекарственных препаратов в аптеках {cn_genitive(cn)}. "
        f"Цены, наличие, аналоги. Бесплатный поиск без регистрации."
    )
    canonical = f"{base_url(request)}/{city}/preparaty"
    total = await db.medications.count_documents({"is_canonical": {"$ne": False}})
    body = [
        f"<p>В каталоге <strong>{total:,}</strong> препаратов с актуальной информацией о наличии в аптеках {cn_genitive(cn)}.</p>".replace(",", " "),
        "<h2>Категории препаратов</h2><ul>",
    ]
    for cat in CATEGORIES:
        if cat["slug"] == "other":
            continue
        u = f"{base_url(request)}/{city}/kategorii/{cat['slug']}"
        body.append(f'<li><a href="{u}">{html.escape(cat["title"])}</a></li>')
    body.append("</ul>")
    # Sample popular meds (alphabetical, first 24)
    cursor = db.medications.find(
        {"is_canonical": {"$ne": False}},
        {"_id": 0, "slug": 1, "name": 1, "dosage": 1, "manufacturer": 1},
    ).sort("name", 1).limit(24)
    body.append("<h2>Препараты А–Я</h2><ul>")
    async for m in cursor:
        u = f"{base_url(request)}/{city}/preparaty/{m['slug']}"
        label = " · ".join(filter(None, [m.get("name"), m.get("dosage"), m.get("manufacturer")]))
        body.append(f'<li><a href="{u}">{html.escape(label)}</a></li>')
    body.append("</ul>")
    return HTMLResponse(render_seo_html(
        title=title,
        description=desc,
        canonical_url=canonical,
        h1=f"Каталог лекарств в {cn_genitive(cn)}",
        body_html="\n".join(body),
        breadcrumbs=[
            ("Главная", f"{base_url(request)}/{city}"),
            ("Каталог препаратов", canonical),
        ],
    ))


async def render_pharmacies_index_for_bot(db, city: str, request: Request) -> HTMLResponse:
    cn = city_name(city)
    pharms = [p for p in PHARMACIES if p.get("city") == city]
    title = f"Аптеки {cn_genitive(cn)} — адреса, телефоны, наличие лекарств | АптекаА"
    desc = (
        f"Аптеки-партнёры в {cn}: {len(pharms)} точек. Адреса, телефоны, "
        f"график работы, актуальное наличие препаратов."
    )
    canonical = f"{base_url(request)}/{city}/apteki"
    body = [
        f"<p>В {cn_genitive(cn)} с нашим сервисом сотрудничают <strong>{len(pharms)}</strong> аптек. Выберите ближайшую и проверьте наличие нужного препарата.</p>",
        "<ul>",
    ]
    for p in pharms:
        u = f"{base_url(request)}/{city}/apteki/{p['id']}"
        addr = p.get("address", "")
        label = " — ".join(filter(None, [p.get("name"), addr]))
        body.append(f'<li><a href="{u}">{html.escape(label)}</a></li>')
    body.append("</ul>")
    return HTMLResponse(render_seo_html(
        title=title,
        description=desc,
        canonical_url=canonical,
        h1=f"Аптеки {cn_genitive(cn)}",
        body_html="\n".join(body),
        breadcrumbs=[
            ("Главная", f"{base_url(request)}/{city}"),
            ("Аптеки", canonical),
        ],
    ))


async def render_categories_index_for_bot(db, city: str, request: Request) -> HTMLResponse:
    cn = city_name(city)
    title = f"Категории лекарств — аптеки {cn_genitive(cn)} | АптекаА"
    desc = (
        f"Категории препаратов: от простуды, обезболивающие, витамины, для сердца и сосудов, "
        f"аллергия, для матери и ребёнка. Наличие в аптеках {cn_genitive(cn)}."
    )
    canonical = f"{base_url(request)}/{city}/kategorii"
    body = ["<ul>"]
    for cat in CATEGORIES:
        if cat["slug"] == "other":
            continue
        u = f"{base_url(request)}/{city}/kategorii/{cat['slug']}"
        body.append(f'<li><a href="{u}">{html.escape(cat["title"])}</a></li>')
    body.append("</ul>")
    return HTMLResponse(render_seo_html(
        title=title,
        description=desc,
        canonical_url=canonical,
        h1=f"Категории лекарств в {cn_genitive(cn)}",
        body_html="\n".join(body),
        breadcrumbs=[
            ("Главная", f"{base_url(request)}/{city}"),
            ("Категории", canonical),
        ],
    ))




async def render_contacts_for_bot(db, city: str, request: Request) -> HTMLResponse:
    """SSR for /kontakty (and /msk/kontakty, /spb/kontakty). Returns a
    crawler-friendly page with the same contact data shown in the React
    Contacts page. This is the URL we point Yandex.Webmaster at for the
    site regionality binding — moderator needs to see a real contacts page,
    not the homepage."""
    cn = city_name(city)
    title = "Контакты — АптекаА: телефон, email, юридический адрес"
    desc = (
        "Контакты сервиса АптекаА: телефон горячей линии 8 (800) 700-70-70, "
        "почта info@aptekaa.ru. Юридический адрес: Московская область, г. Фрязино. "
        f"Сервис работает в {cn_prepositional(cn)} и Санкт-Петербурге."
    )
    canonical = f"{base_url(request)}/kontakty"
    body = [
        '<p>АптекаА — информационный сервис по поиску и сравнению цен на лекарства '
        f'в аптеках {cn_genitive(cn)} и Санкт-Петербурга. Свяжитесь с нами удобным '
        'способом:</p>',
        "<h2>Связь с нами</h2>",
        "<dl>",
        "<dt>Горячая линия</dt><dd>8 (800) 700-70-70 — бесплатно по России</dd>",
        "<dt>Общая почта</dt><dd>info@aptekaa.ru — для пользователей сервиса</dd>",
        "<dt>Для аптек-партнёров</dt><dd>partner@aptekaa.ru — подключение и настройка</dd>",
        "<dt>Техподдержка для аптек</dt><dd>support@aptekaa.ru — для уже подключённых партнёров</dd>",
        "<dt>Приём прайс-листов от аптек</dt><dd>price@aptekaa.ru</dd>",
        "<dt>Юридический адрес</dt>"
        "<dd>141195, Московская область, г. Фрязино, ул. Садовая, д. 1, пом. II</dd>",
        "<dt>Юридическое лицо</dt><dd>ООО «Идеал-Фарм»</dd>",
        "<dt>Режим работы поддержки</dt><dd>Пн-Пт, 9:00–18:00 (МСК)</dd>",
        "</dl>",
        "<h2>География работы сервиса</h2>",
        '<p>Сервис АптекаА предоставляет информацию о наличии и ценах препаратов '
        'в аптеках следующих регионов:</p>',
        "<ul>",
        "<li><strong>Москва и Московская область</strong> — основной регион работы сервиса</li>",
        "<li><strong>Санкт-Петербург и Ленинградская область</strong></li>",
        "</ul>",
        '<p>Юридическое лицо ООО «Идеал-Фарм» зарегистрировано в Московской '
        'области и осуществляет деятельность на территории Российской Федерации '
        'в соответствии с действующим законодательством.</p>',
    ]

    import json as _json
    org_schema = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "АптекаА",
        "legalName": "ООО «Идеал-Фарм»",
        "url": f"{base_url(request)}",
        "logo": f"{base_url(request)}/logo.png",
        "email": "info@aptekaa.ru",
        "telephone": "+7-800-700-70-70",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "ул. Садовая, д. 1, пом. II",
            "addressLocality": "Фрязино",
            "addressRegion": "Московская область",
            "postalCode": "141195",
            "addressCountry": "RU",
        },
        "areaServed": [
            {"@type": "AdministrativeArea", "name": "Москва"},
            {"@type": "AdministrativeArea", "name": "Московская область"},
            {"@type": "AdministrativeArea", "name": "Санкт-Петербург"},
        ],
        "contactPoint": [
            {
                "@type": "ContactPoint",
                "telephone": "+7-800-700-70-70",
                "contactType": "customer service",
                "email": "info@aptekaa.ru",
                "areaServed": "RU",
                "availableLanguage": ["Russian"],
            },
            {
                "@type": "ContactPoint",
                "email": "partner@aptekaa.ru",
                "contactType": "sales",
                "areaServed": "RU",
            },
            {
                "@type": "ContactPoint",
                "email": "support@aptekaa.ru",
                "contactType": "technical support",
                "areaServed": "RU",
                "availableLanguage": ["Russian"],
            },
        ],
    }
    return HTMLResponse(render_seo_html(
        title=title,
        description=desc,
        canonical_url=canonical,
        h1="Контакты сервиса АптекаА",
        body_html="\n".join(body),
        schema_jsonld=_json.dumps(org_schema, ensure_ascii=False),
        breadcrumbs=[
            ("Главная", f"{base_url(request)}/{city}"),
            ("Контакты", canonical),
        ],
    ))


async def render_about_for_bot(db, city: str, request: Request) -> HTMLResponse:
    """SSR for /o-servise — about page."""
    cn = city_name(city)
    title = "О сервисе АптекаА — информационный поисковик лекарств в аптеках"
    desc = (
        "АптекаА — бесплатный информационный сервис по поиску лекарственных "
        f"препаратов и сравнению цен в аптеках {cn_genitive(cn)} и Санкт-Петербурга. "
        "Соответствует законодательству РФ, хранение данных в России."
    )
    canonical = f"{base_url(request)}/o-servise"
    body = [
        '<p>АптекаА — информационный сервис по поиску лекарственных препаратов, '
        'биологически активных добавок и медицинских изделий в аптеках России. '
        'Мы помогаем людям быстро находить нужные препараты по лучшей цене и '
        'в ближайших аптеках.</p>',
        "<h2>Возможности сервиса</h2>",
        "<ul>",
        "<li><strong>Быстрый поиск:</strong> находите препарат в десятках аптек за секунды</li>",
        "<li><strong>Сравнение цен:</strong> цены и наличие во всех подключённых аптеках в одном месте</li>",
        "<li><strong>Карта аптек:</strong> найдите ближайшую аптеку с нужным препаратом</li>",
        "<li><strong>Аналоги препаратов:</strong> подберите более доступный аналог</li>",
        "<li><strong>Ежедневное обновление:</strong> цены и наличие обновляются регулярно</li>",
        "</ul>",
        "<h2>Соответствие законодательству</h2>",
        '<p>АптекаА работает в полном соответствии с законодательством Российской '
        'Федерации, включая ФЗ-152 «О персональных данных». Все данные '
        'пользователей хранятся на серверах в России.</p>',
        "<h2>География</h2>",
        f"<p>Основные регионы работы сервиса: <strong>{cn_genitive(cn)} и Московская "
        "область</strong>, <strong>Санкт-Петербург и Ленинградская область</strong>.</p>",
        '<div><p><strong>Важно:</strong> АптекаА не является аптекой и не '
        'осуществляет продажу или бронирование лекарств. Сведения о ценах и '
        'наличии носят справочный характер. Имеются противопоказания, '
        'необходима консультация со специалистом.</p></div>',
    ]
    return HTMLResponse(render_seo_html(
        title=title,
        description=desc,
        canonical_url=canonical,
        h1="О сервисе АптекаА",
        body_html="\n".join(body),
        breadcrumbs=[
            ("Главная", f"{base_url(request)}/{city}"),
            ("О сервисе", canonical),
        ],
    ))


async def render_for_pharmacies_for_bot(db, city: str, request: Request) -> HTMLResponse:
    """SSR for /dlya-aptek — landing for pharmacy partners."""
    cn = city_name(city)
    title = "Для аптек — подключение к сервису АптекаА | Партнёрство"
    desc = (
        "Подключите вашу аптеку к сервису АптекаА бесплатно. Загружайте прайс-листы, "
        f"получайте дополнительных клиентов из {cn_genitive(cn)} и других регионов."
    )
    canonical = f"{base_url(request)}/dlya-aptek"
    body = [
        '<p>Сервис АптекаА предлагает аптекам-партнёрам бесплатный канал '
        'привлечения клиентов через сравнение цен. Тысячи пользователей '
        f"ежедневно ищут лекарства в {cn_prepositional(cn)} и других городах.</p>",
        "<h2>Как это работает</h2>",
        "<ol>",
        "<li>Оставьте заявку — мы свяжемся с вами в течение рабочего дня</li>",
        "<li>Получите токен для загрузки прайс-листа (XLSX/CSV)</li>",
        "<li>Загружайте обновления через web-форму или по email на price@aptekaa.ru</li>",
        "<li>Ваши цены становятся доступны в поиске сервиса АптекаА</li>",
        "</ol>",
        "<h2>Что это даёт аптеке</h2>",
        "<ul>",
        "<li>Дополнительный поток клиентов из поиска</li>",
        "<li>Бесплатное размещение для начинающих партнёров</li>",
        "<li>Прозрачная статистика по показам и переходам</li>",
        "<li>Простая интеграция: достаточно XLSX/CSV-выгрузки</li>",
        "</ul>",
        '<p>Для подключения напишите на <strong>partner@aptekaa.ru</strong> '
        'или оставьте заявку через форму на сайте. Уже подключены и '
        'нужна техническая помощь? Пишите на <strong>support@aptekaa.ru</strong>.</p>',
    ]
    return HTMLResponse(render_seo_html(
        title=title,
        description=desc,
        canonical_url=canonical,
        h1="АптекаА для аптек-партнёров",
        body_html="\n".join(body),
        breadcrumbs=[
            ("Главная", f"{base_url(request)}/{city}"),
            ("Для аптек", canonical),
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
