import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from bot.miniapp.auth import InvalidInitData, verify_init_data

BOT_TOKEN = "test-bot-token"


def _sign(params: dict) -> str:
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac.new(
        BOT_TOKEN.encode("utf-8"), data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _build_raw_init_data(**overrides) -> str:
    params = {
        "query_id": "abc123",
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            {"id": 42, "first_name": "Test", "last_name": "User", "username": "tuser"}
        ),
        "chat": json.dumps({"id": 100, "type": "CHAT"}),
        "start_param": "",
    }
    params.update(overrides)
    params["hash"] = _sign(params)
    return urlencode(params)


def test_verify_init_data_accepts_correctly_signed_payload():
    raw = _build_raw_init_data()

    result = verify_init_data(raw, BOT_TOKEN)

    assert result.user is not None
    assert result.user.id == 42
    assert result.user.username == "tuser"
    assert result.chat is not None
    assert result.chat.id == 100
    assert result.chat.type == "CHAT"


def test_verify_init_data_rejects_tampered_payload():
    raw = _build_raw_init_data()
    # tamper the chat id inside the already-signed payload without re-signing
    tampered = raw.replace("100", "999")

    with pytest.raises(InvalidInitData):
        verify_init_data(tampered, BOT_TOKEN)


def test_verify_init_data_rejects_wrong_bot_token():
    raw = _build_raw_init_data()

    with pytest.raises(InvalidInitData):
        verify_init_data(raw, "a-different-bot-token")


def test_verify_init_data_rejects_missing_hash():
    params = {"query_id": "abc123", "auth_date": str(int(time.time()))}
    raw = urlencode(params)

    with pytest.raises(InvalidInitData):
        verify_init_data(raw, BOT_TOKEN)


def test_verify_init_data_rejects_stale_auth_date():
    stale_time = int(time.time()) - 7200
    raw = _build_raw_init_data(auth_date=str(stale_time))

    with pytest.raises(InvalidInitData):
        verify_init_data(raw, BOT_TOKEN, max_age_seconds=3600)


def test_verify_init_data_works_without_chat_context():
    raw = _build_raw_init_data(chat="")

    result = verify_init_data(raw, BOT_TOKEN)

    assert result.chat is None
    assert result.user is not None
