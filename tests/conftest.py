import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import get_settings


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations():
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    yield
    command.downgrade(cfg, "base")


@pytest.fixture
async def sessionmaker() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


@pytest.fixture
async def session(sessionmaker: async_sessionmaker[AsyncSession]):
    async with sessionmaker() as s:
        yield s


@pytest.fixture(autouse=True)
async def _clean_tables(session: AsyncSession):
    yield
    for table in (
        "todos",
        "word_subscriptions",
        "broadcasts",
        "users",
        "drink_reviews",
    ):
        await session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
    await session.commit()
