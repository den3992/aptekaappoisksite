# HANDOFF — АптекаА (aptekaa.ru)

**Дата:** 13 февраля 2026
**Состояние:** production, https://aptekaa.ru работает стабильно.
**Предыдущий handoff:** см. `HANDOFF_2026-05-10.md` (заархивирован, содержит подробный контекст начального запуска).

> Этот документ — **полная передача** нового AI-агента: контекст проекта, что
> уже сделано, как устроена инфраструктура, какие есть скрипты, какие плановые
> задачи. Читай целиком прежде чем начинать работу.

---

## 1. Что такое АптекаА (одним абзацем)

Бесплатный поисковик-агрегатор лекарств для Москвы и Санкт-Петербурга. Пользователь
вводит название препарата → получает карточку с фото / описанием / составом / страной /
МНН → видит **цены и наличие в 12 аптеках-партнёрах** на карте города → переходит в
выбранную аптеку. Сейчас **цены MOCKED** (заглушки), потому что аптеки ещё не подключали
прайс-листы. Когда партнёры начнут заливать прайсы, MOCK сменится на реальные данные
автоматически.

Ниша: аналог `aptekamos.ru`, `lekmos.ru`, `apteka.ru` — но только справочный поиск +
карта, без онлайн-заказа. Юридически безопасная позиция: **не аптека**, не торгуем,
не даём медицинских рекомендаций.

**Главная цель сейчас — SEO в Яндексе.** Каждое решение, которое ты принимаешь, должно
учитывать «как это повлияет на индексацию и ранжирование в Яндексе». 95% трафика придёт
оттуда. Google — второстепенно.

**Язык общения с пользователем — РУССКИЙ.** Всегда. Не переходи на английский.

---

## 2. Стек

| Слой | Технология |
|---|---|
| Frontend | React 19, Tailwind, Shadcn/UI, Yandex Maps API |
| Backend | FastAPI 0.110, Motor (async MongoDB driver), Python 3.11 |
| DB | MongoDB 7.0 (в Docker, with auth) |
| AI | OpenAI gpt-4o-mini (через Emergent LLM Key) + Yandex SpeechKit TTS |
| Hosting | Yandex Cloud VM, Ubuntu, Docker Compose |
| Edge | Nginx 1.27-alpine + Let's Encrypt |
| Email | Mail.ru for Business (IMAP/SMTP), `partner@`, `support@aptekaa.ru` |
| DNS | REG.RU (`aptekaa.ru` живой, `аптекаа.рф` — НЕ зарегистрирован в реестре) |
| Аналитика | Yandex.Metrika (counter `109146716`) |

---

## 3. Доступы и инфраструктура

### SSH
- **Хост:** `89.169.137.36` (Yandex Cloud VM, Ubuntu 24.04)
- **Юзер:** `ubuntu`
- **Ключ:** `~/.ssh/aptekaa_key` (в текущем поде агента)
- Пример: `ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36`

### Структура на сервере
```
/home/ubuntu/aptekaa/         ← основной репо (git, den3992/aptekaappoisksite)
├── backend/                  ← FastAPI приложение
│   ├── server.py             ← entry-point, dispatcher SSR-роутов
│   ├── api/
│   │   ├── __init__.py       ← /api/search, /api/medications, /api/categories, ...
│   │   ├── seo.py            ← все SSR-рендереры для ботов (robots.txt, sitemap, медкарты)
│   │   ├── partners.py       ← админка для прайс-листов
│   │   ├── pharmacies_seed.py  ← хардкод PHARMACIES (12 аптек × 2 города)
│   │   └── uploads.py        ← загрузка XLSX/CSV прайсов
│   ├── data/
│   │   └── enrichment-200.json  ← LLM-обогащение топ-200 препаратов
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── pages/            ← MedDetail.jsx, Home.jsx, Catalog.jsx, ... (15 страниц)
│   │   ├── components/ui/    ← shadcn компоненты
│   │   └── api/client.js     ← axios клиент, базовый URL = REACT_APP_BACKEND_URL
│   └── public/
│       └── img/meds/         ← ~2400 WebP файлов (фото препаратов)
├── deploy/                   ← Docker Compose инфра
│   ├── docker-compose.yml    ← 5 сервисов: mongo, backend, imap_worker, frontend, edge
│   ├── backend.Dockerfile
│   ├── frontend.Dockerfile
│   ├── nginx/active.conf     ← конфиг nginx с bot-detection (см. ниже)
│   ├── deploy.sh             ← разворачивание + certbot
│   └── .env                  ← все секреты (НЕ в git)
├── scripts/                  ← разовые миграции и матчинг фото
│   ├── dedup_migration.py    ← см. п. 6.4
│   └── merge_variants.py     ← см. п. 6.5
├── memory/
│   ├── PRD.md                ← краткий лог изменений (поддерживай его)
│   └── test_credentials.md
├── HANDOFF.md                ← этот файл
└── HANDOFF_2026-05-10.md     ← архив прошлого handoff
```

### Docker-сервисы (после `cd deploy && docker compose ps`)
- `deploy-mongo-1` — MongoDB, volume `mongo_data`
- `deploy-backend-1` — FastAPI на порту 8001 (внутри сети)
- `deploy-imap_worker-1` — фоновая выгрузка прайсов из писем
- `deploy-frontend-1` — Nginx со статикой React + папкой `/img/meds/`
- `deploy-edge-1` — внешний Nginx 80/443 с SSL и bot-detection

