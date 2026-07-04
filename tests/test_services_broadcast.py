from bot.db.models import Broadcast, User
from bot.db.repositories.users import UserRepo
from bot.services.broadcast import run_broadcast


class FakeLimiter:
    def __init__(self, fail_user_ids: set[int] | None = None) -> None:
        self.sent: list[dict] = []
        self._fail_user_ids = fail_user_ids or set()

    async def send_message(self, *, user_id=None, chat_id=None, **kwargs):
        if user_id in self._fail_user_ids:
            raise RuntimeError("delivery failed")
        self.sent.append({"user_id": user_id, "chat_id": chat_id, **kwargs})


class _SingleSessionCtx:
    def __init__(self, session) -> None:
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _session_factory(session):
    return _SingleSessionCtx(session)


async def test_run_broadcast_sends_only_to_active_recipients(session, monkeypatch):
    monkeypatch.setattr(
        "bot.services.broadcast.get_sessionmaker", lambda: _session_factory(session)
    )
    repo = UserRepo(session)
    await repo.touch_activity(user_id=1, is_dm=True)
    await repo.touch_activity(user_id=2, is_dm=False)
    await session.commit()
    session.add(Broadcast(id=99, admin_id=1, text="hi"))
    await session.commit()

    limiter = FakeLimiter()
    await run_broadcast(limiter, admin_chat_id=1, broadcast_id=99, text="hi")

    sent_to = {c["user_id"] for c in limiter.sent if c["user_id"] is not None}
    assert sent_to == {1}


async def test_run_broadcast_marks_failed_recipients_as_blocked(session, monkeypatch):
    monkeypatch.setattr(
        "bot.services.broadcast.get_sessionmaker", lambda: _session_factory(session)
    )
    repo = UserRepo(session)
    await repo.touch_activity(user_id=1, is_dm=True)
    await repo.touch_activity(user_id=2, is_dm=True)
    await session.commit()
    session.add(Broadcast(id=100, admin_id=1, text="hi"))
    await session.commit()

    limiter = FakeLimiter(fail_user_ids={2})
    await run_broadcast(limiter, admin_chat_id=1, broadcast_id=100, text="hi")

    blocked_user = await session.get(User, 2)
    ok_user = await session.get(User, 1)
    assert blocked_user.is_blocked is True
    assert ok_user.is_blocked is False


async def test_run_broadcast_updates_broadcast_counts(session, monkeypatch):
    monkeypatch.setattr(
        "bot.services.broadcast.get_sessionmaker", lambda: _session_factory(session)
    )
    repo = UserRepo(session)
    await repo.touch_activity(user_id=1, is_dm=True)
    await repo.touch_activity(user_id=2, is_dm=True)
    await session.commit()
    session.add(Broadcast(id=101, admin_id=1, text="hi"))
    await session.commit()

    limiter = FakeLimiter(fail_user_ids={2})
    await run_broadcast(limiter, admin_chat_id=1, broadcast_id=101, text="hi")

    broadcast = await session.get(Broadcast, 101)
    assert broadcast.sent_count == 1
    assert broadcast.failed_count == 1
