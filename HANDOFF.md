# Handoff Document — АптекаА (поисковик-агрегатор лекарств)

**Дата хендовера:** 10 мая 2026
**Состояние:** Сайт развёрнут в продакшн на https://aptekaa.ru, работает, идёт первая неделя жизни.

---

## 1. О проекте

**АптекаА** — это веб-сервис типа агрегатора цен на лекарства в аптеках Москвы и Санкт-Петербурга. Аналоги: lekmos.ru, 003ms.ru, 009рф, aptekamos.ru.

### Бизнес-модель
- Пользователь ищет препарат → видит карточку → видит цены в **разных аптеках** + карту с пинами → выбирает удобную аптеку
- Аптеки **загружают свои прайс-листы** (XLSX/CSV через web-форму с токеном или через email на price@aptekaa.ru) → сайт показывает их цены
- Монетизация (в будущем): комиссия с аптек / реклама / премиум-размещение

### Целевая аудитория
- Жители Москвы и СПб, ищущие конкретное лекарство «где купить дешевле»
- Аптеки-партнёры, которые хотят больше клиентов

### Юридический и SEO-фокус
- Ориентация на **Яндекс** (95%+ поискового трафика в России)
- Соответствие законам РФ (нет «ЖНВЛП», нет «государственных предельных цен» в UI — пользователь явно просил это убрать)
- Никаких дозировок и медсоветов в LLM-описаниях — только справочная информация и обязательный disclaimer «проконсультируйтесь с врачом»

### Стек
- **Frontend:** React 19, Tailwind CSS, Shadcn/UI, Yandex Maps API
- **Backend:** FastAPI 0.110, Motor (async MongoDB), Python 3.11
- **DB:** MongoDB 7.0 (с auth, в Docker)
- **AI:** OpenAI gpt-4o-mini (через Emergent LLM Key в dev / нужен прямой ключ для продакшена), Yandex SpeechKit TTS (голос «Алёна»)
- **DNS:** REG.RU (оба домена)
- **Хостинг:** Yandex Cloud (Compute Cloud VM)
- **Почта:** Yandex 360 (для бизнеса)

---

## 2. Production Environment

### VPS — Yandex Cloud
| Параметр | Значение |
|---|---|
| **IP (ОБРАТИ ВНИМАНИЕ — ДИНАМИЧЕСКИЙ!)** | `89.169.137.36` |
| **Имя ВМ** | `aptekaa-app` |
| **Зона** | `ru-central1-a` (Москва) |
| **Конфиг** | 2 vCPU 50% (Ice Lake) / 3 GB RAM / 40 GB SSD |
| **ОС** | Ubuntu 22.04 LTS |
| **SSH** | `ssh ubuntu@89.169.137.36` (ключ ed25519, у владельца на Mac) |
| **Стоимость** | ~2793 ₽/мес (тариф май 2026 г.) |
| **Грант Я.Cloud** | 4000 ₽ при регистрации (сейчас тратится) |

⚠️ **Критично:** IP **динамический**. Запрос на статический IP в поддержку Я.Cloud **отправлен**, ждём ответа человека-оператора (робот отказал автоматически — это известный паттерн для свежих аккаунтов). Пока не получили статус «статический» — **не нажимать `Stop`/`Start` ВМ через консоль**, иначе IP сменится и сайт пропадёт. Перезагрузки изнутри (`reboot`) допустимы — IP сохраняется.

### Домены — REG.RU
| Домен | Статус |
|---|---|
| `aptekaa.ru` | ✅ работает на HTTPS, SSL Let's Encrypt |
| `www.aptekaa.ru` | ✅ работает на HTTPS |
| `xn--80aerl0afi.xn--p1ai` (`аптекаа.рф`) | 🟡 куплен (срок до 26.04.2027), DNS пропагирует, SSL пока **не выпущен** |

