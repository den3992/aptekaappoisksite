#!/usr/bin/env bash
# Rebuild + warm-up для Next.js контейнера.
#
# Что делает:
# 1. Пересобирает образ deploy-next.
# 2. Перезапускает контейнер.
# 3. Прогревает ключевые роуты (Next.js делает JIT-компиляцию роутов on-demand:
#    первый запрос к холодному роуту платит 1–2 с компиляции SSR). Без прогрева
#    первый посетитель (или поисковой бот) после rebuild ловит этот штраф.
#
# Использование: bash ~/aptekaa/deploy/rebuild-next.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Building deploy-next"
sudo docker compose -f docker-compose.yml build next

echo "==> Recreating deploy-next-1"
sudo docker compose -f docker-compose.yml up -d --force-recreate next

# Ждём, пока next начнёт отвечать на 3000 (получаем IP контейнера во внутренней
# сети, прокидываемся через temp-контейнер).
echo "==> Waiting for next to become ready"
NEXT_IP=$(sudo docker inspect deploy-next-1 \
  -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
for i in $(seq 1 30); do
  if sudo docker run --rm --network deploy_internal curlimages/curl:latest \
       -s -o /dev/null -w '%{http_code}' --max-time 3 "http://${NEXT_IP}:3000/msk" \
       2>/dev/null | grep -qE '^(200|307)$'; then
    echo "  ✓ next responds after ${i}s"
    break
  fi
  sleep 1
done

# Warm-up список — самые важные роуты, плюс несколько вариантов параметризованных
# страниц, чтобы их шаблоны тоже скомпилировались.
echo "==> Warming up routes"
ROUTES=(
  "/"
  "/msk"
  "/spb"
  "/msk/kategorii"
  "/spb/kategorii"
  "/msk/kategorii/obezbolivayuschie"
  "/msk/preparaty/nurofen-200-mg-tabletki-pokrytye-obolochkoy"
  "/msk/apteki/gorzdrav"
  "/msk/poisk"
  "/o-servise"
  "/kontakty"
  "/politika-konfidencialnosti"
  "/soglasie-na-obrabotku-pd"
  "/robots.txt"
  "/sitemap.xml"
)

OK=0
FAIL=0
for r in "${ROUTES[@]}"; do
  CODE=$(sudo docker run --rm --network deploy_internal curlimages/curl:latest \
    -s -o /dev/null -w '%{http_code} %{time_total}' --max-time 30 \
    "http://${NEXT_IP}:3000${r}" 2>/dev/null || echo "000 0")
  HTTP=$(echo "$CODE" | awk '{print $1}')
  TIME=$(echo "$CODE" | awk '{printf "%.2f", $2}')
  if [[ "$HTTP" =~ ^(200|307|308)$ ]]; then
    printf "  ✓ %3s  %ss  %s\n" "$HTTP" "$TIME" "$r"
    OK=$((OK+1))
  else
    printf "  ✗ %3s  %ss  %s\n" "$HTTP" "$TIME" "$r"
    FAIL=$((FAIL+1))
  fi
done

echo "==> Warm-up done: $OK ok, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
