"""上传、认领、构建任务与任务查询（最容易出错的一段：路径、配额、并发）。

从 server.py 按域拆出来的路由。
路由**注册顺序**由 server 里的 include_router 顺序决定（按各域首条路由行号
排序），改动顺序前先看 tests/test_route_order.py 的检查 —— 顺序反了会被通配路由吃掉。
"""
from __future__ import annotations

import io
import json
import math
import shutil
import re
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

from .. import ctx

from fastapi import APIRouter

router = APIRouter()

MAX_UPLOAD_BYTES = 512 * 1024 * 1024          # 单个 zip 上限 512MB
MAX_EXTRACT_BYTES = 2 * 1024 * 1024 * 1024    # 解压后总上限 2GB（防 zip 炸弹）
INTAKE_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
def _effective_email(request: Request, body_email=None) -> str | None:
    """会话优先；访问令牌是主钥匙，可代 body.email 指定的账号行事（脚本/MCP 通道）。

    令牌持有者本就 adminish（可见一切），这里只是把品牌套件/声音克隆/档位
    这些「跟账号走」的逻辑对脚本侧放开——没有令牌的光 body.email 一律无效。"""
    email = ctx._session_email(request)
    if not email and body_email and ctx._token_ok(request):
        return str(body_email).strip().lower()
    return email
def _usage_today(email: str) -> int:
    """今天已经记了几条（只读，不动账本）。"""
    return int(((ctx._usage_load().get(email) or {}).get(time.strftime("%Y-%m-%d")) or 0))
def _free_quota_check(email: str) -> tuple[bool, int]:
    """免费档还能不能出这一条 + 今天已用几条。判额度只读，记账留给放行之后。"""
    used = _usage_today(email)
    return used < config.FREE_DAILY_BUILDS, used
def _usage_bump(email: str) -> int:
    """记一次出片，返回今天已用次数。只留最近 3 天，防文件长大。"""
    today = time.strftime("%Y-%m-%d")
    keep = {today, time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)),
            time.strftime("%Y-%m-%d", time.localtime(time.time() - 172800))}
    with ctx._LOCK:
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
# 各长阶段的进度区间（真实上报缺位时，用渐近曲线兜底爬升，既不冻住也不会跑飞）
_STAGE_SPAN = {"tts": (6, 16), "plan": (16, 30), "props": (30, 40),
               "render": (40, 78), "audio": (78, 88), "mux": (88, 93), "verify": (93, 99)}
_TICK_TAU = 130.0        # 时间常数（秒）：约 2 分钟后走完该阶段 60%，之后越来越慢
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
@router.post("/api/upload")
async def upload(file: UploadFile, request: Request):
    name = Path(_fix_mojibake_name(file.filename or "bundle.zip")).stem or f"bundle-{int(time.time())}"
    try:
        data = await _read_capped(file, MAX_UPLOAD_BYTES)
    except ValueError:
        return JSONResponse({"error": "zip 超过 512MB 上限"}, status_code=413)
    dest = ctx.WORKSPACES / name
    i = 1
    while dest.exists():
        dest = ctx.WORKSPACES / f"{name}-{i}"
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
    meta = ctx._bundles_meta()
    meta[dest.name] = {"owner": ctx._session_email(request), "created": time.strftime("%Y/%m/%d %H:%M")}
    ctx._bundles_meta_save(meta)
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
@router.post("/api/intake")
async def intake_create(file: UploadFile, request: Request):
    ip = ctx._client_ip(request)
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
    ctx.INTAKES.mkdir(parents=True, exist_ok=True)
    ctx._sweep_intakes()
    code = uuid.uuid4().hex[:12]
    zf_path, side = _intake_paths(code)
    zf_path.write_bytes(data)
    side.write_text(json.dumps({"file": _fix_mojibake_name(file.filename or "bundle.zip"),
                                "created": now, "ip": ip}, ensure_ascii=False),
                    encoding="utf-8")
    base = config.PUBLIC_BASE_URL or f"{request.url.scheme}://{request.url.netloc}"
    return {"code": code, "url": f"{base}/i/{code}"}
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
    zf_path, side_path = _intake_paths(code)
    if not zf_path.is_file():
        side = _intake_sidecar(code)
        if side.get("project_id"):
            return JSONResponse({"error": "这个素材包已被导入过了", "projectId": side["project_id"]},
                                status_code=409)
        return JSONResponse({"error": "链接已失效（素材包 24 小时内有效）"}, status_code=404)
    email = _effective_email(request, (body or {}).get("email"))
    if not email and not ctx._open_mode():
        return JSONResponse({"error": "先登录或注册，再导入素材包"}, status_code=401)
    side = _intake_sidecar(code)
    orig_name = Path(_fix_mojibake_name(side.get("file") or "bundle.zip")).stem or "bundle"
    name = re.sub(r'[\\/:*?"<>|]', "", orig_name).strip() or "bundle"
    dest = ctx.WORKSPACES / name
    i = 1
    while dest.exists():
        dest = ctx.WORKSPACES / f"{name}-{i}"
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
    meta = ctx._bundles_meta()
    meta[dest.name] = {"owner": email, "created": time.strftime("%Y/%m/%d %H:%M")}
    ctx._bundles_meta_save(meta)
    with ctx._LOCK:
        reg = ctx._reg()
        pid = uuid.uuid4().hex[:12]
        reg["projects"].append({"project_id": pid, "title": dest.name, "bundle": dest.name,
                                "created": time.strftime("%Y/%m/%d"), "renders": [],
                                "owner": email})
        ctx._reg_save(reg)
    side["claimed"] = True
    side["claimed_at"] = time.time()
    side["project_id"] = pid
    side_path.write_text(json.dumps(side, ensure_ascii=False), encoding="utf-8")
    zf_path.unlink(missing_ok=True)
    return {"name": dest.name, "project_id": pid, "title": dest.name}
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
        body["brand"] = ctx._brand_for(email)   # 高级档品牌套件，服务端自动带上（默认配置固化）
        if body.get("voice") == "@clone":
            clone = brand_kit.clone_info(email) if auth.tier_at_least(email, "premium") else None
            body["voice"] = (clone or {}).get("voice_id") or None
        raw_badge = str((body.get("series") or {}).get("badge") or "").strip()
        body["series"] = {"badge": raw_badge[:24]} if raw_badge and auth.tier_at_least(email, "premium") else None
    pid = body.get("project_id")
    with ctx._LOCK:
        if pid:
            for j in ctx.JOBS.values():
                if j.get("project_id") == pid and j.get("stage") not in ("done", "failed", "cancelled"):
                    return JSONResponse(
                        {"error": "该项目已有任务在排队/渲染，等它完成再发起新的"},
                        status_code=409)
        job_id = uuid.uuid4().hex[:12]
        ahead = ctx._queue_ahead(job_id)
        ctx.JOBS[job_id] = {"stage": "queued", "stage8": 1, "progress": 3, "error": None, "video": None,
                        "project_id": pid, "owner": email,
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
    # 跑完/失败后冻结耗时，否则"已用"会一直涨（回来再看变成几十小时）
    out["elapsed"] = int((out.get("t_end") or time.time()) - t0) if t0 else None
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
        ctx._jobs_save()
    if dequeued:
        ctx._mark_cancelled(job_id)
        return {"ok": True, "stage": "cancelled"}
    return {"ok": True, "stage": stage}
