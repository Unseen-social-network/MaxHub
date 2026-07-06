import pytest

from bot.services.drink_reviews import (
    InvalidDrinkReview,
    display_category,
    normalize_category,
    validate_category,
    validate_name,
    validate_note,
    validate_order,
    validate_rating,
    validate_sort,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Вино", "вино"),
        (" вино  ", "вино"),
        ("ВИНО", "вино"),
        ("  энергетики   напитки ", "энергетики напитки"),
    ],
)
def test_normalize_category(raw, expected):
    assert normalize_category(raw) == expected


def test_display_category_capitalizes_first_letter():
    assert display_category("вино") == "Вино"
    assert display_category("") == ""


def test_validate_category_rejects_empty_and_whitespace():
    with pytest.raises(InvalidDrinkReview):
        validate_category("   ")


def test_validate_category_normalizes():
    assert validate_category(" ВИНО ") == "вино"


def test_validate_name_rejects_empty():
    with pytest.raises(InvalidDrinkReview):
        validate_name("   ")


def test_validate_name_strips_and_collapses_whitespace():
    assert validate_name("  Мерло   Резерв ") == "Мерло Резерв"


def test_validate_note_allows_empty():
    assert validate_note(None) == ""
    assert validate_note("") == ""
    assert validate_note("  ") == ""


def test_validate_note_strips_but_keeps_internal_formatting():
    assert validate_note("  строка1\nстрока2  ") == "строка1\nстрока2"


@pytest.mark.parametrize("rating", [1, 5, 10])
def test_validate_rating_accepts_in_range(rating):
    assert validate_rating(rating) == rating


@pytest.mark.parametrize("rating", [0, -1, 11, 100])
def test_validate_rating_rejects_out_of_range(rating):
    with pytest.raises(InvalidDrinkReview):
        validate_rating(rating)


def test_validate_sort_accepts_known_fields():
    for field in ("created_at", "rating", "name", "favorite"):
        assert validate_sort(field) == field


def test_validate_sort_rejects_unknown_field():
    with pytest.raises(InvalidDrinkReview):
        validate_sort("price")


def test_validate_order_accepts_asc_desc():
    assert validate_order("asc") == "asc"
    assert validate_order("desc") == "desc"


def test_validate_order_rejects_unknown_value():
    with pytest.raises(InvalidDrinkReview):
        validate_order("random")
