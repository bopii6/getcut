"""videogen 本地可视化工作台后端。

    python -m videogen.server     # http://localhost:8600

聚焦视频生成：素材包选择/上传 -> 内容确认 -> 渲染配置 -> 生成与成片。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac as _hmac
import html
import io
import ipaddress
import json
import math
import os
import shutil
import re
import stat
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from . import agenthub, auth, config, cos_store, legal, licenses, preview, safestore, version, voice_clone
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
JOBS_FILE = Path(config.JOBS_FILE)
REG = Path(config.REGISTRY_FILE)
# 全局锁：JOBS / registry / 渲染工作目录都是共享可变状态，串行化写操作
_LOCK = threading.RLock()
# 双通道流水线：
#   prep 通道 —— 配音/分镜/版式（等外部 API 为主），多路并行，不占渲染力
#   渲染通道 —— 挂单等成片台交回 + ffmpeg 混音封装；画面渲染不在这台机器上
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
#   草稿备料 —— 剪映草稿要切每镜素材与逐句配音（一串 ffmpeg），默认只留 1 路细水长流
_VERIFY_CONCURRENCY = max(1, int(os.environ.get("VIDEOGEN_VERIFY_CONCURRENCY", "2")))
_DRAFT_CONCURRENCY = max(1, int(os.environ.get("VIDEOGEN_DRAFT_CONCURRENCY", "1")))
_VERIFY_SEM = threading.Semaphore(_VERIFY_CONCURRENCY)
_DRAFT_SEM = threading.Semaphore(_DRAFT_CONCURRENCY)

# 渲染全部在用户本机跑（2026-09-20 拍板，不做云端渲染备选）：渲染灶台线程
# 只负责「挂单等成片台领走 + 等带声成片交回」，画面渲染与混音都发生在用户
# 自己的浏览器里（协议见 agenthub.py 模块注释）。灶台线程数因此可以
# 放开——每个线程只是在等 IO，不再吃主机 CPU/内存。
_RENDER_STAGE_WORKERS = max(1, int(os.environ.get("VIDEOGEN_RENDER_STAGES", "6") or "6"))

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


# 限流与额度都按 IP 记，所以"IP 从哪来"必须先说清楚：
# XFF 的第一段是**客户端自己写上来**的，直接信就等于"谁都能换一张新脸"。
# 只有直连来源本身就是可信代理时，XFF 才是可信的 —— 生产的接法是 Caddy 与容器
# 同机（peer 127.0.0.1），这时 XFF 第一段是真客户 IP。
# 仓库 docker-compose 曾把 8600 直接映射到公网，那种接法下 peer 就是公网 IP，
# 一律不认 XFF。（peer 不是 IP 的只有测试桩，那种情况下照旧认，便于模拟多客户。）
# 哪些"直连来源"可以替我们说话（即它是反代，XFF 第一段才是真客户 IP）。
# 不图省事用 ipaddress.is_private：那把 TEST-NET、192.0.2/24 这类文档段也算"内网"，
# 拿 203.0.113.7 当客户 IP 的测试就会假绿。这里只列真会出现代理的段。
_PROXY_NETS = tuple(ipaddress.ip_network(n) for n in
                    ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                     "169.254.0.0/16", "::1/128", "fe80::/10"))


def _peer_is_proxy(peer: str) -> bool:
    if os.environ.get("VIDEOGEN_TRUST_PROXY_HEADERS") == "1":
        return True
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return True          # 不是 IP 形状：测试桩/嵌入调用，退回可信
    return any(ip.version == net.version and ip in net for net in _PROXY_NETS)


def _client_ip(request: Request) -> str:
    peer = (request.client.host if request.client else "") or ""
    if _peer_is_proxy(peer):
        fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if fwd:
            return fwd
    return peer or "?"


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
    ok, why, issued = try_topics.guard(WORKSPACES, ip, cookie)
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
    # 记账已在 guard 里做完（判定与写账本同一把锁，别拆成两步）
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
_PUBLIC_PATHS = {"/", "/index.html", "/studio", "/healthz", "/api/templates",
                 "/api/auth/status", "/api/auth/login", "/api/auth/register",
                 "/api/auth/send-code", "/api/auth/reset-code", "/api/auth/reset",
                 "/api/pricing", "/api/sample-bundle",
                 # 三页法定文本必须匿名可读：客户在付款前就要能看到，
                 # 而且支付通道/应用市场抽查时"登录后可见"不算提供
                 "/privacy", "/terms", "/refund"}


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
            or path.startswith("/api/jianying/pull")
            # 成片台外壳：未登录也要能打开这页看到「登录/注册」，页面里所有
            # 数据接口照旧要会话。放行的只是 HTML/JS 壳，不含任何用户数据。
            or path.startswith("/poc/"))


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
    # 归属表读坏了不能当"谁都不属于"：那样下一次保存就把所有素材包的归属冲没了
    data = safestore.read_json(BUNDLES_META, default={"bundles": {}},
                               shape=lambda d: isinstance(d.get("bundles"), dict))
    return data.get("bundles", {})


def _bundles_meta_save(meta: dict) -> None:
    try:
        safestore.write_json(BUNDLES_META, {"bundles": meta},
                             count=lambda d: len(d.get("bundles") or {}))
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
    if _open_mode():
        return True          # 开放模式（本机自用，需显式开）
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
    if _open_mode():
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
    if _open_mode():
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


def _agent_job_ok(job_id: str, request: Request):
    """成片台系接口的统一放行：任务得是调用者自己的（管理员与开放模式除外）。

    身份取 `_agent_identity` —— 成片台有两条通道：浏览器带会话 cookie，或用
    /api/agent/login 换到的设备令牌。只认 cookie 会把令牌那条正路误伤成 403。
    设备名是客户端自己填的，不能当身份凭证，它只用来挡同一账号下两个浏览器抢单。
    返回 None 表示放行；否则把返回的响应直接发给调用方。
    """
    ident = _agent_identity(request)
    if ident is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    if ident in ("__admin__", "__open__") or auth.is_admin(ident):
        # 管理员本来就能看到全站任务与归属（_is_adminish），放行不算多给能力；
        # 客户单卡住时站长得能替他把这一步做完。以前只认全局令牌那条，
        # 管理员自己的会话会被当成"别人"挡在 403，和上面这句注释说的不是一回事。
        return None
    with _LOCK:
        j = JOBS.get(str(job_id))
        if j is None:
            owner = None
        elif j.get("try"):
            return None                      # 试玩样片本就是公开引流物
        elif j.get("owner") is not None:
            owner = j["owner"]
        else:                                # 老任务没记 owner，退到项目归属
            p = next((x for x in _reg()["projects"]
                      if x["project_id"] == j.get("project_id")), None)
            owner = (p or {}).get("owner")
    if owner != ident:
        return JSONResponse({"error": "任务不属于你"}, status_code=403)
    return None


def _request_authed(request: Request) -> bool:
    tok = (request.headers.get("x-agent-token") or "").strip()
    if tok and auth.read_session(tok):
        return True            # 成片台/脚本的设备令牌（登录接口签发的长会话）
    if _token_ok(request) or _session_email(request):
        return True
    return _open_mode()                                # 开放模式（需显式开）


def _effective_email(request: Request, body_email=None) -> str | None:
    """会话优先；访问令牌是主钥匙，可代 body.email 指定的账号行事（脚本/MCP 通道）。

    令牌持有者本就 adminish（可见一切），这里只是把品牌套件/声音克隆/档位
    这些「跟账号走」的逻辑对脚本侧放开——没有令牌的光 body.email 一律无效。"""
    email = _session_email(request)
    if not email and body_email and _token_ok(request):
        return str(body_email).strip().lower()
    return email


def _open_mode() -> bool:
    """本机自用开放模式：显式开了 `VIDEOGEN_OPEN_MODE=1`、没配令牌也没建过账号。

    那个开关是关键：以前只看"没令牌 + 没账号"，而生产上状态文件读不到时这条也成立
    → 全站开门。现在默认关，掉挂载只会变成谁都进不来（报错），不是谁都进得来。
    """
    return config.open_mode_allowed() and not AUTH_TOKEN and not auth.has_users()


# ---------- 免费档每日出片额度 ----------
USAGE_FILE = Path(config.USAGE_FILE)


def _usage_load() -> dict:
    """用量账本。

    以前是 `json.loads` + `except: pass` —— 账本一旦写坏就"当谁都没用过"，
    等于给所有免费档当场重发额度，和第 8 节刚修掉的"坏文件当空库"是同一个病。
    现在走 safestore：救不回来就抛 StoreUnrecoverable，宁可这一单失败也不白送额度。
    """
    data = safestore.read_json(USAGE_FILE, default={}, shape=lambda d: isinstance(d, dict))
    return data if isinstance(data, dict) else {}


def _usage_today(email: str) -> int:
    """今天已经记了几条（只读，不动账本）。"""
    return int(((_usage_load().get(email) or {}).get(time.strftime("%Y-%m-%d")) or 0))


def _free_quota_check(email: str) -> tuple[bool, int]:
    """免费档还能不能出这一条 + 今天已用几条。判额度只读，记账留给放行之后。"""
    used = _usage_today(email)
    return used < config.FREE_DAILY_BUILDS, used


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
            safestore.write_json(USAGE_FILE, data, indent=None)
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


@app.on_event("startup")
def _purge_legacy_recordings() -> None:
    """老客户手上遗留的原始录音（`brand/sample.mp3`）开机清一次。

    这轮把留存策略定成"客户的录音用完即删、服务器上不留档"，但改了写入路径只挡住
    新用户 —— 之前存下来的那份还在 /state 里，而且每天还跟着进备份。
    """
    n = brand_kit.purge_recordings()
    if n:
        print("startup: purged %d legacy customer recording(s)" % n)


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


def _clone_worker(raw: bytes, prefix: str, base: str) -> str:
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
        # 临时目录一退，客户的原始录音就没了：服务器上不留档（见 brand.set_clone）
        # 预热试听缓存：否则用户第一次点试听要现合成（数秒），
        # 超出浏览器"点击后 5 秒内可自动播放"窗口会被拦（实测踩过）
        try:
            pf = _preview_file(voice_id)
            if not pf.exists() or pf.stat().st_size == 0:
                tts_mod.synthesize_preview(voice_id, pf, "嗨，这是你的专属声音，来听听效果。")
        except Exception:  # noqa: BLE001 - 预热失败不影响登记，试听会走现场合成
            pass
        return voice_id


@app.post("/api/voice-clone")
async def voice_clone_create(request: Request, file: UploadFile = None):
    """上传录音（webm/ogg/m4a/mp3）→ ffmpeg 转码 → 百炼声音复刻 → 存 voice_id。

    原始录音只在内存与临时目录里待一小会儿，登记完就随临时目录消失。
    """
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
        voice_id = await asyncio.to_thread(
            _clone_worker, raw, f"getcut-{brand_kit._key(email)}", base)
    except voice_clone.CloneError as e:
        code = 400 if "录音转换失败" in str(e) or "ffmpeg" in str(e) else 502
        return JSONResponse({"error": str(e)}, status_code=code)
    brand_kit.set_clone(email, voice_id)
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


def _malformed_path(request: Request) -> bool:
    """路径里带 NUL（%00 解码而来）就不是路径了。

    pathlib 遇到嵌入空字节直接抛 ValueError，而带文件名参数的接口全是公开的
    （/poc/ /fonts/ /templates/ /api/bgm/ /try/）：匿名访客一个请求就能在服务端
    打出整段 traceback。在门口拦一次，胜过在五个取文件的接口各写一遍。
    """
    if "\x00" in request.url.path:
        return True
    raw = request.scope.get("raw_path") or b""
    return isinstance(raw, bytes) and b"%00" in raw.lower()


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    if _malformed_path(request):
        return JSONResponse({"error": "not found"}, status_code=400)
    if not _is_public(request.url.path) and not _request_authed(request):
        return JSONResponse({"error": "未登录"}, status_code=401)
    return await call_next(request)


# ---------- 响应头：缓存策略 + 基础安全头 ----------
# 治三件事：
#  1. 回访重拉 —— 以前一个 Cache-Control 都没设，浏览器每次进工作台都要把那份大 HTML
#     整页重下一遍，而这台服务器出网只有 3Mbps。HTML 走「必须回源校验 + 弱 ETag」，
#     内容没变就 304（见 _page）；稳定资源给短 max-age。
#  2. 隐私 —— 凡是带客户数据的路径（素材、任务、成片、账号）一律 no-store：
#     共享缓存（公司代理 / CDN / 别人机器上的浏览器磁盘）留下别人的口播稿和成片不可接受。
#     默认值就是 no-store，新加路由忘了分类也不会把客户数据放进缓存。
#  3. 基础安全头 —— nosniff 防 MIME 嗅探；防点击劫持必须用 SAMEORIGIN / frame-ancestors 'self'，
#     **不能写 DENY**：工作台首页本身就是用 iframe 打开 /poc/ 成片台的（index.html:1153），
#     写 DENY 等于把自己那条正路挡死。

_NO_STORE_PREFIXES = ("/api", "/media", "/agent-media", "/outputs", "/try/", "/vc-src/")
# /studio 与 /i/ 只是同一份 SPA 外壳（客户数据都走 /api，已 no-store），
# 它们要的是「必须回源校验 + ETag」：内容没变回 304，省的是整页 764KB。
_LONG_CACHE_PREFIXES = ("/fonts/",)              # 文件名稳定、体积大
# 成片台自己的代码包：文件名不带内容哈希（bundle.js 永远是这个名字）。
# 给它 max-age 等于每次部署后一小时内客户仍在跑旧程序 —— 修好的 bug 在服务器上、
# 不在客户屏幕上（2026-09-21 就是这么被将了一军：红字明明删掉了，客户截图里还在）。
# no-cache 不是"不许缓存"，是"每次回源校验"：没变就 304，几个字节。
_APP_CODE_PREFIXES = ("/poc/",)
_SHORT_CACHE_SUFFIXES = (".js", ".css", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico",
                         ".woff2", ".mp3", ".mp4", ".wav")   # 产物名不带内容哈希，只给 1 小时


def _cache_control(path: str) -> str:
    if path.startswith(_NO_STORE_PREFIXES):
        return "no-store"
    if path.startswith(_APP_CODE_PREFIXES):
        return "no-cache"
    if path.startswith(_LONG_CACHE_PREFIXES):
        return "public, max-age=604800"          # 7 天
    if path.endswith(_SHORT_CACHE_SUFFIXES):
        return "public, max-age=3600"            # 1 小时：改名不及时也不会长期看到旧页
    return "no-cache"                            # HTML 与没分类的：必须回源校验


@app.middleware("http")
async def _response_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("x-content-type-options", "nosniff")
    h.setdefault("x-frame-options", "SAMEORIGIN")
    h.setdefault("content-security-policy", "frame-ancestors 'self'")
    h.setdefault("referrer-policy", "same-origin")
    if request.headers.get("x-forwarded-proto") == "https":
        # 只在确实走了 https 的那次响应上承诺，免得 http 环境下给出无效头
        h.setdefault("strict-transport-security", "max-age=15552000")
    h["cache-control"] = ("no-store" if response.status_code >= 400
                          else _cache_control(request.url.path))
    return response


def _etag_of(body: str) -> str:
    return 'W/"%s"' % hashlib.sha1(body.encode("utf-8")).hexdigest()[:20]


def _page(request: Request, body: str) -> Response:
    """大 HTML 一律走这里：配弱 ETag，命中就回 304，浏览器少下一整页。"""
    tag = _etag_of(body)
    if any(t.strip() == tag for t in (request.headers.get("if-none-match") or "").split(",")):
        return Response(status_code=304, headers={"etag": tag, "cache-control": "no-cache"})
    return HTMLResponse(body, headers={"etag": tag, "cache-control": "no-cache"})


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
    """登录/注册页初始化用（公开）。

    `open` 一并说出来：前端曾自己用"没令牌 + 没账号"猜开放模式，而 _open_mode 还要求
    显式 VIDEOGEN_OPEN_MODE=1 —— 猜错的结果是访客一进成片台就撞 401、落地页糊一屏红字。
    """
    return {"smtp": auth.smtp_ready(), "dev_email": config.DEV_EMAIL_FALLBACK,
            "token_auth": bool(AUTH_TOKEN), "locked": auth.has_users(),
            "open": _open_mode()}


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
    """注册第二步：邮箱 + 验证码 + 密码。管理员只由 `VIDEOGEN_ADMIN_EMAILS` 白名单决定。"""
    email = body.get("email", "")
    if not auth.check_code(email, body.get("code", "")):
        return JSONResponse({"error": "验证码不对或已过期"}, status_code=400)
    # 管理员只认 VIDEOGEN_ADMIN_EMAILS 白名单；库里一个账号都没有也**不会**送人管理员，
    # 否则"账号文件丢了"就等于"最高权限重新待发"（见 config.ADMIN_EMAILS 上方注释）。
    # body 里传什么都不算，role 只由服务端按邮箱决定。
    role = "admin" if str(email).strip().lower() in config.ADMIN_EMAILS else "user"
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
    ip = _client_ip(request)
    allowed, left = auth.login_can_try(ip, email)
    if not allowed:
        # 只回 429，不再跑哈希：挡在门外就没必要替对方做 PBKDF2（那正是他要的开销）
        return JSONResponse({"error": auth.login_blocked_left(left)}, status_code=429)
    if not auth.verify_login(email, body.get("password", "")):
        auth.login_failed(ip, email)
        time.sleep(0.6)   # 拖慢暴力尝试
        return JSONResponse({"error": "邮箱或密码不对"}, status_code=401)
    auth.login_succeeded(ip, email)
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



# ---------- 三页法定文本（公开，无需登录） ----------
# 与代码逐条对齐：留存数字来自 legal.RETENTION，改数字只改那一处，
# 免得出现"文案说 30 天、代码清 90 天"这种被投诉一句就翻车的写法。
for _kind in ("privacy", "terms", "refund"):

    def _legal_page(request: Request, _k: str = _kind) -> Response:
        return _page(request, legal.page(_k))

    _legal_page.__name__ = "legal_" + _kind
    app.get("/" + _kind, response_class=HTMLResponse)(_legal_page)


def _usage_drop(email: str) -> None:
    """注销时把用量账本里这个人的键去掉（额度是跟账号走的，账号没了不留）。"""
    with _LOCK:
        data = _usage_load()
        if email in data:
            data.pop(email, None)
            try:
                safestore.write_json(USAGE_FILE, data, indent=None)
            except OSError:
                pass


def _purge_account(email: str) -> dict:
    """删掉这个人名下的一切，并回报删了哪些、各多少。

    每类都单独数一遍是有用的：客户问"你们到底删了什么"，我们答得出；
    答不出来的"我们已彻底删除"，在投诉与诉讼里等于没删。
    素材包目录只删归属明确是自己的 —— 无主的历史包可能是别人的，不能顺手带走。
    """
    out: dict = {"bundles": [], "projects": 0, "jobs": 0, "cos": 0, "brand": False}
    meta = _bundles_meta()
    for name, info in list(meta.items()):
        if (info or {}).get("owner") != email:
            continue
        d = (WORKSPACES / name).resolve()
        if WORKSPACES.resolve() in d.parents and d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
        meta.pop(name, None)
        out["bundles"].append(name)
    _bundles_meta_save(meta)

    with _LOCK:
        reg = _reg()
        mine = [x for x in reg["projects"] if x.get("owner") == email]
        reg["projects"] = [x for x in reg["projects"] if x.get("owner") != email]
        _reg_save(reg)
    out["projects"] = len(mine)

    with _LOCK:
        for jid, j in list(JOBS.items()):
            if j.get("owner") != email:
                continue
            v = j.get("video")
            if v and Path(v).is_file():
                Path(v).unlink(missing_ok=True)
            key = j.get("cos_key")
            if key and cos_store.enabled():
                try:
                    cos_store.drop(key)
                    out["cos"] += 1
                except Exception as exc:  # noqa: BLE001 - 云上删不掉要喊，但别挡住注销
                    print("cos drop failed on purge %s: %s" % (key, exc))
            JOBS.pop(jid, None)
            out["jobs"] += 1
        _jobs_save()

    vid = brand_kit.clear_clone(email)
    if vid:
        try:
            voice_clone.remove(vid)
        except Exception as exc:  # noqa: BLE001
            print("voice clone remove failed: %s" % exc)
    bdir = brand_kit._dir(email)
    if bdir.is_dir():
        shutil.rmtree(bdir, ignore_errors=True)
        out["brand"] = True
    return out


@app.post("/api/auth/delete-account")
def auth_delete_account(body: dict, request: Request, response: Response):
    """注销账号：本人登录 + 再输一次密码确认。

    要密码是因为只凭登录状态就能删掉全部作品，破坏力太大（共享电脑、
    被看到的 cookie 都够）。删完所有设备的通行证立刻失效，卡密记录去身份保留，
    因为财务要能对账 —— 这两条都写在隐私政策里，代码与文案必须一致。
    """
    email = _session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    if not body.get("confirm"):
        return JSONResponse({"error": "请勾选确认：注销会删除素材包、成片与品牌套装，无法恢复"},
                            status_code=400)
    if not auth.verify_login(email, str(body.get("password") or "")):
        return JSONResponse({"error": "密码不对，注销没有生效"}, status_code=403)
    deleted = _purge_account(email)
    ok, why = auth.delete_user(email)
    if not ok:
        return JSONResponse({"error": why or "注销失败"}, status_code=400)
    anonymized = licenses.anonymize(email)
    _usage_drop(email)
    auth.revoke_all_sessions(email)
    resp = JSONResponse({"ok": True, "deleted": deleted, "license_records_anonymized": anonymized})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    print("account deleted: %s 素材包%d 项目%d 任务%d 云成片%d" % (
        email, len(deleted["bundles"]), deleted["projects"], deleted["jobs"], deleted["cos"]))
    return resp


@app.get("/api/auth/sessions")
def auth_sessions(request: Request):
    """我这个账号现在在哪些设备上登录着。"""
    email = _session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    return {"sessions": auth.list_sessions(email)}


@app.post("/api/auth/session/revoke")
def auth_session_revoke(body: dict, request: Request):
    """撕掉指定那一台的通行证 —— 以前只能换全局密钥＝所有人一起掉线。"""
    email = _session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    sid = str(body.get("sid") or "").strip()
    if not sid:
        return JSONResponse({"error": "要踢哪一台：缺少会话标识"}, status_code=400)
    if not auth.revoke_session(email, sid):
        # 别人的 sid 与不存在的 sid 回同一个码：不能拿它探测"这个会话在不在"
        return JSONResponse({"error": "这台设备已经不在线了"}, status_code=404)
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
        # 发一批记一笔：谁发的、什么时候、几片、什么档、备注。
        # 没有这行流水，直播间卖完货对不上账时我们连"这张码是我给的"都证不了。
        licenses.log_issue(_session_email(request) or "token",
                           str(body.get("tier") or ""), codes, str(body.get("note") or ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"codes": codes, "stats": licenses.stats()}


# ---------- 试听（B5）----------

@app.get("/api/admin/licenses/audit")
def admin_license_audit(request: Request, limit: int = 100):
    """卡密发放流水（最近若干条，倒序）。只有管理员能看。"""
    if not _is_adminish(request):
        return JSONResponse({"error": "只有管理员能看"}, status_code=403)
    return {"rows": licenses.list_audit(max(1, min(int(limit or 100), 1000)))}


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
    elif voice not in tts_mod.load_voices():
        # 目录外的音色 id 只认调用者自己克隆的那一个：光知道别人的 id 借不到他的声音
        email = _session_email(request)
        c = brand_kit.clone_info(email) if email else None
        if not c or c.get("voice_id") != voice:
            return JSONResponse({"error": "音色不存在"}, status_code=404)
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
        safestore.write_json(JOBS_FILE, JOBS, indent=None)
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
    return safestore.read_json(REG, default={"projects": []},
                               shape=lambda d: isinstance(d.get("projects"), list))


def _reg_save(reg: dict) -> None:
    safestore.write_json(REG, reg, count=lambda d: len(d.get("projects") or []))


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
def index(request: Request) -> Response:
    """首页就是成片台本体：拖包 → 生成 → 取片一屏走完，不必先进工作台找入口。
    静态资源仍在 /poc/ 下，靠 <base> 让页面里的相对路径照旧解析。"""
    page = _poc_html()
    if isinstance(page, JSONResponse):
        return page
    return _page(request, page.replace("<head>", '<head><base href="/poc/">', 1))


@app.get("/studio", response_class=HTMLResponse)
@app.get("/studio/", response_class=HTMLResponse)
def studio(request: Request) -> Response:
    """工作台：作品库与历史项目。主路径已在成片台，这里退成后台。"""
    return _page(request, _inject_browser_export((STATIC / "index.html").read_text(encoding="utf-8")))


@app.get("/i/{code}", response_class=HTMLResponse)
def intake_page(code: str, request: Request) -> Response:
    """Agent 直投短链：与 / 同一份 SPA，前端按路径进入「素材包已送达」落地页。"""
    return _page(request, _inject_browser_export((STATIC / "index.html").read_text(encoding="utf-8")))


# 成片台悬浮组件：有任务在等成片台时，任务页右下角浮出按钮，
# 点击全屏打开 /poc/ 成片台（纯浏览器渲染合成），完成后 postMessage 通知收起。
_BROWSER_EXPORT_WIDGET = """
<script>
(function(){
  if (window.__gcExportWidget) return; window.__gcExportWidget = 1;
  var wrap = null;
  function waitingCount(){
    return fetch('/api/jobs', {credentials:'same-origin'})
      .then(function(r){ return r.json(); })
      .then(function(d){
        var a = (d && d.active) || [];
        return a.filter(function(j){
          return j.stage === 'render' && /等待成片台/.test(j.detail || '');
        }).length;
      }).catch(function(){ return 0; });
  }
  function show(n){
    if (!wrap){
      wrap = document.createElement('div');
      wrap.style.cssText = 'position:fixed;inset:0;z-index:2147483000;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;';
      var b = document.createElement('button');
      b.id = 'gc-bx-go';
      b.style.cssText = 'all:unset;cursor:pointer;background:var(--acc);color:var(--acc-ink);padding:16px 30px;border-radius:9px;font:700 18px/1.45 var(--sans);text-align:center;box-shadow:var(--sh-2);';
      b.addEventListener('click', openFrame);
      wrap.appendChild(b);
      document.body.appendChild(wrap);
    }
    wrap.firstChild.innerHTML = '有 ' + n + ' 条视频等你生成<br><span style=\"font-size:14px;font-weight:400;opacity:.85\">点击在你这台电脑上完成，直接出带声 MP4（每条约 1~4 分钟，期间保持本页打开）</span>';
    wrap.style.display = 'flex';
  }
  function openFrame(){
    var f = document.getElementById('gc-bx-frame');
    if (f) return;
    f = document.createElement('iframe');
    f.id = 'gc-bx-frame';
    f.src = '/poc/?agent=1&device=' + encodeURIComponent('\\u7f51\\u9875\\u6d4f\\u89c8\\u5668');
    f.allow = 'display-capture';
    f.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;border:0;z-index:2147483001;background:#111;';
    document.body.appendChild(f);
    window.addEventListener('message', function(ev){
      if (ev.data && ev.data.type === 'getcut-export-done' && f.parentNode){
        setTimeout(function(){ f.remove(); location.reload(); }, 1800);
      }
    });
  }
  function tick(){
    waitingCount().then(function(n){
      if (n > 0) openFrame();
    });
  }
  function boot(){ tick(); setInterval(tick, 5000); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
</script>"""


def _inject_browser_export(html: str) -> str:
    if "</body>" in html and "__gcExportWidget" not in html:
        return html.replace("</body>", _BROWSER_EXPORT_WIDGET + "</body>", 1)
    return html


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
    """云平台健康检查（不落盘、不触发扫描副作用）。

    这里**不再报版本号**：以前硬编码 `"version": "1.0"`，说了等于没说；
    真版本在 `/api/version`（要登录），不把精确版本暴露给匿名探针。
    """
    return {"ok": True, "jobs": len(JOBS)}


@app.get("/api/version")
def api_version():
    """线上到底是哪一版：commit + 构建时间 + 关键依赖的实际版本。

    故意留在鉴权后面（不进 _PUBLIC_PATHS）：匿名访问者不该拿到精确版本信息，
    而问这个问题的站长/排障本来就登录着；外部只需要 /healthz 那个存活信号。
    读的是**运行时真实装着的**版本，不是 requirements 里写的期望值 ——
    生产是宿主绑挂代码 + 部署时还会 pip 装包，只有问运行时才算数。
    """
    from importlib import metadata as md
    deps = {}
    for name in ("fastapi", "starlette", "pydantic", "pillow", "websockets",
                 "cos-python-sdk-v5", "edge-tts", "requests", "python-multipart"):
        try:
            deps[name] = md.version(name)
        except Exception:  # noqa: BLE001 - 装没装都要说实话
            deps[name] = "未安装"
    return {**version.info(), "deps": deps}


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
    # 预演会读包里的口播文案出分镜，所以"包存在"不够，还得是调用者自己的包
    if request is not None and not _bundle_visible(str(bundle), request):
        raise ValueError("素材包不存在")
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
    if not _bundle_visible(bundle, request):
        return JSONResponse({"error": "素材包不合法"}, status_code=400)
    return preview.build_preview_payload(pid, {"bundle": bundle})


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
        if not video.is_file() and not render.get("cos_key"):
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
# 靠它自证身份。5 分钟过期，签发前已过高级版付费墙。TTL 内允许重复取：
# 助手端第一次传输成功但自检失败重拉时（2026-09-19 深夜实测踩过），焚得太急
# 会把合法重试顶成 403；窗口短、内容固定，重放风险可忽略。
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
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                zpath = _P(td) / "draft.zip"
                jyd.build_zip(mf, video, _P(voice) if voice else None, zpath)
                data = zpath.read_bytes()
        except Exception as exc:  # noqa: BLE001 - 打包失败保留 token，助手重试还能用
            return JSONResponse({"error": f"草稿打包失败: {exc}"}, status_code=500)
        fname = f"GetCut-剪映草稿-{info['rid'][:6]}.zip"
        from urllib.parse import quote
        return Response(
            content=data, media_type="application/zip",
            headers={"Content-Disposition":
                     "attachment; filename=getcut-draft.zip; "
                     "filename*=UTF-8''{}".format(quote(fname))})
    finally:
        _drop_staged(video, staged)


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
    finally:
        _drop_staged(video, staged)


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
    """防 Zip Slip / zip 炸弹 / 符号链接逃逸：逐条校验成员路径落在 dest 内，且总量受控。

    光校验名字挡不住符号链接：`link` 与 `link/evil.txt` 两条名字各自都在 dest 内，
    解压器却会先建软链再把文件"穿过"它写到外面 —— 上传口对免费注册用户开着，
    而 /app/videogen 是从宿主机挂进来的，等于任意登录用户可写服务器代码。
    所以成员类型也要限：只收普通文件与目录。
    """
    dest = dest.resolve()
    total = 0
    for member in zf.infolist():
        total += member.file_size
        if total > MAX_EXTRACT_BYTES:
            raise ValueError("解压后体积超限")
        mode = member.external_attr >> 16
        # 只看"类型位"：0o600/0o644 这类只带权限不带类型的写法很常见（Python 自己
        # writestr 就是 0o600），当成普通文件；带类型位又不是普通文件/目录的才拒。
        if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError(f"不支持的文件类型: {member.filename}")
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


async def _read_capped(file, cap: int) -> bytes:
    """流式读上传体，超 cap 当场掐断。await file.read() 会把没限大的包整个吞进内存
    才想起查上限——公网端点一脚 10GB 的包就能把 3G 内存的小机器踹下线。"""
    buf = bytearray()
    while True:
        chunk = await file.read(8 * 1024 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > cap:
            raise ValueError("upload too large")
    return bytes(buf)


@app.post("/api/upload")
async def upload(file: UploadFile, request: Request):
    name = Path(_fix_mojibake_name(file.filename or "bundle.zip")).stem or f"bundle-{int(time.time())}"
    try:
        data = await _read_capped(file, MAX_UPLOAD_BYTES)
    except ValueError:
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
    try:
        data = await _read_capped(file, MAX_UPLOAD_BYTES)
    except ValueError:
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
def intake_claim(code: str, request: Request, body: dict = None):
    """认领：把包解进工作区、登记归属、建好项目并挂上，一次顶「上传 + 建项目 + 挂包」。

    要登录（开放模式本机自用除外；令牌主钥匙可代 body.email 指定的账号）：
    渲染是账号行为，包认领后跟着账号走。
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
    email = _effective_email(request, (body or {}).get("email"))
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
    email = _effective_email(request, body.get("email"))
    if email and not auth.is_admin(email) and auth.user_tier(email) == "free":
        body = dict(body)
        body["watermark"] = True
        allowed, used = _free_quota_check(email)
        if not allowed:
            # 被挡的这一次**不记账**：以前是先 _usage_bump 再判超限，
            # 于是被拒的尝试也一直往账本上加数，「我的」里会出现「已用 7 / 2 条」
            return JSONResponse(
                {"error": f"今天的免费额度（每天 {config.FREE_DAILY_BUILDS} 条）用完了，"
                          f"已用 {used} 条。"
                          f"¥{config.PRICES['premium']} 永久买断，不限量去水印——点右上角「升级」看看",
                 "limited": True},
                status_code=429)
        _usage_bump(email)
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
                # 等成片台领取时不再爬"假进度"——那是兜底动画，会误导用户以为在渲染
                if j.get("stage") == "render" and not j.get("render_via"):
                    j["detail"] = "等你在这台电脑上生成 · 打开成片台点「生成视频」"
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
                    item["detail"] = ("排队生成中 · 前面还有 %d 条" % ahead) if ahead else "马上开始生成"
                else:
                    item["detail"] = ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "马上开始"
                item["queued_pos"] = ahead
            items.append(item)
    active = [i for i in items if i["stage"] not in ("done", "failed", "cancelled")]
    finished = sorted((i for i in items if i["stage"] in ("done", "failed", "cancelled")),
                      key=lambda x: x.get("t0") or 0, reverse=True)[:8]
    out = {"concurrency": _RENDER_STAGE_WORKERS, "active": active, "recent": finished,
           "agent": agenthub.snapshot() if (_is_adminish(request) or _open_mode()) else None}
    return out


@app.get("/api/admin/nodes")
def admin_nodes(request: Request):
    """管理员看成片台水位：哪几台在线、队列里还有几个没领。"""
    if not _is_adminish(request):
        return JSONResponse({"error": "只有管理员能看"}, status_code=403)
    return {"enabled": True, "kind": "agent", **agenthub.snapshot()}


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
            out["detail"] = ("排队生成中 · 前面还有 %d 条" % ahead) if ahead else "马上开始生成"
        else:
            out["detail"] = ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "马上开始"
    t0 = out.get("t0")
    # 跑完/失败后冻结耗时，否则"已用"会一直涨（回来再看变成几十小时）
    out["elapsed"] = int((out.get("t_end") or time.time()) - t0) if t0 else None
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


# ---------- 浏览器成片台（Agent 协议）接口 ----------
# 成片台页面轮询这组接口领任务/下载渲染包/上报进度/交回带声成片。
# 身份三种：登录签发的设备令牌（x-agent-token，90 天）、主钥匙（x-auth-token，
# 调试/管理）、开放模式（本机自用）。成片台只领自己的任务——素材是用户自己
# 的，不能串门到别人的电脑上。

def _agent_identity(request: Request) -> str | None:
    tok = (request.headers.get("x-agent-token") or "").strip()
    if tok:
        email = auth.read_session(tok)
        if email:
            return email
    if _token_ok(request):
        return "__admin__"
    email = _session_email(request)
    if email:
        return email
    return "__open__" if _open_mode() else None


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


@app.post("/api/agent/login")
def agent_login(body: dict):
    """成片台登录：邮箱密码换 90 天设备令牌，存本机以后免输。"""
    email = str(body.get("email") or "").strip().lower()
    if not auth.verify_login(email, str(body.get("password") or "")):
        return JSONResponse({"error": "邮箱或密码不对"}, status_code=401)
    return {"token": auth.make_session(email, ttl=90 * 24 * 3600), "email": email}


@app.get("/api/agent/poll")
def agent_poll(request: Request, device: str = "", wait: int = 1):
    """长轮询领任务（服务器最多挂 25 秒）：领到就返回渲染包描述。"""
    ident = _agent_identity(request)
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
    return {"job": payload["job"], "props": payload["props"], "files": files}


@app.get("/api/agent/job/{job_id}/file")
def agent_job_file(job_id: str, request: Request, path: str = ""):
    """下载渲染包里的一个文件（只放行挂单时登记过的相对路径）。"""
    if _agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    if (denied := _agent_job_ok(job_id, request)) is not None:
        return denied
    p = agenthub.file_path(job_id, path)
    if p is None:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(p, filename=Path(path).name)


@app.post("/api/agent/job/{job_id}/progress")
def agent_job_progress(job_id: str, body: dict, request: Request, device: str = ""):
    """成片台上报进度；响应里带 cancel 旗子，让成片台知道该收手了。"""
    if _agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    if (denied := _agent_job_ok(job_id, request)) is not None:
        return denied
    return agenthub.progress(job_id, _agent_device(request, device),
                             int(body.get("pct") or 0), body.get("detail"),
                             failed=body.get("status") == "error",
                             requeue=body.get("requeue") is True,
                             voluntary=body.get("voluntary") is True)


@app.post("/api/agent/job/{job_id}/visual")
async def agent_job_visual(job_id: str, request: Request, device: str = ""):
    """成片台交回产物（默认 final=1 带声成片）：落临时名，原子转正唤醒灶台。"""
    if _agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    if (denied := _agent_job_ok(job_id, request)) is not None:
        return denied
    dev = _agent_device(request, device)
    tmp = agenthub.upload_target(job_id, dev)
    if tmp is None:
        return JSONResponse({"error": "任务不在生成中（可能已收回或取消）"},
                            status_code=410)
    crop = request.query_params.get("crop") or ""
    if crop:
        agenthub.set_crop(job_id, dev, crop)
    final = request.query_params.get("final") == "1"
    data = await request.body()
    if len(data) < 4096:
        return JSONResponse({"error": "画面轨文件异常（太小）"}, status_code=400)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(data)
    if not agenthub.deliver(job_id, dev, tmp, final=final):
        tmp.unlink(missing_ok=True)
        return JSONResponse({"error": "任务不在生成中（可能已收回或取消）"},
                            status_code=410)
    return {"ok": True}


@app.post("/api/agent/job/{job_id}/layer")
async def agent_job_layer(job_id: str, request: Request, device: str = "",
                          name: str = ""):
    """成片台交回剪映分轨图层：base.png / cards/shot_00N.png / texts.json。

    文件名过 agenthub 的白名单再拼路径（这里不接受任何客户端给的目录），
    身份认的是交片那台设备留下的凭据——图层是成片之后才陆续到的，
    任务记录那时已经摘牌。
    """
    if _agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    if (denied := _agent_job_ok(job_id, request)) is not None:
        return denied
    dst = agenthub.layer_target(job_id, _agent_device(request, device), name)
    if dst is None:
        return JSONResponse({"error": "没有等图层的那台成片台，或文件名不合法"},
                            status_code=410)
    data = await request.body()
    # 上限是防有人拿这个口往服务器塞东西；下限只挡空包——
    # 「图层缺不缺」由 draft_build.import_layers 逐张把关
    if not (1 <= len(data) <= 25 * 1024 * 1024):
        return JSONResponse({"error": "图层大小不对"}, status_code=400)
    dst.write_bytes(data)
    return {"ok": True, "bytes": len(data)}


@app.get("/api/agent/status")
def agent_status(request: Request):
    if _agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    snap = agenthub.snapshot()
    if _is_adminish(request) or _open_mode():
        return snap
    # 普通用户只看自己那几个任务：全站任务号与别人电脑的设备名不外泄
    with _LOCK:
        mine = {jid for jid, j in JOBS.items() if _job_visible(j, request)}
    jobs = [d for d in snap.get("jobs") or [] if d.get("job") in mine]
    return {"devices": [], "jobs": jobs,
            "waiting": sum(1 for d in jobs if d.get("status") == "waiting"),
            "rendering": sum(1 for d in jobs if d.get("status") == "rendering")}


BROWSERPOC_DIR = STATIC / "poc"


def _poc_html():
    """成片台首页的 HTML；没打包时给一句照着能修的话。"""
    f = BROWSERPOC_DIR / "index.html"
    if not f.is_file():
        return JSONResponse({"error": "成片台页面未打包（renderer/_tool_bundle.mjs）"},
                            status_code=404)
    return f.read_text(encoding="utf-8")



def _file_tag(target: Path) -> str:
    """文件版 ETag：改动时间 + 字节数，不读文件内容（3.7MB 的包不该为算标签整份读一遍）。"""
    st = target.stat()
    return '"%x-%x"' % (int(st.st_mtime), st.st_size)


@app.get("/poc/{rel_path:path}")
def poc_page(request: Request, rel_path: str = "index.html"):
    """浏览器成片台（web-renderer 逐帧渲染 + 浏览器内混音，产出带声 mp4）。
    同源部署，正式环境里登录用户的会话 cookie 随页面自动可用。"""
    target = (BROWSERPOC_DIR / rel_path).resolve()
    try:
        # 用真包含判断：str().startswith 会让 /poc/../隔壁目录 混进来
        inside = target.is_relative_to(BROWSERPOC_DIR.resolve())
    except (OSError, ValueError):
        inside = False
    if not inside or not target.is_file():
        html = _poc_html()
        return html if isinstance(html, JSONResponse) else HTMLResponse(html)
    # 这些文件名不带内容哈希（bundle.js 永远是这个名字），所以只能"每次回源校验"：
    # 光把 Cache-Control 改成 no-cache 会让浏览器每次重下 3.7MB（FileResponse 自己
    # 不认 If-None-Match），3Mbps 的出网带宽上就是十几秒白等 —— 304 得我们自己回。
    tag = _file_tag(target)
    if any(t.strip() == tag for t in (request.headers.get("if-none-match") or "").split(",")):
        return Response(status_code=304, headers={"etag": tag})
    return FileResponse(target, headers={"etag": tag})


@app.get("/agent-media/{job_id}/{rel_path:path}")
def agent_media(job_id: str, request: Request, rel_path: str = ""):
    """成片台直读渲染包素材：已登记文件按登记路径放行；
    fonts/ 这类模板公共资产不入渲染包，回退到 renderer/public。"""
    if _agent_identity(request) is None:
        return JSONResponse({"error": "成片台未登录"}, status_code=401)
    if (denied := _agent_job_ok(job_id, request)) is not None:
        return denied
    p = agenthub.file_path(job_id, rel_path)
    if p is None and rel_path.startswith("fonts/") and ".." not in rel_path:
        cand = Path(__file__).resolve().parent.parent / "renderer" / "public" / rel_path
        if cand.is_file():
            p = cand
    if p is None:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(p)


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
    key = (j or {}).get("cos_key")
    if key and cos_store.enabled():
        try:
            return RedirectResponse(cos_store.sign_url(key, Path(str(v)).name))
        except Exception as exc:  # noqa: BLE001 - 外存取不到就回退本地
            print("cos sign_url failed, fallback local: %s" % exc)
    if not Path(v).is_file():
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


def _cos_mark(job_id: str, key: str) -> None:
    """把 cos_key 记到任务表与项目登记上（两份都要：重启后靠 registry 找得回）。"""
    with _LOCK:
        j = JOBS.get(job_id)
        if j:
            j["cos_key"] = key
            _jobs_save()
        reg = _reg()
        for pr in reg["projects"]:
            for r in pr.get("renders") or []:
                if r.get("id") == job_id:
                    r["cos_key"] = key
        _reg_save(reg)


def _cos_archive(job_id: str, video: Path) -> None:
    """成片后台传对象存储：传成之后本地那份等画面校验跑完才删（见 _verify_bg）。

    为什么后台：30MB 上传要几秒，不该压在「点完成」这条路径上；
    为什么传成也不立刻删：画面校验要抽帧读本地这份文件。
    """
    if not cos_store.enabled() or not video.is_file():
        return

    def go():
        key = cos_store.archive(job_id, video)
        if not key:
            return
        _cos_mark(job_id, key)
        _cos_drop_local(job_id, video)
    threading.Thread(target=go, daemon=True).start()


def _cos_drop_local(job_id: str, video: Path) -> None:
    """外存有了 + 画面校验跑完了，本地这份才删；任一条件不满足就留着。"""
    with _LOCK:
        j = JOBS.get(job_id) or {}
        if not j.get("cos_key") or not j.get("verify"):
            return
    try:
        video.unlink()
    except OSError:
        pass


def _film_or_fetch(video: Path) -> tuple[Path | None, bool]:
    """本地在就用本地；本地没了但外存有，拉回一份临时件（剪映草稿、封面要真文件）。

    返回 (可用路径, 是不是外存取回的临时件)。临时件用完必须 `_drop_staged` 删掉：
    这些副本留着，40G 系统盘又会慢慢被填满，等于白做归档。
    """
    if video.is_file():
        return video, False
    if not cos_store.enabled():
        return None, False
    with _LOCK:
        reg = _reg()
        key = next((r.get("cos_key") for pr in reg["projects"] for r in (pr.get("renders") or [])
                    if r.get("file") == str(video)), None)
    if not key:
        return None, False
    tmp = OUTPUTS / video.name
    return (tmp, True) if cos_store.fetch(key, tmp) else (None, False)


def _drop_staged(video: Path | None, staged: bool) -> None:
    """删掉刚从对象存储取回的过路副本（本地原本就有的那份不动）。"""
    if staged and video is not None:
        try:
            video.unlink()
        except OSError:
            pass


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
        _cos_drop_local(job_id, video)


BROWSER_V_BOX = 1920   # 交付给浏览器的视频最长边
BROWSER_V_FPS = 30     # 交付给浏览器的视频最高帧率


def _browser_safe_video(path: str, cache_dir: Path) -> str:
    """素材视频进客户浏览器前，把「解码不起」的那一类重编成浏览器扛得住的一档：
    长边 ≤1920、帧率 ≤30、每 30 帧一个关键帧、不带音频轨与 timed-metadata 轨。

    四条各对应一个真实事故，改之前先读完：
    1. 4K 原片：一帧解码出来是 RGBA 33MB，而画面只有 1080×1920——纯白烧客户内存。
       2026-09-21 线上「华为昇腾960」那条就是渲到 32% 时把标签页顶到
       Chrome "Aw, Snap! Out of Memory"。
    2. 稀疏关键帧：随机取帧得从上一个关键帧连解到底，实测 Mixkit 素材 251 帧
       才一个关键帧。所以**只要决定重编，就顺手把关键帧插密**（-g 30）。
    3. 高帧率源（实测 50fps 的 mixkit 素材）会卡在 mediabunny 的 Extracting frame。
    4. tmcd 时间码轨同样卡首帧提取；且 ffmpeg 见输入带时间码就会自己补一条，
       所以 -write_tmcd 0 两条分支都得带（上一版只在纯剥轨那条加了，
       4K@60fps 重编出来的产物仍带着 data 轨）。

    干净的小素材**原样放行、不重编**：实测把 540p/720p 也一律重编，体积反而涨
    六成（0.8MB→1.2MB、2.2MB→3.7MB），而出网只有 3Mbps——那是拿带宽换内存，
    换错了方向。判据只认三样：带 data 轨、帧率超上限、长边超上限。
    产物按「素材名 + 大小 + mtime + 编码档」缓存在工作区持久盘（.browsersafe，
    不放 config.WORK：那是容器层，一次重新部署就清空，而挂给成片台的路径还活着），
    同一素材跨任务只编一次。"""
    p = Path(path)
    if p.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
        return path
    try:
        st = p.stat()
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,width,height,r_frame_rate",
             "-of", "csv=p=0", str(p)],
            capture_output=True, text=True, timeout=30, check=True)
        w = h = 0
        fps = 0.0
        has_data = False
        for line in probe.stdout.strip().splitlines():
            c = [x.strip() for x in line.split(",")]
            if c[0] == "data":
                has_data = True            # 音频/字幕行的宽高字段是空的
            elif c[0] == "video" and not w and len(c) > 3 and c[1] and c[2]:
                w, h = int(c[1]), int(c[2])
                num, _, den = c[3].partition("/")
                fps = int(num) / int(den or 1) if num and den != "0" else 0.0
        if not w or not (has_data or fps > BROWSER_V_FPS + 1
                         or max(w, h) > BROWSER_V_BOX):
            return path
        profile = f"b{BROWSER_V_BOX}f{BROWSER_V_FPS}"
        out = cache_dir / (f"{p.stem}.{profile}.{st.st_size}"
                           f".{int(st.st_mtime_ns)}.mp4")
        if not out.is_file():
            cache_dir.mkdir(parents=True, exist_ok=True)
            # 临时件必须以 .mp4 结尾：ffmpeg 靠后缀选封装，写成 xxx.tmp 会直接失败
            tmp = cache_dir / (out.name + ".part.mp4")
            # 只缩不放：min() 保证重编不会把小素材放大
            vf = [f"scale='min({BROWSER_V_BOX},iw)':'min({BROWSER_V_BOX},ih)'"
                  ":force_original_aspect_ratio=decrease:force_divisible_by=2"]
            if fps > BROWSER_V_FPS + 1:
                vf.insert(0, f"fps={BROWSER_V_FPS}")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(p),
                 "-map", "0:v:0", "-an", "-write_tmcd", "0",
                 "-vf", ",".join(vf),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-pix_fmt", "yuv420p",
                 "-g", str(BROWSER_V_FPS), "-keyint_min", str(BROWSER_V_FPS),
                 "-sc_threshold", "0",
                 "-movflags", "+faststart", str(tmp)],
                timeout=900, check=True)
            tmp.replace(out)
        return str(out)
    except Exception as exc:  # noqa: BLE001 - 清洗失败就用原文件，别拦渲染
        print(f"browser_safe_video({p.name}) skipped: {exc}", flush=True)
        return path


