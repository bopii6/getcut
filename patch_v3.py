# -*- coding: utf-8 -*-
import io
p = r"E:\getcut\build_v3.py"
s = io.open(p, encoding="utf-8").read()
subs = [
    ('d.text((70, 300), "我的第一个 AI 短视频号"', 'd.text((70, 340), "我的第一个 AI 短视频号"'),
    ('("播放量", "128.4", "万", INK, 112, 54, 600), ("私信", "0", "", RED, 158, 54, 860)',
     '("播放量", "128.4", "万", INK, 116, 56, 640), ("私信", "0", "", RED, 162, 56, 920)'),
    ('for yy in (730, 990):', 'for yy in (785, 1065):'),
    ('img.paste(lay, (int(W / 2 - lay.width / 2), 1230), lay)',
     'img.paste(lay, (int(W / 2 - lay.width / 2), 1300), lay)'),
    ('(fs_lat - fs_cn) * 0.28', '(fs_lat - fs_cn) * 0.16'),
    ('y = 950 + (1 - a) * 50', 'y = 1040 + (1 - a) * 50'),
    ('d.text((W / 2, 1400), cfg["note"]', 'd.text((W / 2, 1480), cfg["note"]'),
    ('q = ease_back(p / .4); cx, cy = W / 2, 545', 'q = ease_back(p / .4); cx, cy = W / 2, 625'),
    ('    cx, cy = W / 2, 520\n    for i, lab', '    cx, cy = W / 2, 600\n    for i, lab'),
    ('    cx, cy = W / 2, 520\n    d.rounded_rectangle([cx - 430',
     '    cx, cy = W / 2, 600\n    d.rounded_rectangle([cx - 430'),
    ('    cx, cy = W / 2, 540\n    d.polygon([(cx - 70',
     '    cx, cy = W / 2, 615\n    d.polygon([(cx - 70'),
    ('    cx, cy = W / 2, 540\n    cw, ch = 800, 350',
     '    cx, cy = W / 2, 615\n    cw, ch = 800, 350'),
]
for a, b in subs:
    if a not in s:
        print("MISS:", a[:50])
        continue
    s = s.replace(a, b)
io.open(p, "w", encoding="utf-8").write(s)
print("patched")
