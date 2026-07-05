from maxapi.enums.chat_type import ChatType
from maxapi.types.message import Message, MessageBody, Recipient
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser

from bot.handlers.fallback import (
    KNOWN_COMMANDS,
    IsUnrecognizedText,
    handle_unknown_command,
)


class FakeLimiter:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return None


def _make_event(chat_id: int, text: str | None) -> MessageCreated:
    message = Message(
        sender=MaxUser(user_id=1, first_name="T", is_bot=False, last_activity_time=0),
        recipient=Recipient(user_id=1, chat_id=chat_id, chat_type=ChatType.CHAT),
        timestamp=0,
    )
    if text is not None:
        message.body = MessageBody(mid="m1", seq=1, text=text)
    return MessageCreated(message=message, timestamp=0)


async def test_is_unrecognized_text_matches_slash_prefixed_text():
    filt = IsUnrecognizedText()

    assert await filt(_make_event(1, "/xyz")) is True
    assert await filt(_make_event(1, "  /xyz with args")) is True


async def test_is_unrecognized_text_matches_plain_text():
    filt = IsUnrecognizedText()

    assert await filt(_make_event(1, "просто сообщение в чат")) is True


async def test_is_unrecognized_text_rejects_empty_or_missing_text():
    filt = IsUnrecognizedText()

    assert await filt(_make_event(1, None)) is False
    assert await filt(_make_event(1, "   ")) is False


async def test_handle_unknown_command_sends_help_with_clipboard_buttons():
    limiter = FakeLimiter()

    await handle_unknown_command(_make_event(100, "/foobar"), limiter)

    assert len(limiter.sent) == 1
    sent = limiter.sent[0]
    assert sent["chat_id"] == 100
    assert "не разобрал" in sent["text"].lower()

    attachments = sent["attachments"]
    assert len(attachments) == 1
    keyboard = attachments[0]
    buttons = [button for row in keyboard.payload.buttons for button in row]
    assert len(buttons) == len(KNOWN_COMMANDS)
    for button, command in zip(buttons, KNOWN_COMMANDS, strict=True):
        assert button.payload == command
