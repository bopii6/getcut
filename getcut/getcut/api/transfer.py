"""上传、认领、构建任务与任务查询（最容易出错的一段：路径、配额、并发）。

从 server.py 按域拆出来的路由。
路由**注册顺序**由 server 里的 include_router 顺序决定（按各域首条路由行号
排序），改动顺序前先看 tests/test_route_order.py 的检查 —— 顺序反了会被通配路由吃掉。
"""
from __future__ import annotations

import json
import math
import re
import secrets
import shutil
import stat
import threading
import time
import uuid
import zipfile
from pathlib import Path
from fastapi import Request, UploadFile
from fastapi.responses import JSONResponse
from .. import agenthub, auth, config, safestore
from .. import brand as brand_kit
from .. import schemas

from .. import ctx

from fastapi import APIRouter

router = APIRouter()

MAX_UPLOAD_BYTES = 512 * 1024 * 1024          # 单个 zip 上限 512MB
MAX_EXTRACT_BYTES = 2 * 1024 * 1024 * 1024    # 解压后总上限 2GB（防 zip 炸弹）
INTAKE_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
# 收件口（一次性票 → PUT）的四道判据。系统盘只剩十几 G，而账号/密钥/备份/日志
# 都在同一块盘上 —— 上限与水位都是照着"绝不能把盘写满"定的，不是照着方便定的。
MAX_INTAKE_BYTES = 200 * 1024 * 1024          # 一张票最多收 200MB（素材包实测 30~80MB）
_INTAKE_TICKETS_PER_HOUR = 10                 # 同一地址每小时最多领 10 张票
_INTAKE_OPEN_TICKETS = 5                      # 一个账号手上最多攒 5 张没用掉的票
_INTAKE_WATERLINE_BYTES = 2 * 1024 ** 3       # 收件区堆到 2GB 就先拒收
# 整包上传口（/api/upload）与收件口同源的四道闸。2026-09-24 补齐 —— 在这之前
# 这条口只有单包 512MB 上限，限流/水位/配额一道都没有，而它是登录即可达的：
# 免费注册个号就能循环塞 512MB 的包（重名自动 -1/-2 永不覆盖），照收件口那起
# 事故的写法，几小时就能把盘写满。水位照 40G 盘、成片+备份还要占的现实定。
_UPLOAD_RATE: dict[str, list[float]] = {}     # ip -> 最近整包上传时间戳（滑窗限流）
_UPLOADS_PER_HOUR = 20                        # 同一地址每小时最多传 20 个包
_USER_BUNDLE_CAP = 100                        # 一个账号名下最多 100 个素材包（目前没有删包口）
_WORKSPACES_WATERLINE_BYTES = 6 * 1024 ** 3   # 素材库堆到 6GB 先拒收（现占 2.5G，盘剩 14G）
def _effective_email(request: Request, body_email=None) -> str | None:
    """会话优先；其次认「账号自己的设备令牌」；主钥匙可代 body.email 行事。

    为什么要单独认设备令牌：客户端工具（技能 / MCP）以前得拿**站点主钥匙**，
    而那张钥匙能领走并看见全站任何客户的素材与成片 —— 把它发给客户等于把
    整站交出去。现在客户机器上只需要一张**自己账号**的令牌：在「登录设备」里
    看得见、能单独踢掉，泄露了也只波及它自己那一个账号。
    令牌持有者本就 adminish（可见一切）这条不变：body.email 仍然只对主钥匙有效。"""
    email = ctx._session_email(request)
    if not email:
        tok = (request.headers.get("x-agent-token") or "").strip()
        if tok:
            email = auth.read_session(tok)
    if not email and body_email and ctx._token_ok(request):
        return str(body_email).strip().lower()
    return email
def _usage_today(email: str) -> int:
    """今天已经记了几条（只读，不动账本）。"""
    return int(((ctx._usage_load().get(email) or {}).get(time.strftime("%Y-%m-%d")) or 0))
def _free_quota_check(email: str) -> tuple[bool, int]:
    """免费档还能不能出这一条 + 今天已用几条。判额度只读，记账留给放行之后。"""
    with ctx._LOCK:
        used = _usage_today(email)
        return used < config.FREE_DAILY_BUILDS, used


def _usage_bump_locked(email: str) -> int:
    """在 ``ctx._LOCK`` 内记一次出片；调用方必须已经持锁。"""
    today = time.strftime("%Y-%m-%d")
    keep = {today, time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)),
            time.strftime("%Y-%m-%d", time.localtime(time.time() - 172800))}
    data = ctx._usage_load()
    user = {d: n for d, n in (data.get(email) or {}).items() if d in keep}
    user[today] = int(user.get(today, 0)) + 1
    data[email] = user
    try:
        ctx.USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        safestore.write_json(ctx.USAGE_FILE, data, indent=None)
    except OSError:
        pass
    return user[today]