def _build_audio_package(audio: dict) -> tuple[dict, dict[str, str]]:
    """混音计划（cli.build_render 算好的 voice/bgm/sfx 事件）→ 浏览器可执行的
    {音频相对路径: 本地文件} + props.audio 元数据。

    props.audio 形如 {voice, bgm, sfx:[{t,file,vol}], durationMs}：浏览器端
    NiwoVideo 据此挂 <Audio> 层，web-renderer 逐帧渲染时一并混音进成片。
    """
    files: dict[str, str] = {}
    vp = Path(str(audio["voice"]))
    voice_rel = f"audio/voice{vp.suffix or '.mp3'}"
    files[voice_rel] = str(vp)
    bgm_rel = None
    bp = audio.get("bgm")
    if bp and Path(bp).is_file():
        bgm_rel = f"audio/bgm{Path(bp).suffix or '.mp3'}"
        files[bgm_rel] = str(Path(bp))
    sfx_meta = []
    by_file: dict[str, str] = {}
    for at_s, f, vol in (audio.get("sfx") or []):
        p = Path(str(f))
        rel = by_file.get(str(p))
        if rel is None:
            rel = f"audio/sfx{len(by_file)}{p.suffix or '.wav'}"
            by_file[str(p)] = rel
            files[rel] = str(p)
        sfx_meta.append({"t": round(float(at_s), 3), "file": rel, "vol": float(vol)})
    meta = {"voice": voice_rel, "bgm": bgm_rel, "sfx": sfx_meta,
            "durationMs": int(float(audio.get("duration_s") or 0) * 1000)}
    return meta, files


