# -*- coding: utf-8 -*-
import io
p = r"E:\getcut\build_v3.py"
s = io.open(p, encoding="utf-8").read()

s = s.replace("from PIL import Image, ImageDraw, ImageFont, ImageFilter",
              "from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops")

old_beam_start = "def beam(img, cx, cy, w, h, strength=1.0):"
i = s.index(old_beam_start)
j = s.index("def chrome(", i)
new_beam = '''def beam(img, cx, cy, w, h, strength=1.0):
    lay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(lay)
    for i in range(8):
        k = 1 - i / 8
        d.rectangle([cx - w * k / 2, 0, cx + w * k / 2, cy + h * k],
                    fill=tuple(int(c * .05 * k * strength) for c in (255, 236, 205)))
    d.ellipse([cx - w * .6, cy - h * .32, cx + w * .6, cy + h * .32],
              fill=tuple(int(c * .08 * strength) for c in (255, 242, 215)))
    lay = lay.filter(ImageFilter.GaussianBlur(110))
    return ImageChops.screen(img, lay)

'''
s = s[:i] + new_beam + s[j:]
io.open(p, "w", encoding="utf-8").write(s)
print("beam patched")
