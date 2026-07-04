import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from bot.db.repositories.word_subscriptions import WordSubscriptionRepo
from bot.db.session import get_sessionmaker
from bot.services.rate_limit import RateLimitedBot

DEFAULT_WORDS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "words.json"
)


@lru_cache
def _load_words_cached(path_str: str) -> tuple[dict, ...]:
    with open(path_str, encoding="utf-8") as f:
        return tuple(json.load(f))


def load_words(path: Path | None = None) -> list[dict]:
    return list(_load_words_cached(str(path or DEFAULT_WORDS_PATH)))


def pick_word_for_date(target_date: date, words: list[dict]) -> dict:
    index = target_date.toordinal() % len(words)
    return words[index]


def format_word_message(word: dict) -> str:
    return (
        f"📖 Слово дня: {word['word']}\n\n"
        f"{word['definition']}\n\n"
        f"Пример: {word['example']}"
    )


async def broadcast_daily_word(limiter: RateLimitedBot) -> None:
    words = load_words()
    message = format_word_message(pick_word_for_date(date.today(), words))

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        chat_ids = await WordSubscriptionRepo(session).list_chat_ids()

    for chat_id in chat_ids:
        await limiter.send_message(chat_id=chat_id, text=message)
