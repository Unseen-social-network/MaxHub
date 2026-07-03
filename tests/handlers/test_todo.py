from maxapi.enums.chat_type import ChatType
from maxapi.types.callback import Callback
from maxapi.types.message import Message, Recipient
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser

from app.db.repo.todos import TodoRepo
from app.handlers.todo import handle_todo, handle_todo_callback


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


def _make_callback_event(
    chat_id: int, payload: str, user_id: int = 1
) -> MessageCallback:
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

    await handle_todo(
        _make_message_event(100), ["add", "купить", "хлеб"], session, limiter
    )
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


async def test_add_without_text_shows_usage(session):
    limiter = FakeLimiter()

    await handle_todo(_make_message_event(100), ["add"], session, limiter)

    assert "Укажите текст" in limiter.sent[0]["text"]
