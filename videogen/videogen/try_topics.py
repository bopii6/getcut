"""试玩：落地页让**未登录**的新访客试做一条十几秒的样片。

防滥用是这个模块的第一要务（公开接口 = 谁都能调）：

- **只接受这里列出的选题 id**，素材包路径由这里给出——绝不接受任何用户传入的路径/文件；
- 每个浏览器 cookie 一次、每个 IP 一天两次（容忍家里多设备）；
- 出片固定 15 秒以内、降到 720×1280、带 GetCut 水印；
- 限流记录写在 `WORKSPACES/.videogen-try.json`（跟用户库同一个持久卷）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import safestore

ROOT = Path(__file__).resolve().parent.parent          # videogen/
TRY_BUNDLE_ROOT = ROOT / "samples"                     # 试玩素材包随代码走（不用往服务器手工拷）

# 选题表：加一条 = 往 samples/ 里放一个短素材包 + 在这里加一行
TOPICS: list[dict] = [
    {"id": "fed", "title": "白宫喊话降息，美联储反手加息",
     "subtitle": "15 秒资讯短片 · 6 张素材", "bundle": "try-fed", "template": "editorial"},
    {"id": "f35", "title": "美国批 48 架 F-35 给沙特",
     "subtitle": "14 秒 · 数字多、有冲突", "bundle": "try-f35", "template": "data"},
]

COOKIE_LIMIT = 1          # 每个浏览器一次
IP_LIMIT = 2              # 每个 IP 每天两次
WINDOW_S = 24 * 3600


def topic(tid: str) -> dict | None:
    return next((t for t in TOPICS if t["id"] == tid), None)


def bundle_dir(t: dict) -> Path:
    """选题对应的素材包目录；必须落在 samples/ 里且是合法素材包。"""
    d = (TRY_BUNDLE_ROOT / t["bundle"]).resolve()
    if TRY_BUNDLE_ROOT.resolve() not in d.parents or not (d / "content.json").is_file():
        raise ValueError("试玩素材包缺失")
    return d


def remember_cookie(workspaces: Path, cookie: str) -> None:
    """把发给浏览器的 cookie 记进限流账本。

    第一次请求没有 cookie，我们发一个新的；如果不记账，同一个浏览器第二次来
    就拦不住（只靠 IP 的话还能再蹭一次）。
    """
    if not cookie:
        return
    path = _store_path(workspaces)
    data = _load(path)
    data["cookies"][cookie] = time.time()
    try:
        safestore.write_json(path, data, indent=None)
    except Exception:  # noqa: BLE001
        pass


# ---------- 限流 ----------
def _store_path(workspaces: Path) -> Path:
    return Path(workspaces) / ".videogen-try.json"


def _load(path: Path) -> dict:
    d = safestore.read_json(path, default={}, shape=lambda x: isinstance(x, dict))
    return {"cookies": d.get("cookies") or {}, "ips": d.get("ips") or {}}


def guard(workspaces: Path, ip: str, cookie: str) -> tuple[bool, str]:
    """能不能再试一次。通过就立刻记账（先扣后跑，避免并发绕限流）。"""
    path = _store_path(workspaces)
    data = _load(path)
    now = time.time()
    if cookie and cookie in data["cookies"]:
        return False, "这个浏览器已经试做过了"
    times = [t for t in (data["ips"].get(ip) or []) if now - t < WINDOW_S]
    if len(times) >= IP_LIMIT:
        return False, "今天从这个网络试做的次数用完了"
    if cookie:
        data["cookies"][cookie] = now
    times.append(now)
    data["ips"][ip] = times[-8:]
    # 顺手清掉过期的 cookie 记录，文件不会越滚越大
    data["cookies"] = {k: v for k, v in data["cookies"].items() if now - v < 30 * 24 * 3600}
    try:
        safestore.write_json(path, data, indent=None)
    except Exception:  # noqa: BLE001
        pass
    return True, ""
