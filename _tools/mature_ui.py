#!/usr/bin/env python3
"""成熟度升级（对齐原版）：首页封面卡/分区/引导卡/页脚版本戳 + 配置页版面预览/冲突警告/语速微调。"""
from pathlib import Path

FE = Path(r'E:/短视频生成/videogen/server_static/index.html')
s = FE.read_text(encoding='utf-8')
applied = []


def rep(old, new, tag, count=1):
    global s
    assert old in s, f"ANCHOR MISS: {tag}"
    s = s.replace(old, new, count)
    applied.append(tag)


# ---------- 1. 首页重写：封面卡 + 双分区 + 引导卡 + 页脚 ----------
rep('''async function renderHome(){
  $("sidebar").classList.add("hide");
  const projs = await api("/api/projects");
  $("main").innerHTML = `
    <h1>我的视频项目</h1>
    <p class="sub">每个项目是一份独立草稿。用 Agent Skill 做出 zip 素材包，上传后在这里渲染成片。</p>
    <button class="btn" id="newProj">＋ 新建项目</button>
    <h3>全部项目</h3>
    <div class="grid" id="projGrid"></div>`;
  $("newProj").onclick = async () => {
    const r = await api("/api/projects/create", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    CUR = {project_id: r.project_id, title:"新建项目", bundle:null};
    renderStudio(1);
  };
  const g = $("projGrid");
  if (!projs.length) g.innerHTML = "<p class='sub'>还没有项目。点上面的「新建项目」，再上传一个素材包 zip 即可开始。</p>";
  projs.forEach(p => {
    const d = document.createElement("div");
    d.className = "card";
    d.innerHTML = `<div class="pad"><strong>${p.title}</strong>
      <div class="meta">${(p.renders||[]).length} 个成片 · ${p.created}</div></div>
      <button class="del">删除项目</button>`;
    d.onclick = (e) => { if (e.target.className === "del") return; CUR = p; renderStudio(1); };
    d.querySelector(".del").onclick = (e) => {
      e.stopPropagation();
      confirmBox(`删除项目「${p.title}」？`, "项目及其渲染记录将一并删除，此操作不可撤销。",
        async () => {
          await api(`/api/projects/${p.project_id}/delete`, {method:"POST"});
          toast("已删除项目");
          renderHome();
        });
    };
    g.appendChild(d);
  });
}''',
'''function projectCard(p){
  const d = document.createElement("div");
  d.className = "card";
  const cover = p.cover
    ? `<img class="cover" loading="lazy" alt="${p.title}" src="${p.cover}">`
    : `<div class="cover cover-empty">${(p.title || "?").slice(0, 1)}</div>`;
  d.innerHTML = `${cover}
    <div class="pad">
      <div class="chipmeta">${p.renders_count || 0} 个成片${p.renders_count ? " · 已完成" : ""}</div>
      <strong>${p.title}</strong>
      <div class="meta">${p.assets_count ?? "-"} 个素材 · ${p.created}</div>
    </div>
    <button class="del" aria-label="删除项目 ${p.title}">删除项目</button>`;
  d.onclick = (e) => { if (e.target.className === "del") return; CUR = p; renderStudio(1); };
  d.querySelector(".del").onclick = (e) => {
    e.stopPropagation();
    confirmBox(`删除项目「${p.title}」？`, "项目及其渲染记录将一并删除，此操作不可撤销。",
      async () => {
        await api(`/api/projects/${p.project_id}/delete`, {method:"POST"});
        toast("已删除项目");
        renderHome();
      });
  };
  return d;
}

async function renderHome(){
  $("sidebar").classList.add("hide");
  const projs = await api("/api/projects");
  $("main").innerHTML = `
    <h1>我的视频项目</h1>
    <p class="sub">每个项目是一份独立草稿。用 Agent Skill 做出 zip 素材包，上传后在这里渲染成片。</p>
    <div class="hero-actions">
      <button class="btn" id="newProj">＋ 新建项目</button>
      <button class="btn ghost" id="showHelp">怎么开始？</button>
    </div>
    ${projs.length ? "" : `
    <div class="onboard">
      <strong>还没有素材包？</strong>
      <p>两种方式开始：把你手上的 zip 素材包拖进「新建项目」的上传区；或在项目里直接从工作区选择已有素材包。</p>
      <p class="hint">素材包结构：content.json（文案）+ manifest.json（素材清单）+ images/ + videos/</p>
    </div>`}
    ${projs.length ? '<h3>最近项目</h3><div class="grid" id="recentGrid"></div>' : ""}
    <h3>全部项目</h3>
    <div class="grid" id="projGrid"></div>
    <div class="footver">videogen · 本地版 1.0 · 渲染管线与成片规范对齐 Niwo</div>`;
  $("newProj").onclick = async () => {
    const r = await api("/api/projects/create", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    CUR = {project_id: r.project_id, title:"新建项目", bundle:null};
    renderStudio(1);
  };
  $("showHelp").onclick = () => confirmBox("三步做出第一条片子",
    "1. 新建项目 → 上传或选择素材包 zip；2. 内容确认 → 核对文案与素材；3. 渲染配置 → 选好音色语速后点「开始渲染」。成片会出现在第 4 步，可直接播放和下载。",
    () => {}, "知道了", true);
  const g = $("projGrid");
  if (!projs.length) g.innerHTML = "<p class='sub'>还没有项目。点上面的「新建项目」，再上传一个素材包 zip 即可开始。</p>";
  projs.forEach(p => g.appendChild(projectCard(p)));
  const recent = $("recentGrid");
  if (recent) projs.slice(0, 3).forEach(p => recent.appendChild(projectCard(p)));
}''',
    "home-rewrite")

