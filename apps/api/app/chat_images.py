from __future__ import annotations

import base64
import binascii
import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_CHAT_IMAGE_DATA_URL_CHARS = 3_000_000
MAX_CHAT_IMAGE_BYTES = 2_200_000
MAX_CHAT_IMAGE_PIXELS = 4_194_304
MAX_CHAT_IMAGE_EDGE = 2048


def normalize_chat_image(data_url: str) -> str:
    """Validate, orient, and strip metadata from a bounded browser image data URL."""
    if len(data_url) > MAX_CHAT_IMAGE_DATA_URL_CHARS:
        raise ValueError("A imagem ficou grande demais depois da preparação.")
    expected_formats = {
        "data:image/webp;base64,": "WEBP",
        "data:image/png;base64,": "PNG",
        "data:image/jpeg;base64,": "JPEG",
    }
    prefix = next(
        (candidate for candidate in expected_formats if data_url.startswith(candidate)), None
    )
    if prefix is None:
        raise ValueError("Formato de imagem não aceito para análise.")

    try:
        encoded = data_url[len(prefix) :]
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Não foi possível ler a imagem enviada.") from error
    if not raw or len(raw) > MAX_CHAT_IMAGE_BYTES:
        raise ValueError("A imagem preparada ultrapassa o limite permitido.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                if source.format != expected_formats[prefix]:
                    raise ValueError("O conteúdo enviado não corresponde ao formato da imagem.")
                width, height = source.size
                if width < 1 or height < 1 or width * height > MAX_CHAT_IMAGE_PIXELS:
                    raise ValueError("A imagem preparada excede a resolução permitida.")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("A imagem preparada excede a resolução permitida.") from error
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Não foi possível decodificar a imagem enviada.") from error

    image.thumbnail((MAX_CHAT_IMAGE_EDGE, MAX_CHAT_IMAGE_EDGE), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="WEBP", quality=88, method=4)
    normalized = base64.b64encode(output.getvalue()).decode("ascii")
    return prefix + normalized
