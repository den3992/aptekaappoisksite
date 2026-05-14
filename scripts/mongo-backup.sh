#!/bin/bash
# Daily MongoDB backup for aptekaa.ru.
#
# 1. mongodump → gzipped archive in /var/backups/aptekaa-mongo/
# 2. Upload to Yandex Object Storage (s3://aptekaa-mongo-backups/YYYY/MM/...)
# 3. Local retention 14 days; cloud retention 90 days (bucket lifecycle).
#
# Cron: 0 3 * * * root /opt/aptekaa/scripts/mongo-backup.sh >> /var/log/aptekaa-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="/var/backups/aptekaa-mongo"
RETENTION_DAYS=14
ENV_FILE="/home/ubuntu/aptekaa/deploy/.env"
S3_ENV="/etc/aptekaa/s3-backup.env"

mkdir -p "$BACKUP_DIR"

if [[ -f "$ENV_FILE" ]]; then
    MONGO_PASSWORD=$(grep '^MONGO_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)
else
    echo "[$(date -Is)] ERROR: env file not found: $ENV_FILE" >&2
    exit 1
fi

if [[ -z "${MONGO_PASSWORD:-}" ]]; then
    echo "[$(date -Is)] ERROR: MONGO_PASSWORD is empty" >&2
    exit 1
fi

# Rotate local first (so we always keep ≥1 previous backup if today fails).
find "$BACKUP_DIR" -name 'aptekaa-*.archive.gz' -mtime "+$RETENTION_DAYS" -delete

STAMP=$(date +%Y%m%d-%H%M%S)
TARGET="$BACKUP_DIR/aptekaa-$STAMP.archive.gz"
TMP="${TARGET}.tmp"

echo "[$(date -Is)] Starting backup → $TARGET"

docker exec deploy-mongo-1 \
    mongodump \
        --uri="mongodb://aptekaa_admin:${MONGO_PASSWORD}@localhost:27017/aptekaa?authSource=admin" \
        --archive \
        --gzip \
    > "$TMP"

SIZE=$(stat -c%s "$TMP")
if (( SIZE < 1024 )); then
    echo "[$(date -Is)] ERROR: backup size ${SIZE} bytes — too small, refusing"
    rm -f "$TMP"
    exit 1
fi

mv "$TMP" "$TARGET"
chmod 600 "$TARGET"

HUMAN=$(numfmt --to=iec --suffix=B --format="%.1f" "$SIZE")
echo "[$(date -Is)] Local OK: $TARGET ($HUMAN)"

# ---- Upload to Yandex Object Storage ----
if [[ -f "$S3_ENV" ]]; then
    set -a
    . "$S3_ENV"
    set +a
    YEAR=$(date +%Y)
    MONTH=$(date +%m)
    S3_KEY="${YEAR}/${MONTH}/aptekaa-${STAMP}.archive.gz"
    if aws --endpoint-url="$S3_ENDPOINT" \
           s3 cp "$TARGET" "s3://${S3_BUCKET}/${S3_KEY}" \
           --no-progress \
           --storage-class STANDARD; then
        echo "[$(date -Is)] Cloud OK: s3://${S3_BUCKET}/${S3_KEY}"
    else
        echo "[$(date -Is)] WARN: cloud upload failed (local backup still kept)"
    fi
else
    echo "[$(date -Is)] WARN: $S3_ENV missing, skipping cloud upload"
fi
