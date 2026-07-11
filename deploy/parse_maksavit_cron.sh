#!/usr/bin/env bash
# Парсер цен и наличия сети «Максавит» (maksavit.ru). Мультигородний:
# nn (Нижний Новгород), spb (СПб), krd (Краснодар), msk (Пушкино/МО → Москва).
# Запускается из crontab. Свой flock-лок (не пересекается с Горздрав/36,6/Ригла).
# Время — 02:30 UTC, вне блэкаута 03-07 UTC (Горздрав), не в 01:00/02:00.
#
# Usage:
#   parse_maksavit_cron.sh update        # быстрый рефреш цен уже сматченных позиций
#   parse_maksavit_cron.sh full          # перематч всего канонического набора (еженед.)
#   parse_maksavit_cron.sh availability  # только маски наличия (store_bitmap)

set -euo pipefail

MODE="${1:-update}"
DATE=$(date +%Y%m%d-%H%M%S)
LOG_DIR=/var/log/aptekaa
LOG="${LOG_DIR}/parse_maksavit-${MODE}-${DATE}.log"
LOCK=/var/lock/aptekaa_parse_maksavit.lock
DEPLOY=/home/ubuntu/aptekaa/deploy

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | start ==="

exec 9>"$LOCK" || { echo "ERR: cannot open lock file"; exit 1; }
if ! flock -n 9; then
  echo "WARN: previous parse_maksavit still running, skip"
  exit 0
fi

# Пароль Mongo читаем ОДИН раз в переменную окружения и прокидываем в
# контейнер через `docker exec -e MONGO_PW` (имя без значения → docker берёт
# значение из окружения вызывающего процесса). Так пароль НЕ попадает в argv
# и не виден в `ps aux` на хосте. Внутри контейнера sh подставляет $MONGO_PW.
# Сам запрос (не секрет) передаём через -e CQ — это снимает проблему кавычек.
MONGO_PW="$(grep '^MONGO_PASSWORD=' "$DEPLOY/.env" | cut -d= -f2-)"
export MONGO_PW

count_query() {
  local q="$1"
  docker exec -e MONGO_PW -e CQ="$q" deploy-mongo-1 sh -c \
    'mongosh --quiet -u aptekaa_admin -p "$MONGO_PW" --authenticationDatabase admin --eval "db.getSiblingDB(\"aptekaa\").prices_real.countDocuments($CQ)"' \
    | tail -1
}

BEFORE_TOTAL=$(count_query '{source:"maksavit", price:{$ne:null}}')
echo "BEFORE: maksavit priced=$BEFORE_TOTAL"

case "$MODE" in
  update)
    # Только цены (--no-availability): с расширением на 9 городов update с фазой
    # наличия шёл 9ч+ (02:30->11:42). Наличие обновляет отдельный availability-крон
    # (15:00) и воскресный full — как у Здоровья.
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_maksavit --update-only --no-availability
    ;;
  full)
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_maksavit --rematch
    ;;
  availability)
    # Только маски наличия (store_bitmap) по аптекам всех городов — без
    # перематчинга цен. Цена не меняется → IndexNow и алерт не нужны.
    cd "$DEPLOY" && docker compose exec -T backend python -m scripts.parse_maksavit --availability-only
    echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | done ==="
    exit 0
    ;;
  *)
    echo "ERR: unknown mode '$MODE' (use 'update', 'full' or 'availability')"
    exit 2
    ;;
esac

AFTER_TOTAL=$(count_query '{source:"maksavit", price:{$ne:null}}')
echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | mode=$MODE | done ==="
echo "AFTER:  maksavit priced=$AFTER_TOTAL"

# IndexNow: парсер пишет изменённые slug-и в /tmp/indexnow_changed_maksavit.txt
# внутри backend-контейнера.
echo "--- IndexNow ping (maksavit) ---"
cd "$DEPLOY" && docker compose exec -T backend python -m scripts.indexnow_ping /tmp/indexnow_changed_maksavit.txt || echo "IndexNow ping failed (non-fatal)"

# Алерт при резком падении (>20%).
if [ "${AFTER_TOTAL:-0}" -lt $((BEFORE_TOTAL * 80 / 100)) ]; then
  echo "ALERT: maksavit records dropped from $BEFORE_TOTAL to $AFTER_TOTAL (>20% loss)"
  exit 3
fi
