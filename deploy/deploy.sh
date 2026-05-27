#!/usr/bin/env bash
# АптекаА — production deploy script for Yandex Cloud VM
# Usage: bash deploy.sh [--reimport-mdlp]
#
# Pre-requisites already done by hand:
#   • Ubuntu 22.04 server with docker installed (this is your case)
#   • DNS for aptekaa.ru, www.aptekaa.ru, xn--80aerl0afi.xn--p1ai pointing to this server
#   • /app/deploy/.env file populated (script auto-creates skeleton if missing)

set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
log()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $*"; }
err()  { echo -e "${RED}[deploy]${NC} $*" >&2; }

# ────────────────────────────────────────────────────────────────
# 1. .env validation
# ────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    err ".env не найден в /home/ubuntu/aptekaa/deploy/. Скопируйте .env.example → .env и заполните перед запуском."
    exit 1
fi
set -a; source .env; set +a

REQUIRED=(MONGO_USER MONGO_PASSWORD MONGO_DB ADMIN_TOKEN EMERGENT_LLM_KEY YANDEX_API_KEY YANDEX_FOLDER_ID
          IMAP_USER IMAP_PASSWORD SMTP_USER SMTP_PASSWORD REACT_APP_BACKEND_URL REACT_APP_YANDEX_MAPS_KEY
          LETSENCRYPT_EMAIL CORS_ORIGINS)
for v in "${REQUIRED[@]}"; do
    if [ -z "${!v:-}" ]; then err "Не задана обязательная переменная: $v"; exit 1; fi
done
log "Проверка .env: OK"

# ────────────────────────────────────────────────────────────────
# 2. Bootstrap nginx (HTTP only) — нужно для получения сертификата
# ────────────────────────────────────────────────────────────────
log "Запускаем nginx в HTTP-режиме (для ACME-challenge)..."
cp nginx/edge-bootstrap.conf nginx/active.conf
docker compose up -d --build edge backend next mongo
sleep 5

# ────────────────────────────────────────────────────────────────
# 3. Получаем SSL сертификат от Let's Encrypt
# ────────────────────────────────────────────────────────────────
if [ ! -f /var/lib/docker/volumes/deploy_certbot_etc/_data/live/aptekaa.ru/fullchain.pem ]; then
    log "Запрашиваем SSL у Let's Encrypt для aptekaa.ru, www.aptekaa.ru..."
    # Примечание: xn--80aerl0afi.xn--p1ai (аптекаа.рф) исключён — DNS на момент
    # первого деплоя ещё пропагировал. Добавить отдельно через certbot --expand,
    # когда DNS для .рф-домена прогреется глобально.
    docker compose run --rm certbot \
        certbot certonly --webroot -w /var/www/certbot \
        -d aptekaa.ru -d www.aptekaa.ru \
        --email "${LETSENCRYPT_EMAIL}" --agree-tos --non-interactive --no-eff-email
    log "Сертификат получен ✅"
else
    log "Сертификат уже существует, переиспользуем"
fi

# ────────────────────────────────────────────────────────────────
# 4. Переключаем nginx на полную SSL-конфигурацию
# ────────────────────────────────────────────────────────────────
log "Переключаем nginx на HTTPS-конфигурацию..."
cp nginx/edge-ssl.conf nginx/active.conf
docker compose up -d edge
sleep 3

# ────────────────────────────────────────────────────────────────
# 5. Запускаем backend, next, imap_worker
# ────────────────────────────────────────────────────────────────
log "Поднимаем backend, next, imap_worker..."
docker compose up -d --build

# ────────────────────────────────────────────────────────────────
# 6. Импорт MDLP (один раз) и обогащение карточек (опционально)
# ────────────────────────────────────────────────────────────────
if docker compose exec -T mongo mongosh --quiet --username "${MONGO_USER}" --password "${MONGO_PASSWORD}" --authenticationDatabase admin "${MONGO_DB}" --eval "db.medications.countDocuments({})" 2>/dev/null | grep -qE '^[0-9]+$'; then
    COUNT=$(docker compose exec -T mongo mongosh --quiet --username "${MONGO_USER}" --password "${MONGO_PASSWORD}" --authenticationDatabase admin "${MONGO_DB}" --eval "print(db.medications.countDocuments({}))")
    log "В Mongo уже ${COUNT} препаратов"
else
    COUNT=0
fi

REIMPORT=0
[[ "${1:-}" == "--reimport-mdlp" ]] && REIMPORT=1

if [ "${COUNT:-0}" -lt 1000 ] || [ "$REIMPORT" -eq 1 ]; then
    log "Запускаем импорт MDLP-реестра (займёт ~3 минуты)..."
    docker compose exec backend python -m scripts.import_mdlp || warn "import_mdlp вернул ошибку — проверьте логи"
fi

log "Поддерживаем сидинг партнёрских аптек..."
docker compose exec backend python -m scripts.seed_pharmacy_tokens || true

# ────────────────────────────────────────────────────────────────
# 7. Cron: автообновление SSL и автобэкап Mongo
# ────────────────────────────────────────────────────────────────
log "Регистрируем cron-задачи (renew SSL + backup mongo)..."
CRON_RENEW="0 4 * * * cd $(pwd) && docker compose run --rm certbot renew --quiet && docker compose exec edge nginx -s reload >/dev/null 2>&1"
CRON_BACKUP="30 3 * * * cd $(pwd) && bash backup.sh >> /var/log/aptekaa-backup.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'aptekaa-backup\|certbot renew' ; echo "$CRON_RENEW" ; echo "$CRON_BACKUP" ) | crontab -

# ────────────────────────────────────────────────────────────────
# 8. Status
# ────────────────────────────────────────────────────────────────
log "Запущенные контейнеры:"
docker compose ps

echo ""
log "✅ ДЕПЛОЙ ЗАВЕРШЁН"
echo ""
echo "Проверка:"
echo "   curl -sI https://aptekaa.ru | head -5"
echo "   curl -s https://aptekaa.ru/api/cities"
echo ""
echo "Если домен ещё не указывает на этот сервер — настройте DNS в REG.RU по DNS.md"
