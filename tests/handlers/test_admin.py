from maxapi.enums.chat_type import ChatType
from maxapi.types.message import Message, Recipient
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser

from app.handlers.admin import handle_version


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
