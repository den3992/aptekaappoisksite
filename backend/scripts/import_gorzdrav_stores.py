"""Импортирует список аптек Горздрав (регион MOS) в MongoDB."""
import os, sys, asyncio, logging
from pathlib import Path
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "aptekaa")

GZ_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Flex-Locale": "country=RU;bs=gz.ru",
    "Flex-Region": "region=MOS",
    "Flex-App": "WEB",
}

def fmt_schedule(sched):
    if not sched:
        return ""
    if sched.get("is24Hour"):
        return "Круглосуточно"
    days = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    labels = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    times = set()
    for d in days:
        day = sched.get(d, {})
        if day.get("isWorkingDay"):
            times.add(f"{day.get('workFrom','')[:5]}–{day.get('workTo','')[:5]}")
    if len(times) == 1:
        return f"Ежедневно {times.pop()}"
    return sched.get("name", "")

async def main():
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    async with httpx.AsyncClient(headers=GZ_HEADERS, timeout=20) as c:
        r = await c.get("https://gorzdrav.org/api/v1/dictionary-data/stores")
        r.raise_for_status()
        stores = r.json()

    log.info(f"Получено аптек: {len(stores)}")

    # Фильтруем: только активные и регион MOS
    mos_stores = [
        s for s in stores
        if s.get("activity")
        and "MOS" in s.get("storeInfo", {}).get("regionIds", [])
    ]
    log.info(f"Аптек в регионе MOS (активных): {len(mos_stores)}")

    # Стабильный append-only idx: существующим аптекам сохраняем idx,
    # новым выдаём следующий по порядку. store_bitmap в prices_real
    # позиционно завязан на idx — переиспользовать слоты нельзя.
    existing: dict[str, int] = {}
    async for d in db.gorzdrav_stores.find({}, {"_id": 0, "store_id": 1, "idx": 1}):
        existing[d["store_id"]] = d.get("idx")
    next_idx = max([i for i in existing.values() if i is not None], default=-1) + 1

    seen: set[str] = set()
    new_count = 0
    for s in mos_stores:
        sid = s["storeId"]
        seen.add(sid)
        info = s.get("storeInfo", {})
        sched = info.get("schedule", {})
        idx = existing.get(sid)
        if idx is None:
            idx = next_idx
            next_idx += 1
            new_count += 1
        await db.gorzdrav_stores.update_one(
            {"store_id": sid},
            {"$set": {
                "store_id": sid,
                "idx": idx,
                "name": info.get("brand", {}).get("id") == 1 and "36,6" or "Горздрав",
                "full_name": s.get("name", ""),
                "lat": info.get("latitude"),
                "lng": info.get("longitude"),
                "address": info.get("address", ""),
                "phone": info.get("phone", ""),
                "hours": fmt_schedule(sched),
                "is_24h": sched.get("is24Hour", False),
                "city": "msk",
                "source": "gorzdrav",
                "active": True,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

    # Аптеки, пропавшие из выдачи API — деактивируем, но idx-слот сохраняем.
    deact = await db.gorzdrav_stores.update_many(
        {"store_id": {"$nin": list(seen)}},
        {"$set": {"active": False}},
    )
    await db.gorzdrav_stores.create_index("store_id", unique=True)
    await db.gorzdrav_stores.create_index([("lat", 1), ("lng", 1)])
    await db.gorzdrav_stores.create_index("idx")
    log.info(
        f"Обновлено аптек: {len(seen)} (новых: {new_count}), "
        f"деактивировано: {deact.modified_count}"
    )

    client_db.close()

if __name__ == "__main__":
    asyncio.run(main())