### DNS-записи (REG.RU, для aptekaa.ru)
```
A     | @                | 89.169.137.36
A     | www              | 89.169.137.36
MX    | @                | 10 mx.yandex.net.
TXT   | @                | yandex-verification: e6a0b158c0131253
TXT   | @                | v=spf1 redirect=_spf.yandex.net
TXT   | _dmarc           | v=DMARC1; p=none; rua=mailto:info@aptekaa.ru
TXT   | mail._domainkey  | v=DKIM1; k=rsa; p=...   ← НУЖНО ПРОВЕРИТЬ, ДОБАВЛЕНО ЛИ ОНО
```

⚠️ **DKIM:** на момент хендовера пользователь добавлял запись DKIM из Я.360 → нужно **проверить** что она прописана. Без DKIM Gmail/Outlook будут метить письма от @aptekaa.ru как спам. См. `https://360.yandex.ru/business` → Домены → DKIM.

### DNS аптекаа.рф (REG.RU)
```
A | @   | 89.169.137.36
A | www | 89.169.137.36
```
(MX/SPF/DKIM не нужны — почты на этом домене нет, делает 301 на aptekaa.ru)

### Email — Yandex 360 (тариф «Базовый», бесплатно, 1 пользователь = 3 ящика)

⚠️ **На самом деле в Я.360 «Базовый» = 1 сотрудник.** У пользователя создано 3 ящика (`info@`, `partners@`, `price@`) — возможно через создание нескольких сотрудников, надо уточнить лимиты при росте команды. Если упрётся в лимит — переход на «Оптимальный» (~249 ₽/мес/пользователь).

| Ящик | Назначение | Где показывается |
|---|---|---|
| `info@aptekaa.ru` | Общие вопросы пользователей | Главная, футер, контакты, юр. страницы |
| `partners@aptekaa.ru` | Связь с аптеками-партнёрами | Страница «Для аптек», подвал |
| `price@aptekaa.ru` | Приём прайс-листов от аптек (IMAP-парсер) | Скрытый, выдаём в личке аптекам |

### IMAP/SMTP креды для price@aptekaa.ru
- IMAP: `imap.yandex.ru:993` (SSL)
- SMTP: `smtp.yandex.ru:465` (SSL)
- App Password: `wpsmkmksenpuxhvl` (16 символов, в `.env` на сервере)
- Подключение проверено ✅

⚠️ **Старая почта на Mail.ru** — была настроена параллельно, но **MX переключены на Я.360**, Mail.ru-почта больше не получает письма на `@aptekaa.ru`. Пользователь сам сказал «забываем».

---

## 3. Учётные данные (внутренние, никуда наружу не пускаются)

### `/app/memory/test_credentials.md` — самый актуальный источник

### Admin URL — управление заявками партнёров
- URL: `https://aptekaa.ru/partner-admin?token=Aa9k3xR-admin-token-2026-aptekaa`

⚠️ Старый dev-токен в Mongo (`Aa9k3xR-admin-token-2026-aptekaa`). На проде в `/home/ubuntu/aptekaa/deploy/.env` сейчас стоит **новый** токен `TCkwKsYaekNAJiBHoL8qjxNGsx4XX7PsiQye7WPy` — фронт скомпилирован с этим. **Используй новый.**

### Mongo (на проде, в Docker, доступ только из контейнеров)
- User: `aptekaa_admin`
- Password: `OkGaeGlcEqdsyGClit9BmphgiRTFeep50rwVgpcO`
- DB: `aptekaa`
- Команда подключения с сервера:
  ```bash
  cd ~/aptekaa/deploy && sudo docker compose exec -T mongo mongosh \
    --quiet --username aptekaa_admin \
    --password "OkGaeGlcEqdsyGClit9BmphgiRTFeep50rwVgpcO" \
    --authenticationDatabase admin aptekaa --eval "db.medications.countDocuments({})"
  ```

