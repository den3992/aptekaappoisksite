# PRD — АптекаА Image Enrichment

## Original problem statement
Connect to project «АптекаА» (aptekaa.ru) via SSH (ubuntu@89.169.137.36) and GitHub
(den3992/aptekaappoisksite.git) to scrape product photos for medication cards and
enrich the `medications` MongoDB collection.

### Constraints
- Photos must be saved as `.webp` in `/frontend/public/img/meds/` and pushed to git.
- No scraping of aggregators (apteka.ru, eapteka.ru, rigla.ru).
- Production server is geo-blocked by the proxy → all scraping runs locally in
  `/app/enrich/`, then files/DB updates are pushed via SSH/SCP/mongosh.

## Architecture
```
/app/enrich/
├── fetch_lib.py             # parallel http + WebP conversion
├── match_lib.py             # bulk regex matching against label_name (via SSH mongosh)
├── apply_lib.py             # SCP files + bulk update image_url + git commit/push
├── remote_lib.py            # equivalent of match+apply but for running ON the server
├── mnn_translit.py          # MNN/trade name query variants for Wikimedia search
├── *_scrape.py              # per-manufacturer scrapers (~25 in total)
└── wc_*.py / rls_*.py       # broad scrapers
```
Remote server: `/home/ubuntu/aptekaa/`, mongo via `docker exec deploy-mongo-1 mongosh`.

## Coverage timeline
| Step | with_img | total | %
|---|---|---|---|
| Session start (fork) | 8 735 | 23 303 | 37.48 % |
| After scrapers | 9 123 | 23 303 | 39.15 % |
| After name-field rematch | **9 252** | 23 303 | **39.70 %** |

### This session adds (+517 cards, +2.22 pp)
**Phase 1 — new scrapers (+388):**
- Sotex (Playwright + modal dismiss): +2
- Microgen (sitemap): +12
- Berlin-Chemie (wp-sitemap medicines): +10
- Biosintez (catalog index): +84
- Avva-Rus (sitemap /production/): +15
- RLS v2 (letter index a–z, 1–2): +4
- Akrikhin (paginated /catalog/): +30
- Wikimedia Commons rerun: +107
- Dalkhim v2 (sitemap-tovar): +119
- Vertex (sitemap-iblock-2): +2
- Veropharm (products subdomain): +3

**Phase 2 — match_lib upgraded with 3rd tier (`name` field) + rematch_all (+129):**
- Microgen rematch: +66
- Berlin-Chemie rematch: +10
- Akrikhin rematch: +5
- Dalkhim rematch: +2
- Vertex rematch: +3
- RLS rematch: +43

## What works (verified accessible from container)
- ✅ Static manufacturer sites with sitemap.xml: berlin-chemie.ru, dalkhimpharm.ru,
  microgen.ru, biosintez.com, avva-rus.ru, akrikhin.ru, vertex.spb.ru,
  products.veropharm.ru
- ✅ Playwright catalogs requiring modal-dismiss: sotex.ru, endopharm.ru
- ✅ RLS scraping (rlsnet.ru)
- ✅ Wikimedia Commons API

## What's blocked
- ❌ DNS does NOT resolve from the container: krka-rus.ru, krasfarma.ru, biokhimik.com,
  pfk-obnovlenie.ru (real catalog), tulapharm.ru, sintez.org (only /lander), takedaprod.ru,
  binnopharm.ru, welfarm.ru, niarmedic.ru, firnm.ru, gedeonrichter.ru, geropharm.com sitemap useless
- ❌ HTTP 403/451 (geo block): nizhpharm.ru, stada.ru, drugs.com
- ❌ JS-only SPA with no catalog API: ozonpharm.ru, takeda.com/ru-ru, sanofi.ru

## Pending / backlog
- P1 — Implement crowdsourcing button "Прислать фото" on empty cards for legal,
  ongoing user contributions.
- P1 — Generate placeholder images via Nano Banana (Gemini) for the remaining ~60%
  cards where no real photo can be obtained.
- P2 — Re-enable broader Wikimedia search with deeper query variants (currently
  hit rate ~1 %).
- P2 — Add more loose match tiers to match_lib (e.g. case-insensitive MNN
  matching, transliteration) — already partly addressed by Tier 3.

## match_lib upgrade (this session)
Tier 1: strict regex on `label_name` (anchored brand + form keyword tail).
Tier 2: loose regex on `label_name` (same, no leading anchor) — runs only if
        Tier 1 yields zero.
Tier 3: NEW — strict regex on `name` field, anchored brand + word-boundary tail
        (allows variant/dose follow-ups like "Мезим форте 10000"). Runs ALWAYS
        and unions into the result set. This is what unlocks variants the
        label_name regex misses because the tail token is a variant qualifier
        (форте, плюс, дуо, Про, 10000) not a form descriptor.

Util: `rematch_all.py` re-runs find_db_matches_bulk against every prior
manifest in /tmp/<prefix>_products.json and applies image_url to newly-matched
unphotographed slugs. `rls_rematch.py` does the same for RLS v2 cache.

## Top untouched manufacturers (no photos)
| Cards | Manufacturer | Web status |
|---|---|---|
| 352 | АО БИОХИМИК | DNS blocked |
| 274 | ООО ТУЛЬСКАЯ ФАРМАЦЕВТИЧЕСКАЯ ФАБРИКА | DNS blocked |
| 205 | АО ПФК ОБНОВЛЕНИЕ | DNS blocked |
| 203 | ОАО СИНТЕЗ | sintez.org has empty sitemap |
| 154 | ООО РУЗФАРМА | unknown site |
| 141 | ДЖОДАС ЭКСПОИМ (India) | unknown |
| 123 | АО КРКА | DNS blocked (krka-rus.ru) |

## Key Mongo schema
medications: `{slug, name, label_name, mnn, manufacturer, image_url, dedup_key, enrichment}`

## Critical notes for next agent
- All commands run on the local container; the only operations on remote are
  `scp` (image upload) + `ssh docker exec mongosh` (DB updates) + `git push` from remote.
- `~/.ssh/id_ed25519` is the SSH key; host is `ubuntu@89.169.137.36`.
- Playwright is installed at `/pw-browsers` — invoke with
  `PLAYWRIGHT_BROWSERS_PATH=/pw-browsers python3 …`.
- For ANY new manufacturer site:
  1. curl the homepage; locate sitemap or /products|catalog/.
  2. Pull product URLs, fetch each in parallel via `fetch_lib.parallel_fetch`.
  3. Extract H1 (trade name) + main image via BeautifulSoup.
  4. `find_db_matches_bulk(trade_names, manufacturer_pattern=…)` then `apply_plan`.
- For modal-blocked or Vue-SPA catalogs: Playwright + dismiss modal + click
  "Показать ещё" until exhausted.
- ALWAYS pass a `manufacturer_pattern` to `find_db_matches_bulk` — otherwise
  brand-name collisions across manufacturers (e.g. several brands of Метформин)
  will pollute the result.
