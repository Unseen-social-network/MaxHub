from maxapi.enums.chat_type import ChatType
from maxapi.enums.upload_type import UploadType
from maxapi.types.attachments.attachment import PhotoAttachmentPayload
from maxapi.types.attachments.image import Image
from maxapi.types.attachments.upload import AttachmentPayload, AttachmentUpload
from maxapi.types.callback import Callback
from maxapi.types.message import Message, MessageBody, Recipient
from maxapi.types.updates.message_callback import MessageCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.types.users import User as MaxUser

import bot.handlers.converter as converter_module
from bot.handlers.converter import handle_conversion_callback, handle_image_message
from bot.services.converter import MAX_INPUT_SIZE_BYTES


class FakeLimiter:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.calls: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return None

    async def call(self, method_name, **kwargs):
        self.calls.append({"method": method_name, **kwargs})
        if method_name == "upload_media":
            return AttachmentUpload(
                type=UploadType.FILE, payload=AttachmentPayload(token="tok")
            )
        return None


def _make_image_event(chat_id: int, mid: str = "m1") -> MessageCreated:
    image = Image(
        type="image",
        payload=PhotoAttachmentPayload(
            photo_id=1, token="tok", url="https://example.com/i.png"
        ),
    )
    body = MessageBody(mid=mid, seq=1, text=None, attachments=[image])
    message = Message(
        sender=MaxUser(user_id=1, first_name="T", is_bot=False, last_activity_time=0),
        recipient=Recipient(user_id=1, chat_id=chat_id, chat_type=ChatType.CHAT),
        timestamp=0,
        body=body,
    )
    return MessageCreated(message=message, timestamp=0)


def _make_callback_event(chat_id: int, payload: str) -> MessageCallback:
    message = Message(
        sender=MaxUser(user_id=1, first_name="T", is_bot=False, last_activity_time=0),
        recipient=Recipient(user_id=1, chat_id=chat_id, chat_type=ChatType.CHAT),
        timestamp=0,
    )
    callback = Callback(
        timestamp=0,
        callback_id="cb1",
        payload=payload,
        user=MaxUser(user_id=1, first_name="T", is_bot=False, last_activity_time=0),
    )
    return MessageCallback(message=message, callback=callback, timestamp=0)


def _make_png_bytes() -> bytes:
    import io

    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (5, 5), color=(0, 255, 0)).save(buf, format="PNG")
    return buf.getvalue()


async def test_image_message_offers_format_buttons(monkeypatch):
    limiter = FakeLimiter()

    async def fake_download(event):
        return _make_png_bytes()

    monkeypatch.setattr(converter_module, "_download_image_bytes", fake_download)

    await handle_image_message(_make_image_event(100), limiter)

    assert limiter.sent
    assert "формат" in limiter.sent[0]["text"].lower()
    assert "m1" in converter_module._pending_conversions


async def test_image_message_rejects_oversized_file(monkeypatch):
    limiter = FakeLimiter()

    async def fake_too_big(event):
        return b"0" * (MAX_INPUT_SIZE_BYTES + 1)

    monkeypatch.setattr(converter_module, "_download_image_bytes", fake_too_big)

    await handle_image_message(_make_image_event(100, mid="m2"), limiter)

    assert "20" in limiter.sent[0]["text"]
    assert "m2" not in converter_module._pending_conversions


async def test_conversion_callback_converts_and_sends_file():
    limiter = FakeLimiter()
    converter_module._pending_conversions["m3"] = _make_png_bytes()

    event = _make_callback_event(100, "conv:png:m3")
    await handle_conversion_callback(event, limiter)

    method_names = [c["method"] for c in limiter.calls]
    assert "upload_media" in method_names
    assert "send_callback" in method_names
    assert "m3" not in converter_module._pending_conversions
