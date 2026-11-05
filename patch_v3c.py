# -*- coding: utf-8 -*-
import io
p = r"E:\getcut\build_v3.py"
s = io.open(p, encoding="utf-8").read()

old = '''    q3 = clamp01((p - .38) / .3)
    if q3 > 0:
        d.text((W / 2, 940), "重复"'''
new = '''    q3 = clamp01((p - .38) / .3)
    if q3 > 0:
        halo = Image.new("RGB", (W, H), (0, 0, 0))
        rr = 430 * ease_out(q3)
        ImageDraw.Draw(halo).ellipse([W / 2 - rr, 940 - rr * .8, W / 2 + rr, 940 + rr * .8],
                                     fill=(34, 24, 16))
        halo = halo.filter(ImageFilter.GaussianBlur(130))
        img.paste(ImageChops.screen(img, halo))
        d = ImageDraw.Draw(img)
        d.text((W / 2, 940), "重复"'''
assert old in s
s = s.replace(old, new)
io.open(p, "w", encoding="utf-8").write(s)
print("halo patched")
