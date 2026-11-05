# -*- coding: utf-8 -*-
"""v5: 复刻他的格式 —— 大字幕 + 屏幕卡片 + 手绘卡通主播。"""
import os, sys, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import build_v4 as B

W, H, FPS = B.W, B.H, B.FPS
OUT = r"E:\getcut\build"
DISP = B.DISP
INK, RED, ORANGE, GREY, CREAM, PAPER = B.INK, B.RED, B.ORANGE, B.GREY, B.CREAM, B.PAPER
F = B.F
cl, ease_out, ease_back, wobble = B.cl, B.ease_out, B.ease_back, B.wobble

HOST = None
def host_img():
    global HOST
    if HOST is None:
        im = Image.open(r"E:\getcut\ref\s_2.png").convert("RGBA")
        bb = im.getbbox()
        im = im.crop(bb)
        HOST = im
    return HOST

CARDS = {
    "hook":  dict(kind="analytics", title="创作者中心"),
    "trap1": dict(kind="form", title="新建项目"),
    "trap2": dict(kind="tools", title="我的工具箱"),
    "trap3": dict(kind="publish", title="发布记录"),
    "trap4": dict(kind="topics", title="今日热点"),
    "trap5": dict(kind="analytics", title="创作者中心"),
    "fix":   dict(kind="chips", title="我的排期"),
    "cta":   dict(kind="cta", title=""),
}

CAP = {
    "hook":  ("三个月，我发了", "200 条 AI 短视频"),
    "trap1": ("第一个坑", "先做内容，再想给谁看"),
    "trap2": ("第二个坑", "一直换工具，从不换结构"),
    "trap3": ("第三个坑", "一条视频，只发一次"),
    "trap4": ("第四个坑", "追得动热点，留不住人"),
    "trap5": ("第五个坑", "只看播放量，不看私信"),
    "fix":   ("解法", "固定角色 / 固定栏目 / 一周 3 条"),
    "cta":   ("评论区打", "模板"),
}
KEY = {"hook": 1, "trap1": 1, "trap2": 1, "trap3": 1, "trap4": 1, "trap5": 1, "fix": 1, "cta": 1}


def beam(img, cx, cy, w, h, strength=1.0):
    from PIL import ImageChops
    lay = Image.new('RGB', (W, H), (0, 0, 0)); d = ImageDraw.Draw(lay)
    for i in range(9):
        k = 1 - i / 9
        d.rectangle([cx - w * k / 2, 0, cx + w * k / 2, cy + h * k],
                    fill=tuple(int(c * .055 * k * strength) for c in (255, 232, 198)))
    lay = lay.filter(ImageFilter.GaussianBlur(110))
    return ImageChops.screen(img, lay)

def rrect(d, box, r, fill, outline=None, w=0):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=w)

