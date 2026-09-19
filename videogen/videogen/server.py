"""videogen 本地可视化工作台后端。

    python -m videogen.server     # http://localhost:8600

聚焦视频生成：素材包选择/上传 -> 内容确认 -> 渲染配置 -> 生成与成片。
"""
from __future__ import annotations

import argparse
import asyncio
import hmac as _hmac
import html
import io
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

from . import auth, config, licenses, preview, voice_clone
from . import brand as brand_kit
from . import tts as tts_mod
from .schemas import Content, Manifest, JobCancelled

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
INTAKE_TTL_SECONDS = 24 * 3600                # Agent 直投的待认领包保留 24 小时
INTAKE_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
SUPPORTED_FORMATS = set(TEMPLATES) | set(TEMPLATE_ALIAS)
MAX_JOBS_KEPT = 80                            # jobs.json 只留最近这么多条，防无限膨胀

app = FastAPI(title="GetCut studio")
JOBS: dict[str, dict] = {}
JOBS_FILE = ROOT / "jobs.json"
REG = ROOT / "registry.json"
# 全局锁：JOBS / registry / 渲染工作目录都是共享可变状态，串行化写操作
_LOCK = threading.RLock()
# 双通道流水线：
#   prep 通道 —— 配音/分镜/版式（等外部 API 为主），多路并行，不占渲染力
#   渲染通道 —— 画面渲染/混音（吃 CPU），同时最多 _RENDER_CONCURRENCY 路
# 渲染中间产物（props_*.json / visual_*.mp4）已按任务隔离，多路互不覆盖。
_PREP_CONCURRENCY = max(1, int(os.environ.get("VIDEOGEN_PREP_CONCURRENCY", "2")))
_RENDER_CONCURRENCY = max(1, int(os.environ.get("VIDEOGEN_CONCURRENCY", "1")))
_PREP_WAIT: list[str] = []     # 等预备通道的任务（FIFO）
_RENDER_WAIT: list[dict] = []  # 等渲染灶台的任务：{"job": id, "prio": int, "seq": int}
_RENDER_SEQ = 0
_PREP_CV = threading.Condition(_LOCK)
_RENDER_CV = threading.Condition(_LOCK)
# 灶台之外的两条低优先后台通道（都限流，防影子任务偷走下一批人的渲染力）：
#   画面校验 —— 抽帧 + 等外部视觉 API，成片交付后才跑，不占灶台名额
#   草稿备料 —— 剪映草稿是一次额外的 Remotion 渲染，默认只留 1 路细水长流
_VERIFY_CONCURRENCY = max(1, int(os.environ.get("VIDEOGEN_VERIFY_CONCURRENCY", "2")))
_DRAFT_CONCURRENCY = max(1, int(os.environ.get("VIDEOGEN_DRAFT_CONCURRENCY", "1")))
_VERIFY_SEM = threading.Semaphore(_VERIFY_CONCURRENCY)
_DRAFT_SEM = threading.Semaphore(_DRAFT_CONCURRENCY)

# 正在干活（非排队/非终态）的阶段：算排队位置时要把它们算在"前面"
_ACTIVE_STAGES = ("tts", "plan", "props", "prepped", "render", "audio", "mux")
_RENDER_STAGES = ("render", "audio", "mux")


# 正在后台备草稿的成片路径：前端据此显示"草稿准备中"还是"已备好"
DRAFT_PREP: set[str] = set()


def _prebuild_draft(video) -> None:
    """渲染完成后在后台把剪映草稿资产备好（失败不影响任何事，导出时还会再试）。

    草稿本身要再渲一次 Remotion——限流 _DRAFT_CONCURRENCY 路，
    否则高峰期成片后面排队的影子渲染会把下一批人的灶台吃掉。
    """
    key = str(video)
    DRAFT_PREP.add(key)
    try:
        from . import jianying_draft as jyd
        with _DRAFT_SEM:
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


