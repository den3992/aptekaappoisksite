# PRD — АптекаА (агрегатор аптек)

## Original problem statement
MVP сайта-агрегатора аптек по образцу lekmos / 003ms / 009рф / aptekamos:
- Минималистичный современный дизайн в зелёно-белой палитре
- Стартовые города: Москва и Санкт-Петербург
- Поиск лекарств (без сложного каталога) с SEO
- Карточка препарата с интеграцией Яндекс.Карт и «облаками цен» (пины с ценами и наличием)
- Раздел «Для аптек» — простая FTP-выгрузка прайсов (xls, xlsx, dbf, csv)
- Юр. соответствие законам РФ. Юрлицо: ООО «Идеал-ФАРМ», ИНН 5050110424, г. Фрязино.
- Язык: русский.
- **Домен**: aptekaa.ru (главный, тематический, 2012 года) + аптекаа.рф → 301 редирект
- **SEO‑приоритет**: Яндекс. Старт без рекламы, через 3–4 месяца тестовая реклама

## Architecture
- **Frontend**: React 19, Tailwind CSS, Framer Motion, React Router DOM, react-helmet-async, Yandex Maps JS API
- **Backend**: FastAPI + Motor (Async MongoDB) + httpx (Yandex SpeechKit). Все эндпоинты — под префиксом `/api`
- **DB**: MongoDB. Коллекции: `medications_raw` (72 054 SKU), `medications` (23 303 карточки), `mnn_index` (3 054 МНН), `voice_messages`, `tts_cache`
- **AI ассистент**: Web Speech API (mic) → `/api/voice/chat` (gpt-4o-mini) → `/api/voice/tts` (Yandex SpeechKit, голос Алёна)
- **Карты**: Yandex Maps JS API через `REACT_APP_YANDEX_MAPS_KEY`

## Implemented features

### Frontend MVP (готово ранее)
- Главная, категории, страница лекарства с моковой Яндекс.Картой и облаками цен
- Список аптек, страница аптеки, страница «Для аптек»
- Юридические страницы (Контакты, Политика конфиденциальности, Согласие)
- Бренд «АптекаА» с 3D-логотипом таблетки
- Подставлены реальные реквизиты ООО «Идеал-ФАРМ» (ИНН 5050110424, Фрязино)
- Auto-scrolling маркетинговая лента партнёров
- Контекст города (Москва / СПб)

### AI голосовой ассистент (✅)
- Backend: `POST /api/voice/chat` — gpt-4o-mini, history in `voice_messages`
- TTS: `POST /api/voice/tts` — **Yandex SpeechKit** v1, голос **alena**, эмоция **good**, формат `oggopus`, кэш в `tts_cache` по SHA-256
- Frontend: `VoiceAssistant.jsx` + `CallView.jsx` — два режима (chat и беседа). В режиме беседы микрофон отключается во время ответа Алёны (защита от эхо-петли).
- Контекст бота: 20 препаратов + 11 аптек (`voice_data.py`)
- Стоимость: ~0.4–0.5 ₽/мин беседы. 7000 мин/мес ≈ 3000 ₽

### Каталог из mdlp.crpt.ru (✅ 2026-02-09)
- **ETL**: `/app/backend/scripts/import_mdlp.py` — XLSX → 3 коллекции MongoDB
- **23 303 карточки** препаратов (группировка по ТН + дозировка + производитель)
- **72 054 SKU** в `medications_raw` (с GTIN, РУ, ЕСКЛП, ЖНВЛП, ВЗН, ПКУ, наркотические)
- **3 054 уникальных МНН** для подбора аналогов
- **Авто-детект Rx** (наркотические/ПКУ/ВЗН/инъекционные → Отпускается по рецепту)
- **Авто-категоризация** по словарю топ-МНН (11 категорий)
- **SEO-слаги** транслитом: `paracetamol-500-mg-tabletki-pokrytye-obolochkoy`
- Индексы: `slug` unique, text(name, mnn) russian, category, mnn, manufacturer

### Backend API (✅ 2026-02-09)
- `GET /api/cities` — список городов
- `GET /api/categories` — 11 категорий с реальными счётчиками
- `GET /api/search?q=&category=&rx=&page=&page_size=` — поиск с пагинацией (стабильная сортировка по textScore + slug tiebreaker)
- `GET /api/search/suggest?q=` — typeahead (regex по name/mnn)
- `GET /api/medications/{slug}` — карточка + варианты + цены (с полем `prices_source: real|demo`)
- `GET /api/medications/{slug}/analogs` — аналоги по МНН (sorted by name)
- `GET /api/pharmacies?city=` — аптеки города
- `GET /api/pharmacies/{id}` — карточка аптеки

