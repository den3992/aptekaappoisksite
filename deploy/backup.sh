#!/usr/bin/env bash
# Daily MongoDB backup → /var/backups/aptekaa (locally on the VM, retention 14 days).
# Можно расширить на загрузку в Yandex Object Storage позже (mc / aws s3 cp).

set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a

BACKUP_DIR="/var/backups/aptekaa"
mkdir -p "$BACKUP_DIR"
STAMP=$(date -u +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/mongo-$STAMP.archive.gz"

echo "[backup] $(date) — создание дампа $OUT"
docker compose exec -T mongo mongodump \
    --username "$MONGO_USER" \
    --password "$MONGO_PASSWORD" \
    --authenticationDatabase admin \
    --db "$MONGO_DB" \
    --archive --gzip > "$OUT"

# Хранение последних 14 архивов
ls -1t "$BACKUP_DIR"/mongo-*.archive.gz 2>/dev/null | tail -n +15 | xargs -r rm -f

SIZE=$(du -h "$OUT" | awk '{print $1}')
echo "[backup] $(date) — готово, размер $SIZE"
