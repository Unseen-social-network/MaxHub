# MaxHub

Бот для мессенджера MAX (dev.max.ru), «всё в одном»: совместные списки дел, «Слово дня» и конвертер изображений.

**Описание бота (используется при регистрации у MasterBot):**
«Совместные списки дел, "Слово дня" и конвертер файлов — всё в одном боте. /help — список команд.»

## Функции

1. **Совместный список дел** — общий todo-лист на чат:
   - `/todo add <текст>` — добавить дело
   - `/todo list` — показать список (нумерованный, с инлайн-кнопками ✅/🗑)
   - `/todo done <n>` — отметить дело выполненным
   - `/todo del <n>` — удалить дело
2. **«Слово дня»** — ежедневная рассылка слова с определением и примером:
   - `/word` — показать слово дня прямо сейчас
   - `/word sub` — подписать чат на ежедневную рассылку (09:00 по времени из `TZ`)
   - `/word unsub` — отписать чат
3. **Конвертер изображений** — пришлите картинку, бот предложит кнопками формат (PNG/JPG/WEBP/PDF) и вернёт файл. Лимит входного файла — 20 МБ.
4. **Админ-рассылка** (`/broadcast`, только для `ADMIN_IDS`) — мастеровый сценарий: текст → превью с числом активных получателей → подтверждение → фоновая рассылка в личку всем, кто писал боту за последние `BROADCAST_ACTIVE_DAYS` дней.
5. **`/v`** (только для `ADMIN_IDS`) — версия, git sha и время сборки текущего деплоя.
6. `/start`, `/help` — список команд.

## Стек

Python 3.12+ / uv, библиотека `maxapi`, FastAPI + uvicorn (webhook), PostgreSQL 16 + SQLAlchemy 2.x (async) + Alembic, APScheduler, Docker + Caddy (авто-HTTPS). Подробности — в [CLAUDE.md](CLAUDE.md).

## Локальная разработка

```bash
make install                # uv sync
cp .env.example .env        # заполните BOT_TOKEN своим токеном для локальных проверок
make migrate                 # alembic upgrade head (нужен запущенный postgres, см. make up-local)
make run                      # MODE=polling, локальный запуск без вебхука
```

Полезные команды (см. полный список через `make help`):

```bash
make lint && make format      # ruff check + ruff format
make test                      # тесты (нужен запущенный postgres)
make up-local                   # docker compose -f docker/docker-compose.local.yml up --build (bot + postgres)
make migration m="..."           # новая миграция
```

## Получение токена бота

1. Откройте MasterBot в MAX и создайте нового бота.
2. Укажите имя **MaxHub** и описание:
   «Совместные списки дел, "Слово дня" и конвертер файлов — всё в одном боте. /help — список команд.»
3. Сохраните выданный токен — он понадобится как `BOT_TOKEN` в `.env` на сервере.

Бот при старте дополнительно синхронизирует имя и описание через API (best-effort, метод не входит в официальную swagger-спецификацию MAX — при ошибке синхронизации бот просто логирует предупреждение и продолжает работать).

## Настройка сервера

Требования: Docker + плагин `docker compose`, доменное имя с A-записью, указывающей на сервер, открытые порты 80 и 443.

По умолчанию используется каталог `/opt/maxbot` — при необходимости его можно
изменить через секрет `DEPLOY_PATH` (см. раздел «GitHub Secrets» ниже).

```bash
sudo mkdir -p /opt/maxbot
cd /opt/maxbot
```

Создайте `/opt/maxbot/.env`:

```bash
BOT_TOKEN=...                # токен от MasterBot
DOMAIN=bot.example.com       # ваш домен
WEBHOOK_PATH=/webhook
PORT=8080
MODE=webhook
ADMIN_IDS=111111,222222      # user_id админов через запятую
DATABASE_URL=postgresql+asyncpg://maxhub:${POSTGRES_PASSWORD}@postgres:5432/maxhub
TZ=Europe/Moscow
BROADCAST_ACTIVE_DAYS=30
POSTGRES_PASSWORD=...        # придумайте пароль для Postgres
IMAGE_TAG=latest
```

Скопируйте `docker/docker-compose.prod.yml` в `/opt/maxbot/docker-compose.yml` и `docker/Caddyfile` в `/opt/maxbot/Caddyfile`, затем:

```bash
docker compose pull
docker compose up -d
```

Caddy автоматически получит и будет продлевать сертификат Let's Encrypt для `DOMAIN`. Бот при старте сам подпишется на вебхук `https://{DOMAIN}{WEBHOOK_PATH}` и применит миграции БД (`alembic upgrade head` выполняется в entrypoint контейнера перед запуском приложения).

**Если на сервере уже занят порт 443 своим nginx** — используйте `docker/docker-compose.prod.nginx.yml` вместо Caddy, подробности в [`docker/nginx/README.md`](docker/nginx/README.md).

## GitHub Secrets (для CI/CD)

В настройках репозитория → Settings → Secrets and variables → Actions добавьте:

| Secret | Назначение |
|---|---|
| `SSH_HOST` | адрес сервера для деплоя |
| `SSH_USER` | пользователь для SSH |
| `SSH_KEY` | приватный SSH-ключ |
| `SSH_PORT` | (опционально) порт SSH, если не 22 |
| `DEPLOY_PATH` | (опционально) каталог с `.env`/`docker-compose.yml` на сервере, если не `/opt/maxbot` |

`GITHUB_TOKEN` для пуша образа в GHCR передаётся автоматически, ничего настраивать не нужно.

## Процесс релиза

Деплой запускается **только** пушем тега вида `v*`:

```bash
git tag v1.0.0
git push --tags
```

Workflow `deploy.yml` соберёт образ, запушит его в `ghcr.io/unseen-social-network/maxhub` с тегами `{tag}` и `latest`, затем по SSH обновит `IMAGE_TAG` в `/opt/maxbot/.env` на сервере и перезапустит стек (`docker compose pull && docker compose up -d`).

## Рассылка через `/broadcast`

1. Напишите боту в личку из аккаунта, указанного в `ADMIN_IDS`, команду `/broadcast`.
2. Пришлите текст рассылки одним сообщением.
3. Бот покажет превью текста и число активных получателей (писавших боту в личку за последние `BROADCAST_ACTIVE_DAYS` дней и не заблокировавших его), с кнопками «✅ Отправить» / «❌ Отменить».
4. После подтверждения рассылка уходит фоновой задачей строго через общий лимитер (не быстрее 2 сообщений в секунду на получателя, до 30 запросов в секунду суммарно) с промежуточным прогрессом каждые ~50 получателей.
5. По завершении бот пришлёт итог: сколько отправлено и сколько не доставлено. Пользователи, заблокировавшие бота, автоматически помечаются и исключаются из будущих рассылок.

Каждая рассылка логируется в таблицу `broadcasts` (админ, текст, время, счётчики отправленных/недоставленных).
