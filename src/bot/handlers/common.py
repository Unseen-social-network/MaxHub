from maxapi import Router
from maxapi.filters.command import Command, CommandStart
from maxapi.types.attachments.buttons import OpenAppButton
from maxapi.types.updates.message_created import MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from bot.services.rate_limit import RateLimitedBot

common_router = Router("common")

HELP_TEXT = (
    "Я — MaxHub, бот «всё в одном» для этого чата.\n\n"
    "📝 Совместные списки дел:\n"
    "/todo add <текст> — добавить дело\n"
    "/todo list — показать список\n"
    "/todo done <n> — отметить выполненным\n"
    "/todo del <n> — удалить\n\n"
    "📖 Слово дня:\n"
    "/word — показать слово дня\n"
    "/word sub — подписать чат на ежедневную рассылку\n"
    "/word unsub — отписаться\n\n"
    "🖼 Конвертер изображений:\n"
    "Пришлите картинку — бот предложит форматы для конвертации.\n\n"
    "/help — это сообщение"
)


@common_router.message_created(CommandStart())
async def handle_start(event: MessageCreated, limiter: RateLimitedBot) -> None:
    chat_id, _user_id = event.get_ids()
    await limiter.send_message(chat_id=chat_id, text=HELP_TEXT)


@common_router.message_created(Command("help"))
async def handle_help(event: MessageCreated, limiter: RateLimitedBot) -> None:
    chat_id, _user_id = event.get_ids()
    await limiter.send_message(chat_id=chat_id, text=HELP_TEXT)


@common_router.message_created(Command("app"))
async def handle_open_app(event: MessageCreated, limiter: RateLimitedBot) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return

    bot_me = event._ensure_bot().me  # noqa: SLF001
    if bot_me is None or not bot_me.username:
        await limiter.send_message(
            chat_id=chat_id,
            text="Мини-приложение временно недоступно, попробуйте позже.",
        )
        return

    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        OpenAppButton(
            text="📱 Открыть приложение",
            web_app=bot_me.username,
            contact_id=bot_me.user_id,
        )
    )
    await limiter.send_message(
        chat_id=chat_id,
        text="Мини-приложение MaxHub: список дел, слово дня и рассылка для админов.",
        attachments=[keyboard.as_markup()],
    )
