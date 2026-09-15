#!/usr/bin/env python3
"""生成 bundle-ai-slowdown-2 的 content.json 与 manifest.json（manifest 按文案推进排序）。"""
import json
from pathlib import Path

B = Path(r'E:/短视频生成/bundle-ai-slowdown-2')
script = (B / '_script.txt').read_text(encoding='utf-8').strip()

content = {
    "schema_version": 1,
    "title": "AI集体喊刹车：市场巨震，特朗普定调骗局",
    "script": script,
    "hook_headline": {
        "lines": ["造AI三巨头集体喊刹车", "特朗普：[[这是骗局]]"]
    },
    "sources": ["华尔街见闻", "21世纪经济报道", "澎湃新闻", "财联社", "第一财经"],
    "pronunciations": {"附和": "fu4 he4"},
    "notes": "素材按横构图收集，建议在 Niwo 里选竖屏信息版渲染。图片来自 Wikimedia Commons（CC/公有领域）与 Pexels/Pixabay（免费商用），视频来自 Mixkit 与 Pexels，均已裁为 8-10 秒。",
}

meta = json.loads((B / '_assets_meta.json').read_text(encoding='utf-8'))

# 按 script_anchor 在文案中的位置排序；同锚点按 kind（视频优先）与文件名
def order_key(item):
    a = item.get('script_anchor', '')
    pos = script.find(a) if a else 10**9
    return (pos, 0 if item['file'].startswith('videos') else 1, item['file'])

meta_sorted = sorted(meta, key=order_key)

assets = []
for m in meta_sorted:
    entry = {
        "file": m["file"],
        "kind": "video" if m["file"].startswith("videos") else "image",
        "summary": m["summary"],
        "tags": m["tags"],
        "script_anchor": m.get("script_anchor", ""),
        "source_url": m.get("source_url", ""),
        "license": m.get("license", ""),
    }
    assets.append(entry)

manifest = {
    "schema_version": 1,
    "generated_by": "videogen (LLM director pipeline)",
    "notes": "素材按口播文案推进排序；视频均已裁剪为 8-10 秒短镜头（无需再标选段）。",
    "assets": assets,
}

(B / 'content.json').write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
(B / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"content.json + manifest.json 已生成 | 素材 {len(assets)} 个")
print("文案:", len(script), "字 ≈", round(len(script)/6), "秒")
for a in assets[:8]:
    print(" ", a["file"], "|", a["summary"][:20], "|", a["script_anchor"][:18])
