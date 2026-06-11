"""
Отзывы пользователей о препаратах (UGC).

На странице препарата посетитель оставляет отзыв: оценка 1–5 + текст.
НИКНЕЙМ НЕ СОБИРАЕМ — показываем только дату и оценку. Это сводит сбор ПД
почти к нулю (152-ФЗ): в БД нет имени/контактов, только хеш IP для анти-спама.

Отзывы публикуются СРАЗУ (без премодерации, решение владельца). Защита:
- honeypot (`website`) — бот заполнит → тихий «успех», ничего не пишем;
- тайминг — сабмит раньше 3 сек после открытия формы = бот;
- rate-limit по хешу IP (в БД): N/час + не более 1 отзыва на (IP, препарат)/сутки;
- вырезание ссылок/контактов из текста — убивает SEO-спам;
- стоп-лист (спам/мат/опасные медсоветы) → отзыв уходит в `hold` (не публичен).
Чистые отзывы → status="published". Поле status позволяет позже включить
премодерацию одним изменением дефолта.

Удаление уже опубликованного — POST /api/reviews/admin/delete с заголовком
X-Admin-Token (тот же ADMIN_TOKEN, что у остального админ-флоу). Это не очередь
модерации, а «кнопка снести плохое», если что-то проскочило.
"""
from __future__ import annotations

import os
import re
import time
import uuid
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, Body, Header, Query
from pydantic import BaseModel, Field, field_validator
from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger("reviews")

# Соль для хеша IP и токен админ-удаления берём из уже существующего ADMIN_TOKEN
# (прокинут в backend через docker-compose) — отдельный секрет не заводим.
_ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
_IP_SALT = (os.environ.get("REVIEWS_IP_SALT") or _ADMIN_TOKEN or "aptekaa-reviews").encode()

MIN_TEXT = 20
MAX_TEXT = 2000
PER_HOUR_LIMIT = 5          # отзывов/час с одного IP
PER_DRUG_PER_DAY = 1        # не более 1 отзыва на (IP, препарат) в сутки
MIN_FILL_SECONDS = 3        # быстрее — бот
MAX_FORM_AGE_SECONDS = 24 * 3600

# Ссылки / контакты в тексте → SEO-спам. Наличие → реджект.
_LINK_RE = re.compile(
    r"(https?://|www\.|\b[\w.-]+\.(?:ru|com|net|org|рф|biz|info|online|shop)\b|@[\w.]+|\bt\.me\b|"
    r"\+?\d[\d\s().-]{8,}\d)",
    re.IGNORECASE,
)
# Грубый стоп-лист: спам-маркеры + опасные «медсоветы» дозировки. Срабатывание
# → отзыв в hold (не публикуется), чтобы не давать живьём вредные указания.
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
    # Как в lead.py: доверяем X-Real-IP (его ставит наш edge), иначе последний
    # хоп XFF (добавлен доверенным прокси), иначе client.host.
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
    """published | hold — куда направить отзыв по содержимому."""
    low = text.lower()
    if any(w in low for w in _STOP_WORDS):
        return "hold"
    if _DANGER_RE.search(text):
        return "hold"
    return "published"


