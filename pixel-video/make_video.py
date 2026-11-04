# -*- coding: utf-8 -*-
"""
PIXEL LAB 01 —— 越糊越高级
纯代码生成的像素风解释短片（竖屏 1080x1920 / 30fps）
所有画面在 270x480 的低分辨率画布上用 1px 绘制，最后 4 倍最近邻放大。
"""
import os, sys, math, random, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 270, 480
SS = 4
OUT_W, OUT_H = W * SS, H * SS
FPS = 30
FONT = r"E:\getcut\pixel-video\assets\zpix.ttf"
AUDIO = r"E:\getcut\pixel-video\build\bgm.wav"
OUTDIR = r"E:\getcut\pixel-video\build"

C = dict(
    bg=(20, 18, 31), bg2=(11, 10, 18), ink=(242, 237, 228),
    dim=(138, 134, 158), dim2=(62, 58, 82),
    teal=(47, 185, 168), teal_d=(28, 118, 109),
    orange=(245, 131, 60), orange_d=(176, 80, 26),
    red=(231, 90, 78), green=(127, 191, 77), blue=(77, 143, 206),
    purple=(138, 111, 191), yellow=(242, 193, 78), plum=(92, 56, 96),
)

_fc, _tc = {}, {}

def _font(size):
    if size not in _fc:
        _fc[size] = ImageFont.truetype(FONT, size)
    return _fc[size]

def text_mask(s, size):
    key = (s, size)
    if key in _tc:
        return _tc[key]
    f = _font(size)
    bbox = f.getbbox(s) or (0, 0, 1, size)
    w = max(bbox[2] - bbox[0] + 2, 1)
    h = max(bbox[3] - bbox[1] + 2, 1)
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).text((-bbox[0] + 1, -bbox[1] + 1), s, font=f, fill=255)
    im = im.point(lambda v: 255 if v >= 110 else 0)
    _tc[key] = im
    return im

def put(img, x, y, s, size=12, color=None, align="left"):
    color = color or C["ink"]
    m = text_mask(s, size)
    w, h = m.size
    if align == "center":
        x -= w // 2
    elif align == "right":
        x -= w
    img.paste(Image.new("RGB", (w, h), color), (int(x), int(y)), m)
    return int(x) + w

def tw(s, size=12):
    return text_mask(s, size).size[0]

def rect(img, x, y, w, h, color):
    ImageDraw.Draw(img).rectangle([x, y, x + w - 1, y + h - 1], fill=color)

def box(img, x, y, w, h, color):
    d = ImageDraw.Draw(img)
    d.rectangle([x, y, x + w - 1, y + h - 1], outline=color)

def art(img, x, y, rows, cell, cmap):
    d = ImageDraw.Draw(img)
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == "." or ch not in cmap:
                continue
            d.rectangle([x + i * cell, y + j * cell,
                         x + i * cell + cell - 1, y + j * cell + cell - 1], fill=cmap[ch])

BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]

def bayer(x, y):
    return (BAYER[y & 3][x & 3] + 0.5) / 16.0

def dots(img, idx, total=5):
    gap = 11
    x0 = W // 2 - (total * gap) // 2 + 2
    for i in range(total):
        c = C["ink"] if i == idx else C["dim2"]
        rect(img, x0 + i * gap, 462, 6, 4, c)

# ---------------------------------------------------------------- scenes

INVADER = [
    "..x.....x..",
    "...x...x...",
    "..xxxxxxx..",
    ".xx.xxx.xx.",
    "xxxxxxxxxxx",
    "x.xxxxxxx.x",
    "x.x.....x.x",
    "...xx.xx...",
]

PLANT = [
    ".....y....",
    "....yyy...",
    ".....g....",
    "..g..g..g.",
    "...g.g.g..",
    "....ggg...",
    ".....g....",
    "..ooooo...",
    "..o...o...",
    "...ooo....",
]

