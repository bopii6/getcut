#!/usr/bin/env python3
import re
from pathlib import Path

RR = Path(r'E:/短视频生成/videogen/videogen/remotion_render.py')
r = RR.read_text(encoding='utf-8')

pat1 = re.compile(
    r'    if progress:\n        cmd \+= \["--log=verbose"\]\n'
    r'    p = subprocess\.run\(cmd, cwd=str\(RENDERER\), capture_output=True, text=True,\n'
    r'                       encoding="utf-8", errors="replace", timeout=timeout\)\n'
)
new1 = (
    '    import re as _re\n'
    '    proc = subprocess.Popen(cmd, cwd=str(RENDERER), stdout=subprocess.PIPE,\n'
    '                            stderr=subprocess.STDOUT, text=True,\n'
    '                            encoding="utf-8", errors="replace")\n'
    '    tail: list[str] = []\n'
    '    last_pct = -1\n'
    '    try:\n'
    '        for line in proc.stdout:  # 实时解析：Bundling x% / Rendered a/b\n'
    '            tail.append(line)\n'
    '            if len(tail) > 200:\n'
    '                tail = tail[-200:]\n'
    '            if progress is None:\n'
    '                continue\n'
    '            m = _re.search(r"Rendered\\s+(\\d+)\\s*/\\s*(\\d+)", line)\n'
    '            if m and int(m.group(2)) > 0:\n'
    '                pct = int(int(m.group(1)) / int(m.group(2)) * 100)\n'
    '            else:\n'
    '                m2 = _re.search(r"(\\d{1,3})%", line)\n'
    '                pct = int(m2.group(1)) if m2 else -1\n'
    '            if pct >= 0 and pct > last_pct:\n'
    '                last_pct = pct\n'
    '                try:\n'
    '                    progress(pct)\n'
    '                except Exception:\n'
    '                    pass\n'
    '        proc.wait(timeout=timeout)\n'
    '    except subprocess.TimeoutExpired:\n'
    '        proc.kill()\n'
    '        raise\n'
)
n1 = len(pat1.findall(r))
r = pat1.sub(lambda m: new1, r)

pat2 = re.compile(
    r'    if p\.returncode != 0 or not produced\.is_file\(\):\n'
    r'        raise RuntimeError\("remotion render failed:\\\\n" \+ \(p\.stderr or p\.stdout or ""\)\[-4000:\]\)\n'
)
new2 = (
    '    if proc.returncode != 0 or not produced.is_file():\n'
    '        raise RuntimeError("remotion render failed:" + chr(10) + "".join(tail)[-4000:])\n'
)
n2 = len(pat2.findall(r))
r = pat2.sub(lambda m: new2, r)

print("段1:", n1, "段2:", n2)
if n1 == 1 and n2 == 1:
    RR.write_text(r, encoding='utf-8')
    print("remotion_render updated")
else:
    raise SystemExit("anchor miss")

CL = Path(r'E:/短视频生成/videogen/videogen/cli.py')
c = CL.read_text(encoding='utf-8')
old_c = '''        report("render", 30)
        visual = remotion_render.render_visual(props, work / "visual.mp4",
                                               progress=lambda p: report("render", 30 + int(p * 0.45)))'''
new_c = '''        report("render", 0)
        visual = remotion_render.render_visual(
            props, work / "visual.mp4",
            progress=lambda p: report("render", max(0, min(p, 100))))'''
assert old_c in c, "cli anchor"
c = c.replace(old_c, new_c)
CL.write_text(c, encoding='utf-8')
print("cli wired")

import subprocess
r2 = subprocess.run(["python", "-c",
    "import sys; sys.path.insert(0, r'E:/短视频生成/videogen'); from videogen import cli, remotion_render, server; print('imports ok')"],
    capture_output=True, text=True)
print((r2.stdout or r2.stderr).strip()[-200:])
