"""免登录试用：出样片、查试用任务状态。

从 server.py 按域拆出来的路由。
路由**注册顺序**由 server 里的 include_router 顺序决定（按各域首条路由行号
排序），改动顺序前先看 tests/test_route_order.py 的检查 —— 顺序反了会被通配路由吃掉。
"""
from __future__ import annotations

import io
import re
import time
import uuid
import zipfile
from pathlib import Path
from fastapi import Request, Response
from fastapi.responses import FileResponse, JSONResponse

from .. import ctx

from fastapi import APIRouter

router = APIRouter()

@router.get("/api/try/topics")
def try_topics_list():
    """试玩选题（公开）：落地页据此渲染"选一个选题试做"的卡片。"""
    from .. import try_topics
    out = []
    for t in try_topics.TOPICS:
        try:
            try_topics.bundle_dir(t)          # 素材包不在就不给它上架
        except ValueError:
            continue
        out.append({"id": t["id"], "title": t["title"], "subtitle": t["subtitle"],
                    "template": t["template"]})
    return {"topics": out, "templates": [{"id": k, "name": v} for k, v in ctx.TEMPLATES.items()],
            "cookie_limit": try_topics.COOKIE_LIMIT, "ip_limit": try_topics.IP_LIMIT}
@router.get("/api/sample-bundle")
def sample_bundle():
    """示例素材包（公开）：把试玩素材现打成 zip 供下载——
    用户拆开看一眼就知道"素材包"长什么样，不用再对着空拖拽区发懵。"""
    from urllib.parse import quote
    from .. import try_topics
    for t in try_topics.TOPICS:
        try:
            d = try_topics.bundle_dir(t)
        except ValueError:
            continue
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(d))   # content.json 落在 zip 根部
        name = "GetCut-示例素材包.zip"
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition":
                                 f"attachment; filename=\"bundle.zip\"; "
                                 f"filename*=UTF-8''{quote(name)}"})
    return JSONResponse({"error": "示例素材包暂时没上架"}, status_code=503)
@router.post("/api/try")
def try_render(request: Request, body: dict = None):
    """提交一次试玩渲染（公开，限流）。

    只认选题 id；模板只认 TEMPLATES 里的；出片是十几秒的低清带水印样片。
    """
    from .. import try_topics

    body = body or {}
    t = try_topics.topic(str(body.get("topic") or ""))
    if t is None:
        return JSONResponse({"error": "没有这个试玩选题"}, status_code=404)
    fmt = str(body.get("template") or t["template"])
    if fmt not in ctx.TEMPLATES:
        fmt = t["template"]
    try:
        bdir = try_topics.bundle_dir(t)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    cookie = request.cookies.get("vg_try") or ""
    ip = ctx._client_ip(request)
    ok, why, issued = try_topics.guard(ctx.WORKSPACES, ip, cookie)
    if not ok:
        return JSONResponse({"error": why, "limited": True}, status_code=429)

    job_id = uuid.uuid4().hex[:12]
    with ctx._LOCK:
        ahead = ctx._queue_ahead(job_id)
        ctx.JOBS[job_id] = {"stage": "queued", "stage8": 1, "progress": 3, "error": None,
                        "video": None, "project_id": None,
                        "try": {"topic": t["id"], "title": t["title"], "template": fmt},
                        "detail": ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "已加入队列",
                        "t0": time.time()}
        ctx._jobs_save()
        ctx._PENDING[job_id] = {"try": True, "try_bundle_dir": str(bdir), "format": fmt,
                            "watermark": True, "useLlm": True, "sfx": True, "sfxMode": "all"}
        ctx._PREP_WAIT.append(job_id)
        ctx._PREP_CV.notify()
    # 记账已在 guard 里做完（判定与写账本同一把锁，别拆成两步）
    resp = JSONResponse({"job": job_id, "topic": t["id"], "template": fmt})
    resp.set_cookie("vg_try", issued, max_age=180 * 24 * 3600, httponly=True, samesite="lax")
    return resp
@router.get("/api/try/{job_id}")
def try_status(job_id: str):
    """试玩进度（公开）：只回进度和样片链接，不回任何内部路径。"""
    j = ctx.JOBS.get(job_id)
    if not j or not j.get("try"):
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    stage = j.get("stage")
    meta = j.get("try") or {}
    return {"stage": stage, "stage8": j.get("stage8"), "progress": j.get("progress"),
            "topic": meta.get("topic"), "template": meta.get("template"),
            "title": meta.get("title"),
            "queued_pos": ctx._queue_ahead(job_id) if stage in ("queued", "prepped") else 0,
            "video": f"/try/{job_id}.mp4" if j.get("try_video") else None,
            "error": j.get("error")}
@router.get("/try/{name}")
def try_video(name: str):
    """试玩样片（公开）：文件名就是任务 id，路径不从用户输入里取。"""
    jid = name[:-4] if name.endswith(".mp4") else name
    if not re.fullmatch(r"[0-9a-f]{6,24}", jid):
        return JSONResponse({"error": "not found"}, status_code=404)
    v = (ctx.JOBS.get(jid) or {}).get("try_video")
    if not v or not Path(v).is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(v, media_type="video/mp4", filename=f"GetCut-试玩-{jid}.mp4")
