# CLAUDE.md — АптекаА project context

> This file is auto-read by Claude Code at the start of each session.
> It contains the **operational knowledge** required to safely work on this
> codebase. Treat everything below as ground truth and do not deviate without
> explicit user approval.

---

## 1. Project overview

**АптекаА** (aptekaa.ru) — a pharmacy search service for Russia (Moscow + Saint
Petersburg) that aggregates medication prices and availability across multiple
pharmacy networks. ~23 000 SKUs in catalog, ~2 000 pharmacies indexed.

* **Frontend**: React (CRA + craco), Tailwind, Shadcn UI, Vaul drawers,
  Yandex Maps v2 JS API, Workbox PWA (Service Worker).
* **Backend**: FastAPI (Python 3.11), MongoDB, served as `/api/*` namespace.
* **Edge**: nginx 1.27 (TLS termination, SSR-for-bots routing, CSP, rate-limits).
* **SSR for crawlers**: a dedicated `/api/seo/render?path=...` endpoint that
  produces unique HTML for `User-Agent` matching Yandex/Google/Bing bots.
* **Deployment**: Docker Compose on a single VM. **All code lives on the VM**,
  there is no separate "local development" — work directly against it.

---

## 2. Remote VM (single source of truth)

| What       | Value                                              |
|------------|----------------------------------------------------|
| Host       | `89.169.137.36`                                    |
| User       | `ubuntu`                                           |
| SSH key    | `~/.ssh/aptekaa_key` (must be present locally)     |
| Code root  | `/home/ubuntu/aptekaa/`                            |
| Compose    | `/home/ubuntu/aptekaa/deploy/docker-compose.yml`   |
| Live URL   | <https://aptekaa.ru>                               |

Optional `~/.ssh/config` snippet (recommended):

```sshconfig
Host aptekaa
  HostName 89.169.137.36
  User ubuntu
  IdentityFile ~/.ssh/aptekaa_key
```

After that, simply `ssh aptekaa` works.

---

## 3. Mandatory development workflow

### 3.1 Always edit on the VM

There is no local copy of the running code — `git clone` of the GitHub repo is
useful for context (Claude can read files faster) but **the canonical state
lives on the VM**. To make a change:

```bash
# 1. Pull current file to /tmp/edit/ on your local machine
scp aptekaa:/home/ubuntu/aptekaa/path/to/file /tmp/edit/file

# 2. Edit it locally with mcp_search_replace / mcp_create_file

# 3. Push it back
scp /tmp/edit/file aptekaa:/home/ubuntu/aptekaa/path/to/file
```

(Or `ssh aptekaa 'cat > /home/ubuntu/aptekaa/path/to/file' <<'EOF' ... EOF`.)

### 3.2 Frontend rebuilds

**NEVER use plain `docker compose build frontend`.** BuildKit's cache will drop
the `REACT_APP_YANDEX_MAPS_KEY` and the maps stop loading. Always use:

```bash
ssh aptekaa 'bash ~/aptekaa/deploy/rebuild-frontend.sh'
```

