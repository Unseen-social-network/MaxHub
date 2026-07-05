from maxapi.context.context import MemoryContext
from maxapi.enums.chat_type import ChatType
from maxapi.types.callback import Callback
from maxapi.types.message import Message, MessageBody, Recipient
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser

from bot.db.repositories.todos import TodoRepo
from bot.handlers.todo import (
    TodoStates,
    handle_todo,
    handle_todo_callback,
    handle_todo_fsm_add_text,
    handle_todo_fsm_choice,
    handle_todo_fsm_done_number,
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


def _make_message_event(
    chat_id: int, user_id: int = 1, text: str | None = None
) -> MessageCreated:
    message = Message(
        sender=MaxUser(
            user_id=user_id, first_name="T", is_bot=False, last_activity_time=0
        ),
        recipient=Recipient(user_id=user_id, chat_id=chat_id, chat_type=ChatType.CHAT),
        timestamp=0,
    )
    if text is not None:
        message.body = MessageBody(mid="m1", seq=1, text=text)
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
    context = MemoryContext(chat_id=100, user_id=1)

    await handle_todo(
        _make_message_event(100), ["add", "купить", "хлеб"], session, context, limiter
    )
    await handle_todo(_make_message_event(100), ["list"], session, context, limiter)

    assert "Добавлено: купить хлеб" in limiter.sent[0]["text"]
    assert "1. ⬜ купить хлеб" in limiter.sent[1]["text"]


async def test_done_by_position_marks_item(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    await handle_todo(
        _make_message_event(100), ["add", "дело"], session, context, limiter
    )

    await handle_todo(
        _make_message_event(100), ["done", "1"], session, context, limiter
    )

    todos = await TodoRepo(session).list_for_chat(100)
    assert todos[0].is_done is True
    assert "1. ✅ дело" in limiter.sent[-1]["text"]


async def test_del_by_position_removes_item(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    await handle_todo(
        _make_message_event(100), ["add", "дело"], session, context, limiter
    )

    await handle_todo(_make_message_event(100), ["del", "1"], session, context, limiter)

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
    context = MemoryContext(chat_id=100, user_id=1)

    await handle_todo(_make_message_event(100), ["add"], session, context, limiter)

    assert "Укажите текст" in limiter.sent[0]["text"]


async def test_bare_todo_starts_fsm_with_choice_buttons(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)

    await handle_todo(_make_message_event(100), [], session, context, limiter)

    assert await context.get_state() == TodoStates.choosing_action
    buttons = [
        button
        for row in limiter.sent[0]["attachments"][0].payload.buttons
        for button in row
    ]
    payloads = {button.payload for button in buttons}
    assert payloads == {
        "todo_fsm:add",
        "todo_fsm:list",
        "todo_fsm:done",
        "todo_fsm:del",
        "/help",
    }


async def test_fsm_choice_list_renders_list_and_clears_state(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    await context.set_state(TodoStates.choosing_action)
    await TodoRepo(session).add(100, "дело", created_by=1)
    await session.commit()

    event = _make_callback_event(100, "todo_fsm:list")
    await handle_todo_fsm_choice(event, session, context, limiter)

    assert await context.get_state() is None
    assert "дело" in limiter.calls[0]["message"].text


async def test_fsm_choice_add_prompts_for_text(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    await context.set_state(TodoStates.choosing_action)

    event = _make_callback_event(100, "todo_fsm:add")
    await handle_todo_fsm_choice(event, session, context, limiter)

    assert await context.get_state() == TodoStates.waiting_add_text


async def test_fsm_add_text_creates_todo_and_clears_state(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    await context.set_state(TodoStates.waiting_add_text)

    event = _make_message_event(100, text="купить молоко")
    await handle_todo_fsm_add_text(event, session, context, limiter)

    assert await context.get_state() is None
    todos = await TodoRepo(session).list_for_chat(100)
    assert todos[0].text == "купить молоко"


async def test_fsm_choice_done_with_empty_list_clears_state(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    await context.set_state(TodoStates.choosing_action)

    event = _make_callback_event(100, "todo_fsm:done")
    await handle_todo_fsm_choice(event, session, context, limiter)

    assert await context.get_state() is None
    assert "пуст" in limiter.calls[0]["message"].text.lower()


async def test_fsm_choice_done_with_items_prompts_for_number(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    await context.set_state(TodoStates.choosing_action)
    await TodoRepo(session).add(100, "дело", created_by=1)
    await session.commit()

    event = _make_callback_event(100, "todo_fsm:done")
    await handle_todo_fsm_choice(event, session, context, limiter)

    assert await context.get_state() == TodoStates.waiting_done_number


async def test_fsm_done_number_marks_item_and_clears_state(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    await TodoRepo(session).add(100, "дело", created_by=1)
    await session.commit()
    await context.set_state(TodoStates.waiting_done_number)

    event = _make_message_event(100, text="1")
    await handle_todo_fsm_done_number(event, session, context, limiter)

    assert await context.get_state() is None
    todos = await TodoRepo(session).list_for_chat(100)
    assert todos[0].is_done is True
