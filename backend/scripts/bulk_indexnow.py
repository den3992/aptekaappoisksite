"""Разовый массовый IndexNow-сабмит всего каталога (города × препараты + категории
+ городские главные). IndexNow (Яндекс/Bing) не ограничен 470/день как recrawl-API,
принимает до 10к URL/запрос. Запуск в backend-контейнере:
    python /tmp/bulk_indexnow.py [--dry]
"""
import os, sys, json, asyncio, urllib.request
from motor.motor_asyncio import AsyncIOMotorClient

KEY = "3c6a00678b80a261eee94accd64427c7"
HOST = "aptekaa.ru"
ENDPOINT = "https://api.indexnow.org/indexnow"
DRY = "--dry" in sys.argv

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])["aptekaa"]
    city_ids = ["msk", "spb", "krd", "nn", "ekb", "kzn", "nsk", "sam", "chel", "ufa", "rnd", "vrn"]
    cat_slugs = [c for c in await db.medications.distinct("category") if c and c != "other"]
    slugs = await db.medications.distinct("slug", {"is_canonical": {"$ne": False}})
    print(f"городов={len(city_ids)} категорий={len(cat_slugs)} препаратов={len(slugs)}")

    urls = []
    for c in city_ids:
        urls.append(f"https://{HOST}/{c}")
        for cat in cat_slugs:
            urls.append(f"https://{HOST}/{c}/kategorii/{cat}")
        for s in slugs:
            urls.append(f"https://{HOST}/{c}/preparaty/{s}")
    print(f"всего URL: {len(urls)}")
    if DRY:
        print("DRY — пример:", urls[:3], "...", urls[-2:]); return

    import time
    sent = 0; errs = 0
    for i in range(0, len(urls), 10000):
        chunk = urls[i:i+10000]
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
