#!/usr/bin/env python3
"""生成 bundle-f35-saudi 的 content.json 与 manifest.json。

manifest 排序沿用 make_bundle2 的规则：按 script_anchor 在文案里的位置排，
同锚点视频优先——这样素材清单的顺序跟着口播推进，规则引擎配镜也更好使。
"""
import json
from pathlib import Path

B = Path(r'E:/短视频生成/bundle-f35-saudi')
script = (B / '_script.txt').read_text(encoding='utf-8').strip()

content = {
    "schema_version": 1,
    "title": "同一天：美国说要收尾，又批了48架F-35给沙特",
    "script": script,
    "hook_headline": {
        "lines": ["嘴上说要把仗收尾", "手上批了[[48架F-35]]"]
    },
    "sources": ["新华社", "界面新闻", "新浪新闻"],
    "pronunciations": {},
    "notes": "选题：2026-09-17/18 美国务院批准可能向沙特出售 48 架 F-35（约 243 亿美元），"
             "同日特朗普谈伊朗战争将做重大决定。素材：人物与军机来自 Wikimedia Commons"
             "（CC/公有领域），城市与航运 b-roll 来自 Pexels / Mixkit，逐条授权记在 _assets_meta.json。",
}

meta = json.loads((B / '_assets_meta.json').read_text(encoding='utf-8'))
# 只保留文件真的在的条目（人工剔除过的图要从清单里去掉）
meta = [m for m in meta if (B / m['file']).is_file()]


def order_key(item):
    a = item.get('script_anchor', '')
    pos = script.find(a) if a else 10 ** 9
    return (pos, 0 if item['file'].startswith('videos') else 1, item['file'])


meta_sorted = sorted(meta, key=order_key)
missing = [m['script_anchor'] for m in meta_sorted if script.find(m['script_anchor']) < 0]
if missing:
    print('⚠️ 这些锚点在文案里找不到，会被排到最后：', sorted(set(missing)))

(B / 'content.json').write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding='utf-8')
(B / 'manifest.json').write_text(json.dumps(
    {"schema_version": 1, "generated_by": "videogen 选题采集（fetch_bundle_f35 + make_bundle_f35）",
     "notes": content["notes"], "assets": [
         {k: m[k] for k in ('file', 'kind' if 'kind' in m else 'file') if k in m} | {
             "kind": "image" if m['file'].startswith('images') else "video",
             "summary": m['summary'], "tags": m['tags'], "script_anchor": m['script_anchor'],
             "source_url": m.get('source_url', ''), "license": m.get('license', '')}
         for m in meta_sorted]},
    ensure_ascii=False, indent=1), encoding='utf-8')

print(f"content.json / manifest.json 已写出：图 {sum(1 for m in meta_sorted if m['file'].startswith('images'))} + "
      f"视频 {sum(1 for m in meta_sorted if m['file'].startswith('videos'))} = {len(meta_sorted)} 条")
print('前 5 条顺序:', [m['file'].split('/')[-1] for m in meta_sorted[:5]])
