"""Prepare photos for the Frame: exactly 3840x2160 (16:9), sRGB, baseline JPEG, size-capped.

Everything (orientation, colour space, crop/fit, compression) is done here so the TV is
only ever handed a plain, conformant file.
"""

from __future__ import annotations

import io

from PIL import Image, ImageCms, ImageEnhance, ImageFilter, ImageOps

try:  # HEIC support is optional
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass

TV_W, TV_H = 3840, 2160
MAX_BYTES = 4 * 1024 * 1024
QUALITIES = (92, 88, 84, 80, 75, 70, 65, 60)
_SRGB = ImageCms.createProfile("sRGB")


def _to_srgb(img: Image.Image) -> Image.Image:
    """Convert from the photo's embedded profile (e.g. iPhone Display P3) to sRGB."""
    icc = img.info.get("icc_profile")
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            img = ImageCms.profileToProfile(img, src, _SRGB, outputMode="RGB")
        except (ImageCms.PyCMSError, OSError, ValueError):
            pass
    return img


def _open(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGBA" if "A" in img.mode else "RGB")
    img = _to_srgb(img)
    if img.mode == "RGBA":  # flatten transparency onto black
        bg = Image.new("RGB", img.size, "black")
        bg.paste(img, mask=img.split()[3])
        img = bg
    return img.convert("RGB")


def _jpeg(img: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    # baseline (non-progressive), 4:2:0, no EXIF/ICC: the most widely accepted form
    img.save(out, "JPEG", quality=quality, progressive=False, subsampling=2, optimize=False)
    return out.getvalue()


def encode_capped(img: Image.Image, max_bytes: int = MAX_BYTES) -> bytes:
    data = b""
    for q in QUALITIES:
        data = _jpeg(img, q)
        if len(data) <= max_bytes:
            break
    return data


def _best_window(img: Image.Image, crop_w: int, crop_h: int) -> tuple[int, int]:
    """Top-left of the ``crop_w x crop_h`` window with the most detail (a cheap saliency
    guess that keeps faces/subjects over empty sky or floor), biased towards the centre."""
    w, h = img.size
    scale = 160 / max(w, h)
    small = img.convert("L").resize((max(1, round(w * scale)), max(1, round(h * scale))))
    edges = small.filter(ImageFilter.FIND_EDGES)
    sw, sh = small.size
    cw, ch = max(1, round(crop_w * scale)), max(1, round(crop_h * scale))
    px = edges.load()
    if sh > ch:  # trim vertically
        rows = [sum(px[x, y] for x in range(sw)) for y in range(sh)]
        best = _scan(rows, ch, sh)
        return 0, min(h - crop_h, round(best / scale))
    cols = [sum(px[x, y] for y in range(sh)) for x in range(sw)]
    best = _scan(cols, cw, sw)
    return min(w - crop_w, round(best / scale)), 0


def _scan(profile: list[int], window: int, total: int) -> int:
    centre = (total - window) / 2
    best, best_score = 0, -1.0
    csum = [0]
    for v in profile:
        csum.append(csum[-1] + v)
    for start in range(0, total - window + 1):
        energy = csum[start + window] - csum[start]
        penalty = 1 - 0.25 * abs(start - centre) / max(centre, 1)  # gentle pull to the middle
        if energy * penalty > best_score:
            best, best_score = start, energy * penalty
    return best


def _crop_to_tv(img: Image.Image) -> Image.Image:
    w, h = img.size
    target = TV_W / TV_H
    if w / h > target:  # too wide: trim the sides
        crop_w, crop_h = round(h * target), h
    else:  # too tall (or exact): trim top/bottom
        crop_w, crop_h = w, round(w / target)
    x, y = _best_window(img, crop_w, crop_h) if (crop_w, crop_h) != (w, h) else (0, 0)
    return img.crop((x, y, x + crop_w, y + crop_h)).resize((TV_W, TV_H), Image.LANCZOS)


def _blur_fit_to_tv(img: Image.Image) -> Image.Image:
    bg = ImageOps.fit(img, (TV_W // 8, TV_H // 8), Image.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(6)).resize((TV_W, TV_H), Image.BILINEAR)
    bg = ImageEnhance.Brightness(bg).enhance(0.7)  # darken so the photo stands out
    fg = img.copy()
    fg.thumbnail((TV_W, TV_H), Image.LANCZOS)
    bg.paste(fg, ((TV_W - fg.width) // 2, (TV_H - fg.height) // 2))
    return bg


def prepare_for_tv(data: bytes, fit: str = "crop", portrait_fit: str = "blur") -> bytes:
    """Return a 3840x2160 JPEG.

    fit:          "crop" fills the screen; "blur" fits the whole photo over a blurred copy.
    portrait_fit: the same choice, applied only to portrait photos (which lose a lot when
                  cropped to landscape, so "blur" is the default).
    """
    img = _open(data)
    mode = portrait_fit if img.height > img.width else fit
    out = _blur_fit_to_tv(img) if mode == "blur" else _crop_to_tv(img)
    return encode_capped(out)


def thumbnail(data: bytes, size: int = 360) -> bytes:
    img = _open(data)
    img.thumbnail((size, size), Image.LANCZOS)
    return _jpeg(img, 80)
