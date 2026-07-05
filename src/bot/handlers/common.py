from maxapi import Router
from maxapi.filters.command import Command, CommandStart
from maxapi.types.attachments.buttons import ClipboardButton, OpenAppButton
from maxapi.types.updates.bot_started import BotStarted
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


def _open_app_button(event: MessageCreated | BotStarted) -> OpenAppButton | None:
    bot_me = event._ensure_bot().me  # noqa: SLF001
    if bot_me is None or not bot_me.username:
        return None
    return OpenAppButton(
        text="📱 Открыть приложение",
        web_app=bot_me.username,
        contact_id=bot_me.user_id,
    )


async def _send_welcome(
    event: MessageCreated | BotStarted, limiter: RateLimitedBot
) -> None:
    chat_id, _user_id = event.get_ids()

    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        ClipboardButton(text="📝 Список дел", payload="/todo"),
        ClipboardButton(text="📖 Слово дня", payload="/word"),
    )
    app_button = _open_app_button(event)
    if app_button is not None:
        keyboard.row(app_button)

    await limiter.send_message(
        chat_id=chat_id, text=HELP_TEXT, attachments=[keyboard.as_markup()]
    )


@common_router.message_created(CommandStart())
async def handle_start(event: MessageCreated, limiter: RateLimitedBot) -> None:
    await _send_welcome(event, limiter)


@common_router.bot_started()
async def handle_bot_started(event: BotStarted, limiter: RateLimitedBot) -> None:
    await _send_welcome(event, limiter)


@common_router.message_created(Command("help"))
async def handle_help(event: MessageCreated, limiter: RateLimitedBot) -> None:
    chat_id, _user_id = event.get_ids()
    await limiter.send_message(chat_id=chat_id, text=HELP_TEXT)


@common_router.message_created(Command("app"))
async def handle_open_app(event: MessageCreated, limiter: RateLimitedBot) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return

    app_button = _open_app_button(event)
    if app_button is None:
        await limiter.send_message(
            chat_id=chat_id,
            text="Мини-приложение временно недоступно, попробуйте позже.",
        )
        return

    keyboard = InlineKeyboardBuilder()
    keyboard.add(app_button)
    await limiter.send_message(
        chat_id=chat_id,
        text="Мини-приложение MaxHub: список дел, слово дня и рассылка для админов.",
        attachments=[keyboard.as_markup()],
    )
