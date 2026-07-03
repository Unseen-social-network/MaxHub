from maxapi import Router
from maxapi.filters.command import Command
from maxapi.filters.filter import BaseFilter
from maxapi.types.updates.message_created import MessageCreated

from app.config import get_settings
from app.rate_limit import RateLimitedBot

admin_router = Router("admin")


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
