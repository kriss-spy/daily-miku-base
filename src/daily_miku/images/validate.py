"""Decode, bound, and normalize untrusted raster image bytes."""

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

MAX_INPUT_BYTES = 4_000_000
MAX_OUTPUT_BYTES = 4_000_000
MAX_DIMENSION = 8_192
MAX_PIXELS = 40_000_000
SUPPORTED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})


class UnsafeImage(ValueError):
    """Submitted bytes violate the controlled raster policy."""


@dataclass(frozen=True)
class NormalizedImage:
    """Metadata and deterministic bytes established by successful decoding."""

    data: bytes
    content_type: str
    extension: str
    source_format: str
    width: int
    height: int


def normalize_raster(data: bytes) -> NormalizedImage:
    """Decode one static raster, strip metadata, and re-encode it as PNG."""
    if not data or len(data) > MAX_INPUT_BYTES:
        raise UnsafeImage("Image bytes must be non-empty and no larger than 4 MB.")
    try:
        with Image.open(BytesIO(data)) as source:
            source_format = source.format
            if source_format not in SUPPORTED_FORMATS:
                raise UnsafeImage(
                    "Only JPEG, PNG, and WebP raster images are supported."
                )
            width, height = source.size
            if width <= 0 or height <= 0:
                raise UnsafeImage("Image dimensions must be positive.")
            if width > MAX_DIMENSION or height > MAX_DIMENSION:
                raise UnsafeImage("Image dimensions exceed the 8192 pixel limit.")
            if width * height > MAX_PIXELS:
                raise UnsafeImage("Image pixel count exceeds the safety limit.")
            if getattr(source, "n_frames", 1) != 1 or getattr(
                source, "is_animated", False
            ):
                raise UnsafeImage("Animated images are not supported.")
            source.load()
            mode = "RGBA" if "A" in source.getbands() else "RGB"
            pixels = source.convert(mode)
    except UnsafeImage:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise UnsafeImage(
            "The file is not a decodable supported raster image."
        ) from exc

    output = BytesIO()
    pixels.save(output, format="PNG", optimize=False, compress_level=9)
    normalized = output.getvalue()
    if len(normalized) > MAX_OUTPUT_BYTES:
        raise UnsafeImage("The normalized image exceeds the 4 MB storage limit.")
    return NormalizedImage(normalized, "image/png", "png", source_format, width, height)
