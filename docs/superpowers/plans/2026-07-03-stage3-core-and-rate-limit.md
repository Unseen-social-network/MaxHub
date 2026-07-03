# Stage 3 — Bot Core and Rate Limiter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the single choke point for all outgoing MAX API calls (`app/rate_limit.py`) and the bot's entrypoint (`app/main.py`) wiring Bot + Dispatcher + `ActivityMiddleware`, supporting both `MODE=polling` (dev) and `MODE=webhook` (FastAPI + `/healthz`), with best-effort startup name/description sync.

**Architecture:** `maxapi`'s `Bot` has no single interceptable HTTP choke point reachable by subclassing (each high-level method like `send_message` delegates to its own `Method(BaseConnection)` object, not to `Bot.request`), so `RateLimitedBot` is a **wrapper/facade** holding a real `Bot` instance. All outgoing calls go through `RateLimitedBot.call(method_name, limit_key=..., **kwargs)`, which acquires a global `AsyncLimiter(30, 1)` and, when `limit_key` (a chat/user id) is given, a lazily-created per-key `AsyncLimiter(2, 1)` from a TTL-evicting registry, then invokes the real `Bot` method with retry-with-backoff-and-jitter on HTTP 429 (`MaxApiError.code == 429`) and network errors (`MaxConnection`). `app/main.py` builds `Bot`/`Dispatcher`, registers `ActivityMiddleware` from Stage 2, does a best-effort `bot.change_info(...)` sync at startup, and branches on `Settings.mode` between `dispatcher.start_polling(bot)` and a FastAPI app (`maxapi.webhook.fastapi.FastAPIMaxWebhook`) served by uvicorn, plus an explicit `bot.subscribe_webhook(...)` call and a `/healthz` route.

**Tech Stack:** `aiolimiter.AsyncLimiter`, `maxapi.Bot`/`Dispatcher`, `maxapi.exceptions.max.{MaxApiError,MaxConnection}`, `maxapi.webhook.fastapi.FastAPIMaxWebhook`, FastAPI + uvicorn, pytest + pytest-asyncio (fake bot objects, no real network/token needed).

## Global Constraints

- Global outgoing limit: 30 req/s; per-chat limit: 2 msg/s (CLAUDE.md "Ограничения MAX API")
- Lazy per-chat limiter dict with TTL-based cleanup (CLAUDE.md "Ограничения MAX API")
- Exponential backoff with jitter on 429 (CLAUDE.md "Ограничения MAX API")
- No handler may call MAX API methods bypassing this wrapper (CLAUDE.md "Ограничения MAX API")
- `bot.change_info()` is deprecated in maxapi/not in the official swagger spec — call it best-effort at startup wrapped in try/except, log a warning on failure, never crash the bot (decision recorded 2026-07-03, see project memory)
- `MODE=polling` for dev, `MODE=webhook` — FastAPI with webhook endpoint + `/healthz` (CLAUDE.md "Этап 3" / Стек)
- Async code everywhere (CLAUDE.md "Конвенции")
- Commit messages: Russian, Conventional Commits, no AI-authorship trailers (CLAUDE.md Section 0)

---

## File Structure

```
app/
├── rate_limit.py     # RateLimitedBot: global+per-chat AsyncLimiter, retry-with-backoff on 429/network errors
└── main.py            # build_bot(), build_dispatcher(), sync_bot_profile(), create_app() (webhook), run_polling(), main()
tests/
├── test_rate_limit.py
└── test_main.py
```

---

### Task 1: RateLimitedBot — global + per-chat rate limiting

**Files:**
- Create: `app/rate_limit.py`
- Test: `tests/test_rate_limit.py`

