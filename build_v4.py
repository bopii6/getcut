# -*- coding: utf-8 -*-
"""v4: closer to the printed-poster look — display type, halftone, riso offset,
camera push-in, music bed."""
import os, sys, math, asyncio, subprocess, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

W, H, FPS = 1080, 1920, 30
OUT = r"E:\getcut\build"
os.makedirs(OUT, exist_ok=True)
FFMPEG = r"C:\Users\wang\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"

PAPER = (243, 236, 219)
INK   = (24, 34, 58)
RED   = (219, 68, 38)
ORANGE= (238, 132, 52)
GREY  = (126, 118, 106)
DARK  = (10, 12, 16)
CREAM = (255, 248, 234)
LINE  = (206, 194, 172)

DISP = r"E:\getcut\ref\ZCOOLQingKeHuangYou.ttf"
LIT  = r"E:\getcut\ref\MaShanZheng.ttf"
BODY = r"C:\Windows\Fonts\msyhbd.ttc"

_fc = {}
def F(p, s, i=0):
    k = (p, int(s), i)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(p, int(s), index=i)
    return _fc[k]

def ease_out(t): t = max(0., min(1., t)); return 1 - (1 - t) ** 3
def ease_in(t):  t = max(0., min(1., t)); return t ** 3
def ease_back(t):
    t = max(0., min(1., t)); c1, c3 = 1.9, 2.9
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
def cl(t): return max(0., min(1., t))

# ---------------------------------------------------------------- texture
_GRAIN = None
_HALFTONE = None
def grain_img():
    global _GRAIN
    if _GRAIN is None:
        rng = np.random.default_rng(3)
        n = rng.normal(0, 9, (H, W, 1)).repeat(3, axis=2)
        _GRAIN = Image.fromarray(np.clip(128 + n, 0, 255).astype(np.uint8))
    return _GRAIN

def halftone_img(pitch=7):
    global _HALFTONE
    if _HALFTONE is None:
        base = Image.new("L", (W, H), 255)
        d = ImageDraw.Draw(base)
        for y in range(0, H, pitch):
            for x in range(0, W, pitch):
                r = pitch * 0.22
                d.ellipse([x - r, y - r, x + r, y + r], fill=225)
        _HALFTONE = base
    return _HALFTONE

def paper(dark=False, ht=0.5):
    base = Image.new("RGB", (W, H), DARK if dark else PAPER)
    if not dark and ht > 0:
        base = Image.composite(Image.new("RGB", (W, H), (232, 222, 202)),
                               base, halftone_img().point(lambda v: int(v * ht)))
    return Image.blend(base, grain_img(), 0.13 if not dark else 0.06)

def riso(d, xy, text, font, col=RED, ink_off=(4, 5), ghost=(238, 196, 120), anchor="mm", ghost_a=None):
    d.text(xy, text, font=font, fill=col, anchor=anchor)
    if ink_off:
        g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        gd.text((xy[0] + ink_off[0], xy[1] + ink_off[1]), text, font=font,
                fill=ghost + (70,), anchor=anchor)
        return g
    return None

def spray(img, cx, cy, r, col=RED, density=900, seed=1):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    rng = np.random.default_rng(seed)
    n = density
    ang = rng.uniform(0, 2 * math.pi, n)
    rad = r * np.sqrt(rng.uniform(0, 1, n)) ** 0.8
    for a, rr in zip(ang, rad):
        x, y = cx + math.cos(a) * rr, cy + math.sin(a) * rr
        s = rng.uniform(0.6, 2.4)
        al = int(26 * (1 - rr / r) + 6)
        d.ellipse([x - s, y - s, x + s, y + s], fill=col + (max(4, al),))
    lay = lay.filter(ImageFilter.GaussianBlur(1.2))
    return Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")

def cam(img, zoom=1.0, dx=0, dy=0):
    if abs(zoom - 1) < 1e-4 and dx == 0 and dy == 0:
        return img
    w, h = int(W / zoom), int(H / zoom)
    x = int((W - w) / 2 + dx)
    y = int((H - h) / 2 + dy)
    return img.crop((x, y, x + w, y + h)).resize((W, H), Image.BILINEAR)

