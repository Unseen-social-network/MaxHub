# Stage 5 — Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the two admin-only commands: `/v` (version info) and `/broadcast` (FSM-driven mass DM to active users, sent through the rate limiter as a background task with progress and a final report).

**Architecture:** A shared `IsAdmin` filter (checks `user_id in settings.admin_ids`) gates both commands — non-admins get no response at all. `/broadcast` uses maxapi's built-in FSM (`StatesGroup`/`State`, `StateFilter`, the per-(chat_id, user_id) `context: BaseContext` injected into handler `data` the same way `session`/`limiter` are — by parameter-name matching) across three handlers: start (`Command("broadcast")` → ask for text, set state), capture (`StateFilter(waiting_text)` → count active recipients, show preview + confirm/cancel buttons, set state), confirm/cancel (`message_callback` → clear state, log the broadcast row, spawn a background `asyncio.Task` that does the actual send). The send loop itself lives in `app/services/broadcast.py` — pure of any Dispatcher/handler concerns, unit-tested directly against real Postgres with a fake limiter that can be told to fail specific recipients.

**Tech Stack:** `maxapi.context.state_machine.{State,StatesGroup}`, `maxapi.filters.state.StateFilter`, `maxapi.context.context.MemoryContext` (used directly in tests — it's the Dispatcher's own default FSM storage), existing Stage 2 `UserRepo`/`BroadcastRepo`, Stage 3 `RateLimitedBot`.

## Global Constraints

- `/v` — admin-only, format `версия: {APP_VERSION}, sha: {GIT_SHA}, собрано: {BUILD_TIME}`; non-admins get no reply (CLAUDE.md "Этап 5")
- `/broadcast` — admin-only FSM: text → preview + active recipient count → «✅ Отправить»/«❌ Отменить» → background asyncio send through the limiter, progress every ~50 recipients, final report "отправлено X, не доставлено Y" (CLAUDE.md "Этап 5")
- Active recipient = `is_dm=true, is_blocked=false, last_activity_at` within `BROADCAST_ACTIVE_DAYS` (CLAUDE.md "Модели данных" / already implemented as `UserRepo.get_active_recipients`)
- Delivery failure → `is_blocked=true` on that user (CLAUDE.md "Этап 5")
- Every broadcast is logged to the `broadcasts` table (CLAUDE.md "Этап 5" — `BroadcastRepo` already exists from Stage 2)
- A test must cover active-user selection and blocked-user handling in the broadcast service (CLAUDE.md "Этап 5")
- No handler bypasses the rate-limit wrapper (CLAUDE.md "Ограничения MAX API", carried from Stage 3/4)
- Commit messages: Russian, Conventional Commits, no AI-authorship trailers (CLAUDE.md Section 0)

---

## File Structure

```
app/
├── handlers/
│   └── admin.py          # IsAdmin filter, /v, /broadcast (3 handlers: start/capture/confirm)
├── services/
│   └── broadcast.py       # run_broadcast() — the actual send loop, DB-facing, limiter-facing
└── main.py                 # + admin_router registration
tests/
├── handlers/
│   └── test_admin.py
└── services/
    └── test_broadcast.py
```

---

### Task 1: `/v` — admin-only version info

**Files:**
- Create: `app/handlers/admin.py`
- Test: `tests/handlers/test_admin.py`

**Interfaces:**
- Produces: `IsAdmin` (`BaseFilter`), `admin_router: Router` with a `Command("v")` handler gated by `IsAdmin()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/handlers/test_admin.py
from maxapi.enums.chat_type import ChatType
from maxapi.types.message import Message, Recipient
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser

from app.handlers.admin import handle_version


class FakeLimiter:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return None


def _make_event(chat_id: int, user_id: int) -> MessageCreated:
    message = Message(
        sender=MaxUser(
            user_id=user_id, first_name="T", is_bot=False, last_activity_time=0
        ),
        recipient=Recipient(user_id=user_id, chat_id=chat_id, chat_type=ChatType.DIALOG),
        timestamp=0,
    )
    return MessageCreated(message=message, timestamp=0)


async def test_version_replies_for_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1,2")
    from app.config import get_settings

    get_settings.cache_clear()
    limiter = FakeLimiter()

    await handle_version(_make_event(chat_id=100, user_id=1), limiter)

    assert limiter.sent
    assert "версия" in limiter.sent[0]["text"]
    get_settings.cache_clear()


async def test_version_silent_for_non_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1,2")
    from app.config import get_settings

    get_settings.cache_clear()
    limiter = FakeLimiter()

    await handle_version(_make_event(chat_id=100, user_id=999), limiter)

    assert limiter.sent == []
    get_settings.cache_clear()
```

