from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str
    max_api_url: str = "https://platform-api2.max.ru"
    domain: str
    webhook_path: str
    miniapp_path: str = "/miniapp"
    port: int
    mode: Literal["webhook", "polling"]
    admin_ids: Annotated[list[int], NoDecode]
    database_url: str
    tz: str = "Europe/Moscow"
    broadcast_active_days: int = 30
    app_version: str = "dev"
    git_sha: str = "unknown"
    build_time: str = "unknown"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
