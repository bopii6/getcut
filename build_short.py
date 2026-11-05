# -*- coding: utf-8 -*-
"""Build a 9:16 'trap list' short in the bizdevelo / vidguy format.
Paper + ink + orange, kinetic type, counter, one-word twist, CTA card.
"""
import os, sys, math, asyncio, subprocess, wave, struct
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
OUT_DIR = r"E:\getcut\build"
os.makedirs(OUT_DIR, exist_ok=True)

FFMPEG = r"C:\Users\wang\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"

PAPER   = (246, 240, 225)
INK     = (26, 42, 74)
RED     = (226, 74, 40)
GREY    = (128, 122, 112)
DARK    = (14, 17, 22)
CREAM   = (255, 250, 240)

CN = r"C:\Windows\Fonts\msyhbd.ttc"
CNR = r"C:\Windows\Fonts\msyh.ttc"
LAT = r"C:\Windows\Fonts\ariblk.ttf"

_fc = {}
def F(path, size, index=0):
    k = (path, size, index)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(path, size, index=index)
    return _fc[k]

# ---------------------------------------------------------------- helpers
def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3

def ease_back(t):
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2

def clamp01(t):
    return max(0.0, min(1.0, t))

def wrap_cjk(text, font, maxw):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        if font.getlength(cur + ch) > maxw and cur:
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines

def draw_center(d, xy, text, font, fill, anchor="mm", spacing=1.25, maxw=None, align="center"):
    """Draw (possibly wrapped) text centered on xy; returns block bbox height."""
    if maxw is None:
        d.text(xy, text, font=font, fill=fill, anchor=anchor)
        return font.size
    lines = wrap_cjk(text, font, maxw)
    lh = int(font.size * spacing)
    total = lh * len(lines)
    x, y = xy
    top = y - total / 2 + lh / 2
    for i, ln in enumerate(lines):
        if align == "center":
            d.text((x, top + i * lh), ln, font=font, fill=fill, anchor="mm")
        else:
            d.text((x, top + i * lh), ln, font=font, fill=fill, anchor="lm")
    return total

def grain(size=(W, H), amp=7):
    rng = np.random.default_rng(7)
    n = rng.normal(0, amp, (size[1], size[0], 1)).repeat(3, axis=2)
    return Image.fromarray(np.clip(128 + n, 0, 255).astype(np.uint8))

GRAIN = None

def paper_base(dark=False):
    global GRAIN
    if GRAIN is None:
        GRAIN = grain()
    if dark:
        img = Image.new("RGB", (W, H), DARK)
        img = Image.blend(img, GRAIN, 0.05)
    else:
        img = Image.new("RGB", (W, H), PAPER)
        img = Image.blend(img, GRAIN, 0.10)
    return img

def sparkle(d, x, y, r, col=RED, w=6):
    pts = [(x, y - r), (x + r * 0.28, y - r * 0.28), (x + r, y),
           (x + r * 0.28, y + r * 0.28), (x, y + r),
           (x - r * 0.28, y + r * 0.28), (x - r, y),
           (x - r * 0.28, y - r * 0.28)]
    d.polygon(pts, fill=col)

def wobble_line(d, x0, x1, y, col=RED, w=10, amp=7, seed=0):
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(24):
        t = i / 23
        x = x0 + (x1 - x0) * t
        yy = y + math.sin(t * math.pi * 2.2) * amp * 0.45 + rng.normal(0, 1.2)
        pts.append((x, yy))
    d.line(pts, fill=col, width=w, joint="curve")

