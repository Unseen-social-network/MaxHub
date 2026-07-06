import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx2
from fastapi import FastAPI

from bot.db.repositories.drink_reviews import DrinkReviewRepo
from bot.miniapp.router import build_miniapp_router

BOT_TOKEN = "test-bot-token"


def _sign(params: dict) -> str:
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(
        b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256
    ).digest()
    return hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _init_data_header(*, user_id: int, chat_id: int | None) -> str:
    params = {
        "query_id": "abc123",
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": "Test"}),
    }
    if chat_id is not None:
        params["chat"] = json.dumps({"id": chat_id, "type": "CHAT"})
    params["hash"] = _sign(params)
    return urlencode(params)


class FakeLimiter:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return None


def _make_app(sessionmaker, limiter) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_miniapp_router(sessionmaker, limiter, bot_token=BOT_TOKEN),
        prefix="/miniapp",
    )
    return app


def _client(app: FastAPI) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    )


async def _add(repo, chat_id=100, **overrides):
    fields = {
        "category": "вино",
        "name": "Мерло",
        "note": "",
        "rating": 7,
        "created_by": 1,
    }
    fields.update(overrides)
    return await repo.add(chat_id, **fields)


async def test_get_drinks_returns_chat_scoped_list(session, sessionmaker):
    repo = DrinkReviewRepo(session)
    await _add(repo, chat_id=100, name="Мерло")
    await _add(repo, chat_id=200, name="Чужой")
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get("/miniapp/api/drinks", headers=headers)

    assert response.status_code == 200
    drinks = response.json()["drinks"]
    assert [d["name"] for d in drinks] == ["Мерло"]


async def test_get_drinks_filters_by_category_case_insensitive(session, sessionmaker):
    repo = DrinkReviewRepo(session)
    await _add(repo, category="вино", name="Мерло")
    await _add(repo, category="пиво", name="Лагер")
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get(
            "/miniapp/api/drinks", headers=headers, params={"category": "ВИНО"}
        )

    assert response.status_code == 200
    drinks = response.json()["drinks"]
    assert [d["name"] for d in drinks] == ["Мерло"]


async def test_get_drinks_search_by_name_note_category(session, sessionmaker):
    repo = DrinkReviewRepo(session)
    await _add(repo, name="Особый Мерло", note="")
    await _add(repo, name="Совиньон Блан", note="кисловатый")
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get(
            "/miniapp/api/drinks", headers=headers, params={"search": "мерло"}
        )

    assert response.status_code == 200
    assert [d["name"] for d in response.json()["drinks"]] == ["Особый Мерло"]


async def test_get_drinks_search_empty_string_does_not_crash(session, sessionmaker):
    repo = DrinkReviewRepo(session)
    await _add(repo, name="Мерло")
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get(
            "/miniapp/api/drinks", headers=headers, params={"search": ""}
        )

    assert response.status_code == 200
    assert len(response.json()["drinks"]) == 1


async def test_get_drinks_favorite_filter(session, sessionmaker):
    repo = DrinkReviewRepo(session)
    await _add(repo, name="Обычный", is_favorite=False)
    await _add(repo, name="Любимый", is_favorite=True)
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get(
            "/miniapp/api/drinks", headers=headers, params={"favorite": "true"}
        )

    assert response.status_code == 200
    assert [d["name"] for d in response.json()["drinks"]] == ["Любимый"]


async def test_get_drinks_sort_by_rating(session, sessionmaker):
    repo = DrinkReviewRepo(session)
    await _add(repo, name="Низкий", rating=3)
    await _add(repo, name="Высокий", rating=9)
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get(
            "/miniapp/api/drinks",
            headers=headers,
            params={"sort": "rating", "order": "desc"},
        )

    assert [d["name"] for d in response.json()["drinks"]] == ["Высокий", "Низкий"]


