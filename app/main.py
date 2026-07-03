import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from maxapi import Bot, Dispatcher
from maxapi.webhook.fastapi import FastAPIMaxWebhook

from app.config import get_settings
from app.db.engine import get_sessionmaker
from app.handlers.common import common_router
from app.handlers.todo import todo_router
from app.middlewares import ActivityMiddleware, LimiterMiddleware
from app.rate_limit import RateLimitedBot

logger = logging.getLogger(__name__)

BOT_NAME = "MaxHub"
BOT_DESCRIPTION = (
    'Совместные списки дел, "Слово дня" и конвертер файлов — всё в одном '
    "боте. /help — список команд."
)


def build_bot() -> Bot:
    return Bot(token=get_settings().bot_token)


def build_dispatcher(bot: Bot) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.register_outer_middleware(ActivityMiddleware(get_sessionmaker()))
    dispatcher.register_outer_middleware(LimiterMiddleware(RateLimitedBot(bot)))
    dispatcher.include_routers(common_router, todo_router)
    return dispatcher


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
    dispatcher = build_dispatcher(bot)
    webhook = FastAPIMaxWebhook(dp=dispatcher, bot=bot)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with webhook.lifespan(app):
            await sync_bot_profile(bot)
            webhook_url = f"https://{settings.domain}{settings.webhook_path}"
            await bot.subscribe_webhook(url=webhook_url)
            yield

    app = FastAPI(lifespan=lifespan)
    webhook.setup(app, path=settings.webhook_path)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def run_polling() -> None:
    bot = build_bot()
    dispatcher = build_dispatcher(bot)
    await sync_bot_profile(bot)
    await dispatcher.start_polling(bot)


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