def wobble(d, x0, x1, y, col=RED, w=11, amp=9, seed=0):
    rng = np.random.default_rng(seed)
    pts = [(x0 + (x1 - x0) * i / 23,
            y + math.sin(i / 23 * math.pi * 2.4) * amp * .5 + rng.normal(0, 1.6)) for i in range(24)]
    d.line(pts, fill=col, width=w, joint="curve")

def sparkle(d, x, y, r, col=RED):
    d.polygon([(x, y - r), (x + r * .3, y - r * .3), (x + r, y), (x + r * .3, y + r * .3),
               (x, y + r), (x - r * .3, y + r * .3), (x - r, y), (x - r * .3, y - r * .3)], fill=col)

def progress(d, p):
    d.rectangle([0, H - 10, W, H], fill=(214, 204, 184))
    d.rectangle([0, H - 10, int(W * cl(p)), H], fill=RED)

SCENES = [
    dict(k="hook",  vo="我把 AI 短视频发了三个月，私信是零。", pad=0.30),
    dict(k="trap1", vo="第一个坑，先想做什么内容，再想给谁看。", pad=0.24),
    dict(k="trap2", vo="第二个坑，一直换工具，从来不换结构。", pad=0.24),
    dict(k="trap3", vo="第三个坑，一条视频，只发一次。", pad=0.24),
    dict(k="trap4", vo="第四个坑，追热点，但不留人。", pad=0.24),
    dict(k="trap5", vo="第五个坑，只看播放量，不看私信。", pad=0.24),
    dict(k="twist", vo="问题不在工具，在那个词。", pad=0.26),
    dict(k="fix",   vo="固定角色，固定栏目，一周三条。改钩子，不改人设。", pad=0.26),
    dict(k="cta",   vo="评论区打模板，我把这五条的脚本骨架发你。", pad=0.80),
]

TRAPS = {
    "trap1": dict(n=1, l1="先做内容", l2="再想给谁看", hot=True,  note="内容不差，差在不知道做给谁"),
    "trap2": dict(n=2, l1="一直换工具", l2="从不换结构", hot=False, note="工具换一圈，问题一动不动"),
    "trap3": dict(n=3, l1="一条视频", l2="只发一次", hot=True,  note="只发一次，等于白发"),
    "trap4": dict(n=4, l1="追得动热点", l2="留不住人", hot=True,  note="热点吃完了，人没留下"),
    "trap5": dict(n=5, l1="只看播放量", l2="不看私信", hot=True,  note="播放是虚荣数字，私信才是生意"),
}

# ---------------------------------------------------------------- audio
def dur_of(p):
    with wave.open(p) as w:
        return w.getnframes() / float(w.getframerate())

def synth_vo():
    ad = os.path.join(OUT, "vo"); os.makedirs(ad, exist_ok=True)
    async def go():
        import edge_tts
        for i, s in enumerate(SCENES):
            mp3 = os.path.join(ad, f"{i:02d}.mp3")
            if not os.path.exists(mp3):
                await edge_tts.Communicate(s["vo"], "zh-CN-YunjianNeural", rate="+14%").save(mp3)
    asyncio.run(go())
    durs = []
    for i in range(len(SCENES)):
        mp3 = os.path.join(ad, f"{i:02d}.mp3"); wav = os.path.join(ad, f"{i:02d}.wav")
        if not os.path.exists(wav):
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", mp3,
                            "-ar", "48000", "-ac", "1", wav], check=True)
        durs.append(dur_of(wav))
    return durs

SR = 48000
def env(length):
    return np.ones(int(SR * length), dtype=np.float32)

def kick(dur=0.28):
    n = int(SR * dur); t = np.linspace(0, dur, n, endpoint=False)
    f = 120 * np.exp(-t * 26) + 48
    ph = 2 * math.pi * np.cumsum(f) / SR
    return (np.sin(ph) * np.exp(-t * 12) * .9).astype(np.float32)

def hat(dur=0.06):
    n = int(SR * dur); t = np.linspace(0, dur, n, endpoint=False)
    x = np.random.default_rng(5).normal(0, 1, n)
    x = np.diff(np.concatenate([[0], x]))
    return (x * np.exp(-t * 90) * .18).astype(np.float32)

def snare(dur=0.18):
    n = int(SR * dur); t = np.linspace(0, dur, n, endpoint=False)
    x = np.random.default_rng(9).normal(0, 1, n) * np.exp(-t * 24)
    return (x * .35).astype(np.float32)