### Креды (`/home/ubuntu/aptekaa/deploy/.env`)
**Не вытаскивай в чат и не пиши в git.** Ключи: `MONGO_USER`, `MONGO_PASSWORD`,
`MONGO_DB`, `ADMIN_TOKEN`, `EMERGENT_LLM_KEY`, `YANDEX_API_KEY`, `YANDEX_FOLDER_ID`,
`CORS_ORIGINS`, `IMAP_*`, `SMTP_*`, `REACT_APP_BACKEND_URL`,
`REACT_APP_YANDEX_MAPS_KEY`, `LETSENCRYPT_EMAIL`.

Конкретные значения читай через:
```bash
ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 'cat /home/ubuntu/aptekaa/deploy/.env'
```

### Админ-панель
- `https://aptekaa.ru/partner-admin?token=TCkwKsYaekNAJiBHoL8qjxNGsx4XX7PsiQye7WPy`
- Через токен можно просматривать загруженные прайсы и менять статусы аптек.

### GitHub
- Репо: `https://github.com/den3992/aptekaappoisksite`
- Push настроен через PAT в `~/aptekaa/.git/config` (на сервере). **Работал на 13.02.2026.**
- Если push выдаёт 403 — пользователь обновит PAT, не паникуй.
- Все коммиты делаем как `aptekaa-agent <agent@aptekaa.ru>`.

---

## 4. Как работает SSR + bot-detection (важно для SEO)

Это уникальный архитектурный приём, не сломай его.

1. Когда **обычный браузер** заходит на `https://aptekaa.ru/msk/preparaty/metformin-...`,
   Nginx отдаёт `index.html` из React-билда. React клиентский роутер сам подтягивает данные.
2. Когда заходит **YandexBot / Googlebot** (определяется по User-Agent в `nginx/active.conf`),
   Nginx проксирует на `backend:8001/api/seo/render?path=...`. Backend выполняет реальный
   запрос в MongoDB и отдаёт **полноценный статический HTML** с `<title>`, `<h1>`,
   `<og:image>`, `Schema.org/Drug`, breadcrumbs, JSON-LD. Боты получают рендер сразу,
   без выполнения JS.
3. Это даёт нам **полноценную индексацию контента** при простом React SPA, без SSR-сервера
   типа Next.js / SvelteKit. Дёшево, эффективно, главное — не сломать.

**Файлы:**
- `deploy/nginx/active.conf` — bot-detection regex + proxy_pass
- `backend/server.py:320+` — диспетчер `/api/seo/render?path=...`
- `backend/api/seo.py` — все рендереры:
  - `render_home_for_bot` (главная)
  - `render_med_for_bot` (карточка препарата)
  - `render_pharmacy_for_bot` (карточка аптеки)
  - `render_category_for_bot` (страница категории)
  - `render_catalog_index_for_bot` (список А-Я по городу)
  - `render_pharmacies_index_for_bot` (список аптек города)
  - `render_categories_index_for_bot` (список категорий города)
  - `render_contacts_for_bot`, `render_about_for_bot`, `render_for_pharmacies_for_bot`
  - `_render_404` — для несуществующих URL

**Правила работы с SSR:**
- В рендерах нельзя использовать `_id` из MongoDB (BSON не сериализуется как JSON-LD).
- Категории/города/аптеки фильтруем по `is_canonical: {$ne: false}` (см. п. 6.4).
- Любые helper-функции, используемые в рендерах, должны быть **определены в `seo.py`**
  (`_title_case`, `_normalize_country`, `cn_genitive` уже там). Если будешь импортировать
  что-то новое из других модулей — проверь, что оно загружается в worker’е uvicorn.
- **Самый частый класс ошибок:** `NameError` в SSR из-за неопределённой helper-функции.
  При деплое backend перезапустится, и боты сразу получат 500. Проверяй через:
  ```bash
  curl -s -A YandexBot https://aptekaa.ru/msk/preparaty/<slug> -w '\nstatus:%{http_code}\n'
  ```

---

## 5. Модель данных (MongoDB)

**База:** `aptekaa`. Коллекции:

### `medications` (≈23 303 документа, **источник истины: ЕСКЛП**)
```javascript
{
  slug: "metformin-1000-mg-tabletki",
  name: "Метформин",
  mnn: "МЕТФОРМИН",
  dosage: "1000 мг",
  form: "ТАБЛЕТКИ, ПОКРЫТЫЕ ОБОЛОЧКОЙ",
  manufacturer: "ООО ОЗОН ФАРМ",     // строго как в ЕСКЛП, не править!
  manufacturer_country: "РОССИЯ",
  ru_number: "ЛП-002189",            // регистрационное удостоверение
  category: "endokrinologiya",       // одна из 12 категорий
  rx: false,                          // рецептурный?
  variants: [                         // см. п. 6.5 — variants дублей сливаются в canonical
    { pack_size: "60 шт", gtin: "04630015110065", primary_pack_desc: "...", ru_number: "..." }
  ],
  image_url: "/img/meds/ozon_metformin-1g-n60-tabl-ozon-farm.webp",  // см. п. 6.1
  dedup_key: "a3f7e2d1b5c8...",      // md5(name+dosage+form+normalized_brand) — см. п. 6.4
  is_canonical: true,                 // если false — не показывается в listings
  canonical_slug: "metformin-1000-mg-tabletki"  // на какой slug ставить rel=canonical
}
```

**Критично:**
- Текстовые поля БД (`manufacturer`, `manufacturer_country`, `mnn`) **в исходном
  регистре ЕСКЛП** (часто КАПС). Title-case делается на лету в UI/SSR функциями
  `_title_case` / `_normalize_country`. **Не мутируй БД для casing!**
