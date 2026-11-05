# -*- coding: utf-8 -*-
"""Build a 9:16 'trap list' short in the bizdevelo / vidguy format."""
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
DARK  = (14, 17, 22)
CREAM = (255, 250, 240)

CN  = r"C:\Windows\Fonts\msyhbd.ttc"
LAT = r"C:\Windows\Fonts\ariblk.ttf"

_fc = {}
def F(path, size, index=0):
    k = (path, int(size), index)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(path, int(size), index=index)
    return _fc[k]

def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3

def ease_back(t):
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2

def clamp01(t):
    return max(0.0, min(1.0, t))

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
        return Image.blend(Image.new("RGB", (W, H), DARK), GRAIN, 0.05)
    return Image.blend(Image.new("RGB", (W, H), PAPER), GRAIN, 0.10)

def sparkle(d, x, y, r, col=RED):
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

def glow(img, center, radius, color=(255, 240, 210), strength=1.0):
    lay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(lay)
    for i in range(6):
        r = radius * (1 - i * 0.14)
        a = int(38 * strength * (i + 1) / 6)
        d.ellipse([center[0] - r, center[1] - r, center[0] + r, center[1] + r],
                  fill=tuple(int(c * a / 60) for c in color))
    lay = lay.filter(ImageFilter.GaussianBlur(70))
    return Image.blend(img, Image.blend(img, lay, 0.9), 0.55)

def progress_bar(d, p):
    d.rectangle([0, H - 8, W, H], fill=(226, 220, 205))
    d.rectangle([0, H - 8, int(W * clamp01(p)), H], fill=RED)

SCENES = [
    dict(k="hook",  vo="我把 AI 短视频发了三个月，私信是零。", pad=0.35),
    dict(k="trap1", vo="第一个坑，先想做什么内容，再想给谁看。", pad=0.28),
    dict(k="trap2", vo="第二个坑，一直换工具，从来不换结构。", pad=0.28),
    dict(k="trap3", vo="第三个坑，一条视频，只发一次。", pad=0.28),
    dict(k="trap4", vo="第四个坑，追热点，但不留人。", pad=0.28),
    dict(k="trap5", vo="第五个坑，只看播放量，不看私信。", pad=0.28),
    dict(k="twist", vo="问题不在工具，在那个词。", pad=0.30),
    dict(k="fix",   vo="固定角色，固定栏目，一周三条。改钩子，不改人设。", pad=0.30),
    dict(k="cta",   vo="评论区打模板，我把这五条的脚本骨架发你。", pad=0.90),
]

TRAPS = {
    "trap1": dict(n=1, l1="先做内容", l2="再想给谁看", key="再想给谁看"),
    "trap2": dict(n=2, l1="一直换工具", l2="从不换结构", key="结构"),
    "trap3": dict(n=3, l1="一条视频",   l2="只发一次",   key="只发一次"),
    "trap4": dict(n=4, l1="追得动热点", l2="留不住人",   key="留不住人"),
    "trap5": dict(n=5, l1="只看播放量", l2="不看私信",   key="私信"),
}

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
    else:
        env = np.exp(-60 * t)
        x = np.sin(2 * math.pi * 1500 * t) * env * 0.25
    return x.astype(np.float32)

