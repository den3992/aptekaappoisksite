from fastapi import FastAPI, APIRouter, HTTPException, Response, Request
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import logging
import hashlib
import httpx
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone

from emergentintegrations.llm.chat import LlmChat, UserMessage
from voice_data import build_context_text
from api import make_router as make_catalog_router
from api.uploads import make_uploads_router
from api.partners import make_partner_router
from api.seo import (
    make_seo_router,
    is_bot,
    render_med_for_bot,
    render_home_for_bot,
    render_pharmacy_for_bot,
    render_category_for_bot,
    render_catalog_index_for_bot,
    render_pharmacies_index_for_bot,
    render_categories_index_for_bot,
    render_contacts_for_bot,
    render_about_for_bot,
    render_for_pharmacies_for_bot,
    _render_404,
)

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
# Voice / Chat Assistant
# ===========================

VOICE_SYSTEM_PROMPT = (
    "Ты — голосовой помощник сервиса АптекаА, российского агрегатора аптек.\n"
    "Твоя задача — помогать пользователям находить лекарства в аптеках Москвы и Санкт-Петербурга.\n\n"
    "ПРАВИЛА ОБЩЕНИЯ:\n"
    "- Отвечай КОРОТКО (1-3 предложения), на русском языке, в дружелюбном тоне на «Вы».\n"
    "- Ответ будет ОЗВУЧЕН — не используй маркдаун, списки, эмодзи или специальные символы.\n"
    "- Не нужно здороваться повторно — приветствие уже показано на экране. Сразу отвечай по существу.\n"
    "- Если пользователь назвал препарат — назови ориентировочную цену (от X до Y рублей) и предложи 1-2 ближайших аптеки из списка.\n"
    "- Если препарата НЕТ в нашей базе — мягко скажи об этом и предложи поискать аналог.\n"
    "- Если просят медицинский совет, дозировку или диагноз — отказывай: «По вопросам приёма лекарств обратитесь к врачу или фармацевту».\n"
    "- НЕ выдумывай препараты, цены или аптеки, которых нет в контексте ниже.\n"
    "- Если спрашивают про сервис: бесплатный поиск, без бронирования, информационный агрегатор.\n"
    "- Если просто здороваются — коротко поприветствуй и спроси, какое лекарство ищут.\n\n"
    + build_context_text()
)

class VoiceChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()), max_length=64)
    message: str = Field(..., min_length=1, max_length=2000)

class VoiceChatResponse(BaseModel):
    session_id: str
    reply: str

