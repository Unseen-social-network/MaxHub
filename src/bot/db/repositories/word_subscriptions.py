from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import WordSubscription


class WordSubscriptionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def subscribe(self, chat_id: int) -> None:
        stmt = insert(WordSubscription).values(chat_id=chat_id)
        stmt = stmt.on_conflict_do_nothing(index_elements=[WordSubscription.chat_id])
        await self._session.execute(stmt)

    async def unsubscribe(self, chat_id: int) -> None:
        stmt = sa_delete(WordSubscription).where(WordSubscription.chat_id == chat_id)
        await self._session.execute(stmt)

    async def is_subscribed(self, chat_id: int) -> bool:
        stmt = select(WordSubscription.chat_id).where(
            WordSubscription.chat_id == chat_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_chat_ids(self) -> list[int]:
        result = await self._session.execute(select(WordSubscription.chat_id))
        return list(result.scalars().all())
