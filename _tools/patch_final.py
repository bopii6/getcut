#!/usr/bin/env python3
"""Final fix: correct var declarations (was: let poll = null) + step4 hydration.
Every anchor is taken verbatim from the current file (grep-verified)."""
from pathlib import Path

FE = Path(r'E:/短视频生成/videogen/server_static/index.html')
s = FE.read_text(encoding='utf-8')
applied = []

def rep(old, new, tag):
    global s
    assert old in s, f"anchor missing: {tag}"
    s = s.replace(old, new, 1)
    applied.append(tag)

# 1) variables: the file still declares only `poll`
rep("let poll = null;",
    "let poll = null;\nlet job = null, timer = null, lastJob = null, lastVideoJob = null;",
    "vars")

# 2) rail navigable
rep('''  ["01 选择素材","02 内容确认","03 渲染配置","04 生成与成片"].forEach((t,i) => {
    const n = i+1, on = n === step, done = n < step;
    const label = t.replace(/^0\\d /,"");
    const dis = n > step ? "disabled" : "";
    const click = n === 1 ? ` onclick="renderStudio(1)"` : "";
    rail += `<button class="${on?"on":done?"done":""}" ${dis}${click} data-n="${n}">
      <span class="n">${done?"✓":`0${n}`}</span><span>${label}</span></button>`;
  });''',
'''  ["01 选择素材","02 内容确认","03 渲染配置","04 生成与成片"].forEach((t,i) => {
    const n = i+1, on = n === step, done = n < step;
    const label = t.replace(/^0\\d /,"");
    const can = n === 1 ? true : (n <= 3 ? !!CUR.bundle : (!!lastJob || !!CUR.hasRender));
    const dis = can ? "" : "disabled";
    const click = can ? ` onclick="renderStudio(${n})"` : "";
    rail += `<button class="${on?"on":done?"done":""}" ${dis}${click} data-n="${n}">
      <span class="n">${done?"✓":`0${n}`}</span><span>${label}</span></button>`;
  });''',
    "rail")

# 3) hydrate step4 with existing render
rep("  if (step === 1 && CUR.bundle) step = 2;   // 已挂载素材包：与原版一致，直接落在内容确认",
'''  if (step === 1 && CUR.bundle) step = 2;   // 已挂载素材包：与原版一致，直接落在内容确认
  if (step === 4) {
    try {
      const rs = (CUR.renders || []).filter(r => r.file);
      if (rs.length) {
        const lr = rs[rs.length - 1];
        CUR.hasRender = true;
        if (!lastJob) lastVideoJob = lr.file.split("-").pop().replace(".mp4", "");
      }
    } catch (e) {}
  }''',
    "hydrate")

# 4) stepRender head
rep('''function stepRender(){
  return `<div class="panel">
    <h2>视频生成中</h2><p class="sub">第 1 次渲染 · ${CUR.title}</p>
    <div class="bar"><i id="pbar"></i></div>
    <h3 id="pstage">准备中</h3><p class="sub" id="ppct"></p>''',
'''function stepRender(){
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
    <p class="sub" id="ppct">${hasOld ? "100% · 成片已生成" : ""}</p>''',
    "stepRender-head")

# 5) stepRender tail
rep('''    <div class="err hide" id="perr"></div>
    <div id="pdone" class="hide">
      <video class="res" id="player" controls style="max-width:100%"></video>
      <a class="btn" id="dl" download style="text-decoration:none">下载成片</a>
    </div>
  </div>`;
}''',
'''    <div class="err hide" id="perr"></div>
    <div class="hide" id="pdoneNew">
      <video class="res" id="player2" controls style="max-width:100%"></video>
      <a class="btn" id="dl2" download style="text-decoration:none">下载成片</a>
    </div>
    ${oldBlock}
  </div>`;
}''',
    "stepRender-tail")

# 6) pollJob: fix stale clearInterval(poll) + support new ids
rep('''  if (j.stage === "failed"){
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
}''',
'''  if (j.stage === "failed"){
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
}''',
    "pollJob")

# 7) recovery branch: support pdoneNew ids
rep('''      $("pdone").classList.remove("hide");
      $("player").src = "/video/" + l.job;
      $("dl").href = "/video/" + l.job;
      return;''',
'''      lastVideoJob = l.job;
      const box2 = $("pdoneNew") || $("pdone");
      if (box2) box2.classList.remove("hide");
      const pl2 = $("player2") || $("player");
      if (pl2) pl2.src = "/video/" + l.job;
      const dl2 = $("dl2") || $("dl");
      if (dl2) dl2.href = "/video/" + l.job;
      return;''',
    "recovery")

FE.write_text(s, encoding='utf-8')
print("applied:", ", ".join(applied))
