from maxapi.enums.chat_type import ChatType
from maxapi.types.message import Message, Recipient
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser

from app.db.repo.word_subscriptions import WordSubscriptionRepo
from app.handlers.word_of_day import handle_word


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
    assert "одписан" in limiter.sent[0]["text"]


async def test_word_unsub_unsubscribes_chat(session):
    limiter = FakeLimiter()
    await WordSubscriptionRepo(session).subscribe(100)
    await session.commit()

    await handle_word(_make_event(100), ["unsub"], session, limiter)

    assert await WordSubscriptionRepo(session).is_subscribed(100) is False
