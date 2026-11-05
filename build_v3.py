# -*- coding: utf-8 -*-
"""v3: 9:16 'trap list' short, bizdevelo/vidguy format. Tighter layout, series frame."""
import os, sys, math, asyncio, subprocess, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
OUT_DIR = r"E:\getcut\build"
os.makedirs(OUT_DIR, exist_ok=True)
FFMPEG = r"C:\Users\wang\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"

PAPER = (246, 240, 225)
INK   = (26, 42, 74)
RED   = (226, 74, 40)
GREY  = (128, 122, 112)
DARK  = (12, 14, 18)
CREAM = (255, 250, 240)
LINE  = (214, 204, 186)

CN  = r"C:\Windows\Fonts\msyhbd.ttc"
LAT = r"C:\Windows\Fonts\ariblk.ttf"

_fc = {}
def F(path, size, index=0):
    k = (path, int(size), index)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(path, int(size), index=index)
    return _fc[k]

def ease_out(t):
    t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3

def ease_back(t):
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2

def clamp01(t):
    return max(0.0, min(1.0, t))

GRAIN = None
def paper_base(dark=False):
    global GRAIN
    if GRAIN is None:
        rng = np.random.default_rng(7)
        n = rng.normal(0, 7, (H, W, 1)).repeat(3, axis=2)
        GRAIN = Image.fromarray(np.clip(128 + n, 0, 255).astype(np.uint8))
    base = Image.new("RGB", (W, H), DARK if dark else PAPER)
    return Image.blend(base, GRAIN, 0.05 if dark else 0.10)

def sparkle(d, x, y, r, col=RED):
    d.polygon([(x, y - r), (x + r * .28, y - r * .28), (x + r, y), (x + r * .28, y + r * .28),
               (x, y + r), (x - r * .28, y + r * .28), (x - r, y), (x - r * .28, y - r * .28)], fill=col)

def wobble(d, x0, x1, y, col=RED, w=10, amp=7, seed=0):
    rng = np.random.default_rng(seed)
    pts = [(x0 + (x1 - x0) * i / 23,
            y + math.sin(i / 23 * math.pi * 2.2) * amp * .45 + rng.normal(0, 1.2)) for i in range(24)]
    d.line(pts, fill=col, width=w, joint="curve")

def pill(text, font, fg=CREAM, bg=INK, pad=(34, 16)):
    tw = font.getlength(text)
    lw, lh = tw + pad[0] * 2, font.size + pad[1] * 2
    layer = Image.new("RGBA", (int(lw + 20), int(lh + 20)), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle([10, 10, 10 + lw, 10 + lh], radius=lh / 2, fill=bg)
    ld.text((10 + lw / 2, 10 + lh / 2), text, font=font, fill=fg, anchor="mm")
    return layer

def paste_at(base, layer, xy):
    base.paste(layer, (int(xy[0] - layer.width / 2), int(xy[1] - layer.height / 2)), layer)

def beam(img, cx, cy, w, h, strength=1.0):
    lay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(lay)
    for i in range(10):
        k = 1 - i / 10
        d.rectangle([cx - w * k / 2, 0, cx + w * k / 2, cy + h * k],
                    fill=tuple(int(c * 26 * k * strength / 10) for c in (255, 236, 205)))
    d.ellipse([cx - w * .75, cy - h * .45, cx + w * .75, cy + h * .45],
              fill=tuple(int(c * 40 * strength) for c in (255, 240, 215)))
    lay = lay.filter(ImageFilter.GaussianBlur(90))
    return Image.blend(img, Image.blend(img, lay, 0.95), 0.75)

def chrome(d, series="AI 短视频避坑 · 第 01 期", dark=False):
    c = (150, 145, 135) if dark else GREY
    d.text((W - 70, 96), series, font=F(CN, 34), fill=c, anchor="rm")
    if not dark:
        d.line([70, 1780, W - 70, 1780], fill=LINE, width=3)
    d.text((70, 1836), "@你的账号", font=F(CN, 38), fill=c, anchor="lm")
    d.text((W - 70, 1836), "每天一条，拆一个坑", font=F(CN, 34), fill=c, anchor="rm")

def progress_bar(d, p):
    d.rectangle([0, H - 8, W, H], fill=(226, 220, 205))
    d.rectangle([0, H - 8, int(W * clamp01(p)), H], fill=RED)

SCENES = [
    dict(k="hook",  vo="我把 AI 短视频发了三个月，私信是零。", pad=0.35),
    dict(k="trap1", vo="第一个坑，先想做什么内容，再想给谁看。", pad=0.26),
    dict(k="trap2", vo="第二个坑，一直换工具，从来不换结构。", pad=0.26),
    dict(k="trap3", vo="第三个坑，一条视频，只发一次。", pad=0.26),
    dict(k="trap4", vo="第四个坑，追热点，但不留人。", pad=0.26),
    dict(k="trap5", vo="第五个坑，只看播放量，不看私信。", pad=0.26),
    dict(k="twist", vo="问题不在工具，在那个词。", pad=0.28),
    dict(k="fix",   vo="固定角色，固定栏目，一周三条。改钩子，不改人设。", pad=0.28),
    dict(k="cta",   vo="评论区打模板，我把这五条的脚本骨架发你。", pad=0.85),
]

TRAPS = {
    "trap1": dict(n=1, l1="先做内容", l2="再想给谁看", hot=True),
    "trap2": dict(n=2, l1="一直换工具", l2="从不换结构", hot=False),
    "trap3": dict(n=3, l1="一条视频", l2="只发一次", hot=True),
    "trap4": dict(n=4, l1="追得动热点", l2="留不住人", hot=True),
    "trap5": dict(n=5, l1="只看播放量", l2="不看私信", hot=True),
}

def dur_of(p):
    with wave.open(p) as w:
        return w.getnframes() / float(w.getframerate())

def synth_all():
    ad = os.path.join(OUT_DIR, "vo"); os.makedirs(ad, exist_ok=True)
    texts = [s["vo"] for s in SCENES]
    async def go():
        import edge_tts
        for i, t in enumerate(texts):
            mp3 = os.path.join(ad, f"{i:02d}.mp3")
            if not os.path.exists(mp3):
                await edge_tts.Communicate(t, "zh-CN-YunjianNeural", rate="+12%").save(mp3)
    asyncio.run(go())
    durs = []
    for i in range(len(texts)):
        mp3 = os.path.join(ad, f"{i:02d}.mp3"); wav = os.path.join(ad, f"{i:02d}.wav")
        if not os.path.exists(wav):
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", mp3,
                            "-ar", "48000", "-ac", "1", wav], check=True)
        durs.append(dur_of(wav))
    return durs

