import time
from dataclasses import dataclass, field

import pytest
from maxapi.exceptions.max import MaxApiError, MaxConnection

from app.rate_limit import RateLimitedBot


@dataclass
class FakeBot:
    calls: list[tuple[str, dict]] = field(default_factory=list)
    fail_times: int = 0
    fail_with: Exception | None = None

    async def send_message(self, **kwargs):
        self.calls.append(("send_message", kwargs))
        return {"ok": True}

    async def noop(self, **kwargs):
        self.calls.append(("noop", kwargs))
        return "done"

    async def flaky(self, **kwargs):
        self.calls.append(("flaky", kwargs))
        if len(self.calls) <= self.fail_times:
            raise self.fail_with
        return "recovered"


async def test_send_message_to_same_chat_is_throttled_to_two_per_second():
    fake = FakeBot()
    limiter = RateLimitedBot(fake, chat_rate=2, chat_period=1.0)

    start = time.monotonic()
    for _ in range(5):
        await limiter.send_message(chat_id=100, text="hi")
    elapsed = time.monotonic() - start

    assert len(fake.calls) == 5
    assert elapsed >= 1.5  # 5 msgs at 2/s take ~2s; allow scheduling slack


async def test_global_limit_is_respected_across_different_chats():
    fake = FakeBot()
    limiter = RateLimitedBot(fake, global_rate=3, global_period=1.0, chat_rate=100)

    start = time.monotonic()
    for chat_id in range(6):
        await limiter.send_message(chat_id=chat_id, text="hi")
    elapsed = time.monotonic() - start

    assert len(fake.calls) == 6
    assert elapsed >= 1.0  # 6 calls at global 3/s take >=1s beyond the first burst


async def test_call_without_limit_key_only_uses_global_limiter():
    fake = FakeBot()
    limiter = RateLimitedBot(fake, global_rate=100, chat_rate=1, chat_period=1.0)

    start = time.monotonic()
    for _ in range(5):
        await limiter.call("noop", limit_key=None)
    elapsed = time.monotonic() - start

    assert len(fake.calls) == 5
    assert elapsed < 0.5  # no per-chat throttling applied when limit_key is None


async def test_retries_on_429_then_succeeds():
    fake = FakeBot(fail_times=2, fail_with=MaxApiError(code=429, raw={}))
    limiter = RateLimitedBot(fake, base_delay=0.01, max_delay=0.05)

    result = await limiter.call("flaky", limit_key=None)

    assert result == "recovered"
    assert len(fake.calls) == 3


async def test_retries_on_connection_error_then_succeeds():
    fake = FakeBot(fail_times=1, fail_with=MaxConnection("boom"))
    limiter = RateLimitedBot(fake, base_delay=0.01, max_delay=0.05)

    result = await limiter.call("flaky", limit_key=None)

    assert result == "recovered"
    assert len(fake.calls) == 2


async def test_gives_up_after_max_retries():
    fake = FakeBot(fail_times=10, fail_with=MaxApiError(code=429, raw={}))
    limiter = RateLimitedBot(fake, max_retries=2, base_delay=0.01, max_delay=0.05)

    with pytest.raises(MaxApiError):
        await limiter.call("flaky", limit_key=None)

    assert len(fake.calls) == 3  # initial attempt + 2 retries


async def test_non_retryable_error_propagates_immediately():
    fake = FakeBot(fail_times=10, fail_with=MaxApiError(code=400, raw={}))
    limiter = RateLimitedBot(fake, base_delay=0.01, max_delay=0.05)

    with pytest.raises(MaxApiError):
        await limiter.call("flaky", limit_key=None)

    assert len(fake.calls) == 1
