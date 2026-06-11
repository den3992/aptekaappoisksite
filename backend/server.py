from fastapi import FastAPI, APIRouter, HTTPException, Response, Request
from fastapi.responses import StreamingResponse, RedirectResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import hashlib
import httpx
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone

from api import make_router as make_catalog_router
from api.uploads import make_uploads_router
from api.partners import make_partner_router
from api.seo import make_seo_router
from api.lead import make_lead_router
from api.reviews import make_reviews_router

import time as _time
from collections import defaultdict as _defaultdict
_RL_BUCKETS = _defaultdict(list)


def _rate_limit(request, key: str, limit: int, per_seconds: int):
    ip = request.client.host if request.client else "anon"
    bkey = f"{key}:{ip}"
    now = _time.time()
    bucket = _RL_BUCKETS[bkey]
    cutoff = now - per_seconds
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= limit:
        raise HTTPException(429, "Слишком много запросов. Попробуйте позже.")
    bucket.append(now)


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Security headers are set at the nginx edge (deploy/nginx/edge-ssl.conf).

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Ignore MongoDB's _id field
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    
    # Convert to dict and serialize datetime to ISO string for MongoDB
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    # Exclude MongoDB's _id field from the query results
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    # Convert ISO string timestamps back to datetime objects
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks

# ===========================
# Yandex SpeechKit TTS
# ===========================

YANDEX_TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
SUPPORTED_VOICES = {"alena", "jane", "omazh", "zahar", "ermil", "filipp", "madirus"}
SUPPORTED_EMOTIONS = {"neutral", "good", "evil"}


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = Field(default="alena")
    emotion: str = Field(default="good")  # warm/friendly default
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


def _tts_cache_key(text: str, voice: str, emotion: str, speed: float) -> str:
    raw = f"{voice}|{emotion}|{speed:.2f}|{text.strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@api_router.post("/voice/tts")
async def voice_tts(request: Request, req: TTSRequest):
    _rate_limit(request, "voice_tts", limit=30, per_seconds=60)
    api_key = os.environ.get("YANDEX_API_KEY")
    folder_id = os.environ.get("YANDEX_FOLDER_ID")
    if not api_key or not folder_id:
        raise HTTPException(status_code=500, detail="Yandex SpeechKit is not configured")

    voice = req.voice if req.voice in SUPPORTED_VOICES else "alena"
    emotion = req.emotion if req.emotion in SUPPORTED_EMOTIONS else "good"
    speed = max(0.5, min(2.0, req.speed))
    text = req.text.strip()

    cache_key = _tts_cache_key(text, voice, emotion, speed)

    # Check cache
    cached = await db.tts_cache.find_one({"_id": cache_key}, {"_id": 0, "audio_b64": 1, "format": 1})
    if cached and cached.get("audio_b64"):
        import base64
        audio_bytes = base64.b64decode(cached["audio_b64"])
        media_type = "audio/ogg" if cached.get("format") == "oggopus" else "audio/mpeg"
        return Response(content=audio_bytes, media_type=media_type, headers={"X-Cache": "HIT"})

    # Call Yandex SpeechKit
    data = {
        "text": text,
        "voice": voice,
        "emotion": emotion,
        "speed": str(speed),
        "format": "oggopus",
        "lang": "ru-RU",
        "folderId": folder_id,
    }
    headers = {"Authorization": f"Api-Key {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(YANDEX_TTS_URL, data=data, headers=headers)
            if resp.status_code != 200:
                logger.error(f"Yandex TTS error {resp.status_code}: {resp.text[:300]}")
                raise HTTPException(status_code=502, detail="Сервис озвучки временно недоступен")
            audio_bytes = resp.content
    except httpx.HTTPError:
        logger.exception("TTS request failed")
        raise HTTPException(status_code=502, detail="Сервис озвучки временно недоступен")

    if not audio_bytes:
        raise HTTPException(status_code=502, detail="Empty audio from TTS provider")

    # Save cache (ignore errors silently)
    try:
        import base64
        await db.tts_cache.insert_one({
            "_id": cache_key,
            "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
            "format": "oggopus",
            "voice": voice,
            "emotion": emotion,
            "speed": speed,
            "text_preview": text[:200],
            "size": len(audio_bytes),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    return Response(content=audio_bytes, media_type="audio/ogg", headers={"X-Cache": "MISS"})


# Include the router in the main app
app.include_router(api_router)

# Catalog API (search, medications, pharmacies, categories) under /api/*
app.include_router(make_catalog_router(db), prefix="/api")

# Pharmacy uploads (HTTP web upload). Hidden route — partners get a token URL,
# nothing on the main site links to /partner-upload.
app.include_router(make_uploads_router(db), prefix="/api/upload")

# Partner request form + admin approval flow.
app.include_router(make_partner_router(db), prefix="/api")

# Заявка на поиск лекарства — письмо на info@aptekaa.ru, БЕЗ записи в БД.
app.include_router(make_lead_router(), prefix="/api")

# Отзывы о препаратах (UGC) — оценка + текст, публикация сразу, анти-спам.
app.include_router(make_reviews_router(db), prefix="/api")

# SEO endpoints — теперь только robots.txt + sitemap*.xml.
# После Phase 8 cutover Next.js SSR'ит HTML нативно для всех User-Agent'ов,
# bot-rewrite в edge nginx удалён, эндпоинт /api/seo/render тоже удалён.
#   aptekaa.ru/robots.txt    → backend /api/seo/robots.txt
#   aptekaa.ru/sitemap*.xml  → backend /api/seo/sitemap*.xml
app.include_router(make_seo_router(db), prefix="/api/seo")


app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=[o.strip() for o in os.environ.get('CORS_ORIGINS', '*').split(',') if o.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Token"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def ensure_indexes():
    """Create indexes once on startup (idempotent). Avoids per-request overhead."""
    try:
        await db.prices.create_index([("pharmacy_id", 1), ("gtin", 1)], unique=True)
        await db.prices.create_index([("slug", 1)])
        await db.unmatched_items.create_index([("upload_id", 1)])
        await db.unmatched_items.create_index([("pharmacy_id", 1), ("gtin", 1)])
        await db.pharmacy_uploads.create_index([("pharmacy_id", 1), ("uploaded_at", -1)])
        # Отзывы: список опубликованных по препарату (новые сверху) + анти-спам.
        await db.reviews.create_index([("slug", 1), ("status", 1), ("created_at", -1)])
        await db.reviews.create_index([("ip_hash", 1), ("created_at", -1)])
        await db.reviews.create_index([("id", 1)], unique=True)
    except Exception as e:
        logger.warning(f"Index creation skipped: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()