def build_audio(scene_durs):
    sr = 48000
    durs = [d + s["pad"] for d, s in zip(scene_durs, SCENES)]
    total = sum(durs)
    track = np.zeros(int(sr * (total + 1.0)), dtype=np.float32)
    marks, t0 = [], 0.0
    for i, (s, d, sd) in enumerate(zip(SCENES, durs, scene_durs)):
        marks.append(dict(kind=s["k"], start=t0, dur=d, vo_dur=sd))
        with wave.open(os.path.join(OUT_DIR, "vo", f"{i:02d}.wav")) as w:
            v = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        a = int(sr * t0)
        track[a:a + len(v)] += v
        if s["k"] == "hook":
            specs = [(0.0, "thud", 0.9), (0.06, "whoosh", 0.7)]
        elif s["k"].startswith("trap"):
            specs = [(0.0, "pop", 0.8), (0.02, "whoosh", 0.35)]
        elif s["k"] == "twist":
            specs = [(0.0, "whoosh", 0.6), (sd * 0.55, "thud", 1.0)]
        elif s["k"] == "fix":
            specs = [(0.0, "pop", 0.7), (sd * 0.45, "pop", 0.5)]
        else:
            specs = [(0.0, "tick", 0.6), (0.25, "pop", 0.6)]
        for at, kind, gain in specs:
            x = sfx(kind) * gain * 0.55
            a = int(sr * (t0 + at))
            if a + len(x) < len(track):
                track[a:a + len(x)] += x
        t0 += d
    peak = max(1e-6, float(np.abs(track).max()))
    track = track / peak * 0.92
    out = os.path.join(OUT_DIR, "audio.wav")
    with wave.open(out, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((track * 32767).astype(np.int16).tobytes())
    return out, marks, total

def s_hook(d, p, t):
    a = ease_back(p / 0.45)
    d.text((W / 2, 470), "AI 短视频 · 三个月", font=F(CN, 46), fill=GREY, anchor="mm")
    d.text((W / 2 - 40, 800), "0", font=F(LAT, 430 * (1.55 - 0.55 * a)), fill=RED, anchor="mm")
    d.text((W / 2 + 190, 880), "私信", font=F(CN, 104), fill=INK, anchor="mm")
    d.text((W / 2, 1075), "发了三个月，一条没回", font=F(CN, 52), fill=INK, anchor="mm")
    txt = "这 5 个坑，我全踩了"
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
    paste_at(d._image, pill(f"{cfg['n']}/5", F(LAT, 34)), (150, 135))
    d.text((W - 110, 150), f"0{cfg['n']}", font=F(LAT, 120), fill=(226, 216, 198), anchor="rm")
    a = ease_out(p / 0.42)
    y1 = 720 + (1 - a) * 60
    d.text((W / 2, y1), cfg["l1"], font=F(CN, 118), fill=INK, anchor="mm")
    col2 = RED if cfg["key"] == cfg["l2"] else INK
    d.text((W / 2, y1 + 168), cfg["l2"], font=F(CN, 118), fill=col2, anchor="mm")
    if cfg["key"] == cfg["l2"]:
        wpx = F(CN, 118).getlength(cfg["l2"])
        wobble_line(d, W / 2 - wpx / 2, W / 2 + wpx / 2, y1 + 168 + 86, col=RED, w=9, seed=cfg["n"])

def art_icon1(d, p):
    q = ease_back(p / 0.4)
    cx, cy = W / 2, 430
    d.ellipse([cx - 66, cy - 66, cx + 66, cy + 66], fill=(206, 198, 184), outline=INK, width=6)
    d.rounded_rectangle([cx - 96, cy + 74, cx + 96, cy + 200], radius=60, fill=(206, 198, 184), outline=INK, width=6)
    d.text((cx, cy - 8), "?", font=F(LAT, 72 * q), fill=INK, anchor="mm")

def art_icon2(d, p):
    cx, cy = W / 2, 430
    for i, lab in enumerate(["工具 A", "工具 B", "工具 C"]):
        x = cx - 250 + i * 250
        d.rounded_rectangle([x - 92, cy - 120, x + 92, cy + 40], radius=16,
                            outline=(196, 188, 172), width=5, fill=(250, 245, 234))
        d.text((x, cy - 40), lab, font=F(CN, 38), fill=(186, 178, 162), anchor="mm")
        d.line([x - 60, cy - 90, x + 60, cy + 10], fill=(214, 76, 56), width=6)
    d.rounded_rectangle([cx - 300, cy + 70, cx + 300, cy + 210], radius=18,
                        outline=INK, width=7, fill=(252, 246, 232))
    for i in range(3):
        d.ellipse([cx - 250 + i * 70, cy + 122, cx - 190 + i * 70, cy + 158], fill=INK)
    d.line([cx - 40, cy + 140, cx + 210, cy + 140], fill=INK, width=8)
    d.text((cx, cy + 265), "结构不动", font=F(CN, 40), fill=GREY, anchor="mm")

def art_icon3(d, p):
    cx, cy = W / 2, 430
    d.rounded_rectangle([cx - 420, cy - 110, cx - 190, cy + 120], radius=14,
                        outline=INK, width=6, fill=(252, 246, 232))
    d.polygon([(cx - 340, cy - 45), (cx - 340, cy + 45), (cx - 265, cy)], fill=RED)
    d.text((cx - 305, cy + 88), "1 条", font=F(CN, 34), fill=GREY, anchor="mm")
    for i in range(3):
        y = cy - 90 + i * 110
        on = i == 0
        d.rounded_rectangle([cx + 40, y - 40, cx + 420, y + 40], radius=12,
                            outline=INK if on else (200, 192, 176), width=6,
                            fill=(252, 246, 232) if on else (238, 232, 220))
        d.text((cx + 230, y), ["已发", "空", "空"][i], font=F(CN, 36),
               fill=INK if on else (190, 182, 166), anchor="mm")
    d.line([cx - 170, cy + 5, cx + 20, cy + 5], fill=INK, width=7)
    d.polygon([(cx + 20, cy + 5), (cx - 6, cy - 12), (cx - 6, cy + 22)], fill=INK)

def art_icon4(d, p):
    cx, cy = W / 2, 430
    d.polygon([(cx - 60, cy + 120), (cx - 10, cy - 120), (cx + 20, cy + 10),
               (cx + 70, cy - 70), (cx + 90, cy + 120)], fill=RED)
    d.polygon([(cx - 20, cy + 120), (cx + 10, cy - 20), (cx + 55, cy + 120)], fill=(246, 176, 60))
    x0 = cx + 230
    d.ellipse([x0 - 24, cy - 60, x0 + 24, cy - 12], fill=INK)
    d.line([x0, cy - 10, x0, cy + 55], fill=INK, width=9)
    d.line([x0, cy + 55, x0 - 34, cy + 110], fill=INK, width=9)
    d.line([x0, cy + 55, x0 + 34, cy + 105], fill=INK, width=9)
    d.line([x0, cy + 5, x0 - 40, cy + 25], fill=INK, width=9)
    d.line([x0, cy + 5, x0 + 44, cy - 25], fill=INK, width=9)

def art_icon5(d, p):
    cx, cy = W / 2, 430
    cw, ch = 760, 340
    d.rounded_rectangle([cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2],
                        radius=26, outline=INK, width=7, fill=(255, 252, 246))
    d.line([cx - cw / 2, cy - 76, cx + cw / 2, cy - 76], fill=(228, 220, 204), width=5)
    d.text((cx - cw / 2 + 36, cy - 118), "创作者中心 · 近 28 天", font=F(CN, 34), fill=GREY, anchor="lm")
    d.text((cx - cw / 2 + 40, cy - 10), "播放量", font=F(CN, 40), fill=GREY, anchor="lm")
    d.text((cx + cw / 2 - 40, cy - 14), "128.4 万", font=F(LAT, 62), fill=INK, anchor="rm")
    d.text((cx - cw / 2 + 40, cy + 100), "私信", font=F(CN, 40), fill=GREY, anchor="lm")
    d.text((cx + cw / 2 - 40, cy + 96), "0", font=F(LAT, 66), fill=RED, anchor="rm")

def s_twist(d, img, p, t):
    k = ease_out(p / 0.5)
    img.paste(glow(img, (W / 2, 760), 620 * (0.5 + 0.6 * k), strength=k))
    if p > 0.05:
        d.text((W / 2, 560), "问题不在工具", font=F(CN, 56), fill=(238, 232, 220), anchor="mm")
    if p > 0.25:
        d.text((W / 2, 700), "在那个词", font=F(CN, 56), fill=(160, 154, 144), anchor="mm")
    q3 = clamp01((p - 0.42) / 0.3)
    if q3 > 0:
        d.text((W / 2, 1010), "重复", font=F(CN, 300 * (1.35 - 0.35 * ease_back(q3))),
               fill=(255, 250, 240), anchor="mm")
        if q3 > 0.5:
            d.text((W / 2, 1255), "同一条，做成不同版本，反复发", font=F(CN, 48),
                   fill=(214, 206, 190), anchor="mm")

def s_fix(d, img, p, t):
    d.text((W / 2, 300), "把这三个钉死", font=F(CN, 74), fill=INK, anchor="mm")
    items = [("固定角色", "同一张脸", 300, 640), ("固定栏目", "同一个名字", 780, 640),
             ("一周 3 条", "同一个节奏", 540, 960)]
    for i, (a, b, x, y) in enumerate(items):
        q = ease_back((p - i * 0.12) / 0.35)
        if q <= 0:
            continue
        lay = Image.new("RGBA", (340, 260), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        ld.rounded_rectangle([6, 6, 334, 254], radius=22, fill=(252, 246, 232), outline=INK, width=6)
        ld.text((170, 96), a, font=F(CN, 54), fill=INK, anchor="mm")
        ld.text((170, 172), b, font=F(CN, 38), fill=GREY, anchor="mm")
        lay = lay.rotate([-4, 3, -2][i], resample=Image.BICUBIC, expand=False)
        sc = 1.0 + (1 - q) * 0.25
        lay = lay.resize((int(lay.width * sc), int(lay.height * sc)), Image.BICUBIC)
        img.paste(lay, (int(x - lay.width / 2), int(y - lay.height / 2)), lay)
    if p > 0.55:
        d.text((W / 2, 1300), "改钩子，不改人设", font=F(CN, 86), fill=RED, anchor="mm")
        wobble_line(d, W / 2 - 330, W / 2 + 330, 1368, col=RED, w=10, seed=3)

def s_cta(d, img, p, t):
    q = ease_out(p / 0.4)
    y = 800 - (1 - q) * 60
    lay = Image.new("RGBA", (900, 620), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([8, 8, 892, 612], radius=40, fill=(255, 252, 246), outline=INK, width=8)
    ld.text((450, 150), "评论区打", font=F(CN, 58), fill=GREY, anchor="mm")
    ld.text((450, 300), "模板", font=F(CN, 190), fill=RED, anchor="mm")
    ld.text((450, 470), "5 条脚本骨架 + 分镜表，直接发你", font=F(CN, 38), fill=INK, anchor="mm")
    img.paste(lay, (int(W / 2 - 450), int(y - 310)), lay)
    if p > 0.3:
        ay = 1180 + math.sin(t * 6) * 8
        d.line([W / 2, ay, W / 2, ay + 130], fill=RED, width=12)
        d.polygon([(W / 2, ay + 175), (W / 2 - 34, ay + 110), (W / 2 + 34, ay + 110)], fill=RED)
    d.text((W / 2, 1620), "@你的账号", font=F(CN, 52), fill=GREY, anchor="mm")

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

def render(marks, total, audio, out_mp4):
    cmd = [FFMPEG, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", audio,
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out_mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(total * FPS)
    for fi in range(n):
        proc.stdin.write(draw_frame(marks, fi / FPS, total).tobytes())
        if fi % 90 == 0:
            print(f"  frame {fi}/{n}", flush=True)
    proc.stdin.close()
    proc.wait()
    return out_mp4

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    durs = synth_all()
    audio, marks, total = build_audio(durs)
    print("total", round(total, 2), "s")
    for m in marks:
        print(f"  {m['kind']:7s} {m['start']:6.2f} +{m['dur']:5.2f}")
    if mode in ("all", "preview"):
        for i, tt in enumerate([1.6, 6.2, 10.4, 14.4, 18.3, 22.0, 26.2, 31.0, 35.6]):
            p = os.path.join(OUT_DIR, f"prev_{i}.png")
            draw_frame(marks, tt, total).save(p)
            print("SHOT", p)
    if mode in ("all", "video"):
        out = os.path.join(OUT_DIR, "short_v1.mp4")
        render(marks, total, audio, out)
        print("WROTE", out)

if __name__ == "__main__":
    main()