def bass(freq, dur):
    n = int(SR * dur); t = np.linspace(0, dur, n, endpoint=False)
    saw = 2 * ((t * freq) % 1) - 1
    x = saw * .5 + np.sin(2 * math.pi * freq * t) * .5
    return (x * np.exp(-t * 2.2) * .22).astype(np.float32)

def build_audio(durs):
    total = sum(d + s["pad"] for d, s in zip(durs, SCENES))
    n = int(SR * (total + .6))
    music = np.zeros(n, dtype=np.float32)
    bpm = 96.0
    beat = 60.0 / bpm
    k = kick(); h = hat(); s = snare()
    i = 0
    bar = 0
    while i * beat < total:
        pos = int(SR * i * beat)
        if i % 4 in (0, 2):
            music[pos:pos + len(k)] += k * .9
        if i % 4 in (1, 3):
            music[pos:pos + len(s)] += s * .5
        pos8 = int(SR * (i * beat + beat / 2))
        if pos8 + len(h) < n:
            music[pos8:pos8 + len(h)] += h * .5
        if i % 8 == 0:
            root = 55.0 if bar % 2 == 0 else 61.7
            b = bass(root, beat * 4)
            music[pos:pos + len(b)] += b
            bar += 1
        i += 1
    music[int(SR * total):] = 0

    vo = np.zeros(n, dtype=np.float32)
    marks, t0 = [], 0.0
    for i, (sc, d) in enumerate(zip(SCENES, durs)):
        pad = sc["pad"]
        marks.append(dict(kind=sc["k"], start=t0, dur=d + pad, vo=d))
        with wave.open(os.path.join(OUT, "vo", f"{i:02d}.wav")) as w:
            v = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.
        vo[int(SR * t0):int(SR * t0) + len(v)] += v
        t0 += d + pad

    # duck music under voice (200ms smoothing)
    win = int(SR * .12)
    kk = np.ones(win) / win
    energy = np.convolve(np.abs(vo), kk, mode="same")
    duck = 1.0 - np.clip(energy * 26, 0, 0.72)
    mix = music * duck * .55 + vo * 1.0

    # sfx
    for m in marks:
        if m["kind"] == "hook":
            ev = [(0.0, "thud", .9), (.05, "whoosh", .8)]
        elif m["kind"].startswith("trap"):
            ev = [(0.0, "pop", .85), (.02, "whoosh", .45), (m["vo"] * .55, "tick", .5)]
        elif m["kind"] == "twist":
            ev = [(0.0, "whoosh", .7), (m["vo"] * .52, "thud", 1.)]
        elif m["kind"] == "fix":
            ev = [(0.0, "pop", .8), (m["vo"] * .45, "pop", .6)]
        else:
            ev = [(0.0, "tick", .7), (.22, "pop", .7)]
        for at, kind, gain in ev:
            x = {"pop": pop, "whoosh": whoosh, "thud": thud, "tick": tick}[kind]() * gain * .5
            a = int(SR * (m["start"] + at))
            if a + len(x) < n:
                mix[a:a + len(x)] += x

    mix = mix / max(1e-6, float(np.abs(mix).max())) * .94
    out = os.path.join(OUT, "audio_v4.wav")
    with wave.open(out, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    return out, marks, total

def pop():
    n = int(SR * .18); t = np.linspace(0, .18, n, endpoint=False)
    f = 900 * np.exp(-t * 20) + 300
    return (np.sin(2 * math.pi * np.cumsum(f) / SR) * np.exp(-t * 26)).astype(np.float32)

def whoosh():
    n = int(SR * .32); t = np.linspace(0, .32, n, endpoint=False)
    x = np.random.default_rng(2).normal(0, 1, n)
    x = np.convolve(x, np.ones(24) / 24, mode="same")
    return (x * np.sin(np.pi * t / .32) ** 2 * .5).astype(np.float32)

def thud():
    n = int(SR * .5); t = np.linspace(0, .5, n, endpoint=False)
    return ((np.sin(2 * math.pi * 52 * t) * .95 + np.sin(2 * math.pi * 88 * t) * .3)
            * np.exp(-t * 9)).astype(np.float32)

def tick():
    n = int(SR * .1); t = np.linspace(0, .1, n, endpoint=False)
    return (np.sin(2 * math.pi * 1700 * t) * np.exp(-t * 70) * .5).astype(np.float32)

# ---------------------------------------------------------------- scenes
def vtext(img, xy, text, font, fill, angle=90):
    tmp = Image.new("RGBA", (int(font.getlength(text)) + 60, font.size + 60), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((tmp.width / 2, tmp.height / 2), text, font=font, fill=fill, anchor="mm")
    tmp = tmp.rotate(angle, expand=True, resample=Image.BICUBIC)
    img.paste(tmp, (int(xy[0] - tmp.width / 2), int(xy[1] - tmp.height / 2)), tmp)

def ghost_num(img, text, cx, cy, size, col=(240, 230, 210)):
    tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((cx, cy), text, font=F(DISP, size), fill=col + (255,), anchor="mm")
    tmp = tmp.rotate(-9, resample=Image.BICUBIC, center=(cx, cy))
    a = tmp.split()[3].point(lambda v: int(v * 0.34))
    img.paste(tmp, (0, 0), a)

def head(d, dark=False):
    c = (156, 148, 136) if dark else GREY
    d.text((W - 64, 92), "短视频避坑 / 01", font=F(DISP, 40), fill=c, anchor="rm")
    d.line([64, 1786, W - 64, 1786], fill=LINE if not dark else (60, 58, 54), width=3)
    d.text((64, 1844), "@你的账号", font=F(DISP, 38), fill=c, anchor="lm")
    d.text((W - 64, 1844), "每天一条 / 拆一个坑", font=F(DISP, 36), fill=c, anchor="rm")

def s_hook(d, img, p, t):
    d.text((64, 330), "我的第一个 AI 短视频号", font=F(DISP, 58), fill=INK, anchor="lm")
    val = 128.4 * ease_out(p / .42)
    v = f"{val:.1f}"
    d.text((64, 640), "播放量", font=F(DISP, 60), fill=GREY, anchor="lm")
    fl = F(DISP, 168)
    uw = F(DISP, 66).getlength("万")
    d.text((W - 64 - uw - 6, 640), v, font=fl, fill=INK, anchor="rm")
    d.text((W - 64, 672), "万", font=F(DISP, 66), fill=INK, anchor="rm")
    d.line([64, 800, W - 64, 800], fill=LINE, width=5)
    qq = ease_out((p - .26) / .28)
    if qq > 0:
        d.text((64, 1000), "私信", font=F(DISP, 60), fill=GREY, anchor="lm")
        d.text((W - 64, 1000 + (1 - qq) * 40), "0", font=F(DISP, 230), fill=RED, anchor="rm")
    d.line([64, 1200, W - 64, 1200], fill=LINE, width=5)
    if p > .46:
        txt = "这 5 个坑，我全踩了"
        tw = F(DISP, 80).getlength(txt) + 90
        lay = Image.new("RGBA", (int(tw + 50), 200), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        ld.rounded_rectangle([16, 16, 16 + tw, 182], radius=14, fill=(252, 244, 228), outline=INK, width=7)
        ld.text((16 + tw / 2, 100), txt, font=F(DISP, 80), fill=INK, anchor="mm")
        lay = lay.rotate(-2.2, resample=Image.BICUBIC)
        img.paste(lay, (int(W / 2 - lay.width / 2), 1330 + int((1 - ease_back((p - .46) / .24)) * 60)), lay)
    for i, (sx, sy, r) in enumerate([(96, 500, 26), (990, 440, 16), (950, 1240, 20)]):
        qqq = ease_back((p - .2 - i * .05) / .3)
        if qqq > 0:
            sparkle(d, sx, sy, r * qqq, col=RED if i != 1 else ORANGE)

def s_trap(d, p, t, key):
    cfg = TRAPS[key]
    a = ease_back(p / .22)
    # counter stamp
    lay = Image.new("RGBA", (300, 110), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([4, 4, 296, 106], radius=14, fill=INK)
    ld.text((150, 55), f"{cfg['n']} / 5", font=F(DISP, 56), fill=CREAM, anchor="mm")
    lay = lay.rotate(-4 + 8 * (1 - a), resample=Image.BICUBIC)
    d._image.paste(lay, (60, 250), lay)

    y = 1020 + (1 - ease_out(p / .3)) * 40
    d.text((W / 2, y), cfg["l1"], font=F(DISP, 152), fill=INK, anchor="mm")
    q2 = cl((p - .18) / .2)
    if q2 > 0:
        col2 = RED if cfg["hot"] else INK
        dy = (1 - ease_back(q2)) * 40
        d.text((W / 2, y + 200 + dy), cfg["l2"], font=F(DISP, 152), fill=col2, anchor="mm")
        if cfg["hot"]:
            wpx = F(DISP, 152).getlength(cfg["l2"])
            wobble(d, W / 2 - wpx / 2, W / 2 + wpx / 2, y + 200 + dy + 108, col=RED, w=10, seed=cfg["n"])
    if p > .40:
        d.text((W / 2, 1540), cfg["note"], font=F(DISP, 50), fill=GREY, anchor="mm")

def art1(d, p):
    cx, cy = W / 2, 720
    q = ease_back(p / .3)
    d.ellipse([cx - 74, cy - 74, cx + 74, cy + 74], fill=(212, 202, 184), outline=INK, width=7)
    d.rounded_rectangle([cx - 104, cy + 82, cx + 104, cy + 214], radius=54,
                        fill=(212, 202, 184), outline=INK, width=7)
    d.text((cx, cy - 8), "?", font=F(DISP, 86 * q), fill=INK, anchor="mm")

def art2(d, p):
    cx, cy = W / 2, 700
    for i, lab in enumerate(["工具 A", "工具 B", "工具 C"]):
        x = cx - 268 + i * 268
        d.rounded_rectangle([x - 100, cy - 108, x + 100, cy + 46], radius=12,
                            outline=(198, 188, 168), width=6, fill=(250, 243, 228))
        d.text((x, cy - 30), lab, font=F(DISP, 40), fill=(188, 178, 160), anchor="mm")
        d.line([x - 66, cy - 80, x + 66, cy + 20], fill=(214, 88, 66), width=8)
    d.rounded_rectangle([cx - 340, cy + 96, cx + 340, cy + 258], radius=14,
                        outline=INK, width=8, fill=(252, 244, 228))
    for i in range(3):
        d.ellipse([cx - 280 + i * 76, cy + 156, cx - 216 + i * 76, cy + 196], fill=INK)
    d.line([cx - 40, cy + 176, cx + 250, cy + 176], fill=INK, width=10)
    d.text((cx + 268, cy + 212), "结构", font=F(DISP, 38), fill=GREY, anchor="mm")

def art3(d, p):
    cx, cy = W / 2, 700
    d.rounded_rectangle([cx - 440, cy - 100, cx - 205, cy + 118], radius=12,
                        outline=INK, width=7, fill=(252, 244, 228))
    d.polygon([(cx - 356, cy - 44), (cx - 356, cy + 44), (cx - 280, cy)], fill=RED)
    d.text((cx - 322, cy + 84), "1 条", font=F(DISP, 36), fill=GREY, anchor="mm")
    for i in range(3):
        y = cy - 90 + i * 106; on = i == 0
        d.rounded_rectangle([cx + 40, y - 40, cx + 440, y + 40], radius=10,
                            outline=INK if on else (200, 190, 172), width=7,
                            fill=(252, 244, 228) if on else (236, 228, 212))
        d.text((cx + 240, y), ["已发", "空", "空"][i], font=F(DISP, 38),
               fill=INK if on else (192, 182, 164), anchor="mm")
    d.line([cx - 190, cy, cx + 20, cy], fill=INK, width=8)
    d.polygon([(cx + 24, cy), (cx - 6, cy - 17), (cx - 6, cy + 17)], fill=INK)

def art4(d, p):
    cx, cy = W / 2, 725
    d.polygon([(cx - 74, cy + 112), (cx - 14, cy - 124), (cx + 20, cy + 8),
               (cx + 76, cy - 62), (cx + 96, cy + 112)], fill=RED)
    d.polygon([(cx - 28, cy + 112), (cx + 6, cy - 16), (cx + 54, cy + 112)], fill=ORANGE)
    x0 = cx + 250
    d.ellipse([x0 - 26, cy - 64, x0 + 26, cy - 14], fill=INK)
    for a, b in [((x0, cy - 12), (x0, cy + 54)), ((x0, cy + 54), (x0 - 38, cy + 110)),
                 ((x0, cy + 54), (x0 + 38, cy + 104)), ((x0, cy + 4), (x0 - 44, cy + 26)),
                 ((x0, cy + 4), (x0 + 48, cy - 26))]:
        d.line([a, b], fill=INK, width=10)

def art5(d, p):
    cx, cy = W / 2, 725
    cw, ch = 820, 350
    d.rounded_rectangle([cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2],
                        radius=18, outline=INK, width=8, fill=(255, 250, 238))
    d.line([cx - cw / 2 + 4, cy - 76, cx + cw / 2 - 4, cy - 76], fill=LINE, width=6)
    d.ellipse([cx - cw / 2 + 34, cy - 128, cx - cw / 2 + 60, cy - 102], fill=(226, 116, 92))
    d.text((cx - cw / 2 + 76, cy - 114), "后台数据", font=F(DISP, 36), fill=GREY, anchor="lm")
    d.text((cx - cw / 2 + 42, cy - 6), "播放", font=F(DISP, 44), fill=GREY, anchor="lm")
    d.text((cx + cw / 2 - 42, cy - 10), "128.4", font=F(DISP, 78), fill=INK, anchor="rm")
    d.text((cx + cw / 2 - 42, cy + 34), "万", font=F(DISP, 40), fill=INK, anchor="rm")
    d.text((cx - cw / 2 + 42, cy + 104), "私信", font=F(DISP, 44), fill=GREY, anchor="lm")
    d.text((cx + cw / 2 - 42, cy + 100), "0", font=F(DISP, 84), fill=RED, anchor="rm")

def s_twist(d, img, p, t):
    q = ease_out(p / .4)
    lay = Image.new("RGB", (W, H), (0, 0, 0))
    ld = ImageDraw.Draw(lay)
    for i in range(9):
        k = 1 - i / 9
        ld.rectangle([W / 2 - 460 * k, 0, W / 2 + 460 * k, 900 + 500 * k],
                     fill=tuple(int(c * .055 * k * q) for c in (255, 232, 198)))
    lay = lay.filter(ImageFilter.GaussianBlur(110))
    img.paste(ImageChops.screen(img, lay))
    d = ImageDraw.Draw(img)
    if p > .03:
        d.text((W / 2, 520), "问题不在工具", font=F(DISP, 62), fill=(232, 224, 210), anchor="mm")
    if p > .2:
        d.text((W / 2, 636), "在那个词", font=F(DISP, 62), fill=(140, 134, 124), anchor="mm")
    q3 = cl((p - .36) / .28)
    if q3 > 0:
        sc = 1.5 - .5 * ease_back(q3)
        rs = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        rd = ImageDraw.Draw(rs)
        rd.text((W / 2, 940), "重复", font=F(DISP, int(400 * sc)), fill=RED + (60,), anchor="mm")
        rs = rs.filter(ImageFilter.GaussianBlur(18))
        img.paste(Image.composite(Image.new("RGB", (W, H), RED), img, rs.split()[3]), (0, 0), rs)
        d = ImageDraw.Draw(img)
        d.text((W / 2, 940), "重复", font=F(DISP, 400 * sc), fill=CREAM, anchor="mm")
    if q3 > .5:
        d.text((W / 2, 1230), "同一条，做成不同版本，反复发", font=F(DISP, 52),
               fill=(212, 204, 188), anchor="mm")

def s_fix(d, img, p, t):
    d.text((W / 2, 380), "把这三个钉死", font=F(DISP, 96), fill=INK, anchor="mm")
    items = [("固定角色", "同一张脸", 300, 620), ("固定栏目", "同一个名字", 782, 620),
             ("一周 3 条", "同一个节奏", 540, 980)]
    for i, (a, b, x, y) in enumerate(items):
        q = ease_back((p - i * .09) / .28)
        if q <= 0:
            continue
        lay = Image.new("RGBA", (380, 300), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        ld.rounded_rectangle([10, 10, 370, 290], radius=14, fill=(252, 244, 228), outline=INK, width=7)
        ld.text((190, 110), a, font=F(DISP, 62), fill=INK, anchor="mm")
        ld.text((190, 200), b, font=F(DISP, 40), fill=GREY, anchor="mm")
        lay = lay.rotate([-4, 3, -2][i], resample=Image.BICUBIC)
        sc = 1 + (1 - q) * .2
        lay = lay.resize((int(lay.width * sc), int(lay.height * sc)), Image.BICUBIC)
        img.paste(lay, (int(x - lay.width / 2), int(y - lay.height / 2)), lay)
    if p > .5:
        d.text((W / 2, 1330), "改钩子，不改人设", font=F(DISP, 108), fill=RED, anchor="mm")
        wobble(d, W / 2 - 360, W / 2 + 360, 1404, col=RED, w=11, seed=7)

def s_cta(d, img, p, t):
    q = ease_out(p / .3)
    y = 780 - (1 - q) * 50
    lay = Image.new("RGBA", (940, 660), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([10, 10, 930, 650], radius=20, fill=(255, 250, 238), outline=INK, width=9)
    ld.text((470, 150), "评论区打", font=F(DISP, 64), fill=GREY, anchor="mm")
    ld.text((470, 320), "模板", font=F(DISP, 210), fill=RED, anchor="mm")
    ld.text((470, 500), "5 条脚本骨架 + 分镜表，直接发你", font=F(DISP, 44), fill=INK, anchor="mm")
    img.paste(lay, (int(W / 2 - 470), int(y - 330)), lay)
    if p > .25:
        ay = 1170 + math.sin(t * 7) * 9
        d.line([W / 2, ay, W / 2, ay + 120], fill=RED, width=14)
        d.polygon([(W / 2, ay + 172), (W / 2 - 38, ay + 100), (W / 2 + 38, ay + 100)], fill=RED)
    if p > .45:
        d.text((W / 2, 1580), "打「模板」，私信自动回", font=F(DISP, 46), fill=GREY, anchor="mm")

SCENE_FN = {"hook": s_hook, "trap1": s_trap, "trap2": s_trap, "trap3": s_trap,
            "trap4": s_trap, "trap5": s_trap, "twist": s_twist, "fix": s_fix, "cta": s_cta}
ART = {"trap1": art1, "trap2": art2, "trap3": art3, "trap4": art4, "trap5": art5}

def draw_frame(marks, t, total):
    mk = marks[0]
    for m in marks:
        if t >= m["start"]:
            mk = m
    local = cl((t - mk["start"]) / max(1e-3, mk["dur"]))
    k = mk["kind"]
    dark = k == "twist"
    img = paper(dark=dark)
    if not dark:
        if k == "hook":
            img = spray(img, W * .78, 640, 420, col=(226, 96, 58), density=700, seed=4)
        if k in ("trap5", "fix"):
            img = spray(img, W * .5, 900, 460, col=(230, 150, 70), density=420, seed=9)
    d = ImageDraw.Draw(img)
    d._image = img
    if k.startswith("trap"):
        ghost_num(img, f"0{TRAPS[k]['n']}", W / 2, 1470, 780)
        d = ImageDraw.Draw(img)
        d._image = img
        s_trap(d, local, t, k)
        ART[k](d, local)
    elif k == "twist":
        s_twist(d, img, local, t)
        d = ImageDraw.Draw(img)
    else:
        SCENE_FN[k](d, img, local, t)
    if not dark:
        vtext(img, (36, 1010), "AI 短视频避坑指南", F(DISP, 34), (192, 182, 164, 150))
    head(d, dark=dark)
    progress(d, t / total)
    # camera push-in (per scene)
    z = 1.0 + .055 * cl(local) ** 1.3
    if k == "twist":
        z = 1.02 + .03 * cl(local)
    img = cam(img, zoom=z)
    # micro shake on cut
    if local < .06:
        sh = int(6 * (1 - local / .06))
        img = cam(img, zoom=1.0, dx=sh, dy=-sh // 2)
    return img

def render(marks, total, audio, out):
    cmd = [FFMPEG, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", audio, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", out]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(total * FPS)
    for fi in range(n):
        pr.stdin.write(draw_frame(marks, fi / FPS, total).tobytes())
        if fi % 90 == 0:
            print(f"  {fi}/{n}", flush=True)
    pr.stdin.close(); pr.wait()
    return out

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    durs = synth_vo()
    audio, marks, total = build_audio(durs)
    print("total", round(total, 2))
    if mode in ("all", "preview"):
        for i, tt in enumerate([1.8, 6.0, 9.8, 13.6, 17.4, 21.2, 25.2, 30.0, 34.6]):
            p = os.path.join(OUT, f"v4_{i}.png")
            draw_frame(marks, tt, total).save(p)
            print("SHOT", p)
    if mode in ("all", "video"):
        o = os.path.join(OUT, "short_v4.mp4")
        render(marks, total, audio, o)
        print("WROTE", o)

if __name__ == "__main__":
    main()