### Yandex API
- Yandex Maps API key: `7944c49c-fc62-4d36-ba40-b20f6fbf0461` (в `frontend/.env` и в `.env` на сервере)
- Yandex SpeechKit API key: `AQVNxtHJbWmC9hZhIPllev9Ef6jUVZCSCyTsebDK`
- Yandex Folder ID: `b1gspgmnrl8f6vkll8oc`

### Emergent LLM Key
- `sk-emergent-621E4C65aF48cF6528`
- ⚠️⚠️⚠️ **РАБОТАЕТ ТОЛЬКО ВНУТРИ EMERGENT-ИНФРАСТРУКТУРЫ** (preview-окружения). С production-сервера в Я.Cloud **отдаёт 403 Forbidden**. Это известное ограничение Emergent — ключ привязан к их IP-сетям.

### GitHub
- Репо: `https://github.com/den3992/aptekaappoisksite` (приватный)
- На момент хендовера PAT для клонирования был передан в чат (`github_pat_11AZUHSTI...`) — **обязательно отозвать** на `github.com/settings/tokens` и сгенерировать новый при необходимости.

---

## 4. Архитектура кода

### Backend (`/app/backend/`)

```
backend/
├── server.py                         # FastAPI app, voice/chat, voice/tts, основные роуты
├── security.py                       # SecurityHeadersMiddleware, verify_admin (X-Admin-Token)
├── voice_data.py                     # System prompts для AI-ассистента
├── api/
│   ├── __init__.py                   # Catalog API: /api/search, /api/categories, /api/medications/{slug}, /api/cities, /api/pharmacies
│   ├── seo.py                        # /api/seo/sitemap.xml, /api/seo/robots.txt, SSR для YandexBot/Googlebot
│   ├── uploads.py                    # POST /api/upload/prices/{token} — XLSX/CSV upload, парсинг, обновление prices[]
│   └── partners.py                   # POST /api/partner-requests, admin endpoints
├── scripts/
│   ├── import_mdlp.py                # Импорт реестра ЛС (XLSX) → 23303 препарата
│   ├── seed_pharmacy_tokens.py       # Сидинг 20 партнёрских аптек (Москва + СПб)
│   ├── enrich_meds.py                # LLM-обогащение: показания, противопоказания (gpt-4o-mini)
│   └── email_imap_worker.py          # IMAP-воркер для приёма прайсов на price@aptekaa.ru
├── data/                             # XLSX реестр MDLP (большой, в репо НЕ лежит — генерируется import_mdlp)
└── requirements.txt
```

### Frontend (`/app/frontend/`)

```
frontend/src/
├── App.js                            # Router, layout
├── api/client.js                     # axios + searchMeds, fetchCategories, suggestMeds, etc.
├── pages/
│   ├── Home.jsx                      # Главная: поиск, популярные препараты, категории, аптеки
│   ├── Search.jsx                    # /search?q=...
│   ├── MedDetail.jsx                 # Карточка препарата + Y.Maps + блок «О препарате» (LLM)
│   ├── Catalog.jsx                   # А-Я каталог с пагинацией
│   ├── Categories.jsx, CategoryDetail.jsx
│   ├── PharmaciesList.jsx, PharmacyDetail.jsx
│   ├── ForPharmacies.jsx             # Лендинг + форма заявки партнёра
│   ├── PartnerUpload.jsx             # /partner-upload?token=... — загрузка XLSX
│   ├── PartnerAdmin.jsx              # /partner-admin?token=ADMIN_TOKEN — модерация заявок
│   └── (юр. страницы: Privacy, Terms, About, Contacts)
├── components/
│   ├── VoiceAssistant.jsx, CallView.jsx   # AI-ассистент с голосом «Алёна»
│   ├── SEOHead.jsx                   # SEO-метатеги
│   ├── CategoryIcon.jsx, PartnersMarquee.jsx, PillIcon.jsx
│   └── ui/                           # Shadcn компоненты
├── lib/
│   ├── ymaps.js                      # Загрузка Yandex Maps API
│   └── categoryStyles.js             # Иконки/цвета категорий (статика)
├── context/CityContext.jsx           # Москва/СПб
└── seo.js                            # SEO-генераторы для каждой страницы
```