Note: `handle_version` is called directly (bypassing the `IsAdmin()` filter that gates it in the real `Dispatcher`), so the non-admin test asserts the handler body itself is also defensive — in practice the filter would prevent the call entirely, but a direct-call test is cheap insurance and matches how Stage 4's handler tests are written.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/handlers/test_admin.py -v` → fails (`ModuleNotFoundError: No module named 'app.handlers.admin'`)

- [ ] **Step 3: Implement `app/handlers/admin.py`** (version-info part only for this task)

```python
# app/handlers/admin.py
from maxapi import Router
from maxapi.filters.command import Command
from maxapi.filters.filter import BaseFilter
from maxapi.types.updates.message_created import MessageCreated

from app.config import get_settings
from app.rate_limit import RateLimitedBot

admin_router = Router("admin")


class IsAdmin(BaseFilter):
    async def __call__(self, event: object) -> bool:
        get_ids = getattr(event, "get_ids", None)
        if not callable(get_ids):
            return False
        _chat_id, user_id = get_ids()
        return user_id is not None and user_id in get_settings().admin_ids


@admin_router.message_created(Command("v"), IsAdmin())
async def handle_version(event: MessageCreated, limiter: RateLimitedBot) -> None:
    chat_id, user_id = event.get_ids()
    if chat_id is None or user_id is None or user_id not in get_settings().admin_ids:
        return

    settings = get_settings()
    await limiter.send_message(
        chat_id=chat_id,
        text=(
            f"версия: {settings.app_version}, sha: {settings.git_sha}, "
            f"собрано: {settings.build_time}"
        ),
    )
```

Run: `uv run pytest tests/handlers/test_admin.py -v` → passes (2 tests).

- [ ] **Step 4: Commit**

```bash
git add app/handlers/admin.py tests/handlers/test_admin.py
git commit -m "feat(bot): добавить команду /v для админов"
```

---

### Task 2: Broadcast send service

**Files:**
- Create: `app/services/broadcast.py`
- Test: `tests/services/test_broadcast.py`

**Interfaces:**
- Consumes: `app.db.repo.users.UserRepo`, `app.db.repo.broadcasts.BroadcastRepo`, `app.db.engine.get_sessionmaker`, `app.config.get_settings`
- Produces: `async def run_broadcast(limiter: RateLimitedBot, *, admin_chat_id: int, broadcast_id: int, text: str, progress_every: int = 50) -> None`. Opens its own sessions (it runs detached from any request/handler session). Task 3's confirm handler calls this via `asyncio.create_task(...)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/services/test_broadcast.py
from app.db.models import Broadcast, User
from app.db.repo.users import UserRepo
from app.services.broadcast import run_broadcast


class FakeLimiter:
    def __init__(self, fail_user_ids: set[int] | None = None) -> None:
        self.sent: list[dict] = []
        self._fail_user_ids = fail_user_ids or set()

    async def send_message(self, *, user_id=None, chat_id=None, **kwargs):
        target = user_id if user_id is not None else chat_id
        if user_id in self._fail_user_ids:
            raise RuntimeError("delivery failed")
        self.sent.append({"user_id": user_id, "chat_id": chat_id, **kwargs})


async def test_run_broadcast_sends_only_to_active_recipients(session, monkeypatch):
    monkeypatch.setattr(
        "app.services.broadcast.get_sessionmaker", lambda: _session_factory(session)
    )
    repo = UserRepo(session)
    await repo.touch_activity(user_id=1, is_dm=True)  # active
    await repo.touch_activity(user_id=2, is_dm=False)  # never DM'd — excluded
    await session.commit()
    session.add(Broadcast(id=99, admin_id=1, text="hi"))
    await session.commit()

    limiter = FakeLimiter()
    await run_broadcast(limiter, admin_chat_id=1, broadcast_id=99, text="hi")

    sent_to = {c["user_id"] for c in limiter.sent}
    assert sent_to == {1}