- БД сверена с реестром «2026_05_08_Общий_реестр_зарегистрированных_ЛП.xlsx» —
  100% совпадение по GTIN. Не нужно «исправлять» странные манекенные текстовые
  значения — они правильные, такие они в ЕСКЛП.
- Текущая статистика:
  - `is_canonical: true` → **22 348** документов (показываются в listings)
  - `is_canonical: false` → **955** документов (скрыты, рендерятся только по прямому URL с canonical=other_slug)
  - `image_url` не null → **~1851** документов (8.3% от каноничных)

### `prices` (пуста; ждёт партнёров)
Структура зарезервирована: `{ pharmacy_id, med_slug, gtin, price, qty, updated_at }`.
Сейчас UI рендерит **МОК** на основе `pack_size`.

### `pharmacies` (12 точек × 2 города, хардкод в `pharmacies_seed.py`)
ID, имя, адрес, координаты, телефон, часы работы, город.

### `imap_threads`, `partner_uploads` (служебные, для админки)

---

## 6. Что было сделано в этой сессии (13.02.2026)

### 6.1 PNG → WebP (Q80, 800px) для всех 997 фото
- Все фото препаратов конвертированы через `cwebp -q 80 -resize 800 0 src.png -o dst.webp`
- Объём: **1.4 ГБ → 23 МБ** (60×)
- Средний файл: 1.5 МБ → 20 КБ
- MongoDB массово обновлён: `.png → .webp` (1218 docs)
- WebP закоммичены в git, PNG удалены с диска
- WebP поддерживают 96% браузеров, +Core Web Vitals → Яндекс ранжирование
- **Все будущие фото скрейпим сразу как WebP**, не как PNG

### 6.2 Критический SSR фикс
В `backend/api/seo.py` использовались `_title_case` и `_normalize_country`, но они **не были
определены** в файле. Каждая карточка препарата падала с `NameError` → HTTP 500 для всех
ботов Яндекса. Добавлены оба хелпера. Коммит `92de124`.

### 6.3 SSR для index-страниц (`/msk/preparaty`, `/msk/apteki`, `/msk/kategorii`)
Эти URL были в `sitemap_static.xml`, но диспетчер не имел для них рендереров → soft-404.
Добавлены `render_catalog_index_for_bot`, `render_pharmacies_index_for_bot`,
`render_categories_index_for_bot`. Все 6 URL (по 3 секции × 2 города) теперь 200.
Коммит `1e9e242`.

### 6.4 Silent dedup дубликатов карточек
**Проблема:** Один и тот же препарат в ЕСКЛП регистрируется под разными РУ (юрлица,
ЕАЭС-регистрация, латинские буквы в названиях). Пользователь видел 3 карточки «Метформин
1000 мг ООО ОЗОН» подряд в выдаче.

**Решение:**
- `scripts/dedup_migration.py` — считает `dedup_key = md5(name + dosage + form +
  normalized_brand)`. Нормализация бренда снимает «ООО / OOO / ФАРМ / ПФК», приводит
  латинские `oaec` → кириллические `оаес`.
- На каждом документе теперь поля `dedup_key`, `is_canonical` (bool), `canonical_slug` (str).
- В группе ≥2 документов один (с большим числом variants и более коротким slug) становится
  `is_canonical=true`, остальные `false`.
- Все listing-API (`/search`, `/suggest`, `/analogs`, sitemap_meds, category SSR, home SSR)
  фильтруют `is_canonical: {$ne: false}`.
- SSR-страница не-canonical документа возвращает 200 с `<link rel="canonical">` на
  canonical slug → Яндекс склеит ранжирование.

**Результат:** 22 348 canonical / 955 hidden. Коммит `4e2000a`.

### 6.5 Merge variants of duplicates into canonical
**Проблема:** После 6.4 пользователь видит одну карточку, но фасовки из остальных
2 РУ были невидимы.

**Решение:** `scripts/merge_variants.py` собирает `variants` из всех документов
`dedup_key`-группы, дедупит по GTIN (фолбэк: `pack_size + label_name`), сортирует
по числу, пишет на canonical. Также бэкфилл `image_url`, если у canonical нет, а у дубля есть.

**Результат:** 855 групп слиты, **1523 уникальных GTIN** перенесены на canonical. Пример:
«Метформин 1000 мг ООО ОЗОН ФАРМ» теперь имеет 6 GTINs (раньше было 3 — другие 3 жили
на 2 дубликат-картах). Когда партнёры начнут заливать прайсы, все 6 артикулов склеятся
под одной чипой «60 шт» в UI. Коммит `c44c6ec`.

### 6.6 Фотографии производителей (главный фокус сессии)
Pipeline единый для всех:
1. Найти sitemap производителя → product URLs.
2. С каждой страницы вытащить `<h1>` (trade name) + главное фото (`og:image`, `itemprop="image"`,
   `IMG_PACK_FRONT/650_650_1`, или `/resize_cache/.../500_350_1/` — зависит от движка).
3. Сразу конвертить через `cwebp -q 80 -resize 800 0` (без промежуточного PNG).
4. Матчить с MongoDB через нормализованный trade-name + form-family (solid/liquid/
   topical/supp/spray/inject). **Важно:** не делать cross-form match (Ибупрофен капсулы
   → Ибупрофен гель — это разные препараты).

**Покрытие после сессии:**

