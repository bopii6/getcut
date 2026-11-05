# -*- coding: utf-8 -*-
import io
p = r"E:\getcut\build_v4.py"
s = io.open(p, encoding="utf-8").read()
s = s.replace("ghost_num(img, f\"0{TRAPS[k]['n']}\", W / 2, 1160, 640)",
              "ghost_num(img, f\"0{TRAPS[k]['n']}\", W / 2, 1470, 780)")
s = s.replace("a = tmp.split()[3].point(lambda v: int(v * 0.5))",
              "a = tmp.split()[3].point(lambda v: int(v * 0.34))")
s = s.replace('if p > .55:\n        d.text((W / 2, 1540), cfg["note"]',
              'if p > .40:\n        d.text((W / 2, 1540), cfg["note"]')
io.open(p, "w", encoding="utf-8").write(s)
print("ok")