async def test_get_drinks_rejects_unknown_sort_field(sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get(
            "/miniapp/api/drinks", headers=headers, params={"sort": "price"}
        )

    assert response.status_code == 400


async def test_get_drinks_rejects_unknown_order(sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get(
            "/miniapp/api/drinks", headers=headers, params={"order": "random"}
        )

    assert response.status_code == 400


async def test_get_drink_categories_returns_only_used_categories_for_chat(
    session, sessionmaker
):
    repo = DrinkReviewRepo(session)
    await _add(repo, chat_id=100, category="вино")
    await _add(repo, chat_id=100, category="пиво")
    await _add(repo, chat_id=200, category="чай")
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get("/miniapp/api/drinks/categories", headers=headers)

    assert response.status_code == 200
    categories = response.json()["categories"]
    assert {c["value"] for c in categories} == {"вино", "пиво"}
    assert {c["label"] for c in categories} == {"Вино", "Пиво"}


async def test_add_drink_creates_review_with_new_category(session, sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.post(
            "/miniapp/api/drinks",
            headers=headers,
            json={
                "category": "  ЭНЕРГЕТИКИ  ",
                "name": "Ред Булл",
                "note": "бодрит",
                "rating": 6,
                "is_favorite": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "энергетики"
    assert body["category_display"] == "Энергетики"
    assert body["name"] == "Ред Булл"
    assert body["is_favorite"] is True

    reviews = await DrinkReviewRepo(session).list_for_chat(100)
    assert len(reviews) == 1
    assert reviews[0].created_by == 1


async def test_add_drink_rejects_empty_category(sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.post(
            "/miniapp/api/drinks",
            headers=headers,
            json={"category": "   ", "name": "Ред Булл", "rating": 6},
        )

    assert response.status_code == 400


async def test_add_drink_rejects_empty_name(sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.post(
            "/miniapp/api/drinks",
            headers=headers,
            json={"category": "чай", "name": "   ", "rating": 6},
        )

    assert response.status_code == 400


async def test_add_drink_rejects_out_of_range_rating(sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.post(
            "/miniapp/api/drinks",
            headers=headers,
            json={"category": "чай", "name": "Улун", "rating": 11},
        )

    assert response.status_code == 400


async def test_update_drink_changes_fields(session, sessionmaker):
    repo = DrinkReviewRepo(session)
    review = await _add(repo, chat_id=100, rating=5)
    await session.commit()
    review_id = review.id

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.patch(
            f"/miniapp/api/drinks/{review_id}",
            headers=headers,
            json={"rating": 9, "is_favorite": True},
        )

    assert response.status_code == 200
    session.expire_all()
    fetched = await repo.get(100, review_id)
    assert fetched.rating == 9
    assert fetched.is_favorite is True


async def test_update_drink_rejects_cross_chat_access(session, sessionmaker):
    repo = DrinkReviewRepo(session)
    review = await _add(repo, chat_id=100)
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=999)}

    async with _client(app) as client:
        response = await client.patch(
            f"/miniapp/api/drinks/{review.id}",
            headers=headers,
            json={"rating": 9},
        )

    assert response.status_code == 404
    fetched = await repo.get(100, review.id)
    assert fetched.rating == 7


async def test_update_drink_rejects_invalid_rating(session, sessionmaker):
    repo = DrinkReviewRepo(session)
    review = await _add(repo, chat_id=100)
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.patch(
            f"/miniapp/api/drinks/{review.id}",
            headers=headers,
            json={"rating": 0},
        )

    assert response.status_code == 400


async def test_delete_drink_removes_item(session, sessionmaker):
    repo = DrinkReviewRepo(session)
    review = await _add(repo, chat_id=100)
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.delete(
            f"/miniapp/api/drinks/{review.id}", headers=headers
        )

    assert response.status_code == 200
    assert await repo.get(100, review.id) is None


async def test_delete_drink_rejects_cross_chat_access(session, sessionmaker):
    repo = DrinkReviewRepo(session)
    review = await _add(repo, chat_id=100)
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=999)}

    async with _client(app) as client:
        response = await client.delete(
            f"/miniapp/api/drinks/{review.id}", headers=headers
        )

    assert response.status_code == 404
    assert await repo.get(100, review.id) is not None


async def test_delete_drink_rejects_unknown_id(sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.delete("/miniapp/api/drinks/999", headers=headers)

    assert response.status_code == 404


async def test_get_drinks_rejects_missing_init_data(sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())

    async with _client(app) as client:
        response = await client.get("/miniapp/api/drinks")

    assert response.status_code == 401
