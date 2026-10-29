"""Generate the add-on's icon.png and logo.png.

    python tools/make_art.py                 # illustrated portrait on the TV
    python tools/make_art.py --photo me.jpg  # use your own picture on the TV screen

Drawn at 4x and downsampled so edges are smooth. Needs Pillow only.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

OUT = Path(__file__).resolve().parents[1] / "framehaphotossync"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
S = 1024  # design grid


def vgradient(size, top, bottom):
    w, h = size
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        col.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return col.resize((w, h))


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return m


def shadow(img, box, radius, blur, offset=(0, 18), alpha=110):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(layer).rounded_rectangle(
        (x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1]), radius, fill=(0, 0, 0, alpha))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def portrait(size, photo: Path | None):
    """The picture shown on the TV: an illustrated portrait, or the user's own photo."""
    w, h = size
    if photo:
        return ImageOps.fit(Image.open(photo).convert("RGB"), size, Image.LANCZOS, centering=(0.5, 0.35))
    img = vgradient(size, (255, 196, 140), (214, 106, 134))
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse((w * 0.62, h * 0.12, w * 0.62 + h * 0.28, h * 0.12 + h * 0.28), fill=(255, 238, 190, 230))  # sun
    d.polygon([(0, h * 0.78), (w * 0.28, h * 0.5), (w * 0.52, h * 0.74), (w * 0.78, h * 0.46), (w, h * 0.7),
               (w, h), (0, h)], fill=(120, 70, 120, 150))  # hills
    cx = w * 0.42
    d.ellipse((cx - w * 0.30, h * 0.66, cx + w * 0.30, h * 1.35), fill=(36, 74, 120))  # shoulders
    d.rectangle((cx - w * 0.055, h * 0.55, cx + w * 0.055, h * 0.74), fill=(224, 170, 130))  # neck
    d.ellipse((cx - w * 0.15, h * 0.16, cx + w * 0.15, h * 0.64), fill=(236, 186, 146))  # head
    d.chord((cx - w * 0.17, h * 0.10, cx + w * 0.17, h * 0.52), 175, 365, fill=(52, 34, 28))  # hair
    d.ellipse((cx - w * 0.17, h * 0.26, cx - w * 0.10, h * 0.62), fill=(52, 34, 28))
    d.ellipse((cx + w * 0.10, h * 0.26, cx + w * 0.17, h * 0.62), fill=(52, 34, 28))
    return img


def draw_tv(img, box, photo):
    x0, y0, x1, y1 = box
    shadow(img, box, 20, 26)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, 22, fill=(32, 32, 36))
    d.rounded_rectangle((x0 + 5, y0 + 5, x1 - 5, y1 - 5), 18, outline=(88, 88, 96), width=3)
    pad = (x1 - x0) * 0.055
    m = (x0 + pad, y0 + pad, x1 - pad, y1 - pad)
    d.rectangle(m, fill=(246, 243, 236))  # the matte
    inset = (x1 - x0) * 0.12
    art = (int(x0 + inset), int(y0 + inset * 0.78), int(x1 - inset), int(y1 - inset * 0.78))
    size = (art[2] - art[0], art[3] - art[1])
    img.paste(portrait(size, photo), art[:2])
    ImageDraw.Draw(img).rectangle(art, outline=(210, 205, 195), width=3)
    return art


def draw_cloud(img, box):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    base_y = y0 + h * 0.62
    d.rounded_rectangle((x0, base_y - h * 0.05, x1, y1), h * 0.19, fill=(255, 255, 255, 255))
    d.ellipse((x0 + w * 0.10, y0 + h * 0.30, x0 + w * 0.46, y0 + h * 0.88), fill=(255, 255, 255, 255))
    d.ellipse((x0 + w * 0.28, y0, x0 + w * 0.72, y0 + h * 0.80), fill=(255, 255, 255, 255))
    d.ellipse((x0 + w * 0.56, y0 + h * 0.22, x0 + w * 0.92, y0 + h * 0.88), fill=(255, 255, 255, 255))
    sh = layer.copy().filter(ImageFilter.GaussianBlur(20))
    sh = Image.merge("RGBA", (Image.new("L", sh.size, 0),) * 3 + (sh.split()[3].point(lambda a: a * 0.35),))
    img.alpha_composite(sh, (0, 14))
    img.alpha_composite(layer)
    return (x0 + w * 0.5, y0 + h * 0.56)


