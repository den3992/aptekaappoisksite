#!/usr/bin/env bash
# Парсер цен «Магнит Аптека» (apteka.magnit.ru) — Фаза 1: наши 4 города
# (msk,spb,krd,nn). Мультигород через FIAS→shopGroupCode. Этап 1: цена+остаток
# по городу, без карты по аптекам.
#
# Время 00:00 UTC — вне блэкаута 03-07 и не пересекается с zdorovie(00:30),
# 36,6(01:00), rigla(02:00), maksavit(02:30), aptechestvo(02:45).
#
# Usage:
#   parse_magnit_cron.sh update   # рефреш цен уже сматченных (--update-only)
#   parse_magnit_cron.sh full     # перематч набора --from-priced (еженед.)

set -euo pipefail
MODE="${1:-update}"
DATE=$(date +%Y%m%d-%H%M%S)
LOG_DIR=/var/log/aptekaa
LOG="${LOG_DIR}/parse_magnit-${MODE}-${DATE}.log"
LOCK=/var/lock/aptekaa_parse_magnit.lock
DEPLOY=/home/ubuntu/aptekaa/deploy
CITIES="msk,spb,krd,nn"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | start ==="

exec 9>"$LOCK" || { echo "ERR: lock"; exit 1; }
if ! flock -n 9; then echo "WARN: previous parse_magnit running, skip"; exit 0; fi

MONGO_PW="$(grep '^MONGO_PASSWORD=' "$DEPLOY/.env" | cut -d= -f2-)"; export MONGO_PW
count_q(){ docker exec -e MONGO_PW -e CQ="$1" deploy-mongo-1 sh -c \
  'mongosh --quiet -u aptekaa_admin -p "$MONGO_PW" --authenticationDatabase admin --eval "db.getSiblingDB(\"aptekaa\").prices_real.countDocuments($CQ)"' | tail -1; }

BEFORE=$(count_q '{source:"magnit", price:{$ne:null}}')
echo "BEFORE: magnit priced=$BEFORE"

case "$MODE" in
  update) cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_magnit --city "$CITIES" --update-only ;;
  full)   cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_magnit --city "$CITIES" --from-priced --rematch ;;
  *) echo "ERR: unknown mode '$MODE'"; exit 2 ;;
esac

AFTER=$(count_q '{source:"magnit", price:{$ne:null}}')
echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | done ==="
echo "AFTER: magnit priced=$AFTER"

echo "--- IndexNow ping (magnit) ---"
cd "$DEPLOY" && docker compose exec -T backend python -m scripts.indexnow_ping /tmp/indexnow_changed_magnit.txt || echo "IndexNow ping failed (non-fatal)"

if [ "${AFTER:-0}" -lt $((BEFORE * 80 / 100)) ]; then
  echo "ALERT: magnit dropped $BEFORE -> $AFTER (>20%)"; exit 3
fi