async def test_run_broadcast_marks_failed_recipients_as_blocked(session, monkeypatch):
    monkeypatch.setattr(
        "app.services.broadcast.get_sessionmaker", lambda: _session_factory(session)
    )
    repo = UserRepo(session)
    await repo.touch_activity(user_id=1, is_dm=True)
    await repo.touch_activity(user_id=2, is_dm=True)
    await session.commit()
    session.add(Broadcast(id=100, admin_id=1, text="hi"))
    await session.commit()

    limiter = FakeLimiter(fail_user_ids={2})
    await run_broadcast(limiter, admin_chat_id=1, broadcast_id=100, text="hi")

    blocked_user = await session.get(User, 2)
    ok_user = await session.get(User, 1)
    assert blocked_user.is_blocked is True
    assert ok_user.is_blocked is False


async def test_run_broadcast_updates_broadcast_counts(session, monkeypatch):
    monkeypatch.setattr(
        "app.services.broadcast.get_sessionmaker", lambda: _session_factory(session)
    )
    repo = UserRepo(session)
    await repo.touch_activity(user_id=1, is_dm=True)
    await repo.touch_activity(user_id=2, is_dm=True)
    await session.commit()
    session.add(Broadcast(id=101, admin_id=1, text="hi"))
    await session.commit()

    limiter = FakeLimiter(fail_user_ids={2})
    await run_broadcast(limiter, admin_chat_id=1, broadcast_id=101, text="hi")

    broadcast = await session.get(Broadcast, 101)
    assert broadcast.sent_count == 1
    assert broadcast.failed_count == 1


def _session_factory(session):
    def factory():
        return _SingleSessionCtx(session)

    return factory


class _SingleSessionCtx:
    def __init__(self, session) -> None:
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False
```

Note: `run_broadcast` is written to call `get_sessionmaker()` freshly each time it needs a session (not once cached at import time), so tests can monkeypatch `app.services.broadcast.get_sessionmaker` to return a factory that always hands back the single shared, already-migrated `session` fixture — keeping the whole test in one transaction like every other DB test in this repo, without needing a second real connection pool.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/services/test_broadcast.py -v` → fails (`ModuleNotFoundError: No module named 'app.services.broadcast'`)

- [ ] **Step 3: Implement**

```python
# app/services/broadcast.py
import logging

from app.config import get_settings
from app.db.engine import get_sessionmaker
from app.db.repo.broadcasts import BroadcastRepo
from app.db.repo.users import UserRepo
from app.rate_limit import RateLimitedBot

logger = logging.getLogger(__name__)


async def run_broadcast(
    limiter: RateLimitedBot,
    *,
    admin_chat_id: int,
    broadcast_id: int,
    text: str,
    progress_every: int = 50,
) -> None:
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        recipients = await UserRepo(session).get_active_recipients(
            get_settings().broadcast_active_days
        )

    sent = 0
    failed = 0

    for i, user_id in enumerate(recipients, start=1):
        try:
            await limiter.send_message(user_id=user_id, text=text)
            sent += 1
        except Exception:
            failed += 1
            logger.warning("Не удалось доставить рассылку пользователю %s", user_id)
            async with sessionmaker() as session:
                await UserRepo(session).mark_blocked(user_id)
                await session.commit()

        if i % progress_every == 0:
            await limiter.send_message(
                chat_id=admin_chat_id, text=f"Прогресс рассылки: {i}/{len(recipients)}"
            )

    async with sessionmaker() as session:
        await BroadcastRepo(session).update_counts(
            broadcast_id, sent_count=sent, failed_count=failed
        )
        await session.commit()

    await limiter.send_message(
        chat_id=admin_chat_id,
        text=f"Рассылка завершена: отправлено {sent}, не доставлено {failed}",
    )
```

Run: `uv run pytest tests/services/test_broadcast.py -v` → passes (3 tests).

- [ ] **Step 4: Commit**

```bash
git add app/services/broadcast.py tests/services/test_broadcast.py
git commit -m "feat(bot): добавить сервис рассылки с учётом активных и заблокированных"
```

---

### Task 3: `/broadcast` FSM handlers

**Files:**
- Modify: `app/handlers/admin.py` (add `BroadcastStates`, three handlers)
- Modify: `tests/handlers/test_admin.py`
- Modify: `app/main.py` (register `admin_router`)

**Interfaces:**
- Produces: `BroadcastStates(StatesGroup)` with `waiting_text`, `confirming` states; handlers `handle_broadcast_start` (`Command("broadcast")` + `IsAdmin()`), `handle_broadcast_text` (`StateFilter(BroadcastStates.waiting_text)` + `IsAdmin()`), `handle_broadcast_decision` (`message_callback` + `IsAdmin()`, payloads `broadcast:confirm`/`broadcast:cancel`).

