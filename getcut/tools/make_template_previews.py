#!/usr/bin/env python3
"""重出「模板选择器」的封面图（缩略图）。

    cd getcut && python tools/make_template_previews.py
    python tools/make_template_previews.py --templates data,poster

**为什么只剩缩略图**：画面渲染在 2026-09-20 从命令行搬进了客户的浏览器成片台
（`cli.py` 里没有 `visual_fn` 会直接抛错），本脚本原来那条"顺手把样片也渲出来"的路
就此作废，`render_still_frame()` 也不存在了。结果是从那天起**改完模板出不了新封面**，
选择器一直挂着 9 月 18 日的旧图——模板改了配色，封面还在演旧配色。

现在走的这条路只出单帧、不出整片，所以不需要那条退役链路：

1. `cli.build_prep()` —— 流水线前半程（配音/分镜/版式），产物 `props.json` 落盘，
   全程不发外部请求（`macro` 那套要 LLM 章节规划，例外）。
2. `renderer/_still.mjs` —— 把 `props.json` 交给 `@remotion/renderer` 出一帧 PNG。
   bundle 只打一次，几套模板共用。
3. 缩到 270×480 存成 `server_static/templates/tpl-<id>.png`。

**样片（sample-<id>.mp4）不再由本脚本产出**：要更新样片，只能在浏览器成片台里
用 `samples/tpl-demo/` 这个包各跑一遍并留下文件。本脚本会告诉你哪些样片比封面旧。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent            # getcut/
sys.path.insert(0, str(ROOT))

from getcut import cli, config                          # noqa: E402

BUNDLE = ROOT / "samples" / "tpl-demo"
STORYBOARD = BUNDLE / "storyboard.json"
OUT_DIR = ROOT / "server_static" / "templates"
STILL_SCRIPT = ROOT / "renderer" / "_still.mjs"
THUMB_W, THUMB_H = 270, 480
FPS = 30


def thumb_frame(props: dict) -> int:
    """挑一帧能代表这套模板的画面：优先带设计卡的镜头，取它的中间。

    注意：这套"优先挑卡"的口径对 `poster` 是错的——大字报的卖点是"一句一屏超大字"，
    卡不是它的脸。要按模板换挑选策略时，改这里而不是改皮肤。
    """
    shots = props.get("shots") or []
    pick = next((s for s in shots if s.get("kind") in ("panel", "callout") and s.get("overlay")), None)
    if pick is None:
        pick = next((s for s in shots
                     if (s.get("macroStage") or {}).get("block", {}).get("type")), None)
    if pick is None:
        pick = next((s for s in shots if s.get("kind") == "title_card"), None)
    if pick is None:
        pick = shots[0] if shots else None
    if not pick:
        return 0
    mid_s = (float(pick["startMs"]) + float(pick["endMs"])) / 2 / 1000.0
    return max(0, int(mid_s * FPS))


def make_thumb(src_png: Path, dst_png: Path) -> None:
    from PIL import Image
    with Image.open(src_png) as im:
        im.convert("RGB").resize((THUMB_W, THUMB_H), Image.LANCZOS).save(dst_png, "PNG", optimize=True)


def build_props(tid: str, dst: Path) -> bool:
    """跑流水线前半程拿 props.json。macro 要 LLM 章节规划，其余照 clone 图纸走。"""
    try:
        if tid == "macro":
            cli.build_prep(BUNDLE, format=tid, use_llm=True)
        else:
            cli.build_prep(BUNDLE, format=tid, clone=STORYBOARD, use_llm=False)
    except Exception as e:  # noqa: BLE001 - 一套失败不该带走其它六套
        print(f"  备料失败：{e}")
        return False
    src = ROOT / "work" / BUNDLE.name / "props.json"
    if not src.is_file():
        print("  备料没留下 props.json")
        return False
    shutil.copyfile(src, dst)
    return True


def report_sample_staleness(ids: list[str]) -> None:
    """样片本脚本产不了，至少把"样片比封面旧"这件事说出来，别让选择器悄悄演旧片。"""
    newest_thumb = max((p.stat().st_mtime for p in OUT_DIR.glob("tpl-*.png")), default=0)
    stale = [t for t in ids
             if (v := OUT_DIR / f"sample-{t}.mp4").is_file() and v.stat().st_mtime < newest_thumb]
    if stale:
        print(f"\n注意：{'、'.join(stale)} 的样片比封面旧，样片要在浏览器成片台里各跑一遍才能更新。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--templates", default="", help="只做这几个（逗号分隔），默认全部上架模板")
    args = ap.parse_args()

    ids = [t.strip() for t in args.templates.split(",") if t.strip()] or list(config.TEMPLATES)
    unknown = [t for t in ids if t not in config.TEMPLATES]
    if unknown:
        print(f"未知模板：{unknown}；可选：{list(config.TEMPLATES)}")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jobs: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="vg-props-") as tmp:
        tmproot = Path(tmp)
        for tid in ids:
            print(f"\n=== {tid} · {config.TEMPLATES[tid]} ===", flush=True)
            props_path = tmproot / f"{tid}.json"
            if not build_props(tid, props_path):
                continue
            props = json.loads(props_path.read_text(encoding="utf-8"))
            full = OUT_DIR / f".full-{tid}.png"
            jobs.append({"props": str(props_path), "frame": thumb_frame(props), "out": str(full)})
            print(f"  已备料（第 {jobs[-1]['frame']} 帧）", flush=True)

        if not jobs:
            print("没有任何模板可出图")
            return 1

        print(f"\n出 {len(jobs)} 帧…", flush=True)
        jobs_file = tmproot / "jobs.json"
        jobs_file.write_text(json.dumps(jobs), encoding="utf-8")
        proc = subprocess.run(
            ["node", STILL_SCRIPT.name, str(jobs_file)],
            cwd=ROOT / "renderer", capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        print((proc.stdout or "").strip()[-2000:])
        if proc.returncode != 0:
            print((proc.stderr or "").strip()[-1200:])

        done = []
        for j in jobs:
            full = Path(j["out"])
            tid = full.name[len(".full-"):-len(".png")]
            if full.is_file():
                make_thumb(full, OUT_DIR / f"tpl-{tid}.png")
                full.unlink(missing_ok=True)
                done.append(tid)
            else:
                print(f"  {tid}：没出图，保留旧封面")
    print(f"\n完成：{len(done)}/{len(ids)} 张封面已更新到 server_static/templates/")
    report_sample_staleness(ids)
    return 0 if len(done) == len(ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
