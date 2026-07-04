from maxapi import Router
from maxapi.filters.filter import BaseFilter
from maxapi.types.attachments.buttons import ClipboardButton
from maxapi.types.updates.message_created import MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from bot.services.rate_limit import RateLimitedBot

fallback_router = Router("fallback")

KNOWN_COMMANDS = [
    "/start",
    "/help",
    "/todo add ",
    "/todo list",
    "/todo done ",
    "/todo del ",
    "/word",
    "/word sub",
    "/word unsub",
]


class LooksLikeCommand(BaseFilter):
    async def __call__(self, event: object) -> bool:
        if not isinstance(event, MessageCreated):
            return False
        body = event.message.body
        text = body.text if body else None
        return bool(text) and text.strip().startswith("/")


@fallback_router.message_created(LooksLikeCommand())
async def handle_unknown_command(
    event: MessageCreated, limiter: RateLimitedBot
) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return

    keyboard = InlineKeyboardBuilder()
    for command in KNOWN_COMMANDS:
        keyboard.row(ClipboardButton(text=command, payload=command))

    await limiter.send_message(
        chat_id=chat_id,
        text=(
            "Не разобрал команду 🤔 В MAX пока нет обычного копирования — "
            "нажмите кнопку, чтобы скопировать команду в буфер обмена, "
            "и отправьте её мне сами:"
        ),
        attachments=[keyboard.as_markup()],
    )
