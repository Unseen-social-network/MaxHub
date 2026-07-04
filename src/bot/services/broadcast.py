import logging

from bot.config import get_settings
from bot.db.repositories.broadcasts import BroadcastRepo
from bot.db.repositories.users import UserRepo
from bot.db.session import get_sessionmaker
from bot.services.rate_limit import RateLimitedBot

logger = logging.getLogger(__name__)


async def run_broadcast(
    limiter: RateLimitedBot,
    *,
    admin_chat_id: int,
    broadcast_id: int,
    text: str,
    progress_every: int = 50,
) -> None:
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        recipients = await UserRepo(session).get_active_recipients(
            get_settings().broadcast_active_days
        )

    sent = 0
    failed = 0

    for i, user_id in enumerate(recipients, start=1):
        try:
            await limiter.send_message(user_id=user_id, text=text)
            sent += 1
        except Exception:
            failed += 1
            logger.warning("Не удалось доставить рассылку пользователю %s", user_id)
            async with sessionmaker() as session:
                await UserRepo(session).mark_blocked(user_id)
                await session.commit()

        if i % progress_every == 0:
            await limiter.send_message(
                chat_id=admin_chat_id,
                text=f"Прогресс рассылки: {i}/{len(recipients)}",
            )

    async with sessionmaker() as session:
        await BroadcastRepo(session).update_counts(
            broadcast_id, sent_count=sent, failed_count=failed
        )
        await session.commit()

    await limiter.send_message(
        chat_id=admin_chat_id,
        text=f"Рассылка завершена: отправлено {sent}, не доставлено {failed}",
    )