### Загрузка прайс-листов аптек (✅ 2026-02-09)
- **Скрытый кабинет аптеки**: `/partner-upload?token=XXXX` (НЕ слинкован с основного сайта)
- **Авторизация по токену** в коллекции `pharmacy_tokens` (3 партнёра засеяно)
- `POST /api/upload/me/{token}` — данные аптеки по токену
- `POST /api/upload/prices/{token}` — загрузка XLSX/CSV (мультипарт, до 25 МБ)
  - Принимает английские (`gtin, name, qty, price`) и русские (`штрихкод, название, количество, цена`) заголовки в любом порядке
  - Опциональные: `pharmacy_id` (код точки), `expiry_date` (срок годности)
  - CSV в UTF-8 или Windows-1251, разделитель `,` или `;` (auto-sniff)
  - Парсит цены типа `125,50` (запятая=точка), очищает `1 500 ₽`
  - Матчит GTIN против `medications_raw` (72k SKU) → пишет в `prices` (upsert по pharmacy_id+gtin)
  - Не сматченные GTIN → `unmatched_items` (вкладка «Требуют разбора»)
  - Возвращает summary: total_rows, valid_rows, invalid_rows, matched, unmatched + sample_errors
  - Уникальный `upload_id` с UUID-суффиксом (защита от двойной загрузки в одну секунду)
- `GET /api/upload/history/{token}` — последние 20 загрузок аптеки
- `GET /api/upload/unmatched/{token}` — товары без сопоставления с реестром
- **Frontend**: `/app/frontend/src/pages/PartnerUpload.jsx` — drag&drop, прогресс, 3 вкладки (Загрузка / История / Требуют разбора)
- Цены сразу видны в `/api/medications/{slug}` с флагом `prices_source: "real"`
- Скрипт сидинга токенов: `python -m scripts.seed_pharmacy_tokens`

### SEO‑фундамент (✅ 2026-02-09)
- `GET /api/seo/robots.txt` — с `Sitemap`, `Host`, `Clean-param` для Yandex
- `GET /api/seo/sitemap.xml` — индекс sitemaps
- `GET /api/seo/sitemap_static.xml` — главная, статичные страницы (с городскими префиксами)
- `GET /api/seo/sitemap_categories.xml` — все категории × 2 города
- `GET /api/seo/sitemap_pharmacies.xml` — аптеки
- `GET /api/seo/sitemap_meds_{N}.xml` — препараты, чанками 25k слагов × 2 города = 50k URL
- `GET /api/seo/render?path=/<city>/...` — серверный HTML рендер для ботов:
  - `<title>`, `<meta description>`, canonical, Open Graph
  - schema.org `Drug`, `Pharmacy`, `WebSite`, `BreadcrumbList`
  - Видимый контент: имя, МНН, форма, дозировка, производитель, варианты упаковки, аналоги, аптеки
  - Плашки «Отпускается по рецепту», «ЖНВЛП», «Государственная предельная цена X ₽»
- В production CF Worker делает rewrite: бот UA → `/api/seo/render?path=...`

### Frontend миграция на API (✅ 2026-02-09)
- `src/api/client.js` — axios клиент (fetchCities, fetchCategories, searchMeds, fetchMed, fetchAnalogs, suggestMeds)
- `src/seo.js` + `src/components/SEOHead.jsx` — react-helmet-async + Schema.org JSON-LD
- **Префикс города в URL**: `/msk/preparaty/<slug>`, `/spb/poisk?q=`, `/msk/kategorii/<slug>`, `/msk/apteki/<id>`
- Бекворд-совместимость: `/preparaty/<slug>`, `/poisk` тоже работают
- Search.jsx — реальный API с пагинацией и фильтрами (категория, rx)
- MedDetail.jsx — реальный API с вариантами упаковки, аналогами, схема.org Drug, плашки ЖНВЛП и госцены
- Home.jsx — API typeahead, городские ссылки

## Tested
- ✅ pytest /app/backend/tests/test_catalog_api.py: **21/21 пройдено**
  - Cities, Categories, Search (с пагинацией, фильтрами, suggest), MedDetail, Analogs, 404, Pharmacies, SEO (robots, sitemaps, render для всех типов страниц), Voice (chat + tts smoke)
- ✅ Playwright e2e: home → search → med-detail flow, городские префиксы, бекворд-совместимость
- ✅ Curl: 21 эндпоинт, схема.org JSON-LD валидируется

## Backlog (приоритизировано)

