#!/usr/bin/env python3
"""定向补抓：沃什本人照片、真金条、美债、点阵图。多出候选，落盘到 _cand 供人工挑选。"""
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
BUNDLE = ROOT / "bundle-fed-hike"
CAND = ROOT / "_tools/_cand"
PEXELS_KEY = (ROOT / "videogen/pexels_key.txt").read_text(encoding="utf-8").strip()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
SKIP = ("upload.wikimedia.org", "commons.wikimedia.org", "gettyimages", "shutterstock",
        "istockphoto", "alamy", "dreamstime", "123rf", "depositphotos", "vcg.com",
        "699pic", "tuchong", "58pic", "huitu", "zcool", "veer", "quanjing")

BING = [
    ("warsh", "Kevin Warsh Federal Reserve"),
    ("warsh", "凯文 沃什 美联储 主席"),
    ("fednews", "美联储 加息 25个基点 2026"),
    ("dotplot", "美联储 点阵图 利率预期"),
    ("ustreasury", "美国财政部 大楼 华盛顿"),
]


def http_get(url, referer="https://www.bing.com/", timeout=60):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


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


def try_save(url, dest, min_side=600, landscape=False):
    try:
        data = http_get(url)
        if len(data) < 45000:
            return None
        im = Image.open(io.BytesIO(data))
        im.load()
        if min(im.size) < min_side:
            return None
        if landscape and im.size[0] <= im.size[1]:
            return None
        im = im.convert("RGB")
        im.save(dest, "JPEG", quality=92)
        return im.size
    except Exception:
        return None


def fetch_bing():
    report = []
    for i, (slug, q) in enumerate(BING):
        got = 0
        for c in bing_images(q, 14):
            if got >= 6:
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
            print("  !! none for", q)
    (CAND / "_bing_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


PEXELS = [
    ("gold", "gold bullion bars investment"),
    ("gold", "gold bars stacked close up"),
    ("treasury", "united states treasury building washington dc"),
    ("bonds", "government bonds investment papers"),
]


def pexels_photo(query, dest):
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "size": "large", "per_page": "12"})
    req = urllib.request.Request(url, headers={"Authorization": PEXELS_KEY, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        data = json.load(r)
    out = []
    for p in data.get("photos", []):
        if (p.get("width") or 0) < 1400:
            continue
        out.append(p)
    return out


def fetch_pexels():
    report = []
    for i, (slug, q) in enumerate(PEXELS):
        for j, p in enumerate(pexels_photo(q, None)[:4]):
            dest = CAND / f"px-{i:02d}-{slug}-{j + 1}.jpg"
            url = p["src"].get("large2x") or p["src"]["large"]
            size = try_save(url, dest, landscape=True)
            if not size:
                continue
            report.append({"file": dest.name, "query": q, "title": p.get("alt") or "",
                           "source_url": p.get("url", ""), "size": size, "provider": "pexels"})
            print("CAND", dest.name, size, (p.get("alt") or "")[:52])
    (CAND / "_pexels_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    CAND.mkdir(parents=True, exist_ok=True)
    print("— bing —")
    fetch_bing()
    print("— pexels —")
    fetch_pexels()
