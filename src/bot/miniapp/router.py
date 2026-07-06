import asyncio
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import get_settings
from bot.db.models import DrinkReview
from bot.db.repositories.broadcasts import BroadcastRepo
from bot.db.repositories.drink_reviews import DrinkReviewRepo
from bot.db.repositories.todos import TodoRepo
from bot.db.repositories.users import UserRepo
from bot.db.repositories.word_subscriptions import WordSubscriptionRepo
from bot.miniapp.auth import InitData, InvalidInitData, verify_init_data
from bot.services.broadcast import run_broadcast
from bot.services.drink_reviews import (
    DEFAULT_ORDER,
    DEFAULT_SORT,
    InvalidDrinkReview,
    display_category,
    normalize_category,
    validate_category,
    validate_name,
    validate_note,
    validate_order,
    validate_rating,
    validate_sort,
)
from bot.services.rate_limit import RateLimitedBot
from bot.services.word_of_day import load_words, pick_word_for_date

STATIC_DIR = Path(__file__).resolve().parent / "static"

_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


class BroadcastRequest(BaseModel):
    text: str


class TodoCreateRequest(BaseModel):
    text: str


class DrinkReviewCreateRequest(BaseModel):
    category: str
    name: str
    note: str = ""
    rating: int
    is_favorite: bool = False


class DrinkReviewUpdateRequest(BaseModel):
    category: str | None = None
    name: str | None = None
    note: str | None = None
    rating: int | None = None
    is_favorite: bool | None = None


def _serialize_drink(review: DrinkReview) -> dict:
    return {
        "id": review.id,
        "category": review.category,
        "category_display": display_category(review.category),
        "name": review.name,
        "note": review.note,
        "rating": review.rating,
        "is_favorite": review.is_favorite,
        "created_at": review.created_at.isoformat(),
        "updated_at": review.updated_at.isoformat(),
    }


