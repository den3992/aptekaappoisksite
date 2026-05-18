#!/usr/bin/env bash
# Reliable frontend rebuild — explicitly passes REACT_APP_* build args.
#
# Why: `docker compose build` with BuildKit sometimes ignores args declared
# only via the `args:` block in docker-compose.yml (env interpolation works
# in `docker compose config`, but not always reaches the build stage). Symptom:
# REACT_APP_YANDEX_MAPS_KEY ends up empty inside the build container, so
# the Yandex Maps script tag is rendered without `apikey=` and the map breaks
# on production med pages.
#
# Always run via this script after frontend code changes:
#   bash ~/aptekaa/deploy/rebuild-frontend.sh
set -euo pipefail
cd "$(dirname "$0")"
set -a; source ./.env; set +a
sudo -E docker compose -f docker-compose.yml build \
  --build-arg "REACT_APP_YANDEX_MAPS_KEY=${REACT_APP_YANDEX_MAPS_KEY:?missing}" \
  --build-arg "REACT_APP_BACKEND_URL=${REACT_APP_BACKEND_URL:?missing}" \
  --build-arg "REACT_APP_YANDEX_TILES_KEY=${REACT_APP_YANDEX_TILES_KEY:-}" \
  frontend
sudo docker compose -f docker-compose.yml up -d --force-recreate frontend

# Smoke-test: bundle on prod URL must contain the apikey
sleep 5
BUNDLE=$(curl -ksL "https://aptekaa.ru/" | grep -oE "static/js/main\.[a-f0-9]+\.js" | head -1)
if curl -ks "https://aptekaa.ru/$BUNDLE" | grep -q "${REACT_APP_YANDEX_MAPS_KEY%-*}"; then
  echo "✓ bundle $BUNDLE contains Yandex Maps apikey"
else
  echo "✗ ERROR: bundle $BUNDLE does NOT contain apikey — map will be broken!"
  exit 1
fi
