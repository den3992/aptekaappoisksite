#!/usr/bin/env bash
# Парсер цен «Здоровье» (s-zdorovie.ru), только Краснодар (city=krd) —
# 2-й источник цен для Краснодара (1-й — Максавит).
# Запускается из crontab. Свой flock-лок. Время — 00:30 UTC, вне блэкаута
# 03-07 UTC (Горздрав) и не пересекается с 36,6 (01:00), Ригла (02:00),
# Максавит (02:30), Аптечество (02:45).
#
# Usage:
#   parse_zdorovie_cron.sh update   # рефреш цен уже сматченных
#   parse_zdorovie_cron.sh full     # перематч набора Максавит-krd (еженед.)
#
# Здоровье — Этап 1 (только цена, без карты наличия), поэтому режима
# availability нет. ВНИМАНИЕ: у сайта нет товарного поиска, поэтому парсер
# В ЛЮБОМ режиме сначала КРАУЛИТ весь каталог (~200-300 запросов, минуты),
# затем матчит — это нормально.

set -euo pipefail

MODE="${1:-update}"
DATE=$(date +%Y%m%d-%H%M%S)
LOG_DIR=/var/log/aptekaa
LOG="${LOG_DIR}/parse_zdorovie-${MODE}-${DATE}.log"
LOCK=/var/lock/aptekaa_parse_zdorovie.lock
DEPLOY=/home/ubuntu/aptekaa/deploy

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | start ==="

exec 9>"$LOCK" || { echo "ERR: cannot open lock file"; exit 1; }
if ! flock -n 9; then
  echo "WARN: previous parse_zdorovie still running, skip"
  exit 0
fi

MONGO_PW="$(grep '^MONGO_PASSWORD=' "$DEPLOY/.env" | cut -d= -f2-)"
export MONGO_PW

count_query() {
  local q="$1"
  docker exec -e MONGO_PW -e CQ="$q" deploy-mongo-1 sh -c \
    'mongosh --quiet -u aptekaa_admin -p "$MONGO_PW" --authenticationDatabase admin --eval "db.getSiblingDB(\"aptekaa\").prices_real.countDocuments($CQ)"' \
    | tail -1
}

BEFORE_TOTAL=$(count_query '{source:"zdorovie", price:{$ne:null}}')
echo "BEFORE: zdorovie priced=$BEFORE_TOTAL"

case "$MODE" in
  update)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_zdorovie --update-only
    ;;
  full)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_zdorovie --from-maksavit --rematch
    ;;
  *)
    echo "ERR: unknown mode '$MODE' (use 'update' or 'full')"
    exit 2
    ;;
esac

AFTER_TOTAL=$(count_query '{source:"zdorovie", price:{$ne:null}}')
echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | done ==="
echo "AFTER:  zdorovie priced=$AFTER_TOTAL"

echo "--- IndexNow ping (zdorovie) ---"
cd "$DEPLOY" && docker compose exec -T backend python -m scripts.indexnow_ping /tmp/indexnow_changed_zdorovie.txt || echo "IndexNow ping failed (non-fatal)"

if [ "${AFTER_TOTAL:-0}" -lt $((BEFORE_TOTAL * 80 / 100)) ]; then
  echo "ALERT: zdorovie records dropped from $BEFORE_TOTAL to $AFTER_TOTAL (>20% loss)"
  exit 3
fi
