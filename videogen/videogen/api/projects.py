"""项目与剪映草稿的读写、发布。

从 server.py 按域拆出来的路由。
路由**注册顺序**由 server 里的 include_router 顺序决定（按各域首条路由行号
排序），改动顺序前先看 tests/test_route_order.py 的检查 —— 顺序反了会被通配路由吃掉。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from .. import auth, config, cos_store, preview

from .. import ctx

from fastapi import APIRouter

router = APIRouter()

def _bundle_meta(bundle: str | None) -> dict:
    """封面（首张图片）+ 素材计数，供项目卡展示用。"""
    if not bundle:
        return {}
    d = ctx.WORKSPACES / bundle
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
@router.get("/api/projects")
def list_projects(request: Request):
    with ctx._LOCK:
        reg = ctx._reg()
        # 自动登记：工作区里出现的新素材包自动成为项目（归属管理员；无管理员则暂挂空）
        known = {p.get("bundle") for p in reg["projects"]}
        added = False
        for b in ctx._find_bundles():
            if b["name"] not in known:
                reg["projects"].append({"project_id": uuid.uuid4().hex[:12], "title": b["name"],
                                        "bundle": b["name"], "created": b["updated"], "renders": [],
                                        "owner": auth.admin_email()})
                added = True
        if added or not reg.get("seeded"):
            reg["seeded"] = True
            ctx._reg_save(reg)
        out = []
        for p in reg["projects"]:
            if not ctx._project_visible(p, request):
                continue
            p = dict(p)
            p["renders_count"] = len(p.get("renders", []))
            p.update(_bundle_meta(p.get("bundle")))
            out.append(p)
        return out
@router.post("/api/projects/create")
def create_project(request: Request, body: dict = None):
    with ctx._LOCK:
        reg = ctx._reg()
        pid = uuid.uuid4().hex[:12]
        reg["projects"].append({"project_id": pid, "title": body.get("title", "新建项目") if body else "新建项目",
                                "bundle": body.get("bundle") if body else None,
                                "created": time.strftime("%Y/%m/%d"), "renders": [],
                                "owner": ctx._session_email(request)})
        ctx._reg_save(reg)
        return {"project_id": pid}
def _preview_auth_ok(pid: str, request: Request) -> bool:
    with ctx._LOCK:
        target = next((p for p in ctx._reg()["projects"]
                       if p["project_id"] == pid), None)
    if not target or not ctx._project_visible(target, request):
        return False
    return True
def _preview_render_body(body: dict, request: Request = None) -> dict:
    """预演入参校验：素材包目录 + 渲染配置。免费档强制带水印（跟成片一个待遇）。"""
    bundle = body.get("bundle")
    if not bundle:
        raise ValueError("缺少素材包")
    bundle_dir = ctx._resolve_bundle(bundle)
    # 预演会读包里的口播文案出分镜，所以"包存在"不够，还得是调用者自己的包
    if request is not None and not ctx._bundle_visible(str(bundle), request):
        raise ValueError("素材包不存在")
    ctx._resolve_bgm(body.get("bgm"))
    fmt = body.get("format") or ctx.DEFAULT_TEMPLATE
    if fmt not in ctx.SUPPORTED_FORMATS:
        raise ValueError(f"模板 '{fmt}' 不存在")
    watermark = body.get("watermark", True) is not False
    if request is not None and not ctx._open_mode():
        email = ctx._session_email(request)
        if email and auth.user_tier(email) == "free":
            watermark = True
    return {"bundle_dir": bundle_dir, "bundle": bundle,
            "voice": body.get("voice") or None,
            "rate": ctx._normalize_rate(body.get("rate")),
            "format": fmt,
            "subtitles": bool(body.get("subtitles", True)),
            "sources": bool(body.get("sources", True)),
            "watermark": watermark,
            "theme": body.get("theme") or "auto",
            "disclaimer": body.get("disclaimer"),
            "brand": (ctx._brand_for(ctx._session_email(request)) if request is not None else None)}
@router.post("/api/projects/{pid}/preview/plan")
def preview_plan(pid: str, body: dict, request: Request):
    """启动预演（TTS+分镜+props，不渲染成片）。返回当前状态。"""
    if not _preview_auth_ok(pid, request):
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    try:
        rb = _preview_render_body(body, request)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    st = preview.preview_state(pid)
    if st["state"] == "running":
        return st
    # 配置与已存预演不一致时重跑
    saved = preview.load_plan(pid)
    if saved and st["state"] == "ready":
        same = all(saved.get(k) == rb.get(k) for k in ("voice", "rate", "format", "subtitles", "sources", "watermark", "brand"))
        if same:
            return {"state": "ready", "progress": 100, "error": None}
        preview.invalidate(pid)
    threading.Thread(target=preview.run_preview, args=(pid, rb), daemon=True).start()
    return {"state": "running", "progress": 0, "error": None}
@router.get("/api/projects/{pid}/preview/status")
def preview_status(pid: str, request: Request):
    if not _preview_auth_ok(pid, request):
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    return preview.preview_state(pid)
@router.post("/api/projects/{pid}/preview/shots")
def preview_shots(pid: str, body: dict, request: Request):
    """分镜页数据：逐镜头静帧按需出图（每张 1-3 秒）。"""
    if not _preview_auth_ok(pid, request):
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    st = preview.preview_state(pid)
    if st["state"] != "ready":
        return JSONResponse({"error": "预演未就绪", "state": st["state"]}, status_code=409)
    bundle = body.get("bundle") or ""
    d = (ctx.WORKSPACES / bundle).resolve()
    if not bundle or ctx.WORKSPACES.resolve() not in d.parents:
        return JSONResponse({"error": "素材包不合法"}, status_code=400)
    if not ctx._bundle_visible(bundle, request):
        return JSONResponse({"error": "素材包不合法"}, status_code=400)
    return preview.build_preview_payload(pid, {"bundle": bundle})
@router.post("/api/projects/{pid}/preview/invalidate")
def preview_invalidate(pid: str, body: dict, request: Request):
    """配置/素材变更后丢弃预演数据。"""
    if not _preview_auth_ok(pid, request):
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    preview.invalidate(pid)
    return {"ok": True}
def _render_or_404(pid: str, rid: str, request: Request):
    """按项目归属取出成片路径；取不到返回 (None, 响应)。"""
    from pathlib import Path as _P
    with ctx._LOCK:
        reg = ctx._reg()
        target = next((p for p in reg["projects"] if p["project_id"] == pid), None)
        if not target or not ctx._project_visible(target, request):
            return None, JSONResponse({"error": "项目不存在"}, status_code=404)
        render = next((r for r in target.get("renders", []) if r.get("id") == rid), None)
        if not render:
            return None, JSONResponse({"error": "成片不存在"}, status_code=404)
        video = _P(render["file"])
        if not video.is_file() and not render.get("cos_key"):
            return None, JSONResponse({"error": "成片文件缺失"}, status_code=404)
    return video, None
@router.get("/api/projects/{pid}/renders/{rid}/jianying-status")
def jianying_status(pid: str, rid: str, request: Request):
    """草稿备好了没：渲染完成后系统就在后台备，前端据此显示"秒装"还是"准备中"。"""
    from .. import draft_build
    from .. import jianying_draft as jyd

    video, err = _render_or_404(pid, rid, request)
    if err:
        return err
    plan_dir = jyd.draft_dir_for(video)
    ready = bool(draft_build.plan_fresh(plan_dir, video))
    return {"ready": ready, "building": (not ready) and str(video) in ctx.DRAFT_PREP,
            "jianying": jyd.jianying_draft_dir().is_dir()}
def _require_premium(request: Request):
    """高级版付费墙。返回 None 表示放行，否则返回 402 响应。"""
    if ctx._open_mode():          # 本机自用开放模式不设墙
        return None
    if auth.tier_at_least(ctx._session_email(request), "premium"):
        return None
    return JSONResponse(
        {"error": f"导出剪映草稿是高级版功能（¥{config.PRICES['premium']} 永久买断）。"
                  "点右上角「升级」查看。",
         "tier_required": "premium"},
        status_code=402)
@router.post("/api/projects/{pid}/renders/{rid}/jianying-import")
def jianying_import(pid: str, rid: str, request: Request):
    """一键导入剪映。

    这台机器上装了剪映（能找到草稿库）→ 直接把草稿装进去，用户打开剪映就能看到；
    没装/不是本机（比如线上服务器）→ 签发一次性 token 让本地小助手来取：
    浏览器唤起 getcut:// 协议，助手凭 token 从 /api/jianying/pull 拉草稿包装进剪映，
    全程用户不用下载、解压、跑脚本。
    """
    import tempfile
    from .. import jianying_draft as jyd

    if (wall := _require_premium(request)) is not None:
        return wall
    video, err = _render_or_404(pid, rid, request)
    if err:
        return err
    mf = jyd.load_manifest(video)
    if mf is None:
        return JSONResponse({"error": "这条成片没有草稿清单（旧成片不支持分轨草稿）"}, status_code=400)

    jyd.prepare_draft(video, mf)                 # 通常已由后台备好，这里是兜底

    root = jyd.jianying_draft_dir()
    if not root.is_dir():
        # 服务器这一侧没有剪映（线上部署就是这样）：签一次性 token 给本地小助手
        # （prepare_draft 失败也不退回下载：build_zip 自带"整条切片"兜底，照样一键进剪映）
        token = uuid.uuid4().hex
        with ctx._LOCK:
            now = time.time()
            for k in [k for k, v in _JY_PULL_TOKENS.items() if v["exp"] < now]:
                _JY_PULL_TOKENS.pop(k, None)
            _JY_PULL_TOKENS[token] = {
                "video": str(video), "rid": rid,
                "title": (mf.get("title") or "成片"),
                "email": ctx._session_email(request), "exp": now + 300}
        return {"installed": False, "protocol": True,
                "pull": f"/api/jianying/pull?t={token}"}

    voice = mf.get("voice")
    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "draft.zip"
        jyd.build_zip(mf, video, Path(voice) if voice else None, zip_path)
        dest = jyd.install_draft(zip_path)
    return {"installed": True, "name": dest.name}
# 一次性草稿提取 token（线上"导入到剪映"专用）：小助手没有浏览器会话，
# 靠它自证身份。5 分钟过期，签发前已过高级版付费墙。TTL 内允许重复取：
# 助手端第一次传输成功但自检失败重拉时（2026-09-19 深夜实测踩过），焚得太急
# 会把合法重试顶成 403；窗口短、内容固定，重放风险可忽略。
_JY_PULL_TOKENS: dict[str, dict] = {}
@router.get("/api/jianying/pull")
def jianying_pull(t: str = ""):
    """本地小助手凭一次性 token 拉剪映草稿包（无会话，token 即凭证）。"""
    info = _JY_PULL_TOKENS.get(t)
    if not info or info["exp"] < time.time():
        _JY_PULL_TOKENS.pop(t, None)
        return JSONResponse(
            {"error": "导入链接已过期或已使用，请回到页面重新点「一键导入到剪映」"},
            status_code=403)
    from .. import jianying_draft as jyd
    from pathlib import Path as _P

    video, staged = _film_or_fetch(_P(info["video"]))
    if video is None:
        _JY_PULL_TOKENS.pop(t, None)
        return JSONResponse({"error": "成片文件缺失"}, status_code=404)
    try:
        mf = jyd.load_manifest(video)
        if mf is None:
            return JSONResponse({"error": "草稿清单缺失，请回页面重新点「一键导入到剪映」"},
                                status_code=400)
        mf["render_id"] = info["rid"]
        mf.setdefault("title", info["title"])
        voice = mf.get("voice")
        try:
            zpath = video.with_suffix(".jianying.zip")
            jyd.build_zip_cached(mf, video, _P(voice) if voice else None, zpath)
        except Exception as exc:  # noqa: BLE001 - 打包失败保留 token，助手重试还能用
            return JSONResponse({"error": f"草稿打包失败: {exc}"}, status_code=500)
        fname = f"GetCut-剪映草稿-{info['rid'][:6]}.zip"
        return FileResponse(zpath, media_type="application/zip", filename=fname)
    finally:
        _drop_staged(video, staged)
@router.get("/api/projects/{pid}/renders/{rid}/jianying-draft")
def jianying_draft_zip(pid: str, rid: str, request: Request):
    """把指定成片打包成剪映专业版草稿 zip（分镜切段 + 可编辑字幕[关字幕渲染时]）。"""
    from pathlib import Path as _P
    from .. import jianying_draft as jyd

    if (wall := _require_premium(request)) is not None:
        return wall
    with ctx._LOCK:
        reg = ctx._reg()
        target = next((p for p in reg["projects"] if p["project_id"] == pid), None)
        if not target or not ctx._project_visible(target, request):
            return JSONResponse({"error": "项目不存在"}, status_code=404)
        render = next((r for r in target.get("renders", []) if r.get("id") == rid), None)
        if not render:
            return JSONResponse({"error": "成片不存在"}, status_code=404)
        video = _P(render["file"])
    video, staged = _film_or_fetch(video)
    if video is None:
        return JSONResponse({"error": "成片文件缺失"}, status_code=404)
    try:
        mf = jyd.load_manifest(video)
        if mf is None:
            # 旧成片没有清单：整条作为单镜头，时长用 ffprobe 探测
            dur_ms = 0.0
            try:
                import subprocess
                outp = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
                    capture_output=True, text=True, timeout=30)
                dur_ms = float(outp.stdout.strip()) * 1000.0
            except Exception:
                dur_ms = 0.0
            if dur_ms <= 0:
                return JSONResponse({"error": "无法读取成片时长"}, status_code=500)
            mf = {"version": 1, "video": str(video), "duration_ms": dur_ms,
                  "fps": 30, "width": 1080, "height": 1920,
                  "title": target.get("title") or "成片", "subtitles": True,
                  "shots": [], "clauses": [], "voice": None, "render_id": rid}
        mf["render_id"] = rid
        mf.setdefault("title", target.get("title") or "成片")

        voice = mf.get("voice")
        title = (mf.get("title") or "成片").replace(" ", "_")[:24]
        fname = f"GetCut-剪映草稿-{title}-{rid[:6]}.zip"
        try:
            zpath = video.with_suffix(".jianying.zip")
            jyd.build_zip_cached(mf, video, _P(voice) if voice else None, zpath)
        except Exception as exc:
            return JSONResponse({"error": f"草稿打包失败: {exc}"}, status_code=500)
        return FileResponse(zpath, media_type="application/zip", filename=fname)
    finally:
        _drop_staged(video, staged)
@router.post("/api/projects/{pid}/delete")
def delete_project(pid: str, request: Request):
    with ctx._LOCK:
        reg = ctx._reg()
        target = next((p for p in reg["projects"] if p["project_id"] == pid), None)
        if not target or not ctx._project_visible(target, request):
            return JSONResponse({"error": "项目不存在"}, status_code=404)
        reg["projects"] = [p for p in reg["projects"] if p["project_id"] != pid]
        ctx._reg_save(reg)
        return {"ok": True}
@router.post("/api/projects/{pid}/mount")
def mount_bundle(pid: str, body: dict, request: Request):
    with ctx._LOCK:
        reg = ctx._reg()
        target = next((p for p in reg["projects"] if p["project_id"] == pid), None)
        if not target or not ctx._project_visible(target, request):
            return JSONResponse({"error": "项目不存在"}, status_code=404)
        new_bundle = body.get("bundle")
        # 只在"换包"时校验归属：改名也走这个接口，且素材包可能已被清理，不能误伤
        if new_bundle and new_bundle != target.get("bundle") and not ctx._bundle_visible(new_bundle, request):
            return JSONResponse({"error": "素材包不存在"}, status_code=404)
        for p in reg["projects"]:
            if p["project_id"] == pid:
                p["bundle"] = new_bundle
                p["title"] = body.get("title") or p["title"]
        ctx._reg_save(reg)
        return {"ok": True}
def _film_or_fetch(video: Path) -> tuple[Path | None, bool]:
    """本地在就用本地；本地没了但外存有，拉回一份临时件（剪映草稿、封面要真文件）。

    返回 (可用路径, 是不是外存取回的临时件)。临时件用完必须 `_drop_staged` 删掉：
    这些副本留着，40G 系统盘又会慢慢被填满，等于白做归档。
    """
    if video.is_file():
        return video, False
    if not cos_store.enabled():
        return None, False
    with ctx._LOCK:
        reg = ctx._reg()
        key = next((r.get("cos_key") for pr in reg["projects"] for r in (pr.get("renders") or [])
                    if r.get("file") == str(video)), None)
    if not key:
        return None, False
    tmp = ctx.OUTPUTS / video.name
    return (tmp, True) if cos_store.fetch(key, tmp) else (None, False)
def _drop_staged(video: Path | None, staged: bool) -> None:
    """删掉刚从对象存储取回的过路副本（本地原本就有的那份不动）。"""
    if staged and video is not None:
        try:
            video.unlink()
        except OSError:
            pass