### Ключевые API endpoints
```
GET  /api/cities
GET  /api/categories
GET  /api/search?q=...&category=...&prefix=А&page=1&page_size=24
GET  /api/search/suggest?q=...
GET  /api/medications/{slug}
GET  /api/pharmacies?city=msk
GET  /api/pharmacies/{id}

POST /api/voice/chat              # AI-ассистент, rate-limit 20/min
POST /api/voice/tts               # Yandex SpeechKit TTS, rate-limit 30/min

POST /api/partner-requests        # Форма «Для аптек», rate-limit 5/час
GET  /api/admin/partner-requests             # X-Admin-Token header
POST /api/admin/partner-requests/{rid}/approve
POST /api/admin/partner-requests/{rid}/reject
GET  /api/admin/partner-requests/{token}     # legacy (для совместимости PartnerAdmin.jsx)

GET  /api/upload/me/{token}       # Аптека: проверка токена
POST /api/upload/prices/{token}   # Аптека: загрузка XLSX/CSV (rate-limit 10/час)
GET  /api/upload/history/{token}
GET  /api/upload/unmatched/{token}

GET  /api/seo/sitemap.xml
GET  /api/seo/robots.txt
GET  /api/seo/render?path=/msk/preparaty/<slug>   # SSR для YandexBot
```

### Схема Mongo
```
medications: {
  slug, name, mnn, form, dosage, manufacturer, manufacturer_country,
  category, rx, vital,
  variants: [{gtin, label_name, ru_number, primary_pack_desc, pack_size}],
  prices: [{pharmacy_id, city, price, qty, updated_at}],
  enrichment: {
    summary, indications[], contraindications[], how_to_take,
    disclaimer, generated_at, model
  }
}

pharmacy_tokens: {pharmacy_id, pharmacy_name, city, chain, token, active, allowed_emails[]}
pharmacy_uploads: {_id, pharmacy_id, filename, size, uploaded_at, parsed_rows, matched, unmatched}
partner_requests: {_id, status, created_at, chain, city, email, phone, count, comment, issued_token, issued_pharmacy_id}
voice_messages: {session_id, role, content, ts}
```

---

## 5. История работы — что сделано (хронология)

### Сессия 1 (10 мая, утро) — Завершение MVP
- Импорт **23 303 препаратов** из MDLP-реестра (грузится скриптом `import_mdlp.py`, ~3 минуты на VPS)
- Полная миграция фронта с `mock.js` на реальное API (Home, Catalog, Categories, Pharmacies, MedDetail). Удалены `mock.js` и `MedCard.jsx`
- Добавлен `?prefix=А` фильтр в `/api/search` для алфавитного каталога
- Создан backend `partner_router` (`POST /api/partner-requests`)
- Тесты: 39/39 ✅

### Сессия 2 (10 мая) — LLM-обогащение и admin-UI
- LLM-обогащение топ-200 препаратов через gpt-4o-mini (показания, противопоказания, способ применения, summary). Скрипт `enrich_meds.py`
- Admin-UI `/partner-admin?token=...` для одобрения/отклонения заявок партнёров
- SSR-блок `«О препарате»` для YandexBot
- Тесты: 48/48 ✅

### Сессия 3 (10 мая) — Security hardening перед деплоем
- **CORS** ограничен whitelist
- **Security headers**: HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
- **Admin auth** через `X-Admin-Token` header + `secrets.compare_digest` (защита от timing-атак); legacy URL-path сохранён
- **Rate limits** (in-memory sliding window per IP):
  - `/api/voice/chat` 20/мин
  - `/api/voice/tts` 30/мин
  - `/api/partner-requests` 5/час
  - `/api/upload/prices/{token}` 10/час
