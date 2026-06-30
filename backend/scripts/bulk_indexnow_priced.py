"""Разовый IndexNow-сабмит ТОЛЬКО ценных (индексируемых) страниц — где у препарата
есть реальная цена в этом городе (там появился гео-блок). НЕ пингуем ~199к пустых
noindex-страниц (против throttle ключа). Запуск в backend-контейнере:
    python /tmp/bulk_indexnow_priced.py [--dry]
"""
import os, sys, json, asyncio, urllib.request, time
from motor.motor_asyncio import AsyncIOMotorClient

KEY = "3c6a00678b80a261eee94accd64427c7"
HOST = "aptekaa.ru"
ENDPOINT = "https://api.indexnow.org/indexnow"
DRY = "--dry" in sys.argv
SOURCES = ["gorzdrav", "apteka366", "rigla", "maksavit", "aptechestvo", "zdorovie", "magnit", "farmakopeika"]


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])["aptekaa"]
    cities = ["msk", "spb", "krd", "nn", "ekb", "kzn", "nsk", "sam", "chel", "ufa", "rnd", "vrn"]
    cat_slugs = [c for c in await db.medications.distinct("category") if c and c != "other"]

    urls = []
    total_priced = 0
    for c in cities:
        urls.append(f"https://{HOST}/{c}")
        for cat in cat_slugs:
            urls.append(f"https://{HOST}/{c}/kategorii/{cat}")
        slugs = await db.prices_real.distinct(
            "slug", {"city": c, "source": {"$in": SOURCES}, "price": {"$gt": 0}}
        )
        total_priced += len(slugs)
        for s in slugs:
            urls.append(f"https://{HOST}/{c}/preparaty/{s}")
    print(f"ценных пар (город,препарат): {total_priced} | всего URL (с гл./катег.): {len(urls)}")
    if DRY:
        print("DRY — пример:", urls[:3], "...", urls[-2:])
        return

    sent = 0
    errs = 0
    for i in range(0, len(urls), 10000):
        chunk = urls[i:i + 10000]
        payload = json.dumps({"host": HOST, "key": KEY,
                              "keyLocation": f"https://{HOST}/{KEY}.txt",
                              "urlList": chunk}).encode()
        req = urllib.request.Request(ENDPOINT, data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            r = urllib.request.urlopen(req, timeout=60)
            sent += len(chunk); errs = 0
            print(f"  batch {i//10000+1}: {len(chunk)} -> HTTP {r.status}", flush=True)
        except Exception as e:
            errs += 1
            print(f"  batch {i//10000+1} ОШИБКА: {str(e)[:120]}", flush=True)
            if errs >= 3:
                print("3 ошибки подряд — стоп (вероятно throttling)."); break
        time.sleep(2)
    print(f"ИТОГО отправлено: {sent} URL")


asyncio.run(main())
