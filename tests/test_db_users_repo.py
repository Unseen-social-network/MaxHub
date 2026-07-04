from datetime import UTC, datetime, timedelta

from bot.db.models import User
from bot.db.repositories.users import UserRepo


async def test_touch_activity_creates_user(session):
    repo = UserRepo(session)

    await repo.touch_activity(user_id=1, is_dm=True)
    await session.commit()

    user = await session.get(User, 1)
    assert user is not None
    assert user.is_dm is True
    assert user.is_blocked is False


async def test_touch_activity_keeps_is_dm_true_once_set(session):
    repo = UserRepo(session)

    await repo.touch_activity(user_id=1, is_dm=True)
    await repo.touch_activity(user_id=1, is_dm=False)
    await session.commit()

    user = await session.get(User, 1)
    assert user.is_dm is True


async def test_mark_blocked(session):
    repo = UserRepo(session)
    await repo.touch_activity(user_id=1, is_dm=True)
    await session.commit()

    await repo.mark_blocked(user_id=1)
    await session.commit()

    user = await session.get(User, 1)
    assert user.is_blocked is True


async def test_get_active_recipients_filters_correctly(session):
    repo = UserRepo(session)

    await repo.touch_activity(user_id=1, is_dm=True)  # active DM, not blocked
    await repo.touch_activity(user_id=2, is_dm=False)  # never DM'd
    await repo.touch_activity(user_id=3, is_dm=True)
    await repo.mark_blocked(user_id=3)  # DM'd but blocked
    session.add(
        User(
            user_id=4,
            is_dm=True,
            is_blocked=False,
            last_activity_at=datetime.now(UTC) - timedelta(days=60),
        )
    )  # DM'd, active, but stale
    await session.commit()

    recipients = await repo.get_active_recipients(active_days=30)

    assert recipients == [1]