def sfx(kind, sr=48000, dur=0.3):
    n = int(sr * dur); t = np.linspace(0, dur, n, endpoint=False)
    if kind == "pop":
        env = np.exp(-22 * t)
        x = np.sin(2 * math.pi * 760 * t) * env * .5 + np.sin(2 * math.pi * 1180 * t) * env * .2
    elif kind == "whoosh":
        noise = np.random.default_rng(1).normal(0, 1, n)
        env = np.sin(np.pi * t / dur) ** 2
        k = int(sr * .004)
        noise = np.convolve(noise, np.ones(k) / k, mode="same")
        x = noise * env * .28
    elif kind == "thud":
        env = np.exp(-16 * t)
        x = (np.sin(2 * math.pi * 58 * t) * .9 + np.sin(2 * math.pi * 92 * t) * .3) * env
    else:
        env = np.exp(-60 * t)
        x = np.sin(2 * math.pi * 1500 * t) * env * .25
    return x.astype(np.float32)

def build_audio(scene_durs):
    sr = 48000
    durs = [d + s["pad"] for d, s in zip(scene_durs, SCENES)]
    total = sum(durs)
    track = np.zeros(int(sr * (total + 1.)), dtype=np.float32)
    marks, t0 = [], 0.
    for i, (s, d, sd) in enumerate(zip(SCENES, durs, scene_durs)):
        marks.append(dict(kind=s["k"], start=t0, dur=d, vo_dur=sd))
        with wave.open(os.path.join(OUT_DIR, "vo", f"{i:02d}.wav")) as w:
            v = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.
        a = int(sr * t0)
        track[a:a + len(v)] += v
        if s["k"] == "hook":
            specs = [(0., "thud", .9), (.06, "whoosh", .7)]
        elif s["k"].startswith("trap"):
            specs = [(0., "pop", .8), (.02, "whoosh", .35)]
        elif s["k"] == "twist":
            specs = [(0., "whoosh", .6), (sd * .55, "thud", 1.)]
        elif s["k"] == "fix":
            specs = [(0., "pop", .7), (sd * .45, "pop", .5)]
        else:
            specs = [(0., "tick", .6), (.25, "pop", .6)]
        for at, kind, gain in specs:
            x = sfx(kind) * gain * .55
            a = int(sr * (t0 + at))
            if a + len(x) < len(track):
                track[a:a + len(x)] += x
        t0 += d
    track = track / max(1e-6, float(np.abs(track).max())) * .92
    out = os.path.join(OUT_DIR, "audio.wav")
    with wave.open(out, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((track * 32767).astype(np.int16).tobytes())
    return out, marks, total

# ---------------------------------------------------------------- scenes
def s_hook(d, img, p, t):
    q = ease_out(p / .35)
    d.text((70, 300), "我的第一个 AI 短视频号", font=F(CN, 44), fill=GREY, anchor="lm")
    rows = [("播放量", "128.4 万", INK, 108, 560), ("私信", "0", RED, 150, 810)]
    for i, (lab, val, col, fs, y) in enumerate(rows):
        qq = ease_out((p - .08 - i * .12) / .35)
        if qq <= 0:
            continue
        d.text((70, y), lab, font=F(CN, 52), fill=GREY, anchor="lm")
        off = (1 - qq) * 40
        d.text((W - 70, y + off), val, font=F(LAT, fs), fill=col, anchor="rm")
    for yy in (690, 940):
        d.line([70, yy, W - 70, yy], fill=LINE, width=4)
    if p > .45:
        txt = "这 5 个坑，我全踩了"
        tw = F(CN, 66).getlength(txt) + 90
        lay = Image.new("RGBA", (int(tw + 40), 170), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        ld.rounded_rectangle([14, 14, 14 + tw, 150], radius=16, fill=(252, 246, 232), outline=INK, width=6)
        ld.text((14 + tw / 2, 84), txt, font=F(CN, 66), fill=INK, anchor="mm")
        lay = lay.rotate(-1.6, resample=Image.BICUBIC)
        img.paste(lay, (int(W / 2 - lay.width / 2), 1150), lay)
    for i, (sx, sy, r) in enumerate([(120, 470, 24), (960, 380, 16), (900, 1080, 20)]):
        qq = ease_back((p - .2 - i * .07) / .3)
        if qq > 0:
            sparkle(d, sx, sy, r * qq, col=RED if i != 1 else (238, 170, 60))

def s_trap(d, p, t, key):
    cfg = TRAPS[key]
    paste_at(d._image, pill(f"{cfg['n']} / 5", F(LAT, 34)), (150, 300))
    d.text((W - 70, 300), f"0{cfg['n']}", font=F(LAT, 110), fill=(228, 219, 202), anchor="rm")
    a = ease_out(p / .42)
    y = 900 + (1 - a) * 50
    d.text((W / 2, y), cfg["l1"], font=F(CN, 126), fill=INK, anchor="mm")
    col2 = RED if cfg["hot"] else INK
    d.text((W / 2, y + 176), cfg["l2"], font=F(CN, 126), fill=col2, anchor="mm")
    if cfg["hot"]:
        wpx = F(CN, 126).getlength(cfg["l2"])
        wobble(d, W / 2 - wpx / 2, W / 2 + wpx / 2, y + 176 + 92, col=RED, w=9, seed=cfg["n"])
    if p > .5 and not cfg["hot"]:
        d.text((W / 2, y + 330), "工具换了一圈，问题一动不动", font=F(CN, 42), fill=GREY, anchor="mm")

def art_icon1(d, p):
    q = ease_back(p / .4); cx, cy = W / 2, 560
    d.ellipse([cx - 70, cy - 70, cx + 70, cy + 70], fill=(208, 200, 186), outline=INK, width=6)
    d.rounded_rectangle([cx - 100, cy + 78, cx + 100, cy + 205], radius=58,
                        fill=(208, 200, 186), outline=INK, width=6)
    d.text((cx, cy - 10), "?", font=F(LAT, 74 * q), fill=INK, anchor="mm")
    d.text((cx, cy + 285), "谁在看？给谁看？", font=F(CN, 40), fill=GREY, anchor="mm")

def art_icon2(d, p):
    cx, cy = W / 2, 520
    for i, lab in enumerate(["工具 A", "工具 B", "工具 C"]):
        x = cx - 265 + i * 265
        d.rounded_rectangle([x - 96, cy - 105, x + 96, cy + 45], radius=16,
                            outline=(200, 192, 176), width=5, fill=(250, 245, 234))
        d.text((x, cy - 30), lab, font=F(CN, 36), fill=(190, 182, 166), anchor="mm")
        d.line([x - 62, cy - 78, x + 62, cy + 18], fill=(216, 96, 76), width=6)
    d.rounded_rectangle([cx - 330, cy + 90, cx + 330, cy + 250], radius=18,
                        outline=INK, width=7, fill=(252, 246, 232))
    for i in range(3):
        d.ellipse([cx - 270 + i * 72, cy + 148, cx - 208 + i * 72, cy + 186], fill=INK)
    d.line([cx - 40, cy + 168, cx + 240, cy + 168], fill=INK, width=9)
    d.text((cx + 250, cy + 206), "结构", font=F(CN, 34), fill=GREY, anchor="mm")

def art_icon3(d, p):
    cx, cy = W / 2, 520
    d.rounded_rectangle([cx - 430, cy - 100, cx - 200, cy + 110], radius=14,
                        outline=INK, width=6, fill=(252, 246, 232))
    d.polygon([(cx - 348, cy - 42), (cx - 348, cy + 40), (cx - 275, cy - 1)], fill=RED)
    d.text((cx - 315, cy + 78), "1 条", font=F(CN, 32), fill=GREY, anchor="mm")
    for i in range(3):
        y = cy - 88 + i * 104; on = i == 0
        d.rounded_rectangle([cx + 40, y - 38, cx + 430, y + 38], radius=12,
                            outline=INK if on else (202, 194, 178), width=6,
                            fill=(252, 246, 232) if on else (238, 232, 220))
        d.text((cx + 235, y), ["已发", "空", "空"][i], font=F(CN, 34),
               fill=INK if on else (192, 184, 168), anchor="mm")
    d.line([cx - 180, cy, cx + 20, cy], fill=INK, width=7)
    d.polygon([(cx + 22, cy), (cx - 4, cy - 16), (cx - 4, cy + 16)], fill=INK)

def art_icon4(d, p):
    cx, cy = W / 2, 540
    d.polygon([(cx - 70, cy + 110), (cx - 12, cy - 120), (cx + 18, cy + 8),
               (cx + 72, cy - 60), (cx + 92, cy + 110)], fill=RED)
    d.polygon([(cx - 26, cy + 110), (cx + 6, cy - 16), (cx + 52, cy + 110)], fill=(246, 176, 60))
    x0 = cx + 240
    d.ellipse([x0 - 24, cy - 62, x0 + 24, cy - 14], fill=INK)
    d.line([x0, cy - 12, x0, cy + 52], fill=INK, width=9)
    d.line([x0, cy + 52, x0 - 36, cy + 108], fill=INK, width=9)
    d.line([x0, cy + 52, x0 + 36, cy + 102], fill=INK, width=9)
    d.line([x0, cy + 4, x0 - 42, cy + 26], fill=INK, width=9)
    d.line([x0, cy + 4, x0 + 46, cy - 26], fill=INK, width=9)

def art_icon5(d, p):
    cx, cy = W / 2, 540
    cw, ch = 800, 350
    d.rounded_rectangle([cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2],
                        radius=26, outline=INK, width=7, fill=(255, 252, 246))
    d.line([cx - cw / 2 + 3, cy - 78, cx + cw / 2 - 3, cy - 78], fill=LINE, width=5)
    d.ellipse([cx - cw / 2 + 34, cy - 128, cx - cw / 2 + 58, cy - 104], fill=(232, 120, 96))
    d.text((cx - cw / 2 + 74, cy - 116), "后台数据", font=F(CN, 32), fill=GREY, anchor="lm")
    d.text((cx - cw / 2 + 40, cy - 8), "播放", font=F(CN, 42), fill=GREY, anchor="lm")
    d.text((cx + cw / 2 - 40, cy - 12), "128.4 万", font=F(LAT, 68), fill=INK, anchor="rm")
    d.text((cx - cw / 2 + 40, cy + 104), "私信", font=F(CN, 42), fill=GREY, anchor="lm")
    d.text((cx + cw / 2 - 40, cy + 100), "0", font=F(LAT, 72), fill=RED, anchor="rm")

def s_twist(d, img, p, t):
    k = ease_out(p / .45)
    img.paste(beam(img, W / 2, 900, 900 * (.7 + .3 * k), 700, strength=k))
    if p > .04:
        d.text((W / 2, 520), "问题不在工具", font=F(CN, 54), fill=(236, 230, 218), anchor="mm")
    if p > .22:
        d.text((W / 2, 640), "在那个词", font=F(CN, 54), fill=(150, 144, 134), anchor="mm")
    q3 = clamp01((p - .38) / .3)
    if q3 > 0:
        d.text((W / 2, 940), "重复", font=F(CN, 330 * (1.34 - .34 * ease_back(q3))),
               fill=(255, 250, 240), anchor="mm")
    if q3 > .55:
        d.text((W / 2, 1200), "同一条，做成不同版本，反复发", font=F(CN, 48),
               fill=(218, 210, 194), anchor="mm")

def s_fix(d, img, p, t):
    d.text((W / 2, 380), "把这三个钉死", font=F(CN, 78), fill=INK, anchor="mm")
    items = [("固定角色", "同一张脸", 300, 620), ("固定栏目", "同一个名字", 780, 620),
             ("一周 3 条", "同一个节奏", 540, 960)]
    for i, (a, b, x, y) in enumerate(items):
        q = ease_back((p - i * .1) / .32)
        if q <= 0:
            continue
        lay = Image.new("RGBA", (360, 280), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        ld.rounded_rectangle([8, 8, 352, 272], radius=22, fill=(252, 246, 232), outline=INK, width=6)
        ld.text((180, 104), a, font=F(CN, 56), fill=INK, anchor="mm")
        ld.text((180, 186), b, font=F(CN, 38), fill=GREY, anchor="mm")
        lay = lay.rotate([-4, 3, -2][i], resample=Image.BICUBIC, expand=False)
        sc = 1. + (1 - q) * .22
        lay = lay.resize((int(lay.width * sc), int(lay.height * sc)), Image.BICUBIC)
        img.paste(lay, (int(x - lay.width / 2), int(y - lay.height / 2)), lay)
    if p > .55:
        d.text((W / 2, 1330), "改钩子，不改人设", font=F(CN, 92), fill=RED, anchor="mm")
        wobble(d, W / 2 - 340, W / 2 + 340, 1400, col=RED, w=10, seed=3)

def s_cta(d, img, p, t):
    q = ease_out(p / .38)
    y = 760 - (1 - q) * 50
    lay = Image.new("RGBA", (920, 640), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([8, 8, 912, 632], radius=40, fill=(255, 252, 246), outline=INK, width=8)
    ld.text((460, 150), "评论区打", font=F(CN, 58), fill=GREY, anchor="mm")
    ld.text((460, 310), "模板", font=F(CN, 195), fill=RED, anchor="mm")
    ld.text((460, 490), "5 条脚本骨架 + 分镜表，直接发你", font=F(CN, 40), fill=INK, anchor="mm")
    img.paste(lay, (int(W / 2 - 460), int(y - 320)), lay)
    if p > .3:
        ay = 1150 + math.sin(t * 6) * 8
        d.line([W / 2, ay, W / 2, ay + 120], fill=RED, width=12)
        d.polygon([(W / 2, ay + 165), (W / 2 - 34, ay + 100), (W / 2 + 34, ay + 100)], fill=RED)
    if p > .5:
        d.text((W / 2, 1560), "打「模板」，私信自动回", font=F(CN, 42), fill=GREY, anchor="mm")

def draw_frame(marks, t, total):
    mk = marks[0]
    for m in marks:
        if t >= m["start"]:
            mk = m
    local = clamp01((t - mk["start"]) / max(1e-3, mk["dur"]))
    k = mk["kind"]
    dark = k == "dark" or k == "twist"
    img = paper_base(dark=dark)
    if k == "twist":
        img = paper_base(dark=True)
    d = ImageDraw.Draw(img); d._image = img
    if k == "hook":
        s_hook(d, img, local, t)
    elif k.startswith("trap"):
        s_trap(d, local, t, k)
        {"trap1": art_icon1, "trap2": art_icon2, "trap3": art_icon3,
         "trap4": art_icon4, "trap5": art_icon5}[k](d, local)
    elif k == "twist":
        s_twist(d, img, local, t); d = ImageDraw.Draw(img)
    elif k == "fix":
        s_fix(d, img, local, t)
    elif k == "cta":
        s_cta(d, img, local, t)
    chrome(d, dark=dark)
    progress_bar(d, t / total)
    return img

def render(marks, total, audio, out_mp4):
    cmd = [FFMPEG, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", audio, "-c:v", "libx264", "-preset", "medium", "-crf", "19",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", out_mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(total * FPS)
    for fi in range(n):
        proc.stdin.write(draw_frame(marks, fi / FPS, total).tobytes())
        if fi % 90 == 0:
            print(f"  frame {fi}/{n}", flush=True)
    proc.stdin.close(); proc.wait()
    return out_mp4

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    durs = synth_all()
    audio, marks, total = build_audio(durs)
    print("total", round(total, 2), "s")
    if mode in ("all", "preview"):
        for i, tt in enumerate([1.5, 6.0, 10.2, 14.2, 18.2, 22.0, 26.0, 31.0, 35.5]):
            p = os.path.join(OUT_DIR, f"v3_{i}.png")
            draw_frame(marks, tt, total).save(p)
            print("SHOT", p)
    if mode in ("all", "video"):
        out = os.path.join(OUT_DIR, "short_v3.mp4")
        render(marks, total, audio, out)
        print("WROTE", out)

if __name__ == "__main__":
    main()
