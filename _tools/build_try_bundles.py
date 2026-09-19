#!/usr/bin/env python3
"""生成"试玩用"的短素材包（落地页让新访客试做一条 15-20 秒的片子）。

为什么单独做短包：正式素材包是 80-90 秒的片子，试玩用它会占渲染队列好几分钟、
也容易被人当免费渲染机。短包只留 8-10 条素材、90 字上下的文案，出一条 20 秒以内的样片。

产出：videogen/samples/try-fed/、videogen/samples/try-f35/（随代码走，不用往服务器手工拷）
素材来源与授权沿用原素材包的 manifest（CC/公有领域 + Pexels + Mixkit）。
"""
import json
import shutil
from pathlib import Path

ROOT = Path(r'E:/短视频生成')
OUT_ROOT = ROOT / 'videogen' / 'samples'

# ---------- 1) 美联储那条：直接用现成的模板样片包（94 字，6 张图） ----------
src = OUT_ROOT / 'tpl-demo'
dst = OUT_ROOT / 'try-fed'
if dst.exists():
    shutil.rmtree(dst)
shutil.copytree(src, dst)
content = json.loads((dst / 'content.json').read_text(encoding='utf-8'))
content['title'] = '试玩：白宫喊话降息，美联储反手加息'
content['notes'] = ('试玩用短素材包（约 15 秒）：给落地页的新访客试做一条片子用。'
                    '素材授权见 manifest.json。')
(dst / 'content.json').write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding='utf-8')
manifest = json.loads((dst / 'manifest.json').read_text(encoding='utf-8'))
print(f'try-fed: {len(content["script"])} 字，{len(manifest["assets"])} 条素材')

# ---------- 2) F-35 那条：从完整素材包里挑 10 条，配 90 字文案 ----------
SRC = ROOT / 'bundle-f35-saudi'
PICK_IMG = ['01-f35-flight.jpg', '09-mbs.jpg', '13-capitol.jpg', '41-riyadh2.jpg',
            '39-redsea2.jpg', '37-trump.jpg']
PICK_VID = ['25-jet-v.mp4', '31-wash-v.mp4', '29-ship-v.mp4', '27-city-v.mp4']
SCRIPT = ('美国一边说要给伊朗战争收尾，一边批准向沙特卖四十八架F-35。'
          '这笔单子大约二百四十三亿美元，还要国会批准，首批战机要等好几年。'
          '仗打到第七个月，直接成本已经三百八十亿。')

dst = OUT_ROOT / 'try-f35'
if dst.exists():
    shutil.rmtree(dst)
(dst / 'images').mkdir(parents=True)
(dst / 'videos').mkdir(parents=True)
src_meta = {a['file']: a for a in json.loads((SRC / 'manifest.json').read_text(encoding='utf-8'))['assets']}

assets = []
for f in PICK_IMG:
    rel = f'images/{f}'
    shutil.copyfile(SRC / rel, dst / rel)
    m = dict(src_meta[rel])
    assets.append(m)
for f in PICK_VID:
    rel = f'videos/{f}'
    shutil.copyfile(SRC / rel, dst / rel)
    m = dict(src_meta[rel])
    assets.append(m)

content = {
    "schema_version": 1,
    "title": "试玩：美国批 48 架 F-35 给沙特",
    "script": SCRIPT,
    "hook_headline": {"lines": ["嘴上说要把仗收尾", "手上批了[[48架F-35]]"]},
    "sources": ["新华社", "界面新闻", "新浪新闻"],
    "pronunciations": {},
    "notes": "试玩用短素材包（约 15 秒）：给落地页的新访客试做一条片子用。素材授权见 manifest.json。",
}
(dst / 'content.json').write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding='utf-8')
(dst / 'manifest.json').write_text(json.dumps(
    {"schema_version": 1, "generated_by": "build_try_bundles.py", "notes": content['notes'],
     "assets": assets}, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'try-f35: {len(SCRIPT)} 字，{len(assets)} 条素材（图 {len(PICK_IMG)} + 视频 {len(PICK_VID)}）')
