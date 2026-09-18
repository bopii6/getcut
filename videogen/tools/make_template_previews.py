#!/usr/bin/env python3
"""一键重出模板缩略图 + 样片。

模板改了之后跑这一条命令就够了：

    cd videogen && python tools/make_template_previews.py

- **样片**：所有上架模板渲染**同一段演示内容**（`samples/tpl-demo/`，走 clone 复刻路径，
  分镜图纸在 `storyboard.json`），所以样片之间的差别只来自模板本身——用户在模板选择器里
  点一下就能听见/看见这套模板长什么样。产出 `server_static/templates/sample-<id>.mp4`。
- **缩略图**：从同一份 props 里挑「有设计卡」的那一拍取中间帧，缩到 270×480，
  产出 `server_static/templates/tpl-<id>.png`（选择器用它当封面；以前这些图是手工跑出来
  提交进仓库的，连脚本都没有，智谷还漏了一张）。

用法：
    python tools/make_template_previews.py                 # 全部模板：样片 + 缩略图
    python tools/make_template_previews.py --templates data,poster
    python tools/make_template_previews.py --no-video      # 只补缩略图
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent            # videogen/
sys.path.insert(0, str(ROOT))

from videogen import cli, config                          # noqa: E402
from videogen import remotion_render as rr                # noqa: E402

BUNDLE = ROOT / "samples" / "tpl-demo"
STORYBOARD = BUNDLE / "storyboard.json"
OUT_DIR = ROOT / "server_static" / "templates"
THUMB_W, THUMB_H = 270, 480
FPS = 30
# 样片统一用同一首 BGM，横着比模板时不引入第二个变量
BGM = ROOT / "assets" / "music" / "bgm-electronic-175.mp3"


def thumb_frame(props: dict) -> int:
    """挑一帧能代表这套模板的画面：优先带设计卡的镜头，取它的中间。"""
    shots = props.get("shots") or []
    pick = next((s for s in shots if s.get("kind") in ("panel", "callout") and s.get("overlay")), None)
    if pick is None:
        pick = next((s for s in shots if s.get("kind") == "title_card"), None)
    if pick is None:
        pick = shots[0] if shots else None
    if not pick:
        return 0
    mid_s = (float(pick["startMs"]) + float(pick["endMs"])) / 2 / 1000.0
    return max(0, int(mid_s * FPS))


def make_thumb(src_jpg: Path, dst_png: Path) -> None:
    from PIL import Image
    with Image.open(src_jpg) as im:
        im.convert("RGB").resize((THUMB_W, THUMB_H), Image.LANCZOS).save(dst_png, "PNG", optimize=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--templates", default="", help="只做这几个（逗号分隔），默认全部上架模板")
    ap.add_argument("--no-video", action="store_true", help="只出缩略图")
    ap.add_argument("--no-thumb", action="store_true", help="只出样片")
    args = ap.parse_args()

    ids = [t.strip() for t in args.templates.split(",") if t.strip()] or list(config.TEMPLATES)
    unknown = [t for t in ids if t not in config.TEMPLATES]
    if unknown:
        print(f"未知模板：{unknown}；可选：{list(config.TEMPLATES)}")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bgm = BGM if BGM.is_file() else None
    for tid in ids:
        print(f"\n=== {tid} · {config.TEMPLATES[tid]} ===", flush=True)
        if not args.no_video:
            cli.build(BUNDLE, OUT_DIR / f"sample-{tid}.mp4", clone=STORYBOARD, format=tid,
                      bgm=bgm, sfx=True, sfx_mode="all", use_llm=False, vision=False,
                      progress=lambda st, p, d=None: print(f"  [{p:3d}%] {d or st}", flush=True))
            # 渲染会顺手在成片旁写剪映草稿清单/资产目录——样片不需要，清掉免得混进静态目录
            for leftover in (OUT_DIR / f"sample-{tid}.draft.json", OUT_DIR / f"sample-{tid}.draftsrc"):
                if leftover.is_dir():
                    shutil.rmtree(leftover, ignore_errors=True)
                else:
                    leftover.unlink(missing_ok=True)
        if not args.no_thumb:
            props_path = ROOT / "work" / BUNDLE.name / "props.json"
            if not props_path.is_file():
                print("  跳过缩略图：没有 work/props.json（先跑一次样片）")
                continue
            props = json.loads(props_path.read_text(encoding="utf-8"))
            frame = thumb_frame(props)
            tmp = OUT_DIR / f".thumb-{tid}.jpg"
            if rr.render_still_frame(props, tmp, frame):
                make_thumb(tmp, OUT_DIR / f"tpl-{tid}.png")
                tmp.unlink(missing_ok=True)
                print(f"  缩略图 tpl-{tid}.png（第 {frame} 帧）", flush=True)
            else:
                print("  缩略图渲染失败", flush=True)
    print("\n完成。缩略图与样片都在 server_static/templates/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
