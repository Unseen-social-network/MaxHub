import asyncio
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from maxapi import Bot, Dispatcher
from maxapi.webhook.fastapi import FastAPIMaxWebhook

from bot.config import get_settings
from bot.db.session import get_sessionmaker
from bot.handlers.admin import admin_router
from bot.handlers.common import common_router
from bot.handlers.converter import converter_router
from bot.handlers.todo import todo_router
from bot.handlers.word_of_day import word_of_day_router
from bot.middlewares.activity import ActivityMiddleware
from bot.middlewares.limiter import LimiterMiddleware
from bot.services.rate_limit import RateLimitedBot
from bot.services.word_of_day import broadcast_daily_word

logger = logging.getLogger(__name__)

BOT_NAME = "MaxHub"
BOT_DESCRIPTION = (
    'Совместные списки дел, "Слово дня" и конвертер файлов — всё в одном '
    "боте. /help — список команд."
)


def build_bot() -> Bot:
    return Bot(token=get_settings().bot_token)


def build_dispatcher(bot: Bot) -> tuple[Dispatcher, RateLimitedBot]:
    dispatcher = Dispatcher()
    dispatcher.register_outer_middleware(ActivityMiddleware(get_sessionmaker()))
    limiter = RateLimitedBot(bot)
    dispatcher.register_outer_middleware(LimiterMiddleware(limiter))
    dispatcher.include_routers(
        common_router,
        todo_router,
        word_of_day_router,
        converter_router,
        admin_router,
    )
    return dispatcher, limiter


def build_scheduler(limiter: RateLimitedBot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=get_settings().tz)
    scheduler.add_job(
        broadcast_daily_word,
        "cron",
        hour=9,
        minute=0,
        args=[limiter],
        id="daily_word",
    )
    return scheduler


async def sync_bot_profile(bot: Bot) -> None:
    try:
        await bot.change_info(
            first_name=BOT_NAME,
            description=BOT_DESCRIPTION,
        )
    except Exception:
        logger.warning(
            "Не удалось синхронизировать имя/описание бота при старте",
            exc_info=True,
        )


def create_app() -> FastAPI:
    settings = get_settings()
    bot = build_bot()
    dispatcher, limiter = build_dispatcher(bot)
    scheduler = build_scheduler(limiter)
    webhook = FastAPIMaxWebhook(dp=dispatcher, bot=bot)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with webhook.lifespan(app):
            await sync_bot_profile(bot)
            webhook_url = f"https://{settings.domain}{settings.webhook_path}"
            await bot.subscribe_webhook(url=webhook_url)
            scheduler.start()
            try:
                yield
            finally:
                scheduler.shutdown()

    app = FastAPI(lifespan=lifespan)
    webhook.setup(app, path=settings.webhook_path)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def run_polling() -> None:
    bot = build_bot()
    dispatcher, limiter = build_dispatcher(bot)
    scheduler = build_scheduler(limiter)
    await sync_bot_profile(bot)
    scheduler.start()
    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()

    if settings.mode == "polling":
        asyncio.run(run_polling())
        return

    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
