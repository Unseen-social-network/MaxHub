from maxapi.context.context import MemoryContext
from maxapi.enums.chat_type import ChatType
from maxapi.types.callback import Callback
from maxapi.types.message import Message, MessageBody, Recipient
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser

from bot.db.repositories.drink_reviews import DrinkReviewRepo
from bot.handlers.drinks import (
    DrinkStates,
    IsDrinkCallback,
    IsDrinkFsmFavoriteCallback,
    IsDrinkFsmRatingCallback,
    handle_drink,
    handle_drink_fsm_category,
    handle_drink_fsm_favorite,
    handle_drink_fsm_name,
    handle_drink_fsm_note,
    handle_drink_fsm_rating,
    handle_drink_list_callback,
)


class FakeLimiter:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.calls: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return None

    async def call(self, method_name, **kwargs):
        self.calls.append({"method": method_name, **kwargs})
        return None


def _make_message_event(
    chat_id: int, user_id: int = 1, text: str | None = None
) -> MessageCreated:
    message = Message(
        sender=MaxUser(
            user_id=user_id, first_name="T", is_bot=False, last_activity_time=0
        ),
        recipient=Recipient(user_id=user_id, chat_id=chat_id, chat_type=ChatType.CHAT),
        timestamp=0,
    )
    if text is not None:
        message.body = MessageBody(mid="m1", seq=1, text=text)
    return MessageCreated(message=message, timestamp=0)


def _make_callback_event(
    chat_id: int, payload: str, user_id: int = 1
) -> MessageCallback:
    message = Message(
        sender=MaxUser(
            user_id=user_id, first_name="T", is_bot=False, last_activity_time=0
        ),
        recipient=Recipient(user_id=user_id, chat_id=chat_id, chat_type=ChatType.CHAT),
        timestamp=0,
    )
    callback = Callback(
        timestamp=0,
        callback_id="cb1",
        payload=payload,
        user=MaxUser(
            user_id=user_id, first_name="T", is_bot=False, last_activity_time=0
        ),
    )
    return MessageCallback(message=message, callback=callback, timestamp=0)


async def test_bare_drink_shows_help(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)

    await handle_drink(_make_message_event(100), [], session, context, limiter)

    assert "рецензии" in limiter.sent[0]["text"].lower()


async def test_drink_help_subcommand_shows_help(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)

    await handle_drink(_make_message_event(100), ["help"], session, context, limiter)

    assert "/drink add" in limiter.sent[0]["text"]


async def test_drink_add_starts_fsm(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)

    await handle_drink(_make_message_event(100), ["add"], session, context, limiter)

    assert await context.get_state() == DrinkStates.waiting_category
    assert "категор" in limiter.sent[0]["text"].lower()


