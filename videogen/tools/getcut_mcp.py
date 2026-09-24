# -*- coding: utf-8 -*-
"""GetCut MCP server：把工作台的「投喂 → 渲染 → 取片」变成 Agent 可直接调用的工具。

方案 1 的电脑 Agent 流程：
    upload_bundle(素材包.zip) → 返回手机短链 → 停止
手机负责导入、确认和提交；电脑成片台负责后台渲染。

配置（优先级：环境变量 > videogen/.env）：
    GETCUT_BASE   工作台地址，默认 https://gc.hellojoy.top
    GETCUT_TOKEN  兼容旧配置：已有设备令牌或管理员主钥匙。新客户优先使用
                  authorize_getcut() 授权，授权令牌会安全写入本地授权文件。
    GETCUT_EMAIL  兼容旧配置：仅主钥匙通道可代填；普通账号令牌忽略它

宿主接入（ZCode 等）：项目根 .mcp.json
    {"mcpServers": {"getcut": {"command": "python",
                               "args": ["<仓库>/videogen/tools/getcut_mcp.py"]}}}

跑站需要：pip install mcp requests（本仓库 requirements 不含 mcp，按需自装）。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
from mcp.server.mcpserver import MCPServer

# 仓库根（tools/ 的上一级）
_REPO = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    """没有 python-dotenv 就手撸一个极简解析：KEY=VALUE，# 注释跳过。"""
    env_file = _REPO / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_env_file()

BASE = (os.environ.get("GETCUT_BASE") or "https://gc.hellojoy.top").rstrip("/")
ENV_TOKEN = os.environ.get("GETCUT_TOKEN") or ""
EMAIL = (os.environ.get("GETCUT_EMAIL") or "").strip().lower()
AUTH_FILE = Path(os.environ.get("GETCUT_AUTH_FILE")
                 or (Path.home() / ".getcut" / "agent-auth.json"))
PENDING_FILE = AUTH_FILE.with_name(AUTH_FILE.stem + "-pending.json")


def _read_local(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, ValueError):
        return {}


