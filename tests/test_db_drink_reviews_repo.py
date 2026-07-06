from bot.db.repositories.drink_reviews import DrinkReviewRepo


async def _add(repo, chat_id=100, **overrides):
    fields = {
        "category": "вино",
        "name": "Мерло",
        "note": "",
        "rating": 7,
        "created_by": 1,
    }
    fields.update(overrides)
    return await repo.add(chat_id, **fields)


async def test_add_and_list_for_chat_is_scoped(session):
    repo = DrinkReviewRepo(session)

    await _add(repo, chat_id=100, name="Мерло")
    await _add(repo, chat_id=100, name="Совиньон")
    await _add(repo, chat_id=200, name="Чужой чат")
    await session.commit()

    reviews = await repo.list_for_chat(100)

    assert {r.name for r in reviews} == {"Мерло", "Совиньон"}


async def test_list_categories_returns_only_used_categories_for_chat(session):
    repo = DrinkReviewRepo(session)

    await _add(repo, chat_id=100, category="вино")
    await _add(repo, chat_id=100, category="пиво")
    await _add(repo, chat_id=200, category="чай")
    await session.commit()

    categories = await repo.list_categories(100)

    assert categories == ["вино", "пиво"]


async def test_filter_by_category(session):
    repo = DrinkReviewRepo(session)

    await _add(repo, category="вино", name="Мерло")
    await _add(repo, category="пиво", name="Лагер")
    await session.commit()

    reviews = await repo.list_for_chat(100, category="пиво")

    assert [r.name for r in reviews] == ["Лагер"]


async def test_search_matches_name(session):
    repo = DrinkReviewRepo(session)
    await _add(repo, name="Особый Мерло")
    await _add(repo, name="Совиньон Блан")
    await session.commit()

    reviews = await repo.list_for_chat(100, search="мерло")

    assert [r.name for r in reviews] == ["Особый Мерло"]


async def test_search_matches_note(session):
    repo = DrinkReviewRepo(session)
    await _add(repo, name="A", note="отличный вкус ванили")
    await _add(repo, name="B", note="кисловатый")
    await session.commit()

    reviews = await repo.list_for_chat(100, search="ванил")

    assert [r.name for r in reviews] == ["A"]


async def test_search_matches_category(session):
    repo = DrinkReviewRepo(session)
    await _add(repo, name="A", category="энергетики")
    await _add(repo, name="B", category="чай")
    await session.commit()

    reviews = await repo.list_for_chat(100, search="энерг")

    assert [r.name for r in reviews] == ["A"]


async def test_sort_by_rating(session):
    repo = DrinkReviewRepo(session)
    await _add(repo, name="Низкий", rating=3)
    await _add(repo, name="Высокий", rating=9)
    await session.commit()

    reviews = await repo.list_for_chat(100, sort="rating", order="desc")

    assert [r.name for r in reviews] == ["Высокий", "Низкий"]

    reviews_asc = await repo.list_for_chat(100, sort="rating", order="asc")
    assert [r.name for r in reviews_asc] == ["Низкий", "Высокий"]


async def test_sort_by_name(session):
    repo = DrinkReviewRepo(session)
    await _add(repo, name="Бета")
    await _add(repo, name="Альфа")
    await session.commit()

    reviews = await repo.list_for_chat(100, sort="name", order="asc")

    assert [r.name for r in reviews] == ["Альфа", "Бета"]


async def test_sort_by_created_at_default_is_newest_first(session):
    repo = DrinkReviewRepo(session)
    first = await _add(repo, name="Первый")
    await session.commit()
    second = await _add(repo, name="Второй")
    await session.commit()

    reviews = await repo.list_for_chat(100)

    assert [r.id for r in reviews] == [second.id, first.id]


async def test_sort_by_favorite_bubbles_favorites_first(session):
    repo = DrinkReviewRepo(session)
    await _add(repo, name="Обычный", is_favorite=False)
    await _add(repo, name="Любимый", is_favorite=True)
    await session.commit()

    reviews = await repo.list_for_chat(100, sort="favorite", order="desc")

    assert reviews[0].name == "Любимый"


async def test_favorite_filter_only_returns_favorites(session):
    repo = DrinkReviewRepo(session)
    await _add(repo, name="Обычный", is_favorite=False)
    await _add(repo, name="Любимый", is_favorite=True)
    await session.commit()

    reviews = await repo.list_for_chat(100, favorite=True)

    assert [r.name for r in reviews] == ["Любимый"]


async def test_set_favorite_toggle(session):
    repo = DrinkReviewRepo(session)
    review = await _add(repo, is_favorite=False)
    await session.commit()

    updated = await repo.set_favorite(100, review.id, True)
    await session.commit()

    assert updated is True
    fetched = await repo.get(100, review.id)
    assert fetched.is_favorite is True


async def test_set_favorite_wrong_chat_returns_false(session):
    repo = DrinkReviewRepo(session)
    review = await _add(repo, chat_id=100)
    await session.commit()

    updated = await repo.set_favorite(999, review.id, True)

    assert updated is False


async def test_delete_scoped_to_chat(session):
    repo = DrinkReviewRepo(session)
    review = await _add(repo, chat_id=100)
    await session.commit()

    deleted_wrong_chat = await repo.delete(999, review.id)
    assert deleted_wrong_chat is False

    deleted = await repo.delete(100, review.id)
    await session.commit()

    assert deleted is True
    assert await repo.get(100, review.id) is None


async def test_update_fields_partial(session):
    repo = DrinkReviewRepo(session)
    review = await _add(repo, rating=5, note="старая заметка")
    await session.commit()

    updated = await repo.update_fields(100, review.id, rating=8)
    await session.commit()

    assert updated is True
    fetched = await repo.get(100, review.id)
    assert fetched.rating == 8
    assert fetched.note == "старая заметка"
