from maxapi import Router
from maxapi.filters.command import Command
from maxapi.types.attachments.buttons import CallbackButton
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.types.updates.message_callback import MessageCallback, MessageForCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repo.todos import TodoRepo
from app.rate_limit import RateLimitedBot

todo_router = Router("todo")


async def _render_todo_list(
    chat_id: int, session: AsyncSession
) -> tuple[str, AttachmentButton | None]:
    todos = await TodoRepo(session).list_for_chat(chat_id)

    if not todos:
        return "Список дел пуст. Добавьте: /todo add <текст>", None

    lines = []
    keyboard = InlineKeyboardBuilder()
    for i, todo in enumerate(todos, start=1):
        mark = "✅" if todo.is_done else "⬜"
        lines.append(f"{i}. {mark} {todo.text}")
        keyboard.row(
            CallbackButton(text=f"✅ {i}", payload=f"todo:done:{todo.id}"),
            CallbackButton(text=f"🗑 {i}", payload=f"todo:del:{todo.id}"),
        )

    return "\n".join(lines), keyboard.as_markup()


@todo_router.message_created(Command("todo"))
async def handle_todo(
    event: MessageCreated,
    args: list[str],
    session: AsyncSession,
    limiter: RateLimitedBot,
) -> None:
    chat_id, user_id = event.get_ids()
    if chat_id is None:
        return

    if not args:
        await limiter.send_message(
            chat_id=chat_id, text="Использование: /todo add|list|done|del"
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