@app.get("/api/sample-bundle")
def sample_bundle():
    """示例素材包（公开）：把试玩素材现打成 zip 供下载——
    用户拆开看一眼就知道"素材包"长什么样，不用再对着空拖拽区发懵。"""
    from urllib.parse import quote
    from . import try_topics
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
        _PENDING[job_id] = {"try": True, "try_bundle_dir": str(bdir), "format": fmt,
                            "watermark": True, "useLlm": True, "sfx": True, "sfxMode": "all"}
        _PREP_WAIT.append(job_id)
        _PREP_CV.notify()
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
            "queued_pos": _queue_ahead(job_id) if stage in ("queued", "prepped") else 0,
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
    """排在 job_id 前面的任务数（"前面还有 N 个任务"的展示口径）。

    queued  = 还没轮上配音：数 prep 通道里在我之前的 + 所有正在干活的
    prepped = 配音分镜已就绪等灶台：数插在我前面的（付费优先）+ 正在渲染的
    """
    with _LOCK:
        j = JOBS.get(job_id) or {}
        stage = j.get("stage")
        active = sum(1 for x in JOBS.values() if x.get("stage") in _ACTIVE_STAGES)
        if stage == "prepped":
            me = next((e for e in _RENDER_WAIT if e["job"] == job_id), None)
            if me is None:
                return active
            ahead = sum(1 for e in _RENDER_WAIT
                        if e["prio"] > me["prio"]
                        or (e["prio"] == me["prio"] and e["seq"] < me["seq"]))
            return ahead + sum(1 for x in JOBS.values() if x.get("stage") in _RENDER_STAGES)
        if stage == "queued":
            try:
                waiting = _PREP_WAIT.index(job_id)
            except ValueError:
                waiting = 0
            return waiting + active
        return active
_PENDING: dict = {}      # job_id -> body（入队暂存，开跑时取出）


def _job_prio(body: dict, email: str | None) -> int:
    """渲染灶台的优先级：付费(2) > 免费注册(1) > 试玩(0)。付费用户不跟试玩抢队。"""
    if body.get("try"):
        return 0
    if email and (auth.is_admin(email) or auth.tier_at_least(email, "basic")):
        return 2
    return 1


def _enqueue_render(job_id: str, prio: int) -> None:
    global _RENDER_SEQ
    with _LOCK:
        _RENDER_SEQ += 1
        _RENDER_WAIT.append({"job": job_id, "prio": prio, "seq": _RENDER_SEQ})
        _RENDER_CV.notify()


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
                 "/api/pricing", "/api/sample-bundle"}


def _is_public(path: str) -> bool:
    return (path in _PUBLIC_PATHS or path.startswith("/fonts/")
            or path.startswith("/templates/")
            # 声音克隆登记：百炼来下载用户录音的中转地址（随机 40 位 hex，登记完即删）
            or path.startswith("/vc-src/")
            # 试玩：新访客没账号也要能看选题、提交试做、看进度、拿样片
            or path.startswith("/api/try") or path.startswith("/try/")
            # Agent 直投：getcut-bundle 技能打包完自动 POST 上来，浏览器打开 /i/<code>
            # 认领导入。公开但按 IP 限流，码本身是随机能力凭证，包 24 小时无人认领即清。
            or path.startswith("/api/intake") or path.startswith("/i/")
            # 剪映导入助手：安装器是公开脚本；pull 靠一次性 token 自证（见 _JY_PULL_TOKENS）
            or path.startswith("/assistant/")
            or path.startswith("/api/jianying/pull"))


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


def _clone_worker(raw: bytes, prefix: str, base: str) -> tuple[str, bytes]:
    """阻塞全程（ffmpeg 转码 + 等百炼下载/登记）。必须在工作者线程里跑：
    事件循环若被占死，百炼来 /vc-src/ 取录音时本站无法应答 → 死锁，
    百炼侧报 download audio failed（2026-09-19 用户实录踩过）。"""
    import tempfile
    from . import voice_clone as vc
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "raw.upload"
        src.write_bytes(raw)
        mp3 = Path(td) / "sample.mp3"
        vc.convert_audio(src, mp3)   # CloneError 由调用方翻译成 400/502
        voice_id = vc.enroll(mp3, prefix, base)
        # 预热试听缓存：否则用户第一次点试听要现合成（数秒），
        # 超出浏览器"点击后 5 秒内可自动播放"窗口会被拦（实测踩过）
        try:
            pf = _preview_file(voice_id)
            if not pf.exists() or pf.stat().st_size == 0:
                tts_mod.synthesize_preview(voice_id, pf, "嗨，这是你的专属声音，来听听效果。")
        except Exception:  # noqa: BLE001 - 预热失败不影响登记，试听会走现场合成
            pass
        return voice_id, mp3.read_bytes()


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
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    host = request.headers.get("host") or request.url.netloc
    base = config.PUBLIC_BASE_URL or f"{proto}://{host}"
    try:
        voice_id, mp3_bytes = await asyncio.to_thread(
            _clone_worker, raw, f"getcut-{brand_kit._key(email)}", base)
    except voice_clone.CloneError as e:
        code = 400 if "录音转换失败" in str(e) or "ffmpeg" in str(e) else 502
        return JSONResponse({"error": str(e)}, status_code=code)
    brand_kit.set_clone(email, voice_id, mp3_bytes)
    return {"ok": True, "voice_id": voice_id}


