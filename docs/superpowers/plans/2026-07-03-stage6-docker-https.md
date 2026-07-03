# Stage 6 — Docker and HTTPS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package MaxHub into a production Docker image and a deployable prod stack (bot + Postgres + Caddy) that terminates HTTPS automatically via Let's Encrypt.

**Architecture:** A multi-stage `Dockerfile` builds the app with `uv` in a builder stage, then copies the resulting `.venv` into a slim non-root runtime stage. Build-args (`APP_VERSION`, `GIT_SHA`, `BUILD_TIME`) become env vars baked into the image, matching `app/config.py`'s `Settings` fields already wired since Stage 1. A `docker-entrypoint.sh` runs `alembic upgrade head` before starting the app, so every deploy self-migrates. `deploy/docker-compose.yml` is the production stack: `postgres:16` (healthchecked, `bot` waits on it), `bot` (pulled from GHCR by tag), `caddy` (80/443, auto-HTTPS via `deploy/Caddyfile`, reverse-proxying to `bot`). No application code changes — `app/main.py` already subscribes the webhook and exposes `/healthz` (Stage 3).

**Tech Stack:** Docker multi-stage build, `ghcr.io/astral-sh/uv` base images, Docker Compose, Caddy (automatic HTTPS).

## Global Constraints

- Multi-stage Dockerfile on `ghcr.io/astral-sh/uv` images; build-args `APP_VERSION`/`GIT_SHA`/`BUILD_TIME` → env; non-root; entrypoint `alembic upgrade head` → start app; healthcheck on `/healthz` (CLAUDE.md "Этап 6")
- Prod `deploy/docker-compose.yml`: `bot` (`ghcr.io/<owner>/<repo>:${IMAGE_TAG}`, env from `.env`), `postgres:16` (volume, healthcheck; bot starts after healthy), `caddy` (80/443, cert volume) (CLAUDE.md "Этап 6")
- `deploy/Caddyfile`: `{$DOMAIN}` → `reverse_proxy bot`, Caddy auto-obtains/renews Let's Encrypt certs (CLAUDE.md "Этап 6")
- App version = git tag, injected via build-args → env (CLAUDE.md "Версионирование и деплой")
- Alembic migrations run automatically at container start, before the app (CLAUDE.md "Версионирование и деплой")
- Webhook subscription to `https://{DOMAIN}{WEBHOOK_PATH}` already happens in `app/main.py`'s lifespan (Stage 3) — no code change needed this stage
- Commit messages: Russian, Conventional Commits, no AI-authorship trailers (CLAUDE.md Section 0)

---

## File Structure

```
Dockerfile
docker-entrypoint.sh
.dockerignore
deploy/
├── docker-compose.yml
└── Caddyfile
```

---

### Task 1: Multi-stage Dockerfile + entrypoint

**Files:**
- Create: `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`