- **Sanitized errors** — больше не светим LLM/TTS stack-trace
- Validation `session_id`, filename uploads
- `.env` теперь в `.gitignore`
- Тесты: 88/88 ✅

### Сессия 4 (10 мая, день) — Подготовка инфраструктуры
- Создана VM в Yandex Cloud (`89.169.137.36`)
- Настроен сервер: UFW, fail2ban, swap 2GB, Docker
- Куплен 2-й домен `аптекаа.рф` (REG.RU, до 26.04.2027)
- Настроен Yandex 360 (3 ящика: info@, partners@, price@)
- Получен App Password для `price@` → IMAP/SMTP проверены
- Создан полный deploy-стек в `/app/deploy/`:
  - `docker-compose.yml` (mongo + backend + frontend + imap_worker + edge-nginx + certbot)
  - `deploy.sh`, `backup.sh`, `nginx/edge-bootstrap.conf`, `nginx/edge-ssl.conf`, `nginx/static.conf`
  - `DNS.md`, `README.md`, `.env.example`
- Удалена страница «Доступные упаковки и формы выпуска» из MedDetail
- Поправлен текст hero-блока на главной

### Сессия 5 (10 мая, вечер) — РЕАЛЬНЫЙ ДЕПЛОЙ
- Push на GitHub
- На сервере: clone, .env, DNS-настройки в REG.RU
- Запуск deploy.sh — несколько проблем устранили на ходу:
  - `.env.example` не попал в репо (gitignore) → создан вручную через `cat > .env << EOF`
  - `frontend/yarn.lock` не было в репо → убрали `--frozen-lockfile` из Dockerfile, yarn создал заново
  - `openpyxl, httpx, imapclient` не было в `requirements.txt` (на Emergent стояли глобально) → добавлены
  - certbot в docker-compose не запускался через `run --rm certbot` → пришлось запросить SSL напрямую через `docker run`
  - SSL получен только для `aptekaa.ru + www`, для `аптекаа.рф` — позже (DNS пропагирует)
  - nginx после переключения на SSL-конфиг не запускался — sed «съел» закрывающую скобку → исправлено awk
  - IMAP-worker падал с `SMTPRecipientsRefused: noreply@id.yandex.ru` → захотфикшено: skip noreply отправители + try/except
- **Импорт MDLP**: 23 303 препарата загружены ✅
- **Перенос enrichment 200→890 документов** (115 уникальных препаратов × все формы): через дамп JSON из preview → push в GitHub → pull на сервер → mongo update_many
- Сайт работает на HTTPS ✅

---

## 6. Текущее состояние

### ✅ Работает
- Сайт `https://aptekaa.ru` (HTTP/2, SSL)
- 23 303 препарата в каталоге
- 890 страниц препаратов с уникальными описаниями (LLM)
- 20 партнёрских аптек с ценами в Москве и СПб
- Голосовой AI-ассистент «Алёна» (Yandex SpeechKit + gpt-4o-mini через Emergent LLM Key)
- Yandex Maps на карточках препаратов
- IMAP-приёмник прайсов от аптек на `price@aptekaa.ru`
- Sitemap + robots.txt + SSR для YandexBot
- Admin-UI заявок партнёров
- Cron на автообновление SSL и автобэкап Mongo

### 🟡 Частично работает / ждёт
- `аптекаа.рф` — DNS пропагирует, SSL ещё не выдан, редирект на основной домен пока через HTTP
- Статический IP — в очереди на одобрение Я.Cloud (запрос отправлен)
- DKIM-запись для Я.360 — не подтверждено, что пользователь добавил в REG.RU
- Регистрация в Яндекс.Вебмастере и Яндекс.Бизнесе — **НЕ сделана**, это критично для индексации

### 🔴 Не работает / ограничения
- **LLM-обогащение с прода невозможно** через Emergent LLM Key (403 Forbidden из РФ-IP). Решения:
  1. Запускать обогащение в preview-окружении Emergent → переливать в прод через JSON-дамп (текущий процесс)
  2. Купить прямой OpenAI-ключ (нужна зарубежная карта) или ProxyAPI (~250 ₽ за $1)

