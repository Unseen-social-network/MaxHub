MIN_RATING = 1
MAX_RATING = 10

SORT_FIELDS = ("created_at", "rating", "name", "favorite")
SORT_ORDERS = ("asc", "desc")

DEFAULT_SORT = "created_at"
DEFAULT_ORDER = "desc"


class InvalidDrinkReview(ValueError):
    pass


def normalize_category(raw: str) -> str:
    return " ".join(raw.split()).lower()


def display_category(category: str) -> str:
    return category[:1].upper() + category[1:] if category else category


def validate_category(raw: str) -> str:
    category = normalize_category(raw)
    if not category:
        raise InvalidDrinkReview("Категория не может быть пустой")
    return category


def validate_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise InvalidDrinkReview("Название не может быть пустым")
    return name


def validate_note(raw: str | None) -> str:
    return (raw or "").strip()


def validate_rating(raw: int) -> int:
    if not MIN_RATING <= raw <= MAX_RATING:
        raise InvalidDrinkReview(f"Оценка должна быть от {MIN_RATING} до {MAX_RATING}")
    return raw


def validate_sort(value: str) -> str:
    if value not in SORT_FIELDS:
        raise InvalidDrinkReview(f"Недопустимая сортировка: {value}")
    return value


def validate_order(value: str) -> str:
    if value not in SORT_ORDERS:
        raise InvalidDrinkReview(f"Недопустимый порядок сортировки: {value}")
    return value
