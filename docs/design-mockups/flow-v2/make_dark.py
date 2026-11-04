# 由浅色版 build_designs.py 派生深色主题：对源码做调色板替换后，在 dark/ 目录重新生成六页。
from pathlib import Path
import re
src = (Path(__file__).parent / 'build_designs.py').read_text(encoding='utf-8')

pairs = [
    # 底色与文字
    ('background:#f3f4f8;color:#25273c', 'background:#121420;color:#e3e5f0'),
    # 顶栏 / 卡片
    ('border-bottom:1px solid #e3e5ed;background:#fff', 'border-bottom:1px solid #262a38;background:#191c28'),
    ('background:#fff;border:1px solid #e1e3ec;border-radius:14px', 'background:#1a1d29;border:1px solid #2a2f3f;border-radius:14px'),
    ('border:1px solid #e1e3ec;border-radius:12px;margin-bottom:24px;padding:18px 26px', 'border:1px solid #2a2f3f;border-radius:12px;margin-bottom:24px;padding:18px 26px;background:#1a1d29'),
    ('background:white;font-size:14px;font-weight:600', 'background:#20242f;font-size:14px;font-weight:600'),
    ('border:1px solid #dce0e9', 'border:1px solid #323748'),
    # 步骤条
    ('background:#dce0e8', 'background:#323748'),
    ('background:#f0f1f6;color:#8e93a5', 'background:#242836;color:#8d93a8'),
    ('box-shadow:0 0 0 5px #f0edff', 'box-shadow:0 0 0 5px #26224a'),
    ('background:#e8f3ed;color:#33805d', 'background:#1e3129;color:#6fcf9a'),
    # 拖放区
    ('border:2px dashed #bdb5e9;border-radius:12px;background:#faf9ff', 'border:2px dashed #4c4478;border-radius:12px;background:#181a28'),
    ('border:1px solid #c1b9eb;background:white;box-shadow:8px 8px 0 #e8e3ff', 'border:1px solid #4c4478;background:#1e2130;box-shadow:8px 8px 0 #141622'),
    ('border-left:5px dotted #bdb3e8', 'border-left:5px dotted #4c4478'),
    # 右侧说明
    ('background:#f1effa;color:#7564c0', 'background:#26224a;color:#a99cf0'),
    # 最近项目
    ('background:#e9e6fa;color:#6657bd', 'background:#26224a;color:#a99cf0'),
    ('background:#f3f4f8;padding:5px 10px;border-radius:5px', 'background:#20242f;padding:5px 10px;border-radius:5px'),
    # 标签
    ('color:#397b5b;background:#eaf4ee', 'color:#6fcf9a;background:#1e3129'),
    ('background:#f4edff;color:#7851b1', 'background:#2a2350;color:#b39bef'),
    ('background:#f0f1f5;color:#858b9a', 'background:#242836;color:#8d93a8'),
    ('background:#f0f1f5;color:#9398a8;border-color:#e5e7ed', 'background:#20242f;color:#6d7386;border-color:#323748'),
    # 文案卡 / 配置
    ('background:#f7f8fb;padding:17px 20px', 'background:#20242f;padding:17px 20px'),
    ('border:1px solid #dfe2ec;border-radius:8px;padding:9px', 'border:1px solid #323748;border-radius:8px;padding:9px'),
    ('border:2px solid #7767da;padding:8px;background:#faf8ff;color:#6151bd', 'border:2px solid #7d6fe0;padding:8px;background:#221f42;color:#a99cf0'),
    ('border:1px solid #dfe2ec;border-radius:7px;padding:10px 13px', 'border:1px solid #323748;border-radius:7px;padding:10px 13px'),
    ('border:1px solid #e1e3ec;border-radius:6px;padding:6px 11px', 'border:1px solid #323748;border-radius:6px;padding:6px 11px'),
    ('background:#f3f0ff;border-color:#d4caf8', 'background:#26224a;border-color:#443c80'),
    # 素材缩略
    ('background:#e5edf2;display:grid;place-items:center;color:#485e79', 'background:#232a38;display:grid;place-items:center;color:#8fa3bd'),
    ('background:#eeeaf5', 'background:#262a3a'),
    ('background:#f0f1f5;color:#6b7083', 'background:#242836;color:#8d93a8'),
    ('background:#ffffffce', 'background:#151823d9'),
    ('background:#5586b5', 'background:#6f9cc0'),
    ('background:#cfdeea', 'background:#33415a'),
    ('color:#99a9bd', 'color:#5f7089'),
    # 模板缩略（浅色样式保持可辨识，微调）
    ('background:#f0ede5', 'background:#33363f'),
    ('background:#706d66', 'background:#9a9da8'),
    ('background:#b7b2a5;display:block', 'background:#565a66;display:block'),
    # 生成页
    ('background:#efedf8', 'background:#262a3a'),
    ('background:#e8eaf1', 'background:#2a2f3f'),
    ('background:#dfe8f1;padding:18px', 'background:#232c3c;padding:18px'),
    ('background:#8a9caf;margin-bottom:8px;box-shadow:0 16px 0 #b0c0d0', 'background:#4d5f77;margin-bottom:8px;box-shadow:0 16px 0 #333f52'),
    ('background:#e9e4f3', 'background:#2a2740'),
    ('background:#b7a9d3;box-shadow:0 16px 0 #d1c4e8', 'background:#4f466e;box-shadow:0 16px 0 #363052'),
    ('background:#e4eeeb', 'background:#22322e'),
    ('background:#f7f8fc;border-radius:8px;padding:14px 18px', 'background:#1c202c;border-radius:8px;padding:14px 18px'),
    ('background:#f2effc;padding:12px 10px;margin:3px -10px', 'background:#221f42;padding:12px 10px;margin:3px -10px'),
    # 导出页
    ('background:#e7f3ed;color:#3d8a65', 'background:#1e3129;color:#6fcf9a'),
    ('border:1px solid #e1e4ed;border-radius:10px;display:flex;align-items:center;gap:17px;margin-bottom:14px', 'border:1px solid #2a2f3f;border-radius:10px;display:flex;align-items:center;gap:17px;margin-bottom:14px'),
    ('background:#faf9ff;border-color:#d6cdf9', 'background:#1d1b2e;border-color:#3d3866'),
    ('border:1px solid #d0c9ed;background:white', 'border:1px solid #4c4478;background:#20242f'),
    ('background:#f7f8fb;border-radius:10px;padding:21px', 'background:#20242f;border-radius:10px;padding:21px'),
    ('border-top:1px solid #e6e8ef', 'border-top:1px solid #2a2f3f'),
    ('border-top:1px solid #e3e5ed;margin-top:24px;padding-top:20px', 'border-top:1px solid #2a2f3f;margin-top:24px;padding-top:20px'),
    ('border-bottom:1px solid #e9eaf0;padding-bottom:15px;margin-bottom:17px', 'border-bottom:1px solid #2a2f3f;padding-bottom:15px;margin-bottom:17px'),
    ('border-bottom:1px solid #e8e9ef;padding-right:26px', 'border-bottom:1px solid #2a2f3f;padding-right:26px'),
    ('border-right:1px solid #e8e9ef;padding-right:26px', 'border-right:1px solid #2a2f3f;padding-right:26px'),
    # 底部切换条
    ('background:#fff;border-top:1px solid #e2e4ec', 'background:#191c28;border-top:1px solid #262a38'),
    ('color:#5147b2;font-weight:bold', 'color:#a99cf0;font-weight:bold'),
    # 焦点环
    ('outline:3px solid #a595ee', 'outline:3px solid #7d6fe0'),
]
# 剩余零散灰字统一压到深底可读的灰蓝
grays = ['#707589','#737889','#787b8b','#75798a','#7c7988','#7d8396','#818397','#818697',
         '#858b9d','#858b9a','#9095a6','#8c90a1','#9398a8','#8b9099','#71798d','#757b90',
         '#7d8294','#83889a','#929d99','#485e79']
out = src
for a, b in pairs:
    out = out.replace(a, b)
for g in grays:
    out = out.replace(g, '#98a0b6')
# .sty 未选中卡片、脚本标题等残留浅底
out = out.replace('.sty{border:1px solid #323748;border-radius:8px;padding:9px;text-align:center;font-size:12px}',
                  '.sty{border:1px solid #323748;border-radius:8px;padding:9px;text-align:center;font-size:12px;background:#20242f;color:#98a0b6}')
out = out.replace("P=Path(__file__).parent", "P=Path(__file__).parent")
out = out.replace("print('Generated six independent design pages at', P)",
                  "print('Generated dark design pages at', P)")
d = Path(__file__).parent
d.mkdir(exist_ok=True)
(d / 'build_dark.py').write_text(out, encoding='utf-8')
import subprocess, sys
r = subprocess.run([sys.executable, str(d / 'build_dark.py')], capture_output=True, text=True)
print(r.stdout, r.stderr)