The script does an explicit `--build-arg REACT_APP_YANDEX_MAPS_KEY=...` and
verifies the bundle contains the apikey at the end (line "✓ bundle … contains
Yandex Maps apikey").

Rebuild takes ~5-7 minutes. **Run it in background** (the SSH connection drops
otherwise):

```bash
ssh aptekaa 'nohup bash ~/aptekaa/deploy/rebuild-frontend.sh > /tmp/rebuild.log 2>&1 &'
# Then poll:
ssh aptekaa 'pgrep -f rebuild-frontend && echo running || echo done; tail -3 /tmp/rebuild.log'
```

If Docker runs out of disk during builds: `ssh aptekaa 'docker builder prune -af'`.

After every frontend rebuild, **also recreate edge** so it picks up the new
bundle hash:

```bash
ssh aptekaa 'cd ~/aptekaa/deploy && docker compose up -d --force-recreate edge'
```

### 3.3 Backend changes

```bash
# Edit files in backend/...
ssh aptekaa 'cd ~/aptekaa/deploy && docker compose restart backend'
```

If you changed `backend/requirements.txt` or `Dockerfile`:
```bash
ssh aptekaa 'cd ~/aptekaa/deploy && docker compose up -d --build --force-recreate backend'
```
This is slow (~3-4 min). Watch with `docker compose logs -f backend`.

### 3.4 Nginx changes

The container mounts `./nginx/active.conf` — **not** `edge-ssl.conf`. You must
copy and reload:

```bash
ssh aptekaa 'sudo cp ~/aptekaa/deploy/nginx/edge-ssl.conf ~/aptekaa/deploy/nginx/active.conf && \
  cd ~/aptekaa/deploy && \
  docker compose exec -T edge nginx -t && \
  docker compose exec -T edge nginx -s reload'
```

If `nginx -t` fails — don't reload, fix the config first.

### 3.5 MongoDB direct access

Authenticated mongosh inside the container:

```bash
ssh aptekaa 'cd ~/aptekaa/deploy && set -a && source .env && set +a && \
  docker compose exec -T mongo mongosh --quiet \
    -u "$MONGO_USER" -p "$MONGO_PASSWORD" --authenticationDatabase admin "$MONGO_DB" \
    --eval "db.medications.findOne({slug: \"nurofen-plyus...\"}, {slug:1, _id:0})"'
```

Important: every MongoDB response shipped via the API **must** exclude `_id`
(BSON `ObjectId` is not JSON-serializable). The codebase already does this
consistently; preserve the pattern.

### 3.6 Service supervisor (deprecated — only Docker now)

There is **no supervisor inside the host**. Everything runs as Docker Compose
services: `backend`, `frontend`, `mongo`, `edge`, `imap_worker`. Use `docker
compose ps`, `docker compose logs -f <svc>` for diagnostics.

---

## 4. Critical product invariants

1. **URL canonical form**: `/msk/...` and `/spb/...` (city.id, not slug). The
   sitemap and SSR canonical URLs use these. Aliases `/moskva` and
   `/sankt-peterburg` redirect 301 → canonical via nginx `rewrite` directives.
   The Home page accepts both forms as a safety net.
2. **Pricing data is mocked** (`backend/api/__init__.py::_mock_prices`) and
   tagged `prices_source: "demo"`. Real pricing will land in a future
   `prices_real` collection once parsers are implemented (see `ROADMAP.md`).
3. **Availability badges are binary**: "В наличии" (green chip on pharmacies
   that stock the SKU) / "Нет в наличии" (whole-card empty state when zero
   pharmacies stock it). No "Мало/Много" градации. Точное `qty` показывается
   only когда `med_source: "direct"` (future phase).
4. **`force_empty_stock` flag** on a medication forces the entire card into the
   empty state regardless of underlying prices. Was used for UX testing of
   Nurofen Plus, cleared 2026-05-15. Don't set it without a reason.
5. **Bot SSR is non-negotiable**: Yandex/Google MUST see fully-rendered HTML
   with Schema.org JSON-LD (Drug + BreadcrumbList + ProductGroup +
   Organization). Any change to routes/sections requires updating
   `backend/api/seo.py` accordingly.
6. **PWA service worker** uses Workbox with `skipWaiting: false`. The bot path
   is `/api/seo/render` which the SW never intercepts (denylist includes
   `/^\/api\//`). Safe to leave on.
7. **CSP allows only `*.yandex.ru`, `*.yandex.net`, `yastatic.net`,
   `mc.yandex.com`** for scripts/img/connect/style. Adding any third-party
   tracker requires CSP update in `deploy/nginx/edge-ssl.conf` + cp to
   `active.conf` + nginx reload.
8. **Yandex Maps API key**: comes from `REACT_APP_YANDEX_MAPS_KEY` env var
   injected at build time. Never inline it. The custom `rebuild-frontend.sh`
   ensures it lands in the bundle.

---

## 5. Mobile-specific UX patterns

(These were carefully tuned over multiple iterations — preserve them.)

* **`MobileTabBar`** (5 tabs, center is Search). Uses `useVisualViewportBottom`
  hook → exposes `--vv-bottom` and `--tabbar-offset` as CSS vars on `<html>`.
  Other floating elements (Footer pb, VoiceAssistant) use these vars to follow
  the bottom system UI on iOS Chrome (which collapses on scroll).
* **`SearchOverlay`** (md:hidden): a modal opened via
  `window.dispatchEvent(new CustomEvent('search-overlay:open'))`. Dispatch
  triggered by the Search tab AND by the Header search input on mobile (it
  blurs itself and dispatches). Up to 50 suggestions, scrolling the list blurs
  input, submitting blurs input.
* **MedDetail fullscreen map**: uses Vaul Drawer with snap-points
  `[0.25, 0.55, 0.9]`. The pharmacy-list inside has `data-vaul-no-drag` so
  scrolling the list doesn't drag the sheet. Pan/zoom on the map triggers a
  `pointerdown/wheel` DOM listener → sheet auto-shrinks to `0.25`. The Yandex
  fullscreen control is removed on mobile, kept on desktop (matchMedia
  conditional).
* **First-visit Search-tab pulse**: 3 rose-colored CSS `ping` rings (~3.6s),
  flag `aptekaa.tabbarSearchHintShown` in localStorage, plays once.

---

## 6. SEO checklist (do not break these)

* `https://aptekaa.ru/robots.txt` → served by backend, Yandex-friendly,
  `Clean-param`, `Host`.
* `https://aptekaa.ru/sitemap.xml` → sitemapindex, sub-sitemaps for static,
  pharmacies, categories, meds (chunked).
* `User-Agent: Googlebot|YandexBot|bingbot|...` for any URL → routed via nginx
  `location /` → `rewrite ^(.*)$ /api/seo/render?path=$1 last` → backend
  produces unique HTML for each page type:
  - `/` and `/{city}` → `render_home_for_bot`
  - `/{city}/preparaty/{slug}` → `render_med_for_bot`
  - `/{city}/preparaty` → `render_catalog_index_for_bot`
  - `/{city}/apteki/{slug}` → `render_pharmacy_for_bot`
  - `/{city}/apteki` → `render_pharmacies_index_for_bot`
  - `/{city}/kategorii/{slug}` → `render_category_for_bot`
  - `/{city}/kategorii` → `render_categories_index_for_bot`
  - `/kontakty`, `/o-servise`, `/dlya-aptek`, `/politika-konfidencialnosti`,
    `/soglasie-na-obrabotku-pd` → dedicated SSR templates.

Test crawler HTML directly:
```bash
curl -s -A "Googlebot" "https://aptekaa.ru/msk/preparaty/<slug>" | head -c 4000
```

---

## 7. Environment & secrets

Live on the VM in `~/aptekaa/deploy/.env`. Includes (do NOT commit, do NOT
print to logs):

* `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_DB`
* `REACT_APP_YANDEX_MAPS_KEY`
* `EMERGENT_LLM_KEY` (will be rotated when LLM enrichment resumes)
* `YANDEX_FOLDER_ID`, `ADMIN_TOKEN`
* `YANDEX_VERIFICATION` (for Webmaster ownership)

If you change `.env` → restart all services:
```bash
ssh aptekaa 'cd ~/aptekaa/deploy && docker compose up -d'
```

---

## 8. Active priorities (2026-05-15)

* **P0** (next): Pharmacy parsers — Apteka.ru, Eapteka, GorZdrav, ZdravCity.
  Plan in `/home/ubuntu/aptekaa/ROADMAP.md` (or `/app/memory/ROADMAP.md`).
  New `pharmacy-parser` service in compose, new `prices_real` collection,
  switch frontend to `availability=true` filter with green chip.
* **P1**: ЖНВЛП official ceiling prices, LLM enrichment of descriptions
  (currently 890 enriched / 23 303 total).
* **P2**: Admitad affiliate links (ZdravCity, 36.6), `navigator.share()` on
  med pages.
* **P3**: Scrape blocked photos for Biochemist (~417 SKUs) and KRKA (~207
  SKUs) via proxies.

---

## 9. Known pitfalls / lessons

* **Background processes for long-running commands**: SSH connection from
  Claude Code's bash will time out at 2 minutes. Always `nohup ... &` and poll.
* **`overflow-x: hidden` on Layout** breaks `position: sticky` for the Header
  on mobile. Use `overflow-x: clip` instead.
* **`history.scrollRestoration`** must be set to `manual` in `ScrollToTop.jsx`
  to prevent browsers from restoring scroll position on F5.
* **`Query(le=20)`** was the old limit for `/api/search/suggest`. Now `le=100`
  so the SearchOverlay can request 50.
* **Vaul `data-vaul-no-drag`** on the scrollable list inside a drawer is
  required, otherwise touchmove scrolling drags the sheet instead of scrolling
  the list.
* **`active.conf` vs `edge-ssl.conf`**: nginx mounts `active.conf`, but the
  source of truth is `edge-ssl.conf`. Always copy after edits.

---

## 10. Test credentials & smoke tests

`./memory/test_credentials.md` (if present) — emails/passwords for any seeded
admin/test accounts. Currently the project does NOT have user-facing auth, so
this file is typically empty.

Smoke test:
```bash
# Health
curl -s https://aptekaa.ru/api/health | head
# Suggest
curl -s 'https://aptekaa.ru/api/search/suggest?q=Нурофен&limit=5' | head -c 400
# Med detail
curl -s https://aptekaa.ru/api/medications/nurofen-plyus-200-mg-10-mg-tabletki-pokrytye-obolochkoy | head -c 400
# Bot SSR
curl -s -A 'Googlebot' https://aptekaa.ru/msk | grep -oE '<title>[^<]+'
```

---

_Last updated: 2026-05-15. When you make significant changes, append a
2-line note here so future Claude sessions know what shifted._
