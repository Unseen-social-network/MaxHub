from app.db.repo.todos import TodoRepo


async def test_add_and_list_for_chat(session):
    repo = TodoRepo(session)

    await repo.add(chat_id=100, text="купить хлеб", created_by=1)
    await repo.add(chat_id=100, text="помыть окна", created_by=2)
    await repo.add(chat_id=200, text="другой чат", created_by=3)
    await session.commit()

    todos = await repo.list_for_chat(chat_id=100)

    assert [t.text for t in todos] == ["купить хлеб", "помыть окна"]
    assert all(t.is_done is False for t in todos)


async def test_mark_done(session):
    repo = TodoRepo(session)
    todo = await repo.add(chat_id=100, text="купить хлеб", created_by=1)
    await session.commit()

    updated = await repo.mark_done(chat_id=100, todo_id=todo.id)
    await session.commit()

    assert updated is True
    todos = await repo.list_for_chat(chat_id=100)
    assert todos[0].is_done is True


async def test_mark_done_wrong_chat_returns_false(session):
    repo = TodoRepo(session)
    todo = await repo.add(chat_id=100, text="купить хлеб", created_by=1)
    await session.commit()

    updated = await repo.mark_done(chat_id=999, todo_id=todo.id)

    assert updated is False


async def test_delete(session):
    repo = TodoRepo(session)
    todo = await repo.add(chat_id=100, text="купить хлеб", created_by=1)
    await session.commit()

    deleted = await repo.delete(chat_id=100, todo_id=todo.id)
    await session.commit()

    assert deleted is True
    assert await repo.list_for_chat(chat_id=100) == []
