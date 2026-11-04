#!/usr/bin/env python3
"""从 Mixkit 抓可商用 BGM，落到 app/public/music，并写一份 library.json。

Mixkit 许可：可商用、可不署名，但不能把曲子本身当素材转售。
每条只留前 70 秒（成片里是循环铺满的，完整版只会让包变大）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = ROOT / "app" / "public" / "music"
LIB = MUSIC_DIR / "library.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
CLIP_SECONDS = 70

# 获客短视频要"节奏紧、不抢人声"：挑这几类
WANT = {
    "corporate": ("corporate", "商务·稳", "律师/教培"),
    "cinematic": ("cinematic", "电影·推进", "加盟/观点"),
    "news": ("news", "新闻·紧迫", "资讯/热点"),
    "electronic": ("electronic", "电子·轻快", "通用"),
    "trap": ("trap", "说唱·强拍", "强钩子"),
    "funk": ("funk", "律动·轻快", "餐饮/门店"),
    "orchestral": ("orchestral", "管弦·压迫", "重话题"),
    "upbeat": ("upbeat", "明快·向上", "通用"),
}


def fetch(url: str, timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return r.read()


def track_ids(genre: str) -> list[str]:
    html = fetch(f"https://mixkit.co/free-stock-music/{genre}/").decode("utf-8", "replace")
    ids = re.findall(r'data-audio-player-preview-url-value="https://assets\.mixkit\.co/music/(\d+)/', html)
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def clip(src: bytes, dst: Path) -> int:
    tmp = dst.with_suffix(".raw")
    tmp.write_bytes(src)
    af = f"afade=t=in:d=0.5,atrim=0:{CLIP_SECONDS},afade=t=out:st={CLIP_SECONDS - 3}:d=3"
    p = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af", af,
         "-ar", "48000", "-b:a", "128k", str(dst)],
        capture_output=True, text=True,
    )
    tmp.unlink(missing_ok=True)
    if p.returncode != 0 or not dst.is_file():
        raise RuntimeError((p.stderr or "ffmpeg failed")[-300:])
    return dst.stat().st_size


def main() -> int:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    lib = []
    for genre, (tag, mood, fit) in WANT.items():
        try:
            ids = track_ids(genre)
        except Exception as e:  # noqa: BLE001
            print(f"[{tag}] 分类页失败：{e}")
            continue
        if not ids:
            print(f"[{tag}] 没找到曲子")
            continue
        tid = ids[0]
        name = f"{tag}.mp3"
        try:
            size = clip(fetch(f"https://assets.mixkit.co/music/{tid}/{tid}.mp3"), MUSIC_DIR / name)
        except Exception as e:  # noqa: BLE001
            print(f"[{tag}] 下载失败：{e}")
            continue
        lib.append({
            "file": name, "genre": tag, "mood": mood, "fit": fit,
            "mixkit_id": tid,
            "source": f"https://mixkit.co/free-stock-music/{genre}/",
            "license": "Mixkit Free Stock Music License",
            "bytes": size,
        })
        print(f"  + {name}（{size // 1024} KB）")

    LIB.write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n共 {len(lib)} 首，清单：{LIB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
