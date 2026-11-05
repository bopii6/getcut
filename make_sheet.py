# -*- coding: utf-8 -*-
import os, json, subprocess
from PIL import Image, ImageDraw, ImageFont

DEST = r"E:\getcut\ref\originals"
FFMPEG = r"C:\Users\wang\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"
items = json.load(open(os.path.join(DEST, "index.json"), encoding="utf-8"))
items = [i for i in items if i["name"].startswith("x_")]
items.sort(key=lambda i: i["name"])

TW, TH = 300, 534
cols, rows = 5, 4
sheet = Image.new("RGB", (cols * TW, rows * TH), (18, 18, 20))
d = ImageDraw.Draw(sheet)
try:
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 22)
except Exception:
    font = ImageFont.load_default()

for idx, it in enumerate(items):
    path = os.path.join(DEST, it["name"])
    t = max(0.4, it["dur"] * 0.12)
    tmp = os.path.join(DEST, f"_f{idx}.png")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", str(t), "-i", path,
                    "-frames:v", "1", "-vf", f"scale={TW}:-1", tmp], check=False)
    if not os.path.exists(tmp):
        continue
    im = Image.open(tmp).convert("RGB")
    w = TW
    h = min(TH, int(im.height * TW / im.width))
    im = im.resize((w, h), Image.LANCZOS)
    x = (idx % cols) * TW
    y = (idx // cols) * TH
    sheet.paste(im, (x, y))
    d.text((x + 10, y + h - 34), f"{idx:02d} · {it['dur']}s · {it['w']}x{it['h']}", font=font, fill=(255, 255, 0))
    os.remove(tmp)

out = os.path.join(DEST, "sheet_x.png")
sheet.save(out)
print("ok", out)