def scene_hook(img, lt):
    d = ImageDraw.Draw(img)
    cols, rows, cell = 11, 8, 14
    gx, gy = W // 2 - cols * cell // 2, 96
    order = list(range(cols * rows))
    random.Random(7).shuffle(order)
    rank = {v: i for i, v in enumerate(order)}
    p = min(max((lt - 0.15) / 2.0, 0), 1.0)
    flick = int(lt * 12)
    pool = [C["teal"], C["orange"], C["cream"] if "cream" in C else C["ink"],
            C["purple"], C["red"], C["green"], C["blue"], C["yellow"]]
    for j in range(rows):
        for i in range(cols):
            on = INVADER[j][i] == "x"
            k = j * cols + i
            locked = rank[k] < p * cols * rows
            if locked:
                d.rectangle([gx + i * cell, gy + j * cell,
                             gx + i * cell + cell - 1, gy + j * cell + cell - 1],
                            fill=C["teal"] if on else C["bg"])
            else:
                rnd = random.Random(flick * 977 + k * 31)
                col = rnd.choice(pool) if rnd.random() < 0.55 else C["bg2"]
                d.rectangle([gx + i * cell, gy + j * cell,
                             gx + i * cell + cell - 1, gy + j * cell + cell - 1],
                            fill=col)
    if lt > 2.15:
        glow = C["teal_d"] if int(lt * 8) % 3 == 0 else C["bg"]
        box(img, gx - 5, gy - 5, cols * cell + 9, rows * cell + 9, glow)
        # 锁定扫描线
        k = min((lt - 2.15) / 0.45, 1.0)
        if k < 1.0:
            sy = int(gy + k * rows * cell)
            d.rectangle([gx - 5, sy, gx + cols * cell + 4, sy + 2], fill=C["ink"])
    put(img, 14, 26, "PIXEL LAB / 01", 12, C["dim"])
    if lt > 2.35:
        n = int((lt - 2.35) * 14)
        s = "越糊越高级"[:max(n, 0)]
        put(img, W // 2, 292, s, 36, C["ink"], "center")
        if len(s) < 5 and int(lt * 3) % 2 == 0:
            rect(img, W // 2 + tw(s, 36) // 2 + 2, 296, 9, 26, C["teal"])
    if lt > 3.05:
        put(img, W // 2, 356, "像素的美学", 12, C["dim"], "center")
        put(img, W // 2, 376, "其实是限制的美学", 12, C["dim"], "center")
    dots(img, 0)

def scene_origin(img, lt):
    d = ImageDraw.Draw(img)
    put(img, 22, 30, "1983 年", 24, C["ink"])
    put(img, 22, 62, "一台掌机，一块小屏幕", 12, C["dim"])
    # 机身
    bx, by, bw, bh = 55, 96, 160, 236
    rect(img, bx, by, bw, bh, (206, 200, 186))
    rect(img, bx, by + bh - 22, bw, 22, (176, 169, 155))
    sx, sy, sw, sh = bx + 14, by + 14, bw - 28, 136
    box(img, sx, sy, sw, sh, (60, 56, 52))
    rect(img, sx, sy, sw, sh, (196, 208, 196))
    # 屏幕内 4 色植物
    cell = 9
    ax = sx + (sw - 10 * cell) // 2
    ay = sy + 10
    p = min(max((lt - 0.5) / 1.8, 0), 1.0)
    cmap = dict(y=C["yellow"], g=C["green"], o=C["orange"], b=(196, 208, 196))
    total = 10 * 10
    reveal = p * total
    idx = 0
    for j, row in enumerate(PLANT):
        for i, ch in enumerate(row):
            idx += 1
            if idx > reveal:
                continue
            if ch == ".":
                continue
            d.rectangle([ax + i * cell, ay + j * cell,
                         ax + i * cell + cell - 1, ay + j * cell + cell - 1], fill=cmap[ch])
    if p >= 1.0 and int(lt * 4) % 2 == 0:
        rect(img, ax + 9 * cell, ay + 9 * cell, cell, cell, C["ink"])
    put(img, sx + sw // 2, sy + sh - 16, "160 × 144", 12, (120, 130, 120), "center")
    # 十字键 + 按钮
    rect(img, bx + 24, by + 176, 40, 12, (92, 88, 84))
    rect(img, bx + 38, by + 162, 12, 40, (92, 88, 84))
    rect(img, bx + 104, by + 176, 16, 16, C["red"])
    rect(img, bx + 128, by + 184, 16, 16, C["teal_d"])
    # 4 色色板
    px, py = 55, 352
    for i, c in enumerate([(196, 208, 196), C["green"], C["yellow"], C["orange"]]):
        rect(img, px + i * 24, py, 18, 18, c)
        box(img, px + i * 24, py, 18, 18, (74, 70, 66))
        if int(lt * 4) % 4 == i:
            box(img, px + i * 24 - 3, py - 3, 24, 24, C["ink"])
    put(img, px + 104, py + 3, "只有 4 种颜色", 12, C["dim"])
    if lt > 3.4:
        put(img, 22, 396, "不是想画糊", 24, C["ink"])
        put(img, 22, 426, "是只能画这么多", 24, C["teal"])
    dots(img, 1)

def _ball(img, cx, cy, r, mode, lt):
    light = (-0.55, -0.62, 0.56)
    lx, ly, lz = light
    norm = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / norm, ly / norm, lz / norm
    d = ImageDraw.Draw(img)
    for y in range(-r, r + 1):
        for x in range(-r, r + 1):
            rr = (x * x + y * y) / (r * r)
            if rr > 1:
                continue
            z = math.sqrt(max(0.0, 1 - rr))
            v = max(0.0, x / r * lx + y / r * ly + z * lz)
            v = v ** 0.9
            if mode == "dith":
                if v > 0.88:
                    col = C["ink"]
                else:
                    col = C["ink"] if v > bayer(cx + x, cy + y) else C["teal_d"]
            else:
                steps = 8
                q = round(v * (steps - 1)) / (steps - 1)
                base = (24, 22, 38)
                top = (242, 237, 228)
                col = tuple(int(base[k] + (top[k] - base[k]) * q) for k in range(3))
            d.point((cx + x, cy + y), fill=col)

def scene_dither(img, lt):
    _ball(img, 76, 176, 56, "dith", lt)
    put(img, 76, 244, "2 色 + 抖动", 12, C["dim"], "center")
    if 2.4 < lt < 6.0:
        _ball(img, 196, 176, 56, "band", lt)
        put(img, 196, 244, "8 色", 12, C["dim"], "center")
    put(img, 22, 32, "同一个球", 12, C["dim"])
    if lt < 2.4 or lt < 6.0:
        if lt > 0.5:
            put(img, 22, 300, "只有两种颜色", 24, C["ink"])
        if lt > 1.6:
            put(img, 22, 330, "也能看出光从哪来", 24, C["ink"])
    if lt >= 6.0:
        # 右侧：三种密度，说明“排列”本身在产生明暗
        bx = 152
        for i, dens in enumerate([0.25, 0.5, 0.75]):
            px = bx + i * 30
            rect(img, px, 150, 26, 26, C["teal_d"])
            for yy in range(26):
                for xx in range(26):
                    if dens == 0.25:
                        on = (xx % 2 == 0 and yy % 2 == 0)
                    elif dens == 0.5:
                        on = ((xx + yy) % 2 == 0)
                    else:
                        on = not (xx % 2 == 0 and yy % 2 == 0)
                    if on:
                        ImageDraw.Draw(img).point((px + xx, 150 + yy), fill=C["ink"])
            put(img, px + 13, 182, f"{int(dens*100)}%", 12, C["dim"], "center")
        put(img, 22, 300, "格子越密", 24, C["ink"])
        put(img, 22, 330, "看着就越亮", 24, C["ink"])
    if lt > 3.6:
        put(img, 22, 378, "这叫 dithering", 12, C["teal"])
        put(img, 22, 398, "用排列，骗过眼睛", 12, C["dim"])
    dots(img, 2)

def _peaks(d, x, y, w, base_y, peaks, color):
    for (px, ph) in peaks:
        px = x + int(px * w)
        for i in range(ph):
            d.line([(px - i, base_y - ph + i), (px + i, base_y - ph + i)], fill=color)

def _panel_soft(img, x, y, w, h):
    """很多颜色：色带、灰、糊。"""
    d = ImageDraw.Draw(img)
    for i in range(h):
        t = i / (h - 1)
        band = int(t * 11) / 11.0
        c0, c1 = (156, 124, 136), (80, 76, 104)
        col = tuple(int(c0[j] + (c1[j] - c0[j]) * band) for j in range(3))
        d.line([(x, y + i), (x + w - 1, y + i)], fill=col)
    d.ellipse([x + 26, y + 16, x + 50, y + 40], fill=(206, 188, 178))
    base = y + h - 26
    _peaks(d, x, y, w, base, [(0.34, 38), (0.72, 46)], (92, 82, 106))
    rect(img, x, base, w, h - (base - y), (98, 100, 122))
    box(img, x - 1, y - 1, w + 2, h + 2, C["bg2"])
    put(img, x + 6, y + 6, "24 色", 12, (216, 208, 214))

def _panel_hard(img, x, y, w, h):
    """四个颜色：硬边、高对比、图形感。"""
    d = ImageDraw.Draw(img)
    rect(img, x, y, w, h, C["plum"])
    base = y + h - 24
    _peaks(d, x, y, w, base, [(0.28, 26), (0.6, 36), (0.86, 20)], (30, 24, 40))
    rect(img, x, base, w, 24, C["orange"])
    d.rectangle([x, base - 1, x + w - 1, base], fill=C["ink"])
    # 水面反光：几道短线
    for k in range(5):
        d.line([(x + 30 + k * 34, base + 7 + (k % 2) * 5),
                (x + 30 + k * 34 + 12, base + 7 + (k % 2) * 5)], fill=C["ink"])
    cx = x + w - 56
    d.ellipse([cx - 9, base - 22, cx + 9, base - 4], fill=C["ink"])
    box(img, x - 1, y - 1, w + 2, h + 2, C["bg2"])
    put(img, x + 6, y + 6, "4 色", 12, (232, 224, 214))

def scene_compare(img, lt):
    put(img, 22, 30, "现在的屏幕", 12, C["dim"])
    put(img, 22, 52, "1677 万种颜色", 24, C["ink"])
    _panel_soft(img, 20, 92, 230, 92)
    put(img, 20, 190, "颜色一多，全都灰掉了", 12, C["dim"])
    if lt > 3.2:
        p = min((lt - 3.2) / 0.35, 1.0)
        sub = img.copy()
        _panel_hard(sub, 20, 216, 230, 92)
        hh = int(92 * p)
        if hh > 0:
            img.paste(sub.crop((0, 216, W, 216 + hh)), (0, 216))
        if p < 1.0:
            rect(img, 20, 216 + hh, 230, 2, C["teal"])
        put(img, 20, 314, "只留四个颜色，反而清楚了", 12, C["dim"])
    if lt > 6.0:
        put(img, 22, 348, "少，才逼得出风格", 24, C["teal"])
        put(img, 22, 388, "限制不是妥协", 12, C["dim"])
        put(img, 22, 406, "是主动做的选择", 12, C["dim"])
    dots(img, 3)

def scene_outro(img, lt):
    put(img, W // 2, 186, "像素不是画得少", 24, C["ink"], "center")
    put(img, W // 2, 218, "是每一格都得算数", 24, C["ink"], "center")
    rect(img, 20, 350, W - 40, 2, C["dim2"])
    x = int(min(-80 + lt * 60, 176))
    step = int(lt * 6) % 2
    art(img, x, 350 - 48 - (1 if step else 0), INVADER, 6,
        dict(x=C["teal"] if step == 0 else C["teal_d"]))
    if lt > 2.4:
        rect(img, W // 2 - 62, 402, 14, 14, C["teal"])
        put(img, W // 2 - 38, 402, "像素实验室", 12, C["ink"])
        put(img, W // 2 - 38, 422, "PIXEL LAB · 01", 12, C["dim"])
    dots(img, 4)

SCENES = [(4.0, scene_hook), (7.0, scene_origin), (9.0, scene_dither),
          (9.0, scene_compare), (7.0, scene_outro)]
TOTAL = sum(s[0] for s in SCENES)

def block_wipe(a, b, p, seed=3):
    out = a.copy()
    blocks = [(x, y) for y in range(0, H, 20) for x in range(0, W, 20)]
    random.Random(seed).shuffle(blocks)
    n = int(len(blocks) * p)
    for (x, y) in blocks[:n]:
        out.paste(b.crop((x, y, min(x + 20, W), min(y + 20, H))), (x, y))
    return out

def render(t):
    acc = 0.0
    for i, (dur, fn) in enumerate(SCENES):
        if t < acc + dur or i == len(SCENES) - 1:
            lt = t - acc
            img = Image.new("RGB", (W, H), C["bg"])
            fn(img, lt)
            # 进入 / 退出 的方块擦除
            if lt < 0.22 and i > 0:
                prev = Image.new("RGB", (W, H), C["bg"])
                SCENES[i - 1][1](prev, SCENES[i - 1][0] - 0.01)
                img = block_wipe(prev, img, lt / 0.22, seed=i)
            if t > TOTAL - 0.55:
                k = max(0.0, (TOTAL - t) / 0.55)
                img = Image.eval(img, lambda v: int(v * k))
            return img
        acc += dur
    return Image.new("RGB", (W, H), C["bg"])

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == "stills":
        times = [1.6, 3.7, 6.2, 9.4, 14.0, 18.6, 22.0, 26.6, 29.6, 33.0]
        sheet = Image.new("RGB", (len(times) * (W + 6), H + 6), (40, 40, 48))
        for i, t in enumerate(times):
            sheet.paste(render(t), (i * (W + 6) + 3, 3))
        sheet = sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST)
        sheet.save(os.path.join(OUTDIR, "contact.png"))
        print("stills ->", os.path.join(OUTDIR, "contact.png"))
        return
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    nf = int(TOTAL * FPS)
    novid = os.path.join(OUTDIR, "video_only.mp4")
    cmd = [ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OUT_W}x{OUT_H}",
           "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow",
           "-crf", "18", "-pix_fmt", "yuv420p", novid]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    for f in range(nf):
        img = render(f / FPS)
        img = img.resize((OUT_W, OUT_H), Image.NEAREST)
        p.stdin.write(img.tobytes())
        if f % 60 == 0:
            print(f"frame {f}/{nf}", flush=True)
    p.stdin.close()
    p.wait()
    print("video ok:", novid, TOTAL, "s")
    final = os.path.join(OUTDIR, "pixel_lab_01.mp4")
    if os.path.exists(AUDIO):
        subprocess.run([ff, "-y", "-i", novid, "-i", AUDIO, "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", final],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("final ->", final)
    else:
        print("!! 缺少音频，跳过合成")

if __name__ == "__main__":
    main()