---

## 7. Pending Tasks (приоритезация)

### 🔴 P0 — Срочно (сегодня-завтра)

1. **Регистрация в Яндекс.Вебмастере** (`https://webmaster.yandex.ru`):
   - Добавить сайт `https://aptekaa.ru`
   - Подтвердить владение через TXT-запись в DNS REG.RU
   - Указать sitemap: `https://aptekaa.ru/sitemap.xml`
   - Без этого Яндекс не начнёт индексацию.

2. **Проверить DKIM** для Я.360 (`360.yandex.ru/business` → Домены → DKIM-подпись). Если не подтверждён — взять значение и добавить TXT `mail._domainkey` в REG.RU.

3. **Дождаться квоты на статический IP** Я.Cloud → конвертировать `89.169.137.36` в статический. Очень критично — без этого при любой остановке ВМ сайт ляжет.

4. **Отозвать GitHub PAT** (`github.com/settings/tokens` → найти `aptekaa-server-deploy` → Revoke).

### 🟡 P1 — На неделе

5. **SSL для аптекаа.рф** (когда DNS пропагирует глобально, проверять `dig @8.8.8.8 xn--80aerl0afi.xn--p1ai +short`):
   ```bash
   sudo docker run --rm \
     -v deploy_certbot_etc:/etc/letsencrypt \
     -v deploy_certbot_webroot:/var/www/certbot \
     certbot/certbot:latest \
     certonly --webroot -w /var/www/certbot \
     -d aptekaa.ru -d www.aptekaa.ru -d xn--80aerl0afi.xn--p1ai \
     --email info@aptekaa.ru --agree-tos --non-interactive --no-eff-email --expand
   ```
   Затем добавить server-блок в `/home/ubuntu/aptekaa/deploy/nginx/active.conf` (см. `edge-ssl.conf` — там есть готовый блок для аптекаа.рф) и `sudo docker compose restart edge`.

6. **Регистрация в Яндекс.Бизнесе** (`business.yandex.ru`) — для попадания в Карты + повышение доверия.

7. **Регистрация в Яндекс.Метрике** — счётчик трафика для аналитики поиска (`metrika.yandex.ru`). Нужно установить JS-снипет в `index.html` или через React-компонент.

8. **Удалить из репо файл `deploy/data/enrichment-200.json`** — был временным, сделал своё дело. Также `frontend/public/enrichment-dump.json`.

9. **Проверить `/app/test_credentials.md` на сервере и в Emergent** — синхронизированы ли данные.

### 🟢 P2 — В среднесрочной перспективе

10. **Расширить LLM-обогащение** — сейчас 890 документов / ~115 уникальных препаратов. Можно довести до 1000-2000 уникальных. **Варианты:**
    - Запускать `enrich_meds.py` в Emergent preview → дампить → переливать на прод (как уже делали)
    - Купить прямой OpenAI-ключ (зарубежная карта) или через `proxyapi.ru` (РФ-карта). После этого `EMERGENT_LLM_KEY` в `.env` на сервере заменить на `OPENAI_API_KEY`, и `enrich_meds.py` заработает прямо с продакшена.

11. **Привлечение партнёрских аптек** — холодные продажи, рассылки, посещение аптек. Сейчас 20 партнёров (мокковые/полу-реальные).

12. **Аналитика поисковых запросов** — после Метрики и неделю работы → смотреть какие запросы реально приводят на сайт → обогащать **именно те препараты** (а не все 10 327 наугад).

13. **SFTP-выгрузка прайсов** — для крупных аптечных сетей, у которых уже есть автоматизация.

14. **Покупка трафика?** — пользователь сам сказал «реклама через 3-4 месяца», начинаем с органики.

---

## 8. Operations Cheatsheet (как работать с сервером)