```python
# additions to app/handlers/admin.py
import asyncio

from maxapi.context.base import BaseContext
from maxapi.context.state_machine import State, StatesGroup
from maxapi.filters.state import StateFilter
from maxapi.types.attachments.buttons import CallbackButton
from maxapi.types.updates.message_callback import MessageCallback, MessageForCallback
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repo.broadcasts import BroadcastRepo
from app.db.repo.users import UserRepo
from app.services.broadcast import run_broadcast

_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


class BroadcastStates(StatesGroup):
    waiting_text = State()
    confirming = State()


@admin_router.message_created(Command("broadcast"), IsAdmin())
async def handle_broadcast_start(
    event: MessageCreated, context: BaseContext, limiter: RateLimitedBot
) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return
    await context.set_state(BroadcastStates.waiting_text)
    await limiter.send_message(chat_id=chat_id, text="Отправьте текст рассылки")


@admin_router.message_created(StateFilter(BroadcastStates.waiting_text), IsAdmin())
async def handle_broadcast_text(
    event: MessageCreated,
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    chat_id, _user_id = event.get_ids()
    text = event.message.body.text if event.message.body else None
    if chat_id is None or not text:
        return

    recipients = await UserRepo(session).get_active_recipients(
        get_settings().broadcast_active_days
    )
    await context.update_data(text=text)
    await context.set_state(BroadcastStates.confirming)

    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        CallbackButton(text="✅ Отправить", payload="broadcast:confirm"),
        CallbackButton(text="❌ Отменить", payload="broadcast:cancel"),
    )
    preview = f"Превью рассылки:\n\n{text}\n\nАктивных получателей: {len(recipients)}"
    await limiter.send_message(
        chat_id=chat_id, text=preview, attachments=[keyboard.as_markup()]
    )


@admin_router.message_callback(StateFilter(BroadcastStates.confirming), IsAdmin())
async def handle_broadcast_decision(
    event: MessageCallback,
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    chat_id, user_id = event.get_ids()
    if chat_id is None:
        return

    data = await context.get_data()
    text = data.get("text", "")
    await context.clear()

    if event.callback.payload == "broadcast:cancel":
        await limiter.call(
            "send_callback",
            limit_key=chat_id,
            callback_id=event.callback.callback_id,
            message=MessageForCallback(text="Рассылка отменена"),
        )
        return

    if event.callback.payload != "broadcast:confirm":
        return

    await limiter.call(
        "send_callback",
        limit_key=chat_id,
        callback_id=event.callback.callback_id,
        message=MessageForCallback(text="Рассылка запущена…"),
    )

    broadcast = await BroadcastRepo(session).create(admin_id=user_id or 0, text=text)
    await session.commit()

    _spawn_background(
        run_broadcast(
            limiter, admin_chat_id=chat_id, broadcast_id=broadcast.id, text=text
        )
    )
```

- [ ] **Step 1: Write the failing tests**

