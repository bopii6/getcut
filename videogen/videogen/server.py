"""videogen 本地可视化工作台后端。

    python -m videogen.server     # http://localhost:8600

聚焦视频生成：素材包选择/上传 -> 内容确认 -> 渲染配置 -> 生成与成片。
"""
from __future__ import annotations

import argparse
import hmac as _hmac
import json
import math
import os
import shutil
import queue
import threading
import time
import uuid
import zipfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import auth, config
from .schemas import Content, Manifest

ROOT = config.ROOT
WORKSPACES = config.WORKSPACES
UPLOADS = config.UPLOADS
STATIC = config.STATIC
OUTPUTS = config.OUTPUTS
AUTH_TOKEN = config.AUTH_TOKEN

TEMPLATES = config.TEMPLATES                  # 模板 id -> 展示名
TEMPLATE_ALIAS = config.TEMPLATE_ALIAS
DEFAULT_TEMPLATE = config.DEFAULT_TEMPLATE

MAX_UPLOAD_BYTES = 512 * 1024 * 1024          # 单个 zip 上限 512MB
MAX_EXTRACT_BYTES = 2 * 1024 * 1024 * 1024    # 解压后总上限 2GB（防 zip 炸弹）
SUPPORTED_FORMATS = set(TEMPLATES) | set(TEMPLATE_ALIAS)
MAX_JOBS_KEPT = 80                            # jobs.json 只留最近这么多条，防无限膨胀

app = FastAPI(title="videogen studio")
JOBS: dict[str, dict] = {}
JOBS_FILE = ROOT / "jobs.json"
REG = ROOT / "registry.json"
# 全局锁：JOBS / registry / 渲染工作目录都是共享可变状态，串行化写操作
_LOCK = threading.RLock()
# 渲染串行化：Remotion 共用 renderer/props.json 与 visual_out.mp4，不能并发
_RENDER_LOCK = threading.Lock()  # 兼容保留（不再使用）
# 渲染队列：FIFO，并发数可用 VIDEOGEN_CONCURRENCY 配置（默认 1；每路渲染约占 1-1.5G 内存）
_RENDER_QUEUE: "queue.Queue[str]" = queue.Queue()
_RENDER_CONCURRENCY = max(1, int(os.environ.get("VIDEOGEN_CONCURRENCY", "1")))
_QUEUE_HEAD: list = []   # 排队中的 job_id（FIFO 顺序）

# 正在干活（非排队/非终态）的阶段：算排队位置时要把它们算在"前面"
_RUNNING_STAGES = ("tts", "plan", "props", "render", "audio", "mux", "verify")


def _queue_ahead(job_id: str) -> int:
    """排在 job_id 前面的任务数 = 排队在我之前的 + 正在渲染的。"""
    try:
        waiting = _QUEUE_HEAD.index(job_id)
    except ValueError:
        waiting = 0
    running = sum(1 for j in JOBS.values() if j.get("stage") in _RUNNING_STAGES)
    return waiting + running
_PENDING: dict = {}      # job_id -> body（入队暂存，开跑时取出）


# ── 鉴权 ─────────────────────────────────────────────
# 三种放行方式，按优先级：
#   1. 会话 cookie（邮箱密码登录签发，见 /api/auth/*）
#   2. 访问令牌（x-auth-token 头或 ?token=，给脚本/老客户端用的主钥匙）
#   3. 开放模式：既没建过账号也没配令牌 → 本机自用不拦
# 页面外壳、字体、健康检查、登录接口本身保持公开。
SESSION_COOKIE = "vg_session"
_PUBLIC_PATHS = {"/", "/index.html", "/healthz",
                 "/api/auth/status", "/api/auth/login", "/api/auth/register",
                 "/api/auth/send-code", "/api/auth/reset-code", "/api/auth/reset"}


def _is_public(path: str) -> bool:
    return (path in _PUBLIC_PATHS or path.startswith("/fonts/")
            or path.startswith("/templates/"))


def _token_ok(request: Request) -> bool:
    if not AUTH_TOKEN:
        return False
    tok = (request.headers.get("x-auth-token")
           or request.query_params.get("token") or "")
    return _hmac.compare_digest(tok, AUTH_TOKEN)


