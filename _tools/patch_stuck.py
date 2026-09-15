#!/usr/bin/env python3
"""Fix stuck render: frontend polling + server job persistence + latest endpoint."""
from pathlib import Path

FE = Path(r'E:/短视频生成/videogen/server_static/index.html')
SV = Path(r'E:/短视频生成/videogen/videogen/server.py')

# ---------------- frontend ----------------
s = FE.read_text(encoding='utf-8')

old = '''async function startRender(){
  await api(`/api/build`, {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({project_id: CUR.project_id, bundle: CUR.bundle,
      voice: CFG.voice, rate: String(CFG.rate), bgm: CFG.bgm, sfx: CFG.sfx, useLlm: true})});
  renderStudio(4);
}'''
new = '''async function startRender(){
  try {
    const r = await api(`/api/build`, {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({project_id: CUR.project_id, bundle: CUR.bundle,
        voice: CFG.voice, rate: String(CFG.rate), bgm: CFG.bgm, sfx: CFG.sfx, useLlm: true})});
    if (!r || !r.job) throw new Error((r && r.error) || "启动渲染失败");
    job = r.job; lastJob = r.job;
    await renderStudio(4);
    if (timer) clearInterval(timer);
    timer = setInterval(() => pollJob(job), 1500);
    pollJob(job);
  } catch (e) {
    alert("启动渲染失败：" + e.message);
  }
}'''
assert old in s, "startRender anchor missing"
s = s.replace(old, new)

old2 = '''async function pollJob(job){
  const j = await api("/api/job/" + job);'''
new2 = '''async function pollJob(job){
  let j;
  try {
    j = await api("/api/job/" + job);
  } catch (e) { return; }
  if (j.stage === "unknown") {
    // 服务重启后内存任务丢失：尝试恢复最近成片
    if (lastJob !== job) return;
    const l = await api("/api/latest");
    if (l && l.video) {
      clearInterval(timer);
      $("pbar").style.width = "100%";
      $("pstage").textContent = "渲染完成";
      $("ppct").textContent = "100% · 成片已生成";
      $("pdone").classList.remove("hide");
      $("player").src = "/video/" + l.job;
      $("dl").href = "/video/" + l.job;
      return;
    }
    $("pstage").textContent = "任务已丢失（服务重启），请重新渲染";
    $("ppct").textContent = "";
    return;
  }'''
assert old2 in s, "pollJob anchor missing"
s = s.replace(old2, new2)

FE.write_text(s, encoding='utf-8')
print("frontend fixed: startRender polls, pollJob recovers")

# ---------------- server ----------------
t = SV.read_text(encoding='utf-8')

old3 = '''app = FastAPI(title="videogen studio")
JOBS: dict[str, dict] = {}
REG = ROOT / "registry.json"'''
new3 = '''app = FastAPI(title="videogen studio")
JOBS: dict[str, dict] = {}
JOBS_FILE = ROOT / "jobs.json"
REG = ROOT / "registry.json"


def _jobs_load() -> None:
    if JOBS_FILE.is_file():
        try:
            JOBS.update(json.loads(JOBS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass


def _jobs_save() -> None:
    try:
        JOBS_FILE.write_text(json.dumps(JOBS, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


_jobs_load()'''
assert old3 in t, "server JOBS anchor missing"
t = t.replace(old3, new3)

old4 = '''            JOBS[job_id].update(stage=stage, stage8=idx + 1, progress=min(base + int(pct / 100 * span), 99))'''
new4 = '''            JOBS[job_id].update(stage=stage, stage8=idx + 1, progress=min(base + int(pct / 100 * span), 99))
            _jobs_save()'''
assert old4 in t, "progress anchor missing"
t = t.replace(old4, new4)

old5 = '''        JOBS[job_id].update(stage="done", stage8=8, progress=100, video=str(out))'''
new5 = '''        JOBS[job_id].update(stage="done", stage8=8, progress=100, video=str(out))
        _jobs_save()'''
assert old5 in t, "done anchor missing"
t = t.replace(old5, new5)

old6 = '''        JOBS[job_id].update(stage="failed", error=str(e)[-800:])'''
new6 = '''        JOBS[job_id].update(stage="failed", stage8=8, error=str(e)[-800:])
        _jobs_save()'''
assert old6 in t, "failed anchor missing"
t = t.replace(old6, new6)

# latest endpoint
old7 = '''@app.get("/video/{job_id}")'''
new7 = '''@app.get("/api/latest")
def latest():
    outs = sorted(OUTPUTS.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) \\
        if OUTPUTS.is_dir() else []
    if not outs:
        return {"video": None}
    f = outs[0]
    jid = f.stem.rsplit("-", 1)[-1]
    return {"video": f.name, "job": jid, "mtime": int(f.stat().st_mtime)}


@app.get("/video/{job_id}")'''
assert old7 in t, "latest anchor missing"
t = t.replace(old7, new7)

SV.write_text(t, encoding='utf-8')
print("server fixed: job persistence + /api/latest")
