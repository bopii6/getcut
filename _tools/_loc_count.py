"""统计本项目代码行数（一次性脚本）。
口径：只统计源码/文档/配置；排除依赖、产物、素材与二进制。
"""
import os
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.deps', 'venv', '.venv', 'outputs',
             'work', 'dist', 'build', '.next', 'site-packages', '.pytest_cache',
             '.mypy_cache', '_cand', '_cand2', 'renderer-media', 'reinstall_test',
             '.idea', '.vscode', 'assets'}
CODE = {'.py': 'Python', '.ts': 'TS', '.tsx': 'TSX', '.js': 'JS', '.mjs': 'JS',
        '.cjs': 'JS', '.jsx': 'JSX', '.html': 'HTML', '.css': 'CSS', '.sh': 'Shell',
        '.ps1': 'PS1', '.bat': 'BAT'}
DOC = {'.md': 'Markdown', '.txt': 'Text'}
CFG = {'.json': 'JSON', '.toml': 'TOML', '.yml': 'YAML', '.yaml': 'YAML', '.ini': 'INI'}
BIN = {'.mp4', '.zip', '.png', '.jpg', '.jpeg', '.webp', '.mp3', '.wav', '.woff2',
       '.ttf', '.ico', '.pdf', '.xlsx', '.psd', '.draft', '.json.gz'}
BINCOUNT = collections.Counter()
BINBYTES = collections.Counter()


def module_of(rel):
    p = rel.replace(os.sep, '/')
    if p.startswith('videogen/videogen/'):
        return 'videogen · 后端 (py)'
    if p.startswith('videogen/server_static/'):
        return 'videogen · 前端 (单页)'
    if p.startswith('videogen/renderer/'):
        return 'videogen · Remotion 渲染器'
    if p.startswith('videogen/tests/'):
        return 'videogen · 离线契约测试'
    if p.startswith('videogen/'):
        return 'videogen · 脚本/Docker/配置'
    if p.startswith('_tools/'):
        return '_tools 采集/构建脚本'
    if p.startswith('design-mockups/'):
        return 'design-mockups 设计稿'
    if p.startswith('niwo-render-everything/'):
        return 'niwo-render-everything(参考)'
    if p.startswith('tools/'):
        return 'tools'
    if p.startswith('cloud/'):
        return 'cloud'
    return '根目录 / 其它'


def readlines(full):
    try:
        with open(full, encoding='utf-8', errors='ignore') as fh:
            return fh.readlines()
    except OSError:
        return None


rows = collections.defaultdict(lambda: {'files': 0, 'lines': 0, 'nonblank': 0,
                                        'docs': 0, 'doclines': 0, 'cfg': 0,
                                        'cfglines': 0, 'lang': collections.Counter()})
for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if d not in SKIP_DIRS]
    for f in fns:
        full = os.path.join(dp, f)
        rel = os.path.relpath(full, ROOT)
        ext = os.path.splitext(f)[1].lower()
        m = rows[module_of(rel)]
        if ext in CODE or ext in DOC or ext in CFG:
            L = readlines(full)
            if L is None:
                continue
            if ext in CODE:
                m['files'] += 1
                m['lines'] += len(L)
                m['nonblank'] += sum(1 for x in L if x.strip())
                m['lang'][CODE[ext]] += len(L)
            elif ext in DOC:
                m['docs'] += 1
                m['doclines'] += len(L)
                m['lang']['Markdown'] += len(L)
            else:
                m['cfg'] += 1
                m['cfglines'] += len(L)
                m['lang'][CFG[ext]] += len(L)
        elif ext in BIN:
            BINCOUNT[ext] += 1
            try:
                BINBYTES[ext] += os.path.getsize(full)
            except OSError:
                pass

print('%-30s%7s%8s%8s%8s%8s   %s' % ('模块', '代码文件', '代码行', '非空行', '文档行', '配置行', '语言'))
print('-' * 104)
TL = TN = TD = TC = TF = 0
for name, m in sorted(rows.items(), key=lambda kv: -kv[1]['lines']):
    if m['lines'] == 0 and m['doclines'] == 0:
        continue
    langs = ' '.join('%s %d' % (k, v) for k, v in sorted(m['lang'].items(), key=lambda x: -x[1]))
    print('%-30s%7d%8d%8d%8d%8d   %s' % (name, m['files'], m['lines'], m['nonblank'],
                                         m['doclines'], m['cfglines'], langs[:44]))
    TL += m['lines']
    TN += m['nonblank']
    TD += m['doclines']
    TC += m['cfglines']
    TF += m['files']
print('-' * 104)
print('%-30s%7d%8d%8d%8d%8d' % ('合计', TF, TL, TN, TD, TC))

keys = ['videogen · 后端 (py)', 'videogen · 前端 (单页)', 'videogen · Remotion 渲染器',
        'videogen · 离线契约测试']
prod = sum(rows[k]['lines'] for k in keys)
print('\n产品本体（后端+前端+渲染器+测试）：%d 行' % prod)
langs = collections.Counter()
for m in rows.values():
    langs.update(m['lang'])
print('按语言：' + '，'.join('%s %d' % (k, v) for k, v in sorted(langs.items(), key=lambda x: -x[1])))
print('\n排除的二进制/产物：' +
      '，'.join('%s %d 个 (%.0f MB)' % (k, v, BINBYTES[k] / 1048576)
                for k, v in sorted(BINCOUNT.items(), key=lambda x: -x[1])))
