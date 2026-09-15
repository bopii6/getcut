#!/usr/bin/env python3
"""剩余 UI 优化补丁（C1-dnd 至 D2）。每处断言锚点，失败即停。"""
from pathlib import Path

FE = Path(r'E:/短视频生成/videogen/server_static/index.html')
s = FE.read_text(encoding='utf-8')
applied = []


def rep(old, new, tag, count=1):
    global s
    assert old in s, f"ANCHOR MISS: {tag}"
    s = s.replace(old, new, count)
    applied.append(tag)


# ---- C3: toast / confirmBox / voiceLabel 工具函数 ----
rep('const STAGE8 = ["素材准备","分镜规划","TTS 配音","画面设计","画面校验","预览帧","最终合成","上传成片"];',
    '''const STAGE8 = ["素材准备","分镜规划","TTS 配音","画面设计","画面校验","预览帧","最终合成","上传成片"];

function voiceLabel(){
  const m = {"zh-CN-YunxiNeural":"云希 · 清爽男声","zh-CN-YunjianNeural":"云健 · 浑厚男声",
             "zh-CN-YunyangNeural":"云扬 · 新闻男声","zh-CN-XiaoxiaoNeural":"晓晓 · 女声"};
  return m[CFG.voice] || CFG.voice;
}

function toast(msg){
  let t = document.getElementById("__toast");
  if (!t) { t = document.createElement("div"); t.id = "__toast"; t.className = "toast";
            t.setAttribute("role","status"); document.body.appendChild(t); }
  t.textContent = msg; t.classList.add("on");
  clearTimeout(t.__h); t.__h = setTimeout(() => t.classList.remove("on"), 2600);
}

function confirmBox(title, desc, onOk){
  const m = document.createElement("div");
  m.className = "modal";
  const box = document.createElement("div");
  box.className = "box"; box.setAttribute("role","dialog"); box.setAttribute("aria-modal","true");
  const h = document.createElement("h3"); h.textContent = title;
  const p = document.createElement("p"); p.textContent = desc;
  const row = document.createElement("div"); row.className = "row";
  const c = document.createElement("button"); c.className = "btn ghost"; c.textContent = "取消";
  const k = document.createElement("button"); k.className = "btn"; k.textContent = "确认删除";
  c.onclick = () => m.remove();
  k.onclick = () => { m.remove(); onOk(); };
  m.onclick = (e) => { if (e.target === m) m.remove(); };
  row.append(c, k); box.append(h, p, row); m.appendChild(box);
  document.body.appendChild(m); k.focus();
}''',
    "C3-tools")

# ---- C1: 拖拽上传真实实现 ----
rep('''  if (step === 1){
    $("zipIn").onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return;
      const fd = new FormData(); fd.append("file", f);
      const r = await api("/api/upload", {method:"POST", body: fd});
      if (r.error) { alert(r.error); return; }
      CUR.bundle = r.name; CUR.title = r.name;
      await api(`/api/projects/${CUR.project_id}/mount`, {method:"POST",
        headers:{"Content-Type":"application/json"}, body: JSON.stringify({bundle:r.name, title:r.name})});
      renderStudio(2);
    };''',
'''  if (step === 1){
    const doUpload = async (f) => {
      if (!f) return;
      const fd = new FormData(); fd.append("file", f);
      const r = await api("/api/upload", {method:"POST", body: fd});
      if (r.error) { alert(r.error); return; }
      CUR.bundle = r.name; CUR.title = r.name;
      await api(`/api/projects/${CUR.project_id}/mount`, {method:"POST",
        headers:{"Content-Type":"application/json"}, body: JSON.stringify({bundle:r.name, title:r.name})});
      toast("素材包已导入：" + r.name);
      renderStudio(2);
    };
    $("zipIn").onchange = (e) => doUpload(e.target.files[0]);
    const dz = $("drop");
    dz.onclick = (e) => { if (e.target.tagName !== "BUTTON") $("zipIn").click(); };
    dz.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("zipIn").click(); } };
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("dragover"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault(); dz.classList.remove("dragover");
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) doUpload(f);
    });''',
    "C1-dnd")

# ---- C2: 删除二次确认 ----
rep('''    d.querySelector(".del").onclick = async (e) => {
      e.stopPropagation();
      await api(`/api/projects/${p.project_id}/delete`, {method:"POST"});
      renderHome();
    };''',
'''    d.querySelector(".del").onclick = (e) => {
      e.stopPropagation();
      confirmBox(`删除项目「${p.title}」？`, "项目及其渲染记录将一并删除，此操作不可撤销。",
        async () => {
          await api(`/api/projects/${p.project_id}/delete`, {method:"POST"});
          toast("已删除项目");
          renderHome();
        });
    };''',
    "C2-delete-confirm")

