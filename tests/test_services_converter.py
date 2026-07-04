import io

import pytest
from PIL import Image as PILImage

from bot.services.converter import SUPPORTED_FORMATS, convert_image


def _make_png_bytes() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGBA", (10, 10), color=(255, 0, 0, 128)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize("target_format", sorted(SUPPORTED_FORMATS - {"pdf"}))
def test_convert_image_produces_valid_output(target_format):
    source = _make_png_bytes()

    result = convert_image(source, target_format)

    out = PILImage.open(io.BytesIO(result))
    out.load()
    expected_pil_format = "JPEG" if target_format == "jpg" else target_format.upper()
    assert out.format == expected_pil_format


def test_convert_image_to_pdf_produces_pdf_bytes():
    source = _make_png_bytes()

    result = convert_image(source, "pdf")

    assert result.startswith(b"%PDF-")


def test_convert_image_rejects_unsupported_format():
    source = _make_png_bytes()

    with pytest.raises(ValueError):
        convert_image(source, "bmp")


def test_convert_image_to_jpg_drops_alpha_without_error():
    source = _make_png_bytes()  # RGBA source

    result = convert_image(source, "jpg")

    out = PILImage.open(io.BytesIO(result))
    assert out.mode in {"RGB", "L"}
