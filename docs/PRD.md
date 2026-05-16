# PRD — АптекаА (aptekaa.ru) — running log

## Project context
SEO-агрегатор лекарств для Москвы и СПб. 23 303 препарата, 12 партнёрских аптек, цены MOCKED.
Production: https://aptekaa.ru. Полная архитектура — в `HANDOFF_2026-05-14.md` на VM (репо `den3992/aptekaappoisksite`).

**Стек**: React 19 + FastAPI + MongoDB 7 + nginx (Docker Compose) на Yandex Cloud VM.
**Главный SEO-приём**: nginx определяет ботов → отдаёт SSR `/api/seo/render` с schema.org Drug + Product + FAQPage; обычные пользователи получают React SPA.

## Sessions log

### 2026-05-15
**Done**:
- ✅ Проверен CSP на блокировку Yandex tracking pixels — **CSP в порядке**: `ym` загружен, `Ya.Metrika2` присутствует, 0 CSP-violations. `*.yandex.ru` (mc/clck), `mc.yandex.com`, `yastatic.net` уже разрешены в script-src/img-src/connect-src. SEO не пострадало.
- ✅ Убран флаг `force_empty_stock` у Нурофен Плюс (`db.medications.updateOne(..., $unset)`). Препарат снова показывает 12 мок-аптек МСК (190–260 ₽) + 8 СПб. Карта рендерится, бейдж рецептурного отпуска работает.

### 2026-05-14
**Done**:
- ✅ P0(a) **Gitleaks workflow restored**: новый PAT с scope `repo + workflow` получен; `.github/workflows/gitleaks.yml` восстановлен из `/tmp/gitleaks-workflow-backup.yml` на VM; запушен в `3e38369`; GitHub Actions run прошёл успешно (`gitleaks: completed/success`)
- ✅ `/app/memory/test_credentials.md` обновлён (admin `danil` / `Linad399@`, проверено через `/api/admin/login` HTTP 200 + JWT)
- ✅ P1 **OTC photos round 3**: 29 WebP файлов (≤87 KB, ≤600px), 31 SKU обновлены в MongoDB, закоммичены в `2b0dd74`
  - Тонзилгон Н (`bn`): 2 SKU
  - Эргоферон (`mm`): 2 SKU
  - Геделикс (`km`): 3 SKU
  - Доктор Мом (`un`): 3 SKU
  - Гриппферон (`fm`): 3 of 4 SKU (нет фото для aerosol)
  - Цитовир-3 (`cm`): 3 SKU
  - Тизин (`kv`): 5 of 8 SKU (нет фото для Эксперт×2, Классик дет)
  - Називин (`ur`): 6 SKU
  - Ринза (`un`): 4 SKU
- ✅ Файлы также docker-cp в running `deploy-frontend-1` — доступны через https://aptekaa.ru/img/meds/* немедленно (без rebuild)
- ✅ 7 новых префиксов добавлены: `bn`, `km`, `un`, `fm`, `cm`, `kv`, `ur`

**Coverage after round 3**: ~3 276 / 23 303 препаратов имеют фото (≈14.1%).

## Активные треки
См. подробный план в `/app/memory/ROADMAP.md`.

**Статус**: Мобильная адаптация + **PWA Service Worker** ЗАВЕРШЕНЫ. 14/14 PWA-тест PASS. Всего по всем итерациям: 86/88 (98%).
**Следующее**: Парсеры топ-4 аптечных сетей (Apteka.ru, Еаптека, ГорЗдрав, ZdravCity) — ~12 дней. План в `/app/memory/ROADMAP.md`.

