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
import threading
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


# ---------- 登录防爆破 ----------
# 登录接口以前只有一句 time.sleep(0.6)「拖慢」——那挡不住挂着连接一直试的人：
# 客户 40~50 岁、弱口令概率高，而登录门后面是别人的选题稿、卡密和后台。
# 对比一下就知道这是漏的：兑换卡密那条有"连错 5 次歇 60 秒"，登录反而没有。
# 两条一起算：按 (账号, IP) 挡针对性爆破，按 IP 总量挡"换邮箱撞库"。
# 内存记账、重启清零：宁可重启后多放行一次，也不把真客户永久锁在门外。
LOGIN_FAIL_LIMIT = 5          # 同一账号 + 同一 IP：连错 5 次就歇
LOGIN_IP_LIMIT = 30           # 同一 IP（换着邮箱猛试）：15 分钟内最多错 30 次
LOGIN_FAIL_WINDOW = 900       # 15 分钟
_login_fail: dict[str, list[float]] = {}


def _recent(stamps: list[float] | None, now: float) -> list[float]:
    return [t for t in (stamps or []) if now - t < LOGIN_FAIL_WINDOW]


def login_can_try(ip: str, email: str) -> tuple[bool, int]:
    """这一次还让不让试。返回 (放行?, 还要等多少秒)。

    两个维度撞上的提示语一模一样 —— 不告诉对方"是这个账号被护住了"还是
    "你这台机器被计数了"，那等于替人探路。
    """
    now = time.time()
    key = f"{_norm_email(email)}|{ip}"
    pair = _recent(_login_fail.get(key), now)
    # 只数这台机器自己的失败（键是 "邮箱|IP"），不然别人撞库会把真客户一起锁在门外
    from_this_ip = [t for k, stamps in _login_fail.items()
                    if k.endswith("|" + ip) for t in _recent(stamps, now)]
    _login_fail[key] = pair
    if len(pair) >= LOGIN_FAIL_LIMIT or len(from_this_ip) >= LOGIN_IP_LIMIT:
        oldest = min(pair) if pair else now
        return False, max(1, int(LOGIN_FAIL_WINDOW - (now - oldest)))
    return True, 0


def login_blocked_left(seconds: int) -> str:
    mins = max(1, round(seconds / 60))
    return f"试错次数太多了，先等 {mins} 分钟再登录；想不起来就走「忘记密码」"


def login_failed(ip: str, email: str) -> None:
    _login_fail.setdefault(f"{_norm_email(email)}|{ip}", []).append(time.time())


def login_succeeded(ip: str, email: str) -> None:
    _login_fail.pop(f"{_norm_email(email)}|{ip}", None)


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
    users = _load_users()   # 下面会顺手把 pw_gen +1：改密码＝所有设备重登
    user = next((u for u in users if u["email"] == email), None)
    if user is None:
        raise ValueError("这个邮箱还没注册过")
    salt = secrets.token_bytes(16)
    user["salt"] = salt.hex()
    user["hash"] = _hash_password(password, salt).hex()
    user["iters"] = PBKDF2_ITERS
    user["pw_reset"] = time.strftime("%Y-%m-%d %H:%M")
    for u in users:
        if u["email"] == email:
            u["pw_gen"] = int(u.get("pw_gen") or 0) + 1
    _save_users(users)
    # 代次 +1 之后这些票全废了：留着记录只会让「登录设备」那一页骗人
    revoke_all_sessions(email)


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
    # 先自增代次再改密：set_password 里那一次 +1 就是这次改密的生效点
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


def make_session(email: str, ttl: int = SESSION_TTL_SHORT,
                 device: str = "", ip: str = "") -> str:
    """签一张通行证：`邮箱|到期|密码代次|会话号|签名`。

    加"密码代次"与"会话号"是为了两件以前做不到的事：
      · 改密码 → 代次 +1 → 旧通行证整批作废（以前改密码不影响已登录的人）
      · 只撕某一张 → 会话号进吊销表（以前只能换全局密钥＝所有人一起掉线）
    ⚠️ 旧格式（3 段）的通行证一律不再接受：那批票既撕不掉也不随改密码作废，
    留着它们等于给"改密码也踢不掉的人"留门。代价是所有人重登一次。
    """
    exp = int(time.time()) + ttl
    gen = _pw_gen(email)
    sid = secrets.token_hex(6)
    payload = f"{email}|{exp}|{gen}|{sid}"
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    _record_session(sid, email, device, ip, exp)
    return f"{payload}|{sig}"


