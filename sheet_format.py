# -*- coding: utf-8 -*-
import os, glob, subprocess
from PIL import Image, ImageDraw, ImageFont

D = r"E:\getcut\ref\format"
FF = r"C:\Users\wang\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"
vids = sorted(glob.glob(os.path.join(D, "*.mp4")))
TW, TH, cols = 400, 712, 3

def dur(p):
    out = subprocess.run([FF.replace(chr(92)+"ffmpeg.exe", chr(92)+"ffprobe.exe"), "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True).stdout
    return round(float(out.strip() or 0), 1)

rows = (len(vids) + cols - 1) // cols
sheet = Image.new("RGB", (cols * TW, rows * TH), (14, 14, 16))
d = ImageDraw.Draw(sheet)
f = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 24)

for i, v in enumerate(vids):
    tmp = os.path.join(D, f"_s{i}.png")
    subprocess.run([FF, "-y", "-loglevel", "error", "-ss", "1.2", "-i", v, "-frames:v", "1",
                    "-vf", f"scale={TW}:-1", tmp], check=False)
    if not os.path.exists(tmp):
        continue
    im = Image.open(tmp).convert("RGB")
    im = im.resize((TW, min(TH, int(im.height * TW / im.width))), Image.LANCZOS)
    x, y = (i % cols) * TW, (i // cols) * TH
    sheet.paste(im, (x, y))
    name = os.path.basename(v).replace("vg_", "").replace(".mp4", "")
    d.rectangle([x, y + TH - 84, x + TW, y + TH], fill=(10, 10, 12))
    d.text((x + 12, y + TH - 62), name, font=f, fill=(255, 255, 255))
    d.text((x + 12, y + TH - 32), f"{dur(v)}s", font=f, fill=(255, 200, 60))
    os.remove(tmp)

out = os.path.join(D, "sheet_format_kb.png")
sheet.save(out)
print("ok", out, len(vids))
