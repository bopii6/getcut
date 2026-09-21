"""邮箱密码登录：注册验证码、用户存储与会话签名（纯标准库，零新增依赖）。

设计取舍：
- 自托管产品的用户量级是个位数，JSON 文件 + PBKDF2 足够，不引入数据库。
- 注册走邮箱验证码（输邮箱→收码→验证→设密码）；验证码在内存里，重启即失效。
- 会话是 HMAC 签名的令牌放 cookie（email|过期时间|签名），服务端无状态；
  签名密钥首次使用时生成并持久化到工作区，容器/进程重启后会话不失效。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import re
import secrets
import smtplib
import time
from email.header import Header
from email.mime.text import MIMEText
from pathlib import Path

from . import config, safestore

PBKDF2_ITERS = 200_000
SESSION_TTL_SHORT = 7 * 24 * 3600     # 不勾"记住我"：7 天
SESSION_TTL_LONG = 30 * 24 * 3600     # 勾"记住我"：30 天
MIN_PASSWORD_LEN = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

USERS_FILE = Path(config.USERS_FILE)
SECRET_FILE = Path(config.AUTH_SECRET_FILE)

# ---------- 验证码 ----------
CODE_TTL = 600          # 10 分钟有效
RESEND_COOLDOWN = 60    # 两次发送至少间隔 60 秒
MAX_ATTEMPTS = 5        # 一个验证码最多试 5 次
_codes: dict[str, dict] = {}

# 按 IP 限发：验证码接口是公开的，单邮箱冷却挡不住"换邮箱轰炸"，
# 会烧掉发信邮箱的配额甚至被封号。每 IP 每小时最多发 10 封（内存记账，重启清零）。
IP_SEND_LIMIT = 10
IP_SEND_WINDOW = 3600
_ip_sends: dict[str, list[float]] = {}


def ip_can_send(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _ip_sends.get(ip, []) if now - t < IP_SEND_WINDOW]
    _ip_sends[ip] = recent
    return len(recent) < IP_SEND_LIMIT


def ip_record_send(ip: str) -> None:
    _ip_sends.setdefault(ip, []).append(time.time())


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def smtp_ready() -> bool:
    return bool(config.EMAIL_SMTP_HOST and config.EMAIL_SMTP_USER
                and config.EMAIL_SMTP_PASS)


def issue_code(email: str, purpose: str = "注册") -> tuple[bool, str]:
    """生成并发送验证码。返回 (是否成功, 给用户看的提示)。"""
    email = _norm_email(email)
    if not EMAIL_RE.match(email):
        return False, "邮箱格式不对"
    prev = _codes.get(email)
    if prev and time.time() - prev["sent_at"] < RESEND_COOLDOWN:
        wait = int(RESEND_COOLDOWN - (time.time() - prev["sent_at"]))
        return False, f"发送太频繁，{wait} 秒后再试"
    code = f"{random.randint(0, 999999):06d}"
    _codes[email] = {"code": code, "exp": time.time() + CODE_TTL,
                     "attempts": 0, "sent_at": time.time()}
    if smtp_ready():
        try:
            _smtp_send(email, code, purpose)
            return True, "验证码已发送，请查收邮箱（注意垃圾箱）"
        except Exception as e:  # noqa: BLE001 - 发信失败要给用户明确反馈
            _codes.pop(email, None)
            return False, f"验证码发送失败：{e}"
    if config.DEV_EMAIL_FALLBACK:
        return True, f"（本机开发模式，未配邮箱）验证码：{code}"
    return False, "邮箱服务尚未配置，请联系管理员"


def check_code(email: str, code: str) -> bool:
    email = _norm_email(email)
    rec = _codes.get(email)
    if not rec:
        return False
    if time.time() > rec["exp"]:
        _codes.pop(email, None)
        return False
    rec["attempts"] += 1
    if rec["attempts"] > MAX_ATTEMPTS:
        _codes.pop(email, None)
        return False
    if not hmac.compare_digest(str(code or "").strip(), rec["code"]):
        return False
    _codes.pop(email, None)   # 验证通过即作废，不可复用
    return True


def _smtp_send(to: str, code: str, purpose: str = "注册") -> None:
    host = config.EMAIL_SMTP_HOST
    port = int(config.EMAIL_SMTP_PORT or "465")
    user, pwd = config.EMAIL_SMTP_USER, config.EMAIL_SMTP_PASS
    msg = MIMEText(
        f"你的 GetCut {purpose}验证码是 {code}，{CODE_TTL // 60} 分钟内有效。\n\n"
        "如果这不是你本人的操作，请忽略本邮件。", "plain", "utf-8")
    msg["Subject"] = Header(f"GetCut {purpose}验证码", "utf-8")
    msg["From"] = config.EMAIL_FROM or user
    msg["To"] = to
    if port == "465" or str(port) == "465":
        server = smtplib.SMTP_SSL(host, int(port), timeout=20)
    else:
        server = smtplib.SMTP(host, int(port), timeout=20)
        server.starttls()
    try:
        server.login(user, pwd)
        server.sendmail(config.EMAIL_FROM or user, [to], msg.as_string())
    finally:
        server.quit()


# ---------- 用户存储 ----------

def _load_users() -> list[dict]:
    """读账号表。坏了先自愈（留现场 + 从每日备份恢复），救不回来就抛 ——
    这里绝不能返回 []：调用方紧接着就会把"空 + 新客户"写回盘，把整份名单冲掉。
    """
    data = safestore.read_json(
        USERS_FILE, default={"users": []},
        shape=lambda d: isinstance(d, dict) and isinstance(d.get("users"), list))
    return data.get("users", [])


def _save_users(users: list[dict]) -> None:
    safestore.write_json(USERS_FILE, {"users": users},
                         count=lambda d: len(d.get("users") or []))


def has_users() -> bool:
    return bool(_load_users())


def is_admin(email: str | None) -> bool:
    email = _norm_email(email)
    return any(u["email"] == email and u.get("role") == "admin"
               for u in _load_users())


def admin_email() -> str | None:
    for u in _load_users():
        if u.get("role") == "admin":
            return u["email"]
    return None


def user_emails() -> list[str]:
    return [u["email"] for u in _load_users()]


def create_user(email: str, password: str, role: str = "user") -> dict:
    """创建用户。非法输入抛 ValueError（信息可直接给前端）。"""
    email = _norm_email(email)
    if not EMAIL_RE.match(email):
        raise ValueError("邮箱格式不对")
    if len(password or "") < MIN_PASSWORD_LEN:
        raise ValueError(f"密码至少 {MIN_PASSWORD_LEN} 位")
    users = _load_users()
    if any(u["email"] == email for u in users):
        raise ValueError("这个邮箱已经注册过了，直接登录吧")
    salt = secrets.token_bytes(16)
    users.append({
        "email": email,
        "salt": salt.hex(),
        "hash": _hash_password(password, salt).hex(),
        "iters": PBKDF2_ITERS,
        "role": role,
        "created": time.strftime("%Y-%m-%d"),
    })
    _save_users(users)
    return {"email": email, "role": role}


def user_exists(email: str) -> bool:
    email = _norm_email(email)
    return any(u["email"] == email for u in _load_users())


def set_password(email: str, password: str) -> None:
    """重设密码（忘记密码走这里）。非法输入抛 ValueError（信息可直接给前端）。"""
    email = _norm_email(email)
    if not EMAIL_RE.match(email):
        raise ValueError("邮箱格式不对")
    if len(password or "") < MIN_PASSWORD_LEN:
        raise ValueError(f"密码至少 {MIN_PASSWORD_LEN} 位")
    users = _load_users()
    user = next((u for u in users if u["email"] == email), None)
    if user is None:
        raise ValueError("这个邮箱还没注册过")
    salt = secrets.token_bytes(16)
    user["salt"] = salt.hex()
    user["hash"] = _hash_password(password, salt).hex()
    user["iters"] = PBKDF2_ITERS
    user["pw_reset"] = time.strftime("%Y-%m-%d %H:%M")
    _save_users(users)


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


# ---------- 档位（卡密买断制） ----------
TIER_RANK = {"free": 0, "basic": 1, "premium": 2}
TIER_LABEL = {"free": "免费版", "basic": "基础版", "premium": "高级版"}


def user_tier(email: str | None) -> str:
    """用户档位。管理员视为高级版（自己人看得到全部功能）。没登录 = free。"""
    email = _norm_email(email)
    if not email:
        return "free"
    for u in _load_users():
        if u["email"] == email:
            if u.get("role") == "admin":
                return "premium"
            return u.get("tier") if u.get("tier") in TIER_RANK else "free"
    return "free"


def set_tier(email: str, tier: str) -> None:
    if tier not in TIER_RANK:
        raise ValueError(f"未知档位 {tier}")
    email = _norm_email(email)
    users = _load_users()
    user = next((u for u in users if u["email"] == email), None)
    if user is None:
        raise ValueError("这个邮箱还没注册过")
    user["tier"] = tier
    user["tier_since"] = time.strftime("%Y-%m-%d %H:%M")
    _save_users(users)


def tier_at_least(email: str | None, need: str) -> bool:
    return TIER_RANK[user_tier(email)] >= TIER_RANK.get(need, 99)


# ---------- 资料（昵称 / 头像） ----------
# 头像是 12 个预设表情，没有图片上传：自托管产品不值得为此开存储面。
# 默认值按邮箱哈希确定性生成——老账号没有这两个字段也不怕，读出来就是默认值，
# 第一次改资料才落盘，所以不需要数据迁移。
AVATARS = ["🦊", "🐼", "🐯", "🦁", "🐸", "🦉", "🐬", "🐨", "🚀", "⚡", "🌈", "🎬"]
NICKNAME_MAX = 16


def _hash_int(seed: str) -> int:
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)


def _default_nickname(email: str) -> str:
    return f"创作者{_hash_int(_norm_email(email)) % 9000 + 1000}"


def _default_avatar(email: str) -> str:
    return AVATARS[_hash_int("av:" + _norm_email(email)) % len(AVATARS)]


def get_profile(email: str) -> dict:
    """昵称与头像（含注册时间，账号页展示用）。没登录/没这人也给确定性默认值。"""
    email = _norm_email(email)
    rec = next((u for u in _load_users() if u["email"] == email), None)
    nickname = (rec or {}).get("nickname") or _default_nickname(email)
    avatar = (rec or {}).get("avatar")
    return {
        "nickname": str(nickname).strip()[:NICKNAME_MAX] or _default_nickname(email),
        "avatar": avatar if avatar in AVATARS else _default_avatar(email),
        "created": (rec or {}).get("created") or "",
    }


def set_profile(email: str, nickname: str | None = None,
                avatar: str | None = None) -> dict:
    """改昵称/头像。非法输入抛 ValueError（信息可直接给前端）。"""
    email = _norm_email(email)
    users = _load_users()
    user = next((u for u in users if u["email"] == email), None)
    if user is None:
        raise ValueError("先登录再改资料")
    if nickname is not None:
        nickname = str(nickname).strip()
        if not nickname:
            raise ValueError("昵称不能是空的")
        if len(nickname) > NICKNAME_MAX:
            raise ValueError(f"昵称最多 {NICKNAME_MAX} 个字")
        user["nickname"] = nickname
    if avatar is not None:
        if avatar not in AVATARS:
            raise ValueError("头像不在可选列表里")
        user["avatar"] = avatar
    user["profile_updated"] = time.strftime("%Y-%m-%d %H:%M")
    _save_users(users)
    return get_profile(email)


def change_password(email: str, old: str, new: str) -> None:
    """登录状态下改密码：必须先验当前密码。非法输入抛 ValueError。"""
    if not verify_login(email, old or ""):
        raise ValueError("当前密码不对")
    set_password(email, new)


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