def arrow_arc(d, c, r, start, end, width, color):
    """Circular arrow: an arc from ``start`` to ``end`` degrees with a head at ``end``."""
    d.arc((c[0] - r, c[1] - r, c[0] + r, c[1] + r), start, end, fill=color, width=width)
    a = math.radians(end)
    tip = (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
    tx, ty = -math.sin(a), math.cos(a)  # tangent (direction of travel)
    nx, ny = math.cos(a), math.sin(a)
    L, Wd = width * 2.6, width * 1.7
    d.polygon([(tip[0] + tx * L, tip[1] + ty * L),
               (tip[0] + nx * Wd, tip[1] + ny * Wd),
               (tip[0] - nx * Wd, tip[1] - ny * Wd)], fill=color)


def draw_sync(img, centre, r, color=(13, 110, 207)):
    d = ImageDraw.Draw(img)
    w = int(r * 0.2)
    arrow_arc(d, centre, r, 205, 335, w, color)
    arrow_arc(d, centre, r, 25, 155, w, color)


def flow_arrow(img, p0, p1, color=(255, 255, 255)):
    """A bold curved arrow from p0 to p1 (cloud -> TV)."""
    d = ImageDraw.Draw(img)
    pts = []
    for i in range(41):
        t = i / 40
        cx, cy = (p0[0] + p1[0]) / 2 + 70, (p0[1] + p1[1]) / 2 - 70
        pts.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * cx + t * t * p1[0],
                    (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * cy + t * t * p1[1]))
    d.line(pts[:-3], fill=color, width=26, joint="curve")
    (ax, ay), (bx, by) = pts[-4], pts[-1]
    ang = math.atan2(by - ay, bx - ax)
    L, Wd = 74, 52
    tip = (bx + math.cos(ang) * 22, by + math.sin(ang) * 22)
    base = (tip[0] - math.cos(ang) * L, tip[1] - math.sin(ang) * L)
    d.polygon([tip, (base[0] + math.sin(ang) * Wd, base[1] - math.cos(ang) * Wd),
               (base[0] - math.sin(ang) * Wd, base[1] + math.cos(ang) * Wd)], fill=color)


def scene(photo, bg_top=(9, 60, 140), bg_bottom=(3, 169, 244)):
    """The 1024x1024 composition (rounded-square badge)."""
    img = vgradient((S, S), bg_top, bg_bottom).convert("RGBA")
    img.putalpha(rounded_mask((S, S), 190))
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((120, 120, 920, 920), fill=(255, 255, 255, 38))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))
    draw_tv(img, (96, 400, 928, 880), photo)
    cc = draw_cloud(img, (88, 96, 520, 340))
    draw_sync(img, cc, 62)
    flow_arrow(img, (540, 250), (700, 392))
    return img


def make_icon(photo):
    scene(photo).resize((256, 256), Image.LANCZOS).save(OUT / "icon.png", optimize=True)


def make_logo(photo):
    W, H = 2000, 800  # 4x of 500x200
    img = vgradient((W, H), (9, 60, 140), (3, 169, 244)).convert("RGBA")
    img.putalpha(rounded_mask((W, H), 110))
    mark = scene(photo).resize((720, 720), Image.LANCZOS)
    img.alpha_composite(mark, (50, 40))
    d = ImageDraw.Draw(img)
    avail = W - 800 - 70

    def fitted(text, size):
        font = ImageFont.truetype(FONT_BOLD, size)
        while d.textlength(text, font=font) > avail:
            size -= 4
            font = ImageFont.truetype(FONT_BOLD, size)
        return font

    title, sub = "Frame Photos", "iCloud \u2192 Samsung Frame"
    d.text((800, 215), title, font=fitted(title, 170), fill=(255, 255, 255))
    d.text((806, 440), sub, font=fitted(sub, 90), fill=(214, 238, 255))
    img.resize((500, 200), Image.LANCZOS).save(OUT / "logo.png", optimize=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", type=Path, help="picture to show on the TV instead of the illustration")
    args = ap.parse_args()
    make_icon(args.photo)
    make_logo(args.photo)
    print("wrote", OUT / "icon.png", OUT / "logo.png")
