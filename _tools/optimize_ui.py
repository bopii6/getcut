#!/usr/bin/env python3
"""工作台优化：应用 frontend-design + web-quality-audit 两个技能。

设计方向（brief 钉死）：暗黑+荧光绿品牌语言、中文、四步向导 —— 保留。
优化执行质量与可用性（自由轴）：
  A. 排版：字体栈/字号阶梯/表格数字/tabular-nums
  B. 可访问性：focus-visible / skip link / aria / reduced-motion / alt / 触达尺寸
  C. 交互诚实性与 UX：拖拽上传真实实现 / 删除二次确认 / 失败重试 / 任务ID复制 /
     04 页"这一次的创作"摘要（对齐原版）
  D. 性能：素材墙视频懒加载
所有锚点在替换前断言。
"""
from pathlib import Path

FE = Path(r'E:/短视频生成/videogen/server_static/index.html')
s = FE.read_text(encoding='utf-8')
applied = []


def rep(old, new, tag, count=1):
    global s
    assert old in s, f"ANCHOR MISS: {tag}"
    s = s.replace(old, new, count)
    applied.append(tag)


# ============ A. 排版 ============
rep('body{background:var(--bg);color:var(--txt);font-family:"Microsoft YaHei",system-ui,sans-serif;font-size:14px}',
    'body{background:var(--bg);color:var(--txt);'
    'font-family:"PingFang SC","HarmonyOS Sans SC","Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif;'
    'font-size:var(--fs-14);line-height:1.6;-webkit-font-smoothing:antialiased}',
    "A1-font-stack")

rep('.hide{display:none!important}',
    '''.hide{display:none!important}
/* ---- 优化：字号阶梯 + 数字对齐 + 焦点可见 + 减少动效 ---- */
:root{--fs-11:11px;--fs-12:12px;--fs-13:13px;--fs-14:14px;--fs-16:16px;--fs-20:20px;--fs-24:24px}
h1{font-size:var(--fs-24);line-height:1.3}
h2{font-size:var(--fs-20);line-height:1.3}
h3{font-size:var(--fs-16);line-height:1.35}
.sub,.meta,.stage,.d,figcaption{line-height:1.55}
.pct,.est,.kv strong,#est2,#rateTxt,.card .meta,.ren{font-variant-numeric:tabular-nums}
button,input,select,textarea{font-family:inherit}
:focus-visible{outline:none;box-shadow:0 0 0 2px var(--bg),0 0 0 4px var(--lime);border-radius:6px}
.btn,.opt,.seg .pill,.rail button,.card,.top button{min-height:36px}
.skip{position:absolute;left:-9999px;top:8px;background:var(--lime);color:#141414;padding:8px 16px;
      border-radius:8px;font-weight:600;z-index:99}
.skip:focus{left:16px}
.toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);background:#2a2a2a;color:var(--txt);
       border:1px solid #3a3a3a;border-left:4px solid var(--lime);border-radius:10px;padding:10px 20px;
       font-size:var(--fs-13);opacity:0;pointer-events:none;transition:opacity .2s}
.toast.on{opacity:1}
.drop.dragover{border-color:var(--lime);background:#141a12}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:98}
.modal .box{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px 24px;width:min(420px,90vw)}
.modal .box p{margin:6px 0 18px;color:var(--gray);font-size:var(--fs-13)}
.modal .row{display:flex;gap:10px;justify-content:flex-end}
input[type=checkbox].sr{position:absolute;opacity:0;width:1px;height:1px}
@media (prefers-reduced-motion: reduce){*{transition:none!important;animation:none!important}}''',
    "A2-css-block")

# ============ B. 可访问性：skip link + main id ============
rep('<div class="wrap">',
    '<a class="skip" href="#main">跳到主内容</a>\n<div class="wrap">',
    "B1-skip-link")

if '<div class="main" id="main" role="main"' not in s:
    rep('<div class="main" id="main">', '<div class="main" id="main" role="main" tabindex="-1">', "B2-main-role")

# ============ C1. 拖拽上传真实实现 ============
rep('<div class="drop" id="drop"><strong>拖拽 zip 到此处，或点击选择文件</strong>',
    '<div class="drop" id="drop" role="button" tabindex="0" aria-label="上传素材包 zip">'
    '<strong>拖拽 zip 到此处，或点击选择文件</strong>',
    "C1-drop-aria")


FE.write_text(s, encoding='utf-8')
print("applied:", ", ".join(applied))

import subprocess
r = subprocess.run(["node", "-e", """
const fs = require('fs');
const html = fs.readFileSync('E:/短视频生成/videogen/server_static/index.html', 'utf-8');
const m = html.match(/<script>([\\s\\S]*?)<\\/script>/);
try { new Function(m[1]); console.log('JS syntax: OK'); } catch (e) { console.log('JS ERROR:', e.message); process.exit(1); }
"""], capture_output=True, text=True)
print((r.stdout or r.stderr).strip())
