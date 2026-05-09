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

### P1
- Загрузка прайс-листов аптек (xls, xlsx, csv, dbf), парсинг и upsert в `prices` collection
- Простой кабинет аптеки (по токену или JWT)
- Дополнительная миграция: Categories.jsx, CategoryDetail.jsx, PharmacyDetail.jsx, PharmaciesList.jsx, Catalog.jsx, NotFound.jsx — на реальный API
- LLM-обогащение топ-500 препаратов (описания, показания) через gpt-4o-mini ~50₽

### P2
- Авторизация для аптек (Emergent Google Auth или JWT)
- Расширение базы партнёров-аптек с 20 до сотен
- Аналитика поисковых запросов
- Админка для контента
- Реальный деплой на aptekaa.ru: DNS Cloudflare, CF Worker для бот-маршрутизации (`/sitemap.xml` → `/api/seo/sitemap.xml`, бот UA → `/api/seo/render`)
- Регистрация в Яндекс.Вебмастере и Яндекс.Бизнесе после деплоя
- Покупка `аптекаа.рф` (~190 ₽/год) с 301 на `aptekaa.ru`

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
