#!/usr/bin/env python3
"""从 Mixkit 抓免费 BGM，补进 assets/music/ 并更新 library.json。

用法：
    python tools/fetch_bgm.py            # 抓缺的风格
    python tools/fetch_bgm.py --force

每条曲子**只留前 75 秒**并压到 128kbps：BGM 在成片里是循环铺满的
（compose.mix_audio 用 -stream_loop -1），完整 3-5 分钟只会让仓库和部署包白白变大。

Mixkit 免费音乐许可：可商用、需在作品里不署名也可（凭证是每条 source/license 字段），
但**不能把曲子本身当素材转售**。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = ROOT / "assets" / "music"
LIB = MUSIC_DIR / "library.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

CLIP_SECONDS = 75

# 风格页 → (中文标签, 情绪)。挑的是"竖屏信息类成片用得上"的路子，
# 跟已有 9 首（upbeat/energetic/electronic/hip-hop/corporate/cinematic/news/trap/chill）错开。
WANT: dict[str, tuple[str, str]] = {
    "ambient": ("ambient", "氛围·舒缓"),
    "atmospheres": ("atmospheres", "空间·辽阔"),
    "classical": ("classical", "古典·叙事"),
    "acid-jazz": ("jazz", "爵士·从容"),
    "breakbeat": ("breakbeat", "碎拍·动感"),
    "funk": ("funk", "律动·轻松"),
    "rock": ("rock", "摇滚·力度"),
    "orchestral": ("orchestral", "管弦·推进"),
}


def fetch(url: str, timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 - 固定站点
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
    """留前 75 秒 + 淡入淡出 + 128k，返回字节数。"""
    tmp = dst.with_suffix(".raw")
    tmp.write_bytes(src)
    af = f"afade=t=in:d=0.5,atrim=0:{CLIP_SECONDS},afade=t=out:st={CLIP_SECONDS - 3}:d=3"
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af", af,
                        "-ar", "44100", "-b:a", "128k", str(dst)], capture_output=True, text=True)
    tmp.unlink(missing_ok=True)
    if p.returncode != 0 or not dst.is_file():
        raise RuntimeError((p.stderr or "ffmpeg failed")[-400:])
    return dst.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    lib: list[dict] = []
    if LIB.is_file():
        try:
            lib = json.loads(LIB.read_text(encoding="utf-8"))
        except Exception:
            lib = []
    have = {i.get("genre") for i in lib}
    added = 0
    for genre, (tag, mood) in WANT.items():
        if tag in have and not args.force:
            continue
        try:
            ids = track_ids(genre)
        except Exception as e:  # noqa: BLE001 - 某个风格页挂了不该中断其他
            print(f"[{tag}] 分类页取失败：{e}")
            continue
        if not ids:
            print(f"[{tag}] 页面里没找到曲子，跳过")
            continue
        tid = ids[0]
        name = f"bgm-{tag}-{tid}.mp3"
        try:
            size = clip(fetch(f"https://assets.mixkit.co/music/{tid}/{tid}.mp3"), MUSIC_DIR / name)
        except Exception as e:  # noqa: BLE001
            print(f"[{tag}] {tid} 下载/裁剪失败：{e}")
            continue
        lib = [i for i in lib if i.get("file") != name]
        lib.append({
            "file": name, "genre": tag, "mood": mood, "mixkit_id": tid,
            "title": f"Mixkit {genre} #{tid}",
            "source": f"https://mixkit.co/free-stock-music/{genre}/",
            "license": "Mixkit Free Stock Music License",
            "bytes": size,
        })
        added += 1
        print(f"  + {name}（{size // 1024} KB，留前 {CLIP_SECONDS}s）")

    LIB.write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n新增 {added} 首；库里共 {len(lib)} 首")
    return 0


if __name__ == "__main__":
    sys.exit(main())