def build_miniapp_router(
    sessionmaker: async_sessionmaker[AsyncSession],
    limiter: RateLimitedBot,
    *,
    bot_token: str,
) -> APIRouter:
    router = APIRouter()

    def _extract_init_data(x_init_data: str | None) -> InitData:
        if not x_init_data:
            raise HTTPException(status_code=401, detail="Missing X-Init-Data")
        try:
            return verify_init_data(x_init_data, bot_token)
        except InvalidInitData as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def _require_admin(init_data: InitData) -> int:
        if init_data.user is None or init_data.user.id not in get_settings().admin_ids:
            raise HTTPException(status_code=403, detail="Только для админов")
        return init_data.user.id

    @router.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @router.get("/api/todos")
    async def get_todos(x_init_data: str | None = Header(default=None)) -> dict:
        init_data = _extract_init_data(x_init_data)
        if init_data.chat is None:
            raise HTTPException(status_code=400, detail="Нет контекста чата")

        async with sessionmaker() as session:
            todos = await TodoRepo(session).list_for_chat(init_data.chat.id)

        return {
            "todos": [
                {"id": todo.id, "text": todo.text, "is_done": todo.is_done}
                for todo in todos
            ]
        }

    @router.post("/api/todos")
    async def add_todo(
        payload: TodoCreateRequest, x_init_data: str | None = Header(default=None)
    ) -> dict:
        init_data = _extract_init_data(x_init_data)
        if init_data.chat is None:
            raise HTTPException(status_code=400, detail="Нет контекста чата")

        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Текст дела пуст")

        created_by = init_data.user.id if init_data.user else 0
        async with sessionmaker() as session:
            todo = await TodoRepo(session).add(
                init_data.chat.id, text, created_by=created_by
            )
            await session.commit()

        return {"id": todo.id, "text": todo.text, "is_done": todo.is_done}

    @router.post("/api/todos/{todo_id}/done")
    async def mark_todo_done(
        todo_id: int, x_init_data: str | None = Header(default=None)
    ) -> dict:
        init_data = _extract_init_data(x_init_data)
        if init_data.chat is None:
            raise HTTPException(status_code=400, detail="Нет контекста чата")

        async with sessionmaker() as session:
            found = await TodoRepo(session).mark_done(init_data.chat.id, todo_id)
            await session.commit()

        if not found:
            raise HTTPException(status_code=404, detail="Дело не найдено")

        return {"status": "ok"}

    @router.delete("/api/todos/{todo_id}")
    async def delete_todo(
        todo_id: int, x_init_data: str | None = Header(default=None)
    ) -> dict:
        init_data = _extract_init_data(x_init_data)
        if init_data.chat is None:
            raise HTTPException(status_code=400, detail="Нет контекста чата")

        async with sessionmaker() as session:
            found = await TodoRepo(session).delete(init_data.chat.id, todo_id)
            await session.commit()

        if not found:
            raise HTTPException(status_code=404, detail="Дело не найдено")

        return {"status": "ok"}

    @router.get("/api/drinks")
    async def get_drinks(
        x_init_data: str | None = Header(default=None),
        search: str | None = None,
        category: str | None = None,
        favorite: bool | None = None,
        sort: str = DEFAULT_SORT,
        order: str = DEFAULT_ORDER,
    ) -> dict:
        init_data = _extract_init_data(x_init_data)
        if init_data.chat is None:
            raise HTTPException(status_code=400, detail="Нет контекста чата")

        try:
            sort = validate_sort(sort)
            order = validate_order(order)
        except InvalidDrinkReview as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        normalized_category = normalize_category(category) if category else None
        search_query = search.strip() if search else None

        async with sessionmaker() as session:
            reviews = await DrinkReviewRepo(session).list_for_chat(
                init_data.chat.id,
                category=normalized_category,
                favorite=favorite,
                search=search_query,
                sort=sort,
                order=order,
            )

        return {"drinks": [_serialize_drink(review) for review in reviews]}

    @router.get("/api/drinks/categories")
    async def get_drink_categories(
        x_init_data: str | None = Header(default=None),
    ) -> dict:
        init_data = _extract_init_data(x_init_data)
        if init_data.chat is None:
            raise HTTPException(status_code=400, detail="Нет контекста чата")

        async with sessionmaker() as session:
            categories = await DrinkReviewRepo(session).list_categories(
                init_data.chat.id
            )

        return {
            "categories": [
                {"value": category, "label": display_category(category)}
                for category in categories
            ]
        }

    @router.post("/api/drinks")
    async def add_drink(
        payload: DrinkReviewCreateRequest,
        x_init_data: str | None = Header(default=None),
    ) -> dict:
        init_data = _extract_init_data(x_init_data)
        if init_data.chat is None:
            raise HTTPException(status_code=400, detail="Нет контекста чата")

        try:
            category = validate_category(payload.category)
            name = validate_name(payload.name)
            note = validate_note(payload.note)
            rating = validate_rating(payload.rating)
        except InvalidDrinkReview as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        created_by = init_data.user.id if init_data.user else 0
        async with sessionmaker() as session:
            review = await DrinkReviewRepo(session).add(
                init_data.chat.id,
                category=category,
                name=name,
                note=note,
                rating=rating,
                created_by=created_by,
                is_favorite=payload.is_favorite,
            )
            await session.commit()

        return _serialize_drink(review)

    @router.patch("/api/drinks/{review_id}")
    async def update_drink(
        review_id: int,
        payload: DrinkReviewUpdateRequest,
        x_init_data: str | None = Header(default=None),
    ) -> dict:
        init_data = _extract_init_data(x_init_data)
        if init_data.chat is None:
            raise HTTPException(status_code=400, detail="Нет контекста чата")

        fields: dict = {}
        try:
            if payload.category is not None:
                fields["category"] = validate_category(payload.category)
            if payload.name is not None:
                fields["name"] = validate_name(payload.name)
            if payload.note is not None:
                fields["note"] = validate_note(payload.note)
            if payload.rating is not None:
                fields["rating"] = validate_rating(payload.rating)
        except InvalidDrinkReview as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if payload.is_favorite is not None:
            fields["is_favorite"] = payload.is_favorite

        async with sessionmaker() as session:
            found = await DrinkReviewRepo(session).update_fields(
                init_data.chat.id, review_id, **fields
            )
            await session.commit()

        if not found:
            raise HTTPException(status_code=404, detail="Рецензия не найдена")

        return {"status": "ok"}

    @router.delete("/api/drinks/{review_id}")
    async def delete_drink(
        review_id: int, x_init_data: str | None = Header(default=None)
    ) -> dict:
        init_data = _extract_init_data(x_init_data)
        if init_data.chat is None:
            raise HTTPException(status_code=400, detail="Нет контекста чата")

        async with sessionmaker() as session:
            found = await DrinkReviewRepo(session).delete(init_data.chat.id, review_id)
            await session.commit()

        if not found:
            raise HTTPException(status_code=404, detail="Рецензия не найдена")

        return {"status": "ok"}

    @router.get("/api/word")
    async def get_word(x_init_data: str | None = Header(default=None)) -> dict:
        init_data = _extract_init_data(x_init_data)
        word = pick_word_for_date(date.today(), load_words())

        subscribed = False
        if init_data.chat is not None:
            async with sessionmaker() as session:
                subscribed = await WordSubscriptionRepo(session).is_subscribed(
                    init_data.chat.id
                )

        return {
            "word": word["word"],
            "definition": word["definition"],
            "example": word["example"],
            "subscribed": subscribed,
        }

    @router.post("/api/word/subscribe")
    async def subscribe_word(x_init_data: str | None = Header(default=None)) -> dict:
        init_data = _extract_init_data(x_init_data)
        if init_data.chat is None:
            raise HTTPException(status_code=400, detail="Нет контекста чата")

        async with sessionmaker() as session:
            await WordSubscriptionRepo(session).subscribe(init_data.chat.id)
            await session.commit()

        return {"subscribed": True}

    @router.post("/api/word/unsubscribe")
    async def unsubscribe_word(x_init_data: str | None = Header(default=None)) -> dict:
        init_data = _extract_init_data(x_init_data)
        if init_data.chat is None:
            raise HTTPException(status_code=400, detail="Нет контекста чата")

        async with sessionmaker() as session:
            await WordSubscriptionRepo(session).unsubscribe(init_data.chat.id)
            await session.commit()

        return {"subscribed": False}

    @router.get("/api/broadcast/summary")
    async def broadcast_summary(x_init_data: str | None = Header(default=None)) -> dict:
        init_data = _extract_init_data(x_init_data)
        _require_admin(init_data)

        async with sessionmaker() as session:
            recipients = await UserRepo(session).get_active_recipients(
                get_settings().broadcast_active_days
            )

        return {"active_recipients": len(recipients)}

    @router.post("/api/broadcast")
    async def send_broadcast(
        payload: BroadcastRequest, x_init_data: str | None = Header(default=None)
    ) -> dict:
        init_data = _extract_init_data(x_init_data)
        admin_id = _require_admin(init_data)

        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Текст рассылки пуст")

        async with sessionmaker() as session:
            broadcast = await BroadcastRepo(session).create(
                admin_id=admin_id, text=text
            )
            await session.commit()
            broadcast_id = broadcast.id

        admin_chat_id = init_data.chat.id if init_data.chat else admin_id

        _spawn_background(
            run_broadcast(
                limiter,
                admin_chat_id=admin_chat_id,
                broadcast_id=broadcast_id,
                text=text,
            )
        )

        return {"status": "started"}

    return router
