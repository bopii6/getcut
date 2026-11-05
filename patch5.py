# -*- coding: utf-8 -*-
import io
p = r"E:\getcut\build_v4.py"
s = io.open(p, encoding="utf-8").read()

helpers = '''def vtext(img, xy, text, font, fill, angle=90):
    tmp = Image.new("RGBA", (int(font.getlength(text)) + 60, font.size + 60), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((tmp.width / 2, tmp.height / 2), text, font=font, fill=fill, anchor="mm")
    tmp = tmp.rotate(angle, expand=True, resample=Image.BICUBIC)
    img.paste(tmp, (int(xy[0] - tmp.width / 2), int(xy[1] - tmp.height / 2)), tmp)

def ghost_num(img, text, cx, cy, size, col=(240, 230, 210)):
    tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((cx, cy), text, font=F(DISP, size), fill=col + (255,), anchor="mm")
    tmp = tmp.rotate(-9, resample=Image.BICUBIC, center=(cx, cy))
    a = tmp.split()[3].point(lambda v: int(v * 0.5))
    img.paste(tmp, (0, 0), a)

def head(d, dark=False):'''
s = s.replace("def head(d, dark=False):", helpers, 1)

old = '''    if k.startswith("trap"):
        s_trap(d, local, t, k)
        ART[k](d, local)'''
new = '''    if k.startswith("trap"):
        ghost_num(img, f"0{TRAPS[k]['n']}", W / 2, 1160, 640)
        d = ImageDraw.Draw(img)
        d._image = img
        s_trap(d, local, t, k)
        ART[k](d, local)'''
assert old in s
s = s.replace(old, new, 1)

old2 = '''    head(d, dark=dark)
    progress(d, t / total)'''
new2 = '''    if not dark:
        vtext(img, (36, 1010), "AI 短视频避坑指南", F(DISP, 34), (192, 182, 164, 150))
    head(d, dark=dark)
    progress(d, t / total)'''
assert old2 in s
s = s.replace(old2, new2, 1)

io.open(p, "w", encoding="utf-8").write(s)
print("ok")
