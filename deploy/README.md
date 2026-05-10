# 🚀 Деплой АптекаА — пошаговая инструкция

Сервер: **`89.169.137.36`** (Yandex Cloud, Ubuntu 22.04, Docker уже установлен)

## Шаг 1 — Зайти на сервер и склонировать репозиторий

С вашего Mac:
```bash
ssh ubuntu@89.169.137.36
```

На сервере:
```bash
cd ~
git clone https://<TOKEN>@github.com/den3992/aptekaappoisksite.git aptekaa
cd aptekaa/deploy
```

(Замените `<TOKEN>` на ваш `github_pat_...`. Этот токен временный — после клонирования его можно отозвать и сгенерировать новый.)

## Шаг 2 — Создать .env

```bash
cp .env.example .env
nano .env
```

Сгенерируйте надёжные пароли:
```bash
# Mongo password
openssl rand -base64 32 | tr -d '/+=' | head -c 40

# Admin token (уже есть, можно оставить тот же или сгенерировать новый)
openssl rand -base64 32 | tr -d '/+=' | head -c 40
```

Заполните в `.env`:
- `MONGO_PASSWORD` — сгенерированный 40-символьный
- `ADMIN_TOKEN` — сгенерированный 40-символьный (или оставьте текущий)
- `REACT_APP_YANDEX_MAPS_KEY` — ваш ключ Яндекс.Карт (из Я.Кабинета разработчика)
- Остальные значения уже заполнены и проверены

Сохранить: `Ctrl+O`, `Enter`, `Ctrl+X`.

## Шаг 3 — Настроить DNS в REG.RU

Откройте `DNS.md` и пошагово сделайте все правки в DNS-зоне обоих доменов. **Можно сделать это сейчас, до запуска деплоя** — DNS пропагирует пока скрипт работает.

Проверка через 10-30 минут:
```bash
dig aptekaa.ru +short
# Должно вернуть: 89.169.137.36
```

## Шаг 4 — Запуск деплоя

```bash
chmod +x deploy.sh backup.sh
sudo ./deploy.sh
```

Скрипт автоматически:
1. Поднимет Mongo, backend, frontend, edge-nginx (HTTP-only)
2. Получит SSL-сертификаты от Let's Encrypt для обоих доменов
3. Переключит nginx на полную HTTPS-конфигурацию
4. Запустит IMAP-воркер
5. Импортирует MDLP-реестр (~3 минуты)
6. Засидит партнёрские аптеки
7. Зарегистрирует cron на автообновление SSL и автобэкап Mongo

⏱️ Полное время деплоя: **~7-10 минут**.

## Шаг 5 — Проверка

```bash
curl -sI https://aptekaa.ru | head -5
# Должно вернуть HTTP/2 200

curl -s https://aptekaa.ru/api/cities
# Должно вернуть JSON со списком городов
```

В браузере:
- https://aptekaa.ru — главная
- https://www.aptekaa.ru — должен 301 на aptekaa.ru
- https://аптекаа.рф — должен 301 на aptekaa.ru
- https://aptekaa.ru/partner-admin?token=... — админка (с правильным токеном)

## Шаг 6 — После деплоя

### LLM-обогащение топ-1000 препаратов
```bash
docker compose exec backend python -m scripts.enrich_meds --limit 1000
```

### Регистрация в Яндекс.Вебмастере
`https://webmaster.yandex.ru/`:
1. Добавить сайт `https://aptekaa.ru`
2. Подтвердить владение (HTML-метатег или TXT-запись — выбирайте удобный)
3. Указать sitemap: `https://aptekaa.ru/sitemap.xml`
4. Через 24-48 часов Яндекс начнёт индексацию

### Регистрация в Яндекс.Бизнесе
`https://business.yandex.ru/` — добавьте организацию для повышения видимости в Картах и поиске.

## Полезные команды

```bash
# Логи
docker compose logs -f backend
docker compose logs -f imap_worker
docker compose logs -f edge

# Перезапуск
docker compose restart backend
docker compose restart edge

# Обновить код после push в GitHub
cd ~/aptekaa && git pull && cd deploy && docker compose up -d --build

# Бэкап вручную
./backup.sh
ls /var/backups/aptekaa/

# Восстановление из бэкапа
docker compose exec -T mongo mongorestore --username "$MONGO_USER" --password "$MONGO_PASSWORD" --authenticationDatabase admin --gzip --archive < /var/backups/aptekaa/mongo-XXXX.archive.gz
```

## Возможные проблемы

### `certbot` не может получить сертификат
- Убедитесь, что DNS уже распространился: `dig aptekaa.ru +short` должен вернуть `89.169.137.36`
- Проверьте, что порт 80 открыт: `sudo ufw status` (должен быть allow 80/tcp)
- Лог: `docker compose run --rm certbot logs`

### Frontend показывает «502 Bad Gateway»
- Подождите 30 секунд (контейнер запускается)
- Логи: `docker compose logs frontend`

### IMAP-воркер не подключается
- Проверьте `IMAP_PASSWORD` в `.env` — должен быть App Password из Я.360
- Попробуйте вручную: `docker compose run --rm backend python -c "import imaplib; m=imaplib.IMAP4_SSL('imap.yandex.ru',993); m.login('price@aptekaa.ru','PASSWORD'); print('OK')"`

### Mongo не запускается
- Проверьте, что `MONGO_PASSWORD` не содержит спецсимволов `:`, `/`, `@`, `?`
- Лог: `docker compose logs mongo`