class ReviewIn(BaseModel):
    slug: str = Field(..., min_length=1, max_length=300)
    rating: int = Field(..., ge=1, le=5)
    text: str = Field(..., min_length=MIN_TEXT, max_length=MAX_TEXT)
    consent: bool = Field(...)
    # honeypot — человек не видит; заполнено → бот.
    website: Optional[str] = Field(None, max_length=200)
    # время рендера формы (мс эпохи) — для тайминг-проверки.
    ts: Optional[int] = Field(None)

    @field_validator("slug", "text", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("text")
    @classmethod
    def _clean_text(cls, v):
        v = _CTRL_RE.sub("", v or "").strip()
        # схлопываем повторяющиеся пробелы/переводы строк
        v = re.sub(r"[ \t]{2,}", " ", v)
        v = re.sub(r"\n{3,}", "\n\n", v)
        if len(v) < MIN_TEXT:
            raise ValueError(f"Отзыв слишком короткий (минимум {MIN_TEXT} символов)")
        return v


def make_reviews_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter()
    coll = db.reviews

    async def _agg(slug: str, page: int = 1, page_size: int = 10):
        """Агрегат + страница опубликованных отзывов по препарату."""
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
                    {"$project": {"_id": 0, "id": 1, "rating": 1, "text": 1, "created_at": 1}},
                ],
            }},
        ]
        doc = (await coll.aggregate(pipeline).to_list(1))
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
                "id": it["id"],
                "rating": it["rating"],
                "text": it["text"],
                "created_at": ca.isoformat() if hasattr(ca, "isoformat") else ca,
            })
        return {
            "count": count, "avg": avg, "dist": dist, "items": items,
            "page": page, "page_size": page_size, "has_more": skip + len(items) < count,
        }

    @router.post("/reviews")
    async def create_review(request: Request, payload: ReviewIn = Body(...)):
        # Honeypot — тихий «успех», ничего не пишем.
        if payload.website:
            return {"ok": True, "status": "published"}

        # Тайминг: слишком быстрый сабмит = бот.
        if payload.ts is not None:
            now_ms = time.time() * 1000
            age = (now_ms - payload.ts) / 1000.0
            if age < MIN_FILL_SECONDS or age > MAX_FORM_AGE_SECONDS:
                return {"ok": True, "status": "published"}  # тихо игнорим бота

        if not payload.consent:
            raise HTTPException(400, "Требуется согласие на обработку данных")

        # Ссылки/контакты → SEO-спам, не принимаем.
        if _LINK_RE.search(payload.text):
            raise HTTPException(400, "Уберите ссылки и контактные данные из текста отзыва")

        # Препарат должен существовать (иначе мусорный slug).
        med = await db.medications.find_one({"slug": payload.slug}, {"_id": 1, "id": 1})
        if not med:
            raise HTTPException(404, "Препарат не найден")

        ip = _client_ip(request)
        iph = _ip_hash(ip)
        now = datetime.now(timezone.utc)

        # Rate-limit по БД (переживает рестарт воркеров).
        hour_ago = now - timedelta(hours=1)
        per_hour = await coll.count_documents({"ip_hash": iph, "created_at": {"$gte": hour_ago}})
        if per_hour >= PER_HOUR_LIMIT:
            raise HTTPException(429, "Слишком много отзывов. Попробуйте позже.")

        day_ago = now - timedelta(days=1)
        per_drug = await coll.count_documents(
            {"ip_hash": iph, "slug": payload.slug, "created_at": {"$gte": day_ago}}
        )
        if per_drug >= PER_DRUG_PER_DAY:
            raise HTTPException(429, "Вы уже оставляли отзыв на этот препарат сегодня.")

        # Дедуп точного копипаста (тот же текст недавно с того же IP).
        text_hash = hashlib.sha256(payload.text.lower().encode()).hexdigest()
        dup = await coll.find_one(
            {"ip_hash": iph, "text_hash": text_hash, "created_at": {"$gte": day_ago}}
        )
        if dup:
            raise HTTPException(429, "Похожий отзыв уже отправлен.")

        status = _classify(payload.text)
        doc = {
            "id": uuid.uuid4().hex,
            "slug": payload.slug,
            "medication_id": med.get("id"),
            "rating": payload.rating,
            "text": payload.text,
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

    @router.post("/reviews/admin/delete")
    async def admin_delete(
        payload: dict = Body(...),
        x_admin_token: str = Header(None, alias="X-Admin-Token"),
    ):
        if not _ADMIN_TOKEN or x_admin_token != _ADMIN_TOKEN:
            raise HTTPException(403, "Forbidden")
        rid = (payload or {}).get("id")
        if not rid:
            raise HTTPException(400, "id required")
        res = await coll.update_one({"id": rid}, {"$set": {"status": "deleted"}})
        return {"ok": True, "modified": res.modified_count}

    @router.get("/reviews/admin/recent")
    async def admin_recent(
        x_admin_token: str = Header(None, alias="X-Admin-Token"),
        limit: int = Query(50, ge=1, le=200),
        status: Optional[str] = Query(None),
    ):
        if not _ADMIN_TOKEN or x_admin_token != _ADMIN_TOKEN:
            raise HTTPException(403, "Forbidden")
        flt = {"status": status} if status else {}
        cursor = coll.find(flt, {"_id": 0, "ip_hash": 0, "text_hash": 0}).sort("created_at", -1).limit(limit)
        out = []
        async for d in cursor:
            ca = d.get("created_at")
            if hasattr(ca, "isoformat"):
                d["created_at"] = ca.isoformat()
            out.append(d)
        return {"items": out}

    return router
