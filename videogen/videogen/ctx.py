"""跨域共享的东西：server 和 videogen/api/* 都从这儿取。

为什么单独一个文件：路由一旦按域搬进 videogen/api/*，server 去 import api、api 又
要回头拿 server 的状态就成了环（Python 里表现为 ImportError 或半初始化模块）。把
「两边都要用的」下沉到这儿，两边就只指向下层，谁也不用指着谁的后背。

规矩：**这儿只放共享**。只被一个域用的 helper 跟着那个域走，别往这儿堆。
被测试用 `server.X = ...` 重新绑定的那几个（WORKSPACES / OUTPUTS / BUNDLES_META /
USAGE_FILE / _reg / _preview_file）也在这儿 —— 唯一真身只有一个，两边都读 ctx.X，
否则测试改了个寂寞。
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import ipaddress
import logging
import os
import re
import threading
import time
from pathlib import Path
from fastapi import Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from . import auth, config, safestore
from . import brand as brand_kit
from . import tts as tts_mod


log = logging.getLogger(__name__)


ROOT = config.ROOT

WORKSPACES = config.WORKSPACES

STATIC = config.STATIC

OUTPUTS = config.OUTPUTS

AUTH_TOKEN = config.AUTH_TOKEN

TEMPLATES = config.TEMPLATES                  # 模板 id -> 展示名

TEMPLATE_ALIAS = config.TEMPLATE_ALIAS

DEFAULT_TEMPLATE = config.DEFAULT_TEMPLATE

INTAKE_TTL_SECONDS = 24 * 3600                # Agent 直投的待认领包保留 24 小时

SUPPORTED_FORMATS = set(TEMPLATES) | set(TEMPLATE_ALIAS)

JOBS: dict[str, dict] = {}

JOBS_FILE = Path(config.JOBS_FILE)

REG = Path(config.REGISTRY_FILE)

# 全局锁：JOBS / registry / 渲染工作目录都是共享可变状态，串行化写操作
_LOCK = threading.RLock()

_PREP_WAIT: list[str] = []     # 等预备通道的任务（FIFO）

_RENDER_WAIT: list[dict] = []  # 等渲染灶台的任务：{"job": id, "prio": int, "seq": int}

_PREP_CV = threading.Condition(_LOCK)

# 渲染全部在用户本机跑（2026-09-20 拍板，不做云端渲染备选）：渲染灶台线程
# 只负责「挂单等成片台领走 + 等带声成片交回」，画面渲染与混音都发生在用户
# 自己的浏览器里（协议见 agenthub.py 模块注释）。灶台线程数因此可以
# 放开——每个线程只是在等 IO，不再吃主机 CPU/内存。
# 6 → 24：一条在等的任务就占一条线程，而"没人领就一直等"最长是 24 小时
# （agenthub._WAIT_PATIENCE）。公开入口（免登录试玩）哪怕单条只等 5 分钟，
# 6 条也够把全站真客户的渲染排空 —— 这里留足余量，配合 try 的短耐心一起止血。
_RENDER_STAGE_WORKERS = max(1, int(os.environ.get("VIDEOGEN_RENDER_STAGES", "24") or "24"))

# 正在干活（非排队/非终态）的阶段：算排队位置时要把它们算在"前面"
_ACTIVE_STAGES = ("tts", "plan", "props", "prepped", "render", "audio", "mux")

_RENDER_STAGES = ("render", "audio", "mux")

# 正在后台备草稿的成片路径：前端据此显示"草稿准备中"还是"已备好"
DRAFT_PREP: set[str] = set()

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

# ── 鉴权 ─────────────────────────────────────────────
# 三种放行方式，按优先级：
#   1. 会话 cookie（邮箱密码登录签发，见 /api/auth/*）
#   2. 访问令牌（x-auth-token 头或 ?token=，给脚本/老客户端用的主钥匙）
#   3. 开放模式：既没建过账号也没配令牌 → 本机自用不拦
# 页面外壳、字体、健康检查、登录接口本身保持公开。
SESSION_COOKIE = "vg_session"

def _token_ok(request: Request) -> bool:
    if not AUTH_TOKEN:
        return False
    tok = (request.headers.get("x-auth-token")
           or request.query_params.get("token") or "")
    return _hmac.compare_digest(tok, AUTH_TOKEN)

def _session_email(request: Request) -> str | None:
    return auth.read_session(request.cookies.get(SESSION_COOKIE) or "")

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
    """任务（进度/成片/剧照）按归属隔离；试玩也必须只有本人或管理员可见。"""
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
        elif j.get("owner") is not None:
            owner = j["owner"]
        else:                                # 老任务没记 owner，退到项目归属
            p = next((x for x in _reg()["projects"]
                      if x["project_id"] == j.get("project_id")), None)
            owner = (p or {}).get("owner")
    if owner != ident:
        return JSONResponse({"error": "任务不属于你"}, status_code=403)
    return None

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

def _brand_for(email: str | None) -> dict | None:
    """高级档：当前用户的品牌套件出片参数。免费/未登录/没设置 = None。"""
    if not email or not auth.tier_at_least(email, "premium"):
        return None
    return brand_kit.for_build(email)

def _etag_of(body: str) -> str:
    return 'W/"%s"' % hashlib.sha1(body.encode("utf-8")).hexdigest()[:20]

def _page(request: Request, body: str) -> Response:
    """大 HTML 一律走这里：配弱 ETag，命中就回 304，浏览器少下一整页。"""
    tag = _etag_of(body)
    if any(t.strip() == tag for t in (request.headers.get("if-none-match") or "").split(",")):
        return Response(status_code=304, headers={"etag": tag, "cache-control": "no-cache"})
    return HTMLResponse(body, headers={"etag": tag, "cache-control": "no-cache"})

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

def _jobs_save() -> None:
    try:
        safestore.write_json(JOBS_FILE, JOBS, indent=None)
    except Exception:
        pass

def _reg() -> dict:
    return safestore.read_json(REG, default={"projects": []},
                               shape=lambda d: isinstance(d.get("projects"), list))

def _reg_save(reg: dict) -> None:
    safestore.write_json(REG, reg, count=lambda d: len(d.get("projects") or []))

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

INTAKES = WORKSPACES / ".intakes"            # 待认领 zip + 登记 sidecar（数据盘，重启不丢）

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

BROWSERPOC_DIR = STATIC / "poc"

def _poc_html():
    """成片台首页的 HTML；没打包时给一句照着能修的话。"""
    f = BROWSERPOC_DIR / "index.html"
    if not f.is_file():
        return JSONResponse({"error": "成片台页面未打包（renderer/_tool_bundle.mjs）"},
                            status_code=404)
    return f.read_text(encoding="utf-8")

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

def _mark_cancelled(job_id: str) -> None:
    with _LOCK:
        j = JOBS.get(job_id)
        if j and j.get("stage") not in ("done", "failed", "cancelled"):
            j.update(stage="cancelled", stage8=8, error=None,
                     detail="已停止", t_end=time.time())
            _jobs_save()

