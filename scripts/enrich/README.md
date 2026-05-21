# Pharma Image Enrichment Pipeline

Скрипты для парсинга и применения фотографий медикаментов из открытых источников
к коллекции `medications` в MongoDB. Запускаются в любом контейнере с сетевым
доступом, файлы и обновления БД пушатся на прод через `ssh`/`scp`/`mongosh`.

## Архитектура

```
shared libs:
  fetch_lib.py    — параллельный HTTP + WebP-конвертация
  match_lib.py    — bulk regex-матчинг trade-name → label_name (через SSH mongosh)
  apply_lib.py    — SCP файлов + bulk update image_url + git commit/push
  mnn_translit.py — варианты MNN/торговых имён для Wikimedia search
  remote_lib.py   — версия match+apply для исполнения НА сервере (docker exec)

site-specific scrapers (имя → сайт/источник):
  akrikhin_scrape.py        akrikhin.ru               paginated /catalog/page{N}/
  avva_scrape.py            avva-rus.ru               sitemap, /production/
  belmed_scrape.py          belmedpreparaty.com
  berlin_chemie_scrape.py   berlin-chemie.ru          wp-sitemap medicines
  berlin_scrape.py          berlin-chemie.ru          (v1, deprecated)
  biosintez_scrape.py       biosintez.com             /products/ index
  canon_scrape.py           canonpharma.ru
  dalkhim_scrape.py         dalkhimpharm.ru           (v1 — catalog page)
  dalkhim_v2_scrape.py      dalkhimpharm.ru           wp-sitemap-tovar (138 URLs)
  endopharm_scrape.py       endopharm.ru
  microgen_scrape.py        microgen.ru               sitemap-iblock-7
  otcpharm_scrape.py        otcpharm.ru
  pharmasyntez_scrape.py    pharmasyntez.com
  pharmstd_scrape.py        pharmstd.ru
  promomed_scrape.py        promomed.com
  servier_scrape.py         servier.ru
  sotex_scrape.py           sotex.ru                  Playwright + modal dismiss
  valenta_scrape.py         valenta.ru
  veropharm_scrape.py       products.veropharm.ru
  vertex_scrape.py          vertex.spb.ru             sitemap-iblock-2
  veropharm_scrape.py       products.veropharm.ru
  wikimedia_scrape.py       Wikimedia Commons API
  rls_scrape_v2.py          rlsnet.ru                 scale-up (letters a–z, 1–2)

JS scripts: groupings/fixes для текстовых полей (не для картинок).
```

## Стандартный пайплайн нового скрипта

```python
from fetch_lib import parallel_fetch, parallel_download_webp
from match_lib import find_db_matches_bulk
from apply_lib import apply_plan

# 1. Discover product URLs (sitemap / catalog index / Playwright)
urls = get_product_urls()

# 2. Fetch product pages in parallel
pages = parallel_fetch(urls, workers=10, timeout=15)

# 3. Parse trade_name + image_url from each page
cards = [parse_page(html, url) for url, html in pages.items() if html]

# 4. Download images, save as PREFIX_<slug>.webp
res = parallel_download_webp(items, IMG_DIR, workers=12, timeout=15)

# 5. Bulk-match trade names against label_name, restricted to manufacturer
matches = find_db_matches_bulk(trade_names, manufacturer_pattern="...")

# 6. Build plan, then apply: SCP + bulk update + git push
apply_plan(plan, prefix=PREFIX, commit_msg="...")
```

## Запуск

Скрипты исходно живут в `/app/enrich/` отдельного development-контейнера с
доступом к internet и SSH-ключом к проду. SSH key: `~/.ssh/id_ed25519`,
host: `ubuntu@89.169.137.36`.

Playwright-скрипты требуют:
```bash
PLAYWRIGHT_BROWSERS_PATH=/pw-browsers python3 sotex_scrape.py
```

## Текущее покрытие
| Метрика | Значение |
|---|---|
| Всего карточек | 23 303 |
| С фото | 9 123 (39.15%) |
| Без фото | 14 180 |

См. `memory/PRD.md` (или `/app/memory/PRD.md` в dev-контейнере) для истории
изменений и списка ТОП-20 производителей без фото.
