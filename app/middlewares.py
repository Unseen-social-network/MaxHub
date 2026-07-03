from typing import Any

from maxapi.enums.chat_type import ChatType
from maxapi.filters.middleware import BaseMiddleware, HandlerCallable
from maxapi.types.updates import UpdateUnion
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repo.users import UserRepo


def _is_dm_event(event_object: UpdateUnion) -> bool:
    message = getattr(event_object, "message", None)
    recipient = getattr(message, "recipient", None) if message is not None else None
    if recipient is None:
        return False
    return recipient.chat_type == ChatType.DIALOG


class ActivityMiddleware(BaseMiddleware):
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def __call__(
        self,
        handler: HandlerCallable,
        event_object: UpdateUnion,
        data: dict[str, Any],
    ) -> Any:
        async with self._sessionmaker() as session:
            get_ids = getattr(event_object, "get_ids", None)
            if callable(get_ids):
                _chat_id, user_id = get_ids()
                if user_id is not None:
                    await UserRepo(session).touch_activity(
                        user_id, is_dm=_is_dm_event(event_object)
                    )
                    await session.commit()

            data["session"] = session
            return await handler(event_object, data)