### P0 (готово к старту)
- ~~Импорт mdlp~~ ✅
- ~~SEO-фундамент~~ ✅
- ~~Каталог API + Search + MedDetail~~ ✅
- ~~Полная миграция Frontend на API (удалён `mock.js`, `MedCard.jsx`)~~ ✅ 2026-05-10
- ~~Форма заявки партнёров `/api/partner-requests` + admin approve/reject~~ ✅ 2026-05-10
- ~~`prefix` фильтр в `/api/search` для каталога А–Я~~ ✅ 2026-05-10

### P1
- ~~Простая admin-страница `/partner-admin?token=...` для одобрения заявок~~ ✅ 2026-05-10
- ~~LLM-обогащение топ-200 препаратов (описания, показания, противопоказания, способ применения) через gpt-4o-mini~~ ✅ 2026-05-10
- Mail.ru IMAP-воркер: ждём от пользователя App Password (DKIM на проверке)
- Расширение базы партнёров-аптек с 20 до сотен

### P2
- SFTP-выгрузка прайсов (после деплоя на VPS)
- Аналитика поисковых запросов
- Реальный деплой на aptekaa.ru: DNS Cloudflare, CF Worker для бот-маршрутизации
- Регистрация в Яндекс.Вебмастере и Яндекс.Бизнесе после деплоя
- Покупка `аптекаа.рф` (~190 ₽/год) с 301 на `aptekaa.ru`
- Расширение LLM-обогащения с 200 до 1000-2000 препаратов

## Changelog (latest)
- **2026-05-10 (Сессия 4) — Подготовка к prod-деплою**:
  - Настроен Yandex 360: 3 ящика (`info@`, `partners@`, `price@`)
  - App Password для `price@aptekaa.ru` создан и проверен (IMAP+SMTP auth ✅)
  - Куплен второй домен `аптекаа.рф` (REG.RU, до 26.04.2027)
  - Создана VM в Yandex Cloud: `89.169.137.36`, Ubuntu 22.04, 2 vCPU / 3 GB / 40 GB SSD
  - Сервер защищён: UFW, fail2ban, swap 2 GB, отключён парольный SSH
  - Docker + docker compose установлены
  - **Полный deploy-стек готов** в `/app/deploy/`:
    - `docker-compose.yml` (mongo + backend + frontend + imap_worker + edge-nginx + certbot)
    - `deploy.sh` (один скрипт — bootstrap → SSL → full HTTPS → cron renewal/backup)
    - `backup.sh` (mongodump → /var/backups/aptekaa, retention 14 дней)
    - `nginx/edge-bootstrap.conf` + `nginx/edge-ssl.conf` (HTTP-only → HTTPS с CSP, HSTS, 301 со старых URL)
    - `nginx/static.conf` (фронтенд-контейнер — SPA fallback + cache headers)
    - `DNS.md` (инструкция по REG.RU: A, MX Я.360, SPF, DKIM, DMARC)
    - `README.md` (пошаговая инструкция)
    - `.env.example` (с пред-заполненными значениями кроме секретов)
  - Удалена страница «Доступные упаковки и формы выпуска» из MedDetail
  - Поправлен текст hero-блока на главной (`Привлекайте новых клиентов...`)
  - Опечатка `partner@` → `partners@` в PartnerUpload.jsx

- **2026-05-10 (Сессия 3) — Security hardening**: CORS whitelist, security headers (CSP/HSTS/X-Frame), constant-time admin auth, rate-limits, sanitized errors. 88/88 ✅
- **2026-05-10 (Сессия 2)**: LLM-обогащение топ-200, admin-UI заявок партнёров. 48/48 ✅
- **2026-05-10 (Сессия 1)**: Миграция Frontend → API. 39/39 ✅

## Files of reference
- `/app/backend/server.py` — FastAPI: voice/chat, voice/tts, catalog router, SEO router
- `/app/backend/api/__init__.py` — catalog endpoints
- `/app/backend/api/seo.py` — robots, sitemap, SSR for bots
- `/app/backend/api/pharmacies_seed.py` — CITIES, CATEGORIES, PHARMACIES seed
- `/app/backend/scripts/import_mdlp.py` — ETL script
- `/app/backend/voice_data.py` — context for voice bot
- `/app/backend/data/mdlp_lp_registry.xlsx` — source registry (13 МБ, 72 054 строки)
- `/app/backend/tests/test_catalog_api.py` — pytest suite (21 tests)
- `/app/frontend/src/App.js` — routes with city prefix + backward-compat
- `/app/frontend/src/api/client.js` — axios client
- `/app/frontend/src/seo.js` + `/app/frontend/src/components/SEOHead.jsx` — SEO helpers
- `/app/frontend/src/pages/Home.jsx`, `Search.jsx`, `MedDetail.jsx` — migrated to API
- `/app/frontend/src/components/VoiceAssistant.jsx` + `CallView.jsx` — voice assistant
