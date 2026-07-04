from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Todo


class TodoRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, chat_id: int, text: str, created_by: int) -> Todo:
        todo = Todo(chat_id=chat_id, text=text, created_by=created_by)
        self._session.add(todo)
        await self._session.flush()
        return todo

    async def list_for_chat(self, chat_id: int) -> list[Todo]:
        stmt = (
            select(Todo)
            .where(Todo.chat_id == chat_id)
            .order_by(Todo.created_at, Todo.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_done(self, chat_id: int, todo_id: int) -> bool:
        stmt = (
            update(Todo)
            .where(Todo.id == todo_id, Todo.chat_id == chat_id)
            .values(is_done=True)
        )
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def delete(self, chat_id: int, todo_id: int) -> bool:
        stmt = sa_delete(Todo).where(Todo.id == todo_id, Todo.chat_id == chat_id)
        result = await self._session.execute(stmt)
        return result.rowcount > 0
