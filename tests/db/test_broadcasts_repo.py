from app.db.models import Broadcast
from app.db.repo.broadcasts import BroadcastRepo


async def test_create_starts_with_zero_counts(session):
    repo = BroadcastRepo(session)

    broadcast = await repo.create(admin_id=1, text="важное объявление")
    await session.commit()

    assert broadcast.id is not None
    assert broadcast.sent_count == 0
    assert broadcast.failed_count == 0


async def test_update_counts(session):
    repo = BroadcastRepo(session)
    broadcast = await repo.create(admin_id=1, text="важное объявление")
    await session.commit()

    await repo.update_counts(broadcast.id, sent_count=42, failed_count=3)
    await session.commit()

    refreshed = await session.get(Broadcast, broadcast.id)
    assert refreshed.sent_count == 42
    assert refreshed.failed_count == 3
