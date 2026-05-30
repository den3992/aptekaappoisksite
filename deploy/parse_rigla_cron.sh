#!/usr/bin/env bash
# Парсер цен Ригла (rigla.ru), только Москва (city=msk). Запускается из crontab.
# Свой flock-лок (не пересекается с Горздравом/36,6). Время — 02:00 UTC, вне
# блэкаута 03-07 UTC (Горздрав) и не в 01:00 (36,6).
#
# Usage:
#   parse_rigla_cron.sh update        # быстрый рефреш цен уже сматченных Ригла
#   parse_rigla_cron.sh full          # перематч всего gorzdrav-набора msk (еженед.)
#   parse_rigla_cron.sh availability  # только маски наличия (store_bitmap) по аптекам
#
# Маски наличия Ригла (pvzList + pvzStocks) также обновляются автоматически
# в конце update/full-ранов. Отдельный режим availability — для интрадей-рефреша.

set -euo pipefail

MODE="${1:-update}"
DATE=$(date +%Y%m%d-%H%M%S)
LOG_DIR=/var/log/aptekaa
LOG="${LOG_DIR}/parse_rigla-${MODE}-${DATE}.log"
LOCK=/var/lock/aptekaa_parse_rigla.lock
DEPLOY=/home/ubuntu/aptekaa/deploy

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | start ==="

exec 9>"$LOCK" || { echo "ERR: cannot open lock file"; exit 1; }
if ! flock -n 9; then
  echo "WARN: previous parse_rigla still running, skip"
  exit 0
fi

count_query() {
  local q="$1"
  docker exec deploy-mongo-1 mongosh --quiet \
    -u aptekaa_admin -p "$(grep MONGO_PASSWORD $DEPLOY/.env|cut -d= -f2)" \
    --authenticationDatabase admin \
    --eval "db.getSiblingDB(\"aptekaa\").prices_real.countDocuments($q)" \
    | tail -1
}

BEFORE_TOTAL=$(count_query '{source:"rigla", price:{$ne:null}}')
echo "BEFORE: rigla priced=$BEFORE_TOTAL"

case "$MODE" in
  update)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_rigla --update-only
    ;;
  full)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_rigla --from-gorzdrav --rematch
    ;;
  availability)
    # Только маски наличия (store_bitmap) по аптекам Ригла — без перематчинга
    # цен. Цена не меняется → IndexNow и алерт >20% не нужны (выходим раньше).
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_rigla --availability-only
    echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | done ==="
    exit 0
    ;;
  *)
    echo "ERR: unknown mode '$MODE' (use 'update', 'full' or 'availability')"
    exit 2
    ;;
esac

AFTER_TOTAL=$(count_query '{source:"rigla", price:{$ne:null}}')
echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | done ==="
echo "AFTER:  rigla priced=$AFTER_TOTAL"

# IndexNow: парсер Ригла пишет изменённые slug-и в /tmp/indexnow_changed_rigla.txt
# внутри backend-контейнера.
echo "--- IndexNow ping (rigla) ---"
cd "$DEPLOY" && docker compose exec -T backend python -m scripts.indexnow_ping /tmp/indexnow_changed_rigla.txt || echo "IndexNow ping failed (non-fatal)"

# Алерт при резком падении (>20%).
if [ "${AFTER_TOTAL:-0}" -lt $((BEFORE_TOTAL * 80 / 100)) ]; then
  echo "ALERT: rigla records dropped from $BEFORE_TOTAL to $AFTER_TOTAL (>20% loss)"
  exit 3
fi