def _session_email(request: Request) -> str | None:
    return auth.read_session(request.cookies.get(SESSION_COOKIE) or "")


# ---------- 多用户归属 ----------
# 注册开放后工作台是多用户的：普通用户只看自己的项目；
# 管理员（第一个注册的）和持访问令牌的脚本可见全部。素材包目录仍是共享的。

def _is_adminish(request: Request) -> bool:
    email = _session_email(request)
    if email and auth.is_admin(email):
        return True
    return not email and _token_ok(request)


BUNDLES_META = WORKSPACES / "bundles.json"   # 素材包归属：{"bundles": {名字: {owner, created}}}


def _bundles_meta() -> dict:
    if BUNDLES_META.is_file():
        try:
            return json.loads(BUNDLES_META.read_text(encoding="utf-8")).get("bundles", {})
        except Exception:  # noqa: BLE001 - 元数据坏了不该让素材包整体不可用
            return {}
    return {}


def _bundles_meta_save(meta: dict) -> None:
    try:
        BUNDLES_META.write_text(json.dumps({"bundles": meta}, ensure_ascii=False, indent=1),
                                encoding="utf-8")
    except OSError:
        pass


def _bundle_owner(name: str) -> str | None:
    return (_bundles_meta().get(name) or {}).get("owner") or None


def _bundle_visible(name: str, request: Request) -> bool:
    """素材包也按归属隔离：自己的、自己项目正在用的、或管理员。

    本次改动之前上传的素材包没有归属记录（无主），只对管理员可见；
    但如果它已经被某个自己可见的项目挂上（老项目），仍然放行，避免历史项目打不开。
    """
    if _is_adminish(request):
        return True
    if not AUTH_TOKEN and not auth.has_users():
        return True          # 开放模式（本机自用）
    email = _session_email(request)
    if not email:
        return False
    owner = _bundle_owner(name)
    if owner:
        return owner == email
    return any(p.get("bundle") == name and p.get("owner") == email
               for p in _reg()["projects"])


def _project_visible(p: dict, request: Request) -> bool:
    if _is_adminish(request):
        return True
    if not AUTH_TOKEN and not auth.has_users():
        return True   # 开放模式（本机自用）：不隔离，全部可见
    email = _session_email(request)
    return bool(email) and p.get("owner") == email


