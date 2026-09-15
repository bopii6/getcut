#!/usr/bin/env python3
"""Real Remotion progress: Popen + line parsing; cli wires it."""
from pathlib import Path

RR = Path(r'E:/短视频生成/videogen/videogen/remotion_render.py')
r = RR.read_text(encoding='utf-8')

old_run = '''    cmd = [node, str(cli_js), "render", "main", rel_out,
           "--props=props.json"]
    if progress:
        cmd += ["--log=verbose"]
    p = subprocess.run(cmd, cwd=str(RENDERER), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    produced = RENDERER / rel_out
    if p.returncode != 0 or not produced.is_file():
        raise RuntimeError("remotion render failed:" + chr(10) + (p.stderr or p.stdout or "")[-4000:])'''

new_run = '''    cmd = [node, str(cli_js), "render", "main", rel_out,
           "--props=props.json"]
    import re as _re
    proc = subprocess.Popen(cmd, cwd=str(RENDERER), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    tail: list[str] = []
    last_pct = -1
    try:
        for line in proc.stdout:  # 实时解析：Bundling x% / Rendered a/b
            tail.append(line)
            if len(tail) > 200:
                tail = tail[-200:]
            if progress is None:
                continue
            m = _re.search(r"Rendered\\s+(\\d+)\\s*/\\s*(\\d+)", line)
            if m and int(m.group(2)) > 0:
                pct = int(int(m.group(1)) / int(m.group(2)) * 100)
            else:
                m2 = _re.search(r"(\\d{1,3})%", line)
                pct = int(m2.group(1)) if m2 else -1
            if pct >= 0 and pct > last_pct:
                last_pct = pct
                try:
                    progress(pct)
                except Exception:
                    pass
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    produced = RENDERER / rel_out
    if proc.returncode != 0 or not produced.is_file():
        raise RuntimeError("remotion render failed:" + chr(10) + "".join(tail)[-4000:])'''

if old_run in r:
    r = r.replace(old_run, new_run)
    RR.write_text(r, encoding='utf-8')
    print("remotion_render: real progress parsed")
else:
    # 打印实际文本帮助定位
    i = r.find("cmd = [node, str(cli_js)")
    print("ACTUAL BLOCK:\n" + repr(r[i:i+560]))
    raise SystemExit(1)

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
print("cli: render progress wired")

import subprocess
r2 = subprocess.run(["python", "-c",
    "import sys; sys.path.insert(0, r'E:/短视频生成/videogen'); from videogen import cli, remotion_render, server; print('imports ok')"],
    capture_output=True, text=True)
print((r2.stdout or r2.stderr).strip()[-200:])