**Interfaces:**
- Consumes: `aiolimiter.AsyncLimiter`, `maxapi.exceptions.max.MaxApiError`, `maxapi.exceptions.max.MaxConnection`
- Produces: `RateLimitedBot(bot, *, global_rate=30, global_period=1.0, chat_rate=2, chat_period=1.0, chat_ttl=600.0, max_retries=5, base_delay=1.0, max_delay=30.0)` with `async def call(self, method_name: str, *, limit_key: int | None = None, **kwargs) -> Any` and `async def send_message(self, *, chat_id: int | None = None, user_id: int | None = None, **kwargs) -> Any`. Task 2 (`app/main.py`) constructs one `RateLimitedBot` per process and Stage 4/5 handlers call `.send_message(...)` on it exclusively — never the raw `Bot`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rate_limit.py
import time
from dataclasses import dataclass, field

import pytest

from app.rate_limit import RateLimitedBot
from maxapi.exceptions.max import MaxApiError, MaxConnection


@dataclass
class FakeBot:
    calls: list[tuple[str, dict]] = field(default_factory=list)
    fail_times: int = 0
    fail_with: Exception | None = None

    async def send_message(self, **kwargs):
        self.calls.append(("send_message", kwargs))
        return {"ok": True}

    async def noop(self, **kwargs):
        self.calls.append(("noop", kwargs))
        return "done"

    async def flaky(self, **kwargs):
        self.calls.append(("flaky", kwargs))
        if len(self.calls) <= self.fail_times:
            raise self.fail_with
        return "recovered"


async def test_send_message_to_same_chat_is_throttled_to_two_per_second():
    fake = FakeBot()
    limiter = RateLimitedBot(fake, chat_rate=2, chat_period=1.0)

    start = time.monotonic()
    for _ in range(5):
        await limiter.send_message(chat_id=100, text="hi")
    elapsed = time.monotonic() - start

    assert len(fake.calls) == 5
    assert elapsed >= 1.5  # 5 msgs at 2/s take ~2s; allow scheduling slack


async def test_global_limit_is_respected_across_different_chats():
    fake = FakeBot()
    limiter = RateLimitedBot(fake, global_rate=3, global_period=1.0, chat_rate=100)

    start = time.monotonic()
    for chat_id in range(6):
        await limiter.send_message(chat_id=chat_id, text="hi")
    elapsed = time.monotonic() - start

    assert len(fake.calls) == 6
    assert elapsed >= 1.0  # 6 calls at global 3/s take >=1s beyond the first burst


async def test_call_without_limit_key_only_uses_global_limiter():
    fake = FakeBot()
    limiter = RateLimitedBot(fake, global_rate=100, chat_rate=1, chat_period=1.0)

    start = time.monotonic()
    for _ in range(5):
        await limiter.call("noop", limit_key=None)
    elapsed = time.monotonic() - start

    assert len(fake.calls) == 5
    assert elapsed < 0.5  # no per-chat throttling applied when limit_key is None


async def test_retries_on_429_then_succeeds():
    fake = FakeBot(fail_times=2, fail_with=MaxApiError(code=429, raw={}))
    limiter = RateLimitedBot(fake, base_delay=0.01, max_delay=0.05)

    result = await limiter.call("flaky", limit_key=None)

    assert result == "recovered"
    assert len(fake.calls) == 3


async def test_retries_on_connection_error_then_succeeds():
    fake = FakeBot(fail_times=1, fail_with=MaxConnection("boom"))
    limiter = RateLimitedBot(fake, base_delay=0.01, max_delay=0.05)

    result = await limiter.call("flaky", limit_key=None)

    assert result == "recovered"
    assert len(fake.calls) == 2


async def test_gives_up_after_max_retries():
    fake = FakeBot(fail_times=10, fail_with=MaxApiError(code=429, raw={}))
    limiter = RateLimitedBot(fake, max_retries=2, base_delay=0.01, max_delay=0.05)

    with pytest.raises(MaxApiError):
        await limiter.call("flaky", limit_key=None)

    assert len(fake.calls) == 3  # initial attempt + 2 retries


