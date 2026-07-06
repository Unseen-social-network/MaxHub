from maxapi import Router
from maxapi.context.base import BaseContext
from maxapi.context.state_machine import State, StatesGroup
from maxapi.filters.command import Command
from maxapi.filters.filter import BaseFilter
from maxapi.filters.state import StateFilter
from maxapi.types.attachments.buttons import CallbackButton, ClipboardButton
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.types.updates.message_callback import MessageCallback, MessageForCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import DrinkReview
from bot.db.repositories.drink_reviews import DrinkReviewRepo
from bot.services.drink_reviews import (
    DEFAULT_ORDER,
    DEFAULT_SORT,
    SORT_FIELDS,
    SORT_ORDERS,
    InvalidDrinkReview,
    display_category,
    normalize_category,
    validate_category,
    validate_name,
    validate_note,
)
from bot.services.rate_limit import RateLimitedBot

drinks_router = Router("drinks")

_CATEGORY_CHIP_LIMIT = 8

_SORT_LABELS = {
    "created_at": "🗓 Дата",
    "rating": "⭐ Оценка",
    "name": "🔤 Название",
    "favorite": "❤ Избранное",
}

DRINK_HELP_TEXT = (
    "🍹 Рецензии на напитки:\n"
    "/drink add — добавить рецензию (категория → название → описание → "
    "оценка → фаворит)\n"
    "/drink list [категория|fav] [sort:дата|оценка|название|избранное] "
    "[order:asc|desc] — список с фильтрами и сортировкой\n"
    "/drink search <текст> — поиск по названию, описанию и категории\n"
    "/drink fav — только избранное\n"
    "/drink del <id> — удалить рецензию по id\n"
    "/drink help — эта справка"
)

_SORT_ARG_ALIASES = {
    "дата": "created_at",
    "date": "created_at",
    "created_at": "created_at",
    "оценка": "rating",
    "rating": "rating",
    "название": "name",
    "name": "name",
    "избранное": "favorite",
    "favorite": "favorite",
}


class DrinkStates(StatesGroup):
    waiting_category = State()
    waiting_name = State()
    waiting_note = State()
    waiting_rating = State()
    waiting_favorite = State()


class IsDrinkCallback(BaseFilter):
    async def __call__(self, event: object) -> bool:
        if not isinstance(event, MessageCallback):
            return False
        payload = event.callback.payload or ""
        return payload.split(":")[0] == "drink"


class IsDrinkFsmRatingCallback(BaseFilter):
    async def __call__(self, event: object) -> bool:
        if not isinstance(event, MessageCallback):
            return False
        payload = event.callback.payload or ""
        return payload.startswith("drink_fsm:rating:")


class IsDrinkFsmFavoriteCallback(BaseFilter):
    async def __call__(self, event: object) -> bool:
        if not isinstance(event, MessageCallback):
            return False
        payload = event.callback.payload or ""
        return payload in {"drink_fsm:fav:yes", "drink_fsm:fav:no"}


def _back_to_commands_button() -> ClipboardButton:
    return ClipboardButton(text="🏠 К командам", payload="/help")


def _rating_keyboard() -> AttachmentButton:
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        *[
            CallbackButton(text=str(n), payload=f"drink_fsm:rating:{n}")
            for n in range(1, 6)
        ]
    )
    keyboard.row(
        *[
            CallbackButton(text=str(n), payload=f"drink_fsm:rating:{n}")
            for n in range(6, 11)
        ]
    )
    return keyboard.as_markup()


def _favorite_choice_keyboard() -> AttachmentButton:
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        CallbackButton(text="❤ Да, фаворит", payload="drink_fsm:fav:yes"),
        CallbackButton(text="Нет", payload="drink_fsm:fav:no"),
    )
    return keyboard.as_markup()


def _format_review_line(review: DrinkReview) -> str:
    heart = "❤ " if review.is_favorite else ""
    line = (
        f"#{review.id} {heart}{display_category(review.category)} — "
        f"{review.name} ({review.rating}/10)"
    )
    if review.note:
        line += f"\n   {review.note}"
    return line


