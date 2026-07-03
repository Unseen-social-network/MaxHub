from app.db.repo.word_subscriptions import WordSubscriptionRepo


async def test_subscribe_and_is_subscribed(session):
    repo = WordSubscriptionRepo(session)

    await repo.subscribe(chat_id=100)
    await session.commit()

    assert await repo.is_subscribed(chat_id=100) is True
    assert await repo.is_subscribed(chat_id=200) is False


async def test_subscribe_is_idempotent(session):
    repo = WordSubscriptionRepo(session)

    await repo.subscribe(chat_id=100)
    await repo.subscribe(chat_id=100)
    await session.commit()

    assert await repo.list_chat_ids() == [100]


async def test_unsubscribe(session):
    repo = WordSubscriptionRepo(session)
    await repo.subscribe(chat_id=100)
    await session.commit()

    await repo.unsubscribe(chat_id=100)
    await session.commit()

    assert await repo.is_subscribed(chat_id=100) is False


async def test_list_chat_ids(session):
    repo = WordSubscriptionRepo(session)
    await repo.subscribe(chat_id=100)
    await repo.subscribe(chat_id=200)
    await session.commit()

    assert sorted(await repo.list_chat_ids()) == [100, 200]
