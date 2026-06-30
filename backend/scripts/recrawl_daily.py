"""
Ежедневный переобход страниц через API Яндекс.Вебмастера.

Очередь: препараты с ценой Магнита в 6 новых городах (ekb,kzn,nsk,sam,chel,ufa),
по убыванию популярности (число сетей с ценой в Москве = прокси спроса).
Каждый запуск шлёт до DAILY_LIMIT (470) URL, отмечает отправленные в Mongo
(recrawl_submitted), чтобы не повторяться. Квоту 470/день Яндекс enforce'ит сам.

Порядок URL: препарат №1 во всех 6 городах, препарат №2 во всех 6, … — так
топовые лекарства попадают в индекс во всех городах сразу.

API: https://yandex.ru/dev/webmaster/doc/dg/reference/host-recrawl-post.html
  GET  /v4/user/                                   → user_id
  GET  /v4/user/{uid}/hosts/                       → host_id для aptekaa.ru
  POST /v4/user/{uid}/hosts/{hid}/recrawl/queue/   body {"url": "..."} (1 URL/запрос)

Токен: env YANDEX_WEBMASTER_TOKEN (OAuth, scope webmaster:hostinfo+verify).

Запуск:
  python -m scripts.recrawl_daily            # отправить следующие 470
  python -m scripts.recrawl_daily --limit 100
  python -m scripts.recrawl_daily --dry      # построить очередь, НЕ отправлять
  python -m scripts.recrawl_daily --status   # сколько отправлено / осталось
"""
from __future__ import annotations
import os, sys, asyncio, argparse
from pathlib import Path
from datetime import datetime, timezone

import httpx
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from motor.motor_asyncio import AsyncIOMotorClient
from scripts.parse_gorzdrav import MONGO_URL, DB_NAME, log

API = "https://api.webmaster.yandex.net/v4"
HOST_NAME = "aptekaa.ru"
SITE = "https://aptekaa.ru"
ALL_CITIES = ["msk", "spb", "krd", "nn", "ekb", "kzn", "nsk", "sam", "chel", "ufa", "rnd", "vrn"]
REAL = ["gorzdrav", "apteka366", "rigla", "maksavit", "aptechestvo", "zdorovie", "magnit", "farmakopeika"]
MATCH_OK = ["matched", "mnn_match", "needs_review"]
DAILY_LIMIT = 470
TOKEN = os.environ.get("YANDEX_WEBMASTER_TOKEN", "")


def _headers():
    return {"Authorization": f"OAuth {TOKEN}", "Content-Type": "application/json"}


async def resolve_ids(client: httpx.AsyncClient):
    r = await client.get(f"{API}/user/", headers=_headers(), timeout=30)
    r.raise_for_status()
    uid = r.json()["user_id"]
    r = await client.get(f"{API}/user/{uid}/hosts/", headers=_headers(), timeout=30)
    r.raise_for_status()
    hid = None
    for h in r.json().get("hosts", []):
        if HOST_NAME in (h.get("unicode_host_url", "") + h.get("ascii_host_url", "") + h.get("host_id", "")):
            hid = h["host_id"]; break
    if not hid:
        raise RuntimeError(f"host {HOST_NAME} не найден среди {[h.get('host_id') for h in r.json().get('hosts',[])]}")
    return uid, hid