async def test_non_retryable_error_propagates_immediately():
    fake = FakeBot(fail_times=10, fail_with=MaxApiError(code=400, raw={}))
    limiter = RateLimitedBot(fake, base_delay=0.01, max_delay=0.05)

    with pytest.raises(MaxApiError):
        await limiter.call("flaky", limit_key=None)

    assert len(fake.calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_rate_limit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.rate_limit'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/rate_limit.py
import asyncio
import random
import time
from typing import Any

from aiolimiter import AsyncLimiter
from maxapi.exceptions.max import MaxApiError, MaxConnection


class _ChatLimiterRegistry:
    def __init__(self, rate: float, period: float, ttl: float) -> None:
        self._rate = rate
        self._period = period
        self._ttl = ttl
        self._limiters: dict[int, AsyncLimiter] = {}
        self._last_used: dict[int, float] = {}

    def get(self, key: int) -> AsyncLimiter:
        self._evict_stale()
        self._last_used[key] = time.monotonic()
        if key not in self._limiters:
            self._limiters[key] = AsyncLimiter(self._rate, self._period)
        return self._limiters[key]

    def _evict_stale(self) -> None:
        now = time.monotonic()
        stale_keys = [
            key
            for key, last_used in self._last_used.items()
            if now - last_used > self._ttl
        ]
        for key in stale_keys:
            self._limiters.pop(key, None)
            self._last_used.pop(key, None)


class RateLimitedBot:
    def __init__(
        self,
        bot: Any,
        *,
        global_rate: float = 30,
        global_period: float = 1.0,
        chat_rate: float = 2,
        chat_period: float = 1.0,
        chat_ttl: float = 600.0,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self._bot = bot
        self._global_limiter = AsyncLimiter(global_rate, global_period)
        self._chat_limiters = _ChatLimiterRegistry(chat_rate, chat_period, chat_ttl)
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

    async def call(
        self, method_name: str, *, limit_key: int | None = None, **kwargs: Any
    ) -> Any:
        await self._global_limiter.acquire()
        if limit_key is not None:
            await self._chat_limiters.get(limit_key).acquire()

        method = getattr(self._bot, method_name)
        return await self._call_with_retry(method, **kwargs)

    async def send_message(
        self,
        *,
        chat_id: int | None = None,
        user_id: int | None = None,
        **kwargs: Any,
    ) -> Any:
        limit_key = chat_id if chat_id is not None else user_id
        return await self.call(
            "send_message", limit_key=limit_key, chat_id=chat_id, user_id=user_id, **kwargs
        )

    async def _call_with_retry(self, method: Any, **kwargs: Any) -> Any:
        attempt = 0
        while True:
            try:
                return await method(**kwargs)
            except MaxApiError as exc:
                if exc.code != 429 or attempt >= self._max_retries:
                    raise
            except MaxConnection:
                if attempt >= self._max_retries:
                    raise

            delay = min(self._base_delay * (2**attempt), self._max_delay)
            delay += random.uniform(0, delay * 0.1)
            await asyncio.sleep(delay)
            attempt += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rate_limit.py -v`
Expected: PASS (7 tests; the two timing tests take ~1.5-2s and ~1s respectively)

- [ ] **Step 5: Commit**

```bash
git add app/rate_limit.py tests/test_rate_limit.py
git commit -m "feat(bot): добавить RateLimitedBot с лимитером и ретраями"
```

---

### Task 2: Bot core wiring — `app/main.py`

**Files:**
- Create: `app/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `app.config.get_settings`, `app.db.engine.get_sessionmaker`, `app.middlewares.ActivityMiddleware`, `app.rate_limit.RateLimitedBot`, `maxapi.Bot`, `maxapi.Dispatcher`, `maxapi.webhook.fastapi.FastAPIMaxWebhook`
- Produces: `build_bot() -> Bot`, `build_dispatcher() -> Dispatcher` (registers `ActivityMiddleware`), `async def sync_bot_profile(bot: Bot) -> None`, `create_app() -> FastAPI` (webhook mode; exposes `/healthz`), `async def run_polling() -> None`, `def main() -> None`. Stage 4/5 routers get `include_routers(...)` into the `Dispatcher` returned by `build_dispatcher()` — this is the wiring point future stages extend.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
from fastapi.testclient import TestClient

from app.main import create_app


async def _noop_check_me(self) -> None:
    return None


def test_healthz_returns_ok(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("DOMAIN", "example.com")
    monkeypatch.setenv("WEBHOOK_PATH", "/webhook")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("MODE", "webhook")
    monkeypatch.setenv("ADMIN_IDS", "1")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://maxhub:maxhub@localhost:5432/maxhub"
    )

    from maxapi.dispatcher import Dispatcher

    monkeypatch.setattr(Dispatcher, "check_me", _noop_check_me)

    async def _noop_sync_profile(bot):
        return None

    async def _noop_subscribe_webhook(self, *args, **kwargs):
        return None

    import app.main as main_module

    monkeypatch.setattr(main_module, "sync_bot_profile", _noop_sync_profile)

    from maxapi.bot import Bot

    monkeypatch.setattr(Bot, "subscribe_webhook", _noop_subscribe_webhook)

    app = create_app()

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/main.py
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from maxapi import Bot, Dispatcher
from maxapi.webhook.fastapi import FastAPIMaxWebhook

from app.config import get_settings
from app.db.engine import get_sessionmaker
from app.middlewares import ActivityMiddleware

logger = logging.getLogger(__name__)

BOT_NAME = "MaxHub"
BOT_DESCRIPTION = (
    'Совместные списки дел, "Слово дня" и конвертер файлов — всё в одном '
    "боте. /help — список команд."
)


def build_bot() -> Bot:
    return Bot(token=get_settings().bot_token)


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.register_outer_middleware(ActivityMiddleware(get_sessionmaker()))
    return dispatcher


async def sync_bot_profile(bot: Bot) -> None:
    try:
        await bot.change_info(
            first_name=BOT_NAME,
            description=BOT_DESCRIPTION,
        )
    except Exception:
        logger.warning(
            "Не удалось синхронизировать имя/описание бота при старте",
            exc_info=True,
        )


def create_app() -> FastAPI:
    settings = get_settings()
    bot = build_bot()
    dispatcher = build_dispatcher()
    webhook = FastAPIMaxWebhook(dp=dispatcher, bot=bot)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with webhook.lifespan(app):
            await sync_bot_profile(bot)
            webhook_url = f"https://{settings.domain}{settings.webhook_path}"
            await bot.subscribe_webhook(url=webhook_url)
            yield

    app = FastAPI(lifespan=lifespan)
    webhook.setup(app, path=settings.webhook_path)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def run_polling() -> None:
    bot = build_bot()
    dispatcher = build_dispatcher()
    await sync_bot_profile(bot)
    await dispatcher.start_polling(bot)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()

    if settings.mode == "polling":
        asyncio.run(run_polling())
        return

    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
```

Note: `FastAPI(lifespan=...)` accepts only one lifespan context manager, and passing an explicit `lifespan=` means `@app.on_event("startup")` handlers **never fire** (verified empirically — Starlette skips its default lifespan, which is what wires up `on_event`, whenever a custom one is supplied). So `sync_bot_profile` and the webhook subscription must run inside a lifespan that wraps `webhook.lifespan(app)` via `async with`, not as a separate `on_event` hook.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_main.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat(bot): добавить app/main.py с Bot/Dispatcher, polling и webhook режимами"
```

---

### Task 3: Stage verification

- [ ] **Step 1: Full lint + test run**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -v`
Expected: all checks pass, all Stage 1+2+3 tests green (24 + 8 = 32 tests)

- [ ] **Step 2: Manual polling smoke check** (best-effort — a real `BOT_TOKEN` is required for `bot.get_me()` inside `dispatcher.start_polling`/`check_me()` to succeed against the live MAX API; without one this will fail at the network call, which is expected and not a code defect)

Run: `MODE=polling uv run python -m app.main`
Expected: either connects and starts polling (with a real token), or fails cleanly with an API/auth error from `maxapi` (not an import/wiring error) — confirms `app/main.py` constructs everything correctly up to the network boundary
