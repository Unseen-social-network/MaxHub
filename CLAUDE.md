# CLAUDE.md

Этот файл даёт Claude Code контекст для работы с репозиторием.

## О проекте

**MaxHub** — бот для мессенджера MAX (dev.max.ru), «всё в одном»:

- **Название бота:** MaxHub
- **Описание бота:** «Совместные списки дел, "Слово дня" и конвертер файлов — всё в одном боте. /help — список команд.»
- Название и описание задаются при создании у MasterBot; бот при старте дополнительно синхронизирует их через API (метод изменения информации о боте), чтобы данные в коде были источником правды.

## 0. ЗАПРЕТЫ В КОММИТАХ И ИСТОРИИ (жёстко, без исключений)

Эти правила имеют наивысший приоритет. Нарушение = откатить коммит.

- В сообщениях коммитов, в теле PR, в комментариях кода, в `CHANGELOG`, в авторстве
  и в любых артефактах репозитория **ЗАПРЕЩЕНО** упоминать: `Claude`, `Anthropic`,
  `claude.ai`, `claude code`, `AI`, `ИИ`, `сгенерировано`, `assistant`, `LLM`, `Cursor`, `cursoragent@cursor.com`,`cursor.com`, `cursoragent`
  «при помощи нейросети» и любые синонимы, прямо или косвенно указывающие на
  происхождение кода от ИИ-ассистента.
- **НЕ добавлять** трейлеры вида `Co-Authored-By: Claude ...`,
  `Generated with ...`, `🤖 ...` и подобные. Коммиты должны выглядеть как
  написанные человеком-разработчиком.
- **НЕ менять** `user.name` / `user.email` в git-конфиге. Использовать те, что
  уже настроены в окружении. Если они не настроены — остановиться и спросить.
