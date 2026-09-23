"""设备端 agent 上报与取活。

从 server.py 按域拆出来的路由。
路由**注册顺序**由 server 里的 include_router 顺序决定（按各域首条路由行号
排序），改动顺序前先看 tests/test_route_order.py 的检查 —— 顺序反了会被通配路由吃掉。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from fastapi import Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from .. import agenthub, auth, config

from .. import ctx

from fastapi import APIRouter

router = APIRouter()

@router.get("/assistant/GetCut-Setup.bat")
def jianying_assistant_installer():
    """导入助手安装器（单文件 bat，内嵌 ps1）。公开路由：脚本里没有用户数据。"""
    f = config.STATIC / "assistant" / "GetCut-Setup.bat"
    if not f.is_file():
        return JSONResponse({"error": "安装器未构建：跑 python _tools/build_assistant.py"},
                            status_code=404)
    return FileResponse(f, media_type="application/octet-stream",
                        headers={"Content-Disposition":
                                 "attachment; filename=GetCut-Setup.bat"})
def _claim_owners(identity: str) -> list:
    """这台成片台可以领谁的活：只领自己的；主钥匙领无主+管理员自己的。"""
    if identity == "__admin__":
        admin = auth.admin_email()
        return [None] + ([admin] if admin else [])
    if identity == "__open__":
        return [None]
    return [identity]
def _agent_device(request: Request, fallback: str = "device") -> str:
    name = (request.headers.get("x-agent-device")
            or request.query_params.get("device") or fallback).strip()
    return re.sub(r"[^\w.\-]", "_", name)[:48] or fallback
@router.post("/api/agent/login")
def agent_login(body: dict, request: Request):
    """成片台登录：邮箱密码换 90 天设备令牌，存本机以后免输。

    这张票等于"这台机器可以领走该客户的全部任务、看到他的素材与文案"，所以：
    ① 必须和普通登录走同一道节流（以前这里直接 verify_login —— 无限流、不延时，
    等于给撞库开了个不用排队的前门，每试一次还替对方跑一次 PBKDF2）；
    ② 必须记上是哪台设备，否则「登录设备」里它是一行空白，客户想踢掉某台都挑不出。
    """
    email = str(body.get("email") or "").strip().lower()
    ip = ctx._client_ip(request)
    allowed, left = auth.login_can_try(ip, email)
    if not allowed:
        # 只回 429，不再跑哈希：挡在门外就没必要替对方做那笔开销
        return JSONResponse({"error": auth.login_blocked_left(left)}, status_code=429)
    if not auth.verify_login(email, str(body.get("password") or "")):
        auth.login_failed(ip, email)
        time.sleep(0.6)   # 拖慢暴力尝试
        return JSONResponse({"error": "邮箱或密码不对"}, status_code=401)
    auth.login_succeeded(ip, email)
    return {"token": auth.make_session(
                email, ttl=90 * 24 * 3600,
                device=_agent_device(request, str(body.get("device") or "成片台")),
                ip=ip),
            "email": email}
@router.get("/api/agent/poll")
def agent_poll(request: Request, device: str = "", wait: int = 1):
    """长轮询领任务（服务器最多挂 25 秒）：领到就返回渲染包描述。"""
    ident = ctx._agent_identity(request)
    if ident is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    dev = _agent_device(request, device)
    # x-agent-final: 1 = 浏览器成片台：能自己混音出完整 mp4，
    # 领任务时把音轨（配音/BGM/音效+混音计划）一并下发
    want_audio = (request.headers.get("x-agent-final") or "").strip() == "1"
    payload = agenthub.wait_for_job(_claim_owners(ident), dev,
                                    timeout=25.0 if wait else 0.0,
                                    want_audio=want_audio)
    if not payload:
        return {"job": None}
    files = []
    for rel, p in payload["files"].items():
        try:
            files.append({"path": rel, "size": os.path.getsize(p)})
        except OSError:
            pass
    return {"job": payload["job"], "props": payload["props"], "files": files,
            "claim": payload.get("claim")}
@router.get("/api/agent/job/{job_id}/file")
def agent_job_file(job_id: str, request: Request, path: str = ""):
    """下载渲染包里的一个文件（只放行挂单时登记过的相对路径）。"""
    if ctx._agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    if (denied := ctx._agent_job_ok(job_id, request)) is not None:
        return denied
    p = agenthub.file_path(job_id, path)
    if p is None:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(p, filename=Path(path).name)
@router.post("/api/agent/job/{job_id}/progress")
def agent_job_progress(job_id: str, body: dict, request: Request, device: str = ""):
    """成片台上报进度；响应里带 cancel 旗子，让成片台知道该收手了。"""
    if ctx._agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    if (denied := ctx._agent_job_ok(job_id, request)) is not None:
        return denied
    # 这一单此刻的认领凭据（poll 领到时发的）：设备名只是标签，凭据才是凭证
    claim = (request.headers.get("x-agent-claim") or "").strip()[:64]
    resp = agenthub.progress(job_id, claim,
                             int(body.get("pct") or 0), body.get("detail"),
                             device=_agent_device(request, device),
                             failed=body.get("status") == "error",
                             requeue=body.get("requeue") is True,
                             voluntary=body.get("voluntary") is True)
    if resp.get("claim_bad"):
        # 403 = 再试也没用（这一单已经不在它手上了），前端该停手而不是继续刷
        return JSONResponse({"error": "这一单已经不是你在生成的了（已收回或已换页）"},
                            status_code=403)
    return resp
_MAX_VISUAL_BYTES = 300 * 1024 * 1024     # 一条 1080×1920 两分钟成片约 20~40MB，留足余量
_MAX_LAYER_BYTES = 25 * 1024 * 1024


async def _body_capped(request: Request, cap: int) -> bytes | None:
    """收请求体；超过 cap 当场丢手返回 None。

    `await request.body()` 再判大小 = 允许对方把任意多字节先塞进服务器内存再看
    顺不顺眼（图层口那句"25MB 上限"以前就是这么漏的）。边读边判才挡得住。
    """
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > cap:
            return None
    return bytes(buf)
@router.post("/api/agent/job/{job_id}/visual")
async def agent_job_visual(job_id: str, request: Request, device: str = ""):
    """成片台交回产物（默认 final=1 带声成片）：落临时名，原子转正唤醒灶台。"""
    if ctx._agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    if (denied := ctx._agent_job_ok(job_id, request)) is not None:
        return denied
    claim = (request.headers.get("x-agent-claim") or "").strip()[:64]
    tmp = agenthub.upload_target(job_id, claim)
    if tmp is None:
        return JSONResponse({"error": "任务不在生成中（可能已收回或取消）"},
                            status_code=410)
    crop = request.query_params.get("crop") or ""
    if crop:
        agenthub.set_crop(job_id, claim, crop)
    final = request.query_params.get("final") == "1"
    data = await _body_capped(request, _MAX_VISUAL_BYTES)
    if data is None:
        return JSONResponse({"error": "成片太大了，没收"}, status_code=413)
    if len(data) < 4096:
        return JSONResponse({"error": "画面轨文件异常（太小）"}, status_code=400)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(data)
    if not agenthub.deliver(job_id, claim, tmp, final=final):
        tmp.unlink(missing_ok=True)
        return JSONResponse({"error": "任务不在生成中（可能已收回或取消）"},
                            status_code=410)
    return {"ok": True}
@router.post("/api/agent/job/{job_id}/layer")
async def agent_job_layer(job_id: str, request: Request, device: str = "",
                          name: str = ""):
    """成片台交回剪映分轨图层：base.png / cards/shot_00N.png / texts.json。

    文件名过 agenthub 的白名单再拼路径（这里不接受任何客户端给的目录），
    身份认的是交片那台设备留下的凭据——图层是成片之后才陆续到的，
    任务记录那时已经摘牌。
    """
    if ctx._agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    if (denied := ctx._agent_job_ok(job_id, request)) is not None:
        return denied
    dst = agenthub.layer_target(job_id,
                                (request.headers.get("x-agent-claim") or "").strip()[:64],
                                name)
    if dst is None:
        return JSONResponse({"error": "没有等图层的那台成片台，或文件名不合法"},
                            status_code=410)
    data = await _body_capped(request, _MAX_LAYER_BYTES)
    # 上限是防有人拿这个口往服务器塞东西；下限只挡空包——
    # 「图层缺不缺」由 draft_build.import_layers 逐张把关
    if data is None or len(data) < 1:
        return JSONResponse({"error": "图层大小不对"}, status_code=400)
    dst.write_bytes(data)
    return {"ok": True, "bytes": len(data)}
@router.get("/api/agent/status")
def agent_status(request: Request):
    if ctx._agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    snap = agenthub.snapshot()
    if ctx._is_adminish(request) or ctx._open_mode():
        return snap
    # 普通用户只看自己那几个任务：全站任务号与别人电脑的设备名不外泄
    with ctx._LOCK:
        mine = {jid for jid, j in ctx.JOBS.items() if ctx._job_visible(j, request)}
    jobs = [d for d in snap.get("jobs") or [] if d.get("job") in mine]
    return {"devices": [], "jobs": jobs,
            "waiting": sum(1 for d in jobs if d.get("status") == "waiting"),
            "rendering": sum(1 for d in jobs if d.get("status") == "rendering")}
def _file_tag(target: Path) -> str:
    """文件版 ETag：改动时间 + 字节数，不读文件内容（3.7MB 的包不该为算标签整份读一遍）。"""
    st = target.stat()
    return '"%x-%x"' % (int(st.st_mtime), st.st_size)
@router.get("/poc/{rel_path:path}")
def poc_page(request: Request, rel_path: str = "index.html"):
    """浏览器成片台（web-renderer 逐帧渲染 + 浏览器内混音，产出带声 mp4）。
    同源部署，正式环境里登录用户的会话 cookie 随页面自动可用。"""
    target = (ctx.BROWSERPOC_DIR / rel_path).resolve()
    try:
        # 用真包含判断：str().startswith 会让 /poc/../隔壁目录 混进来
        inside = target.is_relative_to(ctx.BROWSERPOC_DIR.resolve())
    except (OSError, ValueError):
        inside = False
    if not inside or not target.is_file():
        html = ctx._poc_html()
        return html if isinstance(html, JSONResponse) else HTMLResponse(html)
    # 这些文件名不带内容哈希（bundle.js 永远是这个名字），所以只能"每次回源校验"：
    # 光把 Cache-Control 改成 no-cache 会让浏览器每次重下 3.7MB（FileResponse 自己
    # 不认 If-None-Match），3Mbps 的出网带宽上就是十几秒白等 —— 304 得我们自己回。
    tag = _file_tag(target)
    if any(t.strip() == tag for t in (request.headers.get("if-none-match") or "").split(",")):
        return Response(status_code=304, headers={"etag": tag})
    return FileResponse(target, headers={"etag": tag})
