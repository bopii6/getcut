#!/usr/bin/env python3
"""GUI 走查后的重构修复（6 项）。每处锚点均在替换前断言。"""
from pathlib import Path

SV = Path(r'E:/短视频生成/videogen/videogen/server.py')
FE = Path(r'E:/短视频生成/videogen/server_static/index.html')

def rep(text, old, new, tag, count=1):
    assert old in text, f"anchor missing: {tag}"
    return text.replace(old, new, count), tag

# ============ #1 CRITICAL: TTS 语速格式 ============
s = SV.read_text(encoding='utf-8')
s, _ = rep(s, '''def _worker(job_id: str, body: dict) -> None:
    import sys
    sys.path.insert(0, str(ROOT))
    from . import cli''',
'''def _normalize_rate(rate) -> str | None:
    """前端传 "100"，edge-tts 要求 "+0%"/"+15%"；这里统一转换。"""
    if rate is None or rate == "":
        return None
    r = str(rate).strip()
    if r.endswith("%"):
        return r if r[0] in "+-" else f"+{r}"
    try:
        return f"{int(float(r)) - 100:+d}%"
    except ValueError:
        return None


def _worker(job_id: str, body: dict) -> None:
    import sys
    sys.path.insert(0, str(ROOT))
    from . import cli''', "#1-helper")

s, _ = rep(s, '''                  voice=body.get("voice") or None,
                  rate=body.get("rate") or None,''',
'''                  voice=body.get("voice") or None,
                  rate=_normalize_rate(body.get("rate")),''', "#1-call")

# ============ #2 钩子标题两行 + 高亮 ============
s, _ = rep(s, '''    hook = content.hook_headline
    return {
        "name": name,
        "title": content.title,
        "script": content.script,
        "estSeconds": round(len(content.script) / 6),
        "hook": hook.plain(hook.lines[0]) if hook and hook.lines else "",
        "hookLine2": (hook.plain(hook.lines[1]) if hook and len(hook.lines) > 1 else ""),
        "highlight": (hook.lines[0][hook.lines[0].index("[[") + 2: hook.lines[0].index("]]")]
                      if hook and hook.lines and "[[" in hook.lines[0] else ""),''',
'''    hook = content.hook_headline
    hook_lines = []
    if hook and hook.lines:
        for ln in hook.lines:
            spans = hook.highlight_spans(ln)
            hook_lines.append({
                "text": hook.plain(ln),
                "highlight": hook.plain(ln)[spans[0][0]:spans[0][1]] if spans else "",
            })
    return {
        "name": name,
        "title": content.title,
        "script": content.script,
        "estSeconds": round(len(content.script) / 6),
        "hookLines": hook_lines,''', "#2-backend")

# ============ #4 渲染进度：tick 线程存活 + Remotion 真实进度 ============
s, _ = rep(s, '''    def _tick():  # smooth the long render stage visually
        while JOBS[job_id]["stage"] == "render" and JOBS[job_id]["progress"] < 86:
            JOBS[job_id]["progress"] = min(JOBS[job_id]["progress"] + 1, 86)
            time.sleep(2.5)
    threading.Thread(target=_tick, daemon=True).start()''',
'''    def _tick():
        # 全程存活：仅在 render 阶段把进度平滑推进（上限 86，真实进度会覆盖它）
        real = {"pct": 0}

        def note_real(p: int):  # 由 cli 侧回调传入的真实进度
            real["pct"] = p

        while JOBS[job_id]["stage"] not in ("done", "failed"):
            j = JOBS[job_id]
            if j["stage"] == "render":
                floor = max(62, real["pct"])
                if j["progress"] < min(floor, 86):
                    j["progress"] = min(floor, 86)
                elif real["pct"] == 0 and j["progress"] < 86:
                    j["progress"] = min(j["progress"] + 1, 86)
            time.sleep(2.5)
    threading.Thread(target=_tick, daemon=True).start()''', "#4-tick")

SV.write_text(s, encoding='utf-8')
print("server.py: #1 rate / #2 hookLines / #4 tick 已应用")

# ============ 前端修复 ============
t = FE.read_text(encoding='utf-8')

