#!/usr/bin/env python3
"""Step4 hydration + navigable rail + fix stale clearInterval(poll). Anchors taken
from the CURRENT file content (verified by reading it)."""
from pathlib import Path

FE = Path(r'E:/短视频生成/videogen/server_static/index.html')
s = FE.read_text(encoding='utf-8')
applied = []

# 1) state vars
old = "let bundle = null, job = null, timer = null, lastJob = null;"
new = "let bundle = null, job = null, timer = null, lastJob = null, lastVideoJob = null;"
assert old in s; s = s.replace(old, new); applied.append("vars")

# 2) rail navigable
old = '''  ["01 选择素材","02 内容确认","03 渲染配置","04 生成与成片"].forEach((t,i) => {
    const n = i+1, on = n === step, done = n < step;
    const label = t.replace(/^0\\d /,"");
    const dis = n > step ? "disabled" : "";
    const click = n === 1 ? ` onclick="renderStudio(1)"` : "";
    rail += `<button class="${on?"on":done?"done":""}" ${dis}${click} data-n="${n}">
      <span class="n">${done?"✓":`0${n}`}</span><span>${label}</span></button>`;
  });'''
new = '''  ["01 选择素材","02 内容确认","03 渲染配置","04 生成与成片"].forEach((t,i) => {
    const n = i+1, on = n === step, done = n < step;
    const label = t.replace(/^0\\d /,"");
    const can = n === 1 ? true : (n <= 3 ? !!CUR.bundle : (!!lastJob || !!CUR.hasRender));
    const dis = can ? "" : "disabled";
    const click = can ? ` onclick="renderStudio(${n})"` : "";
    rail += `<button class="${on?"on":done?"done":""}" ${dis}${click} data-n="${n}">
      <span class="n">${done?"✓":`0${n}`}</span><span>${label}</span></button>`;
  });'''
assert old in s; s = s.replace(old, new); applied.append("rail")

# 3) hydrate step4
old = '''  if (step === 1 && CUR.bundle) step = 2;   // 已挂载素材包：与原版一致，直接落在内容确认'''
new = '''  if (step === 1 && CUR.bundle) step = 2;   // 已挂载素材包：与原版一致，直接落在内容确认
  if (step === 4 && !lastJob) {
    try {
      const rs = (CUR.renders || []).filter(r => r.file);
      if (rs.length) {
        const lr = rs[rs.length - 1];
        CUR.hasRender = true;
        lastVideoJob = lr.file.split("-").pop().replace(".mp4", "");
      }
    } catch (e) {}
  }'''
assert old in s; s = s.replace(old, new); applied.append("hydrate")

# 4) stepRender head — show existing render
old = '''function stepRender(){
  return `<div class="panel">
    <h2>视频生成中</h2><p class="sub">第 1 次渲染 · ${CUR.title}</p>
    <div class="bar"><i id="pbar"></i></div>
    <h3 id="pstage">准备中</h3><p class="sub" id="ppct"></p>'''
new = '''function stepRender(){
  const hasOld = !!lastVideoJob;
  const oldBlock = hasOld ? `
    <div id="pdone">
      <video class="res" id="player" controls style="max-width:100%" src="/video/${lastVideoJob}"></video>
      <a class="btn" id="dl" download href="/video/${lastVideoJob}" style="text-decoration:none">下载成片</a>
      <p class="sub" style="margin-top:8px">最近一次成片 · 任务 ${lastVideoJob} · 点「开始渲染」可生成新版本</p>
    </div>` : "";
  return `<div class="panel">
    <h2>${hasOld ? "生成与成片" : "视频生成中"}</h2>
    <p class="sub">第 ${hasOld ? (((CUR.renders||[]).length) || 1) : 1} 次渲染 · ${CUR.title}</p>
    <div class="bar"><i id="pbar" style="width:${hasOld ? 100 : 0}%"></i></div>
    <h3 id="pstage">${hasOld ? "渲染完成" : "准备中"}</h3>
    <p class="sub" id="ppct">${hasOld ? "100% · 成片已生成" : ""}</p>'''
assert old in s; s = s.replace(old, new); applied.append("stepRender-head")

# 5) stepRender tail — new-render done box
old = '''    <div class="err hide" id="perr"></div>
    <div id="pdone" class="hide">
      <video class="res" id="player" controls style="max-width:100%"></video>
      <a class="btn" id="dl" download style="text-decoration:none">下载成片</a>
    </div>
  </div>`;
}'''
new = '''    <div class="err hide" id="perr"></div>
    <div class="hide" id="pdoneNew">
      <video class="res" id="player2" controls style="max-width:100%"></video>
      <a class="btn" id="dl2" download style="text-decoration:none">下载成片</a>
    </div>
    ${oldBlock}
  </div>`;
}'''
assert old in s; s = s.replace(old, new); applied.append("stepRender-tail")

# 6) pollJob: fix stale clearInterval(poll) + support pdoneNew
old = '''  if (j.stage === "failed"){
    clearInterval(poll);
    $("pstage").textContent = "渲染失败";
    $("perr").classList.remove("hide"); $("perr").textContent = j.error || "";
    return;
  }
  if (j.stage === "done"){
    clearInterval(poll);
    $("pbar").style.width = "100%"; $("pstage").textContent = "渲染完成";
    $("ppct").textContent = "100% · 成片已生成";
    $("pdone").classList.remove("hide");
    $("player").src = "/video/" + job;
    $("dl").href = "/video/" + job;
    addRender(job);
  }
}'''
new = '''  if (j.stage === "failed"){
    clearInterval(timer);
    $("pstage").textContent = "渲染失败";
    $("perr").classList.remove("hide"); $("perr").textContent = j.error || "";
    return;
  }
  if (j.stage === "done"){
    clearInterval(timer);
    lastVideoJob = job;
    $("pbar").style.width = "100%"; $("pstage").textContent = "渲染完成";
    $("ppct").textContent = "100% · 成片已生成";
    const box = $("pdoneNew") || $("pdone");
    if (box) box.classList.remove("hide");
    const pl = $("player2") || $("player");
    if (pl) pl.src = "/video/" + job;
    const dl = $("dl2") || $("dl");
    if (dl) dl.href = "/video/" + job;
    addRender(job);
  }
}'''
assert old in s; s = s.replace(old, new); applied.append("pollJob")

# 7) recovery branch: support pdoneNew too
old = '''      $("pdone").classList.remove("hide");
      $("player").src = "/video/" + l.job;
      $("dl").href = "/video/" + l.job;
      return;'''
new = '''      lastVideoJob = l.job;
      const box2 = $("pdoneNew") || $("pdone");
      if (box2) box2.classList.remove("hide");
      const pl2 = $("player2") || $("player");
      if (pl2) pl2.src = "/video/" + l.job;
      const dl2 = $("dl2") || $("dl");
      if (dl2) dl2.href = "/video/" + l.job;
      return;'''
assert old in s; s = s.replace(old, new); applied.append("recovery")

FE.write_text(s, encoding='utf-8')
print("applied:", ", ".join(applied))