async def _get_view(context: BaseContext) -> dict:
    data = await context.get_data()
    return {
        "category": data.get("drink_category"),
        "favorite": bool(data.get("drink_favorite", False)),
        "search": data.get("drink_search"),
        "sort": data.get("drink_sort", DEFAULT_SORT),
        "order": data.get("drink_order", DEFAULT_ORDER),
    }


async def _update_view(context: BaseContext, **overrides: object) -> None:
    await context.update_data(
        **{f"drink_{key}": value for key, value in overrides.items()}
    )


async def _reset_view(context: BaseContext, **overrides: object) -> None:
    view = {
        "category": None,
        "favorite": False,
        "search": None,
        "sort": DEFAULT_SORT,
        "order": DEFAULT_ORDER,
    }
    view.update(overrides)
    await _update_view(context, **view)


def _parse_list_args(args: list[str]) -> dict:
    overrides: dict = {}
    for arg in args:
        lowered = arg.lower()
        if lowered in {"fav", "favorite", "favorites"}:
            overrides["favorite"] = True
        elif lowered.startswith("sort:"):
            candidate = _SORT_ARG_ALIASES.get(lowered.split(":", 1)[1])
            if candidate is not None:
                overrides["sort"] = candidate
        elif lowered.startswith("order:"):
            candidate = lowered.split(":", 1)[1]
            if candidate in SORT_ORDERS:
                overrides["order"] = candidate
        else:
            overrides["category"] = normalize_category(arg)
    return overrides


async def _render_drink_list(
    chat_id: int, session: AsyncSession, context: BaseContext
) -> tuple[str, AttachmentButton]:
    view = await _get_view(context)
    repo = DrinkReviewRepo(session)
    reviews = await repo.list_for_chat(
        chat_id,
        category=view["category"],
        favorite=view["favorite"] or None,
        search=view["search"],
        sort=view["sort"],
        order=view["order"],
    )
    categories = await repo.list_categories(chat_id)

    header_bits = []
    if view["search"]:
        header_bits.append(f"поиск «{view['search']}»")
    if view["category"]:
        header_bits.append(f"категория «{display_category(view['category'])}»")
    if view["favorite"]:
        header_bits.append("только избранное")
    header = " · ".join(header_bits)

    keyboard = InlineKeyboardBuilder()

    if not reviews:
        text = "Рецензий пока нет" if not header else f"Ничего не найдено ({header})"
    else:
        lines = [_format_review_line(review) for review in reviews]
        text = (f"{header}\n\n" if header else "") + "\n".join(lines)
        for review in reviews:
            fav_label = "💔 Убрать" if review.is_favorite else "❤ В избранное"
            keyboard.row(
                CallbackButton(text=fav_label, payload=f"drink:fav:{review.id}"),
                CallbackButton(text="🗑", payload=f"drink:del:{review.id}"),
            )

    sort_buttons = [
        CallbackButton(
            text=("• " if view["sort"] == key else "") + label,
            payload=f"drink:sort:{key}",
        )
        for key, label in _SORT_LABELS.items()
    ]
    keyboard.row(*sort_buttons[:2])
    keyboard.row(*sort_buttons[2:])

    fav_toggle_label = ("✅" if view["favorite"] else "☆") + " Только избранное"
    keyboard.row(CallbackButton(text=fav_toggle_label, payload="drink:filter:favorite"))

    if categories:
        chips = [
            CallbackButton(
                text=("• " if view["category"] == category else "")
                + display_category(category),
                payload=f"drink:filter:category:{category}",
            )
            for category in categories[:_CATEGORY_CHIP_LIMIT]
        ]
        for i in range(0, len(chips), 2):
            keyboard.row(*chips[i : i + 2])
        if view["category"]:
            keyboard.row(
                CallbackButton(
                    text="✖ Сбросить категорию", payload="drink:filter:category"
                )
            )

    keyboard.row(_back_to_commands_button())

    return text, keyboard.as_markup()


