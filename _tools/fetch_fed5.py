#!/usr/bin/env python3
"""最后一轮补抓：美联储发布会现场、美债收益率、利率点阵图。"""
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"E:/短视频生成")
CAND = ROOT / "_tools/_cand2"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
SKIP = ("upload.wikimedia.org", "commons.wikimedia.org", "gettyimages", "shutterstock",
        "istockphoto", "alamy", "dreamstime", "123rf", "depositphotos", "vcg.com",
        "699pic", "tuchong", "58pic", "huitu", "zcool", "veer", "quanjing")

PLAN = [
    ("presser", "Federal Reserve chair press conference"),
    ("presser", "美联储 主席 新闻发布会 现场"),
    ("yield", "美国国债 收益率 飙升"),
    ("yield", "Treasury yields rise bond market"),
    ("dotplot", "FOMC dot plot projections chart"),
    ("bond", "US Treasury bonds certificate"),
]


def bing_images(query, want=12):
    url = "https://www.bing.com/images/search?" + urllib.parse.urlencode(
        {"q": query, "form": "HDRSC2", "first": "1", "count": "40"})
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
        mu, pu = obj.get("murl"), obj.get("purl")
        if not mu or not pu or any(h in mu for h in SKIP):
            continue
        out.append({"url": mu, "source_url": pu, "title": (obj.get("t") or "")[:90]})
        if len(out) >= want:
            break
    return out


def try_save(url, dest):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Referer": "https://www.bing.com/",
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if len(data) < 45000:
            return None
        im = Image.open(io.BytesIO(data))
        im.load()
        if min(im.size) < 620:
            return None
        im = im.convert("RGB")
        im.save(dest, "JPEG", quality=92)
        return im.size
    except Exception:
        return None


report = []
CAND.mkdir(parents=True, exist_ok=True)
for i, (slug, q) in enumerate(PLAN):
    got = 0
    for c in bing_images(q, 14):
        if got >= 5:
            break
        dest = CAND / f"{i:02d}-{slug}-{got + 1}.jpg"
        size = try_save(c["url"], dest)
        if not size:
            continue
        got += 1
        report.append({"file": dest.name, "query": q, "title": c["title"],
                       "source_url": c["source_url"], "size": size})
        print("CAND", dest.name, size, c["title"][:52])
    if not got:
        print("  !! none", q)
(CAND / "_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
