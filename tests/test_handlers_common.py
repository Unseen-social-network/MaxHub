from maxapi.enums.chat_type import ChatType
from maxapi.types.message import Message, Recipient
from maxapi.types.updates.bot_started import BotStarted
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser

from bot.handlers.common import (
    HELP_TEXT,
    handle_bot_started,
    handle_help,
    handle_open_app,
    handle_start,
)


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


class FakeBot:
    class _Me:
        user_id = 777
        username = "maxhub_bot"

    me = _Me()


class FakeBotWithoutUsername:
    class _Me:
        user_id = 777
        username = None

    me = _Me()


async def test_start_sends_help_text_with_action_buttons():
    limiter = FakeLimiter()
    event = _make_event(chat_id=100)
    event.bot = FakeBot()

    await handle_start(event, limiter)

    assert len(limiter.sent) == 1
    sent = limiter.sent[0]
    assert sent["chat_id"] == 100
    assert sent["text"] == HELP_TEXT
    buttons = [
        button for row in sent["attachments"][0].payload.buttons for button in row
    ]
    assert {getattr(button, "payload", None) for button in buttons} >= {
        "/todo",
        "/word",
    }


async def test_start_without_bot_username_skips_open_app_button():
    limiter = FakeLimiter()
    event = _make_event(chat_id=100)
    event.bot = FakeBotWithoutUsername()

    await handle_start(event, limiter)

    buttons = [
        button
        for row in limiter.sent[0]["attachments"][0].payload.buttons
        for button in row
    ]
    assert len(buttons) == 2


async def test_bot_started_sends_help_text_with_action_buttons():
    limiter = FakeLimiter()
    event = BotStarted(
        chat_id=100,
        user=MaxUser(user_id=1, first_name="Test", is_bot=False, last_activity_time=0),
        timestamp=0,
    )
    event.bot = FakeBot()

    await handle_bot_started(event, limiter)

    assert len(limiter.sent) == 1
    sent = limiter.sent[0]
    assert sent["chat_id"] == 100
    assert sent["text"] == HELP_TEXT
    buttons = [
        button for row in sent["attachments"][0].payload.buttons for button in row
    ]
    assert {getattr(button, "payload", None) for button in buttons} >= {
        "/todo",
        "/word",
    }


async def test_help_sends_help_text():
    limiter = FakeLimiter()

    await handle_help(_make_event(chat_id=200), limiter)

    assert limiter.sent == [{"chat_id": 200, "text": HELP_TEXT}]


async def test_open_app_sends_open_app_button():
    limiter = FakeLimiter()
    event = _make_event(chat_id=300)
    event.bot = FakeBot()

    await handle_open_app(event, limiter)

    assert len(limiter.sent) == 1
    sent = limiter.sent[0]
    assert sent["chat_id"] == 300
    button = sent["attachments"][0].payload.buttons[0][0]
    assert button.web_app == "maxhub_bot"
    assert button.contact_id == 777


async def test_open_app_without_bot_username_sends_fallback_text():
    limiter = FakeLimiter()
    event = _make_event(chat_id=300)
    event.bot = FakeBotWithoutUsername()

    await handle_open_app(event, limiter)

    assert limiter.sent == [
        {
            "chat_id": 300,
            "text": "Мини-приложение временно недоступно, попробуйте позже.",
        }
    ]
