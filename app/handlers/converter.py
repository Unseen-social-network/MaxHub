import asyncio

from maxapi import Router
from maxapi.filters.filter import BaseFilter
from maxapi.types.attachments.buttons import CallbackButton
from maxapi.types.attachments.image import Image
from maxapi.types.input_media import InputMediaBuffer
from maxapi.types.updates.message_callback import MessageCallback, MessageForCallback
from maxapi.types.updates.message_created import MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from app.rate_limit import RateLimitedBot
from app.services.converter import (
    MAX_INPUT_SIZE_BYTES,
    SUPPORTED_FORMATS,
    convert_image,
)

converter_router = Router("converter")

_pending_conversions: dict[str, bytes] = {}


class HasImageAttachment(BaseFilter):
    async def __call__(self, event: object) -> bool:
        if not isinstance(event, MessageCreated):
            return False
        body = event.message.body
        if body is None or not body.attachments:
            return False
        return any(isinstance(a, Image) for a in body.attachments)


async def _download_image_bytes(event: MessageCreated) -> bytes:
    image = next(a for a in event.message.body.attachments if isinstance(a, Image))
    bot = event._ensure_bot()  # noqa: SLF001
    return await bot.download_bytes(image.payload.url)


@converter_router.message_created(HasImageAttachment())
async def handle_image_message(event: MessageCreated, limiter: RateLimitedBot) -> None:
    chat_id, _user_id = event.get_ids()
    if chat_id is None:
        return

    data = await _download_image_bytes(event)

    if len(data) > MAX_INPUT_SIZE_BYTES:
        await limiter.send_message(
            chat_id=chat_id,
            text="Файл слишком большой. Максимальный размер — 20 МБ.",
        )
        return

    mid = event.message.body.mid
    _pending_conversions[mid] = data

    keyboard = InlineKeyboardBuilder()
    for fmt in sorted(SUPPORTED_FORMATS):
        keyboard.add(CallbackButton(text=fmt.upper(), payload=f"conv:{fmt}:{mid}"))
    keyboard.adjust(len(SUPPORTED_FORMATS))

    await limiter.send_message(
        chat_id=chat_id,
        text="Выберите формат для конвертации:",
        attachments=[keyboard.as_markup()],
    )


@converter_router.message_callback()
async def handle_conversion_callback(
    event: MessageCallback, limiter: RateLimitedBot
) -> None:
    payload = event.callback.payload or ""
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != "conv":
        return

    target_format, mid = parts[1], parts[2]
    chat_id, _user_id = event.get_ids()
    data = _pending_conversions.pop(mid, None)
    if chat_id is None or data is None:
        return

    converted = await asyncio.to_thread(convert_image, data, target_format)

    upload = await limiter.call(
        "upload_media",
        limit_key=chat_id,
        media=InputMediaBuffer(
            buffer=converted,
            filename=f"converted.{target_format}",
            type="file",
        ),
    )

    await limiter.call(
        "send_callback",
        limit_key=chat_id,
        callback_id=event.callback.callback_id,
        message=MessageForCallback(text="Готово!", attachments=[upload]),
    )