@app.get("/vc-src/{name}")
def vc_src(name: str):
    """声音克隆登记期间的中转文件：40 位随机 hex 命名，登记完即删，30 分钟兜底清扫。"""
    if not re.fullmatch(r"[0-9a-f]{40}\.mp3", name or ""):
        return JSONResponse({"error": "not found"}, status_code=404)
    f = voice_clone.VC_SRC_DIR / name
    if not f.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f, media_type="audio/mpeg")


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
    """定价页数据（公开）：价格与站长微信。收款码功能已拆（只走微信转账）。"""
    email = _session_email(request)
    return {"prices": config.PRICES, "wechat_id": config.SALES_WECHAT_ID or "",
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


def _preview_file(voice: str) -> Path:
    """试听音频的缓存路径（按音色+渠道命名，冷了会现合成）。"""
    entry = tts_mod.resolve_voice(voice)
    if entry.get("legacy"):
        safe = "edge_" + re.sub(r"[^A-Za-z0-9_-]", "", entry.get("edge") or "x")[:60]
    elif entry.get("provider") == "dashscope" and tts_mod.dashscope_ready():
        safe = "ds_" + re.sub(r"[^A-Za-z0-9_-]", "", str(entry.get("id") or "x"))[:60]
    else:
        safe = "edge_" + re.sub(r"[^A-Za-z0-9_-]", "", str(entry.get("edge") or "x"))[:60]
    d = ROOT / "assets" / "voice_previews"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.mp3"


@app.get("/api/voice-preview")
def voice_preview(request: Request, voice: str = "xiaoxia"):
    """音色试听：合成一句短样，按音色+渠道缓存（首次约 1-2 秒）。"""
    if voice == "@clone":
        # 确认页里「我的声音」以 @clone 占位；试听必须换成当前用户真实的克隆音色 id
        email = _session_email(request)
        c = brand_kit.clone_info(email) if email else None
        if not c or not c.get("voice_id"):
            return JSONResponse({"error": "还没有克隆声音，先到「我的 → 品牌套装」里录制"},
                                status_code=404)
        voice = c["voice_id"]
    f = _preview_file(voice)
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
    _stale = [jid for jid, j in JOBS.items() if j.get("stage") not in ("done", "failed", "cancelled")]
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


@app.get("/i/{code}", response_class=HTMLResponse)
def intake_page(code: str):
    """Agent 直投短链：与 / 同一份 SPA，前端按路径进入「素材包已送达」落地页。"""
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
    没装/不是本机（比如线上服务器）→ 签发一次性 token 让本地小助手来取：
    浏览器唤起 getcut:// 协议，助手凭 token 从 /api/jianying/pull 拉草稿包装进剪映，
    全程用户不用下载、解压、跑脚本。
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

    jyd.prepare_draft(video, mf)                 # 通常已由后台备好，这里是兜底

    root = jyd.jianying_draft_dir()
    if not root.is_dir():
        # 服务器这一侧没有剪映（线上部署就是这样）：签一次性 token 给本地小助手
        # （prepare_draft 失败也不退回下载：build_zip 自带"整条切片"兜底，照样一键进剪映）
        token = uuid.uuid4().hex
        with _LOCK:
            now = time.time()
            for k in [k for k, v in _JY_PULL_TOKENS.items() if v["exp"] < now]:
                _JY_PULL_TOKENS.pop(k, None)
            _JY_PULL_TOKENS[token] = {
                "video": str(video), "rid": rid,
                "title": (mf.get("title") or "成片"),
                "email": _session_email(request), "exp": now + 300}
        return {"installed": False, "protocol": True,
                "pull": f"/api/jianying/pull?t={token}"}

    voice = mf.get("voice")
    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "draft.zip"
        jyd.build_zip(mf, video, Path(voice) if voice else None, zip_path)
        dest = jyd.install_draft(zip_path)
    return {"installed": True, "name": dest.name}


# 一次性草稿提取 token（线上"导入到剪映"专用）：小助手没有浏览器会话，
# 靠它自证身份。5 分钟过期，下载成功即焚，签发前已过高级版付费墙。
_JY_PULL_TOKENS: dict[str, dict] = {}


@app.get("/api/jianying/pull")
def jianying_pull(t: str = ""):
    """本地小助手凭一次性 token 拉剪映草稿包（无会话，token 即凭证）。"""
    info = _JY_PULL_TOKENS.get(t)
    if not info or info["exp"] < time.time():
        _JY_PULL_TOKENS.pop(t, None)
        return JSONResponse(
            {"error": "导入链接已过期或已使用，请回到页面重新点「一键导入到剪映」"},
            status_code=403)
    from . import jianying_draft as jyd
    from pathlib import Path as _P

    video = _P(info["video"])
    if not video.is_file():
        _JY_PULL_TOKENS.pop(t, None)
        return JSONResponse({"error": "成片文件缺失"}, status_code=404)
    mf = jyd.load_manifest(video)
    if mf is None:
        return JSONResponse({"error": "草稿清单缺失，请回页面重新点「一键导入到剪映」"},
                            status_code=400)
    mf["render_id"] = info["rid"]
    mf.setdefault("title", info["title"])
    voice = mf.get("voice")
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            zpath = _P(td) / "draft.zip"
            jyd.build_zip(mf, video, _P(voice) if voice else None, zpath)
            data = zpath.read_bytes()
    except Exception as exc:  # noqa: BLE001 - 打包失败保留 token，助手重试还能用
        return JSONResponse({"error": f"草稿打包失败: {exc}"}, status_code=500)
    _JY_PULL_TOKENS.pop(t, None)      # 下载成功才焚 token
    fname = f"GetCut-剪映草稿-{info['rid'][:6]}.zip"
    from urllib.parse import quote
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition":
                 "attachment; filename=getcut-draft.zip; "
                 "filename*=UTF-8''{}".format(quote(fname))})


