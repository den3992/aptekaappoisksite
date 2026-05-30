#!/usr/bin/env bash
# Парсер цен Аптеки 36,6 (366.ru), MOS + SPE. Запускается из crontab.
# Свой flock-лок (не пересекается с Горздравом). Время — 01:00 UTC, вне
# блэкаута 03-07 UTC, который держит Горздрав.
#
# Usage:
#   parse_apteka366_cron.sh update   # быстрый рефреш цен уже сматченных 36,6
#   parse_apteka366_cron.sh full     # перематч всего gorzdrav-набора (еженед.)
#   parse_apteka366_cron.sh availability  # только маски наличия 36,6 (интрадей)
#
# Парсер сам прогоняет оба региона (--region=both по умолчанию).

set -euo pipefail

MODE="${1:-update}"
DATE=$(date +%Y%m%d-%H%M%S)
LOG_DIR=/var/log/aptekaa
LOG="${LOG_DIR}/parse_apteka366-${MODE}-${DATE}.log"
LOCK=/var/lock/aptekaa_parse_apteka366.lock
DEPLOY=/home/ubuntu/aptekaa/deploy

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | start ==="

exec 9>"$LOCK" || { echo "ERR: cannot open lock file"; exit 1; }
if ! flock -n 9; then
  echo "WARN: previous parse_apteka366 still running, skip"
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

BEFORE_TOTAL=$(count_query '{source:"apteka366", price:{$ne:null}}')
echo "BEFORE: apteka366 priced=$BEFORE_TOTAL"

case "$MODE" in
  update)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_apteka366 --update-only --region=both
    ;;
  full)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_apteka366 --from-gorzdrav --rematch --region=both
    ;;
  availability)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_apteka366 --availability-only --region=both
    ;;
  *)
    echo "ERR: unknown mode '$MODE' (use 'update', 'full' or 'availability')"
    exit 2
    ;;
esac

AFTER_TOTAL=$(count_query '{source:"apteka366", price:{$ne:null}}')
echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | done ==="
echo "AFTER:  apteka366 priced=$AFTER_TOTAL"

# IndexNow: парсер 36,6 пишет изменённые slug-и в /tmp/indexnow_changed_366.txt
# внутри backend-контейнера.
echo "--- IndexNow ping (366) ---"
cd "$DEPLOY" && docker compose exec -T backend python -m scripts.indexnow_ping /tmp/indexnow_changed_366.txt || echo "IndexNow ping failed (non-fatal)"

# Алерт при резком падении (>20%).
if [ "${AFTER_TOTAL:-0}" -lt $((BEFORE_TOTAL * 80 / 100)) ]; then
  echo "ALERT: apteka366 records dropped from $BEFORE_TOTAL to $AFTER_TOTAL (>20% loss)"
  exit 3
fi
