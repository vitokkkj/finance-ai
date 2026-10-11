from __future__ import annotations

import base64
from io import BytesIO

import pytest
from PIL import Image

from app.chat_images import normalize_chat_image


def _webp_data_url(width: int, height: int) -> str:
    image = Image.new("RGB", (width, height), color=(245, 245, 245))
    output = BytesIO()
    image.save(output, format="WEBP")
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def test_chat_image_is_reencoded_as_webp_without_exceeding_edge_limit() -> None:
    normalized = normalize_chat_image(_webp_data_url(2048, 1024))
    image_bytes = base64.b64decode(normalized.split(",", 1)[1], validate=True)

    with Image.open(BytesIO(image_bytes)) as image:
        assert image.format == "WEBP"
        assert image.size == (2048, 1024)


@pytest.mark.parametrize(
    "value",
    [
        "data:image/png;base64,AAAA",
        "data:image/webp;base64,not-base64",
        "data:image/webp;base64,",
    ],
)
def test_chat_image_rejects_invalid_data_urls(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_chat_image(value)


def test_chat_image_rejects_dimensions_above_decoded_pixel_limit() -> None:
    with pytest.raises(ValueError, match="resolução permitida"):
        normalize_chat_image(_webp_data_url(2049, 2048))