@app.get("/assistant/GetCut-Setup.bat")
def jianying_assistant_installer():
    """导入助手安装器（单文件 bat，内嵌 ps1）。公开路由：脚本里没有用户数据。"""
    f = config.STATIC / "assistant" / "GetCut-Setup.bat"
    if not f.is_file():
        return JSONResponse({"error": "安装器未构建：跑 python _tools/build_assistant.py"},
                            status_code=404)
    return FileResponse(f, media_type="application/octet-stream",
                        headers={"Content-Disposition":
                                 "attachment; filename=GetCut-Setup.bat"})


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


def _fix_mojibake_name(name: str) -> str:
    """multipart 里的中文文件名常被按 latin-1 解码成乱码（curl/旧客户端不发 filename*），掰回 UTF-8。

    本来就解对了的名字（含真正的中文）latin-1 编不回去，原样返回。"""
    try:
        return name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


@app.post("/api/upload")
async def upload(file: UploadFile, request: Request):
    name = Path(_fix_mojibake_name(file.filename or "bundle.zip")).stem or f"bundle-{int(time.time())}"
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


# ---------- Agent 直投（素材包自动进站） ----------
# 配合 getcut-bundle 技能：Agent 打包完直接 POST 上来拿一条 /i/<code> 短链；
# 任何浏览器（含手机）打开短链，页面自己把包导进工作台并建好项目，
# 用户只需要点「确定，导入工作台」→「确认内容并开始生成」。

INTAKES = WORKSPACES / ".intakes"            # 待认领 zip + 登记 sidecar（数据盘，重启不丢）
_INTAKE_RATE: dict[str, list[float]] = {}    # ip -> 最近上传时间戳（滑窗限流）


def _intake_paths(code: str) -> tuple[Path, Path]:
    return INTAKES / f"{code}.zip", INTAKES / f"{code}.json"


