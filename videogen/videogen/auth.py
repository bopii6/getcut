"""邮箱密码登录：用户存储与会话签名（纯标准库，零新增依赖）。

设计取舍：
- 自托管产品的用户量级是个位数，JSON 文件 + PBKDF2 足够，不引入数据库。
- 会话是 HMAC 签名的令牌放 cookie（email|过期时间|签名），服务端无状态；
  签名密钥首次使用时生成并持久化到工作区，容器/进程重启后会话不失效。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path

from . import config

PBKDF2_ITERS = 200_000
SESSION_TTL_SHORT = 7 * 24 * 3600     # 不勾"记住我"：7 天
SESSION_TTL_LONG = 30 * 24 * 3600     # 勾"记住我"：30 天
MIN_PASSWORD_LEN = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

USERS_FILE = Path(config.USERS_FILE)
SECRET_FILE = Path(config.AUTH_SECRET_FILE)


# ---------- 用户存储 ----------

def _load_users() -> list[dict]:
    if not USERS_FILE.is_file():
        return []
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        return data.get("users", []) if isinstance(data, dict) else []
    except Exception:  # noqa: BLE001 - 损坏文件视为无用户，别把登录整个挂掉
        return []


def _save_users(users: list[dict]) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps({"users": users}, ensure_ascii=False, indent=1),
                          encoding="utf-8")


def has_users() -> bool:
    return bool(_load_users())


def user_emails() -> list[str]:
    return [u["email"] for u in _load_users()]


def create_user(email: str, password: str) -> dict:
    """创建用户。非法输入抛 ValueError（信息可直接给前端）。"""
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("邮箱格式不对")
    if len(password or "") < MIN_PASSWORD_LEN:
        raise ValueError(f"密码至少 {MIN_PASSWORD_LEN} 位")
    users = _load_users()
    if any(u["email"] == email for u in users):
        raise ValueError("这个邮箱已经注册过了")
    salt = secrets.token_bytes(16)
    users.append({
        "email": email,
        "salt": salt.hex(),
        "hash": _hash_password(password, salt).hex(),
        "iters": PBKDF2_ITERS,
        "created": time.strftime("%Y-%m-%d"),
    })
    _save_users(users)
    return {"email": email}


def verify_login(email: str, password: str) -> bool:
    email = (email or "").strip().lower()
    user = next((u for u in _load_users() if u["email"] == email), None)
    if not user:
        # 用户不存在也跑一次哈希，避免"响应时间泄露账号是否存在"
        _hash_password(password or "", b"timing-equalizer")
        return False
    salt = bytes.fromhex(user["salt"])
    expect = bytes.fromhex(user["hash"])
    got = _hash_password(password or "", salt, int(user.get("iters", PBKDF2_ITERS)))
    return hmac.compare_digest(got, expect)


def _hash_password(password: str, salt: bytes, iters: int = PBKDF2_ITERS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)


# ---------- 会话签名 ----------

def _secret() -> bytes:
    if SECRET_FILE.is_file():
        return SECRET_FILE.read_bytes().strip()
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    sec = secrets.token_bytes(32)
    SECRET_FILE.write_bytes(sec)
    try:
        SECRET_FILE.chmod(0o600)
    except OSError:
        pass
    return sec


def make_session(email: str, ttl: int = SESSION_TTL_SHORT) -> str:
    exp = int(time.time()) + ttl
    payload = f"{email}|{exp}"
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def read_session(token: str) -> str | None:
    """会话有效返回邮箱，无效返回 None（过期/签名不对/格式不对）。"""
    parts = (token or "").split("|")
    if len(parts) != 3:
        return None
    email, exp, sig = parts
    if not exp.isdigit():
        return None
    expect = hmac.new(_secret(), f"{email}|{exp}".encode("utf-8"),
                      hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        return None
    if int(exp) < time.time():
        return None
    return email