def _usage_bump(email: str) -> int:
    """记一次出片，返回今天已用次数。只留最近 3 天，防文件长大。"""
    with ctx._LOCK:
        return _usage_bump_locked(email)


def _free_quota_claim(email: str) -> tuple[bool, int]:
    """在同一临界区检查并记一次免费出片，避免并发请求各自看到旧余额。"""
    with ctx._LOCK:
        used = _usage_today(email)
        if used >= config.FREE_DAILY_BUILDS:
            return False, used
        return True, _usage_bump_locked(email)
# 各长阶段的进度区间（真实上报缺位时，用渐近曲线兜底爬升，既不冻住也不会跑飞）
_STAGE_SPAN = {"tts": (6, 16), "plan": (16, 30), "props": (30, 40),
               "render": (40, 78), "audio": (78, 88), "mux": (88, 93), "verify": (93, 99)}
_TICK_TAU = 130.0        # 时间常数（秒）：约 2 分钟后走完该阶段 60%，之后越来越慢
def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """防 Zip Slip / zip 炸弹 / 符号链接逃逸：逐条校验成员路径落在 dest 内，且总量受控。

    光校验名字挡不住符号链接：`link` 与 `link/evil.txt` 两条名字各自都在 dest 内，
    解压器却会先建软链再把文件"穿过"它写到外面 —— 上传口对免费注册用户开着，
    而 /app/getcut 是从宿主机挂进来的，等于任意登录用户可写服务器代码。
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


async def _save_capped(file, cap: int, tmp: Path) -> None:
    """边收边落盘，超 cap 当场断（临时文件由调用方清）。

    为什么不整包读进内存再写：512MB 一条、线程池并发几条，3G 内存的小机
    直接进 OOM killer 的射程 —— 落盘同样是流式的，内存里永远只过 1MB 一块。"""
    left = cap
    with tmp.open("wb") as out:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                return
            left -= len(chunk)
            if left < 0:
                raise ValueError("upload too large")
            out.write(chunk)


def _workspaces_stored_bytes() -> int:
    """素材库（WORKSPACES，不含收件区）现占字节：整包上传的水位判据用。

    要走整棵树，慢；但上传是低频动作，每次多花一秒换"盘不会被写满"值得。
    收件区不算进来：它有自己的 2GB 水位，两本账分开记。"""
    root = ctx.WORKSPACES
    if not root.is_dir():
        return 0
    skip = ctx.INTAKES
    total = 0
    for d in root.iterdir():
        if d == skip or not d.is_dir():
            continue
        for f in d.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    return total


@router.post("/api/upload")
async def upload(file: UploadFile, request: Request):
    ip = ctx._client_ip(request)
    now = time.time()
    hits = [t for t in _UPLOAD_RATE.get(ip, []) if now - t < 3600]
    if len(hits) >= _UPLOADS_PER_HOUR:
        return JSONResponse({"error": "传得太频繁了，一小时后再试"}, status_code=429)
    meta = ctx._bundles_meta()
    email = _effective_email(request)
    if email:
        mine = sum(1 for m in meta.values() if m.get("owner") == email)
        if mine >= _USER_BUNDLE_CAP:
            return JSONResponse(
                {"error": f"你名下已有 {mine} 个素材包，装不下了，联系客服清理"},
                status_code=429)
    if _workspaces_stored_bytes() > _WORKSPACES_WATERLINE_BYTES:
        return JSONResponse({"error": "素材库暂时满了，请稍后再试"}, status_code=503)
    name = Path(_fix_mojibake_name(file.filename or "bundle.zip")).stem or f"bundle-{int(time.time())}"
    dest = ctx.WORKSPACES / name
    i = 1
    while dest.exists():
        dest = ctx.WORKSPACES / f"{name}-{i}"
        i += 1
    dest.mkdir(parents=True)
    tmp = ctx.WORKSPACES / f".upload-{uuid.uuid4().hex}.zip"
    try:
        try:
            await _save_capped(file, MAX_UPLOAD_BYTES, tmp)
        except ValueError:
            shutil.rmtree(dest, ignore_errors=True)
            return JSONResponse({"error": "zip 超过 512MB 上限"}, status_code=413)
        try:
            with zipfile.ZipFile(tmp) as zf:
                _safe_extract(zf, dest)
        except (zipfile.BadZipFile, ValueError) as e:
            shutil.rmtree(dest, ignore_errors=True)
            return JSONResponse({"error": f"素材包无效：{e}"}, status_code=400)
    finally:
        tmp.unlink(missing_ok=True)
    if not (dest / "content.json").is_file():
        shutil.rmtree(dest, ignore_errors=True)
        return JSONResponse({"error": "zip 里没有 content.json，不是有效的素材包"}, status_code=400)
    # 只查"文件在不在"是不够的：content.json 少个 title 字段，包会被收下，
    # 直到出片那一刻才 500，前端只看到 "HTTP 500"、任务里是一截 'title'。
    # 收包当场解析一遍，坏包直接 400 说人话，不占名字也不占额度。
    try:
        content = schemas.Content.load(dest / "content.json")
        if not content.title.strip():
            raise ValueError("content.json 的 title 是空的")
        if not content.script.strip():
            raise ValueError("content.json 的 script（口播稿）是空的")
        if (dest / "manifest.json").is_file():
            schemas.Manifest.load(dest / "manifest.json")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        shutil.rmtree(dest, ignore_errors=True)
        return JSONResponse({"error": f"素材包内容有问题：{e}"}, status_code=400)
    # owner 用 _effective_email：设备令牌（技能/MCP）传的包也记到账号头上，
    # 以前只认会话，工具端传的包 owner 落 None，成了无主数据
    meta[dest.name] = {"owner": email, "created": time.strftime("%Y/%m/%d %H:%M")}
    ctx._bundles_meta_save(meta)
    hits.append(now)
    _UPLOAD_RATE[ip] = hits
    return {"name": dest.name}
_INTAKE_RATE: dict[str, list[float]] = {}    # ip -> 最近上传时间戳（滑窗限流）
def _intake_paths(code: str) -> tuple[Path, Path]:
    return ctx.INTAKES / f"{code}.zip", ctx.INTAKES / f"{code}.json"
def _intake_sidecar(code: str) -> dict:
    _, side = _intake_paths(code)
    if side.is_file():
        try:
            return json.loads(side.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 登记坏了按没有处理
            return {}
    return {}
def _intake_sidecar_save(code: str, data: dict) -> None:
    """原子写收件登记（几 KB 的 json）：领票时就写，包还没到也有一条记录。"""
    ctx.INTAKES.mkdir(parents=True, exist_ok=True)
    _, side = _intake_paths(code)
    safestore.write_json(side, data, indent=None)


def _intake_stored_bytes() -> int:
    if not ctx.INTAKES.is_dir():
        return 0
    total = 0
    for f in ctx.INTAKES.glob("*.zip"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _intake_reserved_bytes(exclude: str | None = None) -> int:
    """已通过 PUT 原子占位、尚未转正的字节数。"""
    if not ctx.INTAKES.is_dir():
        return 0
    total = 0
    for side_path in ctx.INTAKES.glob("*.json"):
        code = side_path.stem
        if code == exclude:
            continue
        side = _intake_sidecar(code)
        if side.get("put_claim"):
            total += max(0, int(side.get("put_reserved") or 0))
    return total
@router.get("/api/intake")
def intake_list(request: Request):
    """我的收件箱：这个账号领过、还没导入的包。手机端「素材」入口读的就是这里。

    只列自己的（owner 写在票上），别人看不见你寄了什么。`state` 给手机一个
    明确的人话状态，旧的 `ready` / `projectId` 字段继续保留给旧页面。
    """
    email = ctx._session_email(request)
    if not email and not ctx._open_mode():
        return JSONResponse({"error": "未登录"}, status_code=401)
    ctx._sweep_intakes()
    out = []
    if ctx.INTAKES.is_dir():
        for f in sorted(ctx.INTAKES.glob("*.json"), key=lambda p: p.name):
            side = _intake_sidecar(f.stem)
            if not side or side.get("owner") != email:
                continue
            ready = (ctx.INTAKES / f"{f.stem}.zip").is_file()
            claimed = bool(side.get("claimed") and side.get("project_id"))
            if claimed:
                state = "imported"
            elif side.get("claim_token"):
                state = "importing"
            elif ready:
                state = "ready"
            else:
                state = "waiting_upload"
            project = None
            if claimed:
                with ctx._LOCK:
                    project = next((p for p in ctx._reg()["projects"]
                                    if p.get("project_id") == side.get("project_id")
                                    and p.get("owner") == email), None)
            out.append({"code": f.stem, "ready": ready,
                        "claimed": claimed, "state": state,
                        "file": Path(str(side.get("file") or "")).name,
                        "bundle": project.get("bundle") if project else None,
                        "expiresAt": (side.get("created") or 0) + ctx.INTAKE_TTL_SECONDS,
                        "projectId": side.get("project_id")})
    out.sort(key=lambda x: -x["expiresAt"])
    return {"intakes": out[:30]}
@router.post("/api/intake/ticket")
def intake_ticket(request: Request, body: dict = None):
    """领一张收件票：客户在自己登录的网页上点一下，拿到一条一次性的上传地址。

    为什么不再像以前那样"谁都能 POST /api/intake"：那条口匿名、单包 512MB、
    同一 IP 一小时 10 次 —— 一小时能塞进 5GB，而线上那块 40G 系统盘只剩十几 G，
    约 3 小时就能把整台机器写崩（账号、密钥、备份、日志都在同一块盘上）。
    更要紧的是：客户端工具以前要拿**站点主钥匙**才能上传，那张钥匙能领走并看见
    全站任何客户的素材与成片 —— 正好是"一条片子只有本人能经手"这条红线不能容忍的。
    现在票一次一用、认领人写死在票上，客户机器上不需要任何账号或密钥。
    """
    email = _effective_email(request, (body or {}).get("email"))
    if not email and not ctx._open_mode():
        return JSONResponse({"error": "先登录，再领收件地址"}, status_code=401)
    ip = ctx._client_ip(request)
    now = time.time()
    hits = [t for t in _INTAKE_RATE.get(ip, []) if now - t < 3600]
    if len(hits) >= _INTAKE_TICKETS_PER_HOUR:
        return JSONResponse({"error": "领收件地址太频繁了，一小时后再试"}, status_code=429)
    ctx.INTAKES.mkdir(parents=True, exist_ok=True)
    ctx._sweep_intakes()
    # 过期清扫只在"有人来"时才动手，所以没人上传时包会一直躺着 —— 水位这道判
    # 是另一只保险：收件区堆到线上限就先拒，不给它写满整块盘的机会
    if _intake_stored_bytes() > _INTAKE_WATERLINE_BYTES:
        return JSONResponse({"error": "收件区暂时满了，请稍后再试"}, status_code=503)
    open_n = sum(1 for f in ctx.INTAKES.glob("*.json")
                 if _intake_sidecar(f.stem).get("owner") == email
                 and not (ctx.INTAKES / f"{f.stem}.zip").is_file())
    if open_n >= _INTAKE_OPEN_TICKETS:
        return JSONResponse({"error": f"你还有 {open_n} 个收件地址没用掉，先拿去上传"},
                            status_code=429)
    code = uuid.uuid4().hex[:12]
    secret = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    _intake_sidecar_save(code, {"owner": email, "secret": secret, "created": now})
    hits.append(now)
    _INTAKE_RATE[ip] = hits
    base = str(request.base_url).rstrip("/")
    return {"code": code, "url": f"{base}/i/{code}",
            "expiresAt": now + ctx.INTAKE_TTL_SECONDS,
            "maxBytes": MAX_INTAKE_BYTES,
            "put_url": f"{base}/api/intake/{code}?t={secret}"}
@router.put("/api/intake/{code}")
async def intake_put(code: str, request: Request):
    """凭票上传：一条 PUT。票本身就是一次性凭证，不要账号、不要任何钥匙。"""
    if not INTAKE_CODE_RE.match(code):
        return JSONResponse({"error": "链接无效"}, status_code=404)

    zf_path, _ = _intake_paths(code)
    got = (request.query_params.get("t") or "")[:64]
    claim = uuid.uuid4().hex
    # 占用与水位预留只在同步临界区内完成；网络流 await 期间绝不持有线程锁。
    with ctx._LOCK:
        ctx._sweep_intakes()
        side = _intake_sidecar(code)
        # 不区分"没有这张票"与"票不对"：这条地址会被抄来抄去，别替人探路
        if not side.get("secret") or not secrets.compare_digest(str(side["secret"]), got):
            return JSONResponse({"error": "收件地址无效或已过期"}, status_code=403)
        if zf_path.is_file() or side.get("claimed"):
            return JSONResponse({"error": "这个收件地址已经收过包了"}, status_code=409)
        if side.get("put_claim"):
            return JSONResponse({"error": "这个收件地址正在上传，请不要重复提交"}, status_code=409)
        if _intake_stored_bytes() + _intake_reserved_bytes() > _INTAKE_WATERLINE_BYTES:
            return JSONResponse({"error": "收件区暂时满了，请稍后再试"}, status_code=503)
        side["put_claim"] = claim
        side["put_claim_at"] = time.time()
        side["put_reserved"] = 0
        _intake_sidecar_save(code, side)

    # 包体边收边落盘（临时文件、验完原子转正）：整包憋内存的老写法，
    # 几条并发的 200MB PUT 就能把 3G 内存的小机顶进 OOM。
    ctx.INTAKES.mkdir(parents=True, exist_ok=True)
    tmp = ctx.INTAKES / f".put-{uuid.uuid4().hex}.part"
    committed = False
    published = False
    try:
        over = False
        full = False
        with tmp.open("wb") as out:
            left = MAX_INTAKE_BYTES
            async for chunk in request.stream():
                for start in range(0, len(chunk), 1024 * 1024):
                    piece = chunk[start:start + 1024 * 1024]
                    if left - len(piece) < 0:
                        over = True
                        break
                    # 先在水位账本里原子预留，再把这块写到盘上。这样多条 PUT
                    # 即使同时通过入口，也不可能一起按“旧余额”把收件区写越线。
                    with ctx._LOCK:
                        current = _intake_sidecar(code)
                        if current.get("put_claim") != claim:
                            return JSONResponse(
                                {"error": "这个收件地址正在上传，请不要重复提交"},
                                status_code=409)
                        used = (_intake_stored_bytes()
                                + _intake_reserved_bytes(exclude=code)
                                + int(current.get("put_reserved") or 0))
                        if used + len(piece) > _INTAKE_WATERLINE_BYTES:
                            full = True
                            break
                        current["put_reserved"] = int(current.get("put_reserved") or 0) + len(piece)
                        _intake_sidecar_save(code, current)
                    out.write(piece)
                    left -= len(piece)
                if over or full:
                    break
        if over:
            return JSONResponse({"error": f"素材包超过 {MAX_INTAKE_BYTES // 1048576}MB 上限"},
                                status_code=413)
        if full:
            return JSONResponse({"error": "收件区暂时满了，请稍后再试"}, status_code=503)
        try:
            with zipfile.ZipFile(tmp) as zf:
                if "content.json" not in zf.namelist():
                    raise zipfile.BadZipFile("no content.json")
        except zipfile.BadZipFile:
            return JSONResponse({"error": "zip 里没有 content.json，不是有效的素材包"}, status_code=400)

        with ctx._LOCK:
            current = _intake_sidecar(code)
            if current.get("put_claim") != claim or zf_path.is_file():
                return JSONResponse({"error": "这个收件地址已经收过包了"}, status_code=409)
            tmp.replace(zf_path)
            published = True
            # 24 小时从"包真到了"这一刻算。文件名走 query（HTTP 头只许 ASCII，
            # 而客户就是把选题写进 zip 名的人）；名字只用于导入后给项目起名。
            current.pop("put_claim", None)
            current.pop("put_claim_at", None)
            current.pop("put_reserved", None)
            current["created"] = time.time()
            current["file"] = _fix_mojibake_name(
                request.query_params.get("name") or "bundle.zip")[:160]
            _intake_sidecar_save(code, current)
            committed = True
    finally:
        tmp.unlink(missing_ok=True)
        if not committed:
            if locals().get("published"):
                zf_path.unlink(missing_ok=True)
            with ctx._LOCK:
                current = _intake_sidecar(code)
                if current.get("put_claim") == claim:
                    current.pop("put_claim", None)
                    current.pop("put_claim_at", None)
                    current.pop("put_reserved", None)
                    _intake_sidecar_save(code, current)
    size = zf_path.stat().st_size
    base = str(request.base_url).rstrip("/")
    return {"ok": True, "bytes": size, "url": f"{base}/i/{code}"}
@router.get("/api/intake/{code}/meta")
def intake_meta(code: str, request: Request):
    """落地页概要：**只说"有个包在等你"，不说包里写了什么**。

    这条链接是一条取件码，会被转发、会被别人扫到。以前它匿名回标题、口播前
    400 字、字数与图片视频数 —— 等于 A 把链接发到群里，谁都能读 A 还没发布的选题稿
    （2026-09-23 隔离定调后查出来的，见 tests/test_intake_privacy.py）。
    内容一律等**认领之后**由项目页显示：认领要登录，认领后这条就归他账号。
    """
    if not INTAKE_CODE_RE.match(code):
        return JSONResponse({"error": "链接无效"}, status_code=404)
    zf_path, _ = _intake_paths(code)
    side = _intake_sidecar(code)
    email = ctx._session_email(request)
    out = {"logged": bool(email) or ctx._open_mode()}
    if not zf_path.is_file():
        if side.get("claimed") and side.get("project_id"):
            pid = side["project_id"]
            out.update({"claimed": True})
            # 项目号也只给正主：别人扫到链接不该知道这条落到哪个项目
            if email or ctx._open_mode():
                with ctx._LOCK:
                    p = next((x for x in ctx._reg()["projects"]
                             if x.get("project_id") == pid), None)
                if p and p.get("owner") in (None, email):
                    out["projectId"] = pid
            return out
        return JSONResponse({"error": "链接已失效（素材包 24 小时内有效）"}, status_code=404)
    # 连原始文件名都不给：客户常把选题直接写进 zip 名（"美联储加息内幕.zip"），
    # 那等于把稿子标题念给每一个扫到链接的人听。名字等导入之后在项目页里看。
    out.update({"claimed": False,
                "expiresAt": (side.get("created") or 0) + ctx.INTAKE_TTL_SECONDS})
    return out
@router.post("/api/intake/{code}/claim")
def intake_claim(code: str, request: Request, body: dict = None):
    """认领：把包解进工作区、登记归属、建好项目并挂上，一次顶「上传 + 建项目 + 挂包」。

    要登录（开放模式本机自用除外；令牌主钥匙可代 body.email 指定的账号）：
    渲染是账号行为，包认领后跟着账号走。
    """
    if not INTAKE_CODE_RE.match(code):
        return JSONResponse({"error": "链接无效"}, status_code=404)
    email = _effective_email(request, (body or {}).get("email"))
    if not email and not ctx._open_mode():
        return JSONResponse({"error": "先登录或注册，再导入素材包"}, status_code=401)

    zf_path, _ = _intake_paths(code)
    claim = uuid.uuid4().hex
    dest = None
    committed = False
    try:
        # 先在同一把锁里复查票权并写 claim 标记。第二个并发请求只能看到
        # “正在导入”，不能也去解包、建同名目录或追加第二个项目。
        with ctx._LOCK:
            side = _intake_sidecar(code)
            owner = side.get("owner")
            admin = ctx._is_adminish(request) or ctx._open_mode()
            if owner and email != owner and not admin:
                return JSONResponse(
                    {"error": "这条收件地址是给别的账号领的，换本人账号再来"},
                    status_code=403)
            if not zf_path.is_file():
                if side.get("project_id"):
                    # 已导入：项目号只给正主，别人只知道"这条用过了"
                    if admin or email == owner:
                        return JSONResponse({"error": "这个素材包已被导入过了",
                                             "projectId": side["project_id"]}, status_code=409)
                    return JSONResponse({"error": "这个素材包已经被导入过了"}, status_code=409)
                if side.get("claim_token"):
                    return JSONResponse({"error": "这个素材包正在导入，请稍候"}, status_code=409)
                return JSONResponse(
                    {"error": "包还没到，或这条地址已过期（24 小时内有效）"},
                    status_code=404)

            orig_name = Path(_fix_mojibake_name(side.get("file") or "bundle.zip")).stem or "bundle"
            name = re.sub(r'[\\/:*?"<>|]', "", orig_name).strip() or "bundle"
            dest = ctx.WORKSPACES / name
            i = 1
            while True:
                try:
                    dest.mkdir(parents=True, exist_ok=False)
                    break
                except FileExistsError:
                    dest = ctx.WORKSPACES / f"{name}-{i}"
                    i += 1
            side["claim_token"] = claim
            side["claim_at"] = time.time()
            _intake_sidecar_save(code, side)

        try:
            with zipfile.ZipFile(zf_path) as zf:
                _safe_extract(zf, dest)
        except (zipfile.BadZipFile, ValueError) as e:
            return JSONResponse({"error": f"素材包无效：{e}"}, status_code=400)
        if not (dest / "content.json").is_file():
            return JSONResponse(
                {"error": "zip 里没有 content.json，不是有效的素材包"}, status_code=400)

        with ctx._LOCK:
            current = _intake_sidecar(code)
            if current.get("claim_token") != claim:
                return JSONResponse({"error": "这个素材包正在导入，请稍候"}, status_code=409)
            meta = ctx._bundles_meta()
            meta[dest.name] = {"owner": email, "created": time.strftime("%Y/%m/%d %H:%M")}
            ctx._bundles_meta_save(meta)
            reg = ctx._reg()
            pid = uuid.uuid4().hex[:12]
            reg["projects"].append({"project_id": pid, "title": dest.name, "bundle": dest.name,
                                    "created": time.strftime("%Y/%m/%d"), "renders": [],
                                    "owner": email})
            ctx._reg_save(reg)
            current.pop("claim_token", None)
            current.pop("claim_at", None)
            current["claimed"] = True
            current["claimed_at"] = time.time()
            current["project_id"] = pid
            _intake_sidecar_save(code, current)
            zf_path.unlink(missing_ok=True)
            committed = True
        return {"name": dest.name, "project_id": pid, "title": dest.name}
    finally:
        if not committed and dest is not None:
            shutil.rmtree(dest, ignore_errors=True)
        if not committed:
            with ctx._LOCK:
                current = _intake_sidecar(code)
                if current.get("claim_token") == claim:
                    current.pop("claim_token", None)
                    current.pop("claim_at", None)
                    _intake_sidecar_save(code, current)
@router.post("/api/build")
def start_build(body: dict, request: Request):
    fmt = body.get("format") or ctx.DEFAULT_TEMPLATE
    if fmt not in ctx.SUPPORTED_FORMATS:
        return JSONResponse(
            {"error": f"模板 '{fmt}' 不存在，可选：{'、'.join(ctx.TEMPLATES)}"}, status_code=400)
    if not body.get("bundle"):
        return JSONResponse({"error": "缺少素材包"}, status_code=400)
    if body.get("project_id"):
        with ctx._LOCK:
            target = next((p for p in ctx._reg()["projects"]
                           if p["project_id"] == body["project_id"]), None)
            if target and not ctx._project_visible(target, request):
                return JSONResponse({"error": "项目不存在"}, status_code=403)
    if not ctx._bundle_visible(body["bundle"], request):
        return JSONResponse({"error": "素材包不存在"}, status_code=404)
    try:
        ctx._resolve_bundle(body["bundle"])
        ctx._resolve_bgm(body.get("bgm"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    # 付费墙：免费档每天限量出片且强制带 GetCut 水印；基础/高级版不限量、水印随意。
    email = _effective_email(request, body.get("email"))
    free_email = (email if email and not auth.is_admin(email)
                  and auth.user_tier(email) == "free" else None)
    if free_email:
        body = dict(body)
        body["watermark"] = True
    if email:
        body = dict(body)
        body["brand"] = ctx._brand_for(email)   # 高级档品牌套件，服务端自动带上（默认配置固化）
        if body.get("voice") == "@clone":
            clone = brand_kit.clone_info(email) if auth.tier_at_least(email, "premium") else None
            body["voice"] = (clone or {}).get("voice_id") or None
        raw_badge = str((body.get("series") or {}).get("badge") or "").strip()
        body["series"] = {"badge": raw_badge[:24]} if raw_badge and auth.tier_at_least(email, "premium") else None
    pid = body.get("project_id")
    with ctx._LOCK:
        # 先判项目已有任务，再消费免费额度。两者与入队共用 ctx._LOCK，
        # 既避免 409 白扣额度，也避免两个同项目请求同时越过检查。
        if pid:
            for j in ctx.JOBS.values():
                if j.get("project_id") == pid and j.get("stage") not in ("done", "failed", "cancelled"):
                    return JSONResponse(
                        {"error": "该项目已有任务在排队/渲染，等它完成再发起新的"},
                        status_code=409)
        if free_email:
            allowed, used = _free_quota_claim(free_email)
            if not allowed:
                return JSONResponse(
                    {"error": f"今天的免费额度（每天 {config.FREE_DAILY_BUILDS} 条）用完了，"
                              f"已用 {used} 条。"
                              f"¥{config.PRICES['premium']} 永久买断，不限量去水印——点右上角「升级」看看",
                     "limited": True},
                    status_code=429)
        job_id = uuid.uuid4().hex[:12]
        ahead = ctx._queue_ahead(job_id)
        ctx.JOBS[job_id] = {"stage": "queued", "stage8": 1, "progress": 3, "error": None, "video": None,
                        "project_id": pid, "owner": email,
                        "free_quota": bool(free_email),
                        "detail": ("排队中 · 前面还有 %d 个任务" % ahead) if ahead
                        else "已加入队列", "t0": time.time()}
        ctx._jobs_save()
        ctx._PENDING[job_id] = body
        ctx._PREP_WAIT.append(job_id)
        ctx._PREP_CV.notify()

    def _tick():
        # 兜底：真实上报缺位时按渐近曲线缓慢推进，避免进度条看起来卡死
        while True:
            time.sleep(3)
            with ctx._LOCK:
                j = ctx.JOBS.get(job_id)
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
                    ctx._jobs_save()
    threading.Thread(target=_tick, daemon=True).start()
    return {"job": job_id}
@router.get("/api/jobs")
def my_jobs(request: Request):
    """当前用户视角的任务：进行中/排队的在前，最近 8 条已完结随后。"""
    with ctx._LOCK:
        reg = ctx._reg()
        visible = {p["project_id"]: p for p in reg["projects"]
                   if ctx._project_visible(p, request)}
        items = []
        for jid, j in ctx.JOBS.items():
            pj = visible.get(j.get("project_id") or "")
            if pj is None:
                continue
            item = {"job_id": jid, "project_id": j.get("project_id"),
                    "title": pj.get("title") or "项目",
                    "stage": j.get("stage"), "stage8": j.get("stage8"),
                    "progress": j.get("progress"), "detail": j.get("detail"),
                    "error": j.get("error"), "t0": j.get("t0")}
            if item["stage"] in ("queued", "prepped"):
                ahead = ctx._queue_ahead(jid)
                if item["stage"] == "prepped":
                    item["detail"] = ("排队生成中 · 前面还有 %d 条" % ahead) if ahead else "马上开始生成"
                else:
                    item["detail"] = ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "马上开始"
                item["queued_pos"] = ahead
            items.append(item)
    active = [i for i in items if i["stage"] not in ("done", "failed", "cancelled")]
    finished = sorted((i for i in items if i["stage"] in ("done", "failed", "cancelled")),
                      key=lambda x: x.get("t0") or 0, reverse=True)[:8]
    out = {"concurrency": ctx._RENDER_STAGE_WORKERS, "active": active, "recent": finished,
           "agent": agenthub.snapshot() if (ctx._is_adminish(request) or ctx._open_mode()) else None}
    return out
@router.get("/api/job/{job_id}")
def job_status(job_id: str, request: Request):
    j = ctx.JOBS.get(job_id)
    if j is None or not ctx._job_visible(j, request):
        return {"stage": "unknown"}   # 不存在与无权同形，不泄露任务存在性
    if j.get("try"):
        # 通用任务接口只给试玩的公开进度；不能把 video/try_video/work_dir
        # 等内部路径借 dict(j) 顺手带出去。样片下载走 /try/<id>.mp4 的专属鉴权。
        out = {key: j.get(key) for key in
               ("stage", "stage8", "progress", "detail", "error")}
    else:
        out = dict(j)
    out.pop("cancel", None)           # 内部旗子不外泄
    if out.get("stage") in ("queued", "prepped"):
        with ctx._LOCK:
            ahead = ctx._queue_ahead(job_id)
        out["queued_pos"] = ahead
        if out.get("stage") == "prepped":
            out["detail"] = ("排队生成中 · 前面还有 %d 条" % ahead) if ahead else "马上开始生成"
        else:
            out["detail"] = ("排队中 · 前面还有 %d 个任务" % ahead) if ahead else "马上开始"
    t0 = out.get("t0")
    # 跑完/失败后冻结耗时，否则"已用"会一直涨（回来再看变成几十小时）。
    # try 的白名单里没有 t0，也就不额外制造 elapsed 字段。
    if t0:
        out["elapsed"] = int((j.get("t_end") or time.time()) - t0)
    return out

@router.post("/api/job/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    """停止任务。排队中的直接移出队列即刻生效；已经在干活的举旗子，
    由渲染轮询循环（1 秒一查，杀进程树）或下一个阶段边界接住。"""
    with ctx._LOCK:
        j = ctx.JOBS.get(job_id)
        if j is None or not ctx._job_visible(j, request):
            return JSONResponse({"error": "任务不存在"}, status_code=404)
        if j.get("stage") in ("done", "failed", "cancelled"):
            return {"ok": True, "stage": j["stage"]}
        stage = j.get("stage")
        before = len(ctx._PREP_WAIT)
        ctx._PREP_WAIT[:] = [x for x in ctx._PREP_WAIT if x != job_id]
        dequeued = len(ctx._PREP_WAIT) < before
        rbefore = len(ctx._RENDER_WAIT)
        ctx._RENDER_WAIT[:] = [e for e in ctx._RENDER_WAIT if e["job"] != job_id]
        dequeued = dequeued or len(ctx._RENDER_WAIT) < rbefore
        j["cancel"] = True
        if dequeued:
            ctx._PENDING.pop(job_id, None)
        # 用户自己停掉也没拿到片子：那次免费额度同样退回去
        if j.get("free_quota") and not j.get("free_refunded"):
            if ctx._usage_refund(j.get("owner") or ""):
                j["free_refunded"] = True
        ctx._jobs_save()
    if dequeued:
        ctx._mark_cancelled(job_id)
        return {"ok": True, "stage": "cancelled"}
    return {"ok": True, "stage": stage}