def pill(text, font, fg=CREAM, bg=INK, pad=(34, 16), angle=0):
    tw = font.getlength(text)
    lw, lh = tw + pad[0] * 2, font.size + pad[1] * 2
    layer = Image.new("RGBA", (int(lw + 20), int(lh + 20)), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle([10, 10, 10 + lw, 10 + lh], radius=lh / 2, fill=bg)
    ld.text((10 + lw / 2, 10 + lh / 2), text, font=font, fill=fg, anchor="mm")
    if angle:
        layer = layer.rotate(angle, resample=Image.BICUBIC, expand=False)
    return layer

def paste_at(base, layer, xy):
    x, y = int(xy[0] - layer.width / 2), int(xy[1] - layer.height / 2)
    base.paste(layer, (x, y), layer)

def glow(img, center, radius, color=(255, 240, 210), strength=1.0):
    lay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(lay)
    for i in range(6):
        r = radius * (1 - i * 0.14)
        a = int(38 * strength * (i + 1) / 6)
        d.ellipse([center[0] - r, center[1] - r, center[0] + r, center[1] + r], fill=tuple(int(c * a / 60) for c in color))
    lay = lay.filter(ImageFilter.GaussianBlur(70))
    return Image.blend(img, Image.blend(img, lay, 0.9), 0.55)

def progress_bar(d, p):
    d.rectangle([0, H - 8, W, H], fill=(226, 220, 205))
    d.rectangle([0, H - 8, int(W * clamp01(p)), H], fill=RED)

# ---------------------------------------------------------------- script
SCENES = [
    dict(k="hook",  vo="鎴戞妸 AI 鐭棰戝彂浜嗕笁涓湀锛岀淇℃槸闆躲€?, pad=0.35),
    dict(k="trap1", vo="绗竴涓潙锛屽厛鎯冲仛浠€涔堝唴瀹癸紝鍐嶆兂缁欒皝鐪嬨€?, pad=0.28),
    dict(k="trap2", vo="绗簩涓潙锛屼竴鐩存崲宸ュ叿锛屼粠鏉ヤ笉鎹㈢粨鏋勩€?, pad=0.28),
    dict(k="trap3", vo="绗笁涓潙锛屼竴鏉¤棰戯紝鍙彂涓€娆°€?, pad=0.28),
    dict(k="trap4", vo="绗洓涓潙锛岃拷鐑偣锛屼絾涓嶇暀浜恒€?, pad=0.28),
    dict(k="trap5", vo="绗簲涓潙锛屽彧鐪嬫挱鏀鹃噺锛屼笉鐪嬬淇°€?, pad=0.28),
    dict(k="twist", vo="闂涓嶅湪宸ュ叿锛屽湪閭ｄ釜璇嶃€?, pad=0.30),
    dict(k="fix",   vo="鍥哄畾瑙掕壊锛屽浐瀹氭爮鐩紝涓€鍛ㄤ笁鏉°€傛敼閽╁瓙锛屼笉鏀逛汉璁俱€?, pad=0.30),
    dict(k="cta",   vo="璇勮鍖烘墦妯℃澘锛屾垜鎶婅繖浜旀潯鐨勮剼鏈鏋跺彂浣犮€?, pad=0.90),
]

TRAPS = {
    "trap1": dict(n=1, l1="鍏堝仛鍐呭", l2="鍐嶆兂缁欒皝鐪?, key="缁欒皝鐪?),
    "trap2": dict(n=2, l1="涓€鐩存崲宸ュ叿", l2="浠庝笉鎹㈢粨鏋?, key="缁撴瀯"),
    "trap3": dict(n=3, l1="涓€鏉¤棰?,   l2="鍙彂涓€娆?,   key="鍙彂涓€娆?),
    "trap4": dict(n=4, l1="杩藉緱鍔ㄧ儹鐐?, l2="鐣欎笉浣忎汉",   key="鐣欎笉浣忎汉"),
    "trap5": dict(n=5, l1="鍙湅鎾斁閲?, l2="涓嶇湅绉佷俊",   key="绉佷俊"),
}

# ---------------------------------------------------------------- audio
def dur_of(path):
    with wave.open(path) as w:
        return w.getnframes() / float(w.getframerate())

def synth_all():
    audio_dir = os.path.join(OUT_DIR, "vo")
    os.makedirs(audio_dir, exist_ok=True)
    texts = [s["vo"] for s in SCENES]

    async def go():
        import edge_tts
        for i, t in enumerate(texts):
            mp3 = os.path.join(audio_dir, f"{i:02d}.mp3")
            if not os.path.exists(mp3):
                c = edge_tts.Communicate(t, "zh-CN-YunjianNeural", rate="+12%")
                await c.save(mp3)
    asyncio.run(go())

    durs = []
    for i in range(len(texts)):
        mp3 = os.path.join(audio_dir, f"{i:02d}.mp3")
        wav = os.path.join(audio_dir, f"{i:02d}.wav")
        if not os.path.exists(wav):
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", mp3,
                            "-ar", "48000", "-ac", "1", wav], check=True)
        durs.append(dur_of(wav))
    return durs

def sfx(kind, sr=48000, dur=0.3):
    n = int(sr * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    if kind == "pop":
        env = np.exp(-22 * t)
        x = np.sin(2 * math.pi * 760 * t) * env * 0.5 + np.sin(2 * math.pi * 1180 * t) * env * 0.2
    elif kind == "whoosh":
        noise = np.random.default_rng(1).normal(0, 1, n)
        env = np.sin(np.pi * t / dur) ** 2
        k = int(sr * 0.004)
        noise = np.convolve(noise, np.ones(k) / k, mode="same")
        x = noise * env * 0.28
    elif kind == "thud":
        env = np.exp(-16 * t)
        x = (np.sin(2 * math.pi * 58 * t) * 0.9 + np.sin(2 * math.pi * 92 * t) * 0.3) * env
    elif kind == "tick":
        env = np.exp(-60 * t)
        x = np.sin(2 * math.pi * 1500 * t) * env * 0.25
    return x.astype(np.float32)

def build_audio(scene_durs):
    sr = 48000
    durs = [d + s["pad"] for d, s in zip(scene_durs, SCENES)]
    total = sum(durs)
    track = np.zeros(int(sr * (total + 1.0)), dtype=np.float32)
    marks = []
    t0 = 0.0
    for i, (s, d, sd) in enumerate(zip(SCENES, durs, scene_durs)):
        marks.append(dict(kind=s["k"], start=t0, dur=d, vo_dur=sd))
        # voice
        with wave.open(os.path.join(OUT_DIR, "vo", f"{i:02d}.wav")) as w:
            v = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        a = int(sr * t0); b = a + len(v)
        track[a:b] += v
        # sfx per scene type
        sfx_specs = []
        if s["k"] == "hook":
            sfx_specs = [(0.0, "thud", 0.9), (0.06, "whoosh", 0.7)]
        elif s["k"].startswith("trap"):
            sfx_specs = [(0.0, "pop", 0.8), (0.02, "whoosh", 0.35)]
        elif s["k"] == "twist":
            sfx_specs = [(0.0, "whoosh", 0.6), (sd * 0.55, "thud", 1.0)]
        elif s["k"] == "fix":
            sfx_specs = [(0.0, "pop", 0.7), (sd * 0.45, "pop", 0.5)]
        elif s["k"] == "cta":
            sfx_specs = [(0.0, "tick", 0.6), (0.25, "pop", 0.6)]
        for at, kind, gain in sfx_specs:
            x = sfx(kind) * gain * 0.55
            a = int(sr * (t0 + at)); b = a + len(x)
            if b < len(track):
                track[a:b] += x
        t0 += d
    peak = max(1e-6, float(np.abs(track).max()))
    track = track / peak * 0.92
    out = os.path.join(OUT_DIR, "audio.wav")
    with wave.open(out, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((track * 32767).astype(np.int16).tobytes())
    return out, marks, sum(durs)

# ---------------------------------------------------------------- scenes
def s_hook(d, p, t):
    a = ease_back(p / 0.45)
    d.text((W / 2, 470), "AI 鐭棰?路 涓変釜鏈?, font=F(CN, 46), fill=GREY, anchor="mm")
    # huge 0
    f0 = F(LAT, int(430 * (1.55 - 0.55 * a)))
    d.text((W / 2 - 40, 800), "0", font=f0, fill=RED, anchor="mm")
    f1 = F(CN, 104)
    d.text((W / 2 + 190, 880), "绉佷俊", font=f1, fill=INK, anchor="mm")
    d.text((W / 2, 1075), "鍙戜簡涓変釜鏈堬紝涓€鏉℃病鍥?, font=F(CN, 52), fill=INK, anchor="mm")
    q = ease_out((p - 0.35) / 0.4)
    if q > 0:
        txt = "杩?5 涓潙锛屾垜鍏ㄨ俯浜?
        tw = F(CN, 62).getlength(txt) + 96
        d.rounded_rectangle([W / 2 - tw / 2, 1215, W / 2 + tw / 2, 1345], radius=18,
                            outline=INK, width=6, fill=(252, 246, 232))
        d.text((W / 2, 1280), txt, font=F(CN, 62), fill=INK, anchor="mm")
    for i, (sx, sy, r) in enumerate([(150, 560, 26), (930, 660, 18), (880, 1050, 22), (190, 1030, 14)]):
        qq = ease_back((p - 0.25 - i * 0.06) / 0.35)
        if qq > 0:
            sparkle(d, sx, sy, r * qq, col=RED if i % 2 == 0 else (240, 170, 60))

def s_trap(d, p, t, key):
    cfg = TRAPS[key]
    # counter
    q = ease_back(p / 0.3)
    lay = pill(f"{cfg['n']}/5", F(LAT, 34), fg=CREAM, bg=INK)
    paste_at(d._image, lay, (150, 135))
    # number ghost
    d.text((W - 130, 150), f"0{cfg['n']}", font=F(LAT, 120), fill=(226, 216, 198), anchor="rm")
    # title
    a = ease_out(p / 0.42)
    y1 = 720 + (1 - a) * 60
    d.text((W / 2, y1), cfg["l1"], font=F(CN, 118), fill=INK, anchor="mm")
    d.text((W / 2, y1 + 168), cfg["l2"], font=F(CN, 118), fill=RED if cfg["key"] == cfg["l2"] else INK, anchor="mm")
    # wobble underline under red word
    if cfg["key"] == cfg["l2"]:
        wpx = F(CN, 118).getlength(cfg["l2"])
        wobble_line(d, W / 2 - wpx / 2, W / 2 + wpx / 2, y1 + 168 + 86, col=RED, w=9, seed=cfg["n"])

def art_icon1(d, p):  # faceless person + ?
    q = ease_back(p / 0.4)
    cx, cy = W / 2, 430
    d.ellipse([cx - 66, cy - 66, cx + 66, cy + 66], fill=(206, 198, 184), outline=INK, width=6)
    d.rounded_rectangle([cx - 96, cy + 74, cx + 96, cy + 200], radius=60, fill=(206, 198, 184), outline=INK, width=6)
    d.text((cx, cy - 8), "?", font=F(LAT, int(72 * q)), fill=INK, anchor="mm")
    d.text((cx + 190, cy + 20), "璋佸湪鐪嬶紵", font=F(CN, 44), fill=GREY, anchor="lm")

def art_icon2(d, p):  # three tools, one skeleton
    q = ease_out(p / 0.45)
    cx, cy = W / 2, 430
    for i, lab in enumerate(["宸ュ叿 A", "宸ュ叿 B", "宸ュ叿 C"]):
        x = cx - 250 + i * 250
        d.rounded_rectangle([x - 92, cy - 120, x + 92, cy + 40], radius=16,
                            outline=(196, 188, 172), width=5, fill=(250, 245, 234))
        d.text((x, cy - 40), lab, font=F(CN, 38), fill=(186, 178, 162), anchor="mm")
        d.line([x - 60, cy - 90, x + 60, cy + 10], fill=(214, 76, 56), width=6)
    # skeleton stays
    d.rounded_rectangle([cx - 300, cy + 70, cx + 300, cy + 210], radius=18,
                        outline=INK, width=7, fill=(252, 246, 232))
    for i in range(3):
        d.ellipse([cx - 250 + i * 70, cy + 122, cx - 190 + i * 70, cy + 158], fill=INK)
    d.line([cx - 40, cy + 140, cx + 210, cy + 140], fill=INK, width=8)
    d.text((cx + 250, cy + 250), "缁撴瀯涓嶅姩", font=F(CN, 40), fill=GREY, anchor="mm")

def art_icon3(d, p):  # one video -> one platform
    cx, cy = W / 2, 430
    d.rounded_rectangle([cx - 420, cy - 110, cx - 190, cy + 120], radius=14,
                        outline=INK, width=6, fill=(252, 246, 232))
    d.polygon([(cx - 330, cy - 40), (cx - 330, cy + 50), (cx - 260, cy + 5)], fill=RED)
    d.text((cx - 305, cy + 88), "1 鏉?, font=F(CN, 34), fill=GREY, anchor="mm")
    for i in range(3):
        y = cy - 90 + i * 110
        on = i == 0
        d.rounded_rectangle([cx + 40, y - 40, cx + 420, y + 40], radius=12,
                            outline=INK if on else (200, 192, 176), width=6,
                            fill=(252, 246, 232) if on else (238, 232, 220))
        d.text((cx + 230, y), ["宸插彂", "绌?, "绌?][i], font=F(CN, 36),
               fill=INK if on else (190, 182, 166), anchor="mm")
    d.line([cx - 170, cy + 5, cx + 20, cy + 5], fill=INK, width=7)
    d.polygon([(cx + 20, cy + 5), (cx - 6, cy - 12), (cx - 6, cy + 22)], fill=INK)

def art_icon4(d, p):  # flame + person leaving
    cx, cy = W / 2, 430
    d.polygon([(cx - 60, cy + 120), (cx - 10, cy - 120), (cx + 20, cy + 10),
               (cx + 70, cy - 70), (cx + 90, cy + 120)], fill=RED)
    d.polygon([(cx - 20, cy + 120), (cx + 10, cy - 20), (cx + 55, cy + 120)], fill=(246, 176, 60))
    # running stick figure
    x0 = cx + 210
    d.ellipse([x0 - 24, cy - 60, x0 + 24, cy - 12], fill=INK)
    d.line([x0, cy - 10, x0, cy + 55], fill=INK, width=9)
    d.line([x0, cy + 55, x0 - 34, cy + 110], fill=INK, width=9)
    d.line([x0, cy + 55, x0 + 34, cy + 105], fill=INK, width=9)
    d.line([x0, cy + 5, x0 - 40, cy + 25], fill=INK, width=9)
    d.line([x0, cy + 5, x0 + 44, cy - 25], fill=INK, width=9)

def art_icon5(d, p):  # analytics card
    cx, cy = W / 2, 430
    card_w, card_h = 720, 330
    d.rounded_rectangle([cx - card_w / 2, cy - card_h / 2, cx + card_w / 2, cy + card_h / 2],
                        radius=26, outline=INK, width=7, fill=(255, 252, 246))
    d.line([cx - card_w / 2, cy - 76, cx + card_w / 2, cy - 76], fill=(228, 220, 204), width=5)
    d.text((cx - card_w / 2 + 36, cy - 118), "鍒涗綔鑰呬腑蹇?路 杩?28 澶?, font=F(CN, 36), fill=GREY, anchor="lm")
    d.text((cx - card_w / 2 + 40, cy - 10), "鎾斁閲?, font=F(CN, 40), fill=GREY, anchor="lm")
    d.text((cx + card_w / 2 - 40, cy - 14), "128.4 涓?, font=F(LAT, 62), fill=INK, anchor="rm")
    d.text((cx - card_w / 2 + 40, cy + 100), "绉佷俊", font=F(CN, 40), fill=GREY, anchor="lm")
    d.text((cx + card_w / 2 - 40, cy + 96), "0", font=F(LAT, 66), fill=RED, anchor="rm")

def s_twist(d, img, p, t):
    # light
    k = ease_out(p / 0.5)
    img2 = glow(img, (W / 2, 700), 620 * (0.5 + 0.6 * k), strength=k)
    img.paste(img2)
    q1 = ease_out((p - 0.05) / 0.3)
    if q1 > 0:
        d.text((W / 2, 560), "闂涓嶅湪宸ュ叿", font=F(CN, 56), fill=(238, 232, 220), anchor="mm")
    q2 = ease_out((p - 0.25) / 0.25)
    if q2 > 0:
        d.text((W / 2, 700), "鍦ㄩ偅涓瘝", font=F(CN, 56), fill=(160, 154, 144), anchor="mm")
    q3 = clamp01((p - 0.42) / 0.3)
    if q3 > 0:
        f = F(CN, int(300 * (1.35 - 0.35 * ease_back(q3))))
        d.text((W / 2, 1010), "閲嶅", font=f, fill=(255, 250, 240), anchor="mm")
        if q3 > 0.5:
            d.text((W / 2, 1250), "鎶婂悓涓€鏉★紝鍋氭垚涓嶅悓鐗堟湰锛屽弽澶嶅彂", font=F(CN, 48), fill=(214, 206, 190), anchor="mm")

def s_fix(d, img, p, t):
    d.text((W / 2, 300), "鎶婅繖涓変釜閽夋", font=F(CN, 74), fill=INK, anchor="mm")
    items = [("鍥哄畾瑙掕壊", "鍚屼竴寮犺劯"), ("鍥哄畾鏍忕洰", "鍚屼竴涓悕瀛?), ("涓€鍛?3 鏉?, "鍚屼竴涓妭濂?)]
    for i, (a, b) in enumerate(items):
        q = ease_back((p - i * 0.12) / 0.35)
        if q <= 0:
            continue
        lay = Image.new("RGBA", (330, 250), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        ld.rounded_rectangle([6, 6, 324, 244], radius=22, fill=(252, 246, 232), outline=INK, width=6)
        ld.text((165, 92), a, font=F(CN, 54), fill=INK, anchor="mm")
        ld.text((165, 168), b, font=F(CN, 38), fill=GREY, anchor="mm")
        lay = lay.rotate([-4, 3, -2][i], resample=Image.BICUBIC, expand=False)
        sc = 1.0 + (1 - q) * 0.25
        if sc != 1.0:
            lay = lay.resize((int(lay.width * sc), int(lay.height * sc)), Image.BICUBIC)
        x = [300, 690, 540][i] if i < 2 else 540
        y = [640, 640, 940][i]
        img.paste(lay, (int(x - lay.width / 2), int(y - lay.height / 2)), lay)
    q = ease_out((p - 0.55) / 0.3)
    if q > 0:
        grad = RED
        d.text((W / 2, 1290), "鏀归挬瀛愶紝涓嶆敼浜鸿", font=F(CN, 86), fill=grad, anchor="mm")
        wobble_line(d, W / 2 - 330, W / 2 + 330, 1358, col=RED, w=10, seed=3)

def s_cta(d, img, p, t):
    q = ease_out(p / 0.4)
    y = 780 - (1 - q) * 60
    lay = Image.new("RGBA", (900, 620), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([8, 8, 892, 612], radius=40, fill=(255, 252, 246), outline=INK, width=8)
    ld.text((450, 150), "璇勮鍖烘墦", font=F(CN, 58), fill=GREY, anchor="mm")
    ld.text((450, 300), "妯℃澘", font=F(CN, 190), fill=RED, anchor="mm")
    ld.text((450, 470), "5 鏉＄殑鑴氭湰楠ㄦ灦 + 鍒嗛暅琛紝鐩存帴鍙戜綘", font=F(CN, 42), fill=INK, anchor="mm")
    img.paste(lay, (int(W / 2 - 450), int(y - 310)), lay)
    # arrow
    q2 = clamp01((p - 0.3) / 0.4)
    if q2 > 0:
        bounce = math.sin(t * 6) * 8 * q2
        ay = 1180 + bounce
        d.line([W / 2, ay, W / 2, ay + 130], fill=RED, width=12)
        d.polygon([(W / 2, ay + 175), (W / 2 - 34, ay + 110), (W / 2 + 34, ay + 110)], fill=RED)
    d.text((W / 2, 1620), "@浣犵殑璐﹀彿", font=F(CN, 52), fill=GREY, anchor="mm")

# ---------------------------------------------------------------- render
def draw_frame(marks, t, total):
    mk = marks[0]
    for m in marks:
        if t >= m["start"]:
            mk = m
    local = clamp01((t - mk["start"]) / max(1e-3, mk["dur"]))
    img = paper_base(dark=(mk["kind"] == "twist"))
    d = ImageDraw.Draw(img)
    d._image = img
    k = mk["kind"]
    if k == "hook":
        s_hook(d, local, t)
    elif k.startswith("trap"):
        s_trap(d, local, t, k)
        {"trap1": art_icon1, "trap2": art_icon2, "trap3": art_icon3,
         "trap4": art_icon4, "trap5": art_icon5}[k](d, local)
    elif k == "twist":
        s_twist(d, img, local, t)
        d = ImageDraw.Draw(img)
    elif k == "fix":
        s_fix(d, img, local, t)
    elif k == "cta":
        s_cta(d, img, local, t)
    progress_bar(d, t / total)
    return img


def render(scene_marks, total, audio, out_mp4, previews=None):
    marks = scene_marks
    cmd = [FFMPEG, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", audio,
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out_mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n_frames = int(total * FPS)
    for fi in range(n_frames):
        t = fi / FPS
        img = draw_frame(marks, t, total)
        proc.stdin.write(img.tobytes())
        if fi % 60 == 0:
            print(f"  frame {fi}/{n_frames}", flush=True)
    proc.stdin.close()
    proc.wait()
    return out_mp4

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    durs = synth_all()
    audio, marks, total = build_audio(durs)
    print("total duration", round(total, 2), "s")
    for m in marks:
        print(f"  {m['kind']:7s} {m['start']:6.2f} +{m['dur']:5.2f}")
    if mode in ("all", "video"):
        out = os.path.join(OUT_DIR, "short_v1.mp4")
        render(marks, total, audio, out)
        print("WROTE", out)
    if mode in ("all", "preview"):
        shots = [1.6, 6.2, 10.4, 14.4, 18.3, 22.0, 26.2, 31.0, 35.6]
        for i, tt in enumerate(shots):
            img = draw_frame(marks, tt, total)
            p = os.path.join(OUT_DIR, f"prev_{i}_{tt:.1f}.png")
            img.save(p)
            print("SHOT", p)

if __name__ == "__main__":
    main()

