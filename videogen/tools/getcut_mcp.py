# -*- coding: utf-8 -*-
"""GetCut MCP server：把工作台的「投喂 → 渲染 → 取片」变成 Agent 可直接调用的工具。

Agent 全流程（不再开浏览器、不再碰网站 UI）：
    feed_bundle(素材包.zip) → submit_render(project_id, voice=…) → wait_for_job(job_id)
    → download_video(job_id, 保存路径)

配置（优先级：环境变量 > videogen/.env）：
    GETCUT_BASE   工作台地址，默认 https://gc.hellojoy.top
    GETCUT_TOKEN  **这个账号自己的**设备令牌（不是服务器 .env 里那把站点主钥匙：
                  主钥匙能领走并看见全站任何客户的素材与成片，不该出现在客户机器上）。
                  要一张：在登录了的浏览器里 POST /api/agent/login（邮箱+密码），
                  或让站长在「登录设备」里发一张；它随时可以在页面上单独踢掉。
    GETCUT_EMAIL  以哪个账号行事（只有主钥匙能代填，普通账号令牌忽略它）

宿主接入（ZCode 等）：项目根 .mcp.json
    {"mcpServers": {"getcut": {"command": "python",
                               "args": ["<仓库>/videogen/tools/getcut_mcp.py"]}}}

跑站需要：pip install mcp requests（本仓库 requirements 不含 mcp，按需自装）。
"""
from __future__ import annotations

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
TOKEN = os.environ.get("GETCUT_TOKEN") or ""
EMAIL = (os.environ.get("GETCUT_EMAIL") or "").strip().lower()

mcp = MCPServer(
    name="getcut",
    instructions=(
        "GetCut 短视频工作台：把 getcut-bundle 技能做好的素材包 zip 投进工作台、"
        "提交渲染、盯进度、下载成片。先 feed_bundle，再 submit_render（voice 可传 "
        "list_voices 里的任意 id，'@clone' 代表「我的声音」），wait_for_job 等出片，"
        "download_video 拿 MP4。"
    ),
)


def _session() -> requests.Session:
    s = requests.Session()
    # 两张头都带：x-auth-token 是主钥匙通道（站长自己用），x-agent-token 是
    # **账号自己的设备令牌** —— 客户机器上只该填后者：在「登录设备」里看得见、
    # 能单独踢掉，泄露了也只波及那一个账号，而不是整站所有人的片子。
    s.headers["x-auth-token"] = TOKEN
    s.headers["x-agent-token"] = TOKEN
    return s


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
