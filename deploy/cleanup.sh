#!/usr/bin/env bash
# Уборка VM aptekaa: docker-кэш, разовые скрипты, нулевые логи, осиротевшие циклы.
# КОНСЕРВАТИВНО: удаляет только известные паттерны с возрастным фильтром; данные
# (Mongo), код репо и работающие крон-парсеры НЕ трогает. Данные prices_real
# (price<=0 и т.п.) — только отчёт, чистка руками осознанно.
#
# Usage:
#   cleanup.sh          # отчёт + уборка
#   cleanup.sh --dry    # только отчёт, ничего не удалять
set -uo pipefail
DRY=0; [ "${1:-}" = "--dry" ] && DRY=1
say(){ echo "[cleanup] $*"; }
run(){ if [ "$DRY" = 1 ]; then say "DRY: $*"; else eval "$*"; fi; }

say "=== ДИСК ==="
df -h / | tail -1
USE=$(df --output=pcent / | tail -1 | tr -dc 0-9)

say "=== 1. Docker build-кэш/dangling (чистим при диске >75%, иначе отчёт) ==="
docker system df | head -5
if [ "$USE" -gt 75 ]; then
  run "docker builder prune -af --filter until=72h | tail -1"
  run "docker image prune -f | tail -1"
else
  say "диск ${USE}% — docker-кэш не трогаем (порог 75%)"
fi

say "=== 2. Разовые скрипты/дампы в /tmp старше 7 дней (наши паттерны) ==="
PATTERNS="fk_* mk_* rg_* pw_* dbg_* lh_* wm_* bug_hunt* hydr_* diff_* map_scroll* seo1_* fix_* lazy_* cwv_* cleanup_probe* mkcl.json goods*.txt harvest_out*.json *_ssr.html cat_ssr.html sam_ssr.html s1.html s2.html s3.html kzn_*.txt fk_*.html mk_home.html fk_spot.txt"
CNT=0
for p in $PATTERNS; do
  for f in /tmp/$p; do
    [ -f "$f" ] || continue
    if [ "$(find "$f" -mtime +7 2>/dev/null | wc -l)" -gt 0 ]; then
      run "rm -f '$f'"; CNT=$((CNT+1))
    fi
  done
done
say "удалено (или к удалению) из /tmp: $CNT файлов старше 7 дней"

say "=== 3. Нулевые логи /var/log/aptekaa старше 3 дней (артефакт logrotate) ==="
Z=$(find /var/log/aptekaa -name "*.log" -size 0 -mtime +3 2>/dev/null | wc -l)
run "find /var/log/aptekaa -name '*.log' -size 0 -mtime +3 -delete"
say "нулевых логов удалено: $Z"

say "=== 4. Логи старше 30 дней (сверх logrotate rotate 14 — датированные имена множатся) ==="
OLD=$(find /var/log/aptekaa -name "*.log*" -mtime +30 2>/dev/null | wc -l)
run "find /var/log/aptekaa -name '*.log*' -mtime +30 -delete"
say "старых логов удалено: $OLD"

say "=== 5. Осиротевшие bash-циклы (until-поллеры) старше 6 часов — ОТЧЁТ + kill ==="
# ВАЖНО: паттерн ловит только bash -c c 'until' — крон-парсеры (python/docker) не матчатся.
ps -eo pid,etimes,cmd | awk '$2>21600 && /bash -c/ && /until/ && !/awk/' | while read -r pid et cmd; do
  say "  осиротевший цикл pid=$pid age=$((et/3600))h: $(echo "$cmd" | head -c 80)"
  run "kill $pid"
done

say "=== 6. Мусор в backend-контейнере (наши docker cp: /app/*.py вне scripts/, /tmp) ==="
docker exec deploy-backend-1 sh -c '
  ls /app/dbg_*.py /app/fk_*.py /app/fk_*.json /app/mk_*.py /app/rg_*.py /app/rg_*.js /app/wm_*.py /app/load*.py 2>/dev/null
' | while read -r f; do run "docker exec deploy-backend-1 rm -f '$f'"; done
say "контейнер: разовые скрипты убраны (данные/скрипты образа не тронуты)"

say "=== 7. ОТЧЁТ (только отчёт, руками): мусорные записи БД ==="
MONGO_PW="$(grep '^MONGO_PASSWORD=' /home/ubuntu/aptekaa/deploy/.env | cut -d= -f2-)"
docker exec -e MONGO_PW="$MONGO_PW" deploy-mongo-1 sh -c '
  mongosh --quiet -u aptekaa_admin -p "$MONGO_PW" --authenticationDatabase admin aptekaa --eval "
    print(\"  prices_real price=0 (госпитальные, безвредны, копятся): \"+db.prices_real.countDocuments({price:0}));
    print(\"  prices_real not_found/no_match записей: \"+db.prices_real.countDocuments({match_status:{\$in:[\"not_found\",\"no_match\"]}}));
  "' 2>/dev/null

say "=== ИТОГ ==="
df -h / | tail -1
say "готово"