def _intake_sidecar(code: str) -> dict:
    _, side = _intake_paths(code)
    if side.is_file():
        try:
            return json.loads(side.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 登记坏了按没有处理
            return {}
    return {}


def _sweep_intakes(ttl: int = INTAKE_TTL_SECONDS) -> None:
    """过期的待认领包（zip 与登记）直接删。"""
    if not INTAKES.is_dir():
        return
    now = time.time()
    for f in INTAKES.iterdir():
        try:
            if f.is_file() and now - f.stat().st_mtime > ttl:
                f.unlink(missing_ok=True)
        except OSError:
            pass


@app.post("/api/intake")
async def intake_create(file: UploadFile, request: Request):
    ip = _client_ip(request)
    now = time.time()
    hits = [t for t in _INTAKE_RATE.get(ip, []) if now - t < 3600]
    if len(hits) >= 10:
        return JSONResponse({"error": "这个地址上传太频繁了，一小时后再试"}, status_code=429)
    hits.append(now)
    _INTAKE_RATE[ip] = hits
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse({"error": "zip 超过 512MB 上限"}, status_code=413)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if "content.json" not in zf.namelist():
                raise zipfile.BadZipFile("no content.json")
    except zipfile.BadZipFile:
        return JSONResponse({"error": "zip 里没有 content.json，不是有效的素材包"}, status_code=400)
    INTAKES.mkdir(parents=True, exist_ok=True)
    _sweep_intakes()
    code = uuid.uuid4().hex[:12]
    zf_path, side = _intake_paths(code)
    zf_path.write_bytes(data)
    side.write_text(json.dumps({"file": _fix_mojibake_name(file.filename or "bundle.zip"),
                                "created": now, "ip": ip}, ensure_ascii=False),
                    encoding="utf-8")
    base = config.PUBLIC_BASE_URL or f"{request.url.scheme}://{request.url.netloc}"
    return {"code": code, "url": f"{base}/i/{code}"}


@app.get("/api/intake/{code}/meta")
def intake_meta(code: str):
    """落地页概要：不解包，直接从 zip 里抽 content.json/manifest.json 的关键数字。"""
    if not INTAKE_CODE_RE.match(code):
        return JSONResponse({"error": "链接无效"}, status_code=404)
    zf_path, _ = _intake_paths(code)
    side = _intake_sidecar(code)
    if not zf_path.is_file():
        if side.get("claimed") and side.get("project_id"):
            return {"claimed": True, "projectId": side["project_id"]}
        return JSONResponse({"error": "链接已失效（素材包 24 小时内有效）"}, status_code=404)
    out = {"claimed": False, "file": side.get("file") or "bundle.zip",
           "created": side.get("created"),
           "expiresAt": (side.get("created") or 0) + INTAKE_TTL_SECONDS}
    try:
        with zipfile.ZipFile(zf_path) as zf:
            content = json.loads(zf.read("content.json").decode("utf-8"))
            script = str(content.get("script") or "")
            out.update({"title": content.get("title") or out["file"],
                        "scriptChars": len(script), "scriptPreview": script[:400],
                        "estSeconds": round(len(script) / 6)})
            try:
                assets = json.loads(zf.read("manifest.json").decode("utf-8")).get("assets", [])
                out["images"] = sum(1 for a in assets if a.get("kind") == "image")
                out["videos"] = sum(1 for a in assets if a.get("kind") == "video")
            except Exception:  # noqa: BLE001 - manifest 缺失/损坏只影响计数
                pass
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "素材包内容读取失败"}, status_code=400)
    return out


@app.post("/api/intake/{code}/claim")
def intake_claim(code: str, request: Request):
    """认领：把包解进工作区、登记归属、建好项目并挂上，一次顶「上传 + 建项目 + 挂包」。

    要登录（开放模式本机自用除外）：渲染是账号行为，包认领后跟着账号走。
    """
    if not INTAKE_CODE_RE.match(code):
        return JSONResponse({"error": "链接无效"}, status_code=404)
    zf_path, side_path = _intake_paths(code)
    if not zf_path.is_file():
        side = _intake_sidecar(code)
        if side.get("project_id"):
            return JSONResponse({"error": "这个素材包已被导入过了", "projectId": side["project_id"]},
                                status_code=409)
        return JSONResponse({"error": "链接已失效（素材包 24 小时内有效）"}, status_code=404)
    email = _session_email(request)
    if not email and not _open_mode():
        return JSONResponse({"error": "先登录或注册，再导入素材包"}, status_code=401)
    side = _intake_sidecar(code)
    orig_name = Path(_fix_mojibake_name(side.get("file") or "bundle.zip")).stem or "bundle"
    name = re.sub(r'[\\/:*?"<>|]', "", orig_name).strip() or "bundle"
    dest = WORKSPACES / name
    i = 1
    while dest.exists():
        dest = WORKSPACES / f"{name}-{i}"
        i += 1
    dest.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zf_path) as zf:
            _safe_extract(zf, dest)
    except (zipfile.BadZipFile, ValueError) as e:
        shutil.rmtree(dest, ignore_errors=True)
        return JSONResponse({"error": f"素材包无效：{e}"}, status_code=400)
    if not (dest / "content.json").is_file():
        shutil.rmtree(dest, ignore_errors=True)
        return JSONResponse({"error": "zip 里没有 content.json，不是有效的素材包"}, status_code=400)
    meta = _bundles_meta()
    meta[dest.name] = {"owner": email, "created": time.strftime("%Y/%m/%d %H:%M")}
    _bundles_meta_save(meta)
    with _LOCK:
        reg = _reg()
        pid = uuid.uuid4().hex[:12]
        reg["projects"].append({"project_id": pid, "title": dest.name, "bundle": dest.name,
                                "created": time.strftime("%Y/%m/%d"), "renders": [],
                                "owner": email})
        _reg_save(reg)
    side["claimed"] = True
    side["claimed_at"] = time.time()
    side["project_id"] = pid
    side_path.write_text(json.dumps(side, ensure_ascii=False), encoding="utf-8")
    zf_path.unlink(missing_ok=True)
    return {"name": dest.name, "project_id": pid, "title": dest.name}


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
                if j.get("project_id") == pid and j.get("stage") not in ("done", "failed", "cancelled"):
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
        _PENDING[job_id] = body
        _PREP_WAIT.append(job_id)
        _PREP_CV.notify()

    def _tick():
        # 兜底：真实上报缺位时按渐近曲线缓慢推进，避免进度条看起来卡死
        while True:
            time.sleep(3)
            with _LOCK:
                j = JOBS.get(job_id)
                if j is None or j["stage"] in ("done", "failed", "cancelled"):
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
            if item["stage"] in ("queued", "prepped"):
                ahead = _queue_ahead(jid)
                if item["stage"] == "prepped":
                    item["detail"] = ("排队渲染中 · 前面还有 %d 条" % ahead) if ahead else "马上开始渲染"
                else:
                    item["detail"] = ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "马上开始"
                item["queued_pos"] = ahead
            items.append(item)
    active = [i for i in items if i["stage"] not in ("done", "failed", "cancelled")]
    finished = sorted((i for i in items if i["stage"] in ("done", "failed", "cancelled")),
                      key=lambda x: x.get("t0") or 0, reverse=True)[:8]
    return {"concurrency": _RENDER_CONCURRENCY, "active": active, "recent": finished}