```python
# additions to tests/handlers/test_admin.py
from maxapi.context.context import MemoryContext

from app.db.repo.broadcasts import BroadcastRepo
from app.db.repo.users import UserRepo
from app.handlers.admin import (
    BroadcastStates,
    handle_broadcast_decision,
    handle_broadcast_start,
    handle_broadcast_text,
)


def _make_callback_event(chat_id: int, payload: str, user_id: int) -> MessageCallback:
    from maxapi.types.callback import Callback

    message = Message(
        sender=MaxUser(
            user_id=user_id, first_name="T", is_bot=False, last_activity_time=0
        ),
        recipient=Recipient(user_id=user_id, chat_id=chat_id, chat_type=ChatType.DIALOG),
        timestamp=0,
    )
    callback = Callback(
        timestamp=0,
        callback_id="cb1",
        payload=payload,
        user=MaxUser(
            user_id=user_id, first_name="T", is_bot=False, last_activity_time=0
        ),
    )
    return MessageCallback(message=message, callback=callback, timestamp=0)


async def test_broadcast_start_sets_state_and_prompts(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1")
    from app.config import get_settings

    get_settings.cache_clear()
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=1, user_id=1)

    await handle_broadcast_start(_make_event(chat_id=1, user_id=1), context, limiter)

    assert await context.get_state() == BroadcastStates.waiting_text
    assert "текст" in limiter.sent[0]["text"].lower()
    get_settings.cache_clear()


async def test_broadcast_text_shows_preview_and_count(session, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1")
    from app.config import get_settings

    get_settings.cache_clear()
    await UserRepo(session).touch_activity(user_id=5, is_dm=True)
    await session.commit()

    limiter = FakeLimiter()
    context = MemoryContext(chat_id=1, user_id=1)
    event = _make_event(chat_id=1, user_id=1)
    event.message.body = event.message.body  # placeholder, replaced below

    from maxapi.types.message import MessageBody

    event.message.body = MessageBody(mid="m1", seq=1, text="важное объявление")

    await handle_broadcast_text(event, session, context, limiter)

    assert await context.get_state() == BroadcastStates.confirming
    assert "важное объявление" in limiter.sent[0]["text"]
    assert "1" in limiter.sent[0]["text"]
    get_settings.cache_clear()


async def test_broadcast_decision_cancel_clears_state(session, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1")
    from app.config import get_settings

    get_settings.cache_clear()
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=1, user_id=1)
    await context.set_state(BroadcastStates.confirming)
    await context.update_data(text="hi")

    event = _make_callback_event(1, "broadcast:cancel", user_id=1)
    await handle_broadcast_decision(event, session, context, limiter)

    assert await context.get_state() is None
    assert limiter.calls[0]["method"] == "send_callback"
    get_settings.cache_clear()


async def test_broadcast_decision_confirm_logs_broadcast_row(session, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1")
    from app.config import get_settings

    get_settings.cache_clear()
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=1, user_id=1)
    await context.set_state(BroadcastStates.confirming)
    await context.update_data(text="важное объявление")

    event = _make_callback_event(1, "broadcast:confirm", user_id=1)
    await handle_broadcast_decision(event, session, context, limiter)
    await session.commit()

    assert await context.get_state() is None
    broadcasts = (await session.execute(__import__("sqlalchemy").select(BroadcastRepo))).all if False else None
    get_settings.cache_clear()
```

(The last test's row-count assertion is simplified in the real implementation step below — verify via a direct `select(Broadcast)` query rather than the placeholder shown here, which exists only to mark where the assertion belongs; replace before running.)

- [ ] **Step 2: Run to verify failure, then implement the additions to `app/handlers/admin.py` shown above, then re-run**

Run: `uv run pytest tests/handlers/test_admin.py -v` → fails, then passes after implementation (6 tests total with Task 1's two).

Fix the placeholder assertion in `test_broadcast_decision_confirm_logs_broadcast_row` to:

```python
from sqlalchemy import select

from app.db.models import Broadcast


async def test_broadcast_decision_confirm_logs_broadcast_row(session, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1")
    from app.config import get_settings

    get_settings.cache_clear()
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=1, user_id=1)
    await context.set_state(BroadcastStates.confirming)
    await context.update_data(text="важное объявление")

    event = _make_callback_event(1, "broadcast:confirm", user_id=1)
    await handle_broadcast_decision(event, session, context, limiter)

    assert await context.get_state() is None
    result = await session.execute(select(Broadcast).where(Broadcast.admin_id == 1))
    broadcasts = result.scalars().all()
    assert len(broadcasts) == 1
    assert broadcasts[0].text == "важное объявление"
    get_settings.cache_clear()
```

Note: this test spawns a real background `asyncio.Task` (`run_broadcast`) that will try to open its own DB session via `get_sessionmaker()` — harmless in the test process (it'll just find zero active recipients matching `BROADCAST_ACTIVE_DAYS` from whatever `.env` is loaded, complete quickly, and its final report call goes to the `FakeLimiter`, which is a plain Python object, not awaited by the test — acceptable fire-and-forget for this one test since it doesn't assert on send_message side effects of the background task itself, only on the synchronous `broadcasts` row creation that happens before the task is spawned).

- [ ] **Step 3: Wire `admin_router` into `app/main.py`**

```python
from app.handlers.admin import admin_router
...
    dispatcher.include_routers(
        common_router, todo_router, word_of_day_router, converter_router, admin_router
    )
```

Run: `uv run pytest tests/test_main.py -v` → still passes.

- [ ] **Step 4: Commit**

```bash
git add app/handlers/admin.py tests/handlers/test_admin.py app/main.py
git commit -m "feat(bot): добавить FSM-сценарий /broadcast"
```

---

### Task 4: Stage verification

- [ ] **Step 1: Full lint + test run**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -v`
Expected: all checks pass, all tests green
