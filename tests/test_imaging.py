import io

from PIL import Image

from app.imaging import TV_H, TV_W, prepare_for_tv, thumbnail


def img_bytes(w, h):
    b = io.BytesIO()
    Image.new("RGB", (w, h), "blue").save(b, "JPEG")
    return b.getvalue()


def size(data):
    return Image.open(io.BytesIO(data)).size


def test_crop_and_blur_fill_4k():
    for fit in ("crop", "blur"):
        out, portrait = prepare_for_tv(img_bytes(1200, 1200), fit)
        assert size(out) == (TV_W, TV_H) and not portrait


def test_portrait_and_none_keep_shape():
    out, portrait = prepare_for_tv(img_bytes(1000, 2000), "crop")
    assert portrait and size(out)[0] < size(out)[1]
    out, portrait = prepare_for_tv(img_bytes(6000, 3000), "none")
    assert not portrait and size(out) == (3840, 1920)


def test_thumbnail():
    assert max(size(thumbnail(img_bytes(3000, 2000)))) == 360
