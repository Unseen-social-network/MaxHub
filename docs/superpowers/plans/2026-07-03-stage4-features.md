# Stage 4 — Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the four user-facing features from CLAUDE.md "Функции" 1-3 plus `/start`/`/help`: shared per-chat todo list, daily "Слово дня" broadcast, image-format converter, and command help.

**Architecture:** Handlers live under `app/handlers/`, one `maxapi.Router` per feature, included into the `Dispatcher` built in `app/main.py`. Every handler receives `session: AsyncSession` (from Stage 2's `ActivityMiddleware`) and `limiter: RateLimitedBot` (from a new `LimiterMiddleware`, Task 1 of this stage) purely by parameter-name matching — maxapi's `call_handler` filters the middleware `data` dict down to whatever parameter names a handler declares. **No handler ever calls a raw `Bot`/event shortcut method** (`event.reply()`, `.send()`, `.answer()`, `.edit()`, `bot.send_message()`, etc.) — those all bypass `RateLimitedBot` internally (verified by reading `maxapi`'s `PeerShortcutMixin`/`MessageCallback.edit()` source: they call `self._ensure_bot().send_message(...)`/`bot.send_callback(...)` directly). Every outgoing call goes through `limiter.send_message(...)` or `limiter.call(method_name, ...)`. Business logic (word picking, image conversion) is pure and framework-free in `app/services/`, unit-tested without any bot/DB fakes.

**Tech Stack:** `maxapi.Router`/`Command` filter/`InlineKeyboardBuilder`/`CallbackButton`, `Pillow` (`asyncio.to_thread`), `APScheduler` `AsyncIOScheduler` with a cron trigger, existing Stage 2 repos (`TodoRepo`, `WordSubscriptionRepo`) and Stage 3 `RateLimitedBot`.

## Global Constraints

- No handler calls MAX API methods bypassing the rate-limit wrapper (CLAUDE.md "Ограничения MAX API")
- `/todo add|list|done|del`, numbered output with done/del inline buttons (CLAUDE.md "Этап 4"/"Функции")
- `/word`, `/word sub`, `/word unsub`; daily 09:00 (TZ from env) broadcast through the limiter; `data/words.json` with 30 words (CLAUDE.md "Этап 4")
- Image converter: inline format buttons (png/jpg/webp/pdf), Pillow via `asyncio.to_thread`, 20 MB input limit, clear errors (CLAUDE.md "Этап 4")
- `/start`, `/help` describing all features (CLAUDE.md "Этап 4")
- Blocking operations (Pillow) go through `asyncio.to_thread` (CLAUDE.md "Конвенции")
- Bot messages in Russian (CLAUDE.md "Конвенции")
- Async everywhere; thin handlers, logic in `services/`/`db/repo/` (CLAUDE.md "Конвенции")
- Commit messages: Russian, Conventional Commits, no AI-authorship trailers (CLAUDE.md Section 0)

---

## File Structure

```
app/
├── middlewares.py          # + LimiterMiddleware (injects `limiter: RateLimitedBot`)
├── main.py                  # + RateLimitedBot construction, router registration, APScheduler wiring
├── handlers/
│   ├── common.py             # /start, /help
│   ├── todo.py                # /todo add|list|done|del + callback buttons
│   ├── word_of_day.py          # /word, /word sub, /word unsub
│   └── converter.py            # image → format buttons → converted file
└── services/
    ├── word_of_day.py           # load_words(), pick_word_for_date(), format_word_message(), broadcast_daily_word()
    └── converter.py              # convert_image() — pure Pillow logic
data/words.json              # 30 words: {"word", "definition", "example"}
tests/
├── test_middlewares_limiter.py
├── services/
│   ├── test_word_of_day.py
│   └── test_converter.py
└── handlers/
    ├── test_todo.py
    ├── test_word_of_day.py
    └── test_converter.py
```

---

### Task 1: LimiterMiddleware — inject `RateLimitedBot` into handler data

**Files:**
- Modify: `app/middlewares.py`
- Modify: `app/main.py` (`build_dispatcher` now takes `bot`, constructs and registers `LimiterMiddleware`)
- Modify: `tests/test_main.py` (update for new `build_dispatcher(bot)` signature)
- Test: `tests/test_middlewares_limiter.py`

**Interfaces:**
- Produces: `LimiterMiddleware(limiter: RateLimitedBot)`, a `BaseMiddleware` that sets `data["limiter"] = limiter`. `build_dispatcher(bot: Bot) -> Dispatcher` now registers both `ActivityMiddleware` and `LimiterMiddleware(RateLimitedBot(bot))`. Every handler in Tasks 2-5 declares a `limiter: RateLimitedBot` parameter to receive it.

- [ ] **Step 1: Write and run the failing test, then implement**

```python
# tests/test_middlewares_limiter.py
from app.middlewares import LimiterMiddleware
from app.rate_limit import RateLimitedBot


async def test_injects_limiter_into_handler_data():
    limiter = RateLimitedBot(bot=object())
    middleware = LimiterMiddleware(limiter)
    seen = {}

    async def handler(event_object, data):
        seen["limiter"] = data.get("limiter")
        return "ok"

    result = await middleware(handler, event_object=None, data={})

    assert result == "ok"
    assert seen["limiter"] is limiter
```

Run: `uv run pytest tests/test_middlewares_limiter.py -v` → fails (`ImportError: cannot import name 'LimiterMiddleware'`).

Add to `app/middlewares.py`:

```python
from app.rate_limit import RateLimitedBot


class LimiterMiddleware(BaseMiddleware):
    def __init__(self, limiter: RateLimitedBot) -> None:
        self._limiter = limiter

    async def __call__(
        self,
        handler: HandlerCallable,
        event_object: UpdateUnion,
        data: dict[str, Any],
    ) -> Any:
        data["limiter"] = self._limiter
        return await handler(event_object, data)
```

Run again → passes.

- [ ] **Step 2: Update `app/main.py` and its test**

In `app/main.py`, change:

```python
def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.register_outer_middleware(ActivityMiddleware(get_sessionmaker()))
    return dispatcher
```

to:

```python
def build_dispatcher(bot: Bot) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.register_outer_middleware(ActivityMiddleware(get_sessionmaker()))
    dispatcher.register_outer_middleware(LimiterMiddleware(RateLimitedBot(bot)))
    dispatcher.include_routers(
        common_router, todo_router, word_of_day_router, converter_router
    )
    return dispatcher
```

(the four router imports/names are filled in as Tasks 2-5 create them — this task only needs the two `register_outer_middleware` lines and the changed signature; add router includes incrementally in later tasks). Update both call sites (`create_app`, `run_polling`) from `build_dispatcher()` to `build_dispatcher(bot)`. Update `tests/test_main.py`'s monkeypatching if needed (it doesn't reference `build_dispatcher` directly, so no change should be required — rerun it to confirm).

Run: `uv run pytest tests/test_main.py tests/test_middlewares_limiter.py -v` → all pass.

- [ ] **Step 3: Commit**

```bash
git add app/middlewares.py app/main.py tests/test_middlewares_limiter.py tests/test_main.py
git commit -m "feat(bot): добавить LimiterMiddleware и прокинуть RateLimitedBot в хендлеры"
```

---

### Task 2: `/start`, `/help`

**Files:**
- Create: `app/handlers/common.py`
- Test: `tests/handlers/test_common.py`

**Interfaces:**
- Produces: `common_router: Router` with `/start` and `/help` handlers. Both call `limiter.send_message(chat_id=..., text=...)`.

Handlers are tested by calling the registered function directly with a fake `limiter` (a stub object recording calls) — no real Dispatcher/network needed, matching the pattern already proven for `ActivityMiddleware`.

```python
# app/handlers/common.py
from maxapi import Router
from maxapi.filters.command import Command, CommandStart

from app.rate_limit import RateLimitedBot
from app.types import MessageCreated  # see note below

common_router = Router("common")

HELP_TEXT = (
    "Я — MaxHub, бот «всё в одном» для этого чата.\n\n"
    "📝 Совместные списки дел:\n"
    "/todo add <текст> — добавить дело\n"
    "/todo list — показать список\n"
    "/todo done <n> — отметить выполненным\n"
    "/todo del <n> — удалить\n\n"
    "📖 Слово дня:\n"
    "/word — показать слово дня\n"
    "/word sub — подписать чат на ежедневную рассылку\n"
    "/word unsub — отписаться\n\n"
    "🖼 Конвертер изображений:\n"
    "Пришлите картинку — бот предложит форматы для конвертации.\n\n"
    "/help — это сообщение"
)


@common_router.message_created(CommandStart())
async def handle_start(event: MessageCreated, limiter: RateLimitedBot) -> None:
    chat_id, _user_id = event.get_ids()
    await limiter.send_message(chat_id=chat_id, text=HELP_TEXT)


@common_router.message_created(Command("help"))
async def handle_help(event: MessageCreated, limiter: RateLimitedBot) -> None:
    chat_id, _user_id = event.get_ids()
    await limiter.send_message(chat_id=chat_id, text=HELP_TEXT)
```

Note: import `MessageCreated` from `maxapi.types.updates.message_created` (confirmed path from Stage 2's `ActivityMiddleware` test) — there is no `app.types` module; use the real import path:

```python
from maxapi.types.updates.message_created import MessageCreated
```

- [ ] **Step 1: Write the failing test**

```python
# tests/handlers/test_common.py
from maxapi.enums.chat_type import ChatType
from maxapi.types.message import Message, Recipient
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser

from app.handlers.common import HELP_TEXT, handle_help, handle_start


class FakeLimiter:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return None


def _make_event(chat_id: int = 100) -> MessageCreated:
    message = Message(
        sender=MaxUser(
            user_id=1, first_name="Test", is_bot=False, last_activity_time=0
        ),
        recipient=Recipient(user_id=1, chat_id=chat_id, chat_type=ChatType.DIALOG),
        timestamp=0,
    )
    return MessageCreated(message=message, timestamp=0)


async def test_start_sends_help_text():
    limiter = FakeLimiter()

    await handle_start(_make_event(chat_id=100), limiter)

    assert limiter.sent == [{"chat_id": 100, "text": HELP_TEXT}]


async def test_help_sends_help_text():
    limiter = FakeLimiter()

    await handle_help(_make_event(chat_id=200), limiter)

    assert limiter.sent == [{"chat_id": 200, "text": HELP_TEXT}]
```

Run: `uv run pytest tests/handlers/test_common.py -v` → fails (`ModuleNotFoundError: No module named 'app.handlers.common'`).

- [ ] **Step 2: Implement `app/handlers/common.py`** (code above) and re-run → passes.

- [ ] **Step 3: Commit**

```bash
git add app/handlers/common.py tests/handlers/__init__.py tests/handlers/test_common.py
git commit -m "feat(bot): добавить команды /start и /help"
```

---

### Task 3: `/todo` — add, list, done, del + inline buttons

**Files:**
- Create: `app/handlers/todo.py`
- Test: `tests/handlers/test_todo.py`

**Interfaces:**
- Consumes: `app.db.repo.todos.TodoRepo` (Stage 2)
- Produces: `todo_router: Router` with one `Command("todo")` text handler that dispatches on `args[0]` (`add|list|done|del`), and one `message_callback` handler matching payloads `todo:done:<id>`/`todo:del:<id>`. A shared `_render_todo_list(chat_id, session) -> tuple[str, AttachmentButton]` builds the numbered text + inline keyboard used by both `/todo list` and after any done/del action (text command or button).

```python
# app/handlers/todo.py
from maxapi import Router
from maxapi.filters.command import Command
from maxapi.types.attachments.buttons import CallbackButton
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repo.todos import TodoRepo
from app.rate_limit import RateLimitedBot

todo_router = Router("todo")


async def _render_todo_list(
    chat_id: int, session: AsyncSession
) -> tuple[str, AttachmentButton | None]:
    todos = await TodoRepo(session).list_for_chat(chat_id)

    if not todos:
        return "Список дел пуст. Добавьте: /todo add <текст>", None

    lines = []
    keyboard = InlineKeyboardBuilder()
    for i, todo in enumerate(todos, start=1):
        mark = "✅" if todo.is_done else "⬜"
        lines.append(f"{i}. {mark} {todo.text}")
        keyboard.row(
            CallbackButton(text=f"✅ {i}", payload=f"todo:done:{todo.id}"),
            CallbackButton(text=f"🗑 {i}", payload=f"todo:del:{todo.id}"),
        )

    return "\n".join(lines), keyboard.as_markup()


@todo_router.message_created(Command("todo"))
async def handle_todo(
    event: MessageCreated,
    args: list[str],
    session: AsyncSession,
    limiter: RateLimitedBot,
) -> None:
    chat_id, user_id = event.get_ids()
    if chat_id is None:
        return

    if not args:
        await limiter.send_message(
            chat_id=chat_id, text="Использование: /todo add|list|done|del"
        )
        return

    subcommand, rest = args[0].lower(), args[1:]

    if subcommand == "add":
        text = " ".join(rest).strip()
        if not text:
            await limiter.send_message(
                chat_id=chat_id, text="Укажите текст: /todo add <текст>"
            )
            return
        await TodoRepo(session).add(chat_id, text, created_by=user_id or 0)
        await session.commit()
        await limiter.send_message(chat_id=chat_id, text=f"Добавлено: {text}")
        return

    if subcommand == "list":
        text, keyboard = await _render_todo_list(chat_id, session)
        attachments = [keyboard] if keyboard else None
        await limiter.send_message(chat_id=chat_id, text=text, attachments=attachments)
        return

    if subcommand in {"done", "del"}:
        if not rest or not rest[0].isdigit():
            await limiter.send_message(
                chat_id=chat_id, text=f"Использование: /todo {subcommand} <n>"
            )
            return

        position = int(rest[0])
        todos = await TodoRepo(session).list_for_chat(chat_id)
        if position < 1 or position > len(todos):
            await limiter.send_message(chat_id=chat_id, text="Нет такого номера")
            return

        todo_id = todos[position - 1].id
        if subcommand == "done":
            await TodoRepo(session).mark_done(chat_id, todo_id)
        else:
            await TodoRepo(session).delete(chat_id, todo_id)
        await session.commit()

        text, keyboard = await _render_todo_list(chat_id, session)
        attachments = [keyboard] if keyboard else None
        await limiter.send_message(chat_id=chat_id, text=text, attachments=attachments)
        return

    await limiter.send_message(
        chat_id=chat_id, text="Неизвестная команда: /todo add|list|done|del"
    )


@todo_router.message_callback()
async def handle_todo_callback(
    event: MessageCallback,
    session: AsyncSession,
    limiter: RateLimitedBot,
) -> None:
    payload = event.callback.payload or ""
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != "todo":
        return

    action, raw_todo_id = parts[1], parts[2]
    chat_id, _user_id = event.get_ids()
    if chat_id is None or not raw_todo_id.isdigit():
        return

    todo_id = int(raw_todo_id)
    if action == "done":
        await TodoRepo(session).mark_done(chat_id, todo_id)
    elif action == "del":
        await TodoRepo(session).delete(chat_id, todo_id)
    else:
        return
    await session.commit()

    text, keyboard = await _render_todo_list(chat_id, session)
    attachments = [keyboard] if keyboard else None
    from maxapi.types.updates.message_callback import MessageForCallback

    await limiter.call(
        "send_callback",
        limit_key=chat_id,
        callback_id=event.callback.callback_id,
        message=MessageForCallback(text=text, attachments=attachments),
    )
```

- [ ] **Step 1: Write the failing tests** (against real Postgres, reusing `tests/db/conftest.py`'s `session` fixture — add `tests/handlers/conftest.py` that re-exports it, or point pytest at both dirs; simplest is a one-line `tests/handlers/conftest.py`:)

```python
# tests/handlers/conftest.py
from tests.db.conftest import _apply_migrations, _clean_tables, session, sessionmaker  # noqa: F401
```

```python
# tests/handlers/test_todo.py
from app.db.repo.todos import TodoRepo
from app.handlers.todo import handle_todo, handle_todo_callback
from maxapi.enums.chat_type import ChatType
from maxapi.types.message import Message, Recipient
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser
from maxapi.types.callback import Callback


class FakeLimiter:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.calls: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return None

    async def call(self, method_name, **kwargs):
        self.calls.append({"method": method_name, **kwargs})
        return None


def _make_message_event(chat_id: int, user_id: int = 1) -> MessageCreated:
    message = Message(
        sender=MaxUser(
            user_id=user_id, first_name="T", is_bot=False, last_activity_time=0
        ),
        recipient=Recipient(user_id=user_id, chat_id=chat_id, chat_type=ChatType.CHAT),
        timestamp=0,
    )
    return MessageCreated(message=message, timestamp=0)


def _make_callback_event(chat_id: int, payload: str, user_id: int = 1) -> MessageCallback:
    message = Message(
        sender=MaxUser(
            user_id=user_id, first_name="T", is_bot=False, last_activity_time=0
        ),
        recipient=Recipient(user_id=user_id, chat_id=chat_id, chat_type=ChatType.CHAT),
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


async def test_add_then_list_shows_numbered_items(session):
    limiter = FakeLimiter()

    await handle_todo(_make_message_event(100), ["add", "купить", "хлеб"], session, limiter)
    await handle_todo(_make_message_event(100), ["list"], session, limiter)

    assert "Добавлено: купить хлеб" in limiter.sent[0]["text"]
    assert "1. ⬜ купить хлеб" in limiter.sent[1]["text"]


async def test_done_by_position_marks_item(session):
    limiter = FakeLimiter()
    await handle_todo(_make_message_event(100), ["add", "дело"], session, limiter)

    await handle_todo(_make_message_event(100), ["done", "1"], session, limiter)

    todos = await TodoRepo(session).list_for_chat(100)
    assert todos[0].is_done is True
    assert "1. ✅ дело" in limiter.sent[-1]["text"]


async def test_del_by_position_removes_item(session):
    limiter = FakeLimiter()
    await handle_todo(_make_message_event(100), ["add", "дело"], session, limiter)

    await handle_todo(_make_message_event(100), ["del", "1"], session, limiter)

    todos = await TodoRepo(session).list_for_chat(100)
    assert todos == []
    assert "пуст" in limiter.sent[-1]["text"]


async def test_callback_done_marks_item_and_edits_message(session):
    limiter = FakeLimiter()
    todo = await TodoRepo(session).add(100, "дело", created_by=1)
    await session.commit()

    event = _make_callback_event(100, f"todo:done:{todo.id}")
    await handle_todo_callback(event, session, limiter)

    todos = await TodoRepo(session).list_for_chat(100)
    assert todos[0].is_done is True
    assert limiter.calls[0]["method"] == "send_callback"
    assert "✅" in limiter.calls[0]["message"].text
```

- [ ] **Step 2: Run to verify failure, implement `app/handlers/todo.py`, re-run to verify pass**

Run: `uv run pytest tests/handlers/test_todo.py -v` → fails, then implement, then passes (5 tests).

- [ ] **Step 3: Commit**

```bash
git add app/handlers/todo.py tests/handlers/conftest.py tests/handlers/test_todo.py
git commit -m "feat(bot): добавить команды /todo с инлайн-кнопками done/del"
```

---

### Task 4: `data/words.json` + word-of-day service + handlers + scheduler

**Files:**
- Create: `data/words.json` (30 entries)
- Create: `app/services/word_of_day.py`
- Create: `app/handlers/word_of_day.py`
- Modify: `app/main.py` (register `AsyncIOScheduler`, daily cron job)
- Test: `tests/services/test_word_of_day.py`, `tests/handlers/test_word_of_day.py`

**Interfaces:**
- Produces: `load_words(path: Path | None = None) -> list[dict]`, `pick_word_for_date(target_date: date, words: list[dict]) -> dict`, `format_word_message(word: dict) -> str`, `async def broadcast_daily_word(limiter: RateLimitedBot) -> None` (opens its own session via `get_sessionmaker()`, iterates `WordSubscriptionRepo.list_chat_ids()`). `word_of_day_router: Router` with `/word`, `/word sub`, `/word unsub`.

- [ ] **Step 1: `data/words.json`** — 30 objects `{"word": ..., "definition": ..., "example": ...}` (Russian vocabulary-building words, e.g. "сепульки" excluded — use real words: абрис, сентенция, инсинуация, эфемерный, ... — write 30 real entries).

- [ ] **Step 2: `app/services/word_of_day.py`** — write failing test first:

```python
# tests/services/test_word_of_day.py
from datetime import date

from app.services.word_of_day import format_word_message, load_words, pick_word_for_date


def test_load_words_returns_thirty_entries():
    words = load_words()
    assert len(words) == 30
    assert all({"word", "definition", "example"} <= set(w) for w in words)


def test_pick_word_for_date_is_deterministic():
    words = load_words()
    d = date(2026, 3, 15)

    first = pick_word_for_date(d, words)
    second = pick_word_for_date(d, words)

    assert first == second
    assert first in words


def test_pick_word_for_date_varies_by_day():
    words = load_words()

    word_a = pick_word_for_date(date(2026, 1, 1), words)
    word_b = pick_word_for_date(date(2026, 1, 2), words)

    assert word_a != word_b or len(words) == 1


def test_format_word_message_includes_all_fields():
    word = {"word": "абрис", "definition": "контур предмета", "example": "Абрис здания."}

    message = format_word_message(word)

    assert "абрис" in message
    assert "контур предмета" in message
    assert "Абрис здания." in message
```

Implement:

```python
# app/services/word_of_day.py
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.db.engine import get_sessionmaker
from app.db.repo.word_subscriptions import WordSubscriptionRepo
from app.rate_limit import RateLimitedBot

DEFAULT_WORDS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "words.json"


@lru_cache
def _load_words_cached(path_str: str) -> tuple[dict, ...]:
    with open(path_str, encoding="utf-8") as f:
        return tuple(json.load(f))


def load_words(path: Path | None = None) -> list[dict]:
    return list(_load_words_cached(str(path or DEFAULT_WORDS_PATH)))


def pick_word_for_date(target_date: date, words: list[dict]) -> dict:
    index = target_date.toordinal() % len(words)
    return words[index]


def format_word_message(word: dict) -> str:
    return f"📖 Слово дня: {word['word']}\n\n{word['definition']}\n\nПример: {word['example']}"


async def broadcast_daily_word(limiter: RateLimitedBot) -> None:
    words = load_words()
    message = format_word_message(pick_word_for_date(date.today(), words))

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        chat_ids = await WordSubscriptionRepo(session).list_chat_ids()

    for chat_id in chat_ids:
        await limiter.send_message(chat_id=chat_id, text=message)
```

Run: `uv run pytest tests/services/test_word_of_day.py -v` → passes after implementation.

- [ ] **Step 3: `app/handlers/word_of_day.py`** — write failing test first:

```python
# tests/handlers/test_word_of_day.py
from app.db.repo.word_subscriptions import WordSubscriptionRepo
from app.handlers.word_of_day import handle_word
from maxapi.enums.chat_type import ChatType
from maxapi.types.message import Message, Recipient
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser


class FakeLimiter:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return None


def _make_event(chat_id: int) -> MessageCreated:
    message = Message(
        sender=MaxUser(user_id=1, first_name="T", is_bot=False, last_activity_time=0),
        recipient=Recipient(user_id=1, chat_id=chat_id, chat_type=ChatType.CHAT),
        timestamp=0,
    )
    return MessageCreated(message=message, timestamp=0)


async def test_word_shows_todays_word(session):
    limiter = FakeLimiter()

    await handle_word(_make_event(100), [], session, limiter)

    assert "Слово дня" in limiter.sent[0]["text"]


async def test_word_sub_subscribes_chat(session):
    limiter = FakeLimiter()

    await handle_word(_make_event(100), ["sub"], session, limiter)

    assert await WordSubscriptionRepo(session).is_subscribed(100) is True
    assert "одписал" in limiter.sent[0]["text"]


async def test_word_unsub_unsubscribes_chat(session):
    limiter = FakeLimiter()
    await WordSubscriptionRepo(session).subscribe(100)
    await session.commit()

    await handle_word(_make_event(100), ["unsub"], session, limiter)

    assert await WordSubscriptionRepo(session).is_subscribed(100) is False
```

Implement:

```python
# app/handlers/word_of_day.py
from datetime import date

from maxapi import Router
from maxapi.filters.command import Command
from maxapi.types.updates.message_created import MessageCreated
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repo.word_subscriptions import WordSubscriptionRepo
from app.rate_limit import RateLimitedBot
from app.services.word_of_day import format_word_message, load_words, pick_word_for_date

word_of_day_router = Router("word_of_day")


@word_of_day_router.message_created(Command("word"))
async def handle_word(
    event: MessageCreated,
    args: list[str],
    session: AsyncSession,
    limiter: RateLimitedBot,
) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return

    subcommand = args[0].lower() if args else None

    if subcommand == "sub":
        await WordSubscriptionRepo(session).subscribe(chat_id)
        await session.commit()
        await limiter.send_message(
            chat_id=chat_id, text="Чат подписан на ежедневное слово дня в 09:00"
        )
        return

    if subcommand == "unsub":
        await WordSubscriptionRepo(session).unsubscribe(chat_id)
        await session.commit()
        await limiter.send_message(chat_id=chat_id, text="Чат отписан от слова дня")
        return

    message = format_word_message(pick_word_for_date(date.today(), load_words()))
    await limiter.send_message(chat_id=chat_id, text=message)
```

Run: `uv run pytest tests/handlers/test_word_of_day.py -v` → passes.

- [ ] **Step 4: Wire APScheduler into `app/main.py`**

Add to `app/main.py`:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.word_of_day import broadcast_daily_word


def build_scheduler(limiter: RateLimitedBot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=get_settings().tz)
    scheduler.add_job(
        broadcast_daily_word,
        "cron",
        hour=9,
        minute=0,
        args=[limiter],
        id="daily_word",
    )
    return scheduler
```

Wire it in `create_app()`'s lifespan (start after webhook subscribe, `scheduler.start()`; `scheduler.shutdown()` after the `yield`) and in `run_polling()` (start before `dispatcher.start_polling(bot)`, since polling blocks — start the scheduler first so it runs concurrently in the same event loop). Both need the `RateLimitedBot` instance that `build_dispatcher(bot)` already constructs internally — expose it by having `build_dispatcher` return `tuple[Dispatcher, RateLimitedBot]` instead of just `Dispatcher` (small, contained signature change; update `tests/test_main.py`'s monkeypatching only if it inspects the return value, otherwise no change needed since it only checks `/healthz`).

- [ ] **Step 5: Commit**

```bash
git add data/words.json app/services/word_of_day.py app/handlers/word_of_day.py app/main.py tests/services/__init__.py tests/services/test_word_of_day.py tests/handlers/test_word_of_day.py tests/test_main.py
git commit -m "feat(bot): добавить слово дня и ежедневную рассылку по расписанию"
```

---

### Task 5: Image converter

**Files:**
- Create: `app/services/converter.py`
- Create: `app/handlers/converter.py`
- Modify: `app/main.py` (include `converter_router`)
- Test: `tests/services/test_converter.py`, `tests/handlers/test_converter.py`

**Interfaces:**
- Produces: `SUPPORTED_FORMATS: frozenset[str]` (`{"png", "jpg", "webp", "pdf"}`), `convert_image(data: bytes, target_format: str) -> bytes` (pure, sync — called via `asyncio.to_thread`), `MAX_INPUT_SIZE_BYTES = 20 * 1024 * 1024`. `converter_router: Router` with a custom filter matching `MessageCreated` events carrying an `Image` attachment, and a `message_callback` handler for `conv:<format>:<mid>` payloads.

- [ ] **Step 1: `app/services/converter.py`** — write failing test first (uses Pillow directly to build a tiny in-memory source image, no I/O):

```python
# tests/services/test_converter.py
import io

import pytest
from PIL import Image as PILImage

from app.services.converter import SUPPORTED_FORMATS, convert_image


def _make_png_bytes() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGBA", (10, 10), color=(255, 0, 0, 128)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize("target_format", sorted(SUPPORTED_FORMATS))
def test_convert_image_produces_valid_output(target_format):
    source = _make_png_bytes()

    result = convert_image(source, target_format)

    out = PILImage.open(io.BytesIO(result))
    out.load()
    expected_pil_format = "JPEG" if target_format == "jpg" else target_format.upper()
    assert out.format == expected_pil_format


def test_convert_image_rejects_unsupported_format():
    source = _make_png_bytes()

    with pytest.raises(ValueError):
        convert_image(source, "bmp")


def test_convert_image_to_jpg_drops_alpha_without_error():
    source = _make_png_bytes()  # RGBA source

    result = convert_image(source, "jpg")

    out = PILImage.open(io.BytesIO(result))
    assert out.mode in {"RGB", "L"}
```

Implement:

```python
# app/services/converter.py
import io

from PIL import Image as PILImage

SUPPORTED_FORMATS = frozenset({"png", "jpg", "webp", "pdf"})
MAX_INPUT_SIZE_BYTES = 20 * 1024 * 1024

_PIL_FORMAT_BY_EXTENSION = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP", "pdf": "PDF"}


def convert_image(data: bytes, target_format: str) -> bytes:
    if target_format not in SUPPORTED_FORMATS:
        raise ValueError(f"Неподдерживаемый формат: {target_format}")

    image = PILImage.open(io.BytesIO(data))
    image.load()

    if target_format in {"jpg", "pdf"} and image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")

    output = io.BytesIO()
    image.save(output, format=_PIL_FORMAT_BY_EXTENSION[target_format])
    return output.getvalue()
```

Run: `uv run pytest tests/services/test_converter.py -v` → passes (6 parametrized/plain cases).

- [ ] **Step 2: `app/handlers/converter.py`** — write failing test first:

```python
# tests/handlers/test_converter.py
from maxapi.enums.chat_type import ChatType
from maxapi.types.attachments.attachment import PhotoAttachmentPayload
from maxapi.types.attachments.image import Image
from maxapi.types.message import Message, MessageBody, Recipient
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser
from maxapi.types.callback import Callback

from app.handlers.converter import handle_image_message, handle_conversion_callback
from app.services.converter import MAX_INPUT_SIZE_BYTES


class FakeLimiter:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.calls: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return None

    async def call(self, method_name, **kwargs):
        self.calls.append({"method": method_name, **kwargs})
        if method_name == "download_bytes":
            return kwargs.get("_test_bytes", b"")
        if method_name == "upload_media":
            class _Upload:
                pass

            return _Upload()
        return None


def _make_image_event(chat_id: int, mid: str = "m1") -> MessageCreated:
    image = Image(
        type="image",
        payload=PhotoAttachmentPayload(photo_id=1, token="tok", url="https://example.com/i.png"),
    )
    body = MessageBody(mid=mid, seq=1, text=None, attachments=[image])
    message = Message(
        sender=MaxUser(user_id=1, first_name="T", is_bot=False, last_activity_time=0),
        recipient=Recipient(user_id=1, chat_id=chat_id, chat_type=ChatType.CHAT),
        timestamp=0,
        body=body,
    )
    return MessageCreated(message=message, timestamp=0)


async def test_image_message_offers_format_buttons(monkeypatch):
    limiter = FakeLimiter()

    async def fake_download(**kwargs):
        return b"\x89PNG\r\n\x1a\n" + b"0" * 100

    monkeypatch.setattr(limiter, "call", fake_download, raising=False)
    # simpler: directly monkeypatch the module-level download used by the handler
    import app.handlers.converter as converter_module

    async def fake_bot_download_bytes(url):
        return b"\x89PNG\r\n\x1a\n" + b"0" * 100

    monkeypatch.setattr(
        converter_module, "_download_image_bytes", fake_bot_download_bytes
    )

    await handle_image_message(_make_image_event(100), limiter)

    assert limiter.sent
    assert "формат" in limiter.sent[0]["text"].lower()


async def test_image_message_rejects_oversized_file(monkeypatch):
    limiter = FakeLimiter()
    import app.handlers.converter as converter_module

    async def fake_too_big(url):
        return b"0" * (MAX_INPUT_SIZE_BYTES + 1)

    monkeypatch.setattr(converter_module, "_download_image_bytes", fake_too_big)

    await handle_image_message(_make_image_event(100), limiter)

    assert "20" in limiter.sent[0]["text"]
```

Implement `app/handlers/converter.py` with:
- `_pending_conversions: dict[str, bytes]` module-level dict (mid → downloaded bytes).
- `async def _download_image_bytes(url: str) -> bytes` — thin wrapper the tests monkeypatch; internally does `await get_bot_download(...)`. Since downloads are reads (not subject to CLAUDE.md's send-rate limits), this calls the raw `Bot.download_bytes` directly — the handler still receives `limiter` for `send_message`/`upload_media`/`send_callback`, keeping every *outgoing* call on the wrapper.
- A filter (plain function, not `Command`) checking `isinstance(event, MessageCreated)` and an `Image` in `event.message.body.attachments`.
- `handle_image_message(event, limiter)`: download via `_download_image_bytes`, enforce `MAX_INPUT_SIZE_BYTES`, store bytes in `_pending_conversions[mid]`, send format buttons (`conv:<fmt>:<mid>` payloads).
- `handle_conversion_callback(event, limiter)`: parse `conv:<fmt>:<mid>`, pop bytes from `_pending_conversions`, `await asyncio.to_thread(convert_image, data, fmt)`, `await limiter.call("upload_media", media=InputMediaBuffer(...))`, `await limiter.call("send_callback", callback_id=..., message=MessageForCallback(text="Готово!", attachments=[upload]))`.

Because the handler needs the real `Bot.download_bytes`, and `RateLimitedBot` only wraps outgoing calls by design, `_download_image_bytes` takes the raw `Bot` via `event._ensure_bot()` (same accessor maxapi's own shortcuts use internally) — acceptable since it's a read, not a write subject to the rate-limit spec.

Run: `uv run pytest tests/handlers/test_converter.py -v` → passes.

- [ ] **Step 3: Register `converter_router` in `app/main.py`** alongside the other three routers from Task 1/3/4.

- [ ] **Step 4: Commit**

```bash
git add app/services/converter.py app/handlers/converter.py app/main.py tests/services/test_converter.py tests/handlers/test_converter.py
git commit -m "feat(bot): добавить конвертер изображений"
```

---

### Task 6: Stage verification

- [ ] **Step 1: Full lint + test run**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -v`
Expected: all checks pass, all tests green

- [ ] **Step 2: `/help` text sanity check** — confirm `HELP_TEXT` actually lists all four features (manual read, not automated)
