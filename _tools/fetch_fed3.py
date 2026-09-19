#!/usr/bin/env python3
"""美联储加息(9月17日)素材包取材。
1) 复用两个旧包里仍然对得上的实拍素材（已人工核验过）
2) Pexels 补：黄金、美债票据、港口、机场
3) Bing 图片补：沃什、美联储发布会、点阵图、上交所
所有下载都校验尺寸/体积，只留横构图大图。
"""
import io
import json
import re
import shutil
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(r"E:/短视频生成")
BUNDLE = ROOT / "bundle-fed-hike"
IMAGES = BUNDLE / "images"
VIDEOS = BUNDLE / "videos"
META = ROOT / "_tools/_fed3_meta.json"
FED = ROOT / "美联储加息-素材包"
AIP = ROOT / "niwo-bundle-ai-pause"
PEXELS_KEY = (ROOT / "videogen/pexels_key.txt").read_text(encoding="utf-8").strip()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
SKIP_HOSTS = ("upload.wikimedia.org", "commons.wikimedia.org", "gettyimages", "shutterstock",
              "istockphoto", "alamy", "dreamstime", "123rf", "depositphotos",
              "vcg.com", "699pic", "tuchong", "huitu", "58pic")

# ---------------------------------------------------------------- 复用旧包
COPY_IMAGES = [
    (AIP / "images/08-whitehouse.jpg", "01-whitehouse.jpg", "白宫北草坪与主楼外景，白天", ["白宫", "华盛顿", "美国政府"]),
    (FED / "images/01-fed-building.jpg", "02-fed-building.jpg", "华盛顿美联储大楼正面外景，白色石墙与柱廊，晴天", ["美联储大楼", "华盛顿", "建筑", "外景"]),
    (FED / "images/03-fed-rate-chart.png", "03-fed-rate-chart.png", "联邦基金利率历史走势折线图，带零轴与年刻度", ["利率走势", "联邦基金利率", "图表", "数据"]),
    (FED / "images/14-fed-building.jpg", "07-fed-building2.jpg", "美联储大楼正面外景，蓝天、旗杆与石砌柱廊", ["美联储大楼", "外景", "建筑", "国旗"]),
    (FED / "images/22-market-screen.jpg", "08-market-screen.jpg", "电子屏上的行情界面，红绿K线与成交数据", ["行情屏", "K线", "交易", "屏幕"]),
    (FED / "images/04-usd-closeup.jpg", "09-usd-closeup.jpg", "多张一百美元纸币叠放的近景，可看到钞票纹理与面额", ["美元", "钞票", "近景", "货币"]),
    (FED / "images/09-cpi-chart.png", "10-cpi-chart.png", "美国消费者物价指数同比走势折线图，曲线持续上行", ["通胀走势", "CPI", "图表", "数据"]),
    (FED / "images/10-supermarket.jpg", "11-supermarket.jpg", "超市里推着购物车挑选蔬果的顾客，货架整齐", ["超市", "购物", "货架", "物价"]),
    (AIP / "images/32-trump.jpg", "12-trump.jpg", "特朗普在椭圆形办公室俯身签署文件", ["特朗普", "白宫", "签署"]),
    (AIP / "images/09-whitehouse.jpg", "13-whitehouse2.jpg", "白宫主楼正面，草坪与喷泉", ["白宫", "建筑", "美国"]),
    (FED / "images/21-wallstreet-sign.jpg", "16-wallstreet-sign.jpg", "纽约华尔街路口的街牌与红绿灯，背景是高楼", ["华尔街", "路牌", "纽约", "街景"]),
    (FED / "images/05-mortgage-docs.jpg", "17-mortgage-docs.jpg", "房屋贷款合同文件与一串钥匙放在桌面上", ["房贷", "合同", "钥匙", "文件"]),
    (FED / "images/18-yuan-100.jpg", "18-yuan-100.jpg", "一百元人民币纸币正面，印有人民大会堂图案", ["人民币", "百元", "纸币", "钞票"]),
    (FED / "images/06-bank-counter.jpg", "19-bank-counter.jpg", "银行换汇柜台窗口，玻璃后是外币牌价与柜员", ["银行", "换汇", "柜台", "外币"]),
    (FED / "images/20-nyc-skyline.jpg", "23-nyc-skyline.jpg", "纽约曼哈顿天际线黄昏剪影，高楼群与落日", ["纽约", "天际线", "黄昏", "城市"]),
    (FED / "images/08-calculator.jpg", "24-calculator.jpg", "桌面上的计算器与财务图表，旁边有笔和纸张", ["计算器", "财务", "办公桌", "图表"]),
    (FED / "images/07-coins.jpg", "25-coins.jpg", "硬币成堆散落在白色桌面，浅景深", ["硬币", "存款", "零钱", "桌面"]),
    (AIP / "images/26-stocks.jpg", "26-stocks-screen.jpg", "证交所内悬挂的指数显示屏", ["交易所", "行情", "屏幕"]),
    (FED / "images/24-business-meeting.jpg", "27-business-meeting.jpg", "会议室里几个人围着铺满图表的桌面讨论", ["会议", "数据分析", "讨论", "办公"]),
    (AIP / "images/19-beijing.jpg", "28-china-city.jpg", "北京望京CBD高楼天际线", ["北京", "天际线", "中国", "城市"]),
    (AIP / "images/20-beijing.jpg", "29-china-cbd.jpg", "北京建外SOHO与央视总部大楼", ["北京", "CBD", "地标", "中国"]),
]