# ---------- 2. 首页/卡片新样式 ----------
rep('''.skip{position:absolute;left:-9999px;top:8px;''',
'''.hero-actions{display:flex;gap:10px;margin:14px 0 6px}
.onboard{background:var(--panel);border:1px dashed #3a3a3a;border-radius:14px;padding:18px 20px;margin:18px 0}
.onboard strong{font-size:var(--fs-16)}
.onboard p{color:var(--gray);font-size:var(--fs-13);margin-top:8px;max-width:60ch}
.onboard .hint{font-family:Consolas,monospace;font-size:var(--fs-12);color:#7f7f7f}
.card .cover{width:100%;height:132px;object-fit:cover;display:block;background:#191919}
.card .cover-empty{display:flex;align-items:center;justify-content:center;color:#4a4a4a;
                   font-size:44px;font-weight:900}
.card .chipmeta{display:inline-block;background:#262626;color:var(--lime);border-radius:6px;
                padding:2px 10px;font-size:var(--fs-11);margin-bottom:8px}
.footver{color:#6a6a6a;font-size:var(--fs-12);margin-top:34px;padding-top:14px;border-top:1px solid var(--line)}
.mediapreview{display:flex;gap:14px;align-items:flex-end;margin:10px 0 4px}
.ph{background:#232323;border:1px solid var(--line);border-radius:6px}
.ph.v{width:56px;height:100px}
.ph.h{width:118px;height:66px}
.ph.emb{width:118px;height:66px;display:flex;align-items:center;justify-content:center}
.ph.emb i{display:block;width:74px;height:42px;background:#2e2e2e;border-radius:3px;
          border:1px solid #3d3d3d}
.ph.on{border-color:var(--lime)}
.phcap{color:var(--gray);font-size:var(--fs-11);text-align:center;margin-top:6px}
.warn{margin-top:10px;padding:10px 14px;border-radius:10px;font-size:var(--fs-13);
      background:#2a1d14;border:1px solid #4a3320;border-left:4px solid #d08b3f;color:#e8c79a}
.finetune{display:inline-flex;gap:10px;margin-top:12px}
.skip{position:absolute;left:-9999px;top:8px;''',
    "home-css")