### SSH
```bash
ssh ubuntu@89.169.137.36
cd ~/aptekaa/deploy
```

### Просмотр логов
```bash
sudo docker compose logs backend --tail 50
sudo docker compose logs imap_worker --tail 50
sudo docker compose logs edge --tail 50
sudo docker compose ps                  # статус всех контейнеров
```

### Перезапуск сервисов
```bash
sudo docker compose restart backend
sudo docker compose restart edge
sudo docker compose restart imap_worker
```

### Обновление кода после push в GitHub
```bash
cd ~/aptekaa
git checkout -- backend/requirements.txt   # если были локальные правки
git pull
cd deploy
sudo docker compose build && sudo docker compose up -d
```

### Подключиться к Mongo
```bash
cd ~/aptekaa/deploy && sudo docker compose exec -T mongo mongosh \
  --quiet --username aptekaa_admin \
  --password "OkGaeGlcEqdsyGClit9BmphgiRTFeep50rwVgpcO" \
  --authenticationDatabase admin aptekaa
```

### Бэкапы
- Автоматически: cron каждый день в 03:30 → `/var/backups/aptekaa/mongo-YYYYMMDD.archive.gz`, retention 14 дней
- Вручную: `cd ~/aptekaa/deploy && bash backup.sh`
- Восстановление:
  ```bash
  cd ~/aptekaa/deploy && sudo docker compose exec -T mongo mongorestore \
    --username aptekaa_admin --password "OkGa..." --authenticationDatabase admin \
    --gzip --archive < /var/backups/aptekaa/mongo-XXXX.archive.gz
  ```

### Запустить LLM-обогащение (требует прямого OpenAI-ключа на проде)
```bash
sudo docker compose exec backend python -m scripts.enrich_meds --limit 1000
```

### Сидинг партнёрских аптек (если добавляли новых вручную в код)
```bash
sudo docker compose exec backend python -m scripts.seed_pharmacy_tokens
```

### Перенос enrichment из Emergent preview → прод
1. В Emergent: дампить `medications.find({enrichment: {$exists: true}})` в JSON (slug, name, mnn, enrichment)
2. Положить в `deploy/data/enrichment-XXX.json`
3. Push в GitHub
4. На сервере: `git pull`
5. Импорт через `update_many` (см. историю чата — короткая команда работает)

---

## 9. Известные подводные камни / Lessons Learned

### Эти грабли мы уже наступили — будь осторожен

1. **Emergent LLM Key 403 from outside Emergent IPs** — нельзя использовать с прода. Нужен прямой OpenAI-ключ для масштабирования enrichment.

2. **Я.Cloud квота на статический IP = 0 для новых аккаунтов.** Робот поддержки автоматически отказывает при первом запросе. Нужно идти в человеческую поддержку с обоснованием.

3. **Я.Cloud цены выросли с 1 мая 2026** — расчёты до этой даты были занижены (~750 ₽/мес ожидали, получили ~2800 ₽/мес).

4. **Cloudflare НЕ работает в России** (Роскомнадзор режет TLS ECH с июня 2025). Используем встроенную защиту Я.Cloud + Let's Encrypt + nginx fail2ban. Не предлагай Cloudflare.

5. **Mail.ru DKIM пользователь не довёл до конца** — переключились на Я.360. Не возвращаться к Mail.ru.

6. **`frontend/yarn.lock` отсутствует в репо** (видимо, gitignore ловит) — пришлось убрать `--frozen-lockfile` из Dockerfile. Если делать pip install / yarn install заново, **могут поплыть версии зависимостей**. Желательно зафиксировать `yarn.lock` явно.

7. **`requirements.txt` на момент хендовера НЕ синхронизирован между Emergent /app/backend и проектом на сервере.** Я ходил между ними, добавлял `slowapi`, `openpyxl`, `httpx`, `imap_tools`, `imapclient`. **На прод-сервере в `~/aptekaa/backend/requirements.txt` правильный набор есть.** На Emergent `/app/backend/requirements.txt` — тоже синхронизирован. Но если будешь обновлять — проверь оба места.

