# -*- coding: utf-8 -*-
"""Flat-vector cartoon mascot drawn with PIL primitives (no model needed)."""
import math
from PIL import Image, ImageDraw, ImageFont

INK = (26, 42, 74)
SKIN = (243, 205, 172)
SKIN_SH = (222, 178, 145)
HAIR = (58, 46, 40)
BEANIE = (28, 30, 34)
SHIRT = (108, 122, 92)
SHIRT_SH = (88, 100, 74)
GLASS = (30, 34, 42)
WHITE = (252, 249, 242)
RED = (216, 72, 44)

def _ell(d, box, fill, outline=None, w=0):
    d.ellipse(box, fill=fill, outline=outline, width=w)

def draw_mascot(base, cx, cy, scale=1.0, t=0.0, mouth=0.0, brow=0.0,
                blink=0.0, sweat=0.0, look=0.0, tilt=0.0, body=True):
    """Draw a bust-up cartoon character. cx,cy = centre of the head."""
    S = scale
    bob = math.sin(t * 2.2) * 6 * S
    cy = cy + bob

    layer = Image.new("RGBA", (base.width, base.height), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # ---- shoulders / body
    if body:
        sw, sh = 420 * S, 300 * S
        d.rounded_rectangle([cx - sw / 2, cy + 150 * S, cx + sw / 2, cy + 150 * S + sh],
                            radius=90 * S, fill=SHIRT, outline=INK, width=int(7 * S))
        # collar
        d.polygon([(cx - 70 * S, cy + 160 * S), (cx + 70 * S, cy + 160 * S), (cx, cy + 235 * S)],
                  fill=SHIRT_SH)

    # ---- ears
    for sx in (-1, 1):
        _ell(d, [cx + sx * 175 * S - 26 * S, cy + 5 * S - 34 * S,
                 cx + sx * 175 * S + 26 * S, cy + 5 * S + 34 * S], SKIN, INK, int(6 * S))

    # ---- head
    hw, hh = 168 * S, 190 * S
    _ell(d, [cx - hw, cy - hh, cx + hw, cy + hh], SKIN, INK, int(8 * S))

    # ---- beard
    d.chord([cx - hw + 6 * S, cy - 20 * S, cx + hw - 6 * S, cy + hh - 4 * S],
            200, 340, fill=HAIR)
    # chin skin patch
    _ell(d, [cx - 58 * S, cy + 92 * S, cx + 58 * S, cy + 150 * S], SKIN_SH)

    # ---- beanie
    d.chord([cx - hw - 6 * S, cy - hh - 26 * S, cx + hw + 6 * S, cy + 20 * S],
            180, 360, fill=BEANIE)
    d.rounded_rectangle([cx - hw - 4 * S, cy - 60 * S, cx + hw + 4 * S, cy - 18 * S],
                        radius=22 * S, fill=(36, 38, 44))
    d.rounded_rectangle([cx - 26 * S, cy - 52 * S, cx + 26 * S, cy - 26 * S],
                        radius=8 * S, fill=RED)

    # ---- glasses
    ex = 74 * S
    ey = cy - 6 * S
    r = 56 * S
    for sx in (-1, 1):
        _ell(d, [cx + sx * ex - r, ey - r, cx + sx * ex + r, ey + r], WHITE, GLASS, int(7 * S))
    d.line([cx - ex + r - 4 * S, ey - 2 * S, cx + ex - r + 4 * S, ey - 2 * S], fill=GLASS, width=int(7 * S))
    d.line([cx - ex - r + 6 * S, ey - 4 * S, cx - hw + 6 * S, ey - 10 * S], fill=GLASS, width=int(7 * S))
    d.line([cx + ex + r - 6 * S, ey - 4 * S, cx + hw - 6 * S, ey - 10 * S], fill=GLASS, width=int(7 * S))

    # ---- eyes
    for sx in (-1, 1):
        px = cx + sx * ex + look * 6 * S
        _ell(d, [px - 17 * S, ey - 17 * S, px + 17 * S, ey + 17 * S], GLASS)
        _ell(d, [px - 6 * S - 4 * S, ey - 10 * S, px - 6 * S + 6 * S, ey], WHITE)
        if blink > 0.15:
            h = 34 * S * min(1.0, blink)
            d.rectangle([px - r + 4 * S, ey - h / 2, px + r - 4 * S, ey + h / 2], fill=SKIN)
            d.line([px - r + 4 * S, ey + h / 2, px + r - 4 * S, ey + h / 2], fill=INK, width=int(6 * S))

    # ---- brows
    for sx in (-1, 1):
        by = ey - 78 * S - brow * 12 * S * (1 if sx > 0 else 0.6)
        d.line([cx + sx * ex - 44 * S, by + 14 * S, cx + sx * ex + 44 * S, by - 4 * S * (1 - brow)],
               fill=HAIR, width=int(14 * S), joint="curve")

    # ---- nose
    d.arc([cx - 20 * S, ey + 34 * S, cx + 20 * S, ey + 66 * S], 200, 340, fill=INK, width=int(6 * S))

    # ---- mouth
    mo = mouth
    mw = 62 * S
    mh = (10 + 62 * mo) * S
    my = cy + 118 * S
    if mo < 0.08:
        d.line([cx - mw / 2, my, cx + mw / 2, my], fill=(90, 60, 60), width=int(8 * S))
    else:
        _ell(d, [cx - mw, my - mh * .55, cx + mw, my + mh * .55], (70, 40, 42), INK, int(6 * S))
        _ell(d, [cx - mw * .55, my + mh * .1, cx + mw * .55, my + mh * .62], (196, 96, 92))

    # ---- sweat drop
    if sweat > 0.02:
        sy = cy - 40 * S + 70 * S * (1 - sweat)
        dx, dy = cx + 150 * S, sy
        d.polygon([(dx, dy - 26 * S), (dx + 15 * S, dy + 6 * S), (dx, dy + 18 * S),
                   (dx - 15 * S, dy + 6 * S)], fill=(150, 200, 232), outline=INK, width=int(3 * S))

    if abs(tilt) > 0.01:
        layer = layer.rotate(tilt, resample=Image.BICUBIC, center=(cx, cy))
    base.paste(layer, (0, 0), layer)


if __name__ == "__main__":
    img = Image.new("RGB", (1080, 1000), (246, 240, 225))
    draw_mascot(img, 540, 520, scale=1.4, t=0.5, mouth=0.6, sweat=0.7, brow=0.5)
    img.save(r"E:\getcut\ref\mascot_test.png")
    print("ok")
