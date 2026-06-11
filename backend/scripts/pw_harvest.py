import json, time, os
from playwright.sync_api import sync_playwright

CITY = os.environ.get("CITY", "nsk")
SGC = os.environ["SGC"]
GOODS = [l.strip() for l in open("/tmp/goods.txt") if l.strip()]
_lim = int(os.environ.get("GOODS_LIMIT", "0"))
if _lim:
    GOODS = GOODS[:_lim]
SEED = GOODS[0]
cap = {}
registry = {}     # store_id -> {name,address,lat,lng,schedule,brand}
avail = []        # {good, store_id, qty, price}

LIST_JS = """async (gid) => {
  const u = `/webgate/v1/stores/availability-preview/list?goodId=${gid}&availableFilter=inner&goodQuantity=1`;
  try { const r = await fetch(u, {headers:{'Accept':'application/json'}});
    const j = await r.json(); return {status:r.status, stores:(j&&j.stores)||[]}; }
  catch(e){ return {status:-1, stores:[]}; }
}"""

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                        locale="ru-RU", viewport={"width":1440,"height":900})
    pg = ctx.new_page()
    def handle(route):
        h = dict(route.request.headers)
        if h.get("x-client-name") and h.get("x-device-id"): cap["h"] = h
        out = dict(cap.get("h", h)); out["x-virtual-group-code"] = SGC
        route.continue_(headers=out)
    pg.route("**/availability-preview/**", handle)
    pg.goto("https://apteka.magnit.ru/", wait_until="domcontentloaded", timeout=60000); pg.wait_for_timeout(2500)
    # Установка сессии + захват заголовков. Ретраим на случай Qrator-челленджа.
    for _att in range(5):
        seed = GOODS[_att % len(GOODS)]
        try:
            pg.goto(f"https://apteka.magnit.ru/product/{seed}/availability", wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        pg.wait_for_timeout(6000)
        if cap.get("h"):
            break
        pg.wait_for_timeout(4000)
    if not cap.get("h"):
        print("!! заголовки не пойманы (5 попыток)"); raise SystemExit(1)

    def reseed():
        pg.goto(f"https://apteka.magnit.ru/product/{SEED}/availability", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(5000)

    ok = err = 0; consec = 0
    for i, gid in enumerate(GOODS):
        if i and i % 500 == 0:            # периодически освежаем сессию
            reseed()
        res = None
        for attempt in range(3):
            res = pg.evaluate(LIST_JS, gid)
            if res["status"] == 200: break
            pg.wait_for_timeout(500)
        if res["status"] != 200:
            err += 1; consec += 1
            if consec >= 5:               # сессия умерла — пересоздаём и ретраим
                reseed(); consec = 0
                res = pg.evaluate(LIST_JS, gid)
                if res["status"] != 200: continue
            else:
                continue
        consec = 0
        ok += 1
        for s in res["stores"]:
            sid = str(s.get("storeID") or s.get("code"))
            c = s.get("coordinates") or {}
            if sid not in registry:
                registry[sid] = {"name": s.get("name"), "address": s.get("address"),
                                 "lat": c.get("y"), "lng": c.get("x"),
                                 "schedule": s.get("schedule"), "brand": s.get("retailBrand")}
            avail.append({"good": gid, "store_id": sid,
                          "qty": s.get("availableCount"), "price": (s.get("totalFinalPrice") or 0)//100})
        if (i+1) % 25 == 0: print(f"  {i+1}/{len(GOODS)} | аптек в реестре: {len(registry)}")
    b.close()

out = {"city": CITY, "goods_ok": ok, "goods_err": err,
       "stores": [{"store_id": k, **v} for k, v in registry.items()], "availability": avail}
json.dump(out, open("/tmp/harvest_out.json", "w"), ensure_ascii=False)
print(f"\nГОТОВО: препаратов ok={ok} err={err} | уникальных аптек={len(registry)} | записей наличия={len(avail)}")
for s in out["stores"][:4]:
    print(f"  - {s['name']} | {s['address']} | {s['lat']},{s['lng']} | {s['schedule']}")