| Производитель | Фото в БД | % канонических | Скрипт |
|---|---:|---:|---|
| **ООО ОЗОН + ОЗОН ФАРМ** | 998 / 1330 | 75% | scrape через GraphQL ozonpharm.ru |
| **ЗАО КАНОНФАРМА** | 289 / 448 | 65% | canonpharma.ru/sitemap-iblock-7.xml |
| **АО ФАРМАСИНТЕЗ группа** | 362 / 621 | 58% | pharmasyntez.com/products/ (single-page) |
| **АО АКРИХИН** | 83 / 163 | 51% | akrikhin.ru/sitemap-iblock-1.xml |
| **АО ПФК ОБНОВЛЕНИЕ (Renewal)** | 219 / 464 | 47% | renewal.ru |
| **АО БИОКОМ** | 17 / 39 | 44% | binnopharmgroup.ru |
| **АО ВЕРТЕКС** | 97 / 267 | 36% | vertex.spb.ru (og:image) |
| **АО АЛИУМ (АКОС)** | 53 / 195 | 27% | binnopharmgroup.ru (бонус) |
| **ОАО/ПАО СИНТЕЗ** | 94 / 366 | 26% | binnopharmgroup.ru (бонус) |
| **ОБЩИЙ ИТОГ** | **2213 / 22 348** | **9.9%** | |

**Биохимик отложен в конец списка.** У них:
- `biohimik.net` — это вообще не Биохимик, какой-то админ-интерфейс
- `biohimik.ru` → редиректит на `promomed.pro` (Биохимик принадлежит «Промомеду»)
- Каталог Промомеда **не показывает фото товаров**, только заглушки и логотипы партнёров-аптек.

### 6.6.x Лайфхак для Фармасинтеза (одно-страничный каталог)
В отличие от Bitrix-каталогов остальных (где надо обходить sitemap и фетчить каждую
страницу), у Фармасинтеза **весь каталог на одной странице** `/products/`:
```html
<div class="box-element ...">
  <a href="/products/<category>/<slug>/">
    <div class="square-picture" style="background-image: url('/upload/.../<img>.png');"></div>
    <div class="name">Trade name</div>
    <div class="mnn">МНН</div>
    <div class="dose"><span>2,5 мг</span></div>
    <div class="group">Категория</div>
  </a>
</div>
```
Один HTTP-запрос — 238 продуктов с изображениями, MNN и дозами сразу. Это в 30 раз
быстрее обычного flow. Но: страница НЕ содержит lекарственной формы — для исключения
cross-form match'a (Адеметионин таблетки vs лиофилизат) нужен **2-й проход**
`ps_enrich_forms.py`: посетить каждую страницу продукта и определить форму
по тексту тела (`таблетки` / `лиофилизат` / `раствор для инъекций` / ...).
Дистрибуция вышла: 149 solid, 70 inject, 14 unknown, остальное единичные.

Если попадётся ещё такой производитель — переиспользуй `pharmasyntez_scrape.py` +
`ps_enrich_forms.py` как шаблон.

### 6.7 Прочее
- Phone numbers clickable (`<a href="tel:...">`), часы работы и телефон разделены `|`
- Pack sizes отсортированы по числу по возрастанию (UI чипы)
- ЕСКЛП-артефакты в pack sizes очищены (`см[3*];^мл` → `мл`)
- Title Case для стран и МНН — **только в UI/SSR**, без мутации БД
- GitHub PAT обновлён (push работает)

### 6.8 UI-полировка главной (последние правки)
- **Плейсхолдер поиска** в hero на Home.jsx: `"Название препарата, вещества или
  симптома…"` → `"Введите название препарата"` (короче, понятнее новому
  пользователю). Коммит `d91407b`.
- **Иконка лупы** (`<Search>` из lucide-react): `text-slate-400` (нейтральный
  серый) → `text-rose-500` (#f43f5e — мягкий розово-красный, не насыщенный,
  компенсирует «зелёность» брендового emerald-600). Применено в обоих местах:
  Home.jsx (hero) и Header.jsx (узкий navbar-поиск). Коммит `d91407b`.
- **Партнёров в hero бейдже**: `"Более 200 аптек-партнёров в Москве и СПб"` →
  `"Более 2000 аптек-партнёров..."`. Коммит `0eeef6e`.
- **Удалены 3 декоративные зелёные точки** из фона hero-блока на главной
  (`<div className="absolute ... rounded-full bg-emerald-400/60">` × 3).
  Оставлены две большие размытые `blur-3xl` emerald-орбиты — они дают мягкую
  глубину без визуального шума. Коммит `0eeef6e`.

**На что обратить внимание:** изменение цвета иконки (`rose-500`) — это **первое
введение красного** в раньше чисто emerald-палитру. Если будет добавляться
другая красная иконка (например, медицинский крест, отметки рецептурных
препаратов и т.д.), используй **тот же `rose-500`** для консистентности.
Не вводи `red-500`, `rose-400` или другие оттенки красного без причины.

---

## 7. Где сейчас лежат скрипты (текущий поток работы)

Все скрейпинг-скрипты живут в `/tmp/` на сервере (быстрые однократные миграции, не
коммитим). Закоммичены только переиспользуемые: `scripts/dedup_migration.py`,
`scripts/merge_variants.py`, `scripts/cp_match.py` (если коммитил).

**На сервере существуют:**
- `/tmp/canonpharma_scrape.py` + `/tmp/cp_match.py` — Канонфарма (готово)
- `/tmp/binnopharm_scrape.py` + `/tmp/bnp_match.py` — Синтез/Алиум/Биоком (готово)
- `/tmp/akrikhin_scrape.py` + `/tmp/ak_match.py` — Акрихин (готово)
- `/tmp/vertex_scrape.py` + `/tmp/vx_match.py` — Вертекс (готово)
- `/tmp/pharmasyntez_scrape.py` + `/tmp/ps_enrich_forms.py` + `/tmp/ps_match.py` — Фармасинтез (готово, использует single-page parse + 2-й проход для form_family из тела страницы)
- `/tmp/ozon_match.py` — Озон (применён, артефакты есть в `/tmp/`)

