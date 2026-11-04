#!/usr/bin/env python3
"""从 Mixkit 抓免费音效，补进 assets/sfx/ 并更新 library.json。

用法：
    python tools/fetch_sfx.py            # 抓缺的（已在库里的 id 跳过）
    python tools/fetch_sfx.py --force    # 全部重抓

为什么要有这个脚本：音效库之前是手工一次性抓来直接提交的二进制，没留脚本，
想加几个音效就得再来一遍"打开网页另存为"。现在按分类页抓 preview mp3（音效本身
只有 1 秒上下，preview 就是整条），统一做响度归一化后入库，来源与授权逐条记录。

注意：Mixkit 免费音效许可（可商用、无需署名、不可转售音效本身），
凭证就是每条的 source/license 字段——**不要**把库卖给用户当素材包。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # getcut/
SFX_DIR = ROOT / "assets" / "sfx"
LIB = SFX_DIR / "library.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# 分类 → (Mixkit 分类页, 目标条数)。这些分类要能对上"画面事件"：
#   open 开场扫频 / cut 镜头切换 / card 卡片弹出 / number 数字跳出 /
#   emphasis 重点强调 / end 收尾
PLAN: dict[str, tuple[str, int]] = {
    "open": ("transition", 4),
    "cut": ("whoosh", 5),
    "card": ("pop", 6),
    "number": ("click", 5),
    "emphasis": ("impact", 5),
    "end": ("notification", 3),
}


def fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 - 固定站点
        return r.read()


def previews(page: str) -> list[tuple[str, str]]:
    """分类页 → [(id, preview_url), ...]，按页面顺序。"""
    html = fetch(f"https://mixkit.co/free-sound-effects/{page}/").decode("utf-8", "replace")
    pairs = re.findall(
        r'data-audio-player-preview-url-value="(https://assets\.mixkit\.co/active_storage/sfx/(\d+)/[^"]+)"',
        html)
    seen, out = set(), []
    for url, sid in pairs:
        if sid in seen:
            continue
        seen.add(sid)
        out.append((sid, url))
    return out


def normalize(src: bytes, dst: Path) -> int:
    """统一响度（压在解说之下）+ 削掉首尾静音，输出 44.1k mp3。返回字节数。"""
    tmp = dst.with_suffix(".raw")
    tmp.write_bytes(src)
    af = ("silenceremove=start_periods=1:start_silence=0.02:start_threshold=-45dB,"
          "areverse,silenceremove=start_periods=1:start_silence=0.02:start_threshold=-45dB,areverse,"
          "loudnorm=I=-20:TP=-3,atrim=0:3.0,afade=t=out:st=2.4:d=0.5")
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af", af,
                        "-ar", "44100", "-b:a", "160k", str(dst)],
                       capture_output=True, text=True)
    tmp.unlink(missing_ok=True)
    if p.returncode != 0 or not dst.is_file():
        raise RuntimeError((p.stderr or "ffmpeg failed")[-400:])
    return dst.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="已有 id 也重抓")
    args = ap.parse_args()

    SFX_DIR.mkdir(parents=True, exist_ok=True)
    lib: list[dict] = []
    if LIB.is_file():
        try:
            lib = json.loads(LIB.read_text(encoding="utf-8"))
        except Exception:
            lib = []
    have_ids = {str(i.get("mixkit_id")) for i in lib if i.get("mixkit_id")}
    have_files = {i.get("file") for i in lib}
    added = 0

    for category, (page, want) in PLAN.items():
        try:
            items = previews(page)
        except Exception as e:  # noqa: BLE001 - 网络问题不该中断其他分类
            print(f"[{category}] 取 {page} 分类页失败：{e}")
            continue
        picked = 0
        for sid, url in items:
            if picked >= want:
                break
            if sid in have_ids and not args.force:
                picked += 1
                continue
            name = f"{category}-{sid}.mp3"
            if name in have_files and not args.force:
                picked += 1
                continue
            try:
                data = fetch(url)
                size = normalize(data, SFX_DIR / name)
            except Exception as e:  # noqa: BLE001
                print(f"  [{category}] {sid} 失败：{e}")
                continue
            lib = [i for i in lib if i.get("file") != name]
            lib.append({
                "file": name,
                "category": category,
                "mixkit_id": sid,
                "title": f"Mixkit {page} sfx #{sid}",
                "source": f"https://mixkit.co/free-sound-effects/{page}/",
                "license": "Mixkit Free Sound Effects License",
                "bytes": size,
            })
            picked += 1
            added += 1
            print(f"  [{category}] + {name}（{size // 1024} KB）")

    LIB.write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(f"\n新增 {added} 条；库内共 {len(lib)} 条：{dict(Counter(i['category'] for i in lib))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
