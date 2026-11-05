# -*- coding: utf-8 -*-
import io
p = r"E:\getcut\build_v5.py"
s = io.open(p, encoding="utf-8").read()

s = s.replace("    hh = 640\n", "    hh = 560\n")
s = s.replace("    y = int(1790 - hh + bob)", "    y = int(1880 - hh + bob)")

# taller content: add a third field to the form card
old = '''        if p > .5:
            d.text((left, top + 372), "→ 结果：谁都打动不了", font=F(DISP, 44), fill=RED, anchor="lm")'''
new = '''        d.text((left, top + 350), "为什么是你？", font=F(DISP, 40), fill=GREY, anchor="lm")
        rrect(d, [left, top + 392, right, top + 470], 12, (248, 243, 232), (206, 196, 176), 4)
        d.text((left + 22, top + 431), "因为我会做 AI", font=F(DISP, 40), fill=(190, 180, 160), anchor="lm")
        if p > .45:
            d.text((left, top + 510), "结果：谁都打动不了", font=F(DISP, 44), fill=RED, anchor="lm")'''
assert old in s
s = s.replace(old, new, 1)
io.open(p, "w", encoding="utf-8").write(s)
print("ok")
