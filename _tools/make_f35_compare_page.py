#!/usr/bin/env python3
"""生成 对比-f35/index.html：六套模板的成片并排播放 + 指标对照。

读 build_f35_all_templates.py 产出的 _report.json，把六个成片排成一行，
带"同时播放/全部暂停"（一起放最能看出节奏和版式的差别）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "对比-f35"
report = json.loads((OUT / "_report.json").read_text(encoding="utf-8"))

DESC = {
    "editorial": "纸卡 + 媒体窗 + 信息卡：信息量最足，像一本翻页杂志",
    "data": "浅色仪表盘：左边数据、右边素材，底下一条进度轨",
    "news": "满屏画面 + 底部实色信息条：播报感最强",
    "poster": "黑底荧光黄、一句一屏的超大字：冲击力优先",
    "bleed": "素材铺满全屏、大标题压画面：沉浸感强",
    "zhigu": "三段式：顶带标题不动 / 中段舞台换动作 / 底带字幕",
}

cards = []
for r in report:
    kinds = r.get("kinds") or {}
    kind_txt = "、".join(f"{k}×{v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1]))
    cards.append(f"""
    <figure class="tpl">
      <figcaption>
        <b>{r['name']}</b>
        <small>{DESC.get(r['template'], '')}</small>
      </figcaption>
      <video src="{r['file']}" controls preload="metadata" playsinline></video>
      <ul class="meta">
        <li>时长 <b>{r.get('seconds','—')}</b> 秒</li>
        <li>镜头 <b>{r.get('shots','—')}</b> 个 · 平均 <b>{r.get('avg_shot','—')}</b> 秒/拍</li>
        <li>文件 {r.get('mb','—')} MB</li>
        <li class="kinds">画面元素：{kind_txt or '—'}</li>
      </ul>
    </figure>""")

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>同一选题 · 六套模板成片对比</title><style>
*{{box-sizing:border-box}}
body{{margin:0;padding:26px 20px 60px;background:#12141c;color:#e3e5f0;
  font:14px/1.6 "Microsoft YaHei","Segoe UI",sans-serif}}
h1{{font-size:22px;margin:0 0 6px}}
p.sub{{color:#98a0b6;margin:0 0 18px;max-width:900px}}
.bar{{display:flex;gap:10px;margin:0 0 20px;flex-wrap:wrap}}
button{{font:inherit;font-size:13px;padding:8px 16px;border-radius:8px;border:1px solid #3a3f52;
  background:#20242f;color:#e3e5f0;cursor:pointer}}
button.primary{{background:#6355d8;border-color:#6355d8;color:#fff}}
.row{{display:flex;gap:16px;overflow-x:auto;padding-bottom:14px}}
.tpl{{margin:0;flex:0 0 250px;background:#1a1d29;border:1px solid #2a2f3f;border-radius:12px;
  padding:12px;display:flex;flex-direction:column;gap:10px}}
.tpl b{{font-size:15px;display:block}}
.tpl small{{color:#98a0b6;font-size:12px;display:block;line-height:1.5;margin-top:3px;min-height:36px}}
video{{width:100%;aspect-ratio:9/16;background:#000;border-radius:8px;display:block}}
.meta{{list-style:none;margin:0;padding:0;font-size:12px;color:#98a0b6;display:grid;gap:4px}}
.meta b{{color:#e3e5f0}}
.meta .kinds{{color:#7d86a0;font-size:11px;line-height:1.6}}
</style></head><body>
<h1>同一选题 · 六套模板成片对比</h1>
<p class="sub">选题：美国同一天既谈"收尾"又批准向沙特出售 48 架 F-35（2026-09-17/18）。
同一份素材包、同一段文案、同一首 BGM、同一个音色；<b>每套模板各自走一次大模型编排</b>
（产品真实行为），所以分镜会略有不同——差别来自模板的语汇与版式。</p>
<div class="bar">
  <button class="primary" onclick="all('play')">一起播放</button>
  <button onclick="all('pause')">全部暂停</button>
  <button onclick="all('restart')">全部回到开头</button>
</div>
<div class="row">{''.join(cards)}</div>
<script>
const vids = [...document.querySelectorAll('video')];
function all(cmd) {{
  vids.forEach(v => {{
    if (cmd === 'play') {{ v.currentTime = 0; v.play().catch(()=>{{}}); }}
    if (cmd === 'pause') v.pause();
    if (cmd === 'restart') {{ v.pause(); v.currentTime = 0; }}
  }});
}}
</script>
</body></html>"""

(OUT / "index.html").write_text(html, encoding="utf-8")
print("对比页已生成：", OUT / "index.html")
for r in report:
    print(f"  {r['template']:10s} {r['file']:22s} {r.get('seconds','—'):>6} 秒 · "
          f"{r.get('shots','—'):>2} 镜 · 平均 {r.get('avg_shot','—')} 秒/拍")
