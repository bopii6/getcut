"""videogen 本地可视化工作台后端。

    python -m videogen.server     # http://localhost:8600

聚焦视频生成：素材包选择/上传 -> 内容确认 -> 渲染配置 -> 生成与成片。
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
import zipfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import config
from .schemas import Content, Manifest

ROOT = config.ROOT
WORKSPACES = config.WORKSPACES
UPLOADS = config.UPLOADS
STATIC = config.STATIC
OUTPUTS = config.OUTPUTS

MAX_UPLOAD_BYTES = 512 * 1024 * 1024          # 单个 zip 上限 512MB
MAX_EXTRACT_BYTES = 2 * 1024 * 1024 * 1024    # 解压后总上限 2GB（防 zip 炸弹）
SUPPORTED_FORMATS = {"portrait_editorial", "portrait"}

app = FastAPI(title="videogen studio")
JOBS: dict[str, dict] = {}
JOBS_FILE = ROOT / "jobs.json"
REG = ROOT / "registry.json"
# 全局锁：JOBS / registry / 渲染工作目录都是共享可变状态，串行化写操作
_LOCK = threading.RLock()
# 渲染串行化：Remotion 共用 renderer/props.json 与 visual_out.mp4，不能并发
_RENDER_LOCK = threading.Lock()


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


_jobs_load()


def _reg() -> dict:
    if REG.is_file():
        return json.loads(REG.read_text(encoding="utf-8"))
    return {"projects": []}


def _reg_save(reg: dict) -> None:
    REG.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")


# 渲染阶段映射到 niwo 的 8 阶段
STAGE8 = ["素材准备", "分镜规划", "TTS 配音", "画面设计",
          "画面校验", "预览帧", "最终合成", "上传成片"]
_STAGE_MAP = {"queued": (0, 3), "tts": (2, 22), "plan": (1, 12), "props": (3, 35),
              "render": (6, 55), "audio": (6, 82), "mux": (7, 92), "verify": (4, 88),
              "done": (7, 100)}


def _find_bundles() -> list[dict]:
    out = []
    for d in sorted(WORKSPACES.iterdir()):
        if d.is_dir() and (d / "content.json").is_file():
            m = d / "manifest.json"
            n_assets = 0
            if m.is_file():
                try:
                    n_assets = len((__import__("json").loads(m.read_text(encoding="utf-8"))).get("assets", []))
                except Exception:
                    pass
            out.append({"name": d.name, "assets": n_assets,
                        "updated": time.strftime("%Y/%m/%d %H:%M", time.localtime(d.stat().st_mtime))})
    return out


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/bundles")
def bundles():
    return _find_bundles()


def _bundle_meta(bundle: str | None) -> dict:
    """封面（首张图片）+ 素材计数，供项目卡展示用。"""
    if not bundle:
        return {}
    d = WORKSPACES / bundle
    manifest = d / "manifest.json"
    if not manifest.is_file():
        return {}
    try:
        assets = (json.loads(manifest.read_text(encoding="utf-8"))).get("assets", [])
    except Exception:
        return {}
    cover = None
    for a in assets:
        if a.get("kind") == "image":
            cover = f"/media/{bundle}/{a['file']}"
            break
    return {"cover": cover, "assets_count": len(assets)}


@app.get("/api/projects")
def list_projects():
    with _LOCK:
        reg = _reg()
        # 自动登记：工作区里出现的新素材包自动成为项目（已有 bundle 不重复登记）
        known = {p.get("bundle") for p in reg["projects"]}
        added = False
        for b in _find_bundles():
            if b["name"] not in known:
                reg["projects"].append({"project_id": uuid.uuid4().hex[:12], "title": b["name"],
                                        "bundle": b["name"], "created": b["updated"], "renders": []})
                added = True
        if added or not reg.get("seeded"):
            reg["seeded"] = True
            _reg_save(reg)
        out = []
        for p in reg["projects"]:
            p = dict(p)
            p["renders_count"] = len(p.get("renders", []))
            p.update(_bundle_meta(p.get("bundle")))
            out.append(p)
        return out


@app.post("/api/projects/create")
def create_project(body: dict = None):
    with _LOCK:
        reg = _reg()
        pid = uuid.uuid4().hex[:12]
        reg["projects"].append({"project_id": pid, "title": body.get("title", "新建项目") if body else "新建项目",
                                "bundle": body.get("bundle") if body else None,
                                "created": time.strftime("%Y/%m/%d"), "renders": []})
        _reg_save(reg)
        return {"project_id": pid}


@app.post("/api/projects/{pid}/delete")
def delete_project(pid: str):
    with _LOCK:
        reg = _reg()
        reg["projects"] = [p for p in reg["projects"] if p["project_id"] != pid]
        _reg_save(reg)
        return {"ok": True}


@app.post("/api/projects/{pid}/mount")
def mount_bundle(pid: str, body: dict):
    with _LOCK:
        reg = _reg()
        for p in reg["projects"]:
            if p["project_id"] == pid:
                p["bundle"] = body.get("bundle")
                p["title"] = body.get("title") or p["title"]
        _reg_save(reg)
        return {"ok": True}


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """防 Zip Slip / zip 炸弹：逐条校验成员路径落在 dest 内，且总量受控。"""
    dest = dest.resolve()
    total = 0
    for member in zf.infolist():
        total += member.file_size
        if total > MAX_EXTRACT_BYTES:
            raise ValueError("解压后体积超限")
        target = (dest / member.filename).resolve()
        if target != dest and dest not in target.parents:
            raise ValueError(f"非法路径: {member.filename}")
    zf.extractall(dest)


@app.post("/api/upload")
async def upload(file: UploadFile):
    name = Path(file.filename or "bundle.zip").stem or f"bundle-{int(time.time())}"
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "zip 超过 512MB 上限"}, status_code=413)
    dest = WORKSPACES / name
    i = 1
    while dest.exists():
        dest = WORKSPACES / f"{name}-{i}"
        i += 1
    dest.mkdir(parents=True)
    tmp = dest.parent / f"upload-{uuid.uuid4().hex}.zip"
    tmp.write_bytes(data)
    try:
        with zipfile.ZipFile(tmp) as zf:
            _safe_extract(zf, dest)
    except (zipfile.BadZipFile, ValueError) as e:
        import shutil as _sh
        _sh.rmtree(dest, ignore_errors=True)
        return JSONResponse({"error": f"素材包无效：{e}"}, status_code=400)
    finally:
        tmp.unlink(missing_ok=True)
    if not (dest / "content.json").is_file():
        import shutil as _sh
        _sh.rmtree(dest, ignore_errors=True)
        return JSONResponse({"error": "zip 里没有 content.json，不是有效的素材包"}, status_code=400)
    return {"name": dest.name}


@app.get("/api/bundle/{name}")
def bundle_detail(name: str):
    d = (WORKSPACES / name).resolve()
    if not d.is_dir() or WORKSPACES.resolve() not in d.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    content = Content.load(d / "content.json")
    assets = []
    if (d / "manifest.json").is_file():
        m = Manifest.load(d / "manifest.json")
        assets = [a.__dict__ for a in m.assets]
    hook = content.hook_headline
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
        "hookLines": hook_lines,
        "sources": content.sources,
        "pronunciations": content.pronunciations,
        "notes": content.notes,
        "assets": assets,
        "mediaBase": f"/media/{name}",
    }


@app.get("/media/{name}/{path:path}")
def media(name: str, path: str):
    d = (WORKSPACES / name).resolve()
    f = (d / path).resolve()
    if not f.is_file() or WORKSPACES.resolve() not in f.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f)


@app.post("/api/build")
def start_build(body: dict):
    fmt = body.get("format") or "portrait_editorial"
    if fmt not in SUPPORTED_FORMATS:
        return JSONResponse({"error": f"成片形态 '{fmt}' 尚未实现，当前仅支持竖屏信息版"}, status_code=400)
    if not body.get("bundle"):
        return JSONResponse({"error": "缺少素材包"}, status_code=400)
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        JOBS[job_id] = {"stage": "queued", "stage8": 1, "progress": 3, "error": None, "video": None,
                        "project_id": body.get("project_id")}
        _jobs_save()
    threading.Thread(target=_worker, args=(job_id, body), daemon=True).start()

    def _tick():
        # 兜底平滑：render 阶段每 2.5s +1%（真实进度上报会让它跳得更快）
        while True:
            with _LOCK:
                j = JOBS.get(job_id)
                if j is None or j["stage"] in ("done", "failed"):
                    return
                if j["stage"] == "render" and j["progress"] < 88:
                    j["progress"] += 1
            time.sleep(2.5)
    threading.Thread(target=_tick, daemon=True).start()
    return {"job": job_id}


@app.get("/api/job/{job_id}")
def job_status(job_id: str):
    return JOBS.get(job_id, {"stage": "unknown"})


@app.get("/api/music")
def music_library():
    """BGM 库：assets/music/*.mp3 + library.json（情绪标签）。"""
    d = ROOT / "assets" / "music"
    lib = {}
    mf = d / "library.json"
    if mf.is_file():
        try:
            lib = {x["file"]: x for x in json.loads(mf.read_text(encoding="utf-8"))}
        except Exception:
            lib = {}
    out = []
    for f in sorted(d.glob("*.mp3")):
        info = lib.get(f.name, {})
        out.append({"file": f"assets/music/{f.name}", "name": f.stem,
                    "mood": info.get("mood", ""), "genre": info.get("genre", "")})
    return out


@app.get("/api/latest")
def latest():
    outs = sorted(OUTPUTS.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if OUTPUTS.is_dir() else []
    if not outs:
        return {"video": None}
    f = outs[0]
    jid = f.stem.rsplit("-", 1)[-1]
    return {"video": f.name, "job": jid, "mtime": int(f.stat().st_mtime)}


@app.get("/video/{job_id}")
def video(job_id: str):
    v = JOBS.get(job_id, {}).get("video")
    if not v:
        return JSONResponse({"error": "not ready"}, status_code=404)
    return FileResponse(v, media_type="video/mp4", filename=Path(v).name)


def _normalize_rate(rate) -> str | None:
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
    from . import cli
    try:
        def progress(stage: str, pct: int):
            idx, base = _STAGE_MAP.get(stage, (0, 0))
            span = {"tts": 14, "plan": 10, "props": 12, "render": 30}.get(stage, 8)
            val = min(base + int(pct / 100 * span), 98)
            with _LOCK:
                j = JOBS.get(job_id)
                if j is None:
                    return
                if stage != j["stage"]:
                    j.update(stage=stage, stage8=idx + 1, progress=max(val, j["progress"] + 1))
                elif val > j["progress"]:
                    j.update(stage8=idx + 1, progress=val)
                else:
                    j["stage8"] = idx + 1
                _jobs_save()

        out = OUTPUTS / f"{Path(body['bundle']).stem}-{job_id}.mp4"
        with _RENDER_LOCK:
            cli.build(WORKSPACES / body["bundle"], out,
                      voice=body.get("voice") or None,
                      rate=_normalize_rate(body.get("rate")),
                      bgm=Path(body["bgm"]) if body.get("bgm") else None,
                      renderer=body.get("renderer") or "remotion",
                      format=body.get("format") or "portrait_editorial",
                      sfx=bool(body.get("sfx", True)),
                      sfx_mode=body.get("sfxMode") or ("full" if body.get("sfx", True) else "off"),
                      show_subtitles=bool(body.get("subtitles", True)),
                      show_sources=bool(body.get("sources", True)),
                      theme=body.get("theme") or "auto",
                      disclaimer=body.get("disclaimer"),
                      use_llm=bool(body.get("useLlm", True)),
                      progress=progress)
        with _LOCK:
            JOBS[job_id].update(stage="done", stage8=8, progress=100, video=str(out))
            _jobs_save()
            reg = _reg()
            for p in reg["projects"]:
                if p["project_id"] == body.get("project_id"):
                    p.setdefault("renders", []).append({"id": job_id, "file": str(out),
                        "ts": time.strftime("%Y/%m/%d %H:%M")})
            _reg_save(reg)
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            JOBS[job_id].update(stage="failed", stage8=8, error=str(e)[-800:])
            _jobs_save()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8600)
    a = ap.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