COPY_VIDEOS = [
    (FED / "videos/01-wallstreet.mp4", "01-wallstreet.mp4", "纽约华尔街街景，两侧高楼与来往行人车辆", ["华尔街", "街道", "建筑", "纽约"]),
    (FED / "videos/02-money.mp4", "02-money.mp4", "点钞机清点美元纸币的特写", ["点钞", "美元", "现金", "特写"]),
    (FED / "videos/04-market.mp4", "03-market.mp4", "屏幕上滚动的行情图表与交易数据", ["行情屏", "图表", "交易", "屏幕"]),
    (AIP / "videos/16-stockmarket.mp4", "04-stockmarket.mp4", "股市交易大厅屏幕与行情数据", ["股市", "金融", "交易"]),
    (FED / "videos/08-skyline.mp4", "06-skyline.mp4", "纽约城市天际线航拍移动镜头", ["天际线", "航拍", "城市", "建筑"]),
    (FED / "videos/11-traffic.mp4", "07-traffic.mp4", "夜间城市车流延时，车灯拉出光带", ["车流", "夜景", "城市", "延时"]),
    (FED / "videos/06-bank.mp4", "08-bank.mp4", "城市中的银行建筑与街景", ["银行", "建筑", "城市", "金融"]),
    (FED / "videos/07-laptop.mp4", "09-laptop.mp4", "办公桌上的笔记本电脑显示行情图表，手在键盘上操作", ["笔记本", "图表", "办公", "手部"]),
]

# ---------------------------------------------------------------- Pexels 新增
PEXELS_IMAGES = [
    ("14-gold", "gold bars bullion stack"),
    ("15-treasury", "savings bonds financial documents certificate"),
    ("21-airport", "airport departure terminal travelers"),
    ("22-port", "shipping containers port cargo"),
    ("05-presser", "press conference microphones podium"),
]
PEXELS_VIDEOS = [
    ("05-gold", "gold bars bullion"),
    ("10-port", "shipping containers port crane"),
]

# ---------------------------------------------------------------- Bing 新增
BING_IMAGES = [
    ("04-warsh", "美联储主席 沃什 Kevin Warsh", 2),
    ("06-dotplot", "FOMC dot plot September 2026 projections", 1),
    ("20-ashare", "上海证券交易所 A股 交易大厅", 1),
]

