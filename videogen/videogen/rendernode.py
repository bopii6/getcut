"""渲染工人节点：只干「Remotion 出画面」这一步的独立小服务。

主站把 props.json + 该任务引用的素材文件（public/media、public/brand 下的
相对路径）打成一个 multipart 包 POST 过来（素材名已由主站按 r<jobid>__ 前缀
改写好，节点不做任何改写）；节点落盘后进自己的渲染队列，用与主站完全相同
的 render_visual 跑渲染；主站轮询进度，完了拉走 mp4。

节点是无状态的：不碰 TTS/LLM/账号/成片库，挂了就挂了，主站自动回退本地渲染。
安全模型：Bearer 令牌（必配，不配起不来）+ 部署时防火墙只放行主站 IP。

    运行：python -m videogen.rendernode（镜像里与主站同一个 videogen:latest）
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import shutil
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from . import remotion_render
from .schemas import JobCancelled

RENDERER = remotion_render.RENDERER
NODEJOBS = Path(__file__).resolve().parent.parent / "nodejobs"

app = FastAPI(title="GetCut render node")

_TOKEN = os.environ.get("RENDERNODE_TOKEN", "").strip()
_LANES = max(1, int(os.environ.get("RENDERNODE_CONCURRENCY", "2") or "2"))
_KEEP_SECONDS = max(600, int(os.environ.get("RENDERNODE_KEEP_HOURS", "2") or "2") * 3600)
# props 的帧数上限：30fps × 10 分钟，超过直接拒（防把节点当免费算力跑长片）
_MAX_FRAMES = 30 * 600

# 落盘相对路径白名单：media/<安全名>（已带任务前缀）或 brand/<16hex>.png
_SAFE_MEDIA = re.compile(r"^[0-9A-Za-z._-]{1,160}$")
_SAFE_BRAND = re.compile(r"^brand/[0-9a-f]{16}\.png$")

_JOBS: dict[str, dict] = {}
_WAIT: deque[str] = deque()
_LOCK = threading.RLock()
_CV = threading.Condition(_LOCK)   # notify 必须持有条件变量的锁，直接复用 _LOCK


def _authed(request: Request) -> JSONResponse | None:
    tok = request.headers.get("x-node-token") or ""
    if not _TOKEN or not hmac.compare_digest(tok, _TOKEN):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


def _set(job_id: str, **kw) -> None:
    with _LOCK:
        j = _JOBS.get(job_id)
        if j:
            j.update(kw)


@app.get("/healthz")
def healthz():
    with _LOCK:
        active = sum(1 for j in _JOBS.values() if j["status"] == "running")
        waiting = len(_WAIT)
    return {"ok": True, "lanes": _LANES, "active": active, "waiting": waiting,
            "keep_hours": _KEEP_SECONDS // 3600}


@app.post("/v1/render")
async def submit_render(request: Request, job: str = Form(""),
                        props: str = Form(...),
                        files: list[UploadFile] = File(default=[])):
    """收一个渲染任务：props JSON 字符串 + 素材文件（filename=public 下相对路径）。"""
    bad = _authed(request)
    if bad:
        return bad
    try:
        props_data = json.loads(props)
        frames = int(props_data.get("durationInFrames") or 0)
        if frames <= 0 or frames > _MAX_FRAMES:
            raise ValueError(f"durationInFrames 越界: {frames}")
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"props 不合法: {exc}"}, status_code=400)
    safe_id = re.sub(r"[^0-9A-Za-z_-]", "_", str(job or ""))[:48] or uuid.uuid4().hex[:12]

    media_names: list[str] = []
    try:
        for f in files or []:
            rel = (f.filename or "").replace("\\", "/").lstrip("/")
            if rel.startswith("media/") and _SAFE_MEDIA.match(rel[len("media/"):]):
                base = rel[len("media/"):]
                dst = RENDERER / "public" / "media" / base
                media_names.append(base)
            elif _SAFE_BRAND.match(rel):
                dst = RENDERER / "public" / rel
            else:
                return JSONResponse({"error": f"拒绝的文件路径 {rel}"}, status_code=400)
            dst.parent.mkdir(parents=True, exist_ok=True)
            with open(dst, "wb") as out:
                shutil.copyfileobj(f.file, out, length=1024 * 1024)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"素材落盘失败: {exc}"}, status_code=500)

    (RENDERER / f"props_r{safe_id}.json").write_text(
        json.dumps(props_data, ensure_ascii=False), encoding="utf-8")
    with _LOCK:
        _JOBS[safe_id] = {"status": "queued", "pct": 0, "detail": "素材已就位，等渲染位",
                          "error": None, "t0": time.time(), "media": media_names,
                          "cancel": threading.Event()}
        _WAIT.append(safe_id)
        _CV.notify()
    return {"ok": True, "job": safe_id, "files": len(media_names)}


@app.get("/v1/render/{job_id}")
def render_status(job_id: str, request: Request):
    bad = _authed(request)
    if bad:
        return bad
    j = _JOBS.get(re.sub(r"[^0-9A-Za-z_-]", "_", job_id)[:48])
    if not j:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    return {k: j.get(k) for k in ("status", "pct", "detail", "error")}


@app.get("/v1/render/{job_id}/video")
def render_video(job_id: str, request: Request):
    bad = _authed(request)
    if bad:
        return bad
    safe_id = re.sub(r"[^0-9A-Za-z_-]", "_", job_id)[:48]
    j = _JOBS.get(safe_id)
    out = NODEJOBS / safe_id / "visual.mp4"
    if not j or j["status"] != "done" or not out.is_file():
        return JSONResponse({"error": "video not ready"}, status_code=404)
    return FileResponse(out, media_type="video/mp4", filename="visual.mp4")


@app.delete("/v1/render/{job_id}")
def render_cancel(job_id: str, request: Request):
    """主站用户按了「停止」：杀掉渲染进程树（render_visual 的 cancel_check 接手）。"""
    bad = _authed(request)
    if bad:
        return bad
    safe_id = re.sub(r"[^0-9A-Za-z_-]", "_", job_id)[:48]
    j = _JOBS.get(safe_id)
    if not j:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    j["cancel"].set()
    with _LOCK:
        if safe_id in _WAIT:
            _WAIT.remove(safe_id)
            j["status"] = "cancelled"
    return {"ok": True}


def _node_worker() -> None:
    """渲染位消费者：同时最多 _LANES 路。"""
    while True:
        with _CV:
            while not _WAIT:
                _CV.wait()
            job_id = _WAIT.popleft()
        j = _JOBS.get(job_id)
        if not j or j["status"] == "cancelled":
            continue
        _set(job_id, status="running", detail="启动渲染引擎")
        props_path = RENDERER / f"props_r{job_id}.json"
        try:
            props = json.loads(props_path.read_text(encoding="utf-8"))
        except Exception:
            _set(job_id, status="error", error="props 文件丢失", t_end=time.time())
            continue
        try:
            remotion_render.render_visual(
                props, NODEJOBS / job_id / "visual.mp4", key=f"r{job_id}",
                progress=lambda p, d=None, _id=job_id: _set(_id, pct=int(p), detail=d),
                cancel_check=j["cancel"].is_set)
            _set(job_id, status="done", pct=100, detail="渲染完成", t_end=time.time())
        except JobCancelled:
            _set(job_id, status="cancelled", t_end=time.time())
        except Exception as exc:  # noqa: BLE001
            _set(job_id, status="error", error=str(exc)[:4000], t_end=time.time())


def _sweeper() -> None:
    """定期清理：完结超时的任务（记录/产物/该任务前缀的媒体文件）。"""
    while True:
        time.sleep(600)
        now = time.time()
        try:
            with _LOCK:
                stale = [jid for jid, j in _JOBS.items()
                         if (j["status"] in ("done", "error", "cancelled")
                             and now - (j.get("t_end") or j["t0"]) > _KEEP_SECONDS)
                            # 节点重启/主站失联留下的 running 僵尸：超 24h 一律清
                            or now - j["t0"] > 86400]
            for jid in stale:
                j = _JOBS.get(jid)
                if not j:
                    continue
                shutil.rmtree(NODEJOBS / jid, ignore_errors=True)
                for name in j.get("media") or []:
                    try:
                        (RENDERER / "public" / "media" / name).unlink(missing_ok=True)
                    except OSError:
                        pass
                for junk in (RENDERER / f"props_r{jid}.json", RENDERER / f"render_r{jid}.log"):
                    try:
                        junk.unlink(missing_ok=True)
                    except OSError:
                        pass
                with _LOCK:
                    _JOBS.pop(jid, None)
        except Exception as exc:  # noqa: BLE001
            print(f"node sweeper error: {exc}")


@app.on_event("startup")
def _boot() -> None:
    if not _TOKEN:
        raise RuntimeError("RENDERNODE_TOKEN 未设置：节点拒绝裸奔上线")
    NODEJOBS.mkdir(parents=True, exist_ok=True)
    for _i in range(_LANES):
        threading.Thread(target=_node_worker, daemon=True).start()
    threading.Thread(target=_sweeper, daemon=True).start()
    print(f"render node up: lanes={_LANES} jobs={NODEJOBS}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "9700")))
    a = ap.parse_args()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