async def build_queue(db) -> list[str]:
    """Приоритетная очередь: ВСЕ ценные (price>0) страницы по 12 городам.
    Приоритет: широта (в скольких городах есть) → насыщенность msk сетями →
    slug. Внутри препарата города в порядке ALL_CITIES (msk/spb первыми).
    Совпадает с индексируемым набором (тот же price>0 + match_status, что в
    medication_detail/sitemap)."""
    from collections import Counter
    priced_by_city = {}
    for c in ALL_CITIES:
        s2 = set()
        async for row in db.prices_real.aggregate([
            {"$match": {"city": c, "price": {"$gt": 0}, "source": {"$in": REAL}, "match_status": {"$in": MATCH_OK}}},
            {"$group": {"_id": "$slug", "nets": {"$addToSet": "$source"}}},
            {"$match": {"$expr": {"$gte": [{"$size": "$nets"}, 2]}}},
        ]):
            s2.add(row["_id"])
        priced_by_city[c] = s2
    pop_cities = Counter()
    for c in ALL_CITIES:
        for s in priced_by_city[c]:
            pop_cities[s] += 1
    # тай-брейк: число сетей с ценой в msk (прокси спроса по самому ценному городу)
    msk_nets = {}
    async for row in db.prices_real.aggregate([
        {"$match": {"city": "msk", "price": {"$gt": 0}, "source": {"$in": REAL}}},
        {"$group": {"_id": "$slug", "nets": {"$addToSet": "$source"}}},
    ]):
        msk_nets[row["_id"]] = len(row.get("nets", []))
    ordered = sorted(pop_cities.keys(), key=lambda s: (-pop_cities[s], -msk_nets.get(s, 0), s))
    urls = []
    for s in ordered:
        for c in ALL_CITIES:  # msk/spb первыми
            if s in priced_by_city[c]:
                urls.append(f"{SITE}/{c}/preparaty/{s}")
    return urls


async def main(args):
    client_db = AsyncIOMotorClient(MONGO_URL)
    db = client_db[DB_NAME]

    queue = await build_queue(db)
    submitted = set(await db.recrawl_submitted.distinct("url"))
    pending = [u for u in queue if u not in submitted]
    log.info(f"[recrawl] очередь: {len(queue)} URL, отправлено ранее: {len(submitted)}, осталось: {len(pending)}")

    if args.status:
        log.info(f"[recrawl] СТАТУС: {len(submitted)}/{len(queue)} отправлено, осталось {len(pending)} "
                 f"(~{(len(pending)+DAILY_LIMIT-1)//DAILY_LIMIT} дней при 470/день)")
        client_db.close(); return

    batch = pending[: args.limit]
    if not batch:
        log.info("[recrawl] очередь пуста — всё отправлено."); client_db.close(); return
    log.info(f"[recrawl] к отправке сегодня: {len(batch)} URL (первый: {batch[0]})")

    if args.dry:
        for u in batch[:10]:
            log.info(f"  DRY {u}")
        log.info(f"[recrawl] DRY — не отправлено. Всего в батче: {len(batch)}")
        client_db.close(); return

    if not TOKEN:
        log.error("[recrawl] нет YANDEX_WEBMASTER_TOKEN в окружении"); client_db.close(); return

    async with httpx.AsyncClient() as client:
        uid, hid = await resolve_ids(client)
        log.info(f"[recrawl] user_id={uid} host_id={hid}")
        sent, failed, quota_hit = 0, 0, False
        for u in batch:
            try:
                r = await client.post(f"{API}/user/{uid}/hosts/{hid}/recrawl/queue/",
                                       headers=_headers(), json={"url": u}, timeout=30)
                if r.status_code in (200, 202):
                    await db.recrawl_submitted.update_one(
                        {"url": u}, {"$set": {"url": u, "at": datetime.now(timezone.utc),
                                              "task_id": r.json().get("task_id")}}, upsert=True)
                    sent += 1
                else:
                    txt = r.text[:200]
                    if "QUOTA" in txt.upper() or r.status_code == 429:
                        log.warning(f"[recrawl] квота исчерпана на {sent}-м URL — стоп"); quota_hit = True; break
                    failed += 1
                    if failed <= 5:
                        log.warning(f"[recrawl] {r.status_code} для {u}: {txt}")
                await asyncio.sleep(0.2)
            except Exception as e:
                failed += 1
                if failed <= 5: log.warning(f"[recrawl] err {u}: {e}")
        log.info(f"[recrawl] Готово. Отправлено {sent}, ошибок {failed}, квота_исчерпана={quota_hit}. "
                 f"Всего отправлено за всё время: {len(submitted)+sent}/{len(queue)}")
    await db.recrawl_submitted.create_index("url", unique=True)
    client_db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=DAILY_LIMIT)
    p.add_argument("--dry", action="store_true")
    p.add_argument("--status", action="store_true")
    asyncio.run(main(p.parse_args()))
