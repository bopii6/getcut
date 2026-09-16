#!/usr/bin/env python3
"""用 Bing 图片搜索补齐美联储相关的关键画面（技能允许：通过搜索引擎找真实网络图片）。
下载后校验格式、体积与最小尺寸，并记录来源页地址。
"""
import io
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

BUNDLE = Path(r"E:/短视频生成/美联储加息-素材包")
IMAGES = BUNDLE / "images"
META = Path(r"E:/短视频生成/_tools/_fed_meta.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
SKIP_HOSTS = ("upload.wikimedia.org", "commons.wikimedia.org", "gettyimages", "shutterstock",
              "istockphoto", "alamy", "dreamstime", "123rf", "depositphotos")

# (slug, 搜索词, 张数)
PLAN = [
    ("fed-building", "美联储 埃克尔斯大楼 外观", 2),
    ("fed-building-us", "Federal Reserve Eccles building exterior washington", 1),
    ("fomc-room", "Federal Reserve Board meeting room FOMC", 1),
    ("presser", "美联储 主席 新闻发布会 讲台", 1),
    ("powell", "Jerome Powell 美联储主席 演讲", 1),
    ("warsh", "Kevin Warsh 美联储 主席", 1),
    ("wallstreet", "Wall Street New York Stock Exchange building", 2),
    ("trading-floor", "NYSE trading floor traders", 1),
    ("gas-sign", "gas station price sign dollars", 1),
    ("oil-refinery", "oil refinery at night industry", 1),
    ("mortgage-doc", "mortgage contract signing house keys", 1),
    ("bank-building", "bank building facade city", 1),
    ("atm", "ATM cash machine street", 1),
    ("pboc", "中国人民银行 大楼 北京", 1),
    ("yuan", "人民币 百元 钞票", 2),
    ("fx-board", "机场 外汇 汇率 显示屏", 1),
    ("inflation-chart", "美国 CPI 通胀 走势图", 1),
    ("rate-chart", "联邦基金利率 走势 图", 1),
    ("fed-seal", "Federal Reserve System seal logo", 1),
    ("dc-sunset", "Washington DC 联邦储备 大楼 黄昏", 1),
]


def bing_images(query, want=6):
    url = "https://www.bing.com/images/search?" + urllib.parse.urlencode(
        {"q": query, "form": "HDRSC2", "first": "1", "count": "30"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "ignore")
    except Exception as e:
        print("   bing err:", str(e)[:70])
        return []
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


def download(url, dest, referer="https://www.bing.com/"):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    if len(data) < 60000:
        raise ValueError("too small")
    im = Image.open(io.BytesIO(data))
    if min(im.size) < 600 or im.size[0] <= im.size[1]:      # 只留横构图大图
        raise ValueError(f"bad size {im.size}")
    im = im.convert("RGB")
    dest.write_bytes(data if im.format in (None, "JPEG") else b"")
    if not dest.exists() or dest.stat().st_size == 0:
        im.save(dest, "JPEG", quality=92)
    return im.size


def main():
    meta = json.loads(META.read_text(encoding="utf-8"))
    n = len(meta["images"])
    for slug, query, want in PLAN:
        got = 0
        for cand in bing_images(query, want + 6):
            if got >= want:
                break
            n += 1
            dest = IMAGES / f"{n:02d}-{slug}.jpg"
            try:
                size = download(cand["url"], dest)
            except Exception as e:
                n -= 1
                print("   x", slug, str(e)[:50])
                continue
            meta["images"].append({
                "url": cand["url"], "source_url": cand["source_url"], "title": cand["title"],
                "w": size[0], "h": size[1], "license": "", "creator": "",
                "provider": "bing", "file": f"images/{dest.name}", "bytes": dest.stat().st_size,
                "via": "bing"})
            got += 1
            print("IMG", dest.name, dest.stat().st_size // 1024, "KB", size, cand["title"][:34])
            time.sleep(0.2)
        if got < want:
            print("  !! only", got, "for", slug)
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("== total images:", len(meta["images"]))


if __name__ == "__main__":
    main()