def read_session(token: str) -> str | None:
    """会话有效返回邮箱，无效返回 None（过期/签名不对/格式不对/已吊销/改过密码）。"""
    parts = (token or "").split("|")
    if len(parts) != 5:
        return None
    email, exp, gen, sid, sig = parts
    if not exp.isdigit():
        return None
    expect = hmac.new(_secret(), f"{email}|{exp}|{gen}|{sid}".encode("utf-8"),
                      hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        return None
    if int(exp) < time.time():
        return None
    if sid in _revoked_set():
        return None
    if str(gen) != str(_pw_gen(email)):
        return None
    _touch_session(sid)
    return email


def delete_user(email: str, password: str = "") -> tuple[bool, str]:
    """注销账号：把这个人从账号表里去掉。

    返回 (是否成功, 给用户的提示)。要密码再确认一次：登录状态被别人看到时，
    仅凭 cookie 就能删号是不可接受的破坏力。改密码那条已经会让所有旧通行证失效，
    这里删掉记录后同样立刻全端掉线。
    """
    email = _norm_email(email)
    users = _load_users()
    me = next((u for u in users if u["email"] == email), None)
    if not me:
        return False, "账号不存在"
    if password:
        salt = bytes.fromhex(me["salt"])
        want = _hash_password(password, salt, int(me.get("iters") or PBKDF2_ITERS))
        if not hmac.compare_digest(want.hex(), me["hash"]):
            return False, "密码不对，注销没有生效"
    rest = [u for u in users if u["email"] != email]
    _save_users(rest)
    return True, ""


# ---------- 会话登记与吊销（"这张票只撕这一张"） ----------
# 以前通行证里只有"邮箱 + 到期"，所以要么不动、要么换全局密钥让所有人一起掉线。
# 现在每张票带一个随机 sid：登记在案就能列出来，进吊销表就立刻失效。
SESSIONS_FILE = USERS_FILE.parent / ".videogen-sessions.json"
_MAX_SESSION_RECORDS = 500
_MAX_REVOKED = 1000
_sessions_lock = threading.Lock()
_sessions_state: dict | None = None


def _sessions_load() -> dict:
    """会话表读坏了不许当"没有会话"：那会让已吊销的票重新有效。
    救不回来就抛，宁可登录接口报错，也不能把吊销表忘掉。"""
    global _sessions_state
    if _sessions_state is not None:
        return _sessions_state
    data = safestore.read_json(
        SESSIONS_FILE, default={"records": [], "revoked": {}},
        shape=lambda d: isinstance(d, dict) and isinstance(d.get("records"), list))
    data.setdefault("records", [])
    data.setdefault("revoked", {})
    _sessions_state = data
    return data


def _sessions_save(state: dict) -> None:
    try:
        SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        safestore.write_json(SESSIONS_FILE, state, indent=None)
    except OSError as e:
        print("sessions save failed: %s" % e)


def _prune(state: dict, now: float) -> None:
    """记录与吊销表都要有界：这是公开接口能不断签新票的地方，不设上限就是磁盘炸弹。"""
    keep = sorted(state["records"], key=lambda r: r.get("exp") or 0,
                  reverse=True)[:_MAX_SESSION_RECORDS]
    state["records"] = [r for r in keep if (r.get("exp") or 0) > now]
    rev = {k: v for k, v in state["revoked"].items() if v > now}
    if len(rev) > _MAX_REVOKED:
        newest = sorted(rev.items(), key=lambda kv: kv[1], reverse=True)[:_MAX_REVOKED]
        rev = dict(newest)
    state["revoked"] = rev


def _record_session(sid: str, email: str, device: str, ip: str, exp: int) -> None:
    with _sessions_lock:
        state = _sessions_load()
        now = time.time()
        state["records"].append({"sid": sid, "email": email, "device": (device or "")[:60],
                                 "ip": (ip or "")[:60], "created": int(now), "exp": int(exp),
                                 "last_seen": int(now)})
        _prune(state, now)
        _sessions_save(state)


def _touch_session(sid: str) -> None:
    """last_seen 只每 10 分钟回写一次：每次请求都写状态文件是白给的磁盘压力。"""
    with _sessions_lock:
        state = _sessions_load()
        now = time.time()
        hit = False
        for r in state["records"]:
            if r.get("sid") == sid and now - (r.get("last_seen") or 0) > 600:
                r["last_seen"] = int(now)
                hit = True
        if hit:
            _prune(state, now)
            _sessions_save(state)


def _revoked_set() -> set:
    with _sessions_lock:
        return set(_sessions_load().get("revoked") or {})


def _pw_gen(email: str) -> int:
    for u in _load_users():
        if u["email"] == _norm_email(email):
            return int(u.get("pw_gen") or 0)
    return 0


def list_sessions(email: str) -> list[dict]:
    """这个账号当前在哪些设备上登录着（给"我的设备"页用，也给自己踢人用）。"""
    email = _norm_email(email)
    now = time.time()
    revoked = _revoked_set()
    with _sessions_lock:
        state = _sessions_load()
    rows = [r for r in state["records"]
            if r.get("email") == email and (r.get("exp") or 0) > now
            and r.get("sid") not in revoked]
    rows.sort(key=lambda r: r.get("last_seen") or 0, reverse=True)
    return [{"sid": r["sid"], "device": r.get("device") or "未知设备",
             "ip": r.get("ip") or "", "created": r.get("created"),
             "last_seen": r.get("last_seen")} for r in rows]


def revoke_session(email: str, sid: str) -> bool:
    """撕掉一张票：只有本人（或管理员走后台）能撕自己账号下的。"""
    email = _norm_email(email)
    with _sessions_lock:
        state = _sessions_load()
        rec = next((r for r in state["records"]
                    if r.get("sid") == sid and r.get("email") == email), None)
        if rec is None:
            return False
        state["revoked"][sid] = int(rec.get("exp") or (time.time() + SESSION_TTL_LONG))
        state["records"] = [r for r in state["records"] if r.get("sid") != sid]
        _prune(state, time.time())
        _sessions_save(state)
    return True


def revoke_all_sessions(email: str) -> int:
    """注销账号时用：这个人名下所有票一律作废。"""
    email = _norm_email(email)
    with _sessions_lock:
        state = _sessions_load()
        mine = [r for r in state["records"] if r.get("email") == email]
        for r in mine:
            state["revoked"][r["sid"]] = int(r.get("exp") or (time.time() + 3600))
        state["records"] = [r for r in state["records"] if r.get("email") != email]
        _prune(state, time.time())
        _sessions_save(state)
        return len(mine)
