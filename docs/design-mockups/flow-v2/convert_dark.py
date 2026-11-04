# 从未改动的浅色源码 build_designs.py 一次性生成深色六页，并自检残留浅底。
# 可重复运行：每次都从浅色源码重新转换，不依赖上一轮的补丁状态。
from pathlib import Path
import re, subprocess, sys

HERE = Path(__file__).parent
SRC = HERE / 'build_designs.py'          # 浅色源码，保持不动，随时可还原浅色版
OUT_GEN = HERE / 'build_dark.py'

# 调色板：浅色 → 深色（背景三级：页面 #121420 / 卡片 #1a1d29 / 内嵌面板 #20242f）
MAP = {
    '#f3f4f8': '#121420', '#25273c': '#e3e5f0',
    '#e3e5ed': '#262a38', '#e1e3ec': '#2a2f3f',
    '#dce0e9': '#323748', '#dce0e8': '#323748', '#dfe2ec': '#323748',
    '#e5e7ed': '#323748', '#e4dfff': '#443c80',
    '#f0edff': '#26224a', '#f3f0ff': '#26224a', '#e9e6fa': '#26224a', '#f1effa': '#26224a',
    '#f0f1f6': '#242836', '#f0f1f5': '#242836', '#eeeaf5': '#262a3a',
    '#e8f3ed': '#1e3129', '#eaf4ee': '#1e3129', '#e7f3ed': '#1e3129',
    '#33805d': '#6fcf9a', '#397b5b': '#6fcf9a', '#3d8a65': '#6fcf9a',
    '#bdb5e9': '#4c4478', '#bdb3e8': '#4c4478', '#c1b9eb': '#4c4478', '#d0c9ed': '#4c4478',
    '#e8e3ff': '#141622', '#faf9ff': '#1b1a2e',
    '#7564c0': '#a99cf0', '#6657bd': '#a99cf0', '#6151bd': '#a99cf0', '#6554bf': '#a99cf0',
    '#6759bf': '#a99cf0', '#5546bd': '#a99cf0', '#7360bd': '#a99cf0', '#796ac9': '#a99cf0',
    '#5147b2': '#a99cf0', '#6151ca': '#a99cf0', '#a595ee': '#7d6fe0', '#7767da': '#7d6fe0',
    '#faf8ff': '#221f42', '#f2effc': '#221f42', '#f4edff': '#2a2350', '#7851b1': '#b39bef',
    '#6d56cc': '#b39bef', '#d4caf8': '#443c80',
    '#f7f8fb': '#20242f', '#f7f8fc': '#1c202c',
    '#e5edf2': '#232a38', '#485e79': '#8fa3bd', '#6b7083': '#8d93a8',
    '#ffffffce': '#151823d9', '#5586b5': '#6f9cc0', '#cfdeea': '#33415a', '#99a9bd': '#5f7089',
    '#efedf8': '#262a3a', '#e8eaf1': '#2a2f3f',
    '#dfe8f1': '#232c3c', '#8a9caf': '#4d5f77', '#b0c0d0': '#333f52',
    '#e9e4f3': '#2a2740', '#b7a9d3': '#4f466e', '#d1c4e8': '#363052', '#e4eeeb': '#22322e',
    '#e1e4ed': '#2a2f3f', '#d6cdf9': '#3d3866', '#e6e8ef': '#2a2f3f', '#e9eaf0': '#2a2f3f',
    '#e8e9ef': '#2a2f3f', '#e2e4ec': '#262a38', '#e2e5ee': '#2a2f3f', '#e7eeea': '#262a38',
    # 方案三 .calm 浅绿主题（样式与主流程页共用一份 CSS，必须一并转深）
    '#f5f8f7': '#12141c', '#f5f8f6': '#20242f', '#e9f4ee': '#1e3129', '#edf4ef': '#26224a',
    '#dce6e2': '#2a2f3f', '#d7e2dd': '#323748', '#ccd8d2': '#323748',
    '#257964': '#2fa37f', '#397c66': '#6fcf9a', '#205e4c': '#5fd0a4', '#28785d': '#6fcf9a', '#488a70': '#7dd4ae',
    '#929d99': '#98a0b6', '#e7eeea ': '#262a38',
    # 方案二 .dark 画布主题自带深色，仅对齐底色
    '#111c2b': '#12141c', '#dbe5f3': '#e3e5f0',
    '#9398a8': '#6d7386', '#e5e7ed ': '#323748', '#a595ee ': '#7d6fe0',
}
GRAYS = ['#707589', '#737889', '#787b8b', '#75798a', '#7c7988', '#7d8396', '#818397',
         '#818697', '#858b9d', '#858b9a', '#9095a6', '#8c90a1', '#8b9099', '#71798d',
         '#757b90', '#7d8294', '#83889a', '#929d99', '#878299']
GRAY_TO = '#98a0b6'
# 内容性浅色，不是 UI 底色：模板缩略图本身就要显示浅色模板的样子
ALLOW_LIGHT_BG = {'#f6f6f6', '#f0ede5'}

src = SRC.read_text(encoding='utf-8')
out = src
for a, b in MAP.items():
    out = out.replace(a, b)
for g in GRAYS:
    out = out.replace(g, GRAY_TO)
# 纯白背景统一落到卡片底色，再对个别规则做定点击替
out = out.replace('background:#fff', 'background:#1a1d29').replace('background:white', 'background:#1a1d29')
for a, b in [
    ('border-bottom:1px solid #262a38;background:#1a1d29', 'border-bottom:1px solid #262a38;background:#191c28'),   # 顶栏
    ('background:#1a1d29;border-top:1px solid #262a38', 'background:#191c28;border-top:1px solid #262a38'),          # 切换条
    ('background:#1a1d29;font-size:14px;font-weight:600', 'background:#20242f;font-size:14px;font-weight:600'),       # 次级按钮
    ('background:#1a1d29;box-shadow:8px 8px 0 #141622', 'background:#1e2130;box-shadow:8px 8px 0 #141622'),           # ZIP 图标卡
    ('background:#1a1d29;border:1px solid #2a2f3f;border-radius:8px;overflow:hidden',
     'background:#1c202c;border:1px solid #2a2f3f;border-radius:8px;overflow:hidden'),                                # 分镜卡
    ('border-radius:12px;background:#1b1a2e', 'border-radius:12px;background:#161822'),                               # 拖放区
]:
    assert a in out, f'定点击替未命中: {a[:50]}'
    out = out.replace(a, b)

# ---- 校验：四张主流程页不允许残留高亮度背景 ----
def lum(hexv):
    h = hexv.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

OUT = HERE
tmp_gen = HERE / '_gen_dark.py'
tmp_gen.write_text(out, encoding='utf-8')
r = subprocess.run([sys.executable, tmp_gen], capture_output=True, text=True)
print(r.stdout, r.stderr)
if r.returncode != 0:
    sys.exit(r.returncode)

problems = []
for page in ['01-import', '02-confirm', '03-progress', '04-export']:
    html = (HERE / f'{page}.html').read_text(encoding='utf-8')
    for m in re.finditer(r'background:([^;"}]+)', html):
        v = m.group(1)
        if 'white' in v.lower():
            problems.append((page, v))
        for hexv in re.findall(r'#[0-9a-fA-F]{3,8}', v):
            if hexv.lower() in ALLOW_LIGHT_BG:
                continue
            if lum(hexv) > 0.80:
                problems.append((page, v.strip()))
if problems:
    for p, v in problems:
        print('残留浅底:', p, '→', v)
    sys.exit('校验失败：仍有浅色背景')
print('校验通过：01-04 无残留浅色背景')
