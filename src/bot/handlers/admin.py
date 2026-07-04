import asyncio

from maxapi import Router
from maxapi.context.base import BaseContext
from maxapi.context.state_machine import State, StatesGroup
from maxapi.filters.command import Command
from maxapi.filters.filter import BaseFilter
from maxapi.filters.state import StateFilter
from maxapi.types.attachments.buttons import CallbackButton
from maxapi.types.updates.message_callback import MessageCallback, MessageForCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.repositories.broadcasts import BroadcastRepo
from bot.db.repositories.users import UserRepo
from bot.services.broadcast import run_broadcast
from bot.services.rate_limit import RateLimitedBot

admin_router = Router("admin")

_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


class IsAdmin(BaseFilter):
    async def __call__(self, event: object) -> bool:
        get_ids = getattr(event, "get_ids", None)
        if not callable(get_ids):
            return False
        _chat_id, user_id = get_ids()
        return user_id is not None and user_id in get_settings().admin_ids


@admin_router.message_created(Command("v"), IsAdmin())
async def handle_version(event: MessageCreated, limiter: RateLimitedBot) -> None:
    chat_id, user_id = event.get_ids()
    if chat_id is None or user_id is None or user_id not in get_settings().admin_ids:
        return

    settings = get_settings()
    await limiter.send_message(
        chat_id=chat_id,
        text=(
            f"версия: {settings.app_version}, sha: {settings.git_sha}, "
            f"собрано: {settings.build_time}"
        ),
    )


class BroadcastStates(StatesGroup):
    waiting_text = State()
    confirming = State()


@admin_router.message_created(Command("broadcast"), IsAdmin())
async def handle_broadcast_start(
    event: MessageCreated, context: BaseContext, limiter: RateLimitedBot
) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return
    await context.set_state(BroadcastStates.waiting_text)
    await limiter.send_message(chat_id=chat_id, text="Отправьте текст рассылки")


@admin_router.message_created(StateFilter(BroadcastStates.waiting_text), IsAdmin())
async def handle_broadcast_text(
    event: MessageCreated,
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    chat_id, _user_id = event.get_ids()
    text = event.message.body.text if event.message.body else None
    if chat_id is None or not text:
        return

    recipients = await UserRepo(session).get_active_recipients(
        get_settings().broadcast_active_days
    )
    await context.update_data(text=text)
    await context.set_state(BroadcastStates.confirming)

    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        CallbackButton(text="✅ Отправить", payload="broadcast:confirm"),
        CallbackButton(text="❌ Отменить", payload="broadcast:cancel"),
    )
    preview = f"Превью рассылки:\n\n{text}\n\nАктивных получателей: {len(recipients)}"
    await limiter.send_message(
        chat_id=chat_id, text=preview, attachments=[keyboard.as_markup()]
    )


@admin_router.message_callback(StateFilter(BroadcastStates.confirming), IsAdmin())
async def handle_broadcast_decision(
    event: MessageCallback,
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    chat_id, user_id = event.get_ids()
    if chat_id is None:
        return

    data = await context.get_data()
    text = data.get("text", "")
    await context.clear()

    if event.callback.payload == "broadcast:cancel":
        await limiter.call(
            "send_callback",
            limit_key=chat_id,
            callback_id=event.callback.callback_id,
            message=MessageForCallback(text="Рассылка отменена"),
        )
        return

    if event.callback.payload != "broadcast:confirm":
        return

    await limiter.call(
        "send_callback",
        limit_key=chat_id,
        callback_id=event.callback.callback_id,
        message=MessageForCallback(text="Рассылка запущена…"),
    )

    broadcast = await BroadcastRepo(session).create(admin_id=user_id or 0, text=text)
    await session.commit()

    _spawn_background(
        run_broadcast(
            limiter, admin_chat_id=chat_id, broadcast_id=broadcast.id, text=text
        )
    )
