from fastapi.testclient import TestClient

from app.main import create_app


async def _noop_check_me(self) -> None:
    return None


def test_healthz_returns_ok(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("DOMAIN", "example.com")
    monkeypatch.setenv("WEBHOOK_PATH", "/webhook")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("MODE", "webhook")
    monkeypatch.setenv("ADMIN_IDS", "1")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://maxhub:maxhub@localhost:5432/maxhub"
    )

    from maxapi.dispatcher import Dispatcher

    monkeypatch.setattr(Dispatcher, "check_me", _noop_check_me)

    async def _noop_sync_profile(bot):
        return None

    import app.main as main_module

    monkeypatch.setattr(main_module, "sync_bot_profile", _noop_sync_profile)

    from maxapi.bot import Bot

    async def _noop_subscribe_webhook(self, *args, **kwargs):
        return None

    monkeypatch.setattr(Bot, "subscribe_webhook", _noop_subscribe_webhook)

    from app.config import get_settings

    get_settings.cache_clear()

    app = create_app()

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
