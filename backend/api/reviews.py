"""
Отзывы пользователей о препаратах (UGC).

На странице препарата посетитель оставляет отзыв: оценка 1–5 + текст (+ до 3 фото).
НИКНЕЙМ НЕ СОБИРАЕМ — показываем только дату, оценку, текст и фото. Это сводит
сбор ПД почти к нулю (152-ФЗ): в БД нет имени/контактов, только хеш IP (анти-спам).

Публикация:
- отзыв БЕЗ фото → публикуется сразу (status="published"), если прошёл анти-спам;
- отзыв С ФОТО → всегда уходит в премодерацию (status="hold"): изображения
  нельзя надёжно проверить автоматикой, поэтому их вычитывает админ в панели.

Анти-спам (т.к. текст публикуется сразу): honeypot (`website`), тайминг (`ts`),
DB-rate-limit по хешу IP (N/час + 1/препарат/сутки), вырезание ссылок/контактов,
стоп-лист + опасные медсоветы → hold. Поле status позволяет позже включить
премодерацию и для текста сменой дефолта.

Фото: принимаем любой формат (вкл. iPhone HEIC), на сервере пересжимаем в WebP
(ресайз ≤1280px, q80) — маленький вес + срез EXIF/GPS + обезвреживание файла.
Отдаются edge-nginx по /img/reviews/<id>.webp (та же live-папка, что и фото
препаратов: ../next/public/img смонтирована в edge).

Модерация — в админ-панели (/admin), эндпоинты под /api/admin/reviews* защищены
verify_admin (JWT-логин или X-Admin-Token), как партнёрский флоу.
"""
from __future__ import annotations

import io
import os
import re
import time
import uuid
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, Form, File, UploadFile, Query, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from security import verify_admin

log = logging.getLogger("reviews")

# Pillow + HEIC (iPhone). register опционально — если плагина нет, HEIC просто
# не примем, остальные форматы работают.
from PIL import Image, ImageOps
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

_IP_SALT = (os.environ.get("REVIEWS_IP_SALT") or os.environ.get("ADMIN_TOKEN") or "aptekaa-reviews").encode()

# Куда писать фото. Папка смонтирована и в edge (../next/public/img) → URL /img/reviews/.
PHOTO_DIR = os.environ.get("REVIEW_PHOTO_DIR", "/app/review_photos")
PHOTO_URL_PREFIX = "/img/reviews"

MIN_TEXT = 20
MAX_TEXT = 2000
PER_HOUR_LIMIT = 5
PER_DRUG_PER_DAY = 1
MIN_FILL_SECONDS = 3
MAX_FORM_AGE_SECONDS = 24 * 3600

MAX_PHOTOS = 3
MAX_PHOTO_BYTES = 5 * 1024 * 1024     # 5 МБ на исходный файл
MAX_DIM = 1280                         # ресайз по длинной стороне
WEBP_QUALITY = 80

_LINK_RE = re.compile(
    r"(https?://|www\.|\b[\w.-]+\.(?:ru|com|net|org|рф|biz|info|online|shop)\b|@[\w.]+|\bt\.me\b|"
    r"\+?\d[\d\s().-]{8,}\d)",
    re.IGNORECASE,
)
_STOP_WORDS = [
    "казино", "ставки", "porn", "viagra", "займ", "кредит наличными",
    "купить диплом", "накрутка", "продвижение сайта", "промокод",
    "увеличить член", "заработок в интернете",
]
_DANGER_RE = re.compile(
    r"(колол[аи]?\s+себе|вколол|внутривенно\s+\d|по\s+\d+\s*ампул|"
    r"превыси[лт]ь?\s+дозу|удвоить\s+дозу|смертельн)",
    re.IGNORECASE,
)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _client_ip(request: Request) -> str:
    xri = request.headers.get("x-real-ip", "").strip()
    if xri:
        return xri
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        last = xff.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "anon"


def _ip_hash(ip: str) -> str:
    return hashlib.sha256(_IP_SALT + ip.encode()).hexdigest()


def _classify(text: str) -> str:
    low = text.lower()
    if any(w in low for w in _STOP_WORDS):
        return "hold"
    if _DANGER_RE.search(text):
        return "hold"
    return "published"