async def test_fsm_category_step_rejects_empty(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    await context.set_state(DrinkStates.waiting_category)

    event = _make_message_event(100, text="   ")
    await handle_drink_fsm_category(event, context, limiter)

    assert await context.get_state() == DrinkStates.waiting_category
    assert "пуст" in limiter.sent[0]["text"].lower()


async def test_fsm_category_step_normalizes_and_advances(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    await context.set_state(DrinkStates.waiting_category)

    event = _make_message_event(100, text="  ВИНО  ")
    await handle_drink_fsm_category(event, context, limiter)

    assert await context.get_state() == DrinkStates.waiting_name
    data = await context.get_data()
    assert data["drink_new_category"] == "вино"


async def test_full_add_flow_creates_review(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=7)

    await context.set_state(DrinkStates.waiting_category)
    await handle_drink_fsm_category(
        _make_message_event(100, user_id=7, text="Вино"), context, limiter
    )

    await handle_drink_fsm_name(
        _make_message_event(100, user_id=7, text="  Мерло  "), context, limiter
    )

    await handle_drink_fsm_note(
        _make_message_event(100, user_id=7, text="-"), context, limiter
    )
    assert await context.get_state() == DrinkStates.waiting_rating

    rating_event = _make_callback_event(100, "drink_fsm:rating:9", user_id=7)
    await handle_drink_fsm_rating(rating_event, context, limiter)
    assert await context.get_state() == DrinkStates.waiting_favorite

    fav_event = _make_callback_event(100, "drink_fsm:fav:yes", user_id=7)
    await handle_drink_fsm_favorite(fav_event, session, context, limiter)

    assert await context.get_state() is None
    reviews = await DrinkReviewRepo(session).list_for_chat(100)
    assert len(reviews) == 1
    review = reviews[0]
    assert review.category == "вино"
    assert review.name == "Мерло"
    assert review.note == ""
    assert review.rating == 9
    assert review.is_favorite is True
    assert review.created_by == 7


async def test_drink_list_renders_items_and_buttons(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    repo = DrinkReviewRepo(session)
    await repo.add(100, category="вино", name="Мерло", note="", rating=8, created_by=1)
    await session.commit()

    await handle_drink(_make_message_event(100), ["list"], session, context, limiter)

    assert "Мерло" in limiter.sent[0]["text"]
    buttons = [
        b for row in limiter.sent[0]["attachments"][0].payload.buttons for b in row
    ]
    payloads = {b.payload for b in buttons}
    assert any(p.startswith("drink:fav:") for p in payloads)
    assert any(p.startswith("drink:del:") for p in payloads)
    assert "drink:filter:category:вино" in payloads


async def test_drink_list_filters_by_category_arg(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    repo = DrinkReviewRepo(session)
    await repo.add(100, category="вино", name="Мерло", note="", rating=8, created_by=1)
    await repo.add(100, category="пиво", name="Лагер", note="", rating=6, created_by=1)
    await session.commit()

    await handle_drink(
        _make_message_event(100), ["list", "вино"], session, context, limiter
    )

    text = limiter.sent[0]["text"]
    assert "Мерло" in text
    assert "Лагер" not in text


async def test_drink_search_command(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    repo = DrinkReviewRepo(session)
    await repo.add(100, category="вино", name="Мерло", note="", rating=8, created_by=1)
    await repo.add(100, category="пиво", name="Лагер", note="", rating=6, created_by=1)
    await session.commit()

    await handle_drink(
        _make_message_event(100), ["search", "мерло"], session, context, limiter
    )

    text = limiter.sent[0]["text"]
    assert "Мерло" in text
    assert "Лагер" not in text


async def test_drink_search_requires_text(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)

    await handle_drink(_make_message_event(100), ["search"], session, context, limiter)

    assert "укажите" in limiter.sent[0]["text"].lower()


async def test_drink_fav_command_filters_favorites(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    repo = DrinkReviewRepo(session)
    await repo.add(
        100,
        category="вино",
        name="Любимое",
        note="",
        rating=8,
        created_by=1,
        is_favorite=True,
    )
    await repo.add(
        100, category="пиво", name="Обычное", note="", rating=6, created_by=1
    )
    await session.commit()

    await handle_drink(_make_message_event(100), ["fav"], session, context, limiter)

    text = limiter.sent[0]["text"]
    assert "Любимое" in text
    assert "Обычное" not in text


async def test_drink_del_removes_review(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    repo = DrinkReviewRepo(session)
    review = await repo.add(
        100, category="вино", name="Мерло", note="", rating=8, created_by=1
    )
    await session.commit()

    await handle_drink(
        _make_message_event(100), ["del", str(review.id)], session, context, limiter
    )

    assert await repo.get(100, review.id) is None


async def test_drink_del_unknown_id_reports_not_found(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)

    await handle_drink(
        _make_message_event(100), ["del", "999"], session, context, limiter
    )

    assert "не найдена" in limiter.sent[0]["text"].lower()


async def test_list_callback_toggles_favorite(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    repo = DrinkReviewRepo(session)
    review = await repo.add(
        100, category="вино", name="Мерло", note="", rating=8, created_by=1
    )
    await session.commit()

    event = _make_callback_event(100, f"drink:fav:{review.id}")
    await handle_drink_list_callback(event, session, context, limiter)

    fetched = await repo.get(100, review.id)
    assert fetched.is_favorite is True


async def test_list_callback_deletes_review(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    repo = DrinkReviewRepo(session)
    review = await repo.add(
        100, category="вино", name="Мерло", note="", rating=8, created_by=1
    )
    await session.commit()

    event = _make_callback_event(100, f"drink:del:{review.id}")
    await handle_drink_list_callback(event, session, context, limiter)

    assert await repo.get(100, review.id) is None


async def test_list_callback_sort_updates_view(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)

    event = _make_callback_event(100, "drink:sort:rating")
    await handle_drink_list_callback(event, session, context, limiter)

    data = await context.get_data()
    assert data["drink_sort"] == "rating"


async def test_list_callback_category_filter_with_colon_in_category(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)

    event = _make_callback_event(100, "drink:filter:category:вино крепкое")
    await handle_drink_list_callback(event, session, context, limiter)

    data = await context.get_data()
    assert data["drink_category"] == "вино крепкое"


async def test_list_callback_category_reset(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)
    await context.update_data(drink_category="вино")

    event = _make_callback_event(100, "drink:filter:category")
    await handle_drink_list_callback(event, session, context, limiter)

    data = await context.get_data()
    assert data["drink_category"] is None


async def test_list_callback_favorite_filter_toggle(session):
    limiter = FakeLimiter()
    context = MemoryContext(chat_id=100, user_id=1)

    event = _make_callback_event(100, "drink:filter:favorite")
    await handle_drink_list_callback(event, session, context, limiter)

    data = await context.get_data()
    assert data["drink_favorite"] is True


async def test_is_drink_callback_rejects_fsm_and_other_routers_payloads():
    is_drink = IsDrinkCallback()

    assert await is_drink(_make_callback_event(100, "drink:fav:1")) is True
    assert await is_drink(_make_callback_event(100, "drink_fsm:rating:5")) is False
    assert await is_drink(_make_callback_event(100, "todo:done:1")) is False
    assert await is_drink(_make_callback_event(100, "conv:png:m1")) is False


async def test_is_drink_fsm_rating_callback_only_matches_rating_payloads():
    is_rating = IsDrinkFsmRatingCallback()

    assert await is_rating(_make_callback_event(100, "drink_fsm:rating:7")) is True
    assert await is_rating(_make_callback_event(100, "drink:fav:1")) is False
    assert await is_rating(_make_callback_event(100, "drink_fsm:fav:yes")) is False


async def test_is_drink_fsm_favorite_callback_only_matches_yes_no():
    is_favorite = IsDrinkFsmFavoriteCallback()

    assert await is_favorite(_make_callback_event(100, "drink_fsm:fav:yes")) is True
    assert await is_favorite(_make_callback_event(100, "drink_fsm:fav:no")) is True
    assert await is_favorite(_make_callback_event(100, "drink_fsm:rating:5")) is False
