"""Импортирует список аптек Горздрав в MongoDB.

Регионы: MOS (Москва) → city=msk, SPE (Санкт-Петербург) → city=spb.
Один глобальный append-only idx для всех аптек — на нём позиционно
завязан store_bitmap в prices_real, переиспользовать слоты нельзя.
"""
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

GZ_HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Flex-Locale": "country=RU;bs=gz.ru",
    "Flex-App": "WEB",
}

# Регион Горздрав → city-id в нашем приложении.
REGIONS = [
    ("MOS", "msk"),
    ("SPE", "spb"),
]


def fmt_schedule(sched):
    if not sched:
        return ""
    if sched.get("is24Hour"):
        return "Круглосуточно"
    days = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    times = set()
    for d in days:
        day = sched.get(d, {})
        if day.get("isWorkingDay"):
            times.add(f"{day.get('workFrom','')[:5]}–{day.get('workTo','')[:5]}")
    if len(times) == 1:
        return f"Ежедневно {times.pop()}"
    return sched.get("name", "")


async def fetch_region(region: str) -> list[dict]:
    headers = {**GZ_HEADERS_BASE, "Flex-Region": f"region={region}"}
    async with httpx.AsyncClient(headers=headers, timeout=20) as c:
        r = await c.get("https://gorzdrav.org/api/v1/dictionary-data/stores")
        r.raise_for_status()
        data = r.json()
    return [
        s for s in data
        if s.get("activity") and region in (s.get("storeInfo") or {}).get("regionIds", [])
    ]


async def main():
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    # Сначала собираем существующие idx (append-only по всем регионам).
    existing: dict[str, int] = {}
    async for d in db.gorzdrav_stores.find({}, {"_id": 0, "store_id": 1, "idx": 1}):
        existing[d["store_id"]] = d.get("idx")
    next_idx = max([i for i in existing.values() if i is not None], default=-1) + 1

    seen: set[str] = set()
    new_count = 0
    per_region_count = {}
    for region, city in REGIONS:
        stores = await fetch_region(region)
        per_region_count[region] = len(stores)
        log.info(f"[{region} → {city}] активных в регионе: {len(stores)}")

        for s in stores:
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
                    # Бренд id=1 в MOS — это «36,6» (отдельная подсеть Горздрав-а
                    # в Москве), всё остальное — «Горздрав».
                    "name": "36,6" if info.get("brand", {}).get("id") == 1 else "Горздрав",
                    "full_name": s.get("name", ""),
                    "lat": info.get("latitude"),
                    "lng": info.get("longitude"),
                    "address": info.get("address", ""),
                    "phone": info.get("phone", ""),
                    "hours": fmt_schedule(sched),
                    "is_24h": sched.get("is24Hour", False),
                    "city": city,
                    "source": "gorzdrav",
                    "active": True,
                    "updated_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )

    # Аптеки, пропавшие из выдачи API — деактивируем, idx-слот сохраняем.
    deact = await db.gorzdrav_stores.update_many(
        {"store_id": {"$nin": list(seen)}, "source": "gorzdrav"},
        {"$set": {"active": False}},
    )
    await db.gorzdrav_stores.create_index("store_id", unique=True)
    await db.gorzdrav_stores.create_index([("lat", 1), ("lng", 1)])
    await db.gorzdrav_stores.create_index("idx")
    await db.gorzdrav_stores.create_index("city")
    log.info(
        f"Обновлено: {len(seen)} аптек (новых: {new_count}), "
        f"деактивировано: {deact.modified_count}, "
        f"по регионам: {per_region_count}"
    )

    client_db.close()


if __name__ == "__main__":
    asyncio.run(main())