def card_frame(img, y, p, kind, title):
    """White window card with chrome."""
    x0, x1 = 78, W - 78
    h = 600
    q = ease_out(p / .3)
    dy = int((1 - q) * 70)
    lay = Image.new("RGBA", (x1 - x0 + 80, h + 80), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    # shadow
    ld.rounded_rectangle([30, 44, lay.width - 30, lay.height - 26], radius=30,
                         fill=(26, 34, 58, 40))
    lay = lay.filter(ImageFilter.GaussianBlur(16))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([24, 20, lay.width - 24, lay.height - 40], radius=26,
                         fill=(255, 252, 244, 255), outline=(24, 34, 58, 255), width=7)
    # chrome bar
    for i, c in enumerate([(226, 96, 74), (238, 176, 72), (120, 180, 130)]):
        ld.ellipse([54 + i * 34, 48, 74 + i * 34, 68], fill=c)
    if title:
        ld.text((lay.width / 2, 60), title, font=F(DISP, 32), fill=(140, 132, 118), anchor="mm")
    ld.line([34, 92, lay.width - 34, 92], fill=(226, 218, 200), width=3)
    img.paste(lay, (x0 - 24, y + dy), lay)
    return (x0, y + dy)

def card_body(d, x0, y0, kind, p):
    """Contents inside the card at absolute coords."""
    left, right = x0 + 44, x0 + 880
    top = y0 + 120
    if kind == "analytics":
        rows = [("播放量", "128.4 万", INK), ("点赞", "9.2 万", INK), ("私信", "0", RED)]
        for i, (a, b, c) in enumerate(rows):
            yy = top + 40 + i * 132
            d.text((left, yy), a, font=F(DISP, 46), fill=GREY, anchor="lm")
            d.text((right, yy), b, font=F(DISP, 64), fill=c, anchor="rm")
            d.line([left, yy + 62, right, yy + 62], fill=(232, 224, 208), width=3)
    elif kind == "form":
        d.text((left, top + 20), "这次做什么？", font=F(DISP, 40), fill=GREY, anchor="lm")
        rrect(d, [left, top + 62, right, top + 150], 12, (248, 243, 232), (206, 196, 176), 4)
        d.text((left + 22, top + 106), "还没想好", font=F(DISP, 40), fill=(190, 180, 160), anchor="lm")
        d.text((left, top + 196), "给谁看？", font=F(DISP, 40), fill=GREY, anchor="lm")
        rrect(d, [left, top + 238, right, top + 326], 12, (248, 243, 232), (206, 196, 176), 4)
        d.text((left + 22, top + 282), "所有人", font=F(DISP, 40), fill=(190, 180, 160), anchor="lm")
        d.text((left, top + 350), "为什么是你？", font=F(DISP, 40), fill=GREY, anchor="lm")
        rrect(d, [left, top + 392, right, top + 470], 12, (248, 243, 232), (206, 196, 176), 4)
        d.text((left + 22, top + 431), "因为我会做 AI", font=F(DISP, 40), fill=(190, 180, 160), anchor="lm")
        if p > .45:
            d.text((left, top + 510), "结果：谁都打动不了", font=F(DISP, 44), fill=RED, anchor="lm")
    elif kind == "tools":
        items = [("工具 A", "已卸载"), ("工具 B", "已卸载"), ("工具 C", "在用"), ("结构？", "没变")]
        for i, (a, b) in enumerate(items):
            yy = top + 30 + i * 108
            on = i == 2
            d.text((left, yy), a, font=F(DISP, 44), fill=INK if on else (186, 178, 162), anchor="lm")
            d.text((right, yy), b, font=F(DISP, 40), fill=RED if b == "没变" else GREY, anchor="rm")
            d.line([left, yy + 46, right, yy + 46], fill=(232, 224, 208), width=3)
    elif kind == "publish":
        items = [("抖音", "已发 1 条", True), ("小红书", "没发", False), ("视频号", "没发", False), ("YouTube", "没发", False)]
        for i, (a, b, on) in enumerate(items):
            yy = top + 26 + i * 108
            d.text((left, yy), a, font=F(DISP, 44), fill=INK if on else (186, 178, 162), anchor="lm")
            d.text((right, yy), b, font=F(DISP, 40), fill=(96, 150, 110) if on else (196, 188, 172), anchor="rm")
            d.line([left, yy + 46, right, yy + 46], fill=(232, 224, 208), width=3)
    elif kind == "topics":
        items = ["#AI 短剧涨粉", "#Claude 新模型", "#副业月入过万", "#数字人带货"]
        for i, a in enumerate(items):
            yy = top + 20 + i * 100
            rrect(d, [left, yy - 26, right, yy + 40], 14, (246, 240, 226), (214, 204, 184), 3)
            d.text((left + 24, yy + 6), a, font=F(DISP, 40), fill=(150, 142, 128), anchor="lm")
        if p > .5:
            d.text((left, top + 430), "热点吃完，人没留下", font=F(DISP, 44), fill=RED, anchor="lm")
    elif kind == "chips":
        for i, (a, b) in enumerate([("固定角色", "同一张脸"), ("固定栏目", "同一个名字"), ("一周 3 条", "同一个节奏")]):
            yy = top + 20 + i * 128
            rrect(d, [left, yy, left + 460, yy + 104], 16, (252, 246, 232), (24, 34, 58), 6)
            d.text((left + 26, yy + 34), a, font=F(DISP, 44), fill=INK, anchor="lm")
            d.text((left + 26, yy + 78), b, font=F(DISP, 32), fill=GREY, anchor="lm")
        if p > .45:
            d.text((right - 160, top + 210), "← 这三个\n   别改", font=F(DISP, 40), fill=RED, anchor="lm")
    elif kind == "cta":
        d.text((x0 + 440, y0 + 210), "评论区打", font=F(DISP, 54), fill=GREY, anchor="mm")
        d.text((x0 + 440, y0 + 340), "模板", font=F(DISP, 170), fill=RED, anchor="mm")
        d.text((x0 + 440, y0 + 470), "5 条脚本骨架 + 分镜表，直接发你", font=F(DISP, 36), fill=INK, anchor="mm")

def host(d, img, p, t, talking=True):
    him = host_img()
    hh = 560
    hw = int(him.width * hh / him.height)
    him2 = him.resize((hw, hh), Image.LANCZOS)
    bob = math.sin(t * 2.6) * 7
    x = int(W / 2 - hw / 2)
    y = int(1880 - hh + bob)
    img.paste(him2, (x, y), him2)
    # mouth animation (line-art: small filled ellipse over mouth)
    mo = (math.sin(t * 17) * .5 + .5) if talking else 0
    if mo > .25:
        mx, my = x + hw * .50, y + hh * .455
        rx, ry = hw * .030, hh * .022 * mo
        ImageDraw.Draw(img).ellipse([mx - rx, my - ry, mx + rx, my + ry], fill=(20, 20, 22))

def draw_frame(marks, t, total):
    mk = marks[0]
    for m in marks:
        if t >= m["start"]:
            mk = m
    local = cl((t - mk["start"]) / max(1e-3, mk["dur"]))
    k = mk["kind"]
    dark = k == "twist"
    img = B.paper(dark=dark)
    d = ImageDraw.Draw(img)

    if k == "twist":
        img.paste(beam(img, W / 2, 820, 820, 700, strength=ease_out(local / .4)))
        d = ImageDraw.Draw(img)
        if local > .04:
            d.text((W / 2, 560), "问题不在工具", font=F(DISP, 60), fill=(234, 226, 212), anchor="mm")
        if local > .2:
            d.text((W / 2, 672), "在那个词", font=F(DISP, 60), fill=(142, 136, 126), anchor="mm")
        q3 = cl((local - .34) / .28)
        if q3 > 0:
            d.text((W / 2, 960), "重复", font=F(DISP, 380 * (1.4 - .4 * ease_back(q3))),
                   fill=CREAM, anchor="mm")
        if q3 > .5:
            d.text((W / 2, 1250), "同一条，做成不同版本，反复发", font=F(DISP, 50),
                   fill=(212, 204, 188), anchor="mm")
        d.text((64, 96), "@你的账号", font=F(DISP, 38), fill=(150, 144, 132), anchor="lm")
        B.progress(d, t / total)
        return img

    # caption
    a1, a2 = CAP[k]
    q = ease_out(local / .22)
    d.text((64, 210 + (1 - q) * 26), a1, font=F(DISP, 56), fill=GREY, anchor="lm")
    q2 = ease_out((local - .06) / .22)
    size = 96 if len(a2) <= 12 else 78
    d.text((64, 330 + (1 - q2) * 28), a2, font=F(DISP, size), fill=RED, anchor="lm")

    # card
    c = CARDS[k]
    x0, y0 = card_frame(img, 470, local, c["kind"], c["title"])
    d = ImageDraw.Draw(img)
    card_body(d, x0, y0, c["kind"], local)

    # host
    host(d, img, local, t, talking=True)

    d.text((64, 96), "@你的账号", font=F(DISP, 38), fill=GREY, anchor="lm")
    d.text((W - 64, 96), "AI 短视频避坑 / 01", font=F(DISP, 36), fill=GREY, anchor="rm")
    B.progress(d, t / total)

    z = 1 + .05 * local ** 1.2
    return B.cam(img, zoom=z)

def render(marks, total, audio, out):
    import subprocess
    cmd = [B.FFMPEG, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", audio, "-c:v", "libx264", "-preset", "medium", "-crf", "19",
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
    durs = B.synth_vo()
    audio, marks, total = B.build_audio(durs)
    print("total", round(total, 2))
    if mode in ("all", "preview"):
        for i, tt in enumerate([2.0, 6.2, 10.2, 14.2, 18.2, 22.0, 26.0, 31.0, 35.6]):
            p = os.path.join(OUT, f"v5_{i}.png")
            draw_frame(marks, tt, total).save(p)
            print("SHOT", p)
    if mode in ("all", "video"):
        o = os.path.join(OUT, "short_v5.mp4")
        render(marks, total, audio, o)
        print("WROTE", o)

if __name__ == "__main__":
    main()
