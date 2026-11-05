# -*- coding: utf-8 -*-
import io
p = r"E:\getcut\build_v4.py"
s = io.open(p, encoding="utf-8").read()
pairs = [
    ("cx, cy = W / 2, 600", "cx, cy = W / 2, 720"),
    ("cx, cy = W / 2, 575", "cx, cy = W / 2, 700"),
    ("cx, cy = W / 2, 595", "cx, cy = W / 2, 725"),
    ("d.text((W / 2, 360), \"把这三个钉死\", font=F(DISP, 92)",
     "d.text((W / 2, 380), \"把这三个钉死\", font=F(DISP, 96)"),
]
for a, b in pairs:
    if a not in s:
        print("MISS", a[:40])
    s = s.replace(a, b)
io.open(p, "w", encoding="utf-8").write(s)
print("ok")
