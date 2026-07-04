# Restructure MaxHub to Match Sibling Bot Convention

**Goal:** Align MaxHub's directory layout with the convention independently repeated in `culture-max-bot` and `banword-max-bot` (`src/<package>/` layout, `docker/` holding Dockerfile + local/prod compose, root `Makefile`, `migrations/` not `alembic/`, flat `tests/`), while keeping MaxHub's existing GitHub-only CI/CD and Caddy/HTTPS setup exactly as-is (per user decision — no Gitea/Harbor/Nexus/pre-commit-trio, those are infra this repo doesn't have).

**Scope note:** This is a mechanical restructuring of an already-complete, tested, pushed codebase — no behavior changes. Every step must preserve passing tests. This is not a TDD/new-feature plan; it's a path-mapping + import-rewrite + config-update exercise, verified by the existing test suite + docker build at the end.

## Path mapping

```
app/config.py                    → src/bot/config.py
app/main.py                      → src/bot/__main__.py
app/rate_limit.py                → src/bot/services/rate_limit.py
app/middlewares.py               → src/bot/middlewares/activity.py (ActivityMiddleware)
                                    + src/bot/middlewares/limiter.py (LimiterMiddleware)
                                    + src/bot/middlewares/__init__.py (empty)
app/db/engine.py                 → src/bot/db/session.py
app/db/models.py                 → src/bot/db/models.py
app/db/repo/*.py                 → src/bot/db/repositories/*.py
app/handlers/*.py                → src/bot/handlers/*.py (unchanged filenames)
app/services/broadcast.py        → src/bot/services/broadcast.py (unchanged)
app/services/converter.py        → src/bot/services/converter.py (unchanged)
app/services/word_of_day.py      → src/bot/services/word_of_day.py (unchanged)

alembic/                         → migrations/  (env.py, script.py.mako, versions/)
alembic.ini                      → stays at root, script_location updated

Dockerfile                       → docker/Dockerfile
docker-entrypoint.sh             → docker/docker-entrypoint.sh
docker-compose.yml               → docker/docker-compose.local.yml (+ bot service already added)
deploy/docker-compose.yml        → docker/docker-compose.prod.yml
deploy/Caddyfile                 → docker/Caddyfile
deploy/                          → removed (now empty)

tests/db/test_models.py                    → tests/test_db_models.py
tests/db/test_users_repo.py                → tests/test_db_users_repo.py
tests/db/test_todos_repo.py                → tests/test_db_todos_repo.py
tests/db/test_word_subscriptions_repo.py   → tests/test_db_word_subscriptions_repo.py
tests/db/test_broadcasts_repo.py           → tests/test_db_broadcasts_repo.py
tests/db/test_activity_middleware.py       → tests/test_middlewares_activity.py
tests/db/conftest.py                       → merged into tests/conftest.py (canonical, single)
tests/handlers/test_*.py                   → tests/test_handlers_*.py
tests/handlers/conftest.py                 → deleted (was just a re-export shim)
tests/services/test_*.py                   → tests/test_services_*.py
tests/services/conftest.py                 → deleted (was just a re-export shim)
tests/test_middlewares_limiter.py          → tests/test_middlewares_limiter.py (unchanged, already correctly named)
tests/test_main.py, tests/test_config.py, tests/test_rate_limit.py → tests/test_services_rate_limit.py
                                             (test_rate_limit.py renamed to test_services_rate_limit.py
                                              to match its new module location; test_main.py/test_config.py
                                              stay as-is since __main__.py/config.py are top-level bot/ modules)

data/words.json                  → unchanged (no sibling convention conflict)
```

## Import rewrite rules

- `from app.X import Y` → `from bot.X import Y` for all direct submodule matches EXCEPT the ones that moved to new locations below
- `from app.config import ...` → `from bot.config import ...`
- `from app.rate_limit import ...` → `from bot.services.rate_limit import ...`
- `from app.middlewares import ActivityMiddleware` → `from bot.middlewares.activity import ActivityMiddleware`
- `from app.middlewares import LimiterMiddleware` → `from bot.middlewares.limiter import LimiterMiddleware`
- `from app.db.engine import ...` → `from bot.db.session import ...`
- `from app.db.repo.X import ...` → `from bot.db.repositories.X import ...`
- `from app.db.models import ...` → `from bot.db.models import ...`
- `from app.handlers.X import ...` → `from bot.handlers.X import ...`
- `from app.services.X import ...` → `from bot.services.X import ...`
- `import app.main as main_module` (in tests/test_main.py) → `import bot.__main__ as main_module`
- `from app.main import ...` → `from bot.__main__ import ...`
- `app.main:app` style Docker/uvicorn references → n/a (not used; app is built via `create_app()` in Python, not a uvicorn CLI string)

## Config updates

- `pyproject.toml`: add `[build-system]` (hatchling), `[tool.hatch.build.targets.wheel] packages = ["src/bot"]`, `[project.scripts] bot = "bot.__main__:main"`; ruff `src = ["src", "tests"]`, isort `known-first-party = ["bot"]`, `extend-exclude = ["migrations/versions"]`; pytest `pythonpath = ["src"]`, `testpaths = ["tests"]`.
- `alembic.ini`: `script_location = migrations`, `prepend_sys_path = .` stays (repo root still on path via pytest/uv; migrations/env.py imports `bot.*` which needs `src` on sys.path too — add `src` to `prepend_sys_path` as `prepend_sys_path = src` per banword's exact convention, since alembic CLI is invoked directly, not through pytest's pythonpath).
- `migrations/env.py`: `from app.config import get_settings` → `from bot.config import get_settings`; `from app.db.models import Base` → `from bot.db.models import Base`.
- `docker/Dockerfile`: `COPY . /app` stays fine (whole repo context), but runtime `CMD`/entrypoint reference changes from `python -m app.main` → `python -m bot`; entrypoint script path `docker/docker-entrypoint.sh` copied in.
- `docker/docker-compose.local.yml` / `docker/docker-compose.prod.yml`: `build.context: ..`, `build.dockerfile: docker/Dockerfile` (paths become relative to the compose file's own directory once it lives in `docker/`).
- `docker/Caddyfile`: content unchanged, only referenced from the prod compose's volume mount path (`./Caddyfile` still resolves correctly since compose file and Caddyfile are now siblings in `docker/`).
- `.dockerignore`: no change needed (already excludes tests/docs/etc. by name, doesn't reference `app/` specifically).
- `.github/workflows/ci.yml` / `deploy.yml`: `docker/build-push-action` steps need explicit `context: .` (repo root) + `file: docker/Dockerfile` (previously relied on default root `Dockerfile`).
- `Makefile` (new): `help` (default target, auto-lists `## comment` targets), `install` (`uv sync`), `run` (`MODE=polling uv run python -m bot`), `lint` (`uv run ruff check .`), `format` (`uv run ruff format .`), `test` (`uv run pytest`), `migrate` (`uv run alembic upgrade head`), `migration m="..."` (`uv run alembic revision --autogenerate -m "$(m)"`), `up-local`/`down-local`/`logs-local` (docker compose on `docker/docker-compose.local.yml`), `up-prod`/`down-prod` (docker compose on `docker/docker-compose.prod.yml`, run from a deploy host where `.env` lives alongside).
- `CLAUDE.md`: update "Структура" tree and "Команды разработки" section to the new paths; leave Section 0, feature descriptions, and everything else untouched.
- `README.md`: update command snippets (`uv run python -m app.main` → `uv run python -m bot`, `docker compose up -d postgres` → `docker compose -f docker/docker-compose.local.yml up -d postgres`, etc.) and reference `make` targets where natural.

## Verification

1. `uv sync` succeeds with the new hatchling package config.
2. `uv run ruff check . && uv run ruff format --check .` clean.
3. `uv run pytest -v` — all tests pass (same count as before: 65).
4. `uv run alembic upgrade head` (renamed to `migrations/`) applies against dev Postgres cleanly (fresh migration history — no schema change, so this must be a no-op against an already-migrated DB, or a clean apply against a fresh one).
5. `docker compose -f docker/docker-compose.local.yml up --build` — same expected `InvalidToken`/missing-token boundary as before, confirming the container still self-migrates and boots.
6. `docker/build-push-action` config path change validated by re-running the existing local `docker build -f docker/Dockerfile .` manually (can't trigger real GH Actions from here).

## Commit plan

Given every piece must move together for anything to import correctly, this lands as a small number of logical commits made *after* the whole tree is moved and verified (git allows staging subsets of an already-consistent working tree into separate commits):

1. `refactor: перенести приложение в src/bot/ по конвенции сестринских проектов` — src/, tests/ flatten, pyproject.toml, all import rewrites
2. `refactor: переименовать alembic/ в migrations/`
3. `refactor: перенести Dockerfile и docker-compose в docker/`
4. `build: добавить Makefile для стандартных команд разработки`
5. `docs: обновить CLAUDE.md и README.md под новую структуру`
