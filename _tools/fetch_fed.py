#!/usr/bin/env python3
"""「美联储加息是什么意思」素材取材：Openverse(Flickr 原图) + Pexels(图与视频)。
Wikimedia 在本机被墙，所以不用它。所有下载都校验尺寸与体积。
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BUNDLE = Path(r"E:/短视频生成/美联储加息-素材包")
IMAGES = BUNDLE / "images"
VIDEOS = BUNDLE / "videos"
META = Path(r"E:/短视频生成/_tools/_fed_meta.json")
PEXELS_KEY = Path(r"E:/短视频生成/videogen/pexels_key.txt").read_text(encoding="utf-8").strip()
UA = {"User-Agent": "NiwoBundleFetcher/1.0"}
BLOCKED_HOSTS = ("upload.wikimedia.org", "commons.wikimedia.org")

# 按文案推进顺序排（manifest 顺序尽量跟着文案走）
OPENVERSE_PLAN = [
    ("fed-building", "Federal Reserve building Washington"),
    ("fomc-room", "Federal Reserve Board meeting room"),
    ("presser", "press conference podium microphones"),
    ("powell", "Jerome Powell"),
    ("warsh", "Kevin Warsh Federal Reserve"),
    ("dollar-bill", "hundred dollar bill banknote"),
    ("dollars", "US dollar banknotes"),
    ("wallstreet", "Wall Street New York Stock Exchange"),
    ("trading", "stock exchange trading floor"),
    ("chart-screen", "financial market chart screen"),
    ("gas-price", "gas station price sign"),
    ("oil", "oil refinery"),
    ("supermarket", "supermarket shelves groceries"),
    ("mortgage", "mortgage loan documents signing"),
    ("bank", "bank building facade"),
    ("atm", "ATM cash machine"),
    ("card-pay", "credit card payment"),
    ("car-dealer", "car dealership showroom"),
    ("factory", "factory production line"),
    ("pboc", "People's Bank of China building"),
    ("yuan", "renminbi yuan banknotes"),
    ("fx-board", "currency exchange rate board"),
    ("inflation-chart", "inflation chart"),
    ("nyc-night", "New York City skyline night"),
]

PEXELS_PHOTO_PLAN = [
    ("usd-closeup", "dollar bills money close up"),
    ("calculator", "calculator finance documents"),
    ("bank-interior", "bank interior counter service"),
    ("wallet-card", "credit card wallet payment"),
    ("sale-car", "car dealership parking lot cars"),
    ("factory-2", "factory industrial machine"),
    ("laptop-chart", "laptop stock chart analytics"),
    ("groceries", "grocery shopping cart supermarket"),
    ("fuel", "gas station fuel pump"),
    ("skyline", "new york city skyline"),
    ("fx", "currency exchange money changer"),
    ("coins", "coins stack savings"),
]

PEXELS_VIDEO_PLAN = [
    ("wallstreet", "wall street new york"),
    ("money", "counting money dollars"),
    ("gas", "gas station refueling"),
    ("market", "stock market chart screen"),
    ("supermarket", "supermarket shopping"),
    ("bank", "bank building finance"),
    ("laptop", "laptop finance charts"),
    ("skyline", "new york skyline aerial"),
    ("card", "credit card payment"),
    ("factory", "factory production line"),
    ("traffic", "city traffic night"),
    ("oil", "oil pumpjack energy"),
]

meta = {"images": [], "videos": []}


def fetch(url, dest, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest.stat().st_size


def openverse(query, want=2):
    url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": query, "page_size": "20", "license_type": "all",
         "aspect_ratio": "wide", "size": "large"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
            data = json.load(r)
    except Exception as e:
        print("   openverse err:", e)
        return []
    out = []
    for it in data.get("results", []):
        u = it.get("url") or ""
        if any(h in u for h in BLOCKED_HOSTS):
            continue
        if (it.get("width") or 0) < 1200 or (it.get("width") or 0) <= (it.get("height") or 0):
            continue
        out.append({"url": u, "w": it.get("width"), "h": it.get("height"),
                    "license": (it.get("license") or "") + " " + (it.get("license_version") or ""),
                    "creator": it.get("creator") or "",
                    "source_url": it.get("foreign_landing_url") or "",
                    "title": it.get("title") or "", "provider": it.get("provider") or ""})
        if len(out) >= want:
            break
    return out


def pexels_photos(query, want=2):
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "size": "large", "per_page": "8"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": PEXELS_KEY, **UA}),
                                    timeout=45) as r:
            data = json.load(r)
    except Exception as e:
        print("   pexels photo err:", e)
        return []
    out = []
    for p in data.get("photos", []):
        if (p.get("width") or 0) < 1400:
            continue
        out.append({"url": p["src"].get("large2x") or p["src"]["large"],
                    "w": p.get("width"), "h": p.get("height"),
                    "license": "Pexels License", "creator": p.get("photographer", ""),
                    "source_url": p.get("url", ""), "title": p.get("alt") or "",
                    "provider": "pexels"})
        if len(out) >= want:
            break
    return out


def pexels_videos(query, want=1):
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "size": "medium", "per_page": "8"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": PEXELS_KEY, **UA}),
                                    timeout=45) as r:
            data = json.load(r)
    except Exception as e:
        print("   pexels video err:", e)
        return []
    out = []
    for v in data.get("videos", []):
        files = [f for f in v.get("video_files", [])
                 if (f.get("width") or 0) >= 1280 and (f.get("width") or 0) > (f.get("height") or 0)]
        if not files:
            continue
        files.sort(key=lambda f: abs(f["width"] - 1920))
        out.append({"url": files[0]["link"], "w": files[0]["width"], "h": files[0]["height"],
                    "dur": v.get("duration", 0), "license": "Pexels License",
                    "source_url": v.get("url", ""), "title": f'pexels video {v["id"]}',
                    "provider": "pexels"})
        if len(out) >= want:
            break
    return out


def save_images(plan, getter, tag):
    n = len(meta["images"])
    for slug, query in plan:
        got = 0
        for cand in getter(query):
            n += 1
            name = f"{n:02d}-{slug}.jpg"
            dest = IMAGES / name
            try:
                size = fetch(cand["url"], dest, timeout=90)
            except Exception as e:
                n -= 1
                print("   x", slug, str(e)[:60])
                continue
            if size < 40000:
                dest.unlink(missing_ok=True)
                n -= 1
                continue
            meta["images"].append(dict(cand, file=f"images/{name}", bytes=size, via=tag))
            got += 1
            print("IMG", name, size // 1024, "KB", cand["title"][:38])
            break
        if not got:
            print("   !! no image for", slug)
        time.sleep(0.2)


def main():
    IMAGES.mkdir(parents=True, exist_ok=True)
    VIDEOS.mkdir(parents=True, exist_ok=True)
    print("— openverse —", flush=True)
    save_images(OPENVERSE_PLAN, openverse, "openverse")
    print("— pexels photos —", flush=True)
    save_images(PEXELS_PHOTO_PLAN, pexels_photos, "pexels")
    print("— pexels videos —", flush=True)
    vn = 0
    for slug, query in PEXELS_VIDEO_PLAN:
        picks = pexels_videos(query, 1)
        if not picks:
            print("   !! no video for", slug)
            continue
        p = picks[0]
        vn += 1
        raw = VIDEOS / f"_raw-{vn:02d}-{slug}.mp4"
        out = VIDEOS / f"{vn:02d}-{slug}.mp4"
        try:
            fetch(p["url"], raw, timeout=180)
        except Exception as e:
            print("   x video", slug, str(e)[:60])
            vn -= 1
            continue
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-t", "10", "-i", str(raw),
                            "-map", "0:v:0", "-an", "-c:v", "libx264", "-crf", "20",
                            "-pix_fmt", "yuv420p", "-preset", "veryfast",
                            "-movflags", "+faststart", str(out)],
                           capture_output=True, text=True)
        raw.unlink(missing_ok=True)
        if r.returncode != 0 or not out.is_file() or out.stat().st_size < 200000:
            print("   x trim", slug, (r.stderr or "")[-120:])
            out.unlink(missing_ok=True)
            vn -= 1
            continue
        meta["videos"].append(dict(p, file=f"videos/{out.name}", bytes=out.stat().st_size))
        print("VID", out.name, out.stat().st_size // 1024 // 1024, "MB")
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("== images:", len(meta["images"]), "videos:", len(meta["videos"]))


if __name__ == "__main__":
    main()
