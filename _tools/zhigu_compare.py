# -*- coding: utf-8 -*-
"""原片 vs 复刻片 逐段并排对比：抽帧 + 中文标签拼图"""
import subprocess, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(r'E:\短视频生成')
REF = Path(r'C:\Users\wang\Downloads\每个月6743万人用_20260918103638.mp4')
REP = ROOT / '_zhigu_replica.mp4'
OUT = ROOT / '_tools/_compare'; OUT.mkdir(exist_ok=True)
FONT_PATH = ROOT / 'videogen/renderer/public/fonts/SourceHanSansCN-Heavy.otf'

def dur(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'csv=p=0', str(p)], capture_output=True, text=True)
    return float(r.stdout.strip())

D_REF, D_REP = dur(REF), dur(REP)
print('原片', round(D_REF, 1), 's  复刻片', round(D_REP, 1), 's')

# 按"全片进度"对齐：同一进度位置比一比
POS = [0.02, 0.36]  # 先出关键几段
POS = [0.02, 0.06, 0.12, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.97]
PAIRS = [(p, round(D_REF * p, 1), round(D_REP * p, 1)) for p in POS]

def shot(path, t, name):
    f = OUT / f'{name}.png'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', str(t), '-i', str(path),
                    '-frames:v', '1', str(f)], check=True)
    return f

try:
    font = ImageFont.truetype(str(FONT_PATH), 34)
    font_s = ImageFont.truetype(str(FONT_PATH), 26)
except Exception:
    font = font_s = ImageFont.load_default()

CELL = (430, 764)
for gi in range(0, len(PAIRS), 3):
    group = PAIRS[gi:gi + 3]
    sheet = Image.new('RGB', (CELL[0] * 2 + 60, (CELL[1] + 56) * len(group) + 20), (12, 12, 14))
    d = ImageDraw.Draw(sheet)
    for row, (p, tr, tp) in enumerate(group):
        fr = shot(REF, tr, f'ref_{int(p*100)}')
        fp = shot(REP, tp, f'rep_{int(p*100)}')
        y = row * (CELL[1] + 56) + 50
        sheet.paste(Image.open(fr).convert('RGB').resize(CELL), (10, y))
        sheet.paste(Image.open(fp).convert('RGB').resize(CELL), (CELL[0] + 50, y))
        d.text((10, y - 42), f'原片  {tr}s  ({int(p*100)}%)', fill=(255, 220, 90), font=font)
        d.text((CELL[0] + 50, y - 42), f'复刻  {tp}s  ({int(p*100)}%)', fill=(130, 220, 160), font=font)
    sheet.save(OUT / f'cmp_{gi//3+1}.png')
    print('sheet', gi//3+1, group)