@drinks_router.message_created(Command("drink"))
async def handle_drink(
    event: MessageCreated,
    args: list[str],
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return

    if not args or args[0].lower() == "help":
        await limiter.send_message(chat_id=chat_id, text=DRINK_HELP_TEXT)
        return

    subcommand, rest = args[0].lower(), args[1:]

    if subcommand == "add":
        await context.set_state(DrinkStates.waiting_category)
        await limiter.send_message(
            chat_id=chat_id,
            text="Введите категорию напитка (например: вино, пиво, чай, кофе...)",
        )
        return

    if subcommand == "list":
        await _reset_view(context, **_parse_list_args(rest))
        text, keyboard = await _render_drink_list(chat_id, session, context)
        await limiter.send_message(chat_id=chat_id, text=text, attachments=[keyboard])
        return

    if subcommand == "fav":
        await _reset_view(context, favorite=True)
        text, keyboard = await _render_drink_list(chat_id, session, context)
        await limiter.send_message(chat_id=chat_id, text=text, attachments=[keyboard])
        return

    if subcommand == "search":
        query = " ".join(rest).strip()
        if not query:
            await limiter.send_message(
                chat_id=chat_id, text="Укажите текст: /drink search <текст>"
            )
            return
        await _reset_view(context, search=query)
        text, keyboard = await _render_drink_list(chat_id, session, context)
        await limiter.send_message(chat_id=chat_id, text=text, attachments=[keyboard])
        return

    if subcommand == "del":
        if not rest or not rest[0].isdigit():
            await limiter.send_message(
                chat_id=chat_id, text="Использование: /drink del <id>"
            )
            return
        deleted = await DrinkReviewRepo(session).delete(chat_id, int(rest[0]))
        await session.commit()
        if not deleted:
            await limiter.send_message(
                chat_id=chat_id, text="Рецензия с таким id не найдена"
            )
            return
        text, keyboard = await _render_drink_list(chat_id, session, context)
        await limiter.send_message(
            chat_id=chat_id, text=f"Удалено.\n\n{text}", attachments=[keyboard]
        )
        return

    await limiter.send_message(chat_id=chat_id, text=DRINK_HELP_TEXT)


@drinks_router.message_created(StateFilter(DrinkStates.waiting_category))
async def handle_drink_fsm_category(
    event: MessageCreated, context: BaseContext, limiter: RateLimitedBot
) -> None:
    chat_id, _user_id = event.get_ids()
    text = event.message.body.text if event.message.body else None
    if chat_id is None:
        return

    try:
        category = validate_category(text or "")
    except InvalidDrinkReview as exc:
        await limiter.send_message(chat_id=chat_id, text=str(exc))
        return

    await context.update_data(drink_new_category=category)
    await context.set_state(DrinkStates.waiting_name)
    await limiter.send_message(chat_id=chat_id, text="Введите название напитка")


@drinks_router.message_created(StateFilter(DrinkStates.waiting_name))
async def handle_drink_fsm_name(
    event: MessageCreated, context: BaseContext, limiter: RateLimitedBot
) -> None:
    chat_id, _user_id = event.get_ids()
    text = event.message.body.text if event.message.body else None
    if chat_id is None:
        return

    try:
        name = validate_name(text or "")
    except InvalidDrinkReview as exc:
        await limiter.send_message(chat_id=chat_id, text=str(exc))
        return

    await context.update_data(drink_new_name=name)
    await context.set_state(DrinkStates.waiting_note)
    await limiter.send_message(
        chat_id=chat_id,
        text="Добавьте описание/заметку одним сообщением (или «-», чтобы пропустить)",
    )


@drinks_router.message_created(StateFilter(DrinkStates.waiting_note))
async def handle_drink_fsm_note(
    event: MessageCreated, context: BaseContext, limiter: RateLimitedBot
) -> None:
    chat_id, _user_id = event.get_ids()
    text = event.message.body.text if event.message.body else None
    if chat_id is None:
        return

    note = "" if text is None or text.strip() == "-" else validate_note(text)
    await context.update_data(drink_new_note=note)
    await context.set_state(DrinkStates.waiting_rating)
    await limiter.send_message(
        chat_id=chat_id,
        text="Поставьте оценку от 1 до 10",
        attachments=[_rating_keyboard()],
    )


@drinks_router.message_callback(
    StateFilter(DrinkStates.waiting_rating), IsDrinkFsmRatingCallback()
)
async def handle_drink_fsm_rating(
    event: MessageCallback, context: BaseContext, limiter: RateLimitedBot
) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return

    payload = event.callback.payload or ""
    raw_rating = payload.rsplit(":", 1)[1]
    if not raw_rating.isdigit() or not 1 <= int(raw_rating) <= 10:
        return

    await context.update_data(drink_new_rating=int(raw_rating))
    await context.set_state(DrinkStates.waiting_favorite)
    await limiter.call(
        "send_callback",
        limit_key=chat_id,
        callback_id=event.callback.callback_id,
        message=MessageForCallback(
            text="Это напиток-фаворит?", attachments=[_favorite_choice_keyboard()]
        ),
    )


@drinks_router.message_created(StateFilter(DrinkStates.waiting_rating))
async def handle_drink_fsm_rating_text_fallback(
    event: MessageCreated, limiter: RateLimitedBot
) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return
    await limiter.send_message(
        chat_id=chat_id,
        text="Выберите оценку кнопкой выше",
        attachments=[_rating_keyboard()],
    )


@drinks_router.message_callback(
    StateFilter(DrinkStates.waiting_favorite), IsDrinkFsmFavoriteCallback()
)
async def handle_drink_fsm_favorite(
    event: MessageCallback,
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    chat_id, user_id = event.get_ids()
    if chat_id is None:
        return

    data = await context.get_data()
    category = data.get("drink_new_category")
    name = data.get("drink_new_name")
    rating = data.get("drink_new_rating")
    note = data.get("drink_new_note", "")

    if category is None or name is None or rating is None:
        await context.clear()
        await limiter.call(
            "send_callback",
            limit_key=chat_id,
            callback_id=event.callback.callback_id,
            message=MessageForCallback(
                text="Что-то пошло не так, начните заново: /drink add"
            ),
        )
        return

    is_favorite = event.callback.payload == "drink_fsm:fav:yes"
    review = await DrinkReviewRepo(session).add(
        chat_id,
        category=category,
        name=name,
        note=note,
        rating=rating,
        created_by=user_id or 0,
        is_favorite=is_favorite,
    )
    await session.commit()
    await context.clear()

    await limiter.call(
        "send_callback",
        limit_key=chat_id,
        callback_id=event.callback.callback_id,
        message=MessageForCallback(text=f"Сохранено: {_format_review_line(review)}"),
    )


@drinks_router.message_created(StateFilter(DrinkStates.waiting_favorite))
async def handle_drink_fsm_favorite_text_fallback(
    event: MessageCreated, limiter: RateLimitedBot
) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return
    await limiter.send_message(
        chat_id=chat_id,
        text="Выберите вариант кнопкой выше",
        attachments=[_favorite_choice_keyboard()],
    )


@drinks_router.message_callback(IsDrinkCallback())
async def handle_drink_list_callback(
    event: MessageCallback,
    session: AsyncSession,
    context: BaseContext,
    limiter: RateLimitedBot,
) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return

    payload = event.callback.payload or ""
    parts = payload.split(":", 3)

    if len(parts) == 3 and parts[1] == "fav" and parts[2].isdigit():
        review_id = int(parts[2])
        review = await DrinkReviewRepo(session).get(chat_id, review_id)
        if review is not None:
            await DrinkReviewRepo(session).set_favorite(
                chat_id, review_id, not review.is_favorite
            )
            await session.commit()
    elif len(parts) == 3 and parts[1] == "del" and parts[2].isdigit():
        await DrinkReviewRepo(session).delete(chat_id, int(parts[2]))
        await session.commit()
    elif len(parts) == 3 and parts[1] == "sort" and parts[2] in SORT_FIELDS:
        await _update_view(context, sort=parts[2])
    elif len(parts) >= 3 and parts[1] == "filter" and parts[2] == "favorite":
        view = await _get_view(context)
        await _update_view(context, favorite=not view["favorite"])
    elif len(parts) >= 3 and parts[1] == "filter" and parts[2] == "category":
        category = parts[3] if len(parts) > 3 else None
        await _update_view(context, category=category)
    else:
        return

    text, keyboard = await _render_drink_list(chat_id, session, context)
    await limiter.call(
        "send_callback",
        limit_key=chat_id,
        callback_id=event.callback.callback_id,
        message=MessageForCallback(text=text, attachments=[keyboard]),
    )
