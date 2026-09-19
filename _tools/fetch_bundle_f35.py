#!/usr/bin/env python3
"""采集「美国一天里同时说收尾 + 批 F-35 军售」选题的素材。

复用 fetch_bundle2.py 里的采集器（commons / pexels / pixabay / mixkit / pexelsv），
只把 BUNDLE / META / meta 指到本选题的素材包目录，其余逻辑一行不改。
计划表在 bundle-f35-saudi/_plan.json。
"""
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import fetch_bundle2 as fb   # noqa: E402  （模块级只读密钥，无副作用）

BUNDLE = Path(r'E:/短视频生成/bundle-f35-saudi')
for sub in ('images', 'videos'):
    (BUNDLE / sub).mkdir(parents=True, exist_ok=True)

fb.BUNDLE = BUNDLE
fb.META = BUNDLE / '_assets_meta.json'
fb.meta = json.loads(fb.META.read_text(encoding='utf-8')) if fb.META.is_file() else []


def main() -> int:
    plan = json.loads((BUNDLE / '_plan.json').read_text(encoding='utf-8'))
    log = []
    for item in plan:
        kind = item["kind"]
        try:
            if kind == "commons":
                n = fb.commons(item["slug"], item["q"], item["want"], item["summary"], item["tags"], item["anchor"])
            elif kind == "pexels":
                n = fb.pexels_photos(item["slug"], item["q"], item["want"], item["summary"], item["tags"], item["anchor"])
            elif kind == "pixabay":
                n = fb.pixabay_photos(item["slug"], item["q"], item["want"], item["summary"], item["tags"], item["anchor"])
            elif kind == "mixkit":
                n = fb.mixkit_videos(item["slug"], item["q"], item["want"], item["summary"], item["tags"], item["anchor"])
            elif kind == "pexelsv":
                n = fb.pexels_videos(item["slug"], item["q"], item["want"], item["summary"], item["tags"], item["anchor"])
            else:
                n = 0
        except Exception as e:  # noqa: BLE001 - 单条失败不该中断整轮采集
            n = f"ERR {e}"[:70]
        log.append(f"{kind:8s} {item['slug']:14s} -> {n}")
        print(log[-1], flush=True)
        fb.META.write_text(json.dumps(fb.meta, ensure_ascii=False, indent=1), encoding="utf-8")
    imgs = sum(1 for m in fb.meta if m['file'].startswith('images'))
    vids = sum(1 for m in fb.meta if m['file'].startswith('videos'))
    print(f"\n合计 {len(fb.meta)} 条：图 {imgs} 张 + 视频 {vids} 段")
    return 0


if __name__ == "__main__":
    sys.exit(main())