def _request_authed(request: Request) -> bool:
    if _token_ok(request) or _session_email(request):
        return True
    return not AUTH_TOKEN and not auth.has_users()   # 开放模式


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    if not _is_public(request.url.path) and not _request_authed(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    return await call_next(request)


def _set_session_cookie(response: Response, request: Request, email: str,
                        remember: bool) -> None:
    ttl = auth.SESSION_TTL_LONG if remember else auth.SESSION_TTL_SHORT
    response.set_cookie(
        SESSION_COOKIE, auth.make_session(email, ttl), max_age=ttl,
        httponly=True, samesite="lax",
        secure=request.headers.get("x-forwarded-proto") == "https",
        path="/")


# ---------- 登录接口 ----------

@app.get("/api/auth/status")
def auth_status():
    """登录/注册页初始化用（公开）。"""
    return {"smtp": auth.smtp_ready(), "dev_email": config.DEV_EMAIL_FALLBACK,
            "token_auth": bool(AUTH_TOKEN), "locked": auth.has_users()}


@app.post("/api/auth/send-code")
def auth_send_code(body: dict):
    """注册第一步：给邮箱发验证码。60 秒冷却，10 分钟有效。"""
    ok, msg = auth.issue_code(body.get("email", ""))
    if not ok:
        return JSONResponse({"error": msg}, status_code=400)
    return {"ok": True, "message": msg}


@app.post("/api/auth/register")
def auth_register(body: dict, request: Request, response: Response):
    """注册第二步：邮箱 + 验证码 + 密码。第一个注册的用户自动成为管理员。"""
    email = body.get("email", "")
    if not auth.check_code(email, body.get("code", "")):
        return JSONResponse({"error": "验证码不对或已过期"}, status_code=400)
    role = "admin" if not auth.has_users() else "user"
    try:
        user = auth.create_user(email, body.get("password", ""), role=role)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _set_session_cookie(response, request, user["email"],
                        bool(body.get("remember", True)))
    return user


@app.post("/api/auth/reset-code")
def auth_reset_code(body: dict):
    """忘记密码第一步：给已注册邮箱发验证码（邮箱没注册就直接说清楚）。"""
    email = body.get("email", "")
    if not auth.user_exists(email):
        return JSONResponse({"error": "这个邮箱还没注册过，先注册吧"}, status_code=400)
    ok, msg = auth.issue_code(email, purpose="重设密码")
    if not ok:
        return JSONResponse({"error": msg}, status_code=400)
    return {"ok": True, "message": msg}


@app.post("/api/auth/reset")
def auth_reset(body: dict, request: Request, response: Response):
    """忘记密码第二步：验证码 + 新密码，成功后直接登录。"""
    email = (body.get("email") or "").strip().lower()
    if not auth.check_code(email, body.get("code", "")):
        return JSONResponse({"error": "验证码不对或已过期"}, status_code=400)
    try:
        auth.set_password(email, body.get("password", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _set_session_cookie(response, request, email, bool(body.get("remember", True)))
    return {"email": email}


@app.post("/api/auth/login")
def auth_login(body: dict, request: Request, response: Response):
    email = body.get("email", "")
    if not auth.verify_login(email, body.get("password", "")):
        time.sleep(0.6)   # 拖慢暴力尝试
        return JSONResponse({"error": "邮箱或密码不对"}, status_code=401)
    email = email.strip().lower()
    _set_session_cookie(response, request, email, bool(body.get("remember", True)))
    return {"email": email}


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    email = _session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    return {"email": email}


# ---------- 试听（B5）----------

@app.get("/api/voice-preview")
def voice_preview(voice: str = "zh-CN-YunxiNeural"):
    """音色试听：合成一句短样，按音色缓存（首次约 1-2 秒）。"""
    import asyncio
    import re as _re
    import edge_tts
    safe = _re.sub(r"[^A-Za-z0-9_-]", "", voice)[:64] or "x"
    d = ROOT / "assets" / "voice_previews"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{safe}.mp3"
    if not f.exists() or f.stat().st_size == 0:
        try:
            asyncio.run(edge_tts.Communicate(
                "大家好，这是一段配音试听，听听这个声音合不合适。", voice).save(str(f)))
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": f"试听合成失败：{e}"}, status_code=502)
    return FileResponse(f, media_type="audio/mpeg")


@app.get("/api/bgm/{name}")
def bgm_file(name: str):
    """BGM 试听/播放：只允许 assets/music 下的 mp3。"""
    f = (ROOT / "assets" / "music" / name).resolve()
    music = (ROOT / "assets" / "music").resolve()
    if music not in f.parents or f.suffix.lower() != ".mp3" or not f.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f, media_type="audio/mpeg")


def _jobs_load() -> None:
    if JOBS_FILE.is_file():
        try:
            JOBS.update(json.loads(JOBS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    if len(JOBS) > MAX_JOBS_KEPT:
        keep = sorted(JOBS.items(), key=lambda kv: kv[1].get("t0", 0))[-MAX_JOBS_KEPT:]
        JOBS.clear()
        JOBS.update(dict(keep))


def _jobs_save() -> None:
    try:
        JOBS_FILE.write_text(json.dumps(JOBS, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


_jobs_load()
# 启动清理：上次进程没跑完的任务已随进程消亡，标记失败让用户重发（防僵尸任务挡新提交）
with _LOCK:
    _stale = [jid for jid, j in JOBS.items() if j.get("stage") not in ("done", "failed")]
    if _stale:
        for jid in _stale:
            JOBS[jid].update(stage="failed", stage8=8,
                             error="服务重启，任务中断，请重新渲染")
        _jobs_save()


def _reg() -> dict:
    if REG.is_file():
        return json.loads(REG.read_text(encoding="utf-8"))
    return {"projects": []}


def _reg_save(reg: dict) -> None:
    REG.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")


# 渲染阶段：与真实流水线执行顺序一致（前端 timeline 直接照此渲染）
STAGE8 = ["读取素材", "AI 配音", "分镜规划", "画面设计",
          "画面渲染", "音效混音", "画面校验", "完成"]
# idx 从 0 开始；base 是该阶段起点的总进度
_STAGE_MAP = {"queued": (0, 3), "tts": (1, 6), "plan": (2, 16), "props": (3, 30),
              "render": (4, 40), "audio": (5, 78), "mux": (5, 88), "verify": (6, 93),
              "done": (7, 100)}
# 各长阶段的进度区间（真实上报缺位时，用渐近曲线兜底爬升，既不冻住也不会跑飞）
_STAGE_SPAN = {"tts": (6, 16), "plan": (16, 30), "props": (30, 40),
               "render": (40, 78), "audio": (78, 88), "mux": (88, 93), "verify": (93, 99)}
_TICK_TAU = 130.0        # 时间常数（秒）：约 2 分钟后走完该阶段 60%，之后越来越慢


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


@app.get("/templates/{name}")
def template_thumb(name: str):
    """渲染模板的真实静帧缩略图（工作台模板选择器用）。"""
    root = (STATIC / "templates").resolve()
    f = (root / name).resolve()
    if not f.is_file() or root not in f.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f, media_type="image/png")


@app.get("/fonts/{name}")
def font(name: str):
    """前端自托管的字体子集（展示字，与成片同款）。"""
    root = (STATIC / "fonts").resolve()
    f = (root / name).resolve()
    if not f.is_file() or root not in f.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f, media_type="font/ttf")


@app.get("/api/bundles")
def bundles(request: Request):
    return [b for b in _find_bundles() if _bundle_visible(b["name"], request)]


@app.get("/api/templates")
def templates():
    """可选渲染模板（前端配置页据此渲染选择器）。"""
    return {"default": DEFAULT_TEMPLATE,
            "templates": [{"id": k, "name": v} for k, v in TEMPLATES.items()]}


@app.get("/healthz")
def healthz():
    """云平台健康检查（不落盘、不触发扫描副作用）。"""
    return {"ok": True, "jobs": len(JOBS), "version": "1.0"}


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
def list_projects(request: Request):
    with _LOCK:
        reg = _reg()
        # 自动登记：工作区里出现的新素材包自动成为项目（归属管理员；无管理员则暂挂空）
        known = {p.get("bundle") for p in reg["projects"]}
        added = False
        for b in _find_bundles():
            if b["name"] not in known:
                reg["projects"].append({"project_id": uuid.uuid4().hex[:12], "title": b["name"],
                                        "bundle": b["name"], "created": b["updated"], "renders": [],
                                        "owner": auth.admin_email()})
                added = True
        if added or not reg.get("seeded"):
            reg["seeded"] = True
            _reg_save(reg)
        out = []
        for p in reg["projects"]:
            if not _project_visible(p, request):
                continue
            p = dict(p)
            p["renders_count"] = len(p.get("renders", []))
            p.update(_bundle_meta(p.get("bundle")))
            out.append(p)
        return out


@app.post("/api/projects/create")
def create_project(request: Request, body: dict = None):
    with _LOCK:
        reg = _reg()
        pid = uuid.uuid4().hex[:12]
        reg["projects"].append({"project_id": pid, "title": body.get("title", "新建项目") if body else "新建项目",
                                "bundle": body.get("bundle") if body else None,
                                "created": time.strftime("%Y/%m/%d"), "renders": [],
                                "owner": _session_email(request)})
        _reg_save(reg)
        return {"project_id": pid}


@app.get("/api/projects/{pid}/renders/{rid}/jianying-draft")
def jianying_draft_zip(pid: str, rid: str, request: Request):
    """把指定成片打包成剪映专业版草稿 zip（分镜切段 + 可编辑字幕[关字幕渲染时]）。"""
    import tempfile
    import zipfile
    from pathlib import Path as _P
    from urllib.parse import quote
    from . import jianying_draft as jyd

    with _LOCK:
        reg = _reg()
        target = next((p for p in reg["projects"] if p["project_id"] == pid), None)
        if not target or not _project_visible(target, request):
            return JSONResponse({"error": "项目不存在"}, status_code=404)
        render = next((r for r in target.get("renders", []) if r.get("id") == rid), None)
        if not render:
            return JSONResponse({"error": "成片不存在"}, status_code=404)
        video = _P(render["file"])
        if not video.is_file():
            return JSONResponse({"error": "成片文件缺失"}, status_code=404)

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
    fname = f"videogen-剪映草稿-{title}-{rid[:6]}.zip"
    try:
        with tempfile.TemporaryDirectory() as td:
            zpath = _P(td) / "draft.zip"
            jyd.build_zip(mf, video, _P(voice) if voice else None, zpath)
            data = zpath.read_bytes()
    except Exception as exc:
        return JSONResponse({"error": f"草稿打包失败: {exc}"}, status_code=500)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition":
                 "attachment; filename=jianying-draft-{}.zip; "
                 "filename*=UTF-8''{}".format(rid[:6], quote(fname))})


@app.post("/api/projects/{pid}/delete")
def delete_project(pid: str, request: Request):
    with _LOCK:
        reg = _reg()
        target = next((p for p in reg["projects"] if p["project_id"] == pid), None)
        if not target or not _project_visible(target, request):
            return JSONResponse({"error": "项目不存在"}, status_code=404)
        reg["projects"] = [p for p in reg["projects"] if p["project_id"] != pid]
        _reg_save(reg)
        return {"ok": True}


@app.post("/api/projects/{pid}/mount")
def mount_bundle(pid: str, body: dict, request: Request):
    with _LOCK:
        reg = _reg()
        target = next((p for p in reg["projects"] if p["project_id"] == pid), None)
        if not target or not _project_visible(target, request):
            return JSONResponse({"error": "项目不存在"}, status_code=404)
        new_bundle = body.get("bundle")
        # 只在"换包"时校验归属：改名也走这个接口，且素材包可能已被清理，不能误伤
        if new_bundle and new_bundle != target.get("bundle") and not _bundle_visible(new_bundle, request):
            return JSONResponse({"error": "素材包不存在"}, status_code=404)
        for p in reg["projects"]:
            if p["project_id"] == pid:
                p["bundle"] = new_bundle
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
async def upload(file: UploadFile, request: Request):
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
    meta = _bundles_meta()
    meta[dest.name] = {"owner": _session_email(request), "created": time.strftime("%Y/%m/%d %H:%M")}
    _bundles_meta_save(meta)
    return {"name": dest.name}


@app.get("/api/bundle/{name}")
def bundle_detail(name: str, request: Request):
    d = (WORKSPACES / name).resolve()
    if not d.is_dir() or WORKSPACES.resolve() not in d.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not _bundle_visible(name, request):
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
def media(name: str, path: str, request: Request):
    d = (WORKSPACES / name).resolve()
    f = (d / path).resolve()
    if not f.is_file() or WORKSPACES.resolve() not in f.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not _bundle_visible(name, request):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f)


@app.post("/api/build")
def start_build(body: dict, request: Request):
    fmt = body.get("format") or DEFAULT_TEMPLATE
    if fmt not in SUPPORTED_FORMATS:
        return JSONResponse(
            {"error": f"模板 '{fmt}' 不存在，可选：{'、'.join(TEMPLATES)}"}, status_code=400)
    if not body.get("bundle"):
        return JSONResponse({"error": "缺少素材包"}, status_code=400)
    if body.get("project_id"):
        with _LOCK:
            target = next((p for p in _reg()["projects"]
                           if p["project_id"] == body["project_id"]), None)
            if target and not _project_visible(target, request):
                return JSONResponse({"error": "项目不存在"}, status_code=403)
    if not _bundle_visible(body["bundle"], request):
        return JSONResponse({"error": "素材包不存在"}, status_code=404)
    try:
        _resolve_bundle(body["bundle"])
        _resolve_bgm(body.get("bgm"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    pid = body.get("project_id")
    with _LOCK:
        if pid:
            for j in JOBS.values():
                if j.get("project_id") == pid and j.get("stage") not in ("done", "failed"):
                    return JSONResponse(
                        {"error": "该项目已有任务在排队/渲染，等它完成再发起新的"},
                        status_code=409)
        job_id = uuid.uuid4().hex[:12]
        ahead = _queue_ahead(job_id)
        JOBS[job_id] = {"stage": "queued", "stage8": 1, "progress": 3, "error": None, "video": None,
                        "project_id": pid, "detail": ("排队中 · 前面还有 %d 个任务" % ahead) if ahead
                        else "已加入队列", "t0": time.time()}
        _jobs_save()
        _QUEUE_HEAD.append(job_id)
        _PENDING[job_id] = body
    _RENDER_QUEUE.put(job_id)

    def _tick():
        # 兜底：真实上报缺位时按渐近曲线缓慢推进，避免进度条看起来卡死
        while True:
            time.sleep(3)
            with _LOCK:
                j = JOBS.get(job_id)
                if j is None or j["stage"] in ("done", "failed"):
                    return
                span = _STAGE_SPAN.get(j["stage"])
                if not span:
                    continue
                base, cap = span
                el = time.time() - j.get("t_stage", time.time())
                target = int(base + (cap - base) * (1 - math.exp(-el / _TICK_TAU)))
                if target > j["progress"]:
                    j["progress"] = target
                    _jobs_save()
    threading.Thread(target=_tick, daemon=True).start()
    return {"job": job_id}


@app.get("/api/jobs")
def my_jobs(request: Request):
    """当前用户视角的任务：进行中/排队的在前，最近 8 条已完结随后。"""
    with _LOCK:
        reg = _reg()
        visible = {p["project_id"]: p for p in reg["projects"]
                   if _project_visible(p, request)}
        items = []
        for jid, j in JOBS.items():
            pj = visible.get(j.get("project_id") or "")
            if pj is None:
                continue
            item = {"job_id": jid, "project_id": j.get("project_id"),
                    "title": pj.get("title") or "项目",
                    "stage": j.get("stage"), "stage8": j.get("stage8"),
                    "progress": j.get("progress"), "detail": j.get("detail"),
                    "error": j.get("error"), "t0": j.get("t0")}
            if item["stage"] == "queued":
                ahead = _queue_ahead(jid)
                item["detail"] = ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "马上开始"
                item["queued_pos"] = ahead
            items.append(item)
    active = [i for i in items if i["stage"] not in ("done", "failed")]
    finished = sorted((i for i in items if i["stage"] in ("done", "failed")),
                      key=lambda x: x.get("t0") or 0, reverse=True)[:8]
    return {"concurrency": _RENDER_CONCURRENCY, "active": active, "recent": finished}


@app.get("/api/job/{job_id}")
def job_status(job_id: str):
    j = JOBS.get(job_id)
    if j is None:
        return {"stage": "unknown"}
    out = dict(j)
    if out.get("stage") == "queued":
        with _LOCK:
            ahead = _queue_ahead(job_id)
        out["queued_pos"] = ahead
        out["detail"] = ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "马上开始"
    t0 = out.get("t0")
    out["elapsed"] = int(time.time() - t0) if t0 else None
    # 分镜剧照（渲染开始前先拍好，渲染中陆续可见）
    stills = sorted(OUTPUTS.glob(f"{job_id}-still-*.jpg")) if OUTPUTS.is_dir() else []
    out["stills"] = [f"/still/{p.name}" for p in stills]
    return out


@app.get("/still/{name}")
def still(name: str):
    f = (OUTPUTS / name).resolve()
    if not f.is_file() or OUTPUTS.resolve() not in f.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f, media_type="image/jpeg")


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


def _resolve_bundle(name: str) -> Path:
    """素材包名只允许是 WORKSPACES 的直接子目录，杜绝目录穿越。"""
    d = (WORKSPACES / name).resolve()
    if WORKSPACES.resolve() not in d.parents or not (d / "content.json").is_file():
        raise ValueError("素材包不存在或路径不合法")
    return d


def _resolve_bgm(rel: str | None) -> Path | None:
    """BGM 只允许 assets/ 目录下的 mp3，杜绝任意文件读取。"""
    if not rel:
        return None
    f = (ROOT / rel).resolve()
    assets = (ROOT / "assets").resolve()
    if assets not in f.parents or f.suffix.lower() != ".mp3" or not f.is_file():
        raise ValueError("背景音乐不存在（只能选曲库里的 mp3）")
    return f


def _cleanup_work(bundle_name: str) -> None:
    """成片完成后清掉中间产物（分镜片段/拼接/混音前文件），只留 TTS 缓存。"""
    d = config.WORK / bundle_name
    if not d.is_dir():
        return
    for p in d.iterdir():
        if p.name == "tts":
            continue
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()
        except OSError:
            pass


def _render_worker() -> None:
    """渲染队列消费者：同时最多 _RENDER_CONCURRENCY 个在跑。"""
    while True:
        job_id = _RENDER_QUEUE.get()
        try:
            with _LOCK:
                if job_id in _QUEUE_HEAD:
                    _QUEUE_HEAD.remove(job_id)
                body = _PENDING.pop(job_id, None)
            if not body:
                continue
            _worker(job_id, body)
        except Exception as exc:  # 队列消费者绝不能死
            print(f"render worker error: {exc}")
        finally:
            _RENDER_QUEUE.task_done()


def _worker(job_id: str, body: dict) -> None:
    from . import cli
    try:
        def progress(stage: str, pct: int, detail: str | None = None):
            idx, base = _STAGE_MAP.get(stage, (0, 0))
            span = {"tts": 14, "plan": 10, "props": 12, "render": 27, "audio": 10, "verify": 6}.get(stage, 8)
            val = min(base + int(pct / 100 * span), 98)
            with _LOCK:
                j = JOBS.get(job_id)
                if j is None:
                    return
                if stage != j["stage"]:
                    j.update(stage=stage, stage8=idx + 1, progress=max(val, j["progress"] + 1),
                             t_stage=time.time())
                elif val > j["progress"]:
                    j.update(stage8=idx + 1, progress=val)
                else:
                    j["stage8"] = idx + 1
                if detail:
                    j["detail"] = detail
                _jobs_save()

        # 入参先过安全校验（素材包目录 / BGM 路径），不合法直接把任务标记失败
        bundle_dir = _resolve_bundle(body["bundle"])
        bgm_file = _resolve_bgm(body.get("bgm"))
        out = OUTPUTS / f"{bundle_dir.name}-{job_id}.mp4"
        if True:
            cli.build(bundle_dir, out,
                      voice=body.get("voice") or None,
                      rate=_normalize_rate(body.get("rate")),
                      bgm=bgm_file,
                      renderer=body.get("renderer") or "remotion",
                      format=body.get("format") or DEFAULT_TEMPLATE,
                      sfx=bool(body.get("sfx", True)),
                      sfx_mode=body.get("sfxMode") or ("full" if body.get("sfx", True) else "off"),
                      show_subtitles=bool(body.get("subtitles", True)),
                      show_sources=bool(body.get("sources", True)),
                      theme=body.get("theme") or "auto",
                      disclaimer=body.get("disclaimer"),
                      use_llm=bool(body.get("useLlm", True)),
                      job_id=job_id,
                      progress=progress)
        with _LOCK:
            JOBS[job_id].update(stage="done", stage8=8, progress=100, video=str(out),
                                detail="成片已生成")
            _jobs_save()
            reg = _reg()
            for p in reg["projects"]:
                if p["project_id"] == body.get("project_id"):
                    p.setdefault("renders", []).append({"id": job_id, "file": str(out),
                        "ts": time.strftime("%Y/%m/%d %H:%M")})
            _reg_save(reg)
        _cleanup_work(bundle_dir.name)
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            JOBS[job_id].update(stage="failed", stage8=8, error=str(e)[-800:])
            _jobs_save()


for _i in range(_RENDER_CONCURRENCY):
    threading.Thread(target=_render_worker, daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    # 云部署：HOST 需为 0.0.0.0；PORT 由平台注入（如 Cloudflare Containers / Fly / Railway）
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8600")))
    a = ap.parse_args()
    print(f"videogen studio on http://{a.host}:{a.port}  workspace={WORKSPACES}", flush=True)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
