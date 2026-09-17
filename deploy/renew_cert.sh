#!/usr/bin/env bash
set -Eeuo pipefail

cd /home/ubuntu/aptekaa/deploy

exec 9>/tmp/aptekaa-certbot-renew.lock
flock -n 9 || exit 0

docker compose run --rm \
  --entrypoint certbot certbot \
  renew --non-interactive --no-random-sleep-on-renew

docker compose exec -T edge nginx -t
docker compose exec -T edge nginx -s reload