def _agent_visual(job_id: str, layers_dir: Path | None = None):
    """渲染灶台的画面渲染替身：把 props+素材+音轨挂到 agenthub，
    等用户的浏览器成片台领走渲染、把带声成片交回来。没有云端渲染备选——
    成片台不在线就一直等（这是产品形态），失联的任务由 agenthub 收回重排。

    layers_dir：剪映分轨草稿要的底板/卡片 PNG 与文字几何交回哪儿。成片交回后
    成片台还在同一个页面上接着渲，陆续写进这个目录（见 agenthub.layer_target）。

    交回的东西有两种（成片台在 /visual?final=1 里自己声明）：
    - 浏览器成片台（现行唯一链路）：已带声的完整 mp4，云端原样收下不再动刀；
    - 不带 final 的裸画面轨：只剩手工调试会走到，云端按老规矩补混音封装。
    """
    from . import remotion_render as rr

    def fn(props, out_path, progress=None, cancel_check=None, audio=None):
        with _LOCK:
            owner = (JOBS.get(job_id) or {}).get("owner")
        media, logo_path = rr.collect_remote_assets(props)
        # 素材统一改成分配的 ASCII 名：中文包名生成的媒体名不再进 URL，
        # 浏览器/Caddy/编码各种环节都再无中文路径隐患
        rename: dict[str, str] = {}
        files: dict[str, str] = {}
        for idx, name in enumerate(sorted(media)):
            src = _browser_safe_video(str(media[name]),
                                      config.WORKSPACES / ".browsersafe")
            # 文件名带上所指向字段的指纹：同一个任务号重新挂单时，镜头增删会让
            # _m9 指向另一个文件，而客户端预取用 cache:'force-cache'——没有指纹
            # 就把上次缓存的字节当成本次素材回放，mediabunny 收到一段 JPEG 会报
            # "Unknown container format"（2026-09-21 线上 F-35 那条撞过）
            fst = Path(src).stat()
            fp = hashlib.sha1(f"{fst.st_size}:{int(fst.st_mtime_ns)}"
                              .encode()).hexdigest()[:8]
            safe = f"{job_id}_m{idx}-{fp}{Path(name).suffix}"
            rename[name] = safe
            files[f"media/{safe}"] = src
        props_out = rr._rewrite_media_names(props, rename)
        if logo_path is not None:
            files[str(props.get("brand").get("logo"))] = str(logo_path)
        audio_pkg = None
        if audio and audio.get("voice") and Path(str(audio["voice"])).is_file():
            meta, afiles = _build_audio_package(audio)
            props_out = {**props_out, "audio": meta}
            audio_pkg = (meta, afiles)
        agenthub.register(job_id, owner, props_out, files, str(out_path),
                          audio=audio_pkg,
                          layers_dir=str(layers_dir) if layers_dir else None)
        try:
            visual = agenthub.wait_result(job_id, progress=progress,
                                          cancel_check=cancel_check)
            delivered_final = agenthub.is_final_delivered(job_id)
            agenthub.discard(job_id)
        except BaseException:
            agenthub.discard(job_id)
            raise
        if delivered_final:
            # 浏览器已混好音的完整成片：不裁剪、不转码（重编码的 -an 会把人声丢掉）
            fn.delivered_final = True
            return visual
        # 旧录屏导出页/Node 成片台已退役；非 final 的裸画面轨只剩手工调试一条路，
        # 原样交给 build_render 走云端混音封装（秒级轻活），不再做裁剪转码。
        return visual

    fn.delivered_final = False
    return fn