meta = {"images": [], "videos": []}


def add_image(dest, name, summary, tags, extra):
    meta["images"].append(dict(extra, file=f"images/{name}", summary=summary, tags=tags,
                               bytes=dest.stat().st_size))


def copy_assets():
    n = 0
    for src, name, summary, tags in COPY_IMAGES:
        if not src.is_file():
            print("  !! missing src", src)
            continue
        dst = IMAGES / name
        if dst.is_file() and dst.stat().st_size > 10000:
            add_image(dst, name, summary, tags, {"provider": "local-reuse", "source_url": "", "via": "reuse"})
            n += 1
            continue
        shutil.copy2(src, dst)
        add_image(dst, name, summary, tags, {"provider": "local-reuse", "source_url": "", "via": "reuse"})
        n += 1
    print("copied images:", n)
    vn = 0
    for src, name, summary, tags in COPY_VIDEOS:
        if not src.is_file():
            print("  !! missing src", src)
            continue
        dst = VIDEOS / name
        if not (dst.is_file() and dst.stat().st_size > 100000):
            shutil.copy2(src, dst)
        meta["videos"].append({"file": f"videos/{name}", "summary": summary, "tags": tags,
                               "provider": "local-reuse", "source_url": "", "via": "reuse",
                               "bytes": dst.stat().st_size})
        vn += 1
    print("copied videos:", vn)


def http_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def fetch(url, dest, referer=None):
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
        h["Accept"] = "image/avif,image/webp,image/*,*/*;q=0.8"
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest.stat().st_size


def pexels_photo(query, dest):
    data = http_json("https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "size": "large", "per_page": "10"}),
        {"Authorization": PEXELS_KEY})
    for p in data.get("photos", []):
        if (p.get("width") or 0) < 1400:
            continue
        url = p["src"].get("large2x") or p["src"]["large"]
        try:
            size = fetch(url, dest, referer="https://www.pexels.com/")
        except Exception as e:
            print("   x", str(e)[:50])
            continue
        if size < 60000:
            dest.unlink(missing_ok=True)
            continue
        im = Image.open(dest)
        if im.size[0] <= im.size[1]:
            dest.unlink(missing_ok=True)
            continue
        return {"provider": "pexels", "source_url": p.get("url", ""),
                "license": "Pexels License", "creator": p.get("photographer", ""),
                "title": p.get("alt") or "", "w": im.size[0], "h": im.size[1]}
    return None


def pexels_video(query, dest):
    data = http_json("https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "size": "medium", "per_page": "10"}),
        {"Authorization": PEXELS_KEY})
    for v in data.get("videos", []):
        files = [f for f in v.get("video_files", [])
                 if (f.get("width") or 0) >= 1280 and (f.get("width") or 0) > (f.get("height") or 0)]
        if not files:
            continue
        if v.get("duration", 0) < 12:
            continue
        files.sort(key=lambda f: abs(f["width"] - 1920))
        raw = dest.with_suffix(".raw.mp4")
        try:
            fetch(files[0]["link"], raw, referer="https://www.pexels.com/")
        except Exception as e:
            print("   x", str(e)[:50])
            continue
        return raw, {"provider": "pexels", "source_url": v.get("url", ""),
                     "license": "Pexels License", "title": f'pexels video {v["id"]}',
                     "w": files[0]["width"], "h": files[0]["height"]}
    return None