@api_router.post("/voice/chat", response_model=VoiceChatResponse)
async def voice_chat(request: Request, req: VoiceChatRequest):
    _rate_limit(request, "voice_chat", limit=20, per_seconds=60)
    api_key = os.environ.get('EMERGENT_LLM_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="LLM key is not configured")
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message")
    # Reject session_ids that are not safe identifiers — defense in depth
    # against unbounded session-id explosion in the DB.
    sid = req.session_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", sid):
        raise HTTPException(status_code=400, detail="Invalid session_id")

    # Persist user message
    user_doc = {
        "session_id": sid,
        "role": "user",
        "content": req.message.strip(),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    await db.voice_messages.insert_one(user_doc)

    # Load prior history (excluding the just-inserted message we already have in memory? we will rebuild via chat)
    history_docs = await db.voice_messages.find(
        {"session_id": sid}, {"_id": 0}
    ).sort("ts", 1).to_list(100)

    try:
        # Build conversational context (last 6 turns) into the user message
        prior = history_docs[-7:-1]  # exclude current
        context_block = ""
        if prior:
            lines = []
            for msg in prior:
                role = "Пользователь" if msg.get("role") == "user" else "Помощник"
                lines.append(f"{role}: {msg['content']}")
            context_block = "\n\nКОНТЕКСТ ПРЕДЫДУЩЕГО РАЗГОВОРА:\n" + "\n".join(lines) + "\n\n"

        composed = (
            f"{context_block}ТЕКУЩЕЕ СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ: {req.message.strip()}"
        )

        chat = LlmChat(
            api_key=api_key,
            session_id=sid,
            system_message=VOICE_SYSTEM_PROMPT,
        ).with_model("openai", "gpt-4o-mini")

        reply = await chat.send_message(UserMessage(text=composed))
        if not isinstance(reply, str):
            reply = str(reply)
    except Exception:
        logger.exception("LLM error")
        # Don't leak stack traces / model details to clients in prod
        raise HTTPException(status_code=502, detail="Сервис временно недоступен")

    # Persist bot reply
    await db.voice_messages.insert_one({
        "session_id": sid,
        "role": "assistant",
        "content": reply,
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    return VoiceChatResponse(session_id=sid, reply=reply)


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

# SEO endpoints (robots.txt, sitemap*.xml). Mounted under /api/ because the
# k8s ingress only routes /api/* to the backend. Production CF rewrite rules:
#   aptekaa.ru/robots.txt        → backend /api/seo/robots.txt
#   aptekaa.ru/sitemap.xml       → backend /api/seo/sitemap.xml
#   aptekaa.ru/sitemap_*.xml     → backend /api/seo/sitemap_*.xml
#   aptekaa.ru/<path>  (bot UA)  → backend /api/seo/render?path=<path>
app.include_router(make_seo_router(db), prefix="/api/seo")


@app.get("/api/seo/render", response_class=HTMLResponse)
async def seo_render(path: str, request: Request):
    """Single entry point for crawler-rendered HTML.

    The CF Worker / nginx detects bot User-Agent and forwards the original
    request path to /api/seo/render?path=<original>.

    For preview we accept a `?path=...&force=1` query so we can debug.
    """
    # Parse path: /<city>/<section>/<slug?>
    p = (path or "/").lstrip("/")
    parts = [x for x in p.split("/") if x]
    if not parts:
        return await render_home_for_bot(db, "msk", request)

    # Static pages allowed at top level (no city prefix): /kontakty, /o-servise, /dlya-aptek
    STATIC_PAGES = {"kontakty", "o-servise", "dlya-aptek"}

    if parts[0] in ("msk", "spb"):
        city = parts[0]
        rest = parts[1:]
    elif parts[0] in STATIC_PAGES and len(parts) == 1:
        city = "msk"
        rest = parts  # let the section dispatcher handle it
    else:
        # Unknown top-level segment (not a city, not a known static page) → 404
        return HTMLResponse(_render_404(request, "msk"), status_code=404)

    if not rest:
        return await render_home_for_bot(db, city, request)
    section = rest[0]
    if section == "preparaty" and len(rest) >= 2:
        return await render_med_for_bot(db, city, rest[1], request)
    if section == "preparaty" and len(rest) == 1:
        return await render_catalog_index_for_bot(db, city, request)
    if section == "apteki" and len(rest) >= 2:
        return await render_pharmacy_for_bot(db, city, rest[1], request)
    if section == "apteki" and len(rest) == 1:
        return await render_pharmacies_index_for_bot(db, city, request)
    if section == "kategorii" and len(rest) >= 2:
        return await render_category_for_bot(db, city, rest[1], request)
    if section == "kategorii" and len(rest) == 1:
        return await render_categories_index_for_bot(db, city, request)
    # Static pages: /kontakty, /o-servise, /dlya-aptek (with or without city prefix).
    # These have their own SSR templates so search bots see unique title/h1/content
    # — critical for Yandex.Webmaster regionality verification (contacts page).
    if section == "kontakty" and len(rest) == 1:
        return await render_contacts_for_bot(db, city, request)
    if section == "o-servise" and len(rest) == 1:
        return await render_about_for_bot(db, city, request)
    if section == "dlya-aptek" and len(rest) == 1:
        return await render_for_pharmacies_for_bot(db, city, request)

    # Unknown route → proper 404 with status_code=404 (no soft-404 cloaking)
    return HTMLResponse(_render_404(request, city), status_code=404)


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
    except Exception as e:
        logger.warning(f"Index creation skipped: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()