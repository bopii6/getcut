#!/usr/bin/env python3
"""修正 optimize_ui.py 中的两处问题，然后执行它。"""
from pathlib import Path

p = Path(r'E:/短视频生成/_tools/optimize_ui.py')
s = p.read_text(encoding='utf-8')

# 1) 简化 B2
old = '''rep('<div class="main" id="main">', '<div class="main" id="main" role="main" tabindex="-1">',
    "B2-main-role") if '<div class="main" id="main">' in s else None

if '<div class="main" id="main">' not in s and '<div class="main" id="main" role="main"' not in s:
    rep('<div class="main" id="main">', '<div class="main" id="main" role="main" tabindex="-1">', "B2-main-role")'''
new = '''if '<div class="main" id="main" role="main"' not in s:
    rep('<div class="main" id="main">', '<div class="main" id="main" role="main" tabindex="-1">', "B2-main-role")'''
assert old in s, "b2 anchor"
s = s.replace(old, new)

# 2) 音色标签映射（避免未定义的 CFG.voiceLabel）
old2 = '<span class="k">声音</span><span>${CFG.voiceLabel || "云希 · 清爽男声"} · ${(CFG.rate/100).toFixed(2)}×</span>'
new2 = ('<span class="k">声音</span><span>${voiceLabel()} · ${(CFG.rate/100).toFixed(2)}×</span>')
assert old2 in s, "voice anchor"
s = s.replace(old2, new2)

# 注入 voiceLabel 工具函数（放在 toast 前）
old3 = '''function toast(msg){'''
new3 = '''function voiceLabel(){
  const m = {"zh-CN-YunxiNeural":"云希 · 清爽男声","zh-CN-YunjianNeural":"云健 · 浑厚男声",
             "zh-CN-YunyangNeural":"云扬 · 新闻男声","zh-CN-XiaoxiaoNeural":"晓晓 · 女声"};
  return m[CFG.voice] || CFG.voice;
}

function toast(msg){'''
assert old3 in s, "toast anchor"
s = s.replace(old3, new3, 1)

# 3) 移除两处 noop 残块
import re
s = re.sub(r"\nrep\('''[\s\S]*?''',\n\s*'''[\s\S]*?''',\n\s*\"noop2?\"\) if False else None\n", "\n", s)

p.write_text(s, encoding='utf-8')
print("optimize_ui.py cleaned")

# 执行
import subprocess, sys
r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True, encoding='utf-8', errors='replace')
print(r.stdout.strip())
print(r.stderr.strip()[-500:] if r.returncode else "")
