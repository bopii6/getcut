"""一次性 Agent 账号授权。

Agent 不接收客户密码，也不把设备令牌交给客户复制。Agent 申请一个短时效
授权请求，客户在已登录的 GetCut 页面确认后，服务端才签发绑定该账号的设备令牌。
令牌只通过请求的 poll secret 交回 Agent，且只能领取一次。
"""
from __future__ import annotations

import secrets
import threading
import time

from . import auth, config, safestore

TTL_SECONDS = 10 * 60
MAX_REQUESTS = 200
_STATE_FILE = config.WORKSPACES / ".videogen-agent-authorize.json"
_lock = threading.RLock()
_rate: dict[str, list[float]] = {}


def _shape(data) -> bool:
    return isinstance(data, dict) and isinstance(data.get("requests"), dict)


def _load() -> dict:
    data = safestore.read_json(_STATE_FILE, default={"requests": {}}, shape=_shape)
    now = int(time.time())
    requests = data.get("requests") or {}
    for rid, rec in list(requests.items()):
        if not isinstance(rec, dict) or int(rec.get("expires") or 0) < now:
            requests.pop(rid, None)
    if len(requests) > MAX_REQUESTS:
        keep = sorted(requests.items(), key=lambda x: x[1].get("created", 0), reverse=True)
        requests = dict(keep[:MAX_REQUESTS])
    data["requests"] = requests
    return data


def _save(data: dict) -> None:
    safestore.write_json(_STATE_FILE, data, indent=None, count=lambda d: len(d.get("requests", {})))


def _clean_device(name: str) -> str:
    name = " ".join(str(name or "").split())
    return name[:48] or "电脑 Agent"


def _allowed(ip: str) -> bool:
    now = time.time()
    with _lock:
        recent = [t for t in _rate.get(ip, []) if now - t < 3600]
        if len(recent) >= 20:
            _rate[ip] = recent
            return False
        recent.append(now)
        _rate[ip] = recent
        return True


def start(device: str, ip: str) -> dict:
    if not _allowed(ip):
        raise PermissionError("授权请求太频繁，请十分钟后再试")
    rid = secrets.token_urlsafe(24)
    rec = {
        "request_id": rid,
        "user_code": secrets.token_hex(4).upper(),
        "poll_secret": secrets.token_urlsafe(32),
        "device": _clean_device(device),
        "status": "pending",
        "created": int(time.time()),
        "expires": int(time.time()) + TTL_SECONDS,
        "email": "",
        "token": "",
    }
    with _lock:
        data = _load()
        data["requests"][rid] = rec
        _save(data)
    return {k: rec[k] for k in ("request_id", "user_code", "poll_secret", "device", "expires")}


def info(request_id: str) -> dict | None:
    rid = str(request_id or "").strip()
    if not rid:
        return None
    with _lock:
        rec = _load().get("requests", {}).get(rid)
        if not rec:
            return None
        status = "expired" if int(rec.get("expires") or 0) < int(time.time()) else rec.get("status", "pending")
        return {"request_id": rid, "user_code": rec.get("user_code", ""),
                "device": rec.get("device", "电脑 Agent"), "status": status,
                "expires": rec.get("expires", 0)}


def approve(request_id: str, email: str, ip: str = "") -> dict:
    rid = str(request_id or "").strip()
    email = str(email or "").strip().lower()
    if not rid or not email:
        raise ValueError("授权请求或账号无效")
    with _lock:
        data = _load()
        rec = data.get("requests", {}).get(rid)
        if not rec:
            raise LookupError("授权请求不存在或已过期")
        if int(rec.get("expires") or 0) < int(time.time()):
            rec["status"] = "expired"
            _save(data)
            raise LookupError("授权请求已过期")
        if rec.get("status") == "approved":
            raise ValueError("这台电脑已经授权过了")
        token = auth.make_session(email, ttl=90 * 24 * 3600,
                                   device=rec.get("device") or "电脑 Agent", ip=ip)
        rec.update({"status": "approved", "email": email, "token": token,
                    "approved": int(time.time())})
        _save(data)
        return {"ok": True, "status": "approved", "email": email,
                "device": rec.get("device", "电脑 Agent")}


def poll(request_id: str, poll_secret: str) -> dict:
    rid = str(request_id or "").strip()
    secret = str(poll_secret or "").strip()
    with _lock:
        data = _load()
        rec = data.get("requests", {}).get(rid)
        if not rec or not secrets.compare_digest(str(rec.get("poll_secret") or ""), secret):
            return {"status": "not_found"}
        if int(rec.get("expires") or 0) < int(time.time()):
            rec["status"] = "expired"
            _save(data)
            return {"status": "expired"}
        status = rec.get("status", "pending")
        if status != "approved":
            return {"status": status, "device": rec.get("device", "电脑 Agent")}
        out = {"status": "approved", "email": rec.get("email", ""),
               "device": rec.get("device", "电脑 Agent"), "token": rec.get("token", "")}
        rec["status"] = "consumed"
        rec["token"] = ""
        _save(data)
        return out
