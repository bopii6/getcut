#!/usr/bin/env python3
"""04 step shows existing renders; rail navigable to reached steps."""
from pathlib import Path

FE = Path(r'E:/短视频生成/videogen/server_static/index.html')
s = FE.read_text(encoding='utf-8')

# 1) rail: steps reachable when prerequisites exist
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
assert old in s, "rail anchor"
s = s.replace(old, new)

# 2) renderStudio(4): hydrate existing render info
old2 = '''  if (step === 1 && CUR.bundle) step = 2;   // 已挂载素材包：与原版一致，直接落在内容确认'''
new2 = '''  if (step === 1 && CUR.bundle) step = 2;   // 已挂载素材包：与原版一致，直接落在内容确认
  if (step === 4 && !lastJob) {
    // 进入 04 时若已有成片，直接展示最近一条（对齐原版行为）
    try {
      const rs = (CUR.renders || []).filter(r => r.file);
      if (rs.length) {
        const lr = rs[rs.length - 1];
        CUR.hasRender = true;
        const jid = lr.file.split("-").pop().replace(".mp4", "");
        lastJob = jid; lastVideoJob = jid;
      }
    } catch (e) {}
  }'''
assert old2 in s, "hydrate anchor"
s = s.replace(old2, new2)

# 3) stepRender: show existing video if available
old3 = '''function stepRender(){
  return `<div class="panel">
    <h2>视频生成中</h2><p class="sub">第 1 次渲染 · ${CUR.title}</p>
    <div class="bar"><i id="pbar"></i></div>
    <h3 id="pstage">准备中</h3><p class="sub" id="ppct"></p>'''
new3 = '''function stepRender(){
  const done = lastVideoJob ? `
    <div id="pdone">
      <video class="res" id="player" controls style="max-width:100%" src="/video/${lastVideoJob}"></video>
      <a class="btn" id="dl" download href="/video/${lastVideoJob}" style="text-decoration:none">下载成片</a>
      <p class="sub" style="margin-top:8px">最近一次成片 · 任务 ${lastVideoJob} · 再次渲染可生成新版本</p>
    </div>` : "";
  const state = lastVideoJob ? "渲染完成" : "准备中";
  const pctTxt = lastVideoJob ? "100% · 成片已生成" : "";
  const barW = lastVideoJob ? 100 : 0;
  const doneCls = lastVideoJob ? "" : "hide";
  return `<div class="panel">
    <h2>${lastVideoJob ? "生成与成片" : "视频生成中"}</h2><p class="sub">第 ${lastVideoJob ? ((CUR.renders||[]).length || 1) : 1} 次渲染 · ${CUR.title}</p>
    <div class="bar"><i id="pbar" style="width:${barW}%"></i></div>
    <h3 id="pstage">${state}</h3><p class="sub" id="ppct">${pctTxt}</p>'''
assert old3 in s, "stepRender anchor"
s = s.replace(old3, new3)

# 4) stepRender tail: reuse done block instead of hardcoded hidden
old4 = '''    <div class="err hide" id="perr"></div>
    <div id="pdone" class="hide">
      <video class="res" id="player" controls style="max-width:100%"></video>
      <a class="btn" id="dl" download style="text-decoration:none">下载成片</a>
    </div>
  </div>`;
}'''
new4 = '''    <div class="err hide" id="perr"></div>
    <div class="hide" id="pdoneNew">
      <video class="res" id="player2" controls style="max-width:100%"></video>
      <a class="btn" id="dl2" download style="text-decoration:none">下载成片</a>
    </div>
    ${done}
  </div>`;
}'''
assert old4 in s, "stepRender tail anchor"
s = s.replace(old4, new4)

# 5) pollJob done branch uses pdoneNew
old5 = '''  if (j.stage === "done"){
    clearInterval(timer);
    $("pbar").style.width = "100%"; $("pstage").textContent = "渲染完成";
    $("ppct").textContent = "100% · 成片已生成";
    $("pdone").classList.remove("hide");
    $("player").src = "/video/" + job;
    $("dl").href = "/video/" + job;
    addRender(job);
  }
}'''
new5 = '''  if (j.stage === "done"){
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
assert old5 in s, "pollJob done anchor"
s = s.replace(old5, new5)

# 6) state vars + recovery path uses pdoneNew
s = s.replace("let bundle = null, job = null, timer = null, lastJob = null;",
              "let bundle = null, job = null, timer = null, lastJob = null, lastVideoJob = null;")
old6 = '''    const l = await api("/api/latest");
    if (l && l.video) {
      clearInterval(timer);
      $("pbar").style.width = "100%";
      $("pstage").textContent = "渲染完成";
      $("ppct").textContent = "100% · 成片已生成";
      $("pdone").classList.remove("hide");
      $("player").src = "/video/" + l.job;
      $("dl").href = "/video/" + l.job;
      return;
    }'''
new6 = '''    const l = await api("/api/latest");
    if (l && l.video) {
      clearInterval(timer);
      lastVideoJob = l.job;
      $("pbar").style.width = "100%";
      $("pstage").textContent = "渲染完成";
      $("ppct").textContent = "100% · 成片已生成";
      const box = $("pdoneNew") || $("pdone");
      if (box) box.classList.remove("hide");
      const pl = $("player2") || $("player");
      if (pl) pl.src = "/video/" + l.job;
      const dl = $("dl2") || $("dl");
      if (dl) dl.href = "/video/" + l.job;
      return;
    }'''
assert old6 in s, "recovery anchor"
s = s.replace(old6, new6)

FE.write_text(s, encoding='utf-8')
print("04-step hydration + navigable rail applied (all anchors verified)")
