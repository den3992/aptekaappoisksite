#!/usr/bin/env bash
# Парсер цен «Аптечество» (aptechestvo.ru), только Нижний Новгород (city=nn).
# Запускается из crontab. Свой flock-лок. Время — 02:45 UTC, вне блэкаута
# 03-07 UTC (Горздрав) и не пересекается с 36,6 (01:00), Ригла (02:00),
# Максавит (02:30).
#
# Usage:
#   parse_aptechestvo_cron.sh update   # быстрый рефреш цен уже сматченных
#   parse_aptechestvo_cron.sh full     # перематч всего gorzdrav-набора (еженед.)
#
# Аптечество — Этап 1 (только цена по НН, без карты наличия), поэтому режима
# availability нет (в отличие от Ригла/36,6/Максавита).

set -euo pipefail

MODE="${1:-update}"
DATE=$(date +%Y%m%d-%H%M%S)
LOG_DIR=/var/log/aptekaa
LOG="${LOG_DIR}/parse_aptechestvo-${MODE}-${DATE}.log"
LOCK=/var/lock/aptekaa_parse_aptechestvo.lock
DEPLOY=/home/ubuntu/aptekaa/deploy

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | start ==="

exec 9>"$LOCK" || { echo "ERR: cannot open lock file"; exit 1; }
if ! flock -n 9; then
  echo "WARN: previous parse_aptechestvo still running, skip"
  exit 0
fi

# Пароль Mongo читаем ОДИН раз в переменную окружения и прокидываем в
# контейнер через `docker exec -e MONGO_PW` (имя без значения → docker берёт
# значение из окружения вызывающего процесса). Так пароль НЕ попадает в argv.
MONGO_PW="$(grep '^MONGO_PASSWORD=' "$DEPLOY/.env" | cut -d= -f2-)"
export MONGO_PW

count_query() {
  local q="$1"
  docker exec -e MONGO_PW -e CQ="$q" deploy-mongo-1 sh -c \
    'mongosh --quiet -u aptekaa_admin -p "$MONGO_PW" --authenticationDatabase admin --eval "db.getSiblingDB(\"aptekaa\").prices_real.countDocuments($CQ)"' \
    | tail -1
}

BEFORE_TOTAL=$(count_query '{source:"aptechestvo", price:{$ne:null}}')
echo "BEFORE: aptechestvo priced=$BEFORE_TOTAL"

case "$MODE" in
  update)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_aptechestvo --update-only
    ;;
  full)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_aptechestvo --from-gorzdrav --rematch
    ;;
  *)
    echo "ERR: unknown mode '$MODE' (use 'update' or 'full')"
    exit 2
    ;;
esac

AFTER_TOTAL=$(count_query '{source:"aptechestvo", price:{$ne:null}}')
echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | done ==="
echo "AFTER:  aptechestvo priced=$AFTER_TOTAL"

# IndexNow: парсер пишет изменённые slug-и в /tmp/indexnow_changed_aptechestvo.txt
# внутри backend-контейнера.
echo "--- IndexNow ping (aptechestvo) ---"
cd "$DEPLOY" && docker compose exec -T backend python -m scripts.indexnow_ping /tmp/indexnow_changed_aptechestvo.txt || echo "IndexNow ping failed (non-fatal)"

# Алерт при резком падении (>20%).
if [ "${AFTER_TOTAL:-0}" -lt $((BEFORE_TOTAL * 80 / 100)) ]; then
  echo "ALERT: aptechestvo records dropped from $BEFORE_TOTAL to $AFTER_TOTAL (>20% loss)"
  exit 3
fi