**Шаблон для следующего производителя:**
1. Найти sitemap или каталог → product URLs.
2. Скопировать `vertex_scrape.py` (если og:image работает) или `akrikhin_scrape.py`
   (если резайз-кеш Bitrix) как старт.
3. Скопировать `vx_match.py` как основу матчера, заменить `DB_REGEX` на нужного
   производителя. **Помни про cross-form match** — оставь `idx.setdefault((k,fam))` БЕЗ
   `idx.setdefault((k,"any"))`, чтобы не было ложных совпадений.

---

## 8. Стандартный flow для скрейпинга нового производителя

```bash
# 1. На локальной машине (поде агента) — пишем скрипт
nano /tmp/<short>_scrape.py     # переиспользовать vx_/ak_/cp_scrape как шаблон
nano /tmp/<short>_match.py

# 2. Копируем на прод
scp -i ~/.ssh/aptekaa_key /tmp/<short>_scrape.py ubuntu@89.169.137.36:/tmp/
scp -i ~/.ssh/aptekaa_key /tmp/<short>_match.py  ubuntu@89.169.137.36:/tmp/

# 3. Запускаем скрейп
ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 'rm -rf /tmp/<short>_img && nohup python3 /tmp/<short>_scrape.py > /tmp/<short>_scrape.log 2>&1 & echo started PID=$!'
# Ждём (sleep 60-90 для ~300 продуктов на скорости 0.25 сек/запрос).
# Проверяем счёт webp: ls /tmp/<short>_img/*.webp | wc -l

# 4. Матчинг
ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 'python3 /tmp/<short>_match.py 2>&1'

# 5. Применяем БД-апдейты
ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 "docker cp /tmp/<short>_updates.js deploy-mongo-1:/tmp/<short>_updates.js && docker exec deploy-mongo-1 mongosh -u aptekaa_admin -p \$(grep MONGO_PASSWORD /home/ubuntu/aptekaa/deploy/.env | cut -d= -f2) --authenticationDatabase admin aptekaa --quiet --file /tmp/<short>_updates.js"

# 6. Копируем webp в host volume + в nginx container
ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 'cp /tmp/<short>_img/*.webp /home/ubuntu/aptekaa/frontend/public/img/meds/ && mkdir -p /tmp/<short>_batch && cp /tmp/<short>_img/*.webp /tmp/<short>_batch/ && docker cp /tmp/<short>_batch/. deploy-frontend-1:/usr/share/nginx/html/img/meds/ && rm -rf /tmp/<short>_batch'

# 7. Проверка
# 7a. curl на одну карточку из этого производителя:
ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 "curl -s 'https://aptekaa.ru/api/medications/<slug>' | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get(\"image_url\"))'"
# 7b. Скриншот:
# mcp_screenshot_tool со script, который грабит src='img[src*=<short>_]'

# 8. Коммит и push
ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 "cd /home/ubuntu/aptekaa && git add frontend/public/img/meds/<short>_*.webp && git -c user.name='aptekaa-agent' -c user.email='agent@aptekaa.ru' commit -m 'feat(images): scrape <Производитель> catalog photos' && git push origin main"

# 9. Обновить PRD.md и при необходимости HANDOFF.md
```

---

## 9. Полезные команды

### Логи backend
```bash
ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 'docker logs deploy-backend-1 --tail 50 2>&1'
```

### Перезапуск backend (после изменения файла напрямую в контейнере)
```bash
ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 'docker cp /home/ubuntu/aptekaa/backend/api/seo.py deploy-backend-1:/app/api/seo.py && docker restart deploy-backend-1'
sleep 7
# Verify
curl -s -A YandexBot https://aptekaa.ru/msk -w '\nstatus:%{http_code}\n' -o /dev/null
```

### MongoDB CLI
```bash
ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 "docker exec deploy-mongo-1 mongosh -u aptekaa_admin -p \$(grep MONGO_PASSWORD /home/ubuntu/aptekaa/deploy/.env | cut -d= -f2) --authenticationDatabase admin aptekaa --quiet --eval 'db.medications.countDocuments({is_canonical: true})'"
```

### Тестирование SSR / каталога / API
```bash
# Карточка препарата
curl -s -A YandexBot https://aptekaa.ru/msk/preparaty/<slug>

# Index-страница
curl -s -A YandexBot https://aptekaa.ru/msk/preparaty

# API
curl -s 'https://aptekaa.ru/api/search?q=метформин&page_size=10'
curl -s 'https://aptekaa.ru/api/medications/<slug>'
```

### Образ препарата
```bash
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' https://aptekaa.ru/img/meds/<filename>.webp
```

---

## 10. Backlog (приоритизирован)

### 🔴 P0 — блокеры
Сейчас нет открытых P0. Все прошлые блокеры закрыты в этой сессии.