def _agent_claimed(job_id: str, device: str) -> None:
    """agenthub 回调：成片台领走了任务，任务卡立刻给个准话。"""
    with _LOCK:
        j = JOBS.get(job_id)
        if j:
            j["render_via"] = f"agent:{device}"
            j["detail"] = f"成片台「{device}」已领取，正在本机生成"
            _jobs_save()


agenthub.on_claim = _agent_claimed


def _render_job(job_id: str, body: dict) -> None:
    """渲染阶段：画面交给用户的浏览器成片台渲；final 交回时云端连混音都省了。

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
        with _LOCK:
            if JOBS.get(job_id):
                JOBS[job_id]["render_via"] = "agent"
        render_kwargs = dict(bgm=_resolve_bgm(body.get("bgm")),
                             renderer=body.get("renderer") or "remotion",
                             sfx=bool(body.get("sfx", True)),
                             sfx_mode=body.get("sfxMode") or ("full" if body.get("sfx", True) else "off"),
                             show_subtitles=bool(body.get("subtitles", True)),
                             show_sources=bool(body.get("sources", True)),
                             job_id=job_id, progress=progress, defer_verify=True,
                             cancel_check=lambda: _cancel_requested(job_id),
                             visual_fn=_agent_visual(job_id, out.with_suffix(".layers")))
        cli.build_render(bundle_dir, out, work_dir=work_dir, **render_kwargs)
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
        if not body.get("try"):
            _cos_archive(job_id, out)
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
    """渲染灶台消费者：挂单等成片台领走 + 等带声成片交回。
    画面渲染已经在用户电脑上了，线程只是在等 IO，多开也不吃主机算力。"""
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
        except Exception as exc:  # noqa: BLE001
            print(f"render worker error: {exc}")
            _mark_failed(job_id, exc)


for _i in range(_PREP_CONCURRENCY):
    threading.Thread(target=_prep_worker, daemon=True).start()
for _i in range(_RENDER_STAGE_WORKERS):
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
