"""试玩：落地页让**未登录**的新访客试做一条十几秒的样片。

防滥用是这个模块的第一要务（公开接口 = 谁都能调，而且每次调用真的花 LLM/TTS 钱）：

- **只接受这里列出的选题 id**，素材包路径由这里给出 —— 绝不接受任何用户传入的路径/文件；
- 每个浏览器一次、每个 IP 一天两次（容忍家里多设备）；IP 由调用方给，
  它信不信得过见 `server._client_ip`（XFF 不能由客户端随意编，否则额度等于没有）；
- 出片固定 15 秒以内、降到 720×1280、带 GetCut 水印；
- 限流记录写在 `WORKSPACES/.videogen-try.json`（跟用户库同一个持久卷），
  **键数有上限**：这是公开接口，不设上限就等于让人家用一个脚本撑爆我们的状态文件。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import safestore

ROOT = Path(__file__).resolve().parent.parent          # getcut/
TRY_BUNDLE_ROOT = ROOT / "samples"                     # 试玩素材包随代码走（不用往服务器手工拷）

# 选题表：加一条 = 往 samples/ 里放一个短素材包 + 在这里加一行
TOPICS: list[dict] = [
    {"id": "fed", "title": "白宫喊话降息，美联储反手加息",
     "subtitle": "15 秒资讯短片 · 6 张素材", "bundle": "try-fed", "template": "editorial"},
    {"id": "f35", "title": "美国批 48 架 F-35 给沙特",
     "subtitle": "14 秒 · 数字多、有冲突", "bundle": "try-f35", "template": "data"},
]

COOKIE_LIMIT = 1          # 每个浏览器一次（清掉 cookie 就换不了额度，兜底靠 IP 上限）
IP_LIMIT = 2              # 每个 IP 每天两次
WINDOW_S = 24 * 3600
COOKIE_TTL_S = 30 * 24 * 3600     # 一条浏览器记录留 30 天
MAX_KEYS = 5000                   # 账本每个表的键数上限（约 1MB 封顶）

_LOCK = threading.Lock()          # 账本是读-改-写：不锁就能并发双花额度


def topic(tid: str) -> dict | None:
    return next((t for t in TOPICS if t["id"] == tid), None)


def bundle_dir(t: dict) -> Path:
    """选题对应的素材包目录；必须落在 samples/ 里且是合法素材包。"""
    d = (TRY_BUNDLE_ROOT / t["bundle"]).resolve()
    if TRY_BUNDLE_ROOT.resolve() not in d.parents or not (d / "content.json").is_file():
        raise ValueError("试玩素材包缺失")
    return d


# ---------- 限流账本 ----------
def _store_path(workspaces: Path) -> Path:
    return Path(workspaces) / ".videogen-try.json"


def _load(path: Path) -> dict:
    d = safestore.read_json(path, default={}, shape=lambda x: isinstance(x, dict))
    return {"cookies": d.get("cookies") or {}, "ips": d.get("ips") or {}}


def _newest(items: dict, keep: int) -> dict:
    """只留时间戳最新的 keep 个键。值是时间戳（cookies）或时间戳列表（ips）。"""
    if len(items) <= keep:
        return items

    def stamp(k):
        v = items[k]
        if isinstance(v, list):
            return max(v) if v else 0
        return v if isinstance(v, (int, float)) else 0

    return {k: items[k] for k in sorted(items, key=stamp, reverse=True)[:keep]}


def guard(workspaces: Path, ip: str, cookie: str) -> tuple[bool, str, str]:
    """能不能再试一次。返回 (放行?, 给用户看的话, 本次要记住的浏览器标识)。

    判定与记账在同一把锁里一次做完：先判后记、或者判完再写第二遍，都能被并发钻空子
    （两个请求各自都看到"今天还没用过"，于是一次烧掉两份额度）。
    """
    path = _store_path(workspaces)
    with _LOCK:
        data = _load(path)
        now = time.time()
        if cookie and cookie in data["cookies"]:
            return False, "这个浏览器已经试做过了", ""
        times = [t for t in (data["ips"].get(ip) or []) if now - t < WINDOW_S]
        if len(times) >= IP_LIMIT:
            return False, "今天从这个网络试做的次数用完了", ""
        issued = cookie or ("%012x" % int.from_bytes(os.urandom(6), "big"))
        data["cookies"][issued] = now
        data["ips"][ip] = (times + [now])[-IP_LIMIT * 4:]
        data["cookies"] = _newest(_prune(data["cookies"], now), MAX_KEYS)
        data["ips"] = _newest({k: v for k, v in data["ips"].items()
                               if any(now - t < WINDOW_S for t in v)}, MAX_KEYS)
        try:
            safestore.write_json(path, data, indent=None)
        except Exception:  # noqa: BLE001
            pass
    return True, "", issued


def _prune(records: dict, now: float) -> dict:
    return {k: v for k, v in records.items() if now - v < COOKIE_TTL_S}
