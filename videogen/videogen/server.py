"""videogen 本地可视化工作台后端。

    python -m videogen.server     # http://localhost:8600

聚焦视频生成：素材包选择/上传 -> 内容确认 -> 渲染配置 -> 生成与成片。
"""
from __future__ import annotations

import argparse
import hmac as _hmac
import html
import json
import math
import os
import shutil
import queue
import re
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import auth, config, licenses, preview
from . import brand as brand_kit
from . import tts as tts_mod
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

app = FastAPI(title="GetCut studio")
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


# 正在后台备草稿的成片路径：前端据此显示"草稿准备中"还是"已备好"
DRAFT_PREP: set[str] = set()


def _prebuild_draft(video) -> None:
    """渲染完成后在后台把剪映草稿资产备好（失败不影响任何事，导出时还会再试）。"""
    key = str(video)
    DRAFT_PREP.add(key)
    try:
        from . import jianying_draft as jyd
        mf = jyd.load_manifest(video)
        if mf:
            jyd.prepare_draft(video, mf)
    except Exception as exc:  # noqa: BLE001
        print(f"draft prebuild skipped: {exc}")
    finally:
        DRAFT_PREP.discard(key)


def _downscale_720(src: Path, dst: Path) -> bool:
    """试玩样片降到 720×1280（低清版），失败返回 False。"""
    ff = shutil.which("ffmpeg")
    if not ff:
        return False
    try:
        p = subprocess.run([ff, "-y", "-v", "error", "-i", str(src),
                            "-vf", "scale=720:1280", "-c:v", "libx264", "-crf", "26",
                            "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "copy",
                            "-movflags", "+faststart", str(dst)],
                           capture_output=True, text=True, timeout=300)
        return p.returncode == 0 and dst.is_file() and dst.stat().st_size > 0
    except Exception as exc:  # noqa: BLE001
        print(f"try downscale failed: {exc}")
        return False


