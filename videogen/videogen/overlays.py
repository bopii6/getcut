"""Stage 4: static art layers measured from the reference (portrait_editorial, dark card style).

All geometry in 1080x1920 canvas coordinates, measured off the niwo reference video.
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CANVAS_W, CANVAS_H = 1080, 1920
CARD = (91, 124, 983, 1556)            # light paper card (l, t, r, b)
PANEL = (115, 596, 964, 1440)          # dark square inner panel
MEDIA = (151, 667, 929, 1107)          # 16:9 media window inside the panel
HEADLINE_L1_Y = 358                    # line1 center y
HEADLINE_L2_Y = 452                    # line2 center y
HEADLINE_FONT = 88
SUBTITLE_CENTER = (540, 1322)
FOOTER_L1_Y = 1622
FOOTER_L2_Y = 1666
FOOTER_FONT = 27

PAPER = (206, 202, 196)
PAPER_EDGE = (188, 184, 178)
PANEL_BG = (23, 18, 14)
INK = (24, 22, 20)
RED = (178, 62, 38)
RED_SOFT = (196, 84, 58)
GRAY_FOOT = (150, 146, 140)
WHITE = (245, 243, 240)

FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C:/Windows/Fonts/msyh.ttc"


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def _dark_texture(w: int, h: int, seed: int = 7) -> Image.Image:
    """Mottled dark plaster background approximating the reference."""
    rnd = random.Random(seed)
    im = Image.new("RGB", (w // 4, h // 4), (30, 28, 26))
    dr = ImageDraw.Draw(im)
    for _ in range(2600):
        x, y = rnd.randrange(w // 4), rnd.randrange(h // 4)
        r = rnd.randint(4, 26)
        g = rnd.randint(-14, 12)
        dr.ellipse([x - r, y - r, x + r, y + r], fill=(30 + g, 28 + g, 26 + g))
    im = im.filter(ImageFilter.GaussianBlur(6)).resize((w, h), Image.LANCZOS)
    noise = Image.effect_noise((w, h), 18).convert("L")
    im = Image.composite(im.point(lambda v: min(255, v + 9)), im, noise.point(lambda v: 55))
    # vignette
    vig = Image.new("L", (w, h), 0)
    dv = ImageDraw.Draw(vig)
    dv.ellipse([-w * 0.35, -h * 0.25, w * 1.35, h * 1.25], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(120))
    dark = im.point(lambda v: int(v * 0.72))
    return Image.composite(im, dark, vig)


def _paper_texture(w: int, h: int, seed: int = 3) -> Image.Image:
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h), PAPER)
    dr = ImageDraw.Draw(im)
    for _ in range(w * h // 900):
        x, y = rnd.randrange(w), rnd.randrange(h)
        g = rnd.randint(-9, 7)
        dr.point((x, y), fill=(216 + g, 213 + g, 208 + g))
    return im.filter(ImageFilter.GaussianBlur(0.6))


def _draw_text_center(dr: ImageDraw.ImageDraw, cx: int, cy: int, text: str,
                      f: ImageFont.FreeTypeFont, fill) -> None:
    l, t, r, b = dr.textbbox((0, 0), text, font=f)
    dr.text((cx - (r - l) / 2 - l, cy - (b - t) / 2 - t), text, font=f, fill=fill)


def make_base(content_title_lines: list[tuple[str, list[tuple[int, int]]]],
              sources: list[str], disclaimer: str, out: Path) -> Path:
    """Static frame: texture + paper card + headline band + panel + footer."""
    im = _dark_texture(CANVAS_W, CANVAS_H)
    dr = ImageDraw.Draw(im)

    # paper card with soft shadow
    dr.rounded_rectangle([CARD[0] - 6, CARD[1] + 2, CARD[2] + 6, CARD[3] + 10],
                         radius=30, fill=(12, 10, 9))
    card = _paper_texture(CARD[2] - CARD[0], CARD[3] - CARD[1])
    mask = Image.new("L", card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card.size[0], card.size[1]], radius=26, fill=255)
    im.paste(card, (CARD[0], CARD[1]), mask)
    dr.rounded_rectangle(list(CARD), radius=26, outline=PAPER_EDGE, width=2)

    # headline lines inside the card top
    f_h = font(HEADLINE_FONT)
    for li, (line, highlights) in enumerate(content_title_lines):
        cy = HEADLINE_L1_Y if li == 0 else HEADLINE_L2_Y
        plain = line
        total_w = dr.textbbox((0, 0), plain, font=f_h)[2]
        # highlight blocks first (black block, white text, red tick on its left)
        if li == 1 and highlights:
            x = CARD[0] + 24
            segs = []
            pos = 0
            for (s, e) in highlights:
                segs.append((plain[pos:s], False))
                segs.append((plain[s:e], True))
                pos = e
            segs.append((plain[pos:], False))
            # line2 layout: left normal text, then highlight block pinned to the
            # card's inner right edge (matches the reference layout)
            cx = x
            block_right = CARD[2] - 22
            for si, (txt, is_hl) in enumerate(segs):
                if not txt:
                    continue
                wseg = dr.textbbox((0, 0), txt, font=f_h)[2]
                if is_hl:
                    bx0 = cx + 6
                    bx1 = block_right
                    dr.rounded_rectangle([bx0, cy - 52, bx1, cy + 52], radius=10, fill=(16, 13, 11))
                    dr.rectangle([bx0 + 2, cy - 52, bx0 + 12, cy + 52], fill=RED)
                    # center the highlighted text within the block
                    inner = (bx1 - bx0) - 12 - 20
                    tx = bx0 + 32 + max((inner - wseg) / 2, 0)
                    dr.text((tx, cy - (f_h.size // 2) + 4), txt, font=f_h, fill=WHITE)
                    cx = bx1
                else:
                    if si == len(segs) - 1 and cx >= block_right:
                        break  # no room past the block; reference clips here too
                    dr.text((cx, cy - (f_h.size // 2) + 4), txt, font=f_h, fill=INK)
                    cx += wseg
        else:
            _draw_text_center(dr, (CARD[0] + CARD[2]) // 2, cy, plain, f_h, INK)

    # dark square panel
    dr.rounded_rectangle(list(PANEL), radius=16, fill=PANEL_BG)

    # footer (sources + disclaimer) on the dark background
    f_f = font(FOOTER_FONT, bold=False)
    if sources:
        txt = "资料来源：" + " ｜ ".join(sources)
        _draw_text_center(dr, CANVAS_W // 2, FOOTER_L1_Y, txt, f_f, GRAY_FOOT)
    if disclaimer:
        _draw_text_center(dr, CANVAS_W // 2, FOOTER_L2_Y, disclaimer, f_f, GRAY_FOOT)

    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def make_title_card(label: str, keyword: str, code: str, out: Path) -> Path:
    """Full-panel designed opening card (red bars + label + big keyword)."""
    w, h = PANEL[2] - PANEL[0], PANEL[3] - PANEL[1]
    im = Image.new("RGB", (w, h), PANEL_BG)
    dr = ImageDraw.Draw(im)
    cx = w // 2
    dr.rounded_rectangle([30, 30, w - 30, h - 30], radius=8, outline=(86, 42, 30), width=2)
    dr.rectangle([cx - 12, 26, cx + 12, 200], fill=RED)                     # top center bar
    dr.rectangle([36, 178, w - 36, 186], fill=RED)                          # horizontal rule
    dr.rectangle([36, 226, 44, 258], fill=RED)                              # label tick
    dr.text((58, 224), label, font=font(34), fill=RED_SOFT)
    dr.text((52, 380), keyword, font=font(120), fill=RED_SOFT)              # big keyword
    code_txt = code
    tw = dr.textbbox((0, 0), code_txt, font=font(26, bold=False))[2]
    dr.text((w - 60 - tw, h - 210), code_txt, font=font(26, bold=False), fill=(210, 205, 198))
    dr.rectangle([36, h - 150, 300, h - 147], fill=(127, 212, 201))         # teal underline
    dr.rectangle([cx - 12, h - 120, cx + 12, h - 26], fill=RED)             # bottom center bar
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def make_quote_card(label: str, quote: str, out: Path) -> Path:
    """Full-panel designed closing card (small red label + dim large quote)."""
    w, h = PANEL[2] - PANEL[0], PANEL[3] - PANEL[1]
    im = Image.new("RGB", (w, h), PANEL_BG)
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([30, 30, w - 30, h - 30], radius=8, outline=(70, 40, 30), width=2)
    dr.rectangle([36, 120, 44, 152], fill=RED)
    dr.text((58, 118), label, font=font(36), fill=RED_SOFT)
    dr.text((52, 260), quote, font=font(96), fill=(118, 112, 106))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def _badge(dr, x, y, text):
    w = dr.textbbox((0, 0), text, font=font(24))[2]
    dr.rounded_rectangle([x, y, x + w + 28, y + 44], radius=22, fill=RED)
    dr.text((x + 14, y + 7), text, font=font(24), fill=(245, 240, 235))


def _wrap(text, width):
    return [text[i:i + width] for i in range(0, len(text), width)]


def make_callout(number: str, label: str, caption: str, out: Path) -> Path:
    """Transparent number-callout badge over the media window (parity with the
    reference's red '3800' callout rendered on footage)."""
    w, h = MEDIA[2] - MEDIA[0], MEDIA[3] - MEDIA[1]
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    x, y = 30, 42
    dr.rectangle([x, y, x + 8, y + 30], fill=RED)
    dr.text((x + 20, y + 2), label[:6], font=font(30), fill=RED_SOFT)
    dr.text((x + 16, y + 44), number, font=font(96), fill=RED_SOFT)
    dr.text((x + 22, y + 164), caption[:14], font=font(24, bold=False), fill=(228, 224, 219))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def make_info_panel(spec: dict, out: Path) -> Path:
    """778x440 transparent information panel placed over dimmed footage.

    variants: compare | fact | statement (see planner.apply_designed_overlays)
    """
    w, h = MEDIA[2] - MEDIA[0], MEDIA[3] - MEDIA[1]
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    variant = spec.get("variant", "fact")

    if variant == "compare":
        dr.rectangle([30, 36, 38, 68], fill=RED)
        dr.text((50, 34), spec.get("label", ""), font=font(30), fill=RED_SOFT)
        dr.text((30, 76), spec.get("title", ""), font=font(58), fill=(238, 234, 229))
        dr.text((32, 152), spec.get("subtitle", ""), font=font(26, bold=False), fill=(200, 195, 189))
        col_w = (w - 90) // 2
        for i, (head, body) in enumerate((
                (spec.get("left_head", ""), spec.get("left", "")),
                (spec.get("right_head", ""), spec.get("right", "")))):
            x0 = 30 + i * (col_w + 30)
            dr.rounded_rectangle([x0, 220, x0 + col_w, 400], radius=10,
                                 fill=(30, 16, 10, 200), outline=RED, width=2)
            dr.text((x0 + 18, 236), head, font=font(26), fill=RED_SOFT)
            for li, line in enumerate(_wrap(body, 9)[:3]):
                dr.text((x0 + 18, 280 + li * 38), line, font=font(26, bold=False), fill=WHITE)
        if spec.get("badge"):
            _badge(dr, w - 118, 34, spec["badge"])
    elif variant == "fact":
        dr.rectangle([30, 36, 38, 68], fill=RED)
        dr.text((50, 34), spec.get("label", ""), font=font(30), fill=RED_SOFT)
        cw = min(w - 120, 560)
        dr.rounded_rectangle([30, 110, 30 + cw, 330], radius=12, fill=(238, 235, 229, 235))
        dr.text((58, 138), spec.get("card_title", ""), font=font(40), fill=INK)
        for li, line in enumerate(_wrap(spec.get("card_body", ""), 16)[:3]):
            dr.text((58, 208 + li * 36), line, font=font(26, bold=False), fill=(90, 86, 81))
        if spec.get("badge"):
            _badge(dr, w - 118, 34, spec["badge"])
    else:  # statement
        dr.rectangle([30, 60, 38, 100], fill=RED)
        dr.text((50, 58), spec.get("label", ""), font=font(28), fill=RED_SOFT)
        dr.text((30, 130), spec.get("title", ""), font=font(92), fill=(238, 234, 229))
        sub = spec.get("subtitle", "")
        if sub:
            dr.text((34, 260), sub[:16], font=font(28, bold=False), fill=(205, 200, 194))
        if spec.get("badge"):
            _badge(dr, w - 118, h - 90, spec["badge"])

    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out
