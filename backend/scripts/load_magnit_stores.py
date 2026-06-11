"""Загружает результат Playwright-сбора Магнита в gorzdrav_stores + store_bitmap.
Запуск в backend-контейнере: python /load_magnit_stores.py /tmp/harvest_nsk_full.json
Идемпотентен: store_id стабилен ('magnit_<storeID>'), idx не переиспользуется.
"""
import sys, json, asyncio, os
from collections import defaultdict
from bson.binary import Binary
from motor.motor_asyncio import AsyncIOMotorClient

def popcount(ba): return sum(bin(b).count("1") for b in ba)

async def main(path):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])["aptekaa"]
    data = json.load(open(path, encoding="utf-8"))
    city = data["city"]
    print(f"city={city} stores={len(data['stores'])} avail={len(data['availability'])}")

    # 1) глобальный max idx (append-only, не переиспользуем)
    max_idx = -1
    async for s in db.gorzdrav_stores.find({}, {"idx": 1, "_id": 0}):
        if s.get("idx") is not None and s["idx"] > max_idx:
            max_idx = s["idx"]
    print("текущий глобальный max idx:", max_idx)

    # 2) upsert аптек Магнита, выдаём idx
    store_idx = {}   # storeID(Магнита, str) -> idx
    new = 0
    for st in data["stores"]:
        sid = "magnit_" + str(st["store_id"])
        ex = await db.gorzdrav_stores.find_one({"store_id": sid}, {"idx": 1})
        if ex and ex.get("idx") is not None:
            idx = ex["idx"]
        else:
            max_idx += 1; idx = max_idx; new += 1
        store_idx[str(st["store_id"])] = idx
        await db.gorzdrav_stores.update_one(
            {"store_id": sid},
            {"$set": {
                "store_id": sid, "source": "magnit", "city": city, "idx": idx,
                "name": "Магнит Аптека", "full_name": st.get("name"),
                "address": st.get("address"), "hours": st.get("schedule"),
                "lat": st.get("lat"), "lng": st.get("lng"), "active": True,
            }}, upsert=True)
    print(f"аптек upsert: {len(store_idx)} (новых idx: {new}), новый max idx: {max_idx}")

    # 3) размер маски (глобальный, как у parse_gorzdrav)
    nbytes = (max_idx + 8) // 8

    # 4) наличие good -> {storeID: qty}; строим маску и пишем в prices_real
    by_good = defaultdict(dict)
    for a in data["availability"]:
        by_good[a["good"]][str(a["store_id"])] = a.get("qty") or 0

    updated = 0; bitmapped = 0
    for good, stores in by_good.items():
        ba = bytearray(nbytes)
        for sid, qty in stores.items():
            if qty and qty > 0 and sid in store_idx:
                idx = store_idx[sid]; ba[idx >> 3] |= 1 << (idx & 7)
        if popcount(ba) == 0:
            continue
        bitmapped += 1
        res = await db.prices_real.update_many(
            {"source": "magnit", "city": city, "gz_ext_id": good},
            {"$set": {"store_bitmap": Binary(bytes(ba)), "stores_count": popcount(ba)}})
        updated += res.modified_count
    print(f"goodId с наличием: {bitmapped} | записей prices_real обновлено: {updated} | nbytes={nbytes}")

asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/harvest_nsk_full.json"))