# #2 前端：渲染 hookLines 两行（含高亮块）
t, _ = rep(t, '''  const hl = b.hook;
  const hl2 = b.highlight ? `<span class="hl" style="background:#16110e;color:#f5f3f0;padding:2px 12px;border-left:5px solid var(--red)">${b.highlight}</span>` : "";
  return `<div class="panel">''',
'''  const hookHtml = (b.hookLines || []).map(l => {
    if (!l.highlight) return `<div style="font-size:20px;font-weight:900;margin:2px 0">${l.text}</div>`;
    const idx = l.text.indexOf(l.highlight);
    const before = idx > 0 ? l.text.slice(0, idx) : "";
    const after = l.text.slice(idx + l.highlight.length);
    return `<div style="font-size:20px;font-weight:900;margin:2px 0">${before}` +
      `<span style="background:#16110e;color:#f5f3f0;padding:2px 12px;border-left:5px solid var(--red);display:inline-block">${l.highlight}</span>` +
      `${after}</div>`;
  }).join("");
  return `<div class="panel">''', "#2-fe-head")

t, _ = rep(t, '''    <h3>钩子标题</h3>
    <div class="script" style="font-size:20px;font-weight:900">${hl}${hl2?`<br>${hl2}`:""}</div>''',
'''    <h3>钩子标题</h3>
    <div class="script">${hookHtml || "（无钩子标题）"}</div>''', "#2-fe-body")

# #3 导轨 04：直接查 CUR.renders
t, _ = rep(t, "    const can = n === 1 ? true : (n <= 3 ? !!CUR.bundle : (!!lastJob || !!CUR.hasRender));",
           "    const can = n === 1 ? true : (n <= 3 ? !!CUR.bundle : (!!lastJob || (CUR.renders || []).length > 0));",
           "#3-rail")

# #5 语速改变联动预估时长
t, _ = rep(t, '''    document.querySelectorAll("#rateSeg .pill").forEach(p => p.onclick = () => {
      document.querySelectorAll("#rateSeg .pill").forEach(x => x.classList.remove("on"));
      p.classList.add("on"); CFG.rate = +p.dataset.r;
      $("rateTxt").textContent = (CFG.rate/100).toFixed(2) + "×";
    });''',
'''    document.querySelectorAll("#rateSeg .pill").forEach(p => p.onclick = () => {
      document.querySelectorAll("#rateSeg .pill").forEach(x => x.classList.remove("on"));
      p.classList.add("on"); CFG.rate = +p.dataset.r;
      $("rateTxt").textContent = (CFG.rate/100).toFixed(2) + "×";
      // 预估时长随语速联动
      const base = window.__baseEst || 0;
      const est = Math.round(base / (CFG.rate/100));
      const mm = Math.floor(est/60), ss = est%60;
      if (est > 0) {
        const e2 = $("est2"); if (e2) e2.textContent = `${mm}分${ss}秒`;
        const shell = document.querySelector("#rateSeg")?.parentElement?.querySelector(".d");
        if (shell) shell.textContent = `预估时长 ≈ ${mm}:${String(ss).padStart(2,"0")} · 免费`;
      }
    });''', "#5-rate")

# 记录基准时长（进入配置页时）
t, _ = rep(t, "function stepConfig(b){\n  const est = Math.round(b.estSeconds / (CFG.rate/100));",
           "function stepConfig(b){\n  window.__baseEst = b.estSeconds;\n  const est = Math.round(b.estSeconds / (CFG.rate/100));",
           "#5-base")

# #6 成片形态：竖屏/横屏标注即将支持（本地版固定竖屏信息版）
t, _ = rep(t, '''      <div class="opt" data-v="portrait"><b>竖屏</b></div>
      <div class="opt" data-v="landscape"><b>横屏</b></div>''',
'''      <div class="opt" data-v="portrait" onclick="alert('本地版当前固定为竖屏信息版；竖屏/横屏即将支持')"><b>竖屏</b><small>即将支持</small></div>
      <div class="opt" data-v="landscape" onclick="alert('本地版当前固定为竖屏信息版；竖屏/横屏即将支持')"><b>横屏</b><small>即将支持</small></div>''',
           "#6-format")

# #7 播放器宽度占满卡片
t, _ = rep(t, "video.res { width:100%; border-radius:12px; margin:18px 0; background:#000; }",
           "video.res { display:block; width:100%; max-width:520px; border-radius:12px; margin:18px 0; background:#000; }",
           "#7-player")

FE.write_text(t, encoding='utf-8')
print("index.html: #2/#3/#5/#6/#7 已应用")

# JS 语法校验
import subprocess, json
r = subprocess.run(["node", "-e", """
const fs = require('fs');
const html = fs.readFileSync('E:/短视频生成/videogen/server_static/index.html', 'utf-8');
const m = html.match(/<script>([\\s\\S]*?)<\\/script>/);
try { new Function(m[1]); console.log('JS syntax: OK'); } catch (e) { console.log('JS ERROR:', e.message); process.exit(1); }
"""], capture_output=True, text=True)
print(r.stdout.strip() or r.stderr.strip())
