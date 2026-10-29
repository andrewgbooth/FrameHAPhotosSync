"""Prepare photos for the Frame (3840x2160 JPEG) and make preview thumbnails."""

from __future__ import annotations

import io

from PIL import Image, ImageFilter, ImageOps

try:  # HEIC support is optional
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass

TV_W, TV_H = 3840, 2160


def _open(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def _jpeg(img: Image.Image, quality: int = 92) -> bytes:
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def prepare_for_tv(data: bytes, fit: str = "crop") -> tuple[bytes, bool]:
    """Return (jpeg_bytes, is_portrait).

    fit:
      crop - fill the 16:9 screen, centre-cropping landscape photos
      blur - fit the whole photo over a blurred copy of itself
      none - keep the photo's own aspect ratio (the TV matte frames it)
    Portrait photos are never forced to landscape; the TV's portrait matte is used.
    """
    img = _open(data)
    portrait = img.height > img.width

    if portrait or fit == "none":
        img.thumbnail((TV_W, TV_W) if not portrait else (TV_H, TV_W), Image.LANCZOS)
        return _jpeg(img), portrait

    if fit == "crop":
        out = ImageOps.fit(img, (TV_W, TV_H), Image.LANCZOS, centering=(0.5, 0.45))
        return _jpeg(out), False

    # blur
    bg = ImageOps.fit(img, (TV_W // 8, TV_H // 8), Image.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(6)).resize((TV_W, TV_H), Image.BILINEAR)
    fg = img.copy()
    fg.thumbnail((TV_W, TV_H), Image.LANCZOS)
    bg.paste(fg, ((TV_W - fg.width) // 2, (TV_H - fg.height) // 2))
    return _jpeg(bg), False


def thumbnail(data: bytes, size: int = 360) -> bytes:
    img = _open(data)
    img.thumbnail((size, size), Image.LANCZOS)
    return _jpeg(img, quality=80)