def _write_local(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _saved_token() -> str:
    return str(_read_local(AUTH_FILE).get("token") or "").strip()


def _current_token() -> str:
    return ENV_TOKEN.strip() or _saved_token()


def _clear_pending() -> None:
    try:
        PENDING_FILE.unlink(missing_ok=True)
    except OSError:
        pass

mcp = MCPServer(
    name="getcut",
    instructions=(
        "GetCut 短视频工作台：先通过 authorize_getcut() 让客户在已登录的 GetCut 页面授权；"
        "只有用户明确确认上传后，才把 getcut-bundle 做好的 zip 上传到该账号的云端收件箱，"
        "然后返回手机短链并停止。不要替用户 claim、确认内容、提交生成或下载成片。"
    ),
)


def _session() -> requests.Session:
    s = requests.Session()
    token = _current_token()
    if token:
        # 新授权得到的设备令牌只走 x-agent-token；只有显式旧配置里的
        # GETCUT_TOKEN 才兼容主钥匙通道，避免把用户令牌误当全站钥匙。
        s.headers["x-agent-token"] = token
        if ENV_TOKEN.strip():
            s.headers["x-auth-token"] = ENV_TOKEN.strip()
    return s


def _public_session() -> requests.Session:
    return requests.Session()


def _public_api(method: str, path: str, **kw) -> dict:
    r = _public_session().request(method, BASE + path, timeout=kw.pop("timeout", 180), **kw)
    try:
        d = r.json()
    except ValueError as exc:
        raise RuntimeError(f"{path} HTTP {r.status_code}（非 JSON 响应）") from exc
    if r.status_code >= 400:
        raise RuntimeError(f"{path} HTTP {r.status_code}: {d.get('error') or d}")
    return d


@mcp.tool()
def authorize_getcut() -> dict:
    """创建一次性授权链接；客户需在已登录的 GetCut 页面点击“授权这台电脑”。"""
    out = _public_api("POST", "/api/agent/authorize/start",
                      json={"device": "GetCut Agent"})
    _write_local(PENDING_FILE, {
        "request_id": out["request_id"],
        "poll_secret": out["poll_secret"],
        "created": int(time.time()),
    })
    return {"status": "awaiting_authorization", "authorization_url": out["url"],
            "user_code": out["user_code"], "expires_at": out["expires"],
            "next": "请客户打开授权链接，在已登录的 GetCut 页面点击“授权这台电脑”"}


@mcp.tool()
def getcut_authorization_status() -> dict:
    """查询授权结果；令牌只在 Agent 本地保存，不回显给用户。"""
    pending = _read_local(PENDING_FILE)
    rid = str(pending.get("request_id") or "")
    secret = str(pending.get("poll_secret") or "")
    if not rid or not secret:
        return {"status": "not_started", "next": "先调用 authorize_getcut()"}
    out = _public_api("POST", "/api/agent/authorize/poll",
                      json={"request_id": rid, "poll_secret": secret})
    if out.get("status") == "approved":
        _write_local(AUTH_FILE, {"token": out.get("token", ""),
                                  "email": out.get("email", ""),
                                  "device": out.get("device", "GetCut Agent"),
                                  "authorized_at": int(time.time())})
        _clear_pending()
        return {"status": "authorized", "email": out.get("email", ""),
                "device": out.get("device", "GetCut Agent"),
                "next": "授权完成；后续只有用户明确确认上传时才会发送 ZIP"}
    return {"status": out.get("status", "pending"),
            "next": "等待客户在 GetCut 页面点击授权"}


def _api(method: str, path: str, **kw) -> dict:
    r = _session().request(method, BASE + path, timeout=kw.pop("timeout", 180), **kw)
    try:
        d = r.json()
    except ValueError as exc:
        raise RuntimeError(f"{path} HTTP {r.status_code}（非 JSON 响应）") from exc
    if r.status_code >= 400:
        raise RuntimeError(f"{path} HTTP {r.status_code}: {d.get('error') or d}")
    return d


@mcp.tool()
def getcut_account() -> dict:
    """检查当前 GetCut 设备令牌对应的账号；未登录时明确失败。

    电脑 Agent 不能只看本地有没有 ZIP，就默认它属于某个账号。必须先用这张
    账号设备令牌向服务器确认身份；服务器确认后，上传才会绑定到这个账号。
    """
    if not _current_token():
        raise RuntimeError("这台电脑还没有授权 GetCut；先调用 authorize_getcut()")
    return _api("GET", "/api/agent/whoami")


@mcp.tool()
def upload_bundle(zip_path: str, user_confirmed: bool = False) -> dict:
    """用户明确确认后，才把素材包上传到当前账号空间。

    `user_confirmed=True` 只能由用户在对话里明确点击/说“上传”后传入。默认
    False 时只检查本地 ZIP，不申请收件票、不上传；这样公开 Skills 不会在
    用户还没确认账号和上传动作时把文件送到服务器。
    """
    p = Path(zip_path)
    if not p.is_file():
        raise RuntimeError(f"找不到文件：{zip_path}")
    if not user_confirmed:
        return {"status": "awaiting_confirmation", "zip_path": str(p),
                "next": "素材包已在本地完成；请用户确认登录账号后点击“上传”"}
    account = getcut_account()
    tk = _api("POST", "/api/intake/ticket", json={})
    with open(p, "rb") as f:
        r = _session().put(tk["put_url"], data=f, params={"name": p.name}, timeout=600)
    try:
        sent = r.json()
    except ValueError:
        raise RuntimeError(f"上传收件地址 HTTP {r.status_code}（非 JSON 响应）") from None
    if r.status_code >= 400:
        raise RuntimeError(f"上传失败 HTTP {r.status_code}: {sent.get('error') or sent}")
    return {"status": "uploaded", "account": account.get("email"),
            "code": tk.get("code"), "intake_url": tk.get("url"),
            "url": tk.get("url"), "expires_at": tk.get("expiresAt"),
            "bytes": sent.get("bytes") or p.stat().st_size,
            "next": "请在手机登录同一账号，看到“已送达”后点击导入"}


@mcp.tool()
def feed_bundle(zip_path: str) -> dict:
    """领一张收件地址 → 把素材包 PUT 上去 → 认领成自己的项目。

    zip 是 getcut-bundle 技能产出的素材包（content.json 在根目录），
    路径是本机绝对路径。凭据只有配置里那一张**账号设备令牌**（GETCUT_TOKEN），
    不再要站点主钥匙。认领后项目挂好包，随时可以 submit_render；
    返回的 intake_url 就是 /i/<码>，同一账号在手机打开它也能接着往下走。
    """
    p = Path(zip_path)
    if not p.is_file():
        raise RuntimeError(f"找不到文件：{zip_path}")
    getcut_account()  # 兼容入口也不能绕过真实账号授权
    tk = _api("POST", "/api/intake/ticket",
              json={"email": EMAIL} if EMAIL else {})
    with open(p, "rb") as f:
        r = _session().put(tk["put_url"], data=f, params={"name": p.name}, timeout=600)
    try:
        sent = r.json()
    except ValueError:
        raise RuntimeError(f"上传收件地址 HTTP {r.status_code}（非 JSON 响应）") from None
    if r.status_code >= 400:
        raise RuntimeError(f"上传失败 HTTP {r.status_code}: {sent.get('error') or sent}")
    claim = _api("POST", f"/api/intake/{tk['code']}/claim",
                 json={"email": EMAIL} if EMAIL else {})
    return {"project_id": claim["project_id"], "bundle": claim["name"],
            "title": claim["title"], "intake_url": tk.get("url"),
            "expires_at": tk.get("expiresAt")}


@mcp.tool()
def list_voices() -> list:
    """可用音色清单。id 传给 submit_render 的 voice；'@clone' 是「我的声音」。"""
    return _api("GET", "/api/voices")


@mcp.tool()
def list_projects() -> list:
    """工作台里的项目列表（含可用的 bundle 名）。"""
    return _api("GET", "/api/projects")


@mcp.tool()
def submit_render(project_id: str, voice: str = "xiaoxia", format: str = "",
                  bgm: str = "", use_llm: bool = True) -> dict:
    """提交渲染。voice 见 list_voices（'@clone'=我的声音）；format 缺省走项目默认模板；
    bgm 传曲名或留空自动配。返回 {job_id}，用 job_status / wait_for_job 盯进度。"""
    projects = _api("GET", "/api/projects")
    proj = next((p for p in projects if p.get("project_id") == project_id), None)
    if not proj:
        raise RuntimeError(f"项目不存在：{project_id}")
    bundle = proj.get("bundle")
    if not bundle:
        raise RuntimeError("该项目没挂素材包，先 feed_bundle")
    body = {"project_id": project_id, "bundle": bundle, "voice": voice,
            "subtitles": True, "sources": True, "sfx": True, "use_llm": use_llm}
    if format:
        body["format"] = format
    if bgm:
        body["bgm"] = bgm
    if EMAIL:
        body["email"] = EMAIL
    d = _api("POST", "/api/build", json=body)
    return {"job_id": d.get("job"), "project_id": project_id, "bundle": bundle}


@mcp.tool()
def job_status(job_id: str) -> dict:
    """查渲染进度：stage（queued/tts/plan/…/done/failed）、百分比、人话 detail。"""
    d = _api("GET", f"/api/job/{job_id}")
    return {"job_id": job_id, "stage": d.get("stage"), "stage8": d.get("stage8"),
            "progress": d.get("progress"), "detail": d.get("detail"),
            "error": d.get("error"), "video": d.get("video"),
            "try_video": d.get("try_video")}


@mcp.tool()
def wait_for_job(job_id: str, timeout_s: int = 900) -> dict:
    """阻塞等渲染结束（done / failed），每 6 秒查一次。渲染一般 3-10 分钟。"""
    deadline = time.time() + max(30, min(int(timeout_s), 1800))
    last = {}
    while time.time() < deadline:
        last = job_status(job_id)
        if last.get("stage") in ("done", "failed", "unknown"):
            return last
        time.sleep(6)
    last["timeout"] = True
    return last


@mcp.tool()
def download_video(job_id: str, dest_path: str) -> dict:
    """把 job_id 的成片 MP4 下载到本机 dest_path（绝对路径）。"""
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _session().get(BASE + f"/video/{job_id}", stream=True, timeout=600) as r:
        if r.status_code >= 400:
            raise RuntimeError(f"/video/{job_id} HTTP {r.status_code}")
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 18):
                f.write(chunk)
    return {"saved": str(dest), "bytes": dest.stat().st_size}


def _unwrap(r: requests.Response, path: str) -> dict:
    try:
        d = r.json()
    except ValueError as exc:
        raise RuntimeError(f"{path} HTTP {r.status_code}（非 JSON 响应）") from exc
    if r.status_code >= 400:
        raise RuntimeError(f"{path} HTTP {r.status_code}: {d.get('error') or d}")
    return d


if __name__ == "__main__":
    mcp.run(transport="stdio")
