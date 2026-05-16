# HANDOFF → Claude Code (2026-05-15)

Этот документ — точка передачи проекта **АптекаА** из агентской платформы
**Emergent** в **Claude Code Pro** (CLI). Прочитай его целиком перед первой
сессией.

---

## TL;DR — что нужно сделать (15 минут)

1. **Установи Claude Code** на свою машину:
   ```bash
   npm install -g @anthropic-ai/claude-code
   claude   # залогинься через браузер с Pro-аккаунта
   ```

2. **Получи SSH-ключ к VM**. Самый безопасный вариант — сгенерируй новый
   ключ на своей машине и добавь его на VM (см. раздел 3 ниже).

3. **Склонируй репозиторий**:
   ```bash
   git clone https://github.com/den3992/aptekaappoisksite.git ~/aptekaa
   cd ~/aptekaa
   ```

4. **Запусти Claude Code из папки**:
   ```bash
   cd ~/aptekaa && claude
   ```
   В корне репозитория уже лежит `CLAUDE.md` — Claude Code прочитает его
   автоматически и будет знать всё про проект.

5. **Первая проверка** — попроси Claude Code выполнить:
   ```
   ssh aptekaa 'cd ~/aptekaa/deploy && docker compose ps'
   ```
   Если все 5 контейнеров `Up` — переезд успешен.

---

## 1. Что уже сделано перед передачей

* `CLAUDE.md` создан в корне репозитория — он содержит всё ОПЕРАЦИОННОЕ знание
  о проекте: rebuild script, nginx workflow, MongoDB auth, известные ловушки,
  SEO-инвариaнты. Это "проектный system prompt", который Claude Code читает
  при каждом старте.
* Все изменения последних дней (mobile adaptation, PWA, SearchOverlay, 301
  редиректы, SEO-фикс, дисклеймер) **запушены в GitHub** (см. раздел 5).
* Документы в `/app/memory/` (`PRD.md`, `ROADMAP.md`) — это история и план.
  Они лежат в Emergent-контейнере, поэтому я скопировал их в репозиторий
  под `docs/` (раздел 4).
* На VM в `~/aptekaa/` лежит вся текущая версия кода, идентичная HEAD ветки
  `main` на GitHub.

---

## 2. Архитектура (краткое напоминание)

```
Пользователь (mobile / desktop)
    ↓ HTTPS
nginx (контейнер edge, порт 443) — TLS, rate-limit, CSP, bot UA detection
    ↓
    ├── /api/* → backend (FastAPI, порт 8001)
    │            ├── MongoDB (контейнер mongo)
    │            └── IMAP worker (контейнер imap_worker)
    └── /* (bot UA = Yandex/Google/Bing) → /api/seo/render?path=$1
        /* (browser) → frontend (контейнер nginx serving CRA build)
```

Всё запущено в Docker Compose на VM `89.169.137.36`. Никакого supervisor нет.
Никакого "локального dev-окружения" нет — Claude Code работает SSH'ем по VM.

---

## 3. SSH-ключ для VM (важная часть)

### Вариант A (рекомендуемый): свой новый ключ

```bash
# На своей машине
ssh-keygen -t ed25519 -f ~/.ssh/aptekaa_key -C "claude-code-laptop" -N ""
chmod 600 ~/.ssh/aptekaa_key
```

Теперь нужно добавить **публичную часть** на VM. Если у тебя ещё есть доступ
через старый Emergent-ключ — попроси меня (или себя) добавить новый ключ:

```bash
# Через консоль провайдера VM или через старый доступ:
cat ~/.ssh/aptekaa_key.pub  # покажет публичный ключ
# Скопировать его содержимое и добавить на VM:
ssh ubuntu@89.169.137.36 'cat >> ~/.ssh/authorized_keys' < ~/.ssh/aptekaa_key.pub
```

Проверка:
```bash
ssh -i ~/.ssh/aptekaa_key ubuntu@89.169.137.36 'whoami && hostname'
# Должно вывести: ubuntu, и hostname VM
```

### `~/.ssh/config` (удобство)

```sshconfig
Host aptekaa
  HostName 89.169.137.36
  User ubuntu
  IdentityFile ~/.ssh/aptekaa_key
  IdentitiesOnly yes
```

После этого: `ssh aptekaa 'docker compose ps'` без флагов.

### Вариант B: использовать существующий Emergent-ключ

На VM сейчас в `~/.ssh/authorized_keys` находится 3 ключа (Google IAP +
Emergent-ключ). Сам файл приватного ключа `aptekaa_key` существует **только
в моём Emergent-контейнере** и при моём завершении исчезает. Поэтому Variant A
обязателен.

---

## 4. Документы проекта в репозитории

После моих финальных коммитов (см. раздел 5) в репозитории появятся:

```
/CLAUDE.md                           ← системный контекст для Claude Code
/docs/HANDOFF_TO_CLAUDE_CODE.md      ← этот файл
/docs/PRD.md                         ← Product Requirements Doc
/docs/ROADMAP.md                     ← план задач (P0/P1/P2/P3)
/docs/HANDOFF_2026-05-10.md          ← старые handoff-доки (история)
/docs/HANDOFF_2026-05-14.md
```

`CLAUDE.md` — самое важное. Он содержит:
* Адрес VM, SSH-команды
* Команды rebuild фронтенда (с заметкой про YANDEX_MAPS_KEY)
* MongoDB-команды с аутентификацией
* Nginx workflow (active.conf vs edge-ssl.conf)
* Все продуктовые инварианты (binary бейджи, URL canonical /msk, SEO)
* Mobile UX patterns (Vaul snap-points, visualViewport hook, SearchOverlay)
* Known pitfalls (overflow-x:clip, scrollRestoration, le=100, data-vaul-no-drag)
* Active priorities (P0 парсеры, P1 ЖНВЛП+LLM, P2 affiliate+share, P3 фото)

