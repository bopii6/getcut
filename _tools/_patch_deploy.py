#!/usr/bin/env python3
"""把 renderer/src 挂载加进服务器的 deploy_new.sh（幂等）"""
import io, sys

p = '/opt/videogen/deploy_new.sh'
s = io.open(p, encoding='utf-8').read()
if 'code/renderer/src' in s:
    print('已经加过了，跳过')
    sys.exit(0)

old = '  -v /opt/videogen/code/videogen:/app/videogen \\\n'
new = ('  -v /opt/videogen/code/videogen:/app/videogen \\\n'
       '  -v /opt/videogen/code/renderer/src:/app/renderer/src \\\n')
assert s.count(old) == 1, f'锚点数量 {s.count(old)}'
s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('已加入 renderer/src 挂载')
