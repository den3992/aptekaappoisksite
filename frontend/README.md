# frontend/ — заглушка после миграции на Next.js (Phase 9)

Полный CRA-фронт (React + craco) удалён в Phase 9. Этот каталог остался
только ради `frontend/public/img` — **симлинка на `next/public/img/`** для
обратной совместимости с photo-агентом, который пишет фото препаратов
по старому пути.

## Что было

- `frontend/src/` — React-исходники (компоненты, страницы, CSS)
- `frontend/public/` — статика (favicon'ы, манифест, IndexNow-ключ, /img/, /logos/)
- `frontend/build/` — production-бандл (отдавался nginx'ом через `deploy/frontend.Dockerfile`)
- `frontend/package.json`, `craco.config.js`, и т.д.

Всё это удалено в коммите Phase 9 cleanup. История доступна в git
(до этого коммита).

## Куда переехало

- React-приложение → `next/` (Next.js 15, App Router, SSR)
- Статика из `public/` (favicon, manifest, IndexNow-key, /logos/) → `next/public/`
- Фото препаратов из `public/img/meds/*` → `next/public/img/meds/*`
  (~4500 файлов, ~108 МБ; не трекаются git'ом, см. `.gitignore`)

## Photo-agent

Photo-агент пишет в `frontend/public/img/meds/*.webp`. Через симлинк
файлы попадают в `next/public/img/meds/`, откуда Next.js их сервит.

После того как photo-агент будет переучен писать напрямую в
`next/public/img/meds/`, эту папку можно удалить целиком.