---

## 5. Git state на момент передачи

* **Repo**: <https://github.com/den3992/aptekaappoisksite>
* **Branch**: `main`
* **HEAD on VM**: `f2a1e2c` (последний закоммиченный)
* **Untracked / modified files на VM**: ~33 файла с последних правок
  (mobile adaptation, PWA, SearchOverlay, etc.). Я сделаю финальный коммит
  с понятным сообщением и `git push origin main` непосредственно перед тем,
  как ты закроешь Emergent-сессию.

После моего финального push'a Claude Code сразу при `git pull` или `git clone`
получит полное актуальное состояние.

---

## 6. Что точно НЕ перенесётся

| Инструмент Emergent | Аналог в Claude Code |
|---------------------|----------------------|
| `testing_agent_v3_fork` | Нет прямого аналога. Можно подключить **playwright-mcp** через MCP-конфиг, тогда Claude Code запускает Playwright локально. Или просить Claude Code писать pytest+playwright тесты в `backend/tests/` и `frontend/tests/`. |
| `integration_playbook_expert_v2` | Web search (встроен) + официальная документация. Для Stripe/OpenAI/Gemini-интеграций просто проси Claude Code сделать `WebSearch` по нужной теме. |
| `support_agent` | Не нужен — Emergent-специфичен. |
| `EMERGENT_LLM_KEY` (универсальный ключ Anthropic+OpenAI+Gemini) | Нужно завести свой OpenAI / Anthropic API ключ. Pro-подписка Claude Code НЕ даёт API-доступ. Для LLM-enrichment-задачи (P1) тебе понадобится OpenAI key (~$5 на 23 000 препаратов с GPT-4o-mini). |
| Автоматический screenshot tool (Playwright) | Подключи `playwright-mcp` через `claude mcp add playwright npx -- -y @modelcontextprotocol/server-playwright`. Тогда Claude Code сможет делать скриншоты по запросу. |

---

## 7. Рекомендуемый первый prompt для Claude Code

После всей подготовки запусти Claude Code в папке `~/aptekaa` и отправь:

```
Прочитай CLAUDE.md в корне и docs/HANDOFF_TO_CLAUDE_CODE.md. Затем выполни
smoke test: ssh aptekaa 'docker compose ps' и убедись, что все 5 сервисов
(backend, frontend, mongo, edge, imap_worker) в статусе Up. После этого
покажи мне краткое резюме: что в проекте, на каком этапе, и какая
следующая приоритетная задача из ROADMAP.
```

Claude Code должен ответить:
1. Сводкой по проекту (информационная справочная для лекарств, MSK/SPB).
2. Статусом всех Docker-сервисов.
3. Следующей задачей — **P0 парсер-инфраструктура** (Apteka.ru, Eapteka,
   GorZdrav, ZdravCity).

Если всё это получится — переезд успешен.

---

## 8. После первой успешной сессии

* **Закоммить** обновлённый `CLAUDE.md` если Claude Code сам что-то в нём
  обновил (он умеет редактировать собственный системный промпт под проект).
* **Сразу запушь в GitHub** — это безопаснее чем держать всё только на VM.
* **Включи feature `auto-update` в Claude Code** — `claude --update`. Pro
  обновляется быстро, баги фиксят, MCP-серверы добавляют.

---

## 9. На что обратить внимание в первые часы

* **Контекст window**: Claude Code Pro (Sonnet 4.5) имеет ~200K токенов. Это
  меньше чем у меня в Emergent (~1M). Для длинных задач придётся чаще
  ссылаться на файлы, чем держать их в контексте.
* **Rate-limits Pro-подписки**: ~50 сообщений в 5 часов (точно — смотри
  актуальную страницу Anthropic). Для P0-парсеров одного промежутка должно
  хватать на 1 сетку (Apteka.ru), не больше.
* **Background bash**: `&` + `wait` + `jobs` работают как у меня. Для долгих
  rebuild'ов это критично.
* **Git push с CLAUDE.md**: я УЖЕ зафиксирую токен `ghp_eiZKv...` в remote
  URL, поэтому Claude Code сможет push'ить без отдельной настройки. ⚠️ Это
  значит токен виден в `.git/config` — после миграции **обнови GitHub PAT**
  для безопасности.

---

## 10. Чего я НЕ успел / открытые вопросы

* `EMERGENT_LLM_KEY` в `.env` на VM — **не ротирован** (пользователь
  отложил). Если Claude Code будет работать с LLM-enrichment, нужен либо
  новый ключ Emergent (через старый акк), либо собственный OpenAI key.
* Парсеры пока не реализованы. План в `docs/ROADMAP.md`.
* Биохимика и КРКА (~624 SKU без фото) — на P3.

---

## 11. Контакт меня (последний раз)

Если Claude Code на чём-то застрял и тебе нужно вернуться к моему
конкретному решению — посмотри:
* `git log --oneline -50` на VM или GitHub — все коммиты с понятными
  message
* `/app/memory/PRD.md` (на Emergent) и `docs/PRD.md` (после переезда) —
  pull-out из всех session
* `docs/HANDOFF_2026-05-14.md` и более ранние — детальная история по
  предыдущим сессиям

---

**Удачи. Проект в хорошем месте — мобилка готова, SEO в порядке, осталось
строить парсеры. Claude Code справится.**
