import asyncio
import random
import time
from typing import Any

from aiolimiter import AsyncLimiter
from maxapi.exceptions.max import MaxApiError, MaxConnection


class _ChatLimiterRegistry:
    def __init__(self, rate: float, period: float, ttl: float) -> None:
        self._rate = rate
        self._period = period
        self._ttl = ttl
        self._limiters: dict[int, AsyncLimiter] = {}
        self._last_used: dict[int, float] = {}

    def get(self, key: int) -> AsyncLimiter:
        self._evict_stale()
        self._last_used[key] = time.monotonic()
        if key not in self._limiters:
            self._limiters[key] = AsyncLimiter(self._rate, self._period)
        return self._limiters[key]

    def _evict_stale(self) -> None:
        now = time.monotonic()
        stale_keys = [
            key
            for key, last_used in self._last_used.items()
            if now - last_used > self._ttl
        ]
        for key in stale_keys:
            self._limiters.pop(key, None)
            self._last_used.pop(key, None)


class RateLimitedBot:
    def __init__(
        self,
        bot: Any,
        *,
        global_rate: float = 30,
        global_period: float = 1.0,
        chat_rate: float = 2,
        chat_period: float = 1.0,
        chat_ttl: float = 600.0,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self._bot = bot
        self._global_limiter = AsyncLimiter(global_rate, global_period)
        self._chat_limiters = _ChatLimiterRegistry(chat_rate, chat_period, chat_ttl)
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

    async def call(
        self, method_name: str, *, limit_key: int | None = None, **kwargs: Any
    ) -> Any:
        await self._global_limiter.acquire()
        if limit_key is not None:
            await self._chat_limiters.get(limit_key).acquire()

        method = getattr(self._bot, method_name)
        return await self._call_with_retry(method, **kwargs)

    async def send_message(
        self,
        *,
        chat_id: int | None = None,
        user_id: int | None = None,
        **kwargs: Any,
    ) -> Any:
        limit_key = chat_id if chat_id is not None else user_id
        return await self.call(
            "send_message",
            limit_key=limit_key,
            chat_id=chat_id,
            user_id=user_id,
            **kwargs,
        )

    async def _call_with_retry(self, method: Any, **kwargs: Any) -> Any:
        attempt = 0
        while True:
            try:
                return await method(**kwargs)
            except MaxApiError as exc:
                if exc.code != 429 or attempt >= self._max_retries:
                    raise
            except MaxConnection:
                if attempt >= self._max_retries:
                    raise

            delay = min(self._base_delay * (2**attempt), self._max_delay)
            delay += random.uniform(0, delay * 0.1)
            await asyncio.sleep(delay)
            attempt += 1
