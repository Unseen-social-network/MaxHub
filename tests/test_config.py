import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_parses_admin_ids_from_comma_separated_string(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("DOMAIN", "example.com")
    monkeypatch.setenv("WEBHOOK_PATH", "/webhook")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("MODE", "webhook")
    monkeypatch.setenv("ADMIN_IDS", "111, 222,333")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

    settings = Settings()

    assert settings.admin_ids == [111, 222, 333]


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("DOMAIN", "example.com")
    monkeypatch.setenv("WEBHOOK_PATH", "/webhook")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("MODE", "polling")
    monkeypatch.setenv("ADMIN_IDS", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

    settings = Settings()

    assert settings.tz == "Europe/Moscow"
    assert settings.broadcast_active_days == 30
    assert settings.app_version == "dev"


def test_settings_rejects_invalid_mode(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("DOMAIN", "example.com")
    monkeypatch.setenv("WEBHOOK_PATH", "/webhook")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("MODE", "bogus")
    monkeypatch.setenv("ADMIN_IDS", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

    with pytest.raises(ValidationError):
        Settings()
