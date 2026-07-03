from maxapi.context.context import MemoryContext
from maxapi.enums.chat_type import ChatType
from maxapi.types.callback import Callback
from maxapi.types.message import Message, MessageBody, Recipient
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser
from sqlalchemy import select

from app.db.models import Broadcast
from app.db.repo.users import UserRepo
from app.handlers.admin import (
    BroadcastStates,
    handle_broadcast_decision,
    handle_broadcast_start,
    handle_broadcast_text,
    handle_version,
)


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


def _make_event(chat_id: int, user_id: int) -> MessageCreated:
    message = Message(
        sender=MaxUser(
            user_id=user_id, first_name="T", is_bot=False, last_activity_time=0
        ),
        recipient=Recipient(
            user_id=user_id, chat_id=chat_id, chat_type=ChatType.DIALOG
        ),
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


def _make_callback_event(chat_id: int, payload: str, user_id: int) -> MessageCallback:
    message = Message(
        sender=MaxUser(
            user_id=user_id, first_name="T", is_bot=False, last_activity_time=0
        ),
        recipient=Recipient(
            user_id=user_id, chat_id=chat_id, chat_type=ChatType.DIALOG
        ),
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

    assert await context.get_state() is None
    result = await session.execute(select(Broadcast).where(Broadcast.admin_id == 1))
    broadcasts = result.scalars().all()
    assert len(broadcasts) == 1
    assert broadcasts[0].text == "важное объявление"
    get_settings.cache_clear()