# ---------- 3. 配置页：成片形态预览 + 冲突警告 ----------
rep('''    <h4>成片形态</h4>
    <div class="optrow" id="fmt">
      <div class="opt on" data-v="portrait_editorial"><b>竖屏信息版</b></div>
      <div class="opt" data-v="portrait" onclick="alert('本地版当前固定为竖屏信息版；竖屏/横屏即将支持')"><b>竖屏</b><small>即将支持</small></div>
      <div class="opt" data-v="landscape" onclick="alert('本地版当前固定为竖屏信息版；竖屏/横屏即将支持')"><b>横屏</b><small>即将支持</small></div>
    </div>
    <h5>版面</h5><div class="optrow"><div class="opt on"><b>卡片式</b><small>纸卡加方形内容区</small></div>
    <div class="opt"><b>更换版面</b></div></div>''',
'''    <h4>成片形态</h4>
    <div class="optrow" id="fmt">
      <div class="opt on" data-v="portrait_editorial"><b>竖屏信息版</b><small>9:16 画布 · 顶部大标题</small></div>
      <div class="opt" data-v="portrait" onclick="alert('本地版当前固定为竖屏信息版；竖屏即将支持')"><b>竖屏</b><small>即将支持</small></div>
      <div class="opt" data-v="landscape" onclick="alert('本地版当前固定为竖屏信息版；横屏即将支持')"><b>横屏</b><small>即将支持</small></div>
    </div>
    <div class="mediapreview" aria-hidden="true">
      <div><div class="ph v on"></div><div class="phcap">竖屏 1080×1920</div></div>
      <div><div class="ph emb on"><i></i></div><div class="phcap">信息版：上方标题带 + 嵌 16:9</div></div>
      <div><div class="ph h"></div><div class="phcap">横屏 1920×1080（即将支持）</div></div>
    </div>
    ${(b.notes || "").includes("横构图") ? `<div class="warn">素材包按横构图收集：建议选「竖屏信息版」，选竖屏满屏可能裁掉主体。</div>` : ""}
    <h5>版面</h5><div class="optrow"><div class="opt on"><b>卡片式</b><small>纸卡加方形内容区</small></div>
    <div class="opt"><b>更换版面</b></div></div>''',
    "config-format")

# ---------- 4. 配置页：语速微调 + 组内提示 ----------
rep('''    <h5>语速</h5>
    <div class="cfgbox">
      <div class="cfgline"><span>语速</span><b id="rateTxt">${(CFG.rate/100).toFixed(2)}×</b></div>
      <div class="seg" id="rateSeg">
        ${[80,100,110,120,125,150].map(r=>`<div class="pill ${r===CFG.rate?"on":""}" data-r="${r}">${(r/100).toFixed(2)}×</div>`).join("")}
      </div>
      <div class="d" style="margin-top:8px;color:var(--gray)">预估时长 ≈ ${Math.floor(est/60)}:${String(est%60).padStart(2,"0")} · 免费</div>
    </div>''',
'''    <h5>语速</h5>
    <div class="cfgbox">
      <div class="cfgline"><span>语速 <span style="color:var(--gray);font-size:var(--fs-12)">预估时长 ≈ <span id="estInline">${Math.floor(est/60)}:${String(est%60).padStart(2,"0")}</span></span></span>
        <b id="rateTxt">${(CFG.rate/100).toFixed(2)}×</b></div>
      <div class="seg" id="rateSeg">
        ${[80,100,110,120,125,150].map(r=>`<div class="pill ${r===CFG.rate?"on":""}" data-r="${r}">${(r/100).toFixed(2)}×</div>`).join("")}
      </div>
      <div class="finetune">
        <button class="btn ghost small" id="rateDown" aria-label="减慢 0.05 倍">－ 0.05</button>
        <button class="btn ghost small" id="rateUp" aria-label="加快 0.05 倍">＋ 0.05</button>
        <span style="color:var(--gray);font-size:var(--fs-12);align-self:center">当前：常用档位</span>
      </div>
    </div>''',
    "config-rate")

# ---------- 5. 配置页：多音字说明 ----------
rep('''    <div class="cfgline"><span>启用内置多音字词典</span>
      <span class="switch on" onclick="this.classList.toggle('on')"><i></i></span></div>''',
'''    <div class="cfgline"><div><div>启用内置多音字词典</div>
      <div class="d">词典按全局最长匹配生效，个别语境可能改错读音；素材包里逐词声明的读音始终优先。</div></div>
      <span class="switch on" onclick="this.classList.toggle('on')"><i></i></span></div>''',
    "config-lexicon")

