import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InvalidInitData(Exception):
    pass


@dataclass
class InitDataUser:
    id: int
    first_name: str
    last_name: str | None
    username: str | None


@dataclass
class InitDataChat:
    id: int
    type: str


@dataclass
class InitData:
    query_id: str
    auth_date: int
    user: InitDataUser | None
    chat: InitDataChat | None
    start_param: str | None


def verify_init_data(raw: str, bot_token: str, max_age_seconds: int = 3600) -> InitData:
    """Проверяет подпись initData из MAX Bridge.

    Формула из документации dev.max.ru/docs/webapps/bridge: HMAC_SHA256 от
    отсортированных по алфавиту пар key=value (кроме hash и version),
    объединённых через "\n", ключ — токен бота напрямую (без промежуточного
    secret key, в отличие от Telegram WebApp).
    """
    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InvalidInitData("Отсутствует hash")

    pairs.pop("version", None)

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(pairs.items())
    )
    computed_hash = hmac.new(
        bot_token.encode("utf-8"), data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise InvalidInitData("Неверная подпись initData")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise InvalidInitData("Некорректный auth_date") from exc

    if time.time() - auth_date > max_age_seconds:
        raise InvalidInitData("initData устарела")

    user = None
    if pairs.get("user"):
        user_data = json.loads(pairs["user"])
        user = InitDataUser(
            id=user_data["id"],
            first_name=user_data.get("first_name", ""),
            last_name=user_data.get("last_name"),
            username=user_data.get("username"),
        )

    chat = None
    if pairs.get("chat"):
        chat_data = json.loads(pairs["chat"])
        chat = InitDataChat(id=chat_data["id"], type=chat_data["type"])

    return InitData(
        query_id=pairs.get("query_id", ""),
        auth_date=auth_date,
        user=user,
        chat=chat,
        start_param=pairs.get("start_param") or None,
    )
