import io
import random

from PIL import Image, ImageCms, ImageDraw, ImageStat

from app import imaging
from app.imaging import MAX_BYTES, TV_H, TV_W, prepare_for_tv, thumbnail


def jpeg(w, h, color="blue", **kw):
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "JPEG", **kw)
    return b.getvalue()


def noisy(w, h):
    rnd = random.Random(1)
    img = Image.frombytes("RGB", (w, h), bytes(rnd.randrange(256) for _ in range(w * h * 3)))
    b = io.BytesIO()
    img.save(b, "JPEG", quality=95)
    return b.getvalue()


def check_tv_file(data):
    img = Image.open(io.BytesIO(data))
    assert img.format == "JPEG" and img.size == (TV_W, TV_H) and img.mode == "RGB"
    assert not img.info.get("progressive") and not img.info.get("progression")
    assert "exif" not in img.info and "icc_profile" not in img.info
    assert len(data) <= MAX_BYTES
    return img


def test_every_shape_and_mode_gives_exact_16_9_baseline_jpeg():
    shapes = [(1200, 1200), (1000, 2000), (6000, 3000), (4000, 3000), (3000, 4000), (5000, 1000), (3840, 2160)]
    for w, h in shapes:
        for fit in ("crop", "blur"):
            for pfit in ("crop", "blur"):
                check_tv_file(prepare_for_tv(jpeg(w, h), fit, pfit))


def test_portrait_uses_portrait_fit_and_landscape_uses_fit():
    # blur keeps the whole portrait with dark side bars; crop fills edge to edge
    portrait = jpeg(1000, 2000, "white")
    blur = Image.open(io.BytesIO(prepare_for_tv(portrait, "crop", "blur")))
    crop = Image.open(io.BytesIO(prepare_for_tv(portrait, "blur", "crop")))
    assert blur.getpixel((20, 1000))[0] < 200      # side bar is blurred/darkened, not white
    assert crop.getpixel((20, 1000))[0] > 240      # full-bleed white


def test_file_size_capped_for_noisy_photos():
    data = prepare_for_tv(noisy(1500, 1000), "crop", "crop")
    check_tv_file(data)


def test_display_p3_converted_to_srgb_and_profile_stripped():
    p3 = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))  # stand-in non-trivial profile
    b = io.BytesIO()
    Image.new("RGB", (400, 300), (200, 30, 30)).save(b, "JPEG", icc_profile=p3.tobytes())
    check_tv_file(prepare_for_tv(b.getvalue()))


def test_exif_orientation_is_applied():
    img = Image.new("RGB", (400, 200), "white")  # stored landscape, EXIF says rotate -> portrait
    exif = Image.Exif()
    exif[0x0112] = 6
    b = io.BytesIO()
    img.save(b, "JPEG", exif=exif)
    out = Image.open(io.BytesIO(prepare_for_tv(b.getvalue(), "crop", "blur")))
    assert out.getpixel((20, 1000))[0] < 200  # treated as portrait -> blurred side bars


def test_smart_crop_keeps_the_detailed_region():
    # tall photo: plain top, detailed bottom -> the crop should land at the bottom
    img = Image.new("RGB", (1600, 2400), (120, 120, 120))
    d = ImageDraw.Draw(img)
    for i in range(0, 1600, 40):
        d.rectangle([i, 1700, i + 20, 2400], fill=(255, 255, 255))
    b = io.BytesIO()
    img.save(b, "JPEG")
    out = Image.open(io.BytesIO(prepare_for_tv(b.getvalue(), "crop", "crop")))
    # bottom-weighted window has stripes (high variance); a centre crop would be mostly grey
    assert ImageStat.Stat(out.convert("L").resize((64, 36))).mean[0] > 150


def test_thumbnail():
    assert max(Image.open(io.BytesIO(thumbnail(jpeg(3000, 2000)))).size) == 360


def test_alpha_png_flattened():
    b = io.BytesIO()
    Image.new("RGBA", (600, 400), (255, 0, 0, 0)).save(b, "PNG")
    check_tv_file(prepare_for_tv(b.getvalue()))
