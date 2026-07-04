from datetime import date

from maxapi import Router
from maxapi.filters.command import Command
from maxapi.types.updates.message_created import MessageCreated
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.repositories.word_subscriptions import WordSubscriptionRepo
from bot.services.rate_limit import RateLimitedBot
from bot.services.word_of_day import (
    format_word_message,
    load_words,
    pick_word_for_date,
)

word_of_day_router = Router("word_of_day")


@word_of_day_router.message_created(Command("word"))
async def handle_word(
    event: MessageCreated,
    args: list[str],
    session: AsyncSession,
    limiter: RateLimitedBot,
) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return

    subcommand = args[0].lower() if args else None

    if subcommand == "sub":
        await WordSubscriptionRepo(session).subscribe(chat_id)
        await session.commit()
        await limiter.send_message(
            chat_id=chat_id, text="Чат подписан на ежедневное слово дня в 09:00"
        )
        return

    if subcommand == "unsub":
        await WordSubscriptionRepo(session).unsubscribe(chat_id)
        await session.commit()
        await limiter.send_message(chat_id=chat_id, text="Чат отписан от слова дня")
        return

    message = format_word_message(pick_word_for_date(date.today(), load_words()))
    await limiter.send_message(chat_id=chat_id, text=message)
