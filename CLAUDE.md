# CLAUDE.md

Этот файл даёт Claude Code контекст для работы с репозиторием.

## О проекте

**MaxHub** — бот для мессенджера MAX (dev.max.ru), «всё в одном»:

- **Название бота:** MaxHub
- **Описание бота:** «Совместные списки дел, "Слово дня" и конвертер файлов — всё в одном боте. /help — список команд.»
- Название и описание задаются при создании у MasterBot; бот при старте дополнительно синхронизирует их через API (метод изменения информации о боте), чтобы данные в коде были источником правды.

### Функции

1. **Совместный список дел** — общий todo-лист на чат: `/todo add ...`, `/todo done N`, `/todo del N`, `/todo list`. Список привязан к `chat_id`, все участники чата работают с одним списком.
2. **«Слово дня»** — ежедневная рассылка слова с определением и примером в подписанные чаты (`/word`, `/word sub`, `/word unsub`). Рассылка по расписанию через APScheduler, словарь — `data/words.json`.
3. **Конвертер файлов/изображений** — пользователь отправляет изображение, бот предлагает кнопками целевой формат (png/jpg/webp/pdf), конвертация через Pillow; аудио/видео через ffmpeg — опционально, за фичефлагом.
4. **Админ-рассылка в ЛС** — команда `/broadcast` (только для `ADMIN_IDS`): массовая отправка информационного сообщения в личку всем **активным пользователям**. Активный = писал боту в ЛС за последние `BROADCAST_ACTIVE_DAYS` дней (по умолчанию 30). Сценарий через FSM: админ вводит `/broadcast` → бот просит текст → показывает превью с числом получателей → инлайн-кнопки «Отправить / Отменить» → рассылка строго через лимитер → итоговый отчёт (отправлено / не доставлено). Пользователи, заблокировавшие бота, помечаются `is_blocked=true` и исключаются из будущих рассылок.
5. **`/v`** — только для админов: текущий тег, git sha, время сборки.

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

```
.
├── app/
│   ├── main.py              # точка входа: Bot, Dispatcher, webhook, scheduler
│   ├── config.py            # pydantic-settings
│   ├── rate_limit.py        # исходящий лимитер (см. ниже)
│   ├── handlers/
│   │   ├── todo.py
│   │   ├── word_of_day.py
│   │   ├── converter.py
│   │   └── admin.py         # /v, /broadcast (FSM)
│   ├── services/            # бизнес-логика без привязки к MAX API
│   └── db/
│       ├── engine.py        # async engine + session factory
│       ├── models.py        # SQLAlchemy 2.x declarative (Mapped/mapped_column)
│       └── repo/            # репозитории: users, todos, subscriptions
├── alembic/                 # миграции (async env.py)
├── alembic.ini
├── data/words.json
├── tests/
├── deploy/
│   ├── Caddyfile
│   └── docker-compose.yml   # прод-компоуз (используется на сервере)
├── .github/workflows/
│   ├── ci.yml               # push/PR: ruff, pytest, docker build (без push)
│   └── deploy.yml           # ТОЛЬКО на push тега v*: build+push в GHCR, деплой по SSH
├── Dockerfile
├── docker-compose.yml       # локальная разработка (bot + postgres)
├── pyproject.toml
└── uv.lock
```

## Модели данных (минимум)

- `users`: user_id (PK), first_seen, last_activity_at, is_blocked, is_dm (писал ли в ЛС) — обновляется middleware на каждый апдейт; это база для определения «активных» получателей рассылки
- `todos`: id, chat_id (index), text, is_done, created_by, created_at
- `word_subscriptions`: chat_id (PK), subscribed_at
- `broadcasts`: id, admin_id, text, created_at, sent_count, failed_count — журнал рассылок

## Конфигурация (pydantic-settings, env / .env)

`BOT_TOKEN`, `DOMAIN`, `WEBHOOK_PATH`, `PORT`, `MODE` (webhook|polling), `ADMIN_IDS` (через запятую), `DATABASE_URL` (`postgresql+asyncpg://...`), `TZ` (default Europe/Moscow), `BROADCAST_ACTIVE_DAYS` (default 30), `APP_VERSION`, `GIT_SHA`, `BUILD_TIME`. Секреты только через env; в репо — `.env.example`.

## Ограничения MAX API (критично)

Все исходящие вызовы API идут через единый лимитер в `app/rate_limit.py`:

- **не более 2 сообщений в секунду в один чат** (per-chat token bucket, ключ — chat_id / user_id для ЛС)
- **не более 30 запросов в секунду суммарно** (глобальный лимитер)

Реализация: `aiolimiter.AsyncLimiter(30, 1)` глобально + `AsyncLimiter(2, 1)` на чат (dict с ленивым созданием и очисткой по TTL). Ни один хендлер не вызывает методы API в обход обёртки. Массовые рассылки («Слово дня», `/broadcast`) обязаны идти через эту же очередь — при 1000 получателей рассылка займёт ~35+ секунд, это нормально; рассылка выполняется фоновой задачей с прогрессом для админа. На 429 — экспоненциальный retry с jitter.

## Версионирование и деплой

- Версия приложения = git-тег (`v1.2.3`). Прокидывается в образ build-args `APP_VERSION`, `GIT_SHA`, `BUILD_TIME` → env.
- **CI** (`ci.yml`): на каждый push и PR — ruff check, ruff format --check, pytest (Postgres как service-контейнер), docker build.
- **CD** (`deploy.yml`): триггер строго `on: push: tags: ['v*']`. Build → push в GHCR (`{tag}` и `latest`) → SSH на сервер (secrets `SSH_HOST`, `SSH_USER`, `SSH_KEY`) → обновить `IMAGE_TAG` в `.env` → `docker compose pull && docker compose up -d`. Никакого деплоя с веток.
- Alembic-миграции применяются автоматически на старте контейнера (`alembic upgrade head` в entrypoint до запуска приложения).

## Команды разработки

```bash
uv sync
docker compose up -d postgres            # локальная БД
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "..."
MODE=polling uv run python -m app.main   # локальный запуск без вебхука
uv run ruff check . && uv run ruff format --check .
uv run pytest
docker compose up --build
```

## Конвенции

- Асинхронный код везде; блокирующие операции (Pillow, ffmpeg) — через `asyncio.to_thread`.
- SQLAlchemy 2.x style: `Mapped[...]`/`mapped_column`, `select()`, async sessions через DI/middleware; никакого legacy Query API.
- Схема БД меняется только через Alembic-миграции; `Base.metadata.create_all` не используется.
- Хендлеры тонкие: парсинг → сервис → ответ. Логика и БД — в `services/` и `db/repo/`.
- Сообщения бота на русском языке.
- Логи в stdout (JSON в проде), без файлов.
- Перед коммитом: ruff + pytest должны проходить.
