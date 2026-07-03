from datetime import date

from app.services.word_of_day import (
    format_word_message,
    load_words,
    pick_word_for_date,
)


def test_load_words_returns_thirty_entries():
    words = load_words()
    assert len(words) == 30
    assert all({"word", "definition", "example"} <= set(w) for w in words)


def test_pick_word_for_date_is_deterministic():
    words = load_words()
    d = date(2026, 3, 15)

    first = pick_word_for_date(d, words)
    second = pick_word_for_date(d, words)

    assert first == second
    assert first in words


def test_pick_word_for_date_varies_by_day():
    words = load_words()

    word_a = pick_word_for_date(date(2026, 1, 1), words)
    word_b = pick_word_for_date(date(2026, 1, 2), words)

    assert word_a != word_b or len(words) == 1


def test_format_word_message_includes_all_fields():
    word = {
        "word": "абрис",
        "definition": "контур предмета",
        "example": "Абрис здания.",
    }

    message = format_word_message(word)

    assert "абрис" in message
    assert "контур предмета" in message
    assert "Абрис здания." in message