8. **Юзер просил убрать ЖНВЛП и государственные предельные цены** — это из политических/юридических соображений, **никогда не возвращай**.

9. **Голос «Алёна» зафиксирован** в Yandex SpeechKit — пользователь его утвердил. Не предлагай ElevenLabs или другие TTS.

10. **`cd ~/aptekaa` под sudo** превращается в `/root/aptekaa` (не `/home/ubuntu/aptekaa`). Использовать абсолютные пути в sudo-командах.

11. **Heredoc (`<< EOF`) в одной строке через ssh иногда не закрывается** — пользователь несколько раз вводил неполные команды и терминал зависал. Лучше многострочные скрипты класть в файл и потом запускать.

12. **DNS пропагация .РФ-доменов медленная** — у `аптекаа.рф` после покупки до глобальной видимости прошло >12 часов.

13. **Эмодзи в файлах — пользователь не возражал, но спросил один раз.** Используй умеренно.

---

## 10. Файлы — куда смотреть в репо

### Самые важные
- `/app/memory/PRD.md` — продакт-роадмап и changelog
- `/app/memory/test_credentials.md` — все креды и токены
- `/app/deploy/README.md` — инструкция по деплою
- `/app/deploy/DNS.md` — настройки REG.RU
- `/app/deploy/deploy.sh` — главный скрипт деплоя
- `/app/deploy/docker-compose.yml` — оркестрация контейнеров
- `/app/deploy/nginx/edge-ssl.conf` — production nginx (после получения SSL)
- `/app/deploy/nginx/edge-bootstrap.conf` — initial HTTP-only nginx (для ACME-challenge)

### Тестовые отчёты (последние)
- `/app/test_reports/iteration_5.json` — security audit, всё green

### Логи последних сессий
- `/app/test_result.md`

---

## 11. Контактные точки клиента / пользователя

- **Имя:** Денис (`den3992` на GitHub, `psyche_99` на Mac)
- **Тон общения:** Русский, по-деловому, без излишних формальностей
- **Принимает решения быстро,** но просит конкретные команды для терминала пошагово (не любит длинные простыни кода — присылать одну команду, ждать ответа, давать следующую)
- **Не любит:** долгое ожидание, лишние вопросы при наличии разумного default'а
- **Любит:** конкретику, цифры, оценку «нужно/не нужно сейчас», варианты с пометкой 🟢 рекомендую
- **Бюджет:** ограниченный, но готов вкладываться в инфраструктуру (купил VPS за 2800₽/мес, второй домен)

---

## 12. Что НЕ нужно делать (anti-patterns)

❌ Не использовать Cloudflare — забанено в РФ
❌ Не возвращать ЖНВЛП и предельные цены
❌ Не предлагать ElevenLabs / VAPI вместо Yandex SpeechKit
❌ Не запускать `enrich_meds.py` напрямую с прод-сервера через Emergent LLM Key — будет 403
❌ Не нажимать Stop/Start ВМ в Я.Cloud, пока IP не статический
❌ Не push'ить `.env` файлы в GitHub (уже в .gitignore, но проверь при больших изменениях)
❌ Не предлагать «давай переделаем архитектуру» — MVP работает, задача — расширять, не переписывать

---

## 13. Финальный совет преемнику

Состояние проекта **стабильное и production-ready**. Главное теперь — это **рост** (SEO, привлечение аптек, расширение LLM-описаний по реальным запросам), а не разработка фич.

**Следующий шаг с большим импактом:**
1. Подтвердить DKIM (5 мин)
2. Зарегистрировать в Я.Вебмастере (15 мин) и Я.Бизнесе (30 мин)
3. Получить статический IP (когда поддержка одобрит)
4. Через неделю-две — расширить enrichment по данным Метрики

**Удачи!** 🍀
