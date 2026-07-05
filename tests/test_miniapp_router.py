import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx2
from fastapi import FastAPI

from bot.config import get_settings
from bot.db.repositories.todos import TodoRepo
from bot.db.repositories.users import UserRepo
from bot.db.repositories.word_subscriptions import WordSubscriptionRepo
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


async def test_get_todos_returns_chat_scoped_list(session, sessionmaker):
    await TodoRepo(session).add(chat_id=100, text="купить хлеб", created_by=1)
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get("/miniapp/api/todos", headers=headers)

    assert response.status_code == 200
    todos = response.json()["todos"]
    assert len(todos) == 1
    assert todos[0]["text"] == "купить хлеб"
    assert todos[0]["is_done"] is False


async def test_add_todo_creates_item_scoped_to_chat(session, sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.post(
            "/miniapp/api/todos", headers=headers, json={"text": "купить хлеб"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "купить хлеб"
    assert body["is_done"] is False

    todos = await TodoRepo(session).list_for_chat(100)
    assert len(todos) == 1
    assert todos[0].text == "купить хлеб"
    assert todos[0].created_by == 1


async def test_add_todo_rejects_empty_text(sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.post(
            "/miniapp/api/todos", headers=headers, json={"text": "   "}
        )

    assert response.status_code == 400


async def test_get_todos_rejects_missing_init_data(sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())

    async with _client(app) as client:
        response = await client.get("/miniapp/api/todos")

    assert response.status_code == 401


async def test_get_word_reports_subscription_state(session, sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get("/miniapp/api/word", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert "word" in body and "definition" in body and "example" in body
    assert body["subscribed"] is False


async def test_subscribe_and_unsubscribe_word(session, sessionmaker):
    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        sub_response = await client.post("/miniapp/api/word/subscribe", headers=headers)
        assert sub_response.json() == {"subscribed": True}
        assert await WordSubscriptionRepo(session).is_subscribed(100) is True

        unsub_response = await client.post(
            "/miniapp/api/word/unsubscribe", headers=headers
        )
        assert unsub_response.json() == {"subscribed": False}
        assert await WordSubscriptionRepo(session).is_subscribed(100) is False


async def test_broadcast_summary_rejects_non_admin(sessionmaker, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "999")
    get_settings.cache_clear()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get("/miniapp/api/broadcast/summary", headers=headers)

    assert response.status_code == 403
    get_settings.cache_clear()


async def test_broadcast_summary_reports_active_recipients(
    session, sessionmaker, monkeypatch
):
    monkeypatch.setenv("ADMIN_IDS", "1")
    get_settings.cache_clear()

    await UserRepo(session).touch_activity(user_id=5, is_dm=True)
    await session.commit()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.get("/miniapp/api/broadcast/summary", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"active_recipients": 1}
    get_settings.cache_clear()


async def test_send_broadcast_creates_row_and_starts_background_task(
    session, sessionmaker, monkeypatch
):
    monkeypatch.setenv("ADMIN_IDS", "1")
    get_settings.cache_clear()

    limiter = FakeLimiter()
    app = _make_app(sessionmaker, limiter)
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.post(
            "/miniapp/api/broadcast",
            headers=headers,
            json={"text": "важное объявление"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "started"}
    get_settings.cache_clear()


async def test_send_broadcast_rejects_empty_text(sessionmaker, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1")
    get_settings.cache_clear()

    app = _make_app(sessionmaker, FakeLimiter())
    headers = {"X-Init-Data": _init_data_header(user_id=1, chat_id=100)}

    async with _client(app) as client:
        response = await client.post(
            "/miniapp/api/broadcast", headers=headers, json={"text": "   "}
        )

    assert response.status_code == 400
    get_settings.cache_clear()
