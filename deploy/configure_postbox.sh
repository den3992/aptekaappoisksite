#!/usr/bin/env bash
# Safely store Yandex Cloud Postbox SMTP credentials in deploy/.env.
# Values are entered interactively and never appear in shell history.

set -euo pipefail

cd "$(dirname "$0")"
ENV_FILE="$(pwd)/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Ошибка: $ENV_FILE не найден" >&2
  exit 1
fi

read -r -p "ID API-ключа Postbox: " POSTBOX_KEY_ID
read -r -s -p "Секрет API-ключа Postbox: " POSTBOX_KEY_SECRET
echo

if [[ -z "$POSTBOX_KEY_ID" || -z "$POSTBOX_KEY_SECRET" ]]; then
  echo "Ошибка: ID и секрет не могут быть пустыми" >&2
  exit 1
fi

# API keys contain only URL-safe characters. Reject whitespace or shell syntax
# so the resulting dotenv file stays unambiguous when sourced by deploy.sh.
if [[ ! "$POSTBOX_KEY_ID" =~ ^[A-Za-z0-9._~-]+$ ]] ||
   [[ ! "$POSTBOX_KEY_SECRET" =~ ^[A-Za-z0-9._~-]+$ ]]; then
  echo "Ошибка: ключ содержит неожиданные символы" >&2
  exit 1
fi

TMP_FILE="$(mktemp "${ENV_FILE}.postbox.XXXXXX")"
trap 'rm -f "$TMP_FILE"' EXIT

awk '!/^(LEAD_SMTP_HOST|LEAD_SMTP_PORT|LEAD_SMTP_USER|LEAD_SMTP_PASSWORD|LEAD_SMTP_SECURITY|LEAD_FROM_EMAIL|LEAD_EMAIL)=/' \
  "$ENV_FILE" > "$TMP_FILE"

{
  printf '\n# Yandex Cloud Postbox — заявки с сайта\n'
  printf 'LEAD_SMTP_HOST=postbox.cloud.yandex.net\n'
  printf 'LEAD_SMTP_PORT=587\n'
  printf 'LEAD_SMTP_USER=%s\n' "$POSTBOX_KEY_ID"
  printf 'LEAD_SMTP_PASSWORD=%s\n' "$POSTBOX_KEY_SECRET"
  printf 'LEAD_SMTP_SECURITY=starttls\n'
  printf 'LEAD_FROM_EMAIL=info@aptekaa.ru\n'
  printf 'LEAD_EMAIL=info@aptekaa.ru\n'
} >> "$TMP_FILE"

chmod --reference="$ENV_FILE" "$TMP_FILE"
chown --reference="$ENV_FILE" "$TMP_FILE"
mv -f "$TMP_FILE" "$ENV_FILE"
trap - EXIT

unset POSTBOX_KEY_ID POSTBOX_KEY_SECRET
echo "Postbox настроен. Секрет сохранён в deploy/.env."
