#!/bin/bash
# Daily MongoDB backup for aptekaa.ru.
#
# Creates a gzipped dump in /var/backups/aptekaa-mongo/ and keeps the last 14
# days. Rotation is done before dumping so we always keep ≥1 fresh backup
# even if the dump itself fails.
#
# Cron: 0 3 * * * /opt/aptekaa/scripts/mongo-backup.sh >> /var/log/aptekaa-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="/var/backups/aptekaa-mongo"
RETENTION_DAYS=14
ENV_FILE="/home/ubuntu/aptekaa/deploy/.env"

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

# Rotate first (so we always keep at least one previous backup if today fails).
find "$BACKUP_DIR" -name 'aptekaa-*.archive.gz' -mtime "+$RETENTION_DAYS" -delete

STAMP=$(date +%Y%m%d-%H%M%S)
TARGET="$BACKUP_DIR/aptekaa-$STAMP.archive.gz"
TMP="${TARGET}.tmp"

echo "[$(date -Is)] Starting backup → $TARGET"

# mongodump archive format is a single binary stream; pipe to gzip.
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

# Human-readable size
HUMAN=$(numfmt --to=iec --suffix=B --format="%.1f" "$SIZE")
echo "[$(date -Is)] DONE: $TARGET ($HUMAN)"
echo "[$(date -Is)] Existing backups:"
ls -lh "$BACKUP_DIR" | tail -20
