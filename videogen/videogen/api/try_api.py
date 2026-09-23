"""登录试用：出样片、查试用任务状态。

2026-09-23 定调：**不登录一条都玩不了**（站长的话），三件事一起改掉：
1. 提交试玩要登录，任务挂在这个账号名下 —— 于是它由**客户自己的电脑**去渲染，
   不再需要"站长那台电脑开着才出得来"（以前试玩单没有归属，普通客户领不走，
   线上表现＝公开试玩 100% 不出片，还每条白占一条渲染灶台线程最长 24 小时）。
2. 进度与样片都查归属：`/try/<id>.mp4` 以前拿到任务号就能下别人的样片。
3. 试玩吃同一份免费额度（注册后每天 2 条），不另立"试玩次数"这个新概念。

选题清单与示例素材包**保持公开** —— 好奇阶段就该让人看、让人下载。
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

from .. import config, ctx
from .transfer import _free_quota_check, _usage_bump

from fastapi import APIRouter

router = APIRouter()


def _mine(request: Request, j: dict | None) -> bool:
    """这条试玩单是不是你的（管理员与本机开放模式除外）。

    任务号会直接出现在链接里（`/try/<id>.mp4`），以前谁拿到号都能下别人的样片；
    老数据里没有归属的匿名单从此只有站长看得到 —— 宁可少给，不猜。
    """
    if ctx._is_adminish(request) or ctx._open_mode():
        return True
    email = ctx._session_email(request)
    return bool(email) and bool(j) and j.get("owner") == email

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
    """提交一次试玩渲染：**要登录**，任务挂在这个账号名下，算进每天那 2 条免费额度。

    只认选题 id；模板只认 TEMPLATES 里的；出片是十几秒的低清带水印样片。
    为什么不再匿名放行：片子得有一台电脑替它渲。挂上归属之后，它由**客户自己开着
    的那台电脑**渲（以前试玩单无主，普通客户的成片台按"只领自己的单"这条规则领不
    走，线上表现就是点了没反应，还每条占死一条渲染灶台线程最长 24 小时）。
    """
    from .. import try_topics

    body = body or {}
    email = ctx._session_email(request)
    if not email and not ctx._open_mode():
        return JSONResponse({"error": "登录后就能出片：注册后每天免费 2 条，"
                                      "片子在你自己的电脑上生成"}, status_code=401)
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

    if email:
        allowed, used = _free_quota_check(email)
        if not allowed:
            return JSONResponse({"error": f"今天 {used}/{config.FREE_DAILY_BUILDS} 条免费额度"
                                          "用完了：明天再来，或看「权益与定价」"},
                                status_code=429)

    job_id = uuid.uuid4().hex[:12]
    with ctx._LOCK:
        ahead = ctx._queue_ahead(job_id)
        ctx.JOBS[job_id] = {"stage": "queued", "stage8": 1, "progress": 3, "error": None,
                        "video": None, "project_id": None, "owner": email,
                        "try": {"topic": t["id"], "title": t["title"], "template": fmt},
                        "detail": ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "已加入队列",
                        "t0": time.time()}
        ctx._jobs_save()
        ctx._PENDING[job_id] = {"try": True, "try_bundle_dir": str(bdir), "format": fmt,
                            "watermark": True, "useLlm": True, "sfx": True, "sfxMode": "all"}
        ctx._PREP_WAIT.append(job_id)
        ctx._PREP_CV.notify()
    if email:
        _usage_bump(email)          # 额度按账号算，不再靠那枚 180 天的设备 cookie
    return JSONResponse({"job": job_id, "topic": t["id"], "template": fmt})
@router.get("/api/try/{job_id}")
def try_status(job_id: str, request: Request):
    """试玩进度：只回进度和样片链接，不回任何内部路径 —— 且只回给本人。"""
    j = ctx.JOBS.get(job_id)
    if not j or not j.get("try"):
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if not _mine(request, j):
        return JSONResponse({"error": "这条试玩片不是你的"}, status_code=403)
    stage = j.get("stage")
    meta = j.get("try") or {}
    return {"stage": stage, "stage8": j.get("stage8"), "progress": j.get("progress"),
            "topic": meta.get("topic"), "template": meta.get("template"),
            "title": meta.get("title"),
            "queued_pos": ctx._queue_ahead(job_id) if stage in ("queued", "prepped") else 0,
            "video": f"/try/{job_id}.mp4" if j.get("try_video") else None,
            "error": j.get("error")}
@router.get("/try/{name}")
def try_video(name: str, request: Request):
    """试玩样片：文件名就是任务 id，路径不从用户输入里取；**片子只给本人**。"""
    jid = name[:-4] if name.endswith(".mp4") else name
    if not re.fullmatch(r"[0-9a-f]{6,24}", jid):
        return JSONResponse({"error": "not found"}, status_code=404)
    j = ctx.JOBS.get(jid)
    v = (j or {}).get("try_video")
    if not v or not Path(v).is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    if not _mine(request, j):
        return JSONResponse({"error": "这条试玩片不是你的"}, status_code=403)
    return FileResponse(v, media_type="video/mp4", filename=f"GetCut-试玩-{jid}.mp4")
