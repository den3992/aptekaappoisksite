#!/usr/bin/env bash
# Ежедневный/еженедельный парсер Горздрав.
# Запускается из crontab, защита от пересечения через flock.
#
# Usage:
#   parse_gorzdrav_cron.sh update   # инкрементальное обновление существующих
#   parse_gorzdrav_cron.sh full     # полный rematch всего каталога

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

# Запоминаем счётчики ДО запуска для health-check после.
COUNT_BEFORE=$(docker exec deploy-mongo-1 mongosh --quiet \
  -u aptekaa_admin -p "$(grep MONGO_PASSWORD $DEPLOY/.env|cut -d= -f2)" \
  --authenticationDatabase admin \
  --eval 'db.getSiblingDB("aptekaa").prices_real.countDocuments({source:"gorzdrav", price:{$ne:null}})' \
  | tail -1)

case "$MODE" in
  update)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_gorzdrav --update-only
    ;;
  full)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_gorzdrav --rematch
    ;;
  *)
    echo "ERR: unknown mode '$MODE' (use 'update' or 'full')"
    exit 2
    ;;
esac

COUNT_AFTER=$(docker exec deploy-mongo-1 mongosh --quiet \
  -u aptekaa_admin -p "$(grep MONGO_PASSWORD $DEPLOY/.env|cut -d= -f2)" \
  --authenticationDatabase admin \
  --eval 'db.getSiblingDB("aptekaa").prices_real.countDocuments({source:"gorzdrav", price:{$ne:null}})' \
  | tail -1)

echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | done | before=$COUNT_BEFORE after=$COUNT_AFTER ==="

# IndexNow: парсер записал slug-и с изменившейся ценой в /tmp/indexnow_changed.txt
# внутри backend-контейнера. Шлём их на IndexNow (Яндекс/Bing быстро переиндексируют).
echo "--- IndexNow ping ---"
cd "$DEPLOY" && docker compose exec -T backend python -m scripts.indexnow_ping /tmp/indexnow_changed.txt || echo "IndexNow ping failed (non-fatal)"

# Алерт: если резкое падение (> 20% потеря записей) — это аномалия.
# (cron сам отправит вывод на почту root, если в /etc/aliases настроен MAILTO)
if [ "$COUNT_AFTER" -lt $((COUNT_BEFORE * 80 / 100)) ]; then
  echo "ALERT: gorzdrav records dropped from $COUNT_BEFORE to $COUNT_AFTER (>20% loss)"
  exit 3
fi
