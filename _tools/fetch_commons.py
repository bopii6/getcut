#!/usr/bin/env python3
"""Fetch landscape images (or videos) from Wikimedia Commons for a list of queries.

Usage:
  python fetch_commons.py images   # download bitmap images per IMAGES plan
  python fetch_commons.py videos   # download webm videos per VIDEOS plan

Writes downloads into the bundle dir and metadata into _assets_meta.json.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BUNDLE = Path(r"E:/短视频生成/niwo-bundle-ai-pause")
META = Path(r"E:/短视频生成/_tools/_assets_meta.json")
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "NiwoBundleFetcher/1.0 (personal short-video asset gathering)"}

IMAGES = [
    # (slug, commons search query, how many to fetch)
    ("amodei", "Dario Amodei", 3),
    ("anthropic", "Anthropic logo", 2),
    ("trump", "Donald Trump rally podium", 3),
    ("whitehouse", "White House north lawn", 2),
    ("datacenter", "data center server room", 3),
    ("gpu", "Nvidia GeForce graphics card", 2),
    ("chip", "microchip macro circuit board", 2),
    ("flags", "United States China flags", 2),
    ("beijing", "Beijing skyline skyscrapers", 2),
    ("washington", "United States Capitol dusk", 2),
    ("newspaper", "newspaper printing press", 2),
    ("stocks", "stock exchange trading floor", 2),
    ("robot", "humanoid robot", 2),
    ("un", "United Nations general assembly hall", 2),
    ("brake", "disc brake automobile closeup", 1),
    ("pedal", "car accelerator pedal", 1),
    ("steering", "hands steering wheel driving", 1),
    ("office", "programmer multiple monitors code", 2),
]

VIDEOS = [
    ("datacenter", "data center servers filetype:video", 2),
    ("server", "server room walking filetype:video", 2),
    ("printing", "printing press newspaper filetype:video", 2),
    ("trading", "stock exchange trading filetype:video", 2),
    ("robot", "industrial robot arm filetype:video", 2),
    ("city-night", "city traffic night timelapse filetype:video", 2),
    ("port", "container port cranes filetype:video", 1),
    ("crowd", "crowd walking street filetype:video", 2),
]


def api(params: dict) -> dict:
    params = dict(params, format="json")
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            print(f"  api retry {attempt+1}: {e}")
            time.sleep(2 * (attempt + 1))
    return {}


def search(query: str, limit: int, media: str) -> list[dict]:
    ftype = "bitmap" if media == "images" else "video"
    mode_video = media == "videos"
    data = api({
        "action": "query", "generator": "search",
        "gsrsearch": f"{query} filetype:{ftype}", "gsrnamespace": 6,
        "gsrlimit": limit * 3, "prop": "imageinfo",
        "iiprop": "url|size|mime|duration|extmetadata",
        "iiurlwidth": 1600,
    })
    pages = (data or {}).get("query", {}).get("pages", {})
    out = []
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        infos = p.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        out.append({
            "title": p.get("title", ""),
            "mime": info.get("mime", ""),
            "w": info.get("width", 0),
            "h": info.get("height", 0),
            "duration": info.get("duration") or 0,
            "size": info.get("size", 0),
            # videos: thumburl is a JPEG poster frame, the real file is in url
            "url": info.get("url") if mode_video else (info.get("thumburl") or info.get("url")),
            "page": info.get("descriptionurl", ""),
            "license": lic,
        })
    return out


def download(url: str, dest: Path) -> str | None:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except Exception as e:
        print(f"  download fail: {e}")
        return None
    if not data or len(data) < 3000:
        print("  too small, skip")
        return None
    head = data[:16]
    if head[:1] == b"<" or head[:5].lower() == b"<!doc":
        print("  got HTML, skip")
        return None
    if head[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif head[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        ext = ".webp"
    elif head[4:8] == b"ftyp":
        ext = ".mp4"
    elif head[:4] == b"\x1aE\xdf\xa3":
        ext = ".webm"
    elif head[:4] == b"OggS":
        ext = ".ogv"
    else:
        print(f"  unknown magic {head!r}, skip")
        return None
    dest = dest.with_suffix(ext)
    dest.write_bytes(data)
    return dest.name


def main(mode: str) -> None:
    plan = IMAGES if mode == "images" else VIDEOS
    subdir = "images" if mode == "images" else "videos"
    meta = json.loads(META.read_text(encoding="utf-8")) if META.is_file() else []
    import re as _re
    nums = [int(m.group(1)) for m in (_re.search(r"/(\d+)-", entry["file"]) for entry in meta) if m]
    counter = max(nums, default=0)
    for slug, query, want in plan:
        print(f"[{slug}] {query}")
        results = search(query, want, mode)
        got = 0
        for r in results:
            if got >= want:
                break
            if mode == "images":
                if r["mime"] not in ("image/jpeg", "image/png"):
                    continue
                if r["w"] < 900 or r["w"] < r["h"]:  # landscape only
                    continue
            else:
                if r["mime"] != "video/webm":
                    continue
                if not (4 <= r["duration"] <= 180):
                    continue
                if r["size"] > 150 * 1024 * 1024:
                    continue
            counter += 1
            raw = BUNDLE / subdir / f"{counter:02d}-{slug}.tmp"
            name = download(r["url"], raw)
            if not name:
                counter -= 1
                continue
            print(f"  saved {name}")
            meta.append({
                "file": f"{subdir}/{name}",
                "slug": slug,
                "title": r["title"],
                "page": r["page"],
                "license": r["license"],
                "duration": r["duration"],
            })
            got += 1
            time.sleep(0.4)
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"total meta entries: {len(meta)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "images")
