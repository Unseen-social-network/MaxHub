from app.middlewares import LimiterMiddleware
from app.rate_limit import RateLimitedBot


async def test_injects_limiter_into_handler_data():
    limiter = RateLimitedBot(bot=object())
    middleware = LimiterMiddleware(limiter)
    seen = {}

    async def handler(event_object, data):
        seen["limiter"] = data.get("limiter")
        return "ok"

    result = await middleware(handler, event_object=None, data={})

    assert result == "ok"
    assert seen["limiter"] is limiter