- Сообщения коммитов — на русском, в стиле Conventional Commits
  (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`), по делу, без воды и эмодзи.
- Перед каждым `git commit` мысленно проверить тело и заголовок на наличие
  запрещённых слов. Если хоть одно есть — переписать.

### Функции

1. **Совместный список дел** — общий todo-лист на чат: `/todo add ...`, `/todo done N`, `/todo del N`, `/todo list`. Список привязан к `chat_id`, все участники чата работают с одним списком.
2. **«Слово дня»** — ежедневная рассылка слова с определением и примером в подписанные чаты (`/word`, `/word sub`, `/word unsub`). Рассылка по расписанию через APScheduler, словарь — `data/words.json`.
3. **Конвертер файлов/изображений** — пользователь отправляет изображение, бот предлагает кнопками целевой формат (png/jpg/webp/pdf), конвертация через Pillow; аудио/видео через ffmpeg — опционально, за фичефлагом.
4. **Админ-рассылка в ЛС** — команда `/broadcast` (только для `ADMIN_IDS`): массовая отправка информационного сообщения в личку всем **активным пользователям**. Активный = писал боту в ЛС за последние `BROADCAST_ACTIVE_DAYS` дней (по умолчанию 30). Сценарий через FSM: админ вводит `/broadcast` → бот просит текст → показывает превью с числом получателей → инлайн-кнопки «Отправить / Отменить» → рассылка строго через лимитер → итоговый отчёт (отправлено / не доставлено). Пользователи, заблокировавшие бота, помечаются `is_blocked=true` и исключаются из будущих рассылок.
5. **`/v`** — только для админов: текущий тег, git sha, время сборки.
6. **Mini App** — веб-версия части механик бота (список дел на чтение, слово дня + подписка, рассылка для админов), открывается кнопкой `/app` внутри чата (`OpenAppButton`) по отдельному пути `MINIAPP_PATH` на том же домене, что и вебхук. Авторизация — через MAX Bridge `window.WebApp.initData`, подпись проверяется на бэкенде (HMAC-SHA256 по токену бота).

## Стек

- Python 3.12+, менеджер пакетов — **uv** (зависимости только в `pyproject.toml`, `uv.lock` коммитится; никаких pip/poetry/requirements.txt)
- Библиотека MAX Bot API: **maxapi** (aiogram-подобный стиль: Bot, Dispatcher, роутеры, фильтры, FSM). Документация API: https://dev.max.ru/docs-api
- Режим событий: **webhook** через FastAPI + uvicorn (`maxapi[fastapi]`); polling — только локально для разработки
- БД: **PostgreSQL 16** + **SQLAlchemy 2.x (async)** + **asyncpg**; миграции — **Alembic** (async-шаблон); конфигурация — **pydantic-settings**
- Планировщик: APScheduler (AsyncIOScheduler)
- Reverse-proxy и HTTPS: **Caddy** в docker compose — автоматически получает и продлевает сертификаты Let's Encrypt для домена из env `DOMAIN`
- Docker + docker compose (сервисы: `bot`, `postgres`, `caddy`)
- Линт/формат: ruff; тесты: pytest + pytest-asyncio (тесты БД — против Postgres в docker, не sqlite)

## Структура

Каталоги совпадают по конвенции с соседними ботами (`culture-max-bot`, `banword-max-bot`): `src/<package>/` layout, `docker/` со всеми docker-файлами, `migrations/` вместо `alembic/`, корневой `Makefile`, плоский `tests/`.

```
.
├── src/bot/
│   ├── __main__.py           # точка входа: Bot, Dispatcher, webhook, scheduler
│   ├── config.py              # pydantic-settings
│   ├── handlers/
│   │   ├── common.py           # /start, /help
│   │   ├── todo.py
│   │   ├── word_of_day.py
│   │   ├── converter.py
│   │   ├── admin.py             # /v, /broadcast (FSM)
│   │   └── fallback.py           # ответ на нераспознанную команду
│   ├── middlewares/
│   │   ├── activity.py          # апдейт активности пользователя + сессия в data
│   │   └── limiter.py            # RateLimitedBot в data
│   ├── miniapp/                   # веб-версия механик бота (см. «Функции» п.6)
│   │   ├── auth.py                 # проверка подписи MAX Bridge initData
│   │   ├── router.py                # FastAPI-роутер: /, /api/todos, /api/word, /api/broadcast
│   │   └── static/index.html         # фронтенд (vanilla JS, без сборки)
│   ├── services/                 # бизнес-логика без привязки к MAX API
│   │   ├── rate_limit.py          # исходящий лимитер (см. ниже)
│   │   ├── broadcast.py
│   │   ├── converter.py
│   │   └── word_of_day.py
│   └── db/
│       ├── session.py             # async engine + session factory
│       ├── models.py               # SQLAlchemy 2.x declarative (Mapped/mapped_column)
│       └── repositories/            # репозитории: users, todos, subscriptions, broadcasts
├── migrations/                # Alembic-миграции (async env.py)
├── alembic.ini
├── data/words.json
├── tests/                     # плоский, файлы с префиксом слоя: test_db_*, test_handlers_*, test_services_*
├── docker/
│   ├── Dockerfile
│   ├── docker-entrypoint.sh
│   ├── docker-compose.local.yml         # локальная разработка (bot + postgres)
│   ├── docker-compose.prod.nginx.yml    # прод-компоуз (реально используется на сервере — за существующим nginx)
│   ├── docker-compose.prod.caddyfile.yml # альтернатива со встроенным Caddy (если 443 свободен)
│   ├── Caddyfile
│   └── nginx/maxhub.conf.example
├── .github/workflows/
│   ├── ci.yml               # push/PR: ruff, pytest, docker build (без push)
│   └── deploy.yml           # ТОЛЬКО на push тега v*: build+push в GHCR, деплой по SSH
├── Makefile                  # стандартные команды разработки (make help)
├── pyproject.toml
└── uv.lock
```

## Модели данных (минимум)

- `users`: user_id (PK), first_seen, last_activity_at, is_blocked, is_dm (писал ли в ЛС) — обновляется middleware на каждый апдейт; это база для определения «активных» получателей рассылки
- `todos`: id, chat_id (index), text, is_done, created_by, created_at
- `word_subscriptions`: chat_id (PK), subscribed_at
- `broadcasts`: id, admin_id, text, created_at, sent_count, failed_count — журнал рассылок

## Конфигурация (pydantic-settings, env / .env)

`BOT_TOKEN`, `DOMAIN`, `WEBHOOK_PATH`, `MINIAPP_PATH` (default `/miniapp`), `PORT`, `MODE` (webhook|polling), `ADMIN_IDS` (через запятую), `DATABASE_URL` (`postgresql+asyncpg://...`), `TZ` (default Europe/Moscow), `BROADCAST_ACTIVE_DAYS` (default 30), `APP_VERSION`, `GIT_SHA`, `BUILD_TIME`. Секреты только через env; в репо — `.env.example`.

## Ограничения MAX API (критично)

Все исходящие вызовы API идут через единый лимитер в `src/bot/services/rate_limit.py`:

- **не более 2 сообщений в секунду в один чат** (per-chat token bucket, ключ — chat_id / user_id для ЛС)
- **не более 30 запросов в секунду суммарно** (глобальный лимитер)

Реализация: `aiolimiter.AsyncLimiter(30, 1)` глобально + `AsyncLimiter(2, 1)` на чат (dict с ленивым созданием и очисткой по TTL). Ни один хендлер не вызывает методы API в обход обёртки. Массовые рассылки («Слово дня», `/broadcast`) обязаны идти через эту же очередь — при 1000 получателей рассылка займёт ~35+ секунд, это нормально; рассылка выполняется фоновой задачей с прогрессом для админа. На 429 — экспоненциальный retry с jitter.

## Версионирование и деплой

- Версия приложения = git-тег (`v1.2.3`). Прокидывается в образ build-args `APP_VERSION`, `GIT_SHA`, `BUILD_TIME` → env.
- **CI** (`ci.yml`): на каждый push и PR — ruff check, ruff format --check, pytest (Postgres как service-контейнер), docker build.
- **CD** (`deploy.yml`): триггер `on: workflow_run` от `CI`, запускается только когда `ci.yml` завершился с `conclusion == success` и это был push тега (`head_branch` начинается с `v`) — деплой тега с упавшим/ещё бегущим CI невозможен. Build → push в GHCR (`{tag}` и `latest`) → синхронизировать `docker/docker-compose.prod.nginx.yml` из репозитория на сервер (секреты в `.env` не трогаются, живут только на сервере) → SSH на сервер (secrets `SSH_HOST`, `SSH_USER`, `SSH_KEY`, опционально `SSH_PORT`, `DEPLOY_PATH`, по умолчанию `/opt/max-bot`) → обновить `IMAGE_TAG`/`APP_VERSION`/`GIT_SHA`/`BUILD_TIME` в `.env` (иначе устаревшие значения из `.env` перебивают то, что реально запечено в образ — `docker-compose.prod.*.yml` пробрасывает их в контейнер через `environment:` с фолбэком `${APP_VERSION:-dev}` и т.п., так `/v` всегда показывает то, что реально задеплоено) → дописать строку в `deploy_history.log` на сервере (`timestamp tag sha`, для ручного отката на предыдущий тег — образы остаются в GHCR) → `docker compose -f docker-compose.prod.nginx.yml pull && up -d`. Бот публикуется только на `127.0.0.1:PORT`, HTTPS терминирует уже работающий на сервере nginx (см. `docker/nginx/README.md`). Никакого деплоя с веток.
- Alembic-миграции применяются автоматически на старте контейнера (`alembic upgrade head` в entrypoint до запуска приложения).

## Команды разработки

Через `make` (см. `make help` за полным списком) или напрямую через `uv`:

```bash
make install                              # uv sync
make migrate                              # alembic upgrade head
make migration m="описание"                # новая миграция
make run                                   # локальный запуск без вебхука (MODE=polling)
make lint && make format                   # ruff check + ruff format
make test                                  # pytest (нужен запущенный postgres)
make up-local                              # docker compose -f docker/docker-compose.local.yml up --build (bot + postgres)
make down-local
```

## Конвенции

- Асинхронный код везде; блокирующие операции (Pillow, ffmpeg) — через `asyncio.to_thread`.
- SQLAlchemy 2.x style: `Mapped[...]`/`mapped_column`, `select()`, async sessions через DI/middleware; никакого legacy Query API.
- Схема БД меняется только через Alembic-миграции; `Base.metadata.create_all` не используется.
- Хендлеры тонкие: парсинг → сервис → ответ. Логика и БД — в `services/` и `db/repo/`.
- Сообщения бота на русском языке.
- Логи в stdout (JSON в проде), без файлов.

# Стартовый промт для Claude Code

Скопируй текст ниже в первое сообщение Claude Code в пустом репозитории (в котором уже лежит CLAUDE.md).

---

Создай с нуля production-ready бота **MaxHub** для мессенджера MAX по описанию в CLAUDE.md. Работай поэтапно, после каждого этапа проверяй, что проект запускается и тесты проходят.

**Этап 1 — каркас проекта.**
Инициализируй проект через `uv init` (Python 3.12). Зависимости: maxapi (extra fastapi), fastapi, uvicorn, sqlalchemy[asyncio]>=2.0, asyncpg, alembic, pydantic-settings, apscheduler, aiolimiter, pillow. Dev: ruff, pytest, pytest-asyncio. Создай структуру каталогов из CLAUDE.md, `app/config.py` на pydantic-settings (BOT_TOKEN, DOMAIN, WEBHOOK_PATH, PORT, MODE, ADMIN_IDS, DATABASE_URL, TZ, BROADCAST_ACTIVE_DAYS, APP_VERSION, GIT_SHA, BUILD_TIME), `.env.example`, `.gitignore`.

**Этап 2 — база данных.**
`app/db/engine.py` (async engine + async_sessionmaker), модели SQLAlchemy 2.x (Mapped/mapped_column) из раздела «Модели данных» CLAUDE.md: users, todos, word_subscriptions, broadcasts. Настрой Alembic с async env.py, сгенерируй начальную миграцию. Репозитории в `app/db/repo/`. Middleware диспетчера: на каждый апдейт — upsert пользователя (last_activity_at, is_dm для личных сообщений) и прокидывание сессии в хендлеры. Docker compose для разработки: postgres:16 + bot. Тесты репозиториев против реального Postgres.

**Этап 3 — ядро бота и лимитер.**
`app/rate_limit.py`: обёртка над Bot, через которую идут ВСЕ исходящие вызовы API. Глобальный лимит 30 req/s (aiolimiter) + 2 msg/s на каждый chat_id (ленивый словарь лимитеров с очисткой по TTL). Ретраи с экспоненциальным backoff на 429/сетевые ошибки. Unit-тесты: 5 сообщений в один чат — не быстрее ~2 сек; глобальный лимит соблюдается. `app/main.py`: Bot + Dispatcher; MODE=polling для разработки, MODE=webhook — FastAPI с эндпоинтом вебхука и `/healthz`. На старте бот синхронизирует своё имя «MaxHub» и описание через API-метод изменения информации о боте.

**Этап 4 — фичи.**
1. Совместный todo-лист на чат: `/todo add <текст>`, `/todo list`, `/todo done <n>`, `/todo del <n>`; нумерованный вывод с отметками, инлайн-кнопки done/del.
2. «Слово дня»: `/word`, `/word sub`, `/word unsub`; APScheduler шлёт слово ежедневно в 09:00 (TZ из env) во все подписанные чаты строго через лимитер. Заполни `data/words.json` 30 словами (слово, определение, пример).
3. Конвертер изображений: на присланное изображение — инлайн-кнопки форматов (png/jpg/webp/pdf), конвертация Pillow в `asyncio.to_thread`, лимит входного файла 20 МБ, понятные ошибки.
4. `/start`, `/help` с описанием всех функций.

**Этап 5 — админка.**
1. `/v` — только для ADMIN_IDS: `версия: {APP_VERSION}, sha: {GIT_SHA}, собрано: {BUILD_TIME}`. Не-админам не отвечать.
2. `/broadcast` — только для ADMIN_IDS, FSM-сценарий: бот просит текст рассылки → показывает превью и число активных получателей (users с is_dm=true, is_blocked=false, last_activity_at за последние BROADCAST_ACTIVE_DAYS дней) → инлайн-кнопки «✅ Отправить» / «❌ Отменить» → рассылка фоновой asyncio-задачей строго через лимитер, промежуточный прогресс админу каждые ~50 получателей → итоговый отчёт «отправлено X, не доставлено Y». Ошибки доставки (пользователь заблокировал бота) → is_blocked=true. Каждая рассылка пишется в таблицу broadcasts. Напиши тест сервиса рассылки (выборка активных, учёт заблокированных).

**Этап 6 — Docker и HTTPS.**
Multi-stage Dockerfile на образах `ghcr.io/astral-sh/uv`: build-args APP_VERSION/GIT_SHA/BUILD_TIME → env; non-root; entrypoint: `alembic upgrade head` → запуск приложения; healthcheck на `/healthz`. Прод `deploy/docker-compose.yml`: сервисы `bot` (образ `ghcr.io/<owner>/<repo>:${IMAGE_TAG}`, env из `.env`), `postgres:16` (volume, healthcheck; bot стартует после healthy), `caddy` (80/443, volume для сертификатов). `deploy/Caddyfile`: `{$DOMAIN}` → reverse_proxy bot — Caddy сам получает и продлевает сертификаты Let's Encrypt. После старта бот подписывает вебхук на `https://{DOMAIN}{WEBHOOK_PATH}`.

**Этап 7 — CI/CD.**
`.github/workflows/ci.yml`: на push и pull_request — uv sync, ruff check + format check, pytest (postgres как service-контейнер), docker build без пуша.
`.github/workflows/deploy.yml`: триггер `on: workflow_run` (`workflows: ["CI"]`, `types: [completed]`), job гейтится условием `conclusion == 'success' && event == 'push' && startsWith(head_branch, 'v')` — деплой идёт только после зелёного `ci.yml` на том же тег-коммите (`head_sha` уходит и в checkout `ref`, и в build-args `GIT_SHA`; `head_branch` = имя тега → `TAG`/`APP_VERSION`). Шаги: checkout нужного sha → docker build с build-args (APP_VERSION/GIT_SHA/BUILD_TIME) → push в GHCR с тегами `{tag}` и `latest` → scp актуального `docker/docker-compose.prod.nginx.yml` на сервер → деплой через appleboy/ssh-action (secrets `SSH_HOST`, `SSH_USER`, `SSH_KEY`, опционально `SSH_PORT`, `DEPLOY_PATH` по умолчанию `/opt/max-bot`): на сервере `cd /opt/max-bot && sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG={tag}/" .env && docker compose -f docker-compose.prod.nginx.yml pull && docker compose -f docker-compose.prod.nginx.yml up -d && docker image prune -f`.

**Этап 8 — финал.**
README.md на русском: функции, получение токена у MasterBot (имя MaxHub, описание из CLAUDE.md), настройка сервера (/opt/maxbot, .env с BOT_TOKEN/DOMAIN/ADMIN_IDS/POSTGRES_PASSWORD/IMAGE_TAG, DNS, порты 80/443), GitHub secrets, процесс релиза (`git tag v1.0.0 && git push --tags`), как сделать рассылку через /broadcast. Прогони ruff и pytest, проверь `docker compose up --build`. Осмысленные коммиты по этапам.

Важно: сверяйся с актуальной документацией maxapi и MAX Bot API (https://dev.max.ru/docs-api) — не выдумывай сигнатуры методов; если не уверен в методе библиотеки, проверь исходники пакета в окружении.

---

## Перед запуском промта

1. Создай пустой репозиторий на GitHub, положи в корень `CLAUDE.md`.
2. Получи токен у MasterBot в MAX (имя: **MaxHub**, описание: «Совместные списки дел, "Слово дня" и конвертер файлов — всё в одном боте»).
3. GitHub → Settings → Secrets and variables → Actions: `SSH_HOST`, `SSH_USER`, `SSH_KEY`.
4. На сервере: Docker + compose plugin, каталог `/opt/maxbot` с `.env` (BOT_TOKEN, DOMAIN, ADMIN_IDS, POSTGRES_PASSWORD, IMAGE_TAG=latest), DNS A-запись домена на сервер, открыты порты 80/443.
- Перед коммитом: ruff + pytest должны проходить.
