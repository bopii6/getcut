"""卡密（买断制授权码）：生成、兑换、与档位联动。

销售流程：直播间下单 → 用户加站长微信付款 → 站长发卡密 → 用户在站内兑换。
- 卡密格式 GCB-XXXX-XXXX / GCP-XXXX-XXXX（B=基础版 399，P=高级版 599）。
- 字符表去掉 0/O/1/I/S/5，微信里手抄不会认错；大小写不敏感、连字符可有可无。
- 存储：工作区 JSON 持久卷，含状态（未兑换/已兑换/被谁兑换），站长后台可盘点。
- 兑换只升不降：基础版用户兑高级码 → 升高级；兑基础码 → 提示已是同档；
  高级版用户兑基础码 → 拒绝且不消耗（避免直播间发错码白亏一张）。

命令行（在服务器上给直播间备货）：
    python -m videogen.licenses gen premium 10      # 生成 10 张高级版卡密
    python -m videogen.licenses list                # 盘点：未兑换/已兑换
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path

from . import auth, config, safestore

# 手抄友好的字符表：没有 0/O/1/I/S/5（S/5 也容易混，干脆都不要）
_ALPHABET = "2346789ABCDEFGHJKMNPQRTUVWXYZ"
_CODE_FILE = Path(config.LICENSES_FILE)
_AUDIT_FILE = Path(config.LICENSE_AUDIT_FILE)


def _norm(code: str) -> str:
    """兑换时的归一化：大写、去连字符和空白。"""
    return (code or "").upper().replace("-", "").replace(" ", "")


def _new_code(tier: str) -> str:
    prefix = {"basic": "GCB", "premium": "GCP"}[tier]
    body = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"{prefix}-{body[:4]}-{body[4:]}"


def _load() -> dict:
    data = safestore.read_json(
        _CODE_FILE, default={"codes": []},
        shape=lambda d: isinstance(d, dict) and isinstance(d.get("codes"), list))
    return data if isinstance(data, dict) and isinstance(data.get("codes"), list) else {"codes": []}


def _save(data: dict) -> None:
    safestore.write_json(_CODE_FILE, data)


def generate(tier: str, count: int, note: str = "") -> list[str]:
    """生成 count 张卡密并落盘，返回明文码列表（只在这一刻能整批拿到）。"""
    if tier not in ("basic", "premium"):
        raise ValueError("档位只能是 basic 或 premium")
    count = max(1, min(int(count), 200))
    data = _load()
    codes = []
    now = time.strftime("%Y-%m-%d %H:%M")
    for _ in range(count):
        code = _new_code(tier)
        while any(c["code"] == code for c in data["codes"]):   # 理论撞码，重摇
            code = _new_code(tier)
        data["codes"].append({"code": code, "tier": tier, "created": now,
                              "note": note, "redeemed_by": None, "redeemed_at": None})
        codes.append(code)
    _save(data)
    return codes


def _find(data: dict, code: str) -> dict | None:
    want = _norm(code)
    return next((c for c in data["codes"] if _norm(c["code"]) == want), None)


def redeem(email: str, code: str) -> tuple[bool, str, str]:
    """兑换。返回 (是否成功, 给用户看的提示, 当前档位)。"""
    email = (email or "").strip().lower()
    raw = _norm(code)
    if not email or not raw:
        return False, "先登录，再输入卡密", auth.user_tier(email)
    if len(raw) != 11 or raw[:3] not in ("GCB", "GCP"):
        return False, "卡密格式不对，应是 GCB/GCP 开头的那串码", auth.user_tier(email)
    data = _load()
    rec = _find(data, raw)
    if rec is None:
        return False, "没有这张卡密，找站长核对一下", auth.user_tier(email)
    if rec["redeemed_by"]:
        return False, "这张卡密已被使用", auth.user_tier(email)
    tier = rec["tier"]
    current = auth.user_tier(email)
    if auth.TIER_RANK[current] > auth.TIER_RANK[tier]:
        return False, f"你已经是{auth.TIER_LABEL[current]}，这张{auth.TIER_LABEL[tier]}码就退给站长吧", current
    if auth.TIER_RANK[current] == auth.TIER_RANK[tier] and current != "free":
        return False, f"你已经是{auth.TIER_LABEL[tier]}了，这张码别浪费", current
    try:
        auth.set_tier(email, tier)
    except ValueError as e:
        return False, str(e), current
    rec["redeemed_by"] = email
    rec["redeemed_at"] = time.strftime("%Y-%m-%d %H:%M")
    _save(data)
    return True, f"激活成功！你现在是{auth.TIER_LABEL[tier]}，永久有效", tier


def stats() -> dict:
    """后台盘点用。"""
    codes = _load()["codes"]
    out = {"basic": {"total": 0, "used": 0}, "premium": {"total": 0, "used": 0}}
    for c in codes:
        s = out.setdefault(c["tier"], {"total": 0, "used": 0})
        s["total"] += 1
        if c["redeemed_by"]:
            s["used"] += 1
    return out


def list_codes(limit: int = 200) -> list[dict]:
    """给管理后台展示（脱敏到前 7 位 + 状态）。"""
    out = []
    for c in _load()["codes"][-limit:][::-1]:
        out.append({"code": c["code"][:7] + "…", "tier": c["tier"], "created": c["created"],
                    "note": c.get("note") or "",
                    "redeemed_by": c["redeemed_by"], "redeemed_at": c["redeemed_at"]})
    return out


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "gen" and len(sys.argv) >= 4:
        tier = sys.argv[2].lower()
        n = int(sys.argv[3])
        note = sys.argv[4] if len(sys.argv) > 4 else ""
        for c in generate(tier, n, note):
            print(c)
    elif cmd == "list":
        for c in list_codes():
            mark = f"已兑换 {c['redeemed_by']}" if c["redeemed_by"] else "未兑换"
            print(f"{c['code']}  {c['tier']:<8} {mark}")
        print(json.dumps(stats(), ensure_ascii=False))
    else:
        print("用法: python -m videogen.licenses gen <basic|premium> <数量> [备注]\n"
              "      python -m videogen.licenses list")


def anonymize(email: str) -> int:
    """把这张账号名下的核销记录去掉身份：卡密本身留着（财务要能对账），
    但"谁核销的"换成不可逆摘要。返回改了几条。"""
    want = (email or "").strip().lower()
    if not want:
        return 0
    data = _load()
    digest = hashlib.sha256((want + _anon_salt()).encode("utf-8")).hexdigest()[:10]
    n = 0
    for c in data["codes"]:
        if (c.get("redeemed_by") or "").strip().lower() == want:
            c["redeemed_by"] = "erased-" + digest
            n += 1
    if n:
        _save(data)
    return n


def _anon_salt() -> str:
    """同一份密钥下算出的摘要才稳定；用会话签名密钥当盐，不落明文邮箱。"""
    from . import auth
    try:
        return auth._secret().hex()
    except Exception:  # noqa: BLE001 - 拿不到就用固定盐，注销去身份这件事不该失败
        return "videogen-anon"


def log_issue(operator: str, tier: str, codes: list[str], note: str = "") -> None:
    """发一批卡密就追加一行流水。只追加、不改写；写失败要喊出来（这是账）。"""
    line = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "operator": (operator or "").strip().lower() or "?",
            "tier": tier, "count": len(codes), "note": (note or "")[:120],
            "codes": [c[:7] + "***" for c in codes[:200]]}
    try:
        _AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + chr(10))
    except OSError as e:
        print("license audit write failed: %s" % e)


def list_audit(limit: int = 200) -> list[dict]:
    """最近若干条发放流水（倒序：最新的在前）。"""
    if not _AUDIT_FILE.is_file():
        return []
    rows = []
    for raw in _AUDIT_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rows.append(json.loads(raw))
        except ValueError:
            rows.append({"unparsed": raw[:120]})
    return list(reversed(rows[-max(1, int(limit)):]))
