#!/usr/bin/env bash
# Ежедневный переобход страниц через API Яндекс.Вебмастера (470/день).
# Скрипт сам берёт следующие 470 URL из приоритетной очереди (новые города,
# по популярности) и отмечает отправленные. Квота сбрасывается в 00:00 МСК
# (21:00 UTC) — запускаемся в 22:00 UTC, когда квота свежая.
set -euo pipefail
LOG_DIR=/var/log/aptekaa
mkdir -p "$LOG_DIR"
LOG="${LOG_DIR}/recrawl-$(date +%Y%m%d).log"
exec >> "$LOG" 2>&1
echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | recrawl start ==="
LOCK=/var/lock/aptekaa_recrawl.lock
exec 9>"$LOCK" || exit 1
if ! flock -n 9; then echo "WARN: previous recrawl running, skip"; exit 0; fi
cd /home/ubuntu/aptekaa/deploy
docker compose exec -T backend python -m scripts.recrawl_daily --limit 470
echo "=== $(date -u +'%Y-%m-%d %H:%M:%S UTC') | recrawl done ==="