def _clean_text(v: str) -> str:
    v = _CTRL_RE.sub("", v or "").strip()
    v = re.sub(r"[ \t]{2,}", " ", v)
    v = re.sub(r"\n{3,}", "\n\n", v)
    return v


def _process_photo(raw: bytes) -> bytes:
    """Любой формат → WebP, ресайз ≤MAX_DIM, срез метаданных. Бросает на мусоре."""
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)          # учесть ориентацию телефона
    if img.mode in ("RGBA", "LA", "P"):
        # подложка белая, чтобы прозрачность не стала чёрной
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=WEBP_QUALITY, method=6)
    return out.getvalue()


def make_reviews_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter()
    coll = db.reviews
    os.makedirs(PHOTO_DIR, exist_ok=True)

    async def _agg(slug: str, page: int = 1, page_size: int = 10):
        skip = (page - 1) * page_size
        pipeline = [
            {"$match": {"slug": slug, "status": "published"}},
            {"$facet": {
                "stats": [{"$group": {"_id": None, "count": {"$sum": 1}, "avg": {"$avg": "$rating"}}}],
                "dist": [{"$group": {"_id": "$rating", "n": {"$sum": 1}}}],
                "items": [
                    {"$sort": {"created_at": -1}},
                    {"$skip": skip},
                    {"$limit": page_size},
                    {"$project": {"_id": 0, "id": 1, "rating": 1, "text": 1, "photos": 1, "created_at": 1}},
                ],
            }},
        ]
        doc = await coll.aggregate(pipeline).to_list(1)
        doc = doc[0] if doc else {"stats": [], "dist": [], "items": []}
        stats = doc["stats"][0] if doc["stats"] else {"count": 0, "avg": 0}
        count = int(stats.get("count", 0))
        avg = round(float(stats.get("avg") or 0), 1)
        dist = {str(i): 0 for i in range(1, 6)}
        for d in doc["dist"]:
            dist[str(d["_id"])] = d["n"]
        items = []
        for it in doc["items"]:
            ca = it.get("created_at")
            items.append({
                "id": it["id"], "rating": it["rating"], "text": it["text"],
                "photos": it.get("photos") or [],
                "created_at": ca.isoformat() if hasattr(ca, "isoformat") else ca,
            })
        return {
            "count": count, "avg": avg, "dist": dist, "items": items,
            "page": page, "page_size": page_size, "has_more": skip + len(items) < count,
        }

    @router.post("/reviews")
    async def create_review(
        request: Request,
        slug: str = Form(...),
        rating: int = Form(...),
        text: str = Form(...),
        consent: bool = Form(False),
        website: str = Form(""),
        ts: Optional[int] = Form(None),
        photos: List[UploadFile] = File(default=[]),
    ):
        # Honeypot — тихий «успех».
        if website:
            return {"ok": True, "status": "published"}

        # Тайминг.
        if ts is not None:
            age = (time.time() * 1000 - ts) / 1000.0
            if age < MIN_FILL_SECONDS or age > MAX_FORM_AGE_SECONDS:
                return {"ok": True, "status": "published"}

        if not consent:
            raise HTTPException(400, "Требуется согласие на обработку данных")
        if rating < 1 or rating > 5:
            raise HTTPException(400, "Оценка должна быть от 1 до 5")

        text = _clean_text(text)
        if len(text) < MIN_TEXT:
            raise HTTPException(400, f"Отзыв слишком короткий (минимум {MIN_TEXT} символов)")
        if len(text) > MAX_TEXT:
            raise HTTPException(400, "Отзыв слишком длинный")
        if _LINK_RE.search(text):
            raise HTTPException(400, "Уберите ссылки и контактные данные из текста отзыва")

        med = await db.medications.find_one({"slug": slug}, {"_id": 1, "id": 1})
        if not med:
            raise HTTPException(404, "Препарат не найден")

        ip = _client_ip(request)
        iph = _ip_hash(ip)
        now = datetime.now(timezone.utc)

        hour_ago = now - timedelta(hours=1)
        if await coll.count_documents({"ip_hash": iph, "created_at": {"$gte": hour_ago}}) >= PER_HOUR_LIMIT:
            raise HTTPException(429, "Слишком много отзывов. Попробуйте позже.")
        day_ago = now - timedelta(days=1)
        if await coll.count_documents({"ip_hash": iph, "slug": slug, "created_at": {"$gte": day_ago}}) >= PER_DRUG_PER_DAY:
            raise HTTPException(429, "Вы уже оставляли отзыв на этот препарат сегодня.")

        text_hash = hashlib.sha256(text.lower().encode()).hexdigest()
        if await coll.find_one({"ip_hash": iph, "text_hash": text_hash, "created_at": {"$gte": day_ago}}):
            raise HTTPException(429, "Похожий отзыв уже отправлен.")

        # Фото: принимаем любой формат → WebP. Любое фото → премодерация (hold).
        real_photos = [p for p in (photos or []) if p and p.filename]
        if len(real_photos) > MAX_PHOTOS:
            raise HTTPException(400, f"Можно прикрепить не более {MAX_PHOTOS} фото")
        saved_urls: List[str] = []
        for up in real_photos:
            raw = await up.read()
            if not raw:
                continue
            if len(raw) > MAX_PHOTO_BYTES:
                raise HTTPException(400, "Фото слишком большое (до 5 МБ)")
            try:
                webp = _process_photo(raw)
            except Exception:
                raise HTTPException(400, "Не удалось обработать изображение. Загрузите фото в обычном формате.")
            fname = f"{uuid.uuid4().hex}.webp"
            with open(os.path.join(PHOTO_DIR, fname), "wb") as f:
                f.write(webp)
            saved_urls.append(f"{PHOTO_URL_PREFIX}/{fname}")

        status = "hold" if saved_urls else _classify(text)
        doc = {
            "id": uuid.uuid4().hex,
            "slug": slug,
            "medication_id": med.get("id"),
            "rating": rating,
            "text": text,
            "photos": saved_urls,
            "status": status,
            "ip_hash": iph,
            "text_hash": text_hash,
            "created_at": now,
        }
        await coll.insert_one(doc)
        return {"ok": True, "status": status}

    @router.get("/reviews/{slug}")
    async def list_reviews(slug: str, page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=50)):
        return await _agg(slug, page=page, page_size=page_size)

    # ---------- Модерация (админ-панель) ----------

    @router.get("/admin/reviews")
    async def admin_list(
        _: None = Depends(verify_admin),
        status: str = Query("hold"),
        limit: int = Query(100, ge=1, le=500),
    ):
        cursor = coll.find({"status": status}, {"_id": 0, "ip_hash": 0, "text_hash": 0}).sort("created_at", -1).limit(limit)
        out = []
        async for d in cursor:
            ca = d.get("created_at")
            if hasattr(ca, "isoformat"):
                d["created_at"] = ca.isoformat()
            out.append(d)
        # Сколько ждёт модерации — для бейджа в панели.
        pending = await coll.count_documents({"status": "hold"})
        return {"items": out, "pending": pending}

    @router.post("/admin/reviews/{rid}/approve")
    async def admin_approve(rid: str, _: None = Depends(verify_admin)):
        res = await coll.update_one({"id": rid}, {"$set": {"status": "published"}})
        if not res.matched_count:
            raise HTTPException(404, "Отзыв не найден")
        return {"ok": True}

    @router.post("/admin/reviews/{rid}/reject")
    async def admin_reject(rid: str, _: None = Depends(verify_admin)):
        doc = await coll.find_one({"id": rid}, {"_id": 0, "photos": 1})
        # Чистим файлы фото отклонённого отзыва.
        for url in (doc or {}).get("photos") or []:
            try:
                os.remove(os.path.join(PHOTO_DIR, os.path.basename(url)))
            except OSError:
                pass
        res = await coll.update_one({"id": rid}, {"$set": {"status": "rejected"}})
        if not res.matched_count:
            raise HTTPException(404, "Отзыв не найден")
        return {"ok": True}

    @router.post("/admin/reviews/{rid}/delete")
    async def admin_delete(rid: str, _: None = Depends(verify_admin)):
        res = await coll.update_one({"id": rid}, {"$set": {"status": "deleted"}})
        return {"ok": True, "modified": res.modified_count}

    return router
