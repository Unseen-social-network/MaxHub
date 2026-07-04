from typing import Any

from maxapi.filters.middleware import BaseMiddleware, HandlerCallable
from maxapi.types.updates import UpdateUnion

from bot.services.rate_limit import RateLimitedBot


class LimiterMiddleware(BaseMiddleware):
    def __init__(self, limiter: RateLimitedBot) -> None:
        self._limiter = limiter

    async def __call__(
        self,
        handler: HandlerCallable,
        event_object: UpdateUnion,
        data: dict[str, Any],
    ) -> Any:
        data["limiter"] = self._limiter
        return await handler(event_object, data)