def fetch_pexels():
    for name, q in PEXELS_IMAGES:
        if (IMAGES / f"{name}.jpg").is_file() and (IMAGES / f"{name}.jpg").stat().st_size > 40000:
            print("skip existing img", name)
            continue
        try:
            cand = pexels_photo(q, IMAGES / f"{name}.jpg")
        except Exception as e:
            print("  x pexels", name, str(e)[:60])
            continue
        if not cand:
            print("  !! no pexels img", name)
            continue
        add_image(IMAGES / f"{name}.jpg", f"{name}.jpg", "", [], cand)
        print("IMG", f"{name}.jpg", cand.get("w"), "x", cand.get("h"), cand.get("title", "")[:34])
        time.sleep(0.3)
    for name, q in PEXELS_VIDEOS:
        dest = VIDEOS / f"{name}.mp4"
        if dest.is_file() and dest.stat().st_size > 100000:
            print("skip existing vid", name)
            continue
        try:
            got = pexels_video(q, dest)
        except Exception as e:
            print("  x pexels video", name, str(e)[:60])
            continue
        if not got:
            print("  !! no pexels video", name)
            continue
        raw, cand = got
        ok = trim(raw, dest)
        raw.unlink(missing_ok=True)
        if not ok:
            print("  x trim", name)
            continue
        meta["videos"].append(dict(cand, file=f"videos/{name}.mp4", summary="", tags=[],
                                   bytes=dest.stat().st_size))
        print("VID", f"{name}.mp4", dest.stat().st_size // 1024 // 1024, "MB")
        time.sleep(0.3)


def bing_images(query, want=6):
    url = "https://www.bing.com/images/search?" + urllib.parse.urlencode(
        {"q": query, "form": "HDRSC2", "first": "1", "count": "30"})
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "ignore")
    out = []
    for m in re.finditer(r'm="(\{[^"]+?\})"', html):
        try:
            obj = json.loads(m.group(1).replace("&quot;", '"'))
        except Exception:
            continue
        murl, purl = obj.get("murl"), obj.get("purl")
        if not murl or not purl:
            continue
        if any(h in murl for h in SKIP_HOSTS):
            continue
        out.append({"url": murl, "source_url": purl, "title": (obj.get("t") or "")[:80]})
        if len(out) >= want:
            break
    return out


def fetch_bing():
    for name, query, want in BING_IMAGES:
        got = 0
        for cand in bing_images(query, want + 8):
            if got >= want:
                break
            dest = IMAGES / (f"{name}.jpg" if want == 1 else f"{name}-{got + 1}.jpg")
            if dest.is_file() and dest.stat().st_size > 40000:
                got += 1
                continue
            try:
                size = fetch(cand["url"], dest, referer="https://www.bing.com/")
                if size < 60000:
                    raise ValueError("too small")
                im = Image.open(dest)
                if min(im.size) < 600:
                    raise ValueError(f"small {im.size}")
                im = im.convert("RGB")
                im.save(dest, "JPEG", quality=92)
            except Exception as e:
                dest.unlink(missing_ok=True)
                print("   x", name, str(e)[:44])
                continue
            got += 1
            add_image(dest, dest.name, "", [],
                      {"provider": "bing", "source_url": cand["source_url"],
                       "title": cand["title"], "w": im.size[0], "h": im.size[1]})
            print("IMG", dest.name, size // 1024, "KB", im.size, cand["title"][:30])
            time.sleep(0.3)
        if got < want:
            print("  !! only", got, "for", name)


def trim(src, dst, start=1.0, dur=9.0):
    import subprocess
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", str(src),
                        "-map", "0:v:0", "-an", "-c:v", "libx264", "-crf", "21",
                        "-pix_fmt", "yuv420p", "-preset", "veryfast",
                        "-movflags", "+faststart", str(dst)], capture_output=True, text=True)
    if r.returncode != 0 or not dst.is_file() or dst.stat().st_size < 150000:
        print("    trim err:", (r.stderr or "")[-140:])
        dst.unlink(missing_ok=True)
        return False
    return True


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    IMAGES.mkdir(parents=True, exist_ok=True)
    VIDEOS.mkdir(parents=True, exist_ok=True)
    print("— copy reuse —", flush=True)
    copy_assets()
    print("— pexels —", flush=True)
    fetch_pexels()
    print("— bing —", flush=True)
    fetch_bing()
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("== images:", len(meta["images"]), "videos:", len(meta["videos"]))


if __name__ == "__main__":
    main()