# ---------- 6. 语速微调逻辑 + 联动 ----------
rep('''    document.querySelectorAll("#rateSeg .pill").forEach(p => p.onclick = () => {''',
'''    const setRate = (r, syncPills) => {
      r = Math.max(60, Math.min(200, r));
      CFG.rate = r;
      $("rateTxt").textContent = (r/100).toFixed(2) + "×";
      if (syncPills) document.querySelectorAll("#rateSeg .pill").forEach(x =>
        x.classList.toggle("on", +x.dataset.r === r));
      const base = window.__baseEst || 0;
      const e = Math.round(base / (r/100));
      if (e > 0) {
        const mm = Math.floor(e/60), ss = e%60;
        const e2 = $("est2"); if (e2) e2.textContent = `${mm}分${ss}秒`;
        const ei = $("estInline"); if (ei) ei.textContent = `${mm}:${String(ss).padStart(2,"0")}`;
      }
    };
    $("rateDown").onclick = () => setRate(CFG.rate - 5, true);
    $("rateUp").onclick = () => setRate(CFG.rate + 5, true);
    document.querySelectorAll("#rateSeg .pill").forEach(p => p.onclick = () => {''',
    "rate-finetune-js")

# 原 pill 点击逻辑改为走 setRate
rep('''      p.classList.add("on"); CFG.rate = +p.dataset.r;
      $("rateTxt").textContent = (CFG.rate/100).toFixed(2) + "×";
      const base = window.__baseEst || 0;
      const est = Math.round(base / (CFG.rate/100));
      if (est > 0) {
        const mm = Math.floor(est/60), ss = est%60;
        const e2 = $("est2"); if (e2) e2.textContent = `${mm}分${ss}秒`;
        const shell = document.querySelector("#rateSeg")?.parentElement?.querySelector(".d");
        if (shell) shell.textContent = `预估时长 ≈ ${mm}:${String(ss).padStart(2,"0")} · 免费`;
      }
    });''',
'''      p.classList.add("on");
      setRate(+p.dataset.r, false);
    });''',
    "rate-pill-rewire")

# ---------- 7. confirmBox 支持自定义确认文案 + 只读模式 ----------
rep('''function confirmBox(title, desc, onOk){
  const m = document.createElement("div");
  m.className = "modal";
  const box = document.createElement("div");
  box.className = "box"; box.setAttribute("role","dialog"); box.setAttribute("aria-modal","true");
  const h = document.createElement("h3"); h.textContent = title;
  const p = document.createElement("p"); p.textContent = desc;
  const row = document.createElement("div"); row.className = "row";
  const c = document.createElement("button"); c.className = "btn ghost"; c.textContent = "取消";
  const k = document.createElement("button"); k.className = "btn"; k.textContent = "确认删除";''',
'''function confirmBox(title, desc, onOk, okText, readonly){
  const m = document.createElement("div");
  m.className = "modal";
  const box = document.createElement("div");
  box.className = "box"; box.setAttribute("role","dialog"); box.setAttribute("aria-modal","true");
  const h = document.createElement("h3"); h.textContent = title;
  const p = document.createElement("p"); p.textContent = desc;
  const row = document.createElement("div"); row.className = "row";
  const c = document.createElement("button"); c.className = "btn ghost"; c.textContent = "取消";
  if (readonly) c.textContent = "关闭";
  const k = document.createElement("button"); k.className = "btn"; k.textContent = okText || "确认删除";
  if (readonly) k.classList.add("hide");''',
    "confirmbox-flex")

rep('''  c.onclick = () => m.remove();
  k.onclick = () => { m.remove(); onOk(); };
  m.onclick = (e) => { if (e.target === m) m.remove(); };
  row.append(c, k); box.append(h, p, row); m.appendChild(box);
  document.body.appendChild(m); k.focus();''',
'''  c.onclick = () => m.remove();
  k.onclick = () => { m.remove(); onOk(); };
  m.onclick = (e) => { if (e.target === m) m.remove(); };
  row.append(c, k); box.append(h, p, row); m.appendChild(box);
  document.body.appendChild(m); (readonly ? c : k).focus();''',
    "confirmbox-focus")

FE.write_text(s, encoding='utf-8')
print("applied:", ", ".join(applied))
