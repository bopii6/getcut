"""列出产品本体里行数最多的文件（配合 _loc_count.py 用）。"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = ['videogen/videogen', 'videogen/server_static', 'videogen/renderer',
           'videogen/tests', 'videogen/tools']
SKIP = {'node_modules', '__pycache__', 'outputs', 'work', 'dist', 'build'}
CODE = {'.py', '.ts', '.tsx', '.js', '.mjs', '.cjs', '.html', '.css'}

found = []
for t in TARGETS:
    for dp, dns, fns in os.walk(os.path.join(ROOT, t)):
        dns[:] = [d for d in dns if d not in SKIP]
        for f in fns:
            if os.path.splitext(f)[1].lower() not in CODE:
                continue
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, ROOT)
            if 'package-lock' in f or 'draftsrc' in rel:
                continue
            try:
                with open(full, encoding='utf-8', errors='ignore') as fh:
                    n = sum(1 for _ in fh)
            except OSError:
                continue
            found.append((n, rel.replace(os.sep, '/')))

found.sort(reverse=True)
print('%-8s %s' % ('行数', '文件'))
for n, rel in found[:14]:
    print('%-8d %s' % (n, rel))
print('\n产品本体文件数：%d' % len(found))
print('参考克隆结构：')
clone = os.path.join(ROOT, 'niwo-render-everything')
for dp, dns, fns in os.walk(clone):
    dns[:] = [d for d in dns if d not in SKIP]
    depth = dp[len(clone):].count(os.sep)
    if depth > 2:
        dns[:] = []
        continue
    for f in fns[:6]:
        print('  ' + os.path.join(dp[len(clone) + 1:], f).replace(os.sep, '/'))
