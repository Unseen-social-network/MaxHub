from maxapi import Router
from maxapi.context.base import BaseContext
from maxapi.context.state_machine import State, StatesGroup
from maxapi.filters.command import Command
from maxapi.filters.state import StateFilter
from maxapi.types.attachments.buttons import CallbackButton, ClipboardButton
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.types.updates.message_callback import MessageCallback, MessageForCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.repositories.todos import TodoRepo
from bot.services.rate_limit import RateLimitedBot

todo_router = Router("todo")


class TodoStates(StatesGroup):
    choosing_action = State()
    waiting_add_text = State()
    waiting_done_number = State()
    waiting_del_number = State()


def _back_to_commands_button() -> ClipboardButton:
    return ClipboardButton(text="🏠 К командам", payload="/help")


async def _render_todo_list(
    chat_id: int, session: AsyncSession
) -> tuple[str, AttachmentButton | None]:
    todos = await TodoRepo(session).list_for_chat(chat_id)
    keyboard = InlineKeyboardBuilder()

    if not todos:
        keyboard.row(_back_to_commands_button())
        return "Список дел пуст. Добавьте: /todo add <текст>", keyboard.as_markup()

    lines = []
    for i, todo in enumerate(todos, start=1):
        mark = "✅" if todo.is_done else "⬜"
        lines.append(f"{i}. {mark} {todo.text}")
        keyboard.row(
            CallbackButton(text=f"✅ {i}", payload=f"todo:done:{todo.id}"),
            CallbackButton(text=f"🗑 {i}", payload=f"todo:del:{todo.id}"),
        )
    keyboard.row(_back_to_commands_button())

    return "\n".join(lines), keyboard.as_markup()


def _fsm_choice_keyboard() -> AttachmentButton:
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        CallbackButton(text="➕ Добавить", payload="todo_fsm:add"),
        CallbackButton(text="📋 Список", payload="todo_fsm:list"),
    )
    keyboard.row(
        CallbackButton(text="✅ Отметить готовым", payload="todo_fsm:done"),
        CallbackButton(text="🗑 Удалить", payload="todo_fsm:del"),
    )
    keyboard.row(_back_to_commands_button())
    return keyboard.as_markup()


@todo_router.message_created(Command("todo"))
async def handle_todo(
    event: MessageCreated,
    args: list[str],
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    chat_id, user_id = event.get_ids()
    if chat_id is None:
        return

    if not args:
        await context.set_state(TodoStates.choosing_action)
        await limiter.send_message(
            chat_id=chat_id,
            text="Что нужно сделать со списком дел?",
            attachments=[_fsm_choice_keyboard()],
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


@todo_router.message_callback(StateFilter(TodoStates.choosing_action))
async def handle_todo_fsm_choice(
    event: MessageCallback,
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return

    payload = event.callback.payload or ""

    if payload == "todo_fsm:list":
        await context.clear()
        text, keyboard = await _render_todo_list(chat_id, session)
        attachments = [keyboard] if keyboard else None
        await limiter.call(
            "send_callback",
            limit_key=chat_id,
            callback_id=event.callback.callback_id,
            message=MessageForCallback(text=text, attachments=attachments),
        )
        return

    if payload == "todo_fsm:add":
        await context.set_state(TodoStates.waiting_add_text)
        await limiter.call(
            "send_callback",
            limit_key=chat_id,
            callback_id=event.callback.callback_id,
            message=MessageForCallback(text="Введите текст дела одним сообщением"),
        )
        return

    if payload in {"todo_fsm:done", "todo_fsm:del"}:
        todos = await TodoRepo(session).list_for_chat(chat_id)
        if not todos:
            await context.clear()
            await limiter.call(
                "send_callback",
                limit_key=chat_id,
                callback_id=event.callback.callback_id,
                message=MessageForCallback(text="Список дел пуст"),
            )
            return

        is_done = payload == "todo_fsm:done"
        action_word = "отметить готовым" if is_done else "удалить"
        await context.set_state(
            TodoStates.waiting_done_number if is_done else TodoStates.waiting_del_number
        )
        list_text, _keyboard = await _render_todo_list(chat_id, session)
        await limiter.call(
            "send_callback",
            limit_key=chat_id,
            callback_id=event.callback.callback_id,
            message=MessageForCallback(
                text=f"{list_text}\n\nВведите номер дела, которое нужно {action_word}"
            ),
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

    await limiter.call(
        "send_callback",
        limit_key=chat_id,
        callback_id=event.callback.callback_id,
        message=MessageForCallback(text=text, attachments=attachments),
    )


@todo_router.message_created(StateFilter(TodoStates.waiting_add_text))
async def handle_todo_fsm_add_text(
    event: MessageCreated,
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    chat_id, user_id = event.get_ids()
    text = event.message.body.text if event.message.body else None
    if chat_id is None or not text or not text.strip():
        return

    text = text.strip()
    await TodoRepo(session).add(chat_id, text, created_by=user_id or 0)
    await session.commit()
    await context.clear()
    await limiter.send_message(chat_id=chat_id, text=f"Добавлено: {text}")


async def _handle_fsm_position(
    event: MessageCreated,
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
    *,
    is_done: bool,
) -> None:
    chat_id, _user_id = event.get_ids()
    text = event.message.body.text if event.message.body else None
    if chat_id is None:
        return

    if not text or not text.strip().isdigit():
        await limiter.send_message(chat_id=chat_id, text="Введите номер дела")
        return

    position = int(text.strip())
    todos = await TodoRepo(session).list_for_chat(chat_id)
    if position < 1 or position > len(todos):
        await limiter.send_message(chat_id=chat_id, text="Нет такого номера")
        return

    todo_id = todos[position - 1].id
    if is_done:
        await TodoRepo(session).mark_done(chat_id, todo_id)
    else:
        await TodoRepo(session).delete(chat_id, todo_id)
    await session.commit()
    await context.clear()

    text_out, keyboard = await _render_todo_list(chat_id, session)
    attachments = [keyboard] if keyboard else None
    await limiter.send_message(chat_id=chat_id, text=text_out, attachments=attachments)


@todo_router.message_created(StateFilter(TodoStates.waiting_done_number))
async def handle_todo_fsm_done_number(
    event: MessageCreated,
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    await _handle_fsm_position(event, session, context, limiter, is_done=True)


@todo_router.message_created(StateFilter(TodoStates.waiting_del_number))
async def handle_todo_fsm_del_number(
    event: MessageCreated,
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    await _handle_fsm_position(event, session, context, limiter, is_done=False)
