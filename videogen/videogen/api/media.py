"""成片与预览文件的分发。

从 server.py 按域拆出来的路由。
路由**注册顺序**由 server 里的 include_router 顺序决定（按各域首条路由行号
排序），改动顺序前先看 tests/test_route_order.py 的检查 —— 顺序反了会被通配路由吃掉。
"""
from __future__ import annotations

import logging
from pathlib import Path
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from .. import agenthub, cos_store

from .. import ctx

from fastapi import APIRouter

log = logging.getLogger(__name__)

router = APIRouter()

@router.get("/media/{name}/{path:path}")
def media(name: str, path: str, request: Request):
    d = (ctx.WORKSPACES / name).resolve()
    f = (d / path).resolve()
    if not f.is_file() or ctx.WORKSPACES.resolve() not in f.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not ctx._bundle_visible(name, request):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f)
@router.get("/agent-media/{job_id}/{rel_path:path}")
def agent_media(job_id: str, request: Request, rel_path: str = ""):
    """成片台直读渲染包素材：已登记文件按登记路径放行；
    fonts/ 这类模板公共资产不入渲染包，回退到 renderer/public。"""
    if ctx._agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    if (denied := ctx._agent_job_ok(job_id, request)) is not None:
        return denied
    p = agenthub.file_path(job_id, rel_path)
    if p is None and rel_path.startswith("fonts/") and ".." not in rel_path:
        cand = Path(__file__).resolve().parent.parent / "renderer" / "public" / rel_path
        if cand.is_file():
            p = cand
    if p is None:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(p)
@router.get("/video/{job_id}")
def video(job_id: str, request: Request):
    j = ctx.JOBS.get(job_id)
    if not j or j.get("try"):
        return JSONResponse({"error": "not ready"}, status_code=404)
    v = j.get("video")
    if not v or not ctx._job_visible(j, request):
        return JSONResponse({"error": "not ready"}, status_code=404)
    key = (j or {}).get("cos_key")
    if key and cos_store.enabled():
        try:
            return RedirectResponse(cos_store.sign_url(key, Path(str(v)).name))
        except Exception as exc:  # noqa: BLE001 - 外存取不到就回退本地
            log.warning("cos sign_url failed, fallback local", exc_info=exc)
    if not Path(v).is_file():
        return JSONResponse({"error": "not ready"}, status_code=404)
    return FileResponse(v, media_type="video/mp4", filename=Path(v).name)