# ---- C4: 失败态可重试 ----
rep('''  if (j.stage === "failed"){
    clearInterval(timer);
    $("pstage").textContent = "渲染失败";
    $("perr").classList.remove("hide"); $("perr").textContent = j.error || "";
    return;
  }''',
'''  if (j.stage === "failed"){
    clearInterval(timer);
    $("pstage").textContent = "渲染失败";
    const box = $("perr");
    box.classList.remove("hide");
    box.innerHTML = `<div>渲染没有完成。常见原因：素材包路径失效、配音接口网络异常、模型额度不足。</div>` +
      `<div style="margin-top:8px;color:#b8b3ac;font-family:Consolas,monospace;font-size:12px">` +
      `${(j.error || "未知错误").slice(0, 300)}</div>` +
      `<button class="btn ghost small" style="margin-top:12px" onclick="startRender()">重试渲染</button>`;
    return;
  }''',
    "C4-retry")

# ---- C5: 进度条可访问性 ----
rep('<div class="bar"><i id="pbar" style="width:${hasOld ? 100 : 0}%"></i></div>',
    '<div class="bar" role="progressbar" aria-label="渲染进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${hasOld ? 100 : 0}" id="pbarBox"><i id="pbar" style="width:${hasOld ? 100 : 0}%"></i></div>',
    "C5-progressbar")

rep('  $("pbar").style.width = pct + "%";',
    '  $("pbar").style.width = pct + "%";\n  const pb = $("pbarBox"); if (pb) pb.setAttribute("aria-valuenow", pct);',
    "C5-aria-update")

# ---- C6: 任务ID复制 + 这一次的创作摘要 ----
rep('''    <div style="margin:14px 0"><span style="color:var(--gray)">任务 ID</span>
      <code class="id" id="taskId">${lastJob || CUR.project_id}</code></div>''',
'''    <div style="margin:14px 0;display:flex;align-items:center;gap:10px">
      <span style="color:var(--gray)">任务 ID</span>
      <code class="id" id="taskId">${lastJob || CUR.project_id}</code>
      <button class="btn ghost small" onclick="copyTaskId()">复制</button>
    </div>
    <h4>这一次的创作</h4>
    <div class="kv" style="max-width:440px">
      <span class="k">画面</span><span>竖屏信息版 · 自动基调</span>
      <span class="k">声音</span><span>${voiceLabel()} · ${(CFG.rate/100).toFixed(2)}×</span>
      <span class="k">音乐</span><span>${CFG.bgm ? "已启用" : "未启用"} · 音效 ${CFG.sfxMode === "off" ? "关闭" : "开场档"}</span>
      <span class="k">导演</span><span>DeepSeek 分镜导演</span>
    </div>''',
    "C6-render-meta")

rep('function addRender(job){',
'''function copyTaskId(){
  const t = (document.getElementById("taskId") || {}).textContent || "";
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(t).then(() => toast("任务 ID 已复制"), () => toast("复制失败，请手动选择"));
  } else { toast("当前环境不支持自动复制"); }
}

function addRender(job){''',
    "C6-copy-fn")

# ---- C7: 空态文案 ----
rep('''  if (!projs.length) g.innerHTML = "<p class='sub'>还没有项目，点上面「新建项目」开始。</p>";''',
'''  if (!projs.length) g.innerHTML = "<p class='sub'>还没有项目。点上面的「新建项目」，再上传一个素材包 zip 即可开始。</p>";''',
    "C7-empty")

# ---- D1: 素材墙视频懒加载 + alt ----
rep('''      <div class="aitem">${a.kind==="video"
        ? `<video src="/media/${b.name}/${a.file}" muted preload="metadata"></video>`
        : `<img loading="lazy" src="/media/${b.name}/${a.file}">`}''',
'''      <div class="aitem">${a.kind==="video"
        ? `<video src="/media/${b.name}/${a.file}" muted preload="none" data-lazy-video></video>`
        : `<img loading="lazy" alt="${(a.summary||a.file).replace(/"/g,"")}" src="/media/${b.name}/${a.file}">`}''',
    "D1-lazy-video")

# ---- D2: IntersectionObserver 懒加载 ----
rep('''  $("main").innerHTML = head + `<div id="stepBody">${body}</div>`;
  wireStep(step, b);''',
'''  $("main").innerHTML = head + `<div id="stepBody">${body}</div>`;
  wireStep(step, b);
  const lazies = document.querySelectorAll("[data-lazy-video]");
  if (lazies.length && "IntersectionObserver" in window){
    const io = new IntersectionObserver((entries) => {
      entries.forEach(en => {
        if (en.isIntersecting){ en.target.preload = "metadata"; io.unobserve(en.target); }
      });
    }, { rootMargin: "200px" });
    lazies.forEach(v => io.observe(v));
  }''',
    "D2-observer")

FE.write_text(s, encoding='utf-8')
print("applied:", ", ".join(applied))