@app.get("/api/job/{job_id}")
def job_status(job_id: str, request: Request):
    j = JOBS.get(job_id)
    if j is None or not _job_visible(j, request):
        return {"stage": "unknown"}   # 不存在与无权同形，不泄露任务存在性
    out = dict(j)
    out.pop("cancel", None)           # 内部旗子不外泄
    if out.get("stage") in ("queued", "prepped"):
        with _LOCK:
            ahead = _queue_ahead(job_id)
        out["queued_pos"] = ahead
        if out.get("stage") == "prepped":
            out["detail"] = ("排队渲染中 · 前面还有 %d 条" % ahead) if ahead else "马上开始渲染"
        else:
            out["detail"] = ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "马上开始"
    t0 = out.get("t0")
    # 跑完/失败后冻结耗时，否则"已用"会一直涨（回来再看变成几十小时）
    out["elapsed"] = int((out.get("t_end") or time.time()) - t0) if t0 else None
    # 分镜剧照（渲染开始前先拍好，渲染中陆续可见）
    stills = sorted(OUTPUTS.glob(f"{job_id}-still-*.jpg")) if OUTPUTS.is_dir() else []
    out["stills"] = [f"/still/{p.name}" for p in stills]
    return out


@app.post("/api/job/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    """停止任务。排队中的直接移出队列即刻生效；已经在干活的举旗子，
    由渲染轮询循环（1 秒一查，杀进程树）或下一个阶段边界接住。"""
    with _LOCK:
        j = JOBS.get(job_id)
        if j is None or not _job_visible(j, request):
            return JSONResponse({"error": "任务不存在"}, status_code=404)
        if j.get("stage") in ("done", "failed", "cancelled"):
            return {"ok": True, "stage": j["stage"]}
        stage = j.get("stage")
        before = len(_PREP_WAIT)
        _PREP_WAIT[:] = [x for x in _PREP_WAIT if x != job_id]
        dequeued = len(_PREP_WAIT) < before
        rbefore = len(_RENDER_WAIT)
        _RENDER_WAIT[:] = [e for e in _RENDER_WAIT if e["job"] != job_id]
        dequeued = dequeued or len(_RENDER_WAIT) < rbefore
        j["cancel"] = True
        if dequeued:
            _PENDING.pop(job_id, None)
        _jobs_save()
    if dequeued:
        _mark_cancelled(job_id)
        return {"ok": True, "stage": "cancelled"}
    return {"ok": True, "stage": stage}


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


def _cleanup_work_dir(work_dir) -> None:
    """任务级工作目录用完即删（TTS 缓存在共享目录 work/_tts/ 下，不受影响）。"""
    try:
        shutil.rmtree(Path(work_dir), ignore_errors=True)
    except Exception:
        pass


def _mark_failed(job_id: str, err) -> None:
    with _LOCK:
        j = JOBS.get(job_id)
        if j and j.get("stage") not in ("done", "failed", "cancelled"):
            j.update(stage="failed", stage8=8, error=str(err)[-800:], t_end=time.time())
            _jobs_save()


def _mark_cancelled(job_id: str) -> None:
    with _LOCK:
        j = JOBS.get(job_id)
        if j and j.get("stage") not in ("done", "failed", "cancelled"):
            j.update(stage="cancelled", stage8=8, error=None,
                     detail="已停止", t_end=time.time())
            _jobs_save()


def _cancel_requested(job_id: str) -> bool:
    """取消旗子：渲染循环每秒读一次（dict.get 原子，不必拿锁）。"""
    j = JOBS.get(job_id)
    return bool(j and j.get("cancel"))


def _progress_reporter(job_id: str):
    """阶段进度上报：把流水线的真实阶段映射到 8 段进度条。"""
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
    return progress


def _prep_job(job_id: str, body: dict) -> None:
    """预备阶段：配音/分镜/版式/剧照——全是等外部 API 的活，不占渲染灶台。"""
    from . import cli
    progress = _progress_reporter(job_id)
    try:
        if _cancel_requested(job_id):
            raise JobCancelled("任务已被停止")
        # 入参先过安全校验（素材包目录），不合法直接把任务标记失败
        # 试玩任务由 /api/try 给出已经校验过的绝对路径；其余任务一律只认工作区里的包名
        if body.get("try") and body.get("try_bundle_dir"):
            bundle_dir = Path(body["try_bundle_dir"]).resolve()
            if not (bundle_dir / "content.json").is_file():
                raise ValueError("试玩素材包缺失")
        else:
            bundle_dir = _resolve_bundle(body["bundle"])
        # 工作目录按任务隔离：同一素材包多任务并发时互不踩（TTS 缓存仍在共享目录）
        work_dir = config.WORK / f"{bundle_dir.name}--{job_id}"
        with _LOCK:
            body["_prep"] = {"work_dir": str(work_dir), "bundle_dir": str(bundle_dir)}
        cli.build_prep(bundle_dir, work_dir=work_dir,
                       voice=body.get("voice") or None,
                       rate=_normalize_rate(body.get("rate")),
                       format=body.get("format") or DEFAULT_TEMPLATE,
                       show_subtitles=bool(body.get("subtitles", True)),
                       show_sources=bool(body.get("sources", True)),
                       theme=body.get("theme") or "auto",
                       disclaimer=body.get("disclaimer"),
                       watermark=body.get("watermark", True) is not False,
                       use_llm=bool(body.get("useLlm", True)),
                       brand=body.get("brand") or None,
                       series=body.get("series") or None,
                       job_id=job_id, progress=progress)
        if _cancel_requested(job_id):
            # 备料跑完一半用户按了停止：别再把半成品送上灶台
            raise JobCancelled("任务已被停止")
        with _LOCK:
            j = JOBS.get(job_id)
            if j:
                j.update(stage="prepped", stage8=5, progress=40, t_stage=time.time(),
                         detail="配音与分镜已就绪")
            _jobs_save()
        _enqueue_render(job_id, _job_prio(body, (JOBS.get(job_id) or {}).get("owner")))
    except JobCancelled:
        with _LOCK:
            prep_meta = body.get("_prep") or {}
        if prep_meta.get("work_dir"):
            _cleanup_work_dir(prep_meta["work_dir"])
        _mark_cancelled(job_id)
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            prep_meta = body.get("_prep") or {}
        if prep_meta.get("work_dir"):
            _cleanup_work_dir(prep_meta["work_dir"])
        _mark_failed(job_id, e)


def _verify_bg(job_id: str, bundle_dir: Path, video: Path, work_dir: Path | None) -> None:
    """画面校验后台通道：抽帧 + 最多 4 次外部视觉 API，成片交付后才跑。

    以前它挂在渲染 subprocess 末尾——等网络却占着灶台名额，与双通道初衷相悖。
    现在挪到 done 之后低优先跑（限流 _VERIFY_CONCURRENCY 路），结果记进 job["verify"]
    供排查展示；顺带接管任务工作目录的清理（校验要读 work/prep.json）。
    """
    from . import cli
    try:
        with _VERIFY_SEM:
            report = cli.run_verify(bundle_dir, video, work_dir=work_dir)
        with _LOCK:
            j = JOBS.get(job_id)
            if j:
                j["verify"] = {k: report.get(k) for k in ("ok", "errors", "warnings")}
                _jobs_save()
    except Exception as exc:  # noqa: BLE001
        print(f"verify skipped: {exc}")
    finally:
        if work_dir:
            _cleanup_work_dir(work_dir)


def _render_job(job_id: str, body: dict) -> None:
    """渲染阶段：画面渲染/混音/封装——吃 CPU 的活，同时最多 CONCURRENCY 路。

    校验（等外部 API）不在这里跑：build_render 以 defer_verify 出灶台，
    交给 _verify_bg 后台通道，渲染位早几分钟还给下一个人。
    """
    from . import cli
    progress = _progress_reporter(job_id)
    prep_meta = body.get("_prep") or {}
    work_dir = Path(prep_meta["work_dir"]) if prep_meta.get("work_dir") else None
    out = None
    try:
        if _cancel_requested(job_id):
            raise JobCancelled("任务已被停止")
        bundle_dir = Path(prep_meta.get("bundle_dir") or _resolve_bundle(body["bundle"]))
        out = OUTPUTS / f"{bundle_dir.name}-{job_id}.mp4"
        cli.build_render(bundle_dir, out, work_dir=work_dir,
                         bgm=_resolve_bgm(body.get("bgm")),
                         renderer=body.get("renderer") or "remotion",
                         sfx=bool(body.get("sfx", True)),
                         sfx_mode=body.get("sfxMode") or ("full" if body.get("sfx", True) else "off"),
                         show_subtitles=bool(body.get("subtitles", True)),
                         show_sources=bool(body.get("sources", True)),
                         job_id=job_id, progress=progress, defer_verify=True,
                         cancel_check=lambda: _cancel_requested(job_id))
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
        if body.get("try"):
            # 试玩：降成 720p 带水印的样片给公开链接，原始大文件删掉；不备草稿资产
            small = OUTPUTS / f"try-{job_id}.mp4"
            if _downscale_720(out, small):
                with _LOCK:
                    JOBS[job_id]["try_video"] = str(small)
                out.unlink(missing_ok=True)
                _sweep_try_files()
                threading.Thread(target=_verify_bg, args=(job_id, bundle_dir, small, work_dir),
                                 daemon=True).start()
                work_dir = None   # 清理权已交给校验通道
            else:
                _mark_failed(job_id, "样片转码失败，请稍后再试")
        else:
            # 成片已经交付，接着在后台把剪映草稿资产备好——用户走到导出页时通常已就绪，
            # 点「一键导入剪映」秒装，不用再等 1-2 分钟
            threading.Thread(target=_prebuild_draft, args=(Path(out),), daemon=True).start()
            threading.Thread(target=_verify_bg, args=(job_id, bundle_dir, out, work_dir),
                             daemon=True).start()
            work_dir = None       # 清理权已交给校验通道
    except JobCancelled:
        # 渲染循环杀掉了 Remotion 进程树后抛上来；半成品随 work_dir 一起清
        if out is not None:
            out.unlink(missing_ok=True)
        _mark_cancelled(job_id)
    except Exception as e:  # noqa: BLE001
        _mark_failed(job_id, e)
    finally:
        if work_dir:
            _cleanup_work_dir(work_dir)


def _prep_worker() -> None:
    """预备通道消费者：同时最多 _PREP_CONCURRENCY 路在备料。"""
    while True:
        with _LOCK:
            while not _PREP_WAIT:
                _PREP_CV.wait()
            job_id = _PREP_WAIT.pop(0)
        body = _PENDING.get(job_id) or {}
        try:
            _prep_job(job_id, body)
        except Exception as exc:  # 队列消费者绝不能死
            print(f"prep worker error: {exc}")
            _mark_failed(job_id, exc)


def _render_worker() -> None:
    """渲染灶台消费者：同时最多 _RENDER_CONCURRENCY 路在跑；付费任务优先。"""
    while True:
        with _LOCK:
            while not _RENDER_WAIT:
                _RENDER_CV.wait()
            best = min(_RENDER_WAIT, key=lambda e: (-e["prio"], e["seq"]))
            _RENDER_WAIT.remove(best)
        job_id = best["job"]
        body = _PENDING.get(job_id) or {}
        try:
            _render_job(job_id, body)
        except Exception as exc:
            print(f"render worker error: {exc}")
            _mark_failed(job_id, exc)


for _i in range(_PREP_CONCURRENCY):
    threading.Thread(target=_prep_worker, daemon=True).start()
for _i in range(_RENDER_CONCURRENCY):
    threading.Thread(target=_render_worker, daemon=True).start()


def _intake_sweeper() -> None:
    """定期清掉过期的待认领素材包（Agent 直投，24 小时无人认领即删）。"""
    while True:
        time.sleep(1800)
        try:
            _sweep_intakes()
        except Exception as exc:  # 清扫线程绝不能死
            print(f"intake sweeper error: {exc}")


threading.Thread(target=_intake_sweeper, daemon=True).start()


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
