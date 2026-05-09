from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone

from emergentintegrations.llm.chat import LlmChat, UserMessage
from voice_data import build_context_text


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

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
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str

class VoiceChatResponse(BaseModel):
    session_id: str
    reply: str

@api_router.post("/voice/chat", response_model=VoiceChatResponse)
async def voice_chat(req: VoiceChatRequest):
    api_key = os.environ.get('EMERGENT_LLM_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="LLM key is not configured")
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message")

    # Persist user message
    user_doc = {
        "session_id": req.session_id,
        "role": "user",
        "content": req.message.strip(),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    await db.voice_messages.insert_one(user_doc)

    # Load prior history (excluding the just-inserted message we already have in memory? we will rebuild via chat)
    history_docs = await db.voice_messages.find(
        {"session_id": req.session_id}, {"_id": 0}
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
            session_id=req.session_id,
            system_message=VOICE_SYSTEM_PROMPT,
        ).with_model("openai", "gpt-4o-mini")

        reply = await chat.send_message(UserMessage(text=composed))
        if not isinstance(reply, str):
            reply = str(reply)
    except Exception as e:
        logger.exception("LLM error")
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    # Persist bot reply
    await db.voice_messages.insert_one({
        "session_id": req.session_id,
        "role": "assistant",
        "content": reply,
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    return VoiceChatResponse(session_id=req.session_id, reply=reply)


# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()