### 🟡 P1 — на очереди
1. **Скрейпинг фото остальных топ-производителей.** Ниже — **полный список** всех
   производителей, где сейчас более 50 препаратов без фото (формат: `missing / total
   | производитель`). Брать сверху вниз по убыванию пользы или по простоте сайта.
   Биохимик исторически отложен (см. 6.6 — у Промомеда нет фото в каталоге).

   <details>
   <summary>Полный список (102 производителя) — кликни чтобы развернуть</summary>

   ```
    417 /  417  АО БИОХИМИК                     ⚠️ отложен (см. 6.6)
    318 /  318  ООО ТУЛЬСКАЯ ФАРМАЦЕВТИЧЕСКАЯ ФАБРИКА  (tff.ru — старый сайт)
    295 /  295  ООО ВЕЛФАРМ                     (velfarm.ru)
    278 /  278  ОАО ФАРМСТАНДАРТ-ЛЕКСРЕДСТВА    (pharmstd.ru)
    269 /  269  ООО ГРОТЕКС                     (solopharm.com)
    245 /  331  ОАО СИНТЕЗ                      ✅ частично (binnopharmgroup)
    245 /  464  АО ПФК ОБНОВЛЕНИЕ               ✅ частично (renewal.ru)
    207 /  207  АО КРКА, Д.Д., НОВО МЕСТО        (krka.biz)
    186 /  186  ОАО ФАРМСТАНДАРТ-УФАВИТА        (pharmstd.ru)
    178 /  178  АО НПО МИКРОГЕН                 (microgen.ru, в основном вакцины)
    175 /  175  АО АВВА РУС                     (avva-rus.ru)
    170 /  267  АО ВЕРТЕКС                      ✅ частично (vertex.spb.ru)
    162 /  162  ФГУП МОСКОВСКИЙ ЭНДОКРИННЫЙ ЗАВОД  (endopharm.ru)
    159 /  448  ЗАО КАНОНФАРМА ПРОДАКШН         ✅ частично (canonpharma.ru)
    156 /  156  ООО РУЗФАРМА                    (ruzfarma.com)
    155 /  155  ПАО БИОСИНТЕЗ                   (biosintez.com)
    154 /  154  ОАО ДАЛЬХИМФАРМ                 (dalkhimfarm.ru)
    153 /  153  ДЖОДАС ЭКСПОИМ ПВТ. ЛТД.        (jodaslab.com, ИНДИЯ)
    148 /  148  ООО ВЕЛФАРМ-М                   (дочка Велфарма)
    145 /  145  ООО ПСК ФАРМА
    142 /  195  АО АЛИУМ                        ✅ частично (binnopharmgroup)
    134 /  324  АО ФАРМАСИНТЕЗ                  ✅ частично (pharmasyntez.com)
    132 /  369  ООО ОЗОН                        ✅ частично (ozonpharm.ru)
    130 /  130  ЗАО ВИФИТЕХ
    128 /  128  АО УСОЛЬЕ-СИБИРСКИЙ ХИМФАРМЗАВОД
    125 /  125  ООО КОМПАНИЯ ДЕКО
    123 /  123  АО ФАРМПРОЕКТ
    122 /  122  ООО ЭДВАНСД ФАРМА
    119 /  119  АО ТАТХИМФАРМПРЕПАРАТЫ
    118 /  118  АО МЕДИСОРБ
    116 /  116  ПАО КРАСФАРМА
    116 /  116  ОАО БЗМП
    115 /  115  ООО ИЗВАРИНО ФАРМА
    114 /  114  ФКП АРМАВИРСКАЯ БИОФАБРИКА      (вакцины)
    114 /  114  ООО ЮЖФАРМ
    111 /  111  НАО СЕВЕРНАЯ ЗВЕЗДА
    111 /  111  ООО НПО ФАРМВИЛАР
    108 /  108  ОАО ИРБИТСКИЙ ХИМФАРМЗАВОД
    106 /  106  АО РАФАРМА                      (rafarma.ru)
    104 /  104  ООО МАКИЗ-ФАРМА                 (makiz-pharma.ru)
    102 /  102  ООО ПРАНАФАРМ
    102 /  102  ЗАО МОСКОВСКАЯ ФАРМАЦЕВТИЧЕСКАЯ ФАБРИКА
     99 /   99  ООО КРКА-РУС                    (krka.ru, дочка KRKA)
     99 /   99  АО ФП ОБОЛЕНСКОЕ
     99 /   99  АО КРАСНОГОРСКЛЕКСРЕДСТВА       (klsmed.ru, фитопрепараты)
     99 /   99  ОАО ИВАНОВСКАЯ ФАРМАЦЕВТИЧЕСКАЯ ФАБРИКА
     98 /   98  АО ВЕРОФАРМ                     (veropharm.ru)
     97 /  324  OOO ОЗОН                        ✅ частично (Latin-O вариант)
     97 /   97  РУП БЕЛМЕДПРЕПАРАТЫ             (Беларусь)
     94 /   94  ОАО ГЕДЕОН РИХТЕР               (gedeonrichter.ru, Венгрия)
     92 /   92  ООО ФИРМА ЗДОРОВЬЕ
     90 /   90  АО Р-ФАРМ                       (r-pharm.com)
     86 /   86  ООО ЭЛЛАРА
     86 /   86  ОАО НПК ЭСКОМ
     84 /   84  АО ОРГАНИКА
     83 /   83  ШРЕЯ ЛАЙФ САЕНСИЗ ПВТ. ЛТД.     (ИНДИЯ)
     83 /   83  ЗАО ФАРМАЦЕВТИЧЕСКИЙ ЗАВОД ЭГИС  (egis.ru, Венгрия)
     82 /   82  ООО ХЕМОФАРМ                    (hemofarm.com)
     82 /   82  АО АЛСИ ФАРМА                   (alsipharma.ru)
     81 /   81  К.О. РОМФАРМ КОМПАНИ С.Р.Л.     (rompharm.com)
     79 /  162  АО АКРИХИН                      ✅ частично (akrikhin.ru)
     78 /   78  ООО ПКФ ФИТОФАРМ
     77 /   77  АО ВАЛЕНТА ФАРМ                 (valenta.com)
     76 /   76  ООО АВЕКСИМА СИБИРЬ
     73 /   73  АО НИЖФАРМ                      (stada-russia.com — STADA group)
     73 /   73  ООО ДОКТОР Н
     73 /   73  ООО ВЕРОФАРМ
     73 /   73  АО БИОКАД                       (biocad.ru)
     72 /   72  ОАО САМАРАМЕДПРОМ
     71 /  179  ООО ФАРМАСИНТЕЗ-ТЮМЕНЬ          ✅ частично (pharmasyntez.com)
     70 /   70  АО КИРОВСКАЯ ФАРМАЦЕВТИЧЕСКАЯ ФАБРИКА
     70 /   70  ООО ОНКОТАРГЕТ
     69 /   69  ООО АМЕДАРТ
     69 /   69  ООО ФАРМКОНЦЕПТ
     68 /   68  ЗАО ЯФФ
     66 /   66  ООО ИНТЕРФАРМА
     65 /   65  БИОЛОГИШЕ ХАЙЛЬМИТТЕЛЬ ХЕЕЛЬ ГМБХ  (heel.de, гомеопатия)
     65 /   65  ООО ФАРММЕНТАЛ ГРУПП
     65 /   65  САН ФАРМАСЬЮТИКАЛ ИНДАСТРИЗ ЛТД. (sunpharma.com, ИНДИЯ)
     65 /   65  ООО ГЕРОФАРМ                    (geropharm.ru)
     64 /   64  ФАРМАЦЕВТИЧЕСКИЙ ЗАВОД ПОЛЬФАРМА АО  (polpharma.com, Польша)
     63 /   63  Д-Р РЕДДИ`С ЛАБОРАТОРИС ЛТД.    (drreddys.com, ИНДИЯ)
     63 /   63  ОАО УРАЛБИОФАРМ
     61 /   61  АО БРЫНЦАЛОВ-А
     59 /   59  МИКРО ЛАБС ЛТД.                 (microlabsltd.com, ИНДИЯ)
     59 /   59  ООО ФИРМА ФИТО-БОТ
     58 /   58  АО НОВОСИБХИМФАРМ
     58 /   58  ООО РОЗЛЕКС ФАРМ
     58 /   58  ЗАО ФАРМФИРМА СОТЕКС            (sotex.ru)
     58 /   58  НАО "СЕВЕРНАЯ ЗВЕЗДА"
     57 /   57  АО СТ.-МЕДИФАРМ
     57 /   57  ОАО ТВЕРСКАЯ ФАРМАЦЕВТИЧЕСКАЯ ФАБРИКА
     56 /   56  НОВАРТИС ФАРМА ШТЕЙН АГ          (novartis.com, Швейцария)
     55 /   55  ТЕВА ФАРМАСЬЮТИКАЛ ВОРКС ПРАЙВЭТ КО.ЛТД.  (teva.com, Израиль)
     55 /   55  ГЛЕНМАРК ФАРМАСЬЮТИКАЛ ЛТД.     (glenmarkpharma.com, ИНДИЯ)
     53 /   53  СП ООО ФАРМЛЭНД                 (Беларусь)
     53 /   53  ООО СЛАВЯНСКАЯ АПТЕКА
     53 /   53  АО МАРБИОФАРМ
     53 /   53  БЕЛУПО, ЛЕКАРСТВА И КОСМЕТИКА Д.Д.  (belupo.com, Хорватия)
     52 /   52  ООО ФИРМА ФЕРМЕНТ
     52 /   52  ЗАО ОХФК
     51 /   51  ЛЕК Д.Д.                        (lek.si — Novartis Sandoz, Словения)
   ```

   </details>

   **Стратегия выбора следующего:**
   - 🟢 **Большой каталог + современный сайт** = быстрая победа. Сейчас лидеры:
     **Велфарм (295), Фармстандарт-Лексредства (278), Гротекс/Solopharm (269),
     КРКА (207)**.
   - 🟡 **Иностранцы** (Гедеон Рихтер, Эгис, Сан Фарма, Доктор Реддис, Гленмарк,
     Тева, Новартис, Белупо, Лек, Польфарма) — обычно русифицированных каталогов
     с фото нет; ищи English `/products/` или скрейпь Vidal.ru.
   - 🔴 **Старые сайты / биофабрики / вакцины** (Микроген, Армавирская биофабрика,
     Тульская фабрика, региональные ОАО *химфармзавод*) — низкое покрытие фото, не браться.
   - 💡 **Регулярно обновляй этот список** через:
     ```bash
     ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 'docker exec deploy-mongo-1 mongosh -u aptekaa_admin -p $(grep MONGO_PASSWORD /home/ubuntu/aptekaa/deploy/.env | cut -d= -f2) --authenticationDatabase admin aptekaa --quiet --eval "
     db.medications.aggregate([
       { \$match: { is_canonical: { \$ne: false } } },
       { \$group: { _id: \"\\\$manufacturer\", total: { \$sum: 1 }, with_image: { \$sum: { \$cond: [{ \$ifNull: [\"\\\$image_url\", false] }, 1, 0] } } } },
       { \$addFields: { missing: { \$subtract: [\"\\\$total\", \"\\\$with_image\"] } } },
       { \$match: { missing: { \$gt: 50 } } },
       { \$sort: { missing: -1 } }
     ]).forEach(d => print(d.missing + \"/\" + d.total + \" | \" + d._id));
     "'
     ```
2. **DNS аптекаа.рф (xn--80aerl0afi.xn--p1ai)**: пользователь обратился в REG.RU,
   домен **не зарегистрирован в реестре .рф** (WHOIS пусто). После регистрации:
   ```bash
   host xn--80aerl0afi.xn--p1ai   # должно резолвиться на 89.169.137.36
   ssh ubuntu@89.169.137.36 'cd ~/aptekaa/deploy && ./deploy.sh'  # запустит certbot
   ```
3. **Подпись «Фото производителя»** под изображением в `MedDetail.jsx` и SSR (`seo.py`).
   Пользователь явно сказал «отложим это на потом, запомни». Не делать без явного запроса.

### 🟢 P2 — потом
4. **Лендинг `/dlya-aptek-lending`**: оформить для привлечения аптек-партнёров.
5. **Расширить LLM-обогащение** на все препараты (нужен прямой OpenAI ключ, не Emergent).
6. **Биохимик / Промомед**: если найдёте источник фото — добавить (пока заглушки).
7. **Реальные цены** в SSR карточек (ждём заливки прайсов партнёрами).

---

## 11. Стиль работы с пользователем

- **Язык:** РУССКИЙ всегда. Не переходи на английский, даже в технических объяснениях.
- **Тон:** деловой, но не сухой. Пользователь — собственник бизнеса, не разработчик,
  но технически грамотный. Объясняет проблемы понятным языком, не сыпь термины.
- **Подтверждай план перед выполнением.** Пользователь всегда говорит «давай»,
  «делай», «погнали» — если ответ короткий, ты понял правильно.
- **Не делай больше, чем спросили.** Например, если просят добавить фото производителя X,
  не лезь чинить unrelated баги (только если они на пути).
- **Финиш каждой задачи завершай:**
  - markdown-таблицей с метриками
  - коммитом в git
  - предложением следующего шага (с лёгким а/б/в выбором)
- **Эмодзи:** редко и осмысленно. ✅ для готового, ⚠️ для предупреждения, 🔴🟡🟢 для приоритетов.
- **Не предлагай рефакторинг unsolicited.** Сейчас приоритеты — SEO, фото, лендинг.

---

## 12. Чего НЕ делать (anti-patterns)

1. ❌ **Не скрейпить агрегаторы цен** (apteka.ru, eapteka.ru, rigla.ru и т.п.) — пользователь
   явно запретил из-за рисков. Только официальные сайты производителей.
2. ❌ **Не мутировать БД для casing** (`manufacturer`, `mnn`, `country` остаются как в ЕСКЛП).
   Title-case делается в UI/SSR функциями `_title_case` / `_normalize_country`.
3. ❌ **Не добавлять водяные знаки** на скрейпленные фото — обсуждали, отказались
   (копирайт остаётся за производителем, водяной знак не защищает, а навредит SEO).
4. ❌ **Не предлагать medицинские рекомендации** в LLM-описаниях. Только справочная
   информация и обязательный disclaimer (по ФЗ-38).
5. ❌ **Не возвращать `_id` из MongoDB в JSON** — BSON ObjectId не сериализуется.
   Всегда `projection: {_id: 0, ...}`.
6. ❌ **Не запускать длинные процессы (>120 сек) в foreground.** Используй nohup + & + log file.
7. ❌ **Не пересоздавать `requirements.txt` или `package.json`** — добавляй пакеты через
   `pip install + pip freeze` / `yarn add`. Полное переписывание ломает локк-версии.
8. ❌ **Не делать `.png` фото** — только `.webp` через cwebp -q 80 -resize 800 0.

---

## 13. Open questions для пользователя

1. **Следующий производитель фото?** (см. P1, пункт 1)
2. **Когда домен `аптекаа.рф` зарегистрируется в реестре .рф?** Ждём REG.RU.
3. **Партнёры-аптеки**: есть ли первые контакты, кто загрузит первый реальный
   прайс? Без этого Цены остаются MOCKED.

---

## 14. История коммитов сессии (последние 14)

```
0eeef6e feat(home): bump partner count to 2000+ and clean decorative dots
d91407b feat(ui): simplify hero placeholder + brand-red search icon
85b0b03 docs(handoff): full list of 102 manufacturers missing photos
7a5070a docs(handoff): add Pharmasyntez to manufacturer table + single-page catalog tip
6e74c5d feat(images): scrape Pharmasyntez group catalog photos
483e373 docs: full handoff for new AI agent migration
f66cd9f feat(images): scrape Vertex catalog photos
89d9442 feat(images): scrape Akrikhin catalog photos
9d9566c feat(images): scrape Binnopharm Group catalog (Синтез + Алиум + Биоком)
2c72703 feat(images): scrape Canonpharma Production catalog photos
1e9e242 feat(seo): add SSR for /<city>/preparaty, /<city>/apteki, /<city>/kategorii indexes
89fddaa perf(images): convert all medication photos PNG -> WebP 800px Q80
c44c6ec feat(catalog): merge variants from duplicate registrations into canonical card
4e2000a feat(catalog): silent dedup of duplicate registrations in listings
92de124 fix(seo): define missing _title_case and _normalize_country helpers in SSR
```

Полная история: `git log --oneline` на сервере.

---

## 15. Контакты

- Email пользователя: см. `partner@aptekaa.ru` / `support@aptekaa.ru`
- Telegram, Discord: не использовались
- GitHub: `den3992`
- Хост-провайдер: Yandex Cloud (биллинг — на пользователе)
- Регистратор домена: REG.RU

---

**Конец handoff. Удачи!**

*Если что-то не нашёл — `git log --grep=<ключевое_слово>` или ищи в `memory/PRD.md`.*
