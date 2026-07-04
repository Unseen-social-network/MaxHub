from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Broadcast


class BroadcastRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, admin_id: int, text: str) -> Broadcast:
        broadcast = Broadcast(admin_id=admin_id, text=text)
        self._session.add(broadcast)
        await self._session.flush()
        return broadcast

    async def update_counts(
        self, broadcast_id: int, sent_count: int, failed_count: int
    ) -> None:
        stmt = (
            update(Broadcast)
            .where(Broadcast.id == broadcast_id)
            .values(sent_count=sent_count, failed_count=failed_count)
        )
        await self._session.execute(stmt)
