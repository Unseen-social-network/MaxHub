import io

from PIL import Image as PILImage

SUPPORTED_FORMATS = frozenset({"png", "jpg", "webp", "pdf"})
MAX_INPUT_SIZE_BYTES = 20 * 1024 * 1024

_PIL_FORMAT_BY_EXTENSION = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP", "pdf": "PDF"}


def convert_image(data: bytes, target_format: str) -> bytes:
    if target_format not in SUPPORTED_FORMATS:
        raise ValueError(f"Неподдерживаемый формат: {target_format}")

    image = PILImage.open(io.BytesIO(data))
    image.load()

    if target_format in {"jpg", "pdf"} and image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")

    output = io.BytesIO()
    image.save(output, format=_PIL_FORMAT_BY_EXTENSION[target_format])
    return output.getvalue()
