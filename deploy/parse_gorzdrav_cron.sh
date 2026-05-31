#!/usr/bin/env bash
# Ежедневный/еженедельный парсер Горздрав (MOS + SPE).
# Запускается из crontab, защита от пересечения через flock.
#
# Usage:
#   parse_gorzdrav_cron.sh update   # инкрементальное обновление сматченных
#   parse_gorzdrav_cron.sh full     # полный rematch всего каталога
#
# Парсер сам прогоняет оба региона: MOS → city=msk, SPE → city=spb
# (--region=both — значение по умолчанию у parse_gorzdrav.py).

set -euo pipefail

MODE="${1:-update}"
DATE=$(date +%Y%m%d-%H%M%S)
LOG_DIR=/var/log/aptekaa
LOG="${LOG_DIR}/parse_gorzdrav-${MODE}-${DATE}.log"
LOCK=/var/lock/aptekaa_parse_gorzdrav.lock
DEPLOY=/home/ubuntu/aptekaa/deploy

mkdir -p "$LOG_DIR"

# Логируем всё (stdout+stderr) и в лог-файл, и в stdout (для CRON-mail).
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | start ==="

# flock: если предыдущий запуск ещё идёт — выходим с предупреждением, не ждём.
exec 9>"$LOCK" || { echo "ERR: cannot open lock file"; exit 1; }
if ! flock -n 9; then
  echo "WARN: previous parse_gorzdrav still running, skip"
  exit 0
fi

# Быстрый health-check счётчиков (всего + по городам).
# Пароль Mongo читаем ОДИН раз в переменную окружения и прокидываем в
# контейнер через `docker exec -e MONGO_PW` (имя без значения → docker берёт
# значение из окружения вызывающего процесса). Так пароль НЕ попадает в argv
# и не виден в `ps aux` на хосте. Запрос (не секрет) передаём через -e CQ.
MONGO_PW="$(grep '^MONGO_PASSWORD=' "$DEPLOY/.env" | cut -d= -f2-)"
export MONGO_PW

count_query() {
  local q="$1"
  docker exec -e MONGO_PW -e CQ="$q" deploy-mongo-1 sh -c \
    'mongosh --quiet -u aptekaa_admin -p "$MONGO_PW" --authenticationDatabase admin --eval "db.getSiblingDB(\"aptekaa\").prices_real.countDocuments($CQ)"' \
    | tail -1
}

BEFORE_TOTAL=$(count_query '{source:"gorzdrav", price:{$ne:null}}')
BEFORE_MSK=$(count_query   '{source:"gorzdrav", city:"msk", price:{$ne:null}}')
BEFORE_SPB=$(count_query   '{source:"gorzdrav", city:"spb", price:{$ne:null}}')
echo "BEFORE: total=$BEFORE_TOTAL msk=$BEFORE_MSK spb=$BEFORE_SPB"

case "$MODE" in
  update)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_gorzdrav --update-only --region=both
    ;;
  full)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_gorzdrav --rematch --region=both
    ;;
  *)
    echo "ERR: unknown mode '$MODE' (use 'update' or 'full')"
    exit 2
    ;;
esac

AFTER_TOTAL=$(count_query '{source:"gorzdrav", price:{$ne:null}}')
AFTER_MSK=$(count_query   '{source:"gorzdrav", city:"msk", price:{$ne:null}}')
AFTER_SPB=$(count_query   '{source:"gorzdrav", city:"spb", price:{$ne:null}}')

echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | done ==="
echo "AFTER:  total=$AFTER_TOTAL msk=$AFTER_MSK spb=$AFTER_SPB"

# IndexNow: парсер записал slug-и с изменившейся ценой в /tmp/indexnow_changed.txt
# внутри backend-контейнера. Шлём их на IndexNow (Яндекс/Bing быстро переиндексируют).
echo "--- IndexNow ping ---"
cd "$DEPLOY" && docker compose exec -T backend python -m scripts.indexnow_ping /tmp/indexnow_changed.txt || echo "IndexNow ping failed (non-fatal)"

# Алерт: если резкое падение (> 20% потеря записей) — аномалия.
# (cron сам отправит вывод на почту root, если в /etc/aliases настроен MAILTO).
if [ "$AFTER_TOTAL" -lt $((BEFORE_TOTAL * 80 / 100)) ]; then
  echo "ALERT: gorzdrav records dropped from $BEFORE_TOTAL to $AFTER_TOTAL (>20% loss)"
  exit 3
fi
