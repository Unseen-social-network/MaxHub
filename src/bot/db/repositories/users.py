from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def touch_activity(self, user_id: int, is_dm: bool) -> None:
        stmt = insert(User).values(user_id=user_id, is_dm=is_dm)
        stmt = stmt.on_conflict_do_update(
            index_elements=[User.user_id],
            set_={
                "last_activity_at": func.now(),
                "is_dm": User.is_dm | stmt.excluded.is_dm,
            },
        )
        await self._session.execute(stmt)

    async def mark_blocked(self, user_id: int) -> None:
        await self._session.execute(
            update(User).where(User.user_id == user_id).values(is_blocked=True)
        )

    async def get_active_recipients(self, active_days: int) -> list[int]:
        cutoff = datetime.now(UTC) - timedelta(days=active_days)
        stmt = select(User.user_id).where(
            User.is_dm.is_(True),
            User.is_blocked.is_(False),
            User.last_activity_at >= cutoff,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
