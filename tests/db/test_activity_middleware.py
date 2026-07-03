from maxapi.enums.chat_type import ChatType
from maxapi.types.message import Message, Recipient
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser

from app.db.models import User
from app.middlewares import ActivityMiddleware


def _make_message_created(*, user_id: int, chat_id: int, is_dm: bool) -> MessageCreated:
    chat_type = ChatType.DIALOG if is_dm else ChatType.CHAT
    message = Message(
        sender=MaxUser(
            user_id=user_id,
            first_name="Test",
            is_bot=False,
            last_activity_time=0,
        ),
        recipient=Recipient(user_id=user_id, chat_id=chat_id, chat_type=chat_type),
        timestamp=0,
    )
    return MessageCreated(message=message, timestamp=0)


async def test_upserts_user_and_injects_session(sessionmaker):
    middleware = ActivityMiddleware(sessionmaker)
    event = _make_message_created(user_id=1, chat_id=100, is_dm=True)
    seen_session_is_open = False

    async def handler(event_object, handler_data):
        nonlocal seen_session_is_open
        seen_session_is_open = handler_data["session"].is_active
        return "handled"

    result = await middleware(handler, event, {})

    assert result == "handled"
    assert seen_session_is_open is True

    async with sessionmaker() as session:
        user = await session.get(User, 1)
        assert user is not None
        assert user.is_dm is True


async def test_group_chat_message_sets_is_dm_false(sessionmaker):
    middleware = ActivityMiddleware(sessionmaker)
    event = _make_message_created(user_id=2, chat_id=100, is_dm=False)

    async def handler(event_object, handler_data):
        return None

    await middleware(handler, event, {})

    async with sessionmaker() as session:
        user = await session.get(User, 2)
        assert user is not None
        assert user.is_dm is False
