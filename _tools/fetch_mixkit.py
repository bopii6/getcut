#!/usr/bin/env python3
"""Scrape Mixkit category pages for free-stock-video direct mp4 links, download 720p."""
import re
import time
import urllib.request
from pathlib import Path

BUNDLE = Path(r"E:/短视频生成/niwo-bundle-ai-pause")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# (category url slug, how many clips to take from it)
PLAN = [
    ("data-center", 2),
    ("technology", 2),
    ("city-night", 1),
    ("finance-and-money", 2),
    ("robot", 2),
    ("crowd", 1),
    ("office", 2),
    ("industrial", 1),
    ("server", 2),
]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "ignore")


def grab(category: str, want: int) -> list[tuple[str, str]]:
    """Return list of (item_slug, id) from a category page."""
    html = fetch(f"https://mixkit.co/free-stock-video/{category}/")
    items = re.findall(
        r'href="/free-stock-video/([a-z0-9-]+?)(?:-\d+)?/"[^>]*>', html)
    ids = re.findall(r"https://assets\.mixkit\.co/videos/(\d+)/\d+-\d+\.mp4", html)
    seen, out = set(), []
    for vid in ids:
        if vid in seen:
            continue
        seen.add(vid)
        slug = next((s for s in items if s.endswith(f"-{vid}")), f"mixkit-{category}-{vid}")
        out.append((slug, vid))
    return out[: want * 2]


def download(vid: str, dest: Path) -> bool:
    for res in (720, 360):
        url = f"https://assets.mixkit.co/videos/{vid}/{vid}-{res}.mp4"
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if data[:4] != b"\x00\x00\x00" + b"\x18" and data[4:8] != b"ftyp":
                print(f"  {res}: not mp4 magic, skip")
                continue
            dest.write_bytes(data)
            print(f"  saved {dest.name} ({len(data)//1024} KB, {res}p)")
            return True
        except Exception as e:
            print(f"  {res}: {e}")
    return False


def main() -> None:
    meta_lines = []
    n = 1
    for category, want in PLAN:
        print(f"[{category}]")
        try:
            candidates = grab(category, want)
        except Exception as e:
            print(f"  category fail: {e}")
            continue
        got = 0
        for slug, vid in candidates:
            if got >= want:
                break
            dest = BUNDLE / "videos" / f"raw-{n:02d}.mp4"
            if download(vid, dest):
                title = slug.replace("-", " ").strip()
                meta_lines.append(
                    f"raw-{n:02d}.mp4|{vid}|{title}|https://mixkit.co/free-stock-video/{slug}/"
                )
                got += 1
            n += 1
            time.sleep(0.3)
    (Path(r"E:/短视频生成/_tools/_mixkit_meta.txt")).write_text(
        "\n".join(meta_lines), encoding="utf-8")
    print(f"raw clips: {len(meta_lines)}")


if __name__ == "__main__":
    main()
