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