**Interfaces:**
- Produces: an image exposing port 8080, running as a non-root `app` user, with `APP_VERSION`/`GIT_SHA`/`BUILD_TIME` baked in as env vars from build-args (defaults `dev`/`unknown`/`unknown` matching `app/config.py`'s `Settings` defaults), entrypoint `docker-entrypoint.sh` (runs `alembic upgrade head` then `exec python -m app.main`), `HEALTHCHECK` hitting `/healthz`. Stage 7's CI workflow builds this image; Stage 6 Task 2's compose file runs it.

- [ ] **Step 1: `.dockerignore`**

```
.venv
.git
.github
.pytest_cache
.ruff_cache
__pycache__
*.pyc
.env
data/.gitkeep
docs
tests
alembic/versions/__pycache__
```

- [ ] **Step 2: `docker-entrypoint.sh`**

```sh
#!/bin/sh
set -e

alembic upgrade head
exec python -m app.main
```

- [ ] **Step 3: `Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

ARG APP_VERSION=dev
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown

ENV APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    BUILD_TIME=${BUILD_TIME} \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    MODE=webhook \
    PORT=8080

RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /app app

WORKDIR /app

COPY --from=builder --chown=app:app /app /app
COPY --chown=app:app docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
```

- [ ] **Step 4: Verify it builds**

Run: `docker build -t maxhub:local --build-arg APP_VERSION=test --build-arg GIT_SHA=abc123 --build-arg BUILD_TIME=2026-07-03T00:00:00Z .`
Expected: builds successfully (multi-stage, both stages complete, final image tagged `maxhub:local`)

- [ ] **Step 5: Verify the image runs and self-migrates against real Postgres**

Run (with `docker compose up -d postgres` from the dev compose already up):
```bash
docker run --rm \
  --network maxhub_default \
  -e BOT_TOKEN=fake-token \
  -e DOMAIN=example.com \
  -e WEBHOOK_PATH=/webhook \
  -e PORT=8080 \
  -e MODE=polling \
  -e ADMIN_IDS=1 \
  -e DATABASE_URL=postgresql+asyncpg://maxhub:maxhub@postgres:5432/maxhub \
  maxhub:local
```
Expected: logs show `alembic upgrade head` applying (or already at head), then the app starts and fails cleanly at `InvalidToken` when it hits the real MAX API with `MODE=polling` — same clean failure boundary already proven in Stage 3's manual smoke test, confirming the containerized app boots correctly end-to-end (deps, migrations, entrypoint, non-root permissions) up to the network call.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-entrypoint.sh .dockerignore
git commit -m "feat(docker): добавить multi-stage Dockerfile"
```

---

### Task 2: Production docker-compose

**Files:**
- Create: `deploy/docker-compose.yml`

**Interfaces:**
- Produces: `bot`, `postgres`, `caddy` services. `bot` image is `ghcr.io/unseen-social-network/maxhub:${IMAGE_TAG}` (matches the real `origin` remote `git@github.com:Unseen-social-network/MaxHub.git`, lowercased per GHCR naming rules), reads env from `.env` on the server, depends on `postgres` being healthy. Stage 7's `deploy.yml` workflow sets `IMAGE_TAG` on the server and runs `docker compose pull && docker compose up -d` against this file.

- [ ] **Step 1: Write `deploy/docker-compose.yml`**

```yaml
services:
  bot:
    image: ghcr.io/unseen-social-network/maxhub:${IMAGE_TAG}
    restart: unless-stopped
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - internal

  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_USER: maxhub
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: maxhub
    volumes:
      - maxhub_pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U maxhub"]
      interval: 5s
      timeout: 5s
      retries: 10
    networks:
      - internal

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    environment:
      DOMAIN: ${DOMAIN}
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - maxhub_caddy_data:/data
      - maxhub_caddy_config:/config
    depends_on:
      - bot
    networks:
      - internal

networks:
  internal:

volumes:
  maxhub_pg_data:
  maxhub_caddy_data:
  maxhub_caddy_config:
```

Note: `bot`'s `DATABASE_URL` in the server's `.env` must point at `postgres` (the compose service name), e.g. `postgresql+asyncpg://maxhub:${POSTGRES_PASSWORD}@postgres:5432/maxhub` — documented in Stage 8's README, not hardcoded here since it depends on `POSTGRES_PASSWORD` which is a secret.

- [ ] **Step 2: Validate the compose file parses**

Run: `cd deploy && DOMAIN=example.com IMAGE_TAG=latest POSTGRES_PASSWORD=x docker compose config --quiet && echo OK`
Expected: `OK`, no YAML/schema errors

- [ ] **Step 3: Commit**

```bash
git add deploy/docker-compose.yml
git commit -m "feat(docker): добавить прод docker-compose (bot, postgres, caddy)"
```

---

### Task 3: Caddyfile

**Files:**
- Create: `deploy/Caddyfile`

**Interfaces:**
- Produces: a Caddy config reverse-proxying `{$DOMAIN}` to `bot:8080`, with Caddy handling ACME/Let's Encrypt automatically (default Caddy behavior — no explicit `tls` directive needed for the common case).

- [ ] **Step 1: Write `deploy/Caddyfile`**

```
{$DOMAIN} {
	reverse_proxy bot:8080
}
```

- [ ] **Step 2: Validate syntax**

Run: `docker run --rm -v "$(pwd)/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`
Expected: `Valid configuration`

- [ ] **Step 3: Commit**

```bash
git add deploy/Caddyfile
git commit -m "feat(docker): добавить Caddyfile для автоматического HTTPS"
```

---

### Task 4: Stage verification

- [ ] **Step 1: Full compose stack config check**

Run: `cd deploy && DOMAIN=example.com IMAGE_TAG=local POSTGRES_PASSWORD=x docker compose config`
Expected: fully resolved compose config prints without error, all three services present, `bot` depends on `postgres` with `condition: service_healthy`

- [ ] **Step 2: Confirm dev workflow still passes** (unrelated to Docker, but always re-verify per CLAUDE.md's "после каждого этапа проверяй")

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -v`
Expected: all green (no Python files changed this stage, but confirms nothing else regressed)

- [ ] **Step 3: Clean up local test image**

Run: `docker rmi maxhub:local`