### PWA Service Worker (iteration_9: 14/14 PASS)
- `public/manifest.json` — Russian PWA manifest (short_name='АптекаА', theme #0E9F6E, display=standalone, 7 icons)
- `src/serviceWorkerRegistration.js` — CRA-style registration helper (with onUpdate skipWaiting)
- `src/index.js` — register() вызывается в production
- `craco.config.js` — workbox-webpack-plugin GenerateSW, runtimeCaching:
  - `/api/*` → NetworkFirst (5s timeout, 10 min TTL, 200 entries)
  - same-origin images → CacheFirst (30 days, 400 entries, purgeOnQuotaError)
  - fonts/css/js → StaleWhileRevalidate
- `public/index.html` — `<link rel="manifest" href="%PUBLIC_URL%/manifest.json" />`
- Verified: SW scope=/, state=activated. Cache namespaces: workbox-precache-v2, image-cache, api-cache. Offline reload рендерит cached SPA shell (никаких Chrome dinosaur), повторная загрузка 30-50ms.

### День 9-10 (Catalog/Categories/CategoryDetail/PharmaciesList/P2 + маршрутизация)
- Catalog/Categories/CategoryDetail/PharmaciesList: H1 text-2xl на мобиле, search input type=search, letter-filter 8x8, карточки 2-col mobile, tap-zone h-11
- About/Contacts/Privacy/Consent: py-5 md:py-10, H1 text-2xl, sm:base
- NotFound: text-4xl md:text-5xl
- **Маршрутизация**: slug→id map в Home.jsx ({moskva:'msk', spb:'spb'}). Unknown slugs → `return <NotFound />` напрямую (URL сохраняется). Layout root + overflow-x-hidden
- Iteration_6: 19/21, iteration_7: regression на /moskva fixed, iteration_8: 8/8 PASS

### Покрытие тестами полное (97%)
- iter_1: 21/21 — дни 1-4 + ротирующиеся badges
- iter_3: 14/14 — fullscreen map
- iter_5: 10/10 — snap-points
- iter_6: 19/21 — дни 9-10
- iter_8: 8/8 — маршрутизация финал
- Всего: **72/74 (97%)** + 2 cosmetic non-blocker

### Auto-center карты (улучшение дня 7.5)
- `MedDetail.jsx`: PriceMap → React.forwardRef + useImperativeHandle экспортит `centerOn(lat, lng, zoom)`
- При тапе на pharmacy-item или маркер карты: setSnapPoint(0.25) + setTimeout(300ms) → centerOn(ph.lat, ph.lng, 15)
- 300ms ждём окончания snap-анимации, потом Yandex setCenter с duration:400ms
- Результат: 2GIS/Я.Карт UX — тап → sheet сжимается → камера летит на выбранную аптеку

### День 8 (PharmacyDetail.jsx)
- Mobile-first layout через CSS order: H1 → Карта → Meta-cards → sticky CTAs
- Desktop layout (lg:) — 2-col grid: H1+Meta+Route btn (col-1) | Карта row-span-2 (col-2)
- Один общий ref для карты (без дубликата) через `lg:row-span-2 lg:col-start-2`
- Tappable meta-cards: Адрес → routeHref, Телефон → tel:
- Sticky CTAs: «Позвонить» (белая) + «Маршрут» (зелёная), flex-1, h-12, bottom: calc(64px + safe-area + 8px), pointer-events на wrapper-уровне
- testids: pharmacy-h1, pharmacy-map, pharmacy-phone-link, pharmacy-route-btn (desktop), pharmacy-mobile-cta-wrap, pharmacy-mobile-phone, pharmacy-mobile-route
- pharmacyJsonLd Schema.org сохранён, регрессии нет

### День 7.5 (drag-handle + snap-points)
- vaul Drawer.Root с `snapPoints={[0.25, 0.55, 0.9]}` (числа, НЕ '25%' — vaul 1.1.2 парсит строки как пиксели)
- snapPoint state default 0.55, reset on fullscreen close
- `modal={false}` (карта кликабельна за sheet) + `dismissible={false}` (не закрыть свайпом)
- Drag-handle pill: `w-12 h-1.5 bg-slate-400 rounded-full` (заметная даже в темных условиях)
- Тап на pharmacy-item или маркер карты → `setSnapPoint(0.25)` (автоматическое скрытие sheet чтобы видеть карту)
- Test iteration_5: **10/10 PASS** на mobile 390x844, десктоп без регрессий

### День 7 (full-screen mode карты)
- `MedDetail.jsx`: state `mapFullscreen` + body.overflow lock + ESC handler
- Кнопка `Maximize2` data-testid `map-fullscreen-open` в шапке секции (md:hidden)
- Fullscreen section: `fixed inset-0 z-[70] bg-white flex flex-col`
- Top-bar: ChevronLeft close (`map-fullscreen-close`), название + цена/счёт аптек, Minimize2 (`map-fullscreen-minimize`), safe-area-inset-top
- Bottom-sheet (`map-pharmacy-sheet`) max-h-[42vh]: 12 аптек (`map-sheet-pharmacy-item`), тап → selectedId, bg-emerald-50/60. Маршрут link на каждой карточке. Sticky хедер sheet.
- `PriceMap` accepts `fullscreen` prop, useEffect → setTimeout 60ms → `mapRef.current.container.fitToViewport()` для устранения белой полосы между картой и sheet после resize
- Sticky CTA `mobile-show-on-map-wrap` скрыт при fullscreen
- Lucide imports: добавлены ChevronLeft, Maximize2, Minimize2
- Tested: iteration_2 (BUG: ChevronLeft missing) → iteration_3 (14/14 PASS + cosmetic fitToViewport fix)

### Дни 5-6 (MedDetail.jsx — самая большая работа)
- Фото на мобиле `max-w-[240px] mx-auto p-3`, на десктопе сохранено (`md:mx-0 md:max-w-none md:p-6`)
- H1 `text-2xl sm:text-3xl md:text-4xl leading-tight`
- Карта `h-[360px] md:h-[460px]`
- Pharmacy-row: новая mobile-вёрстка (название+адрес слева, цена справа + кнопки Позвонить/Маршрут полноширинные), desktop layout сохранён в `hidden sm:grid`
- Аналоги `grid-cols-2 md:grid-cols-3 lg:grid-cols-4` (раньше sm:grid-cols-2)
- Sticky mobile CTA «Показать N аптек на карте» (data-testid `mobile-show-on-map-btn`), `bottom: calc(64px + safe-area + 8px)`, скроллит к `[data-testid="med-map-section"]`. Только при `prices.length > 0`. Правильная грамматика для аптеку/аптеки/аптек.
- Все desktop регрессии — нет (проверено скриншотом 1440x900)

### Инциденты дня
- Docker buildkit заполнил tmp → `no space left`. Решено: `docker builder prune -af` + повторная сборка
- После recreate frontend получил новый IP в bridge-сети → edge видел старый IP → 502. Решено: `docker compose up -d --force-recreate edge`. Урок: при изменении frontend всегда после rebuild делать recreate edge тоже.

### Ротирующиеся trust-badges (Home.jsx)
5 badges (2k аптек / 23k препаратов / 18+ сетей / интерактивная карта / без регистрации) ротируют каждые 3 сек, fade 300ms. `aria-live="polite"`. data-testid="hero-trust-badge".

### День 4 (мобильная адаптация — Search.jsx)
- Sidebar `hidden lg:block`, на мобиле вместо него горизонтальная панель: кнопка «Фильтры» (`SlidersHorizontal`) + счётчик активных + чипы (категория, без рецепта) с ✕ + «Сбросить»
- shadcn Drawer (vaul) с фильтрами: переиспользуемый компонент `FiltersBody`, общий для sidebar и drawer; кнопка «Показать N результатов» закрывает drawer
- Карточки: 1 col на мобиле, 2 col sm:, 3 col lg:. `active:bg-slate-50`
- Pagination buttons `h-11` (tap-zone 44+)

### День 3 (мобильная адаптация — Home.jsx)
- `Home.jsx`: brand-блок hidden md:flex; H1 text-3xl→sm:4xl→md:5xl→lg:6xl; trust badge text-[11px]; hero search-form + "часто ищут" chips hidden md:flex (поиск через шапку); paddings sections компактнее на мобиле; CTA для аптек H2 text-2xl на мобиле
- `PartnersMarquee.jsx`: py-6 md:py-10; H2 "Наши партнёры" text-xl на мобиле

### День 2 (мобильная адаптация — voice + header polish)
- `frontend/src/components/Header.jsx`: + кнопка-микрофон `data-testid="header-voice-mic"` (md:hidden, tap-zone 44px) справа в поисковой строке. Диспатчит `window CustomEvent('voice-assistant:open')`. Плюс sticky-shadow на скролле (`scrolled` state + `transition-shadow`) + glassmorphism (`bg-white/95 backdrop-blur-md`)
- `frontend/src/components/VoiceAssistant.jsx`: useEffect слушает global event `voice-assistant:open` → setOpen(true). Плавающая launcher-кнопка теперь `hidden md:flex` — на мобиле скрыта (вход через mic в шапке), на десктопе сохранена.

### Изменения дня 1 (мобильная адаптация)
- `frontend/src/components/MobileTabBar.jsx` — НОВЫЙ: 5 пунктов (Главная/Поиск/Каталог/Аптеки/Ещё), `md:hidden`, safe-area-inset-bottom, активный пункт по pathname, «Поиск» фокусит инпут шапки, «Ещё» открывает Drawer
- `frontend/src/components/Layout.jsx` — переписан: `min-h-[100dvh]`, padding-bottom для мобилы, всегда рендерит Header (на главной десктоп скрыт через md:hidden)
- `frontend/src/components/Header.jsx` — принимает `hideOnDesktop` prop, двухстрочная шапка на мобиле (лого+город / поиск), city-selector виден на всех ширинах, удалён старый mobileOpen-механизм (теперь tab-bar), input padding-y увеличен до 44px tap-height на мобиле

## Backlog

### 🔴 P0 (user-action required)
1. **Ротировать `EMERGENT_LLM_KEY`** (Emergent Profile → Universal Key → Regenerate). Положить в `~/aptekaa/deploy/.env`, `docker compose up -d --force-recreate backend imap_worker`. (Пользователь отложил.)

### 🟡 P1 (можно делать сразу)
2. **Бронхикум** (3 SKU) — bronchicum.ru это SPA, статический HTML не отдаёт картинок. Нужен Playwright / Selenium / напрямую к /static/. Можно попробовать `apteka.ru` API (только image_url, не парсинг страницы).
3. **Тизин Эксперт** (2 SKU) и **Тизин Классик дет** (1 SKU) — нет публичных фото на tyzine.ru. Альтернативы: поискать на eapteka.ru, или kenvuepro.com.
4. **Гриппферон Аэрозоль** (1 SKU) — нет на firnm.ru. Спросить производителя.
5. **LLM enrichment** (`backend/scripts/enrich_meds.py`): с 890 → 2000+ карточек. Запускать только локально / препрод (Emergent блокирует prod IP).

### 🟢 P2
6. **Real prices** — убрать mocks, подключить партнёрские прайсы (IMAP worker уже готов).
7. **KRKA фото** (~207 SKU) — нужен прокси (TLS handshake висит).
8. **Биохимик фото** (~417 SKU) — найти рабочий каталог.
9. DNS TTL → 300; 2FA на reg.ru + Yandex Cloud; DNSSEC; fail2ban; backup-restore test; iDN cert для `аптекаа.рф`.

### 🔵 P3
- CSP nonce-based (A+ на securityheaders); Lockbox; WAF.

## Known bugs/quirks
- `/api/health` returns 405 instead of 200 (cosmetic)
- `/api/voice/chat` 403 on prod (Emergent blocks non-Emergent IPs)
- Nginx HTTP/2 + IDN warnings (non-breaking)
