#!/usr/bin/env bash
# Магнит — по-аптечное наличие (Playwright) -> gorzdrav_stores + store_bitmap.
# Тяжёлый прогон (~5ч на 12 городов, ~30к запросов к Магниту) — ЕЖЕНЕДЕЛЬНО.
# Реестр аптек (адреса/координаты) обновляется попутно (стабилен).
#
# Не конфликтует с parse_magnit (00:00, цена+матчинг): тот пишет stores_count
# (сетевой тотал), а этот — store_bitmap + stores_count=popcount. Фронт считает
# по маске (popcount), поэтому видимое не ломается; недельный прогон переутверждает.
#
# Usage: magnit_stores_cron.sh ["msk spb ..."]   (по умолчанию все 12)
#        GOODS_LIMIT=40 magnit_stores_cron.sh nsk   # быстрый тест плумбинга
set -uo pipefail
CITIES_ARG="${1:-msk spb krd nn ekb kzn nsk sam chel ufa rnd vrn}"
DATE=$(date +%Y%m%d-%H%M%S)
LOG_DIR=/var/log/aptekaa
LOG="${LOG_DIR}/magnit_stores-${DATE}.log"
LOCK=/var/lock/aptekaa_magnit_stores.lock
DEPLOY=/home/ubuntu/aptekaa/deploy
SCRIPTS=/home/ubuntu/aptekaa/backend/scripts
PWIMG=mcr.microsoft.com/playwright/python:v1.49.0-jammy

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date -u +'%F %T UTC') | magnit_stores | START | cities=$CITIES_ARG ==="

exec 9>"$LOCK" || { echo "ERR: lock fail"; exit 1; }
if ! flock -n 9; then echo "WARN: предыдущий magnit_stores ещё идёт — пропуск"; exit 0; fi

cd "$DEPLOY"
MP=$(grep '^MONGO_PASSWORD=' .env | cut -d= -f2-)
mq(){ docker exec deploy-mongo-1 mongosh -u aptekaa_admin -p "$MP" --authenticationDatabase admin aptekaa --quiet --eval "$1"; }

declare -A FIAS=(
  [msk]=0c5b2444-70a0-4932-980c-b4dc0d3f02b5  [spb]=c2deb16a-0330-4f05-821f-1d09c93331e6
  [krd]=7dfa745e-aa19-4688-b121-b655c11e482f  [nn]=555e7d61-d9a7-4ba6-9770-6caa8198c483
  [ekb]=2763c110-cb8b-416a-9dac-ad28a55b4402  [kzn]=93b3df57-4c89-44df-ac42-96f05e9cd3b9
  [nsk]=8dea00e3-9aab-4d8e-887c-ef2aaa546456  [sam]=bb035cc3-1dc2-4627-9d25-a1bf2d4b936b
  [chel]=a376e68d-724a-4472-be7c-891bdb09ae32 [ufa]=7339e834-2cb4-4734-a4c7-1fca2c66e562
  [rnd]=c1cfe4b9-f7c2-423c-abfa-6ed1c05a15c5  [vrn]=5bf5ddff-6353-4a3d-80c4-6fb27f00c6c1
)

# загрузчик в контейнер (надёжно, без зависимости от ребилда образа)
docker cp "$SCRIPTS/load_magnit_stores.py" deploy-backend-1:/tmp/magnit_load.py

OK=0; FAIL=0
for C in $CITIES_ARG; do
  echo "----- $C $(date -u +%T) -----"
  F=${FIAS[$C]:-}
  [ -z "$F" ] && { echo "$C: нет FIAS — пропуск"; FAIL=$((FAIL+1)); continue; }
  SGC=$(curl -s --max-time 25 -H "X-Device-Platform: web" \
        "https://apteka.magnit.ru/webgate/v1/shop-group/by-fias-id/$F" | python3 -c "import sys,json
try: print(json.load(sys.stdin).get('shopGroupCode',''))
except: print('')")
  [ -z "$SGC" ] && { echo "$C: SGC не получен — пропуск"; FAIL=$((FAIL+1)); continue; }
  mq "db.prices_real.distinct(\"gz_ext_id\",{source:\"magnit\",city:\"$C\",price:{\$ne:null}}).forEach(g=>print(g))" > /tmp/magnit_goods.txt
  N=$(wc -l < /tmp/magnit_goods.txt); echo "$C sgc=$SGC goodId=$N"
  [ "$N" -eq 0 ] && { echo "$C: 0 goodId — пропуск"; continue; }
  rm -f /tmp/magnit_harvest.json 2>/dev/null || true
  docker run --rm --network host -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright -e CITY="$C" -e SGC="$SGC" ${GOODS_LIMIT:+-e GOODS_LIMIT=$GOODS_LIMIT} \
    -v "$SCRIPTS/pw_harvest.py":/s.py -v /tmp/magnit_goods.txt:/tmp/goods.txt -v /tmp:/out "$PWIMG" \
    bash -lc "pip install -q playwright==1.49.0 >/dev/null 2>&1 && python /s.py && cp /tmp/harvest_out.json /out/magnit_harvest.json" \
    || { echo "$C: harvest ошибка"; FAIL=$((FAIL+1)); continue; }
  [ ! -f /tmp/magnit_harvest.json ] && { echo "$C: нет harvest json"; FAIL=$((FAIL+1)); continue; }
  docker cp /tmp/magnit_harvest.json deploy-backend-1:/tmp/magnit_harvest.json
  if docker compose exec -T backend python /tmp/magnit_load.py /tmp/magnit_harvest.json; then
    OK=$((OK+1))
  else
    echo "$C: load ошибка"; FAIL=$((FAIL+1))
  fi
  echo "----- $C готов -----"
done

TOTAL=$(mq "db.gorzdrav_stores.countDocuments({source:\"magnit\"})" | tail -1)
echo "=== $(date -u +'%F %T UTC') | magnit_stores | DONE | ok=$OK fail=$FAIL | аптек магнита=$TOTAL ==="
