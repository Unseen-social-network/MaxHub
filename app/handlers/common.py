from maxapi import Router
from maxapi.filters.command import Command, CommandStart
from maxapi.types.updates.message_created import MessageCreated

from app.rate_limit import RateLimitedBot

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
