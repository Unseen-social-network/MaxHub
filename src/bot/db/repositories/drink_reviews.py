from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import DrinkReview
from bot.services.drink_reviews import DEFAULT_ORDER, DEFAULT_SORT


class DrinkReviewRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        chat_id: int,
        *,
        category: str,
        name: str,
        note: str,
        rating: int,
        created_by: int,
        is_favorite: bool = False,
    ) -> DrinkReview:
        review = DrinkReview(
            chat_id=chat_id,
            category=category,
            name=name,
            note=note,
            rating=rating,
            is_favorite=is_favorite,
            created_by=created_by,
        )
        self._session.add(review)
        await self._session.flush()
        return review

    async def get(self, chat_id: int, review_id: int) -> DrinkReview | None:
        stmt = select(DrinkReview).where(
            DrinkReview.id == review_id, DrinkReview.chat_id == chat_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_chat(
        self,
        chat_id: int,
        *,
        category: str | None = None,
        favorite: bool | None = None,
        search: str | None = None,
        sort: str = DEFAULT_SORT,
        order: str = DEFAULT_ORDER,
    ) -> list[DrinkReview]:
        stmt = select(DrinkReview).where(DrinkReview.chat_id == chat_id)

        if category:
            stmt = stmt.where(DrinkReview.category == category)
        if favorite:
            stmt = stmt.where(DrinkReview.is_favorite.is_(True))
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    DrinkReview.name.ilike(pattern),
                    DrinkReview.note.ilike(pattern),
                    DrinkReview.category.ilike(pattern),
                )
            )

        stmt = stmt.order_by(*self._order_by(sort, order))

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_categories(self, chat_id: int) -> list[str]:
        stmt = (
            select(DrinkReview.category)
            .where(DrinkReview.chat_id == chat_id)
            .distinct()
            .order_by(DrinkReview.category)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def set_favorite(
        self, chat_id: int, review_id: int, is_favorite: bool
    ) -> bool:
        stmt = (
            update(DrinkReview)
            .where(DrinkReview.id == review_id, DrinkReview.chat_id == chat_id)
            .values(is_favorite=is_favorite)
        )
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def update_fields(
        self, chat_id: int, review_id: int, **fields: object
    ) -> bool:
        if not fields:
            return await self.get(chat_id, review_id) is not None

        stmt = (
            update(DrinkReview)
            .where(DrinkReview.id == review_id, DrinkReview.chat_id == chat_id)
            .values(**fields)
        )
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def delete(self, chat_id: int, review_id: int) -> bool:
        stmt = sa_delete(DrinkReview).where(
            DrinkReview.id == review_id, DrinkReview.chat_id == chat_id
        )
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    @staticmethod
    def _order_by(sort: str, order: str) -> tuple[ColumnElement, ...]:
        descending = order == "desc"

        if sort == "favorite":
            primary = (
                DrinkReview.is_favorite.desc()
                if descending
                else DrinkReview.is_favorite.asc()
            )
            return (primary, DrinkReview.created_at.desc(), DrinkReview.id.desc())

        column = {
            "rating": DrinkReview.rating,
            "name": DrinkReview.name,
        }.get(sort, DrinkReview.created_at)

        column_order = column.desc() if descending else column.asc()
        tie_breaker = DrinkReview.id.desc() if descending else DrinkReview.id.asc()
        return (column_order, tie_breaker)