def _sweep_try_files(keep: int = 20) -> None:
    """试玩样片只留最近 keep 个，别把磁盘堆满。"""
    try:
        files = sorted(OUTPUTS.glob("try-*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files[keep:]:
            f.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for") or ""
    return (fwd.split(",")[0].strip() or (request.client.host if request.client else "") or "?")


@app.get("/api/try/topics")
def try_topics_list():
    """试玩选题（公开）：落地页据此渲染"选一个选题试做"的卡片。"""
    from . import try_topics
    out = []
    for t in try_topics.TOPICS:
        try:
            try_topics.bundle_dir(t)          # 素材包不在就不给它上架
        except ValueError:
            continue
        out.append({"id": t["id"], "title": t["title"], "subtitle": t["subtitle"],
                    "template": t["template"]})
    return {"topics": out, "templates": [{"id": k, "name": v} for k, v in TEMPLATES.items()],
            "cookie_limit": try_topics.COOKIE_LIMIT, "ip_limit": try_topics.IP_LIMIT}


@app.post("/api/try")
def try_render(request: Request, body: dict = None):
    """提交一次试玩渲染（公开，限流）。

    只认选题 id；模板只认 TEMPLATES 里的；出片是十几秒的低清带水印样片。
    """
    from . import try_topics

    body = body or {}
    t = try_topics.topic(str(body.get("topic") or ""))
    if t is None:
        return JSONResponse({"error": "没有这个试玩选题"}, status_code=404)
    fmt = str(body.get("template") or t["template"])
    if fmt not in TEMPLATES:
        fmt = t["template"]
    try:
        bdir = try_topics.bundle_dir(t)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    cookie = request.cookies.get("vg_try") or ""
    ip = _client_ip(request)
    ok, why = try_topics.guard(WORKSPACES, ip, cookie)
    if not ok:
        return JSONResponse({"error": why, "limited": True}, status_code=429)

    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        ahead = _queue_ahead(job_id)
        JOBS[job_id] = {"stage": "queued", "stage8": 1, "progress": 3, "error": None,
                        "video": None, "project_id": None,
                        "try": {"topic": t["id"], "title": t["title"], "template": fmt},
                        "detail": ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "已加入队列",
                        "t0": time.time()}
        _jobs_save()
        _QUEUE_HEAD.append(job_id)
        _PENDING[job_id] = {"try": True, "try_bundle_dir": str(bdir), "format": fmt,
                            "watermark": True, "useLlm": True, "sfx": True, "sfxMode": "all"}
    _RENDER_QUEUE.put(job_id)
    issued = cookie or uuid.uuid4().hex
    try_topics.remember_cookie(WORKSPACES, issued)   # 发出去的 cookie 立刻记账，下次来就拦得住
    resp = JSONResponse({"job": job_id, "topic": t["id"], "template": fmt})
    resp.set_cookie("vg_try", issued, max_age=180 * 24 * 3600, httponly=True, samesite="lax")
    return resp


@app.get("/api/try/{job_id}")
def try_status(job_id: str):
    """试玩进度（公开）：只回进度和样片链接，不回任何内部路径。"""
    j = JOBS.get(job_id)
    if not j or not j.get("try"):
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    stage = j.get("stage")
    meta = j.get("try") or {}
    return {"stage": stage, "stage8": j.get("stage8"), "progress": j.get("progress"),
            "topic": meta.get("topic"), "template": meta.get("template"),
            "title": meta.get("title"),
            "queued_pos": _queue_ahead(job_id) if stage == "queued" else 0,
            "video": f"/try/{job_id}.mp4" if j.get("try_video") else None,
            "error": j.get("error")}


@app.get("/try/{name}")
def try_video(name: str):
    """试玩样片（公开）：文件名就是任务 id，路径不从用户输入里取。"""
    jid = name[:-4] if name.endswith(".mp4") else name
    if not re.fullmatch(r"[0-9a-f]{6,24}", jid):
        return JSONResponse({"error": "not found"}, status_code=404)
    v = (JOBS.get(jid) or {}).get("try_video")
    if not v or not Path(v).is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(v, media_type="video/mp4", filename=f"GetCut-试玩-{jid}.mp4")


def _queue_ahead(job_id: str) -> int:
    """排在 job_id 前面的任务数 = 排队在我之前的 + 正在渲染的。

    之前只数排队中的，导致"一个在渲染、一个刚排上"时对用户说"马上开始"，
    实际前面还有整整一炉。并发>1 时同样成立。
    """
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
_PUBLIC_PATHS = {"/", "/index.html", "/healthz", "/api/templates",
                 "/api/auth/status", "/api/auth/login", "/api/auth/register",
                 "/api/auth/send-code", "/api/auth/reset-code", "/api/auth/reset",
                 "/api/pricing"}


def _is_public(path: str) -> bool:
    return (path in _PUBLIC_PATHS or path.startswith("/fonts/")
            or path.startswith("/templates/")
            or path.startswith("/api/qr/")
            # 试玩：新访客没账号也要能看选题、提交试做、看进度、拿样片
            or path.startswith("/api/try") or path.startswith("/try/"))


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
    """素材包也是按归属隔离的：自己的、自己项目正在用的、或管理员。

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


def _job_visible(j: dict, request: Request) -> bool:
    """任务（进度/成片/剧照）按归属隔离：试玩样片本就是公开引流物，其余只给
    提交者本人/管理员/开放模式。改动前入库的老任务没有 owner，退回按项目归属判。"""
    if j.get("try"):
        return True
    if _is_adminish(request):
        return True
    if not AUTH_TOKEN and not auth.has_users():
        return True          # 开放模式（本机自用）
    email = _session_email(request)
    owner = j.get("owner")
    if owner is not None:
        return bool(email) and email == owner
    pid = j.get("project_id")
    if not pid:
        return False
    with _LOCK:
        p = next((p for p in _reg()["projects"] if p["project_id"] == pid), None)
    return bool(p) and _project_visible(p, request)


def _request_authed(request: Request) -> bool:
    if _token_ok(request) or _session_email(request):
        return True
    return not AUTH_TOKEN and not auth.has_users()   # 开放模式


def _open_mode() -> bool:
    """本机自用开放模式：没配访问令牌也没建过账号。此时不设付费墙。"""
    return not AUTH_TOKEN and not auth.has_users()


# ---------- 免费档每日出片额度 ----------
USAGE_FILE = Path(config.USAGE_FILE)


def _usage_load() -> dict:
    if USAGE_FILE.is_file():
        try:
            data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:  # noqa: BLE001 - 账本坏了当没记，别把出片挂掉
            pass
    return {}


def _usage_bump(email: str) -> int:
    """记一次出片，返回今天已用次数。只留最近 3 天，防文件长大。"""
    today = time.strftime("%Y-%m-%d")
    keep = {today, time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)),
            time.strftime("%Y-%m-%d", time.localtime(time.time() - 172800))}
    with _LOCK:
        data = _usage_load()
        user = {d: n for d, n in (data.get(email) or {}).items() if d in keep}
        user[today] = int(user.get(today, 0)) + 1
        data[email] = user
        try:
            USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            USAGE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return user[today]


def _tier_of(request: Request) -> str:
    return auth.user_tier(_session_email(request))


def _brand_for(email: str | None) -> dict | None:
    """高级档：当前用户的品牌套件出片参数。免费/未登录/没设置 = None。"""
    if not email or not auth.tier_at_least(email, "premium"):
        return None
    return brand_kit.for_build(email)


# ---------- 品牌套件（高级档） ----------

@app.get("/api/brand")
def brand_get(request: Request):
    """自己的品牌资料（任何登录用户可读，前端好显示引导；写操作才要高级档）。"""
    email = _session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    return {"brand": brand_kit.load(email) or {}, "premium": auth.tier_at_least(email, "premium"),
            "has_logo": brand_kit.logo_path(email) is not None}


@app.put("/api/brand")
def brand_put(body: dict, request: Request):
    email = _session_email(request)
    if not auth.tier_at_least(email, "premium"):
        return JSONResponse({"error": "品牌套件是高级版功能", "tier_required": "premium"},
                            status_code=402)
    data = brand_kit.save(email or "", body)
    return {"ok": True, "brand": data}


@app.post("/api/brand/logo")
def brand_logo_upload(request: Request, file: UploadFile = None):
    email = _session_email(request)
    if not auth.tier_at_least(email, "premium"):
        return JSONResponse({"error": "品牌套件是高级版功能", "tier_required": "premium"},
                            status_code=402)
    if file is None:
        return JSONResponse({"error": "缺少文件"}, status_code=400)
    data = file.file.read(brand_kit.MAX_LOGO + 1)
    try:
        out = brand_kit.set_logo(email or "", data)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, **out}


@app.delete("/api/brand/logo")
def brand_logo_delete(request: Request):
    email = _session_email(request)
    if not auth.tier_at_least(email, "premium"):
        return JSONResponse({"error": "品牌套件是高级版功能", "tier_required": "premium"},
                            status_code=402)
    brand_kit.clear_logo(email or "")
    return {"ok": True}


# ---------- 我的声音（声音复刻，高级档） ----------

@app.get("/api/voice-clone")
def voice_clone_get(request: Request):
    email = _session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    c = brand_kit.clone_info(email)
    return {"premium": auth.tier_at_least(email, "premium"),
            "dashscope": tts_mod.dashscope_ready(),
            "clone": c, "has_voice": bool(c)}


@app.post("/api/voice-clone")
async def voice_clone_create(request: Request, file: UploadFile = None):
    """上传录音（webm/ogg/m4a/mp3）→ ffmpeg 转码 → 百炼声音复刻 → 存 voice_id。"""
    email = _session_email(request)
    if not auth.tier_at_least(email, "premium"):
        return JSONResponse({"error": "声音克隆是高级版功能", "tier_required": "premium"},
                            status_code=402)
    if not tts_mod.dashscope_ready():
        return JSONResponse({"error": "配音服务尚未配置（等站长开通百炼）"}, status_code=503)
    if file is None:
        return JSONResponse({"error": "缺少录音文件"}, status_code=400)
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        return JSONResponse({"error": "录音别超过 20MB（30 秒足够了）"}, status_code=400)
    import tempfile
    from . import voice_clone as vc
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "raw.upload"
        src.write_bytes(raw)
        mp3 = Path(td) / "sample.mp3"
        try:
            vc.convert_audio(src, mp3)
        except vc.CloneError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        try:
            voice_id = vc.enroll(mp3, f"getcut-{brand_kit._key(email)}")
        except vc.CloneError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
    brand_kit.set_clone(email, voice_id, mp3.read_bytes())
    return {"ok": True, "voice_id": voice_id}


@app.delete("/api/voice-clone")
def voice_clone_delete(request: Request):
    email = _session_email(request)
    if not auth.tier_at_least(email, "premium"):
        return JSONResponse({"error": "声音克隆是高级版功能", "tier_required": "premium"},
                            status_code=402)
    vid = brand_kit.clear_clone(email or "")
    if vid:
        from . import voice_clone as vc
        vc.remove(vid)   # 尽力而为
    return {"ok": True}


@app.get("/api/brand/logo")
def brand_logo_get(request: Request):
    """自己的 Logo 图（前端预览用）。"""
    email = _session_email(request)
    p = brand_kit.logo_path(email or "")
    if not p:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type="image/png")


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
def auth_send_code(body: dict, request: Request):
    """注册第一步：给邮箱发验证码。60 秒冷却，10 分钟有效；每 IP 每小时限 10 封。"""
    if not auth.ip_can_send(_client_ip(request)):
        return JSONResponse({"error": "这个网络发验证码太频繁了，一小时后再试"}, status_code=429)
    ok, msg = auth.issue_code(body.get("email", ""))
    if not ok:
        return JSONResponse({"error": msg}, status_code=400)
    auth.ip_record_send(_client_ip(request))
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
def auth_reset_code(body: dict, request: Request):
    """忘记密码第一步：给已注册邮箱发验证码（邮箱没注册就直接说清楚）。"""
    email = body.get("email", "")
    if not auth.user_exists(email):
        return JSONResponse({"error": "这个邮箱还没注册过，先注册吧"}, status_code=400)
    if not auth.ip_can_send(_client_ip(request)):
        return JSONResponse({"error": "这个网络发验证码太频繁了，一小时后再试"}, status_code=429)
    ok, msg = auth.issue_code(email, purpose="重设密码")
    if not ok:
        return JSONResponse({"error": msg}, status_code=400)
    auth.ip_record_send(_client_ip(request))
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


@app.post("/api/auth/change-password")
def auth_change_password(body: dict, request: Request):
    """登录状态下改密码：验当前密码 → 设新密码（会话不用重发，签名里没有密码）。"""
    email = _session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    time.sleep(0.4)   # 和登录一样拖一下，防在线爆破旧密码
    try:
        auth.change_password(email, body.get("old_password", ""),
                             body.get("new_password", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    email = _session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    tier = auth.user_tier(email)
    prof = auth.get_profile(email)
    out = {"email": email, "tier": tier, "tier_label": auth.TIER_LABEL.get(tier, tier),
           "is_admin": auth.is_admin(email),
           "nickname": prof["nickname"], "avatar": prof["avatar"],
           "created": prof["created"], "avatars": auth.AVATARS}
    if tier == "free":
        # 免费档把今天还剩几条说出来，权益卡里直接展示（付费档不限次）
        used = (_usage_load().get(email) or {}).get(time.strftime("%Y-%m-%d"), 0)
        out["builds_today"] = used
        out["free_daily_builds"] = config.FREE_DAILY_BUILDS
    return out


@app.put("/api/me")
def me_update(body: dict, request: Request):
    """改自己的资料（昵称/头像）。只收这两个字段，改密码走 /api/auth/change-password。"""
    email = _session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    try:
        prof = auth.set_profile(email, body.get("nickname"), body.get("avatar"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "nickname": prof["nickname"], "avatar": prof["avatar"]}


# ---------- 档位 / 卡密 / 定价页 ----------

@app.get("/api/pricing")
def pricing(request: Request):
    """定价页数据（公开）：价格、站长微信、收款码在不在。"""
    email = _session_email(request)
    wechat_qr = (config.QR_DIR / "wechat").is_file()
    alipay_qr = (config.QR_DIR / "alipay").is_file()
    return {"prices": config.PRICES, "wechat_id": config.SALES_WECHAT_ID or "",
            "qr": {"wechat": wechat_qr, "alipay": alipay_qr},
            "free_daily_builds": config.FREE_DAILY_BUILDS,
            "tier": auth.user_tier(email), "email": email or "",
            "is_admin": auth.is_admin(email)}


@app.post("/api/license/redeem")
def license_redeem(body: dict, request: Request):
    """卡密兑换：登录用户输码，服务端给账号打档位标记。"""
    email = _session_email(request)
    if not email:
        return JSONResponse({"error": "先登录再兑换"}, status_code=401)
    # 简单防爆破：连续失败 5 次后强制歇 60 秒
    global _REDEEM_FAILS
    now = time.time()
    fails = [f for f in _REDEEM_FAILS.get(email, []) if now - f < 60]
    if len(fails) >= 5:
        return JSONResponse({"error": "试错太多次了，一分钟后再来"}, status_code=429)
    ok, msg, tier = licenses.redeem(email, body.get("code", ""))
    if not ok:
        fails.append(now)
        _REDEEM_FAILS[email] = fails
        return JSONResponse({"error": msg}, status_code=400)
    _REDEEM_FAILS.pop(email, None)
    return {"ok": True, "message": msg, "tier": tier,
            "tier_label": auth.TIER_LABEL.get(tier, tier)}


_REDEEM_FAILS: dict[str, list] = {}


@app.get("/api/admin/licenses")
def admin_list_licenses(request: Request):
    if not _is_adminish(request):
        return JSONResponse({"error": "只有管理员能看"}, status_code=403)
    return {"stats": licenses.stats(), "codes": licenses.list_codes()}


@app.post("/api/admin/licenses/gen")
def admin_gen_licenses(body: dict, request: Request):
    """给直播间备货：生成 N 张卡密，明文只在这一步返回，赶紧复制走。"""
    if not _is_adminish(request):
        return JSONResponse({"error": "只有管理员能生成"}, status_code=403)
    try:
        codes = licenses.generate(str(body.get("tier") or ""), int(body.get("count") or 0),
                                  str(body.get("note") or ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"codes": codes, "stats": licenses.stats()}


_QR_MEDIA = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg"}


@app.post("/api/admin/qr")
def admin_upload_qr(request: Request, which: str = "wechat", file: UploadFile = None):
    """上传收款码（wechat / alipay）。图片落工作区持久卷，重启不丢。"""
    if not _is_adminish(request):
        return JSONResponse({"error": "只有管理员能上传"}, status_code=403)
    if which not in ("wechat", "alipay") or file is None:
        return JSONResponse({"error": "参数不对"}, status_code=400)
    data = file.file.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        return JSONResponse({"error": "图片别超过 4MB"}, status_code=400)
    media = next((m for magic, m in _QR_MEDIA.items() if data.startswith(magic)), None)
    if media is None:
        return JSONResponse({"error": "只认 PNG / JPG 图片"}, status_code=400)
    config.QR_DIR.mkdir(parents=True, exist_ok=True)
    (config.QR_DIR / which).write_bytes(data)
    return {"ok": True, "which": which, "media": media}


@app.get("/api/qr/{which}")
def qr_image(which: str):
    """收款码图片（公开，定价页要展示）。"""
    if which not in ("wechat", "alipay"):
        return JSONResponse({"error": "not found"}, status_code=404)
    f = config.QR_DIR / which
    if not f.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    head = f.read_bytes()[:4]
    media = next((m for magic, m in _QR_MEDIA.items() if head.startswith(magic)), "image/png")
    return FileResponse(f, media_type=media)


# ---------- 试听（B5）----------

@app.get("/api/voices")
def voices_list(request: Request):
    """音色目录：配了百炼密钥就是 CosyVoice 音色；没配则退回 edge 内置目录
    （界面展示什么，合成时就真的用什么，不挂羊头卖狗肉）。"""
    ready = tts_mod.dashscope_ready()
    if not ready:
        legacy = tts_mod.LEGACY_EDGE_VOICES
        return {"voices": [{"id": k, "label": v, "provider": "edge"} for k, v in legacy.items()],
                "dashscope": False, "default": "zh-CN-YunxiNeural"}
    items = [{"id": vid, "label": v.get("label", vid), "provider": "dashscope"}
             for vid, v in tts_mod.load_voices().items()]
    # 我的声音（声音复刻）：克隆过就放进音色列表最前面
    email = _session_email(request)
    if email and auth.tier_at_least(email, "premium") and brand_kit.clone_info(email):
        items.insert(0, {"id": "@clone", "label": "我的声音 · 克隆", "provider": "dashscope"})
    return {"voices": items, "dashscope": True, "default": tts_mod.VOICE}


@app.get("/api/voice-preview")
def voice_preview(voice: str = "xiaoxia"):
    """音色试听：合成一句短样，按音色+渠道缓存（首次约 1-2 秒）。"""
    entry = tts_mod.resolve_voice(voice)
    if entry.get("legacy"):
        safe = "edge_" + re.sub(r"[^A-Za-z0-9_-]", "", entry.get("edge") or "x")[:60]
    elif entry.get("provider") == "dashscope" and tts_mod.dashscope_ready():
        safe = "ds_" + re.sub(r"[^A-Za-z0-9_-]", "", str(entry.get("id") or "x"))[:60]
    else:
        safe = "edge_" + re.sub(r"[^A-Za-z0-9_-]", "", str(entry.get("edge") or "x"))[:60]
    d = ROOT / "assets" / "voice_previews"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{safe}.mp3"
    if not f.exists() or f.stat().st_size == 0:
        try:
            tts_mod.synthesize_preview(
                voice, f, "大家好，这是一段配音试听，听听这个声音合不合适。")
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


@app.get("/api/sfx/{name}")
def sfx_file(name: str):
    """音效试听/播放：只允许 assets/sfx 下的音频。"""
    f = (ROOT / "assets" / "sfx" / name).resolve()
    root = (ROOT / "assets" / "sfx").resolve()
    if root not in f.parents or f.suffix.lower() not in (".mp3", ".wav", ".m4a") or not f.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f, media_type="audio/mpeg")


# 音效分类的中文名与"什么时候响"，试听页按这个分组
_SFX_LABEL = {
    "open": ("开场", "片头起手那一下"),
    "cut": ("镜头切换", "每换一个画面轻切一声"),
    "card": ("卡片弹出", "设计卡/胶囊/榜单弹出来时"),
    "number": ("数字落点", "数字、数字卡冒出来时"),
    "emphasis": ("重点强调", "金句、要用力砸一下的地方"),
    "end": ("收尾", "最后收住"),
}


@app.get("/sfx-preview", response_class=HTMLResponse)
def sfx_preview():
    """音效试听页：按分类列出库里的每一条，点一下就能听。

    存在的理由：出片的人（也就是我）听不到声音，音效"像不像那么回事"只能由人耳朵验收。
    换音效 = 把 mp3 丢进 assets/sfx/ 并在 library.json 加一条，这里会自动出现。
    """
    lib = ROOT / "assets" / "sfx"
    items: list[dict] = []
    try:
        items = json.loads((lib / "library.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        items = []
    rows: dict[str, list[str]] = {}
    for it in items:
        cat = it.get("category") or "其他"
        if cat == "legacy":
            continue
        f = lib / it["file"]
        if not f.is_file():
            continue
        rows.setdefault(cat, []).append(
            f'<li><audio controls preload="none" src="/api/sfx/{html.escape(it["file"])}"></audio>'
            f'<b>{html.escape(it["file"])}</b>'
            f'<small>{it.get("bytes", 0) // 1024} KB · {html.escape(str(it.get("source", "")))}</small></li>')
    order = [c for c in _SFX_LABEL if c in rows] + [c for c in rows if c not in _SFX_LABEL]
    body = "".join(
        f'<section><h2>{html.escape(_SFX_LABEL.get(c, (c, ""))[0])}'
        f'<small>{html.escape(_SFX_LABEL.get(c, ("", ""))[1])}　{len(rows[c])} 条</small></h2>'
        f'<ul>{"".join(rows[c])}</ul></section>'
        for c in order)
    total = sum(len(v) for v in rows.values())
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>音效试听 · 共 {total} 条</title><style>
body{{margin:0;padding:32px 24px 64px;background:#12141c;color:#e3e5f0;
  font:14px/1.6 "Microsoft YaHei","Segoe UI",sans-serif}}
h1{{font-size:22px;margin:0 0 6px}}p.sub{{color:#98a0b6;margin:0 0 26px}}
h2{{font-size:16px;margin:30px 0 12px;display:flex;align-items:baseline;gap:12px}}
h2 small{{font-weight:400;color:#98a0b6;font-size:12px}}
ul{{list-style:none;margin:0;padding:0;display:grid;gap:10px}}
li{{display:flex;align-items:center;gap:14px;background:#1a1d29;border:1px solid #2a2f3f;
  border-radius:10px;padding:12px 16px}}
li b{{font-size:13px;font-weight:600}}li small{{color:#98a0b6;font-size:12px;margin-left:auto}}
audio{{height:34px}}
</style></head><body>
<h1>音效试听</h1>
<p class="sub">共 {total} 条。哪条不合适就在对话里点它的文件名，我换掉。
音效是"什么时候弹出一个东西就响一下"，音量统一压在解说之下。</p>
{body}</body></html>"""


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
            JOBS[jid].update(stage="failed", stage8=8, t_end=time.time(),
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
    """模板素材：真实静帧封面 tpl-<id>.png，和样片 sample-<id>.mp4（选择器里点一下就能看）。

    由 tools/make_template_previews.py 一键生成，模板改了就重跑那条命令。
    """
    root = (STATIC / "templates").resolve()
    f = (root / name).resolve()
    if not f.is_file() or root not in f.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    media = "video/mp4" if f.suffix.lower() == ".mp4" else "image/png"
    return FileResponse(f, media_type=media)


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


# ---------- 分镜预览（渲染前先看每镜画面） ----------

def _preview_auth_ok(pid: str, request: Request) -> bool:
    with _LOCK:
        target = next((p for p in _reg()["projects"]
                       if p["project_id"] == pid), None)
    if not target or not _project_visible(target, request):
        return False
    return True


def _preview_render_body(body: dict, request: Request = None) -> dict:
    """预演入参校验：素材包目录 + 渲染配置。免费档强制带水印（跟成片一个待遇）。"""
    bundle = body.get("bundle")
    if not bundle:
        raise ValueError("缺少素材包")
    bundle_dir = _resolve_bundle(bundle)
    _resolve_bgm(body.get("bgm"))
    fmt = body.get("format") or DEFAULT_TEMPLATE
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"模板 '{fmt}' 不存在")
    watermark = body.get("watermark", True) is not False
    if request is not None and not _open_mode():
        email = _session_email(request)
        if email and auth.user_tier(email) == "free":
            watermark = True
    return {"bundle_dir": bundle_dir, "bundle": bundle,
            "voice": body.get("voice") or None,
            "rate": _normalize_rate(body.get("rate")),
            "format": fmt,
            "subtitles": bool(body.get("subtitles", True)),
            "sources": bool(body.get("sources", True)),
            "watermark": watermark,
            "theme": body.get("theme") or "auto",
            "disclaimer": body.get("disclaimer"),
            "brand": (_brand_for(_session_email(request)) if request is not None else None)}


@app.post("/api/projects/{pid}/preview/plan")
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


@app.get("/api/projects/{pid}/preview/status")
def preview_status(pid: str, request: Request):
    if not _preview_auth_ok(pid, request):
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    return preview.preview_state(pid)


@app.post("/api/projects/{pid}/preview/shots")
def preview_shots(pid: str, body: dict, request: Request):
    """分镜页数据：逐镜头静帧按需出图（每张 1-3 秒）。"""
    if not _preview_auth_ok(pid, request):
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    st = preview.preview_state(pid)
    if st["state"] != "ready":
        return JSONResponse({"error": "预演未就绪", "state": st["state"]}, status_code=409)
    bundle = body.get("bundle") or ""
    d = (WORKSPACES / bundle).resolve()
    if not bundle or WORKSPACES.resolve() not in d.parents:
        return JSONResponse({"error": "素材包不合法"}, status_code=400)
    return preview.build_preview_payload(pid, {"bundle": bundle})


@app.get("/api/projects/{pid}/preview/stills/{name}")
def preview_still(pid: str, name: str):
    f = (preview.preview_dir(pid) / "stills" / name).resolve()
    if not f.is_file() or preview.preview_dir(pid).resolve() not in f.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f, media_type="image/jpeg")


@app.post("/api/projects/{pid}/preview/invalidate")
def preview_invalidate(pid: str, body: dict, request: Request):
    """配置/素材变更后丢弃预演数据。"""
    if not _preview_auth_ok(pid, request):
        return JSONResponse({"error": "项目不存在"}, status_code=404)
    preview.invalidate(pid)
    return {"ok": True}


def _render_or_404(pid: str, rid: str, request: Request):
    """按项目归属取出成片路径；取不到返回 (None, 响应)。"""
    from pathlib import Path as _P
    with _LOCK:
        reg = _reg()
        target = next((p for p in reg["projects"] if p["project_id"] == pid), None)
        if not target or not _project_visible(target, request):
            return None, JSONResponse({"error": "项目不存在"}, status_code=404)
        render = next((r for r in target.get("renders", []) if r.get("id") == rid), None)
        if not render:
            return None, JSONResponse({"error": "成片不存在"}, status_code=404)
        video = _P(render["file"])
        if not video.is_file():
            return None, JSONResponse({"error": "成片文件缺失"}, status_code=404)
    return video, None


@app.get("/api/projects/{pid}/renders/{rid}/jianying-status")
def jianying_status(pid: str, rid: str, request: Request):
    """草稿备好了没：渲染完成后系统就在后台备，前端据此显示"秒装"还是"准备中"。"""
    from . import draft_build
    from . import jianying_draft as jyd

    video, err = _render_or_404(pid, rid, request)
    if err:
        return err
    plan_dir = jyd.draft_dir_for(video)
    ready = bool(draft_build.plan_fresh(plan_dir, video))
    return {"ready": ready, "building": (not ready) and str(video) in DRAFT_PREP,
            "jianying": jyd.jianying_draft_dir().is_dir()}


def _require_premium(request: Request):
    """高级版付费墙。返回 None 表示放行，否则返回 402 响应。"""
    if _open_mode():          # 本机自用开放模式不设墙
        return None
    if auth.tier_at_least(_session_email(request), "premium"):
        return None
    return JSONResponse(
        {"error": f"导出剪映草稿是高级版功能（¥{config.PRICES['premium']} 永久买断）。"
                  "点右上角「升级」查看。",
         "tier_required": "premium"},
        status_code=402)


@app.post("/api/projects/{pid}/renders/{rid}/jianying-import")
def jianying_import(pid: str, rid: str, request: Request):
    """一键导入剪映。

    这台机器上装了剪映（能找到草稿库）→ 直接把草稿装进去，用户打开剪映就能看到；
    没装/不是本机（比如线上服务器）→ 回 {installed:false}，前端退回下载导入包
    （包里带「一键导入剪映.bat」，解压后双击即可）。
    """
    import tempfile
    from . import jianying_draft as jyd

    if (wall := _require_premium(request)) is not None:
        return wall
    video, err = _render_or_404(pid, rid, request)
    if err:
        return err
    mf = jyd.load_manifest(video)
    if mf is None:
        return JSONResponse({"error": "这条成片没有草稿清单（旧成片不支持分轨草稿）"}, status_code=400)

    plan_dir = jyd.prepare_draft(video, mf)          # 通常已由后台备好，这里是兜底
    if plan_dir is None:
        return JSONResponse({"installed": False, "download": True})

    root = jyd.jianying_draft_dir()
    if not root.is_dir():
        # 服务器这一侧没有剪映（线上部署就是这样）：让前端去下载导入包
        return {"installed": False, "download": True, "reason": "本机找不到剪映草稿目录"}

    voice = mf.get("voice")
    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "draft.zip"
        jyd.build_zip(mf, video, Path(voice) if voice else None, zip_path)
        dest = jyd.install_draft(zip_path)
    return {"installed": True, "name": dest.name}


@app.get("/api/projects/{pid}/renders/{rid}/jianying-draft")
def jianying_draft_zip(pid: str, rid: str, request: Request):
    """把指定成片打包成剪映专业版草稿 zip（分镜切段 + 可编辑字幕[关字幕渲染时]）。"""
    import tempfile
    import zipfile
    from pathlib import Path as _P
    from urllib.parse import quote
    from . import jianying_draft as jyd

    if (wall := _require_premium(request)) is not None:
        return wall
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
    fname = f"GetCut-剪映草稿-{title}-{rid[:6]}.zip"
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
    # 付费墙：免费档每天限量出片且强制带 GetCut 水印；基础/高级版不限量、水印随意。
    email = _session_email(request)
    if email and not auth.is_admin(email) and auth.user_tier(email) == "free":
        body = dict(body)
        body["watermark"] = True
        used = _usage_bump(email)
        if used > config.FREE_DAILY_BUILDS:
            return JSONResponse(
                {"error": f"今天的免费额度（每天 {config.FREE_DAILY_BUILDS} 条）用完了。"
                          f"基础版 ¥{config.PRICES['basic']} 永久不限量——点右上角「升级」看看",
                 "limited": True},
                status_code=429)
    if email:
        body = dict(body)
        body["brand"] = _brand_for(email)   # 高级档品牌套件，服务端自动带上（默认配置固化）
        if body.get("voice") == "@clone":
            clone = brand_kit.clone_info(email) if auth.tier_at_least(email, "premium") else None
            body["voice"] = (clone or {}).get("voice_id") or None
        raw_badge = str((body.get("series") or {}).get("badge") or "").strip()
        body["series"] = {"badge": raw_badge[:24]} if raw_badge and auth.tier_at_least(email, "premium") else None
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
                        "project_id": pid, "owner": email,
                        "detail": ("排队中 · 前面还有 %d 个任务" % ahead) if ahead
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
def job_status(job_id: str, request: Request):
    j = JOBS.get(job_id)
    if j is None or not _job_visible(j, request):
        return {"stage": "unknown"}   # 不存在与无权同形，不泄露任务存在性
    out = dict(j)
    if out.get("stage") == "queued":
        with _LOCK:
            ahead = _queue_ahead(job_id)
        out["queued_pos"] = ahead
        out["detail"] = ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "马上开始"
    t0 = out.get("t0")
    # 跑完/失败后冻结耗时，否则"已用"会一直涨（回来再看变成几十小时）
    out["elapsed"] = int((out.get("t_end") or time.time()) - t0) if t0 else None
    # 分镜剧照（渲染开始前先拍好，渲染中陆续可见）
    stills = sorted(OUTPUTS.glob(f"{job_id}-still-*.jpg")) if OUTPUTS.is_dir() else []
    out["stills"] = [f"/still/{p.name}" for p in stills]
    return out


@app.get("/still/{name}")
def still(name: str, request: Request):
    f = (OUTPUTS / name).resolve()
    if not f.is_file() or OUTPUTS.resolve() not in f.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    jid = name.split("-still-", 1)[0]      # 剧照文件名 = <job_id>-still-<n>.jpg
    if not _job_visible(JOBS.get(jid) or {}, request):
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
def latest(request: Request):
    """最近成片名（前端已不用；留给管理员巡检，普通用户不给跨用户文件名）。"""
    if not _open_mode() and not _is_adminish(request):
        return JSONResponse({"error": "not found"}, status_code=404)
    outs = sorted(OUTPUTS.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if OUTPUTS.is_dir() else []
    if not outs:
        return {"video": None}
    f = outs[0]
    jid = f.stem.rsplit("-", 1)[-1]
    return {"video": f.name, "job": jid, "mtime": int(f.stat().st_mtime)}


@app.get("/video/{job_id}")
def video(job_id: str, request: Request):
    j = JOBS.get(job_id)
    v = (j or {}).get("video")
    if not v or not _job_visible(j, request):
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
        # 试玩任务由 /api/try 给出已经校验过的绝对路径；其余任务一律只认工作区里的包名
        if body.get("try") and body.get("try_bundle_dir"):
            bundle_dir = Path(body["try_bundle_dir"]).resolve()
            if not (bundle_dir / "content.json").is_file():
                raise ValueError("试玩素材包缺失")
        else:
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
                      watermark=body.get("watermark", True) is not False,
                      use_llm=bool(body.get("useLlm", True)),
                      brand=body.get("brand") or None,
                      series=body.get("series") or None,
                      job_id=job_id,
                      progress=progress)
        with _LOCK:
            JOBS[job_id].update(stage="done", stage8=8, progress=100, video=str(out), t_end=time.time(),
                                detail="成片已生成")
            _jobs_save()
            reg = _reg()
            for p in reg["projects"]:
                if p["project_id"] == body.get("project_id"):
                    p.setdefault("renders", []).append({"id": job_id, "file": str(out),
                        "ts": time.strftime("%Y/%m/%d %H:%M")})
            _reg_save(reg)
        _cleanup_work(bundle_dir.name)
        if body.get("try"):
            # 试玩：降成 720p 带水印的样片给公开链接，原始大文件删掉；不备草稿资产
            small = OUTPUTS / f"try-{job_id}.mp4"
            if _downscale_720(out, small):
                with _LOCK:
                    JOBS[job_id]["try_video"] = str(small)
                out.unlink(missing_ok=True)
                _sweep_try_files()
            else:
                with _LOCK:
                    JOBS[job_id].update(stage="failed", error="样片转码失败，请稍后再试")
        else:
            # 成片已经交付，接着在后台把剪映草稿资产备好——用户走到导出页时通常已就绪，
            # 点「一键导入剪映」秒装，不用再等 1-2 分钟
            threading.Thread(target=_prebuild_draft, args=(Path(out),), daemon=True).start()
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            JOBS[job_id].update(stage="failed", stage8=8, error=str(e)[-800:], t_end=time.time())
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
