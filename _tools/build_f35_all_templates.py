#!/usr/bin/env python3
"""把同一个选题（bundle-f35-saudi）用 6 套模板各出一版，供人对比排版风格。

每套模板都走**真实的出片流程**（大模型导演按这套模板的语汇编排 + 音效全开 + 同一首 BGM），
所以差别来自"模板语汇 + 版式"，而不是素材或配音。跑完在 对比-f35/ 下产 6 个 mp4 + 一个对比页。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # E:\短视频生成
sys.path.insert(0, str(ROOT / "videogen"))

from videogen import cli, config                        # noqa: E402

BUNDLE = ROOT / "bundle-f35-saudi"
OUT = ROOT / "对比-f35"
BGM = ROOT / "videogen" / "assets" / "music" / "bgm-news-1024.mp3"
# 对比顺序：信息密度从高到低，便于一眼看出差别
ORDER = ["editorial", "data", "news", "poster", "bleed", "zhigu"]

OUT.mkdir(exist_ok=True)
report_rows = []

for tpl in ORDER:
    name = config.TEMPLATES.get(tpl, tpl)
    print(f"\n=== {tpl} · {name} ===", flush=True)
    mp4 = OUT / f"f35-{tpl}.mp4"
    plan_json = ROOT / "videogen" / "work" / BUNDLE.name / "plan.json"
    cli.build(BUNDLE, mp4, format=tpl, bgm=BGM, sfx=True, sfx_mode="all", use_llm=True,
              progress=lambda st, p, d=None: print(f"  [{p:3d}%] {d or st}", flush=True))
    row = {"template": tpl, "name": name, "file": mp4.name,
           "mb": round(mp4.stat().st_size / 1048576, 1)}
    # 从 props 里统计分镜与卡片，便于对照
    props_path = ROOT / "videogen" / "work" / BUNDLE.name / "props.json"
    if props_path.is_file():
        props = json.loads(props_path.read_text(encoding="utf-8"))
        shots = props.get("shots") or []
        kinds = {}
        for s in shots:
            k = (s.get("overlay") or {}).get("variant") or s.get("kind")
            kinds[k] = kinds.get(k, 0) + 1
        durs = [(s["endMs"] - s["startMs"]) / 1000 for s in shots]
        row.update({"shots": len(shots),
                    "seconds": round(props.get("durationInFrames", 0) / 30, 1),
                    "avg_shot": round(sum(durs) / max(1, len(durs)), 2),
                    "kinds": kinds})
    report_rows.append(row)
    print(f"  → {mp4.name}  {row['mb']} MB  镜头 {row.get('shots')}  平均 {row.get('avg_shot')}s", flush=True)
    (OUT / "_report.json").write_text(json.dumps(report_rows, ensure_ascii=False, indent=1), encoding="utf-8")

print("\n全部完成：", ", ".join(r["file"] for r in report_rows))
