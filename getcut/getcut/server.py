"""getcut 本地可视化工作台后端。

    python -m getcut.server     # http://localhost:8600

聚焦视频生成：素材包选择/上传 -> 内容确认 -> 渲染配置 -> 生成与成片。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import re
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from . import agenthub, auth, config, cos_store, legal, logx
from . import brand as brand_kit
from . import tts as tts_mod  # noqa: F401 —— 测试按 server.X 取这条再导出
from .schemas import JobCancelled
from . import ctx
import importlib

from .api import (
    try_api as api_try,
    brand as api_brand,
    auth as api_auth,
    assets as api_assets,
    pages as api_pages,
    projects as api_projects,
    agent as api_agent,
    transfer as api_transfer,
    media as api_media,
)


_CTX_SHARED = frozenset({
    "AUTH_TOKEN", "BROWSERPOC_DIR", "BUNDLES_META", "DEFAULT_TEMPLATE", "DRAFT_PREP", "INTAKES",
    "INTAKE_TTL_SECONDS", "JOBS", "JOBS_FILE", "OUTPUTS", "REG", "ROOT",
    "SESSION_COOKIE", "STATIC", "SUPPORTED_FORMATS", "TEMPLATES", "TEMPLATE_ALIAS", "USAGE_FILE",
    "WORKSPACES", "_ACTIVE_STAGES", "_LOCK", "_PENDING", "_PREP_CV", "_PREP_WAIT",
    "_PROXY_NETS", "_RENDER_STAGES", "_RENDER_STAGE_WORKERS", "_RENDER_WAIT", "_agent_identity", "_agent_job_ok",
    "_brand_for", "_bundle_owner", "_bundle_visible", "_bundles_meta", "_bundles_meta_save", "_client_ip",
    "_etag_of", "_find_bundles", "_is_adminish", "_job_visible", "_jobs_save", "_mark_cancelled",
    "_normalize_rate", "_open_mode", "_page", "_peer_is_proxy", "_poc_html", "_preview_file",
    "_project_visible", "_queue_ahead", "_reg", "_reg_save", "_resolve_bgm", "_resolve_bundle",
    "_session_email", "_sweep_intakes", "_token_ok", "_usage_load",
})


_API_HOME = {
    "agent": frozenset(('_agent_device', '_claim_owners', '_file_tag', 'agent_job_file', 'agent_job_layer', 'agent_job_progress', 'agent_job_visual', 'agent_login', 'agent_poll', 'agent_status', 'jianying_assistant_installer', 'poc_page')),
    "assets": frozenset(('_SFX_LABEL', 'bgm_file', 'bundle_detail', 'bundles', 'font', 'latest', 'music_library', 'sfx_file', 'sfx_preview', 'template_thumb', 'templates', 'voice_preview', 'voices_list')),
    "auth": frozenset(('_REDEEM_FAILS', '_purge_account', '_set_session_cookie', '_usage_drop', 'admin_gen_licenses', 'admin_license_audit', 'admin_list_licenses', 'admin_nodes', 'auth_change_password', 'auth_delete_account', 'auth_login', 'auth_logout', 'auth_register', 'auth_reset', 'auth_reset_code', 'auth_send_code', 'auth_session_revoke', 'auth_sessions', 'auth_status', 'license_redeem', 'me', 'me_update', 'pricing')),
    "brand": frozenset(('_clone_worker', 'brand_get', 'brand_logo_delete', 'brand_logo_get', 'brand_logo_upload', 'brand_put', 'vc_src', 'voice_clone_create', 'voice_clone_delete', 'voice_clone_get')),
    "media": frozenset(('agent_media', 'media', 'video')),
    "pages": frozenset(('_BROWSER_EXPORT_WIDGET', '_inject_browser_export', 'api_version', 'healthz', 'index', 'intake_page', 'studio')),
    "projects": frozenset(('_JY_PULL_TOKENS', '_bundle_meta', '_drop_staged', '_film_or_fetch', '_preview_auth_ok', '_preview_render_body', '_render_or_404', '_require_premium', 'create_project', 'delete_project', 'jianying_draft_zip', 'jianying_import', 'jianying_pull', 'jianying_status', 'list_projects', 'mount_bundle', 'preview_invalidate', 'preview_plan', 'preview_shots', 'preview_status')),
    "transfer": frozenset(('INTAKE_CODE_RE', 'MAX_EXTRACT_BYTES', 'MAX_INTAKE_BYTES', 'MAX_UPLOAD_BYTES', '_INTAKE_OPEN_TICKETS', '_INTAKE_RATE', '_INTAKE_TICKETS_PER_HOUR', '_INTAKE_WATERLINE_BYTES', '_STAGE_SPAN', '_TICK_TAU', '_effective_email', '_fix_mojibake_name', '_free_quota_check', '_intake_paths', '_intake_sidecar', '_intake_sidecar_save', '_intake_stored_bytes', '_raw_body', '_read_capped', '_safe_extract', '_usage_bump', '_usage_today', 'cancel_job', 'intake_claim', 'intake_list', 'intake_meta', 'intake_put', 'intake_ticket', 'job_status', 'my_jobs', 'start_build', 'upload')),
    "try_api": frozenset(('sample_bundle', 'try_render', 'try_status', 'try_topics_list', 'try_video')),
}


def _api_module(name: str):
    """按符号名找到它落在哪个 api 模块（懒加载：import server 不该拖起所有域）。"""
    for mod, names in _API_HOME.items():
        if name in names:
            return importlib.import_module(f"{__package__}.api.{mod}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __getattr__(name: str):
    """server.X：取已被拆走的符号 —— 先问 ctx，再问 api 模块（都只管读）。

    没有这一层，拆分就得改掉所有测试的取用路径；有了它，断言一字不动。
    真要**重新绑定**的那几个走 ctx.X：`server.X = v` 改的是 server 自己的字典，
    handler 读的是 ctx / api 模块，转发帮不上忙 —— 这正是不能图省事的地方。
    """
    if name in _CTX_SHARED:
        return getattr(ctx, name)
    if any(name in names for names in _API_HOME.values()):
        return getattr(_api_module(name), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


log = logging.getLogger(__name__)   # 结构化输出的唯一出口，见 logx 模块头的三条规矩

UPLOADS = config.UPLOADS


MAX_JOBS_KEPT = 80                            # jobs.json 只留最近这么多条，防无限膨胀


def _intake_sweeper(every: float = 600.0) -> None:
    """每 10 分钟清一次收件区（过期包与没用完的票）。

    以前 `_sweep_intakes()` 只挂在"有人来上传/认领"那一刻 —— 没人来的时候，
    过期的包就一直躺在盘上（系统盘只剩十几 G，而账号、密钥、备份都在同一块盘）。
    """
    while True:
        try:
            ctx._sweep_intakes()
        except Exception:  # noqa: BLE001 - 扫不动就下轮再来，别把线程弄死
            log.warning("intake sweep failed", exc_info=True)
        time.sleep(every)

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """开机一次性收尾：清掉老客户手上遗留的原始录音（`brand/sample.mp3`）。

    这轮把留存策略定成"客户的录音用完即删、服务器上不留档"，但改了写入路径只挡住
    新用户 —— 之前存下来的那份还在 /state 里，而且每天还跟着进备份。

    挂在 lifespan 而不是 `@app.on_event("startup")`：后者自 FastAPI 0.93 起废弃，
    每次开机往 stderr 喷 7 行 DeprecationWarning（Dockerfile 的 CMD 是
    `python -m getcut.server`，模块即 `__main__`，警告默认必显示），
    `docker logs` 一混流 jq 就噎死。
    """
    n = brand_kit.purge_recordings()
    if n:
        log.info("startup purged legacy customer recording(s)", extra={"count": n})
    threading.Thread(target=_intake_sweeper, name="intake-sweep", daemon=True).start()
    yield


app = FastAPI(title="GetCut studio", lifespan=_lifespan)

# 路由按域拆进 getcut/api/*，注册顺序 = 各域第一条路由在原文件里的行号顺序。
# 这个顺序不是随便排的：FastAPI 按注册顺序匹配，反了会被通配路由吃掉
# （route_order.py 每次改动后跑一遍即可复核）。
app.include_router(api_try.router)
app.include_router(api_brand.router)
app.include_router(api_auth.router)
app.include_router(api_assets.router)
app.include_router(api_pages.router)
app.include_router(api_projects.router)
app.include_router(api_agent.router)
app.include_router(api_transfer.router)
app.include_router(api_media.router)
# 双通道流水线：
#   prep 通道 —— 配音/分镜/版式（等外部 API 为主），多路并行，不占渲染力
#   渲染通道 —— 挂单等成片台交回 + ffmpeg 混音封装；画面渲染不在这台机器上
# 渲染中间产物（props_*.json / visual_*.mp4）已按任务隔离，多路互不覆盖。
_PREP_CONCURRENCY = max(1, int(os.environ.get("GETCUT_PREP_CONCURRENCY", "2")))
_RENDER_CONCURRENCY = max(1, int(os.environ.get("GETCUT_CONCURRENCY", "1")))
_RENDER_SEQ = 0
_RENDER_CV = threading.Condition(ctx._LOCK)
# 灶台之外的两条低优先后台通道（都限流，防影子任务偷走下一批人的渲染力）：
#   画面校验 —— 抽帧 + 等外部视觉 API，成片交付后才跑，不占灶台名额
#   草稿备料 —— 剪映草稿要切每镜素材与逐句配音（一串 ffmpeg），默认只留 1 路细水长流
_VERIFY_CONCURRENCY = max(1, int(os.environ.get("GETCUT_VERIFY_CONCURRENCY", "2")))
_DRAFT_CONCURRENCY = max(1, int(os.environ.get("GETCUT_DRAFT_CONCURRENCY", "1")))
_VERIFY_SEM = threading.Semaphore(_VERIFY_CONCURRENCY)
_DRAFT_SEM = threading.Semaphore(_DRAFT_CONCURRENCY)






def _prebuild_draft(video) -> None:
    """渲染完成后在后台把剪映草稿资产备好（失败不影响任何事，导出时还会再试）。

    草稿本身要再渲一次 Remotion——限流 _DRAFT_CONCURRENCY 路，
    否则高峰期成片后面排队的影子渲染会把下一批人的灶台吃掉。
    """
    key = str(video)
    ctx.DRAFT_PREP.add(key)
    try:
        from . import jianying_draft as jyd
        with _DRAFT_SEM:
            mf = jyd.load_manifest(video)
            if mf:
                jyd.prepare_draft(video, mf)
    except Exception as exc:  # noqa: BLE001
        log.warning("draft prebuild skipped", exc_info=exc)
    finally:
        ctx.DRAFT_PREP.discard(key)


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
        log.warning("try downscale failed", exc_info=exc)
        return False


def _sweep_try_files(keep: int = 20) -> None:
    """试玩样片只留最近 keep 个，别把磁盘堆满。"""
    try:
        files = sorted(ctx.OUTPUTS.glob("try-*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files[keep:]:
            f.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass




















def _job_prio(body: dict, email: str | None) -> int:
    """渲染灶台的优先级：付费(2) > 免费注册(1) > 试玩(0)。付费用户不跟试玩抢队。"""
    if body.get("try"):
        return 0
    if email and (auth.is_admin(email) or auth.tier_at_least(email, "basic")):
        return 2
    return 1


def _enqueue_render(job_id: str, prio: int) -> None:
    global _RENDER_SEQ
    with ctx._LOCK:
        _RENDER_SEQ += 1
        ctx._RENDER_WAIT.append({"job": job_id, "prio": prio, "seq": _RENDER_SEQ})
        _RENDER_CV.notify()


_PUBLIC_PATHS = {"/", "/index.html", "/studio", "/studio/", "/healthz", "/api/templates",
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






# ---------- 多用户归属 ----------
# 注册开放后工作台是多用户的：普通用户只看自己的项目；
# 管理员（第一个注册的）和持访问令牌的脚本可见全部。素材包目录仍是共享的。



















def _request_authed(request: Request) -> bool:
    tok = (request.headers.get("x-agent-token") or "").strip()
    if tok and auth.read_session(tok):
        return True            # 成片台/脚本的设备令牌（登录接口签发的长会话）
    if ctx._token_ok(request) or ctx._session_email(request):
        return True
    return ctx._open_mode()                                # 开放模式（需显式开）
















def _tier_of(request: Request) -> str:
    return auth.user_tier(ctx._session_email(request))




# ---------- 品牌套件（高级档） ----------









# ---------- 我的声音（声音复刻，高级档） ----------













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
    # 示例素材包：内容是固定的公开选题，不含任何客户数据 —— 给一天缓存，
    # 免得每个新访客都让服务器现打一遍几十 MB 的 zip（出网只有 3Mbps）
    if path == "/api/sample-bundle":
        return "public, max-age=86400"
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


# ---------- 访问日志：一次请求一行 JSON，带请求 ID ----------
# 这就是以前被 `uvicorn.run(log_level="warning")` 连带关掉的那份访问日志。
# 没有它时：出事只能人肉翻 docker logs，而且"这是哪一次请求、哪一条任务、
# 哪一分钟"三样对不上号。现在每次请求发一个 rid，同一次请求里打的所有日志
# （含跑在线程池里的同步端点）都自动带上它，见 logx 模块头。
# 用 fullmatch 而不是 `^...$`：Python 的 `$` 会放过**尾部换行**，
# 那样 "abc\n" 能混进来并被原样回写进 x-request-id 响应头 —— 响应头注入。
_RID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _request_id(request: Request) -> str:
    """上游给了就沿用（便于和 Caddy/网关的日志对上），否则现发一个。

    只认 [A-Za-z0-9_-] 且限长：这个值会回写进 x-request-id 响应头并落进日志，
    放宽了就等于开一个往日志和 HTTP 头里注入换行/控制字符的口子。
    """
    got = request.headers.get("x-request-id") or ""
    if _RID_RE.fullmatch(got):
        return got
    return uuid.uuid4().hex[:16]


@app.middleware("http")
async def _access_log(request: Request, call_next):
    """最外层：401 / 400 / 404 同样要留痕，否则查不到"谁在什么时候撞了门"。

    只记 path 不记 query —— 本站有 `?token=` 这条带主钥匙的通道，
    query 串进日志等于把访问令牌写到磁盘上。
    """
    rid = _request_id(request)
    token = logx.RID.set(rid)
    t0 = time.perf_counter()
    status = 499                       # 走到这就说明没拿到响应（客户端断开/取消，沿用 nginx 的 499）
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["x-request-id"] = rid
        return response
    except Exception:                  # noqa: BLE001 - 没接住的异常由最外层变 500，这里先把整段 traceback 留下
        status = 500
        log.exception("request failed", extra={"rid": rid, "method": request.method,
                                               "path": request.url.path})
        raise
    finally:
        ms = round((time.perf_counter() - t0) * 1000, 1)
        # 分级的意义：出事时 `jq 'select(.level!="INFO")'` 要能直接捞出来。
        # 全记 INFO 等于没分级，全记 WARNING 则健康检查每 30 秒刷一条告警。
        lvl = (logging.ERROR if status >= 500 else
               logging.WARNING if status >= 400 else logging.INFO)
        if status < 400 and request.url.path == "/healthz":
            # 容器 HEALTHCHECK 每 30 秒打一次，一天 2880 行纯噪音，会把
            # `docker logs --tail` 里的真实流量淹掉。降到 DEBUG：默认看不见，
            # 要确认探活真的在跑时把 GETCUT_LOG_LEVEL=DEBUG 就行。
            # 但 4xx/5xx 仍按上面的级别留痕 —— 探活开始失败是正经告警。
            lvl = logging.DEBUG
        log.log(lvl, "access", extra={"rid": rid, "method": request.method,
                                      "path": request.url.path, "status": status,
                                      "ms": ms})
        logx.RID.reset(token)








# ---------- 登录接口 ----------


















# ---------- 三页法定文本（公开，无需登录） ----------
# 与代码逐条对齐：留存数字来自 legal.RETENTION，改数字只改那一处，
# 免得出现"文案说 30 天、代码清 90 天"这种被投诉一句就翻车的写法。
for _kind in ("privacy", "terms", "refund"):

    def _legal_page(request: Request, _k: str = _kind) -> Response:
        return ctx._page(request, legal.page(_k))

    _legal_page.__name__ = "legal_" + _kind
    app.get("/" + _kind, response_class=HTMLResponse)(_legal_page)
















# ---------- 档位 / 卡密 / 定价页 ----------











# ---------- 试听（B5）----------

















def _jobs_load() -> None:
    if ctx.JOBS_FILE.is_file():
        try:
            ctx.JOBS.update(json.loads(ctx.JOBS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    if len(ctx.JOBS) > MAX_JOBS_KEPT:
        keep = sorted(ctx.JOBS.items(), key=lambda kv: kv[1].get("t0", 0))[-MAX_JOBS_KEPT:]
        ctx.JOBS.clear()
        ctx.JOBS.update(dict(keep))




_jobs_load()
# 启动清理：上次进程没跑完的任务已随进程消亡，标记失败让用户重发（防僵尸任务挡新提交）
with ctx._LOCK:
    _stale = [jid for jid, j in ctx.JOBS.items() if j.get("stage") not in ("done", "failed", "cancelled")]
    if _stale:
        for jid in _stale:
            ctx.JOBS[jid].update(stage="failed", stage8=8, t_end=time.time(),
                             error="服务重启，任务中断，请重新渲染")
        ctx._jobs_save()






# 渲染阶段：与真实流水线执行顺序一致（前端 timeline 直接照此渲染）
STAGE8 = ["读取素材", "AI 配音", "分镜规划", "画面设计",
          "画面渲染", "音效混音", "画面校验", "完成"]
# idx 从 0 开始；base 是该阶段起点的总进度
_STAGE_MAP = {"queued": (0, 3), "tts": (1, 6), "plan": (2, 16), "props": (3, 30),
              "render": (4, 40), "audio": (5, 78), "mux": (5, 88), "verify": (6, 93),
              "done": (7, 100)}
































# ---------- 分镜预览（渲染前先看每镜画面） ----------









































# ---------- Agent 直投（素材包自动进站） ----------
# 配合 getcut-bundle 技能：Agent 打包完直接 POST 上来拿一条 /i/<code> 短链；
# 任何浏览器（含手机）打开短链，页面自己把包导进工作台并建好项目，
# 用户只需要点「确定，导入工作台」→「确认内容并开始生成」。





























# ---------- 浏览器成片台（Agent 协议）接口 ----------
# 成片台页面轮询这组接口领任务/下载渲染包/上报进度/交回带声成片。
# 身份三种：登录签发的设备令牌（x-agent-token，90 天）、主钥匙（x-auth-token，
# 调试/管理）、开放模式（本机自用）。成片台只领自己的任务——素材是用户自己
# 的，不能串门到别人的电脑上。












































def _cleanup_work_dir(work_dir) -> None:
    """任务级工作目录用完即删（TTS 缓存在共享目录 work/_tts/ 下，不受影响）。"""
    try:
        shutil.rmtree(Path(work_dir), ignore_errors=True)
    except Exception:
        pass


def _mark_failed(job_id: str, err) -> None:
    with ctx._LOCK:
        j = ctx.JOBS.get(job_id)
        if j and j.get("stage") not in ("done", "failed", "cancelled"):
            j.update(stage="failed", stage8=8, error=str(err)[-800:], t_end=time.time())
            ctx._jobs_save()




def _cancel_requested(job_id: str) -> bool:
    """取消旗子：渲染循环每秒读一次（dict.get 原子，不必拿锁）。"""
    j = ctx.JOBS.get(job_id)
    return bool(j and j.get("cancel"))


def _progress_reporter(job_id: str):
    """阶段进度上报：把流水线的真实阶段映射到 8 段进度条。"""
    def progress(stage: str, pct: int, detail: str | None = None):
        idx, base = _STAGE_MAP.get(stage, (0, 0))
        span = {"tts": 14, "plan": 10, "props": 12, "render": 27, "audio": 10, "verify": 6}.get(stage, 8)
        val = min(base + int(pct / 100 * span), 98)
        with ctx._LOCK:
            j = ctx.JOBS.get(job_id)
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
            ctx._jobs_save()
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
            bundle_dir = ctx._resolve_bundle(body["bundle"])
        # 工作目录按任务隔离：同一素材包多任务并发时互不踩（TTS 缓存仍在共享目录）
        work_dir = config.WORK / f"{bundle_dir.name}--{job_id}"
        with ctx._LOCK:
            body["_prep"] = {"work_dir": str(work_dir), "bundle_dir": str(bundle_dir)}
        cli.build_prep(bundle_dir, work_dir=work_dir,
                       voice=body.get("voice") or None,
                       rate=ctx._normalize_rate(body.get("rate")),
                       format=body.get("format") or ctx.DEFAULT_TEMPLATE,
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
        with ctx._LOCK:
            j = ctx.JOBS.get(job_id)
            if j:
                j.update(stage="prepped", stage8=5, progress=40, t_stage=time.time(),
                         detail="配音与分镜已就绪")
            ctx._jobs_save()
        _enqueue_render(job_id, _job_prio(body, (ctx.JOBS.get(job_id) or {}).get("owner")))
    except JobCancelled:
        with ctx._LOCK:
            prep_meta = body.get("_prep") or {}
        if prep_meta.get("work_dir"):
            _cleanup_work_dir(prep_meta["work_dir"])
        ctx._mark_cancelled(job_id)
    except Exception as e:  # noqa: BLE001
        with ctx._LOCK:
            prep_meta = body.get("_prep") or {}
        if prep_meta.get("work_dir"):
            _cleanup_work_dir(prep_meta["work_dir"])
        _mark_failed(job_id, e)


def _cos_mark(job_id: str, key: str) -> None:
    """把 cos_key 记到任务表与项目登记上（两份都要：重启后靠 registry 找得回）。"""
    with ctx._LOCK:
        j = ctx.JOBS.get(job_id)
        if j:
            j["cos_key"] = key
            ctx._jobs_save()
        reg = ctx._reg()
        for pr in reg["projects"]:
            for r in pr.get("renders") or []:
                if r.get("id") == job_id:
                    r["cos_key"] = key
        ctx._reg_save(reg)


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
    with ctx._LOCK:
        j = ctx.JOBS.get(job_id) or {}
        if not j.get("cos_key") or not j.get("verify"):
            return
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
        with ctx._LOCK:
            j = ctx.JOBS.get(job_id)
            if j:
                j["verify"] = {k: report.get(k) for k in ("ok", "errors", "warnings")}
                ctx._jobs_save()
    except Exception as exc:  # noqa: BLE001
        log.warning("verify skipped", exc_info=exc)
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
        log.warning("browser_safe_video skipped", extra={"file": p.name}, exc_info=exc)
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
        with ctx._LOCK:
            _job = ctx.JOBS.get(job_id) or {}
            owner = _job.get("owner")
            is_try = bool(_job.get("try"))
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
            # 试玩是免登录公开入口，谁都能连着提交几条；让它最多占一条渲染灶台
            # 线程 5 分钟（真人客户的单才配"等你的电脑开机"那 24 小时）
            visual = agenthub.wait_result(job_id, progress=progress,
                                          cancel_check=cancel_check,
                                          patience=300.0 if is_try else None)
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
    with ctx._LOCK:
        j = ctx.JOBS.get(job_id)
        if j:
            j["render_via"] = f"agent:{device}"
            j["detail"] = f"成片台「{device}」已领取，正在本机生成"
            ctx._jobs_save()


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
        bundle_dir = Path(prep_meta.get("bundle_dir") or ctx._resolve_bundle(body["bundle"]))
        out = ctx.OUTPUTS / f"{bundle_dir.name}-{job_id}.mp4"
        with ctx._LOCK:
            if ctx.JOBS.get(job_id):
                ctx.JOBS[job_id]["render_via"] = "agent"
        render_kwargs = dict(bgm=ctx._resolve_bgm(body.get("bgm")),
                             renderer=body.get("renderer") or "remotion",
                             sfx=bool(body.get("sfx", True)),
                             sfx_mode=body.get("sfxMode") or ("full" if body.get("sfx", True) else "off"),
                             show_subtitles=bool(body.get("subtitles", True)),
                             show_sources=bool(body.get("sources", True)),
                             job_id=job_id, progress=progress, defer_verify=True,
                             cancel_check=lambda: _cancel_requested(job_id),
                             visual_fn=_agent_visual(job_id, out.with_suffix(".layers")))
        cli.build_render(bundle_dir, out, work_dir=work_dir, **render_kwargs)
        with ctx._LOCK:
            ctx.JOBS[job_id].update(stage="done", stage8=8, progress=100, video=str(out), t_end=time.time(),
                                detail="成片已生成")
            ctx._jobs_save()
            reg = ctx._reg()
            for p in reg["projects"]:
                if p["project_id"] == body.get("project_id"):
                    p.setdefault("renders", []).append({"id": job_id, "file": str(out),
                        "ts": time.strftime("%Y/%m/%d %H:%M")})
            ctx._reg_save(reg)
        if not body.get("try"):
            _cos_archive(job_id, out)
        if body.get("try"):
            # 试玩：降成 720p 带水印的样片给公开链接，原始大文件删掉；不备草稿资产
            small = ctx.OUTPUTS / f"try-{job_id}.mp4"
            if _downscale_720(out, small):
                with ctx._LOCK:
                    ctx.JOBS[job_id]["try_video"] = str(small)
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
        ctx._mark_cancelled(job_id)
    except Exception as e:  # noqa: BLE001
        _mark_failed(job_id, e)
    finally:
        if work_dir:
            _cleanup_work_dir(work_dir)


def _prep_worker() -> None:
    """预备通道消费者：同时最多 _PREP_CONCURRENCY 路在备料。"""
    while True:
        with ctx._LOCK:
            while not ctx._PREP_WAIT:
                ctx._PREP_CV.wait()
            job_id = ctx._PREP_WAIT.pop(0)
        body = ctx._PENDING.get(job_id) or {}
        try:
            _prep_job(job_id, body)
        except Exception as exc:  # noqa: BLE001 - 队列消费者绝不能死
            log.error("prep worker error", extra={"job": job_id}, exc_info=exc)
            _mark_failed(job_id, exc)


def _render_worker() -> None:
    """渲染灶台消费者：挂单等成片台领走 + 等带声成片交回。
    画面渲染已经在用户电脑上了，线程只是在等 IO，多开也不吃主机算力。"""
    while True:
        with ctx._LOCK:
            while not ctx._RENDER_WAIT:
                _RENDER_CV.wait()
            best = min(ctx._RENDER_WAIT, key=lambda e: (-e["prio"], e["seq"]))
            ctx._RENDER_WAIT.remove(best)
        job_id = best["job"]
        body = ctx._PENDING.get(job_id) or {}
        try:
            _render_job(job_id, body)
        except Exception as exc:  # noqa: BLE001
            log.error("render worker error", extra={"job": job_id}, exc_info=exc)
            _mark_failed(job_id, exc)


for _i in range(_PREP_CONCURRENCY):
    threading.Thread(target=_prep_worker, daemon=True).start()
for _i in range(ctx._RENDER_STAGE_WORKERS):
    threading.Thread(target=_render_worker, daemon=True).start()


def _intake_sweeper() -> None:
    """定期清掉过期的待认领素材包（Agent 直投，24 小时无人认领即删）。"""
    while True:
        time.sleep(1800)
        try:
            ctx._sweep_intakes()
        except Exception as exc:  # noqa: BLE001 - 清扫线程绝不能死
            log.error("intake sweeper error", exc_info=exc)


threading.Thread(target=_intake_sweeper, daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    # 云部署：HOST 需为 0.0.0.0；PORT 由平台注入（如 Cloudflare Containers / Fly / Railway）
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8600")))
    a = ap.parse_args()
    # 进程级日志在这儿一次性接好：JSON 一行一条进 stdout，交给 docker 轮转
    # （别自己开文件——容器一重启文件就留在旧层里，反而找不到）。
    logx.configure()
    log.info("studio starting", extra={"url": f"http://{a.host}:{a.port}",
                                       "workspace": str(ctx.WORKSPACES)})
    uvicorn.run(app, host=a.host, port=a.port,
                # 以前是 log_level="warning"：启动信息、访问日志全被吞掉，
                # 出事只能人肉翻。访问日志改由 _access_log 中间件产出（带 rid、
                # 分级、不记 query），这里放开到 info 只是让 uvicorn 自己的
                # 启动/优雅关闭信息能出来，不与中间件重复。
                log_level=os.environ.get("GETCUT_UVICORN_LOG_LEVEL", "info"),
                # 不装 uvicorn 自带的 logging 配置：那份配置给 uvicorn.* 挂的是
                # 纯文本 handler，开机 4 行 `INFO: Started server process ...`
                # 混进 stdout 就把 `docker logs | jq` 噎死。传 None → uvicorn 不
                # 挂 handler → 消息上浮到 root，由 logx 的 JSON handler 出。
                log_config=None,
                access_log=False)


if __name__ == "__main__":
    main()
