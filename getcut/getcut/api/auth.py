"""登录态、授权码、计费与配额、管理端。

从 server.py 按域拆出来的路由。
路由**注册顺序**由 server 里的 include_router 顺序决定（按各域首条路由行号
排序），改动顺序前先看 tests/test_route_order.py 的检查 —— 顺序反了会被通配路由吃掉。
"""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from .. import agenthub, auth, config, cos_store, licenses, safestore, voice_clone
from .. import brand as brand_kit

from .. import ctx

from fastapi import APIRouter

log = logging.getLogger(__name__)

router = APIRouter()

def _set_session_cookie(response: Response, request: Request, email: str,
                        remember: bool) -> None:
    ttl = auth.SESSION_TTL_LONG if remember else auth.SESSION_TTL_SHORT
    response.set_cookie(
        ctx.SESSION_COOKIE, auth.make_session(email, ttl), max_age=ttl,
        httponly=True, samesite="lax",
        secure=request.headers.get("x-forwarded-proto") == "https",
        path="/")
@router.get("/api/auth/status")
def auth_status():
    """登录/注册页初始化用（公开）。

    `open` 一并说出来：前端曾自己用"没令牌 + 没账号"猜开放模式，而 _open_mode 还要求
    显式 GETCUT_OPEN_MODE=1 —— 猜错的结果是访客一进成片台就撞 401、落地页糊一屏红字。
    """
    return {"smtp": auth.smtp_ready(), "dev_email": config.DEV_EMAIL_FALLBACK,
            "token_auth": bool(ctx.AUTH_TOKEN), "locked": auth.has_users(),
            "open": ctx._open_mode()}
@router.post("/api/auth/send-code")
def auth_send_code(body: dict, request: Request):
    """注册第一步：给邮箱发验证码。60 秒冷却，10 分钟有效；每 IP 每小时限 10 封。"""
    if not auth.ip_can_send(ctx._client_ip(request)):
        return JSONResponse({"error": "这个网络发验证码太频繁了，一小时后再试"}, status_code=429)
    ok, msg = auth.issue_code(body.get("email", ""))
    if not ok:
        return JSONResponse({"error": msg}, status_code=400)
    auth.ip_record_send(ctx._client_ip(request))
    return {"ok": True, "message": msg}
@router.post("/api/auth/register")
def auth_register(body: dict, request: Request, response: Response):
    """注册第二步：邮箱 + 验证码 + 密码。管理员只由 `GETCUT_ADMIN_EMAILS` 白名单决定。"""
    email = body.get("email", "")
    if not auth.check_code(email, body.get("code", "")):
        return JSONResponse({"error": "验证码不对或已过期"}, status_code=400)
    # 管理员只认 GETCUT_ADMIN_EMAILS 白名单；库里一个账号都没有也**不会**送人管理员，
    # 否则"账号文件丢了"就等于"最高权限重新待发"（见 config.ADMIN_EMAILS 上方注释）。
    # body 里传什么都不算，role 只由服务端按邮箱决定。
    role = "admin" if str(email).strip().lower() in config.ADMIN_EMAILS else "user"
    try:
        user = auth.create_user(email, body.get("password", ""), role=role)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _set_session_cookie(response, request, user["email"],
                        bool(body.get("remember", True)))
    return user
@router.post("/api/auth/reset-code")
def auth_reset_code(body: dict, request: Request):
    """忘记密码第一步：给已注册邮箱发验证码（邮箱没注册就直接说清楚）。"""
    email = body.get("email", "")
    if not auth.user_exists(email):
        return JSONResponse({"error": "这个邮箱还没注册过，先注册吧"}, status_code=400)
    if not auth.ip_can_send(ctx._client_ip(request)):
        return JSONResponse({"error": "这个网络发验证码太频繁了，一小时后再试"}, status_code=429)
    ok, msg = auth.issue_code(email, purpose="重设密码")
    if not ok:
        return JSONResponse({"error": msg}, status_code=400)
    auth.ip_record_send(ctx._client_ip(request))
    return {"ok": True, "message": msg}
@router.post("/api/auth/reset")
def auth_reset(body: dict, request: Request, response: Response):
    """忘记密码第二步：验证码 + 新密码，成功后直接登录。"""
    email = (body.get("email") or "").strip().lower()
    if not auth.check_code(email, body.get("code", "")):
        return JSONResponse({"error": "验证码不对或已过期"}, status_code=400)
    try:
        auth.set_password(email, body.get("password", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _set_session_cookie(response, request, email, bool(body.get("remember", True)))
    return {"email": email}
@router.post("/api/auth/login")
def auth_login(body: dict, request: Request, response: Response):
    email = body.get("email", "")
    ip = ctx._client_ip(request)
    allowed, left = auth.login_can_try(ip, email)
    if not allowed:
        # 只回 429，不再跑哈希：挡在门外就没必要替对方做 PBKDF2（那正是他要的开销）
        return JSONResponse({"error": auth.login_blocked_left(left)}, status_code=429)
    if not auth.verify_login(email, body.get("password", "")):
        auth.login_failed(ip, email)
        time.sleep(0.6)   # 拖慢暴力尝试
        return JSONResponse({"error": "邮箱或密码不对"}, status_code=401)
    auth.login_succeeded(ip, email)
    email = email.strip().lower()
    _set_session_cookie(response, request, email, bool(body.get("remember", True)))
    return {"email": email}
@router.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(ctx.SESSION_COOKIE, path="/")
    return {"ok": True}
@router.post("/api/auth/change-password")
def auth_change_password(body: dict, request: Request):
    """登录状态下改密码：验当前密码 → 设新密码（会话不用重发，签名里没有密码）。"""
    email = ctx._session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    time.sleep(0.4)   # 和登录一样拖一下，防在线爆破旧密码
    try:
        auth.change_password(email, body.get("old_password", ""),
                             body.get("new_password", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True}
def _usage_drop(email: str) -> None:
    """注销时把用量账本里这个人的键去掉（额度是跟账号走的，账号没了不留）。"""
    with ctx._LOCK:
        data = ctx._usage_load()
        if email in data:
            data.pop(email, None)
            try:
                safestore.write_json(ctx.USAGE_FILE, data, indent=None)
            except OSError:
                pass
def _purge_account(email: str) -> dict:
    """删掉这个人名下的一切，并回报删了哪些、各多少。

    每类都单独数一遍是有用的：客户问"你们到底删了什么"，我们答得出；
    答不出来的"我们已彻底删除"，在投诉与诉讼里等于没删。
    素材包目录只删归属明确是自己的 —— 无主的历史包可能是别人的，不能顺手带走。
    """
    out: dict = {"bundles": [], "projects": 0, "jobs": 0, "cos": 0, "brand": False}
    meta = ctx._bundles_meta()
    for name, info in list(meta.items()):
        if (info or {}).get("owner") != email:
            continue
        d = (ctx.WORKSPACES / name).resolve()
        if ctx.WORKSPACES.resolve() in d.parents and d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
        meta.pop(name, None)
        out["bundles"].append(name)
    ctx._bundles_meta_save(meta)

    with ctx._LOCK:
        reg = ctx._reg()
        mine = [x for x in reg["projects"] if x.get("owner") == email]
        reg["projects"] = [x for x in reg["projects"] if x.get("owner") != email]
        ctx._reg_save(reg)
    out["projects"] = len(mine)

    with ctx._LOCK:
        for jid, j in list(ctx.JOBS.items()):
            if j.get("owner") != email:
                continue
            v = j.get("video")
            if v and Path(v).is_file():
                Path(v).unlink(missing_ok=True)
            key = j.get("cos_key")
            if key and cos_store.enabled():
                try:
                    cos_store.drop(key)
                    out["cos"] += 1
                except Exception as exc:  # noqa: BLE001 - 云上删不掉要喊，但别挡住注销
                    log.error("cos drop failed on purge", extra={"key": key}, exc_info=exc)
            ctx.JOBS.pop(jid, None)
            out["jobs"] += 1
        ctx._jobs_save()

    vid = brand_kit.clear_clone(email)
    if vid:
        try:
            voice_clone.remove(vid)
        except Exception as exc:  # noqa: BLE001
            log.error("voice clone remove failed", exc_info=exc)
    bdir = brand_kit._dir(email)
    if bdir.is_dir():
        shutil.rmtree(bdir, ignore_errors=True)
        out["brand"] = True
    return out
@router.post("/api/auth/delete-account")
def auth_delete_account(body: dict, request: Request, response: Response):
    """注销账号：本人登录 + 再输一次密码确认。

    要密码是因为只凭登录状态就能删掉全部作品，破坏力太大（共享电脑、
    被看到的 cookie 都够）。删完所有设备的通行证立刻失效，卡密记录去身份保留，
    因为财务要能对账 —— 这两条都写在隐私政策里，代码与文案必须一致。
    """
    email = ctx._session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    if not body.get("confirm"):
        return JSONResponse({"error": "请勾选确认：注销会删除素材包、成片与品牌套装，无法恢复"},
                            status_code=400)
    if not auth.verify_login(email, str(body.get("password") or "")):
        return JSONResponse({"error": "密码不对，注销没有生效"}, status_code=403)
    deleted = _purge_account(email)
    ok, why = auth.delete_user(email)
    if not ok:
        return JSONResponse({"error": why or "注销失败"}, status_code=400)
    anonymized = licenses.anonymize(email)
    _usage_drop(email)
    auth.revoke_all_sessions(email)
    resp = JSONResponse({"ok": True, "deleted": deleted, "license_records_anonymized": anonymized})
    resp.delete_cookie(ctx.SESSION_COOKIE, path="/")
    log.info("account deleted", extra={"email": email, "bundles": len(deleted["bundles"]),
                                       "projects": deleted["projects"], "jobs": deleted["jobs"],
                                       "cos": deleted["cos"]})
    return resp
@router.get("/api/auth/sessions")
def auth_sessions(request: Request):
    """我这个账号现在在哪些设备上登录着。"""
    email = ctx._session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    return {"sessions": auth.list_sessions(email)}
@router.post("/api/auth/session/revoke")
def auth_session_revoke(body: dict, request: Request):
    """撕掉指定那一台的通行证 —— 以前只能换全局密钥＝所有人一起掉线。"""
    email = ctx._session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    sid = str(body.get("sid") or "").strip()
    if not sid:
        return JSONResponse({"error": "要踢哪一台：缺少会话标识"}, status_code=400)
    if not auth.revoke_session(email, sid):
        # 别人的 sid 与不存在的 sid 回同一个码：不能拿它探测"这个会话在不在"
        return JSONResponse({"error": "这台设备已经不在线了"}, status_code=404)
    return {"ok": True}
@router.get("/api/me")
def me(request: Request):
    email = ctx._session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    tier = auth.user_tier(email)
    prof = auth.get_profile(email)
    out = {"email": email, "tier": tier, "tier_label": auth.TIER_LABEL.get(tier, tier),
           "is_admin": auth.is_admin(email),
           "nickname": prof["nickname"], "avatar": prof["avatar"],
           "created": prof["created"], "avatars": auth.AVATARS}
    if tier == "free":
        # 免费档把今天还剩几条说出来，权益卡里直接展示（付费档不限次）
        used = (ctx._usage_load().get(email) or {}).get(time.strftime("%Y-%m-%d"), 0)
        out["builds_today"] = used
        out["free_daily_builds"] = config.FREE_DAILY_BUILDS
    return out
@router.put("/api/me")
def me_update(body: dict, request: Request):
    """改自己的资料（昵称/头像）。只收这两个字段，改密码走 /api/auth/change-password。"""
    email = ctx._session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    try:
        prof = auth.set_profile(email, body.get("nickname"), body.get("avatar"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "nickname": prof["nickname"], "avatar": prof["avatar"]}
@router.get("/api/pricing")
def pricing(request: Request):
    """定价页数据（公开）：价格与站长微信。收款码功能已拆（只走微信转账）。"""
    email = ctx._session_email(request)
    return {"prices": config.PRICES, "wechat_id": config.SALES_WECHAT_ID or "",
            "free_daily_builds": config.FREE_DAILY_BUILDS,
            "tier": auth.user_tier(email), "email": email or "",
            "is_admin": auth.is_admin(email)}
@router.post("/api/license/redeem")
def license_redeem(body: dict, request: Request):
    """卡密兑换：登录用户输码，服务端给账号打档位标记。"""
    email = ctx._session_email(request)
    if not email:
        return JSONResponse({"error": "先登录再兑换"}, status_code=401)
    # 简单防爆破：连续失败 5 次后强制歇 60 秒
    global _REDEEM_FAILS
    now = time.time()
    fails = [f for f in _REDEEM_FAILS.get(email, []) if now - f < 60]
    if len(fails) >= 5:
        return JSONResponse({"error": "试错太多次了，一分钟后再来"}, status_code=429)
    ok, msg, tier = licenses.redeem(email, body.get("code", ""))
    if not ok:
        fails.append(now)
        _REDEEM_FAILS[email] = fails
        return JSONResponse({"error": msg}, status_code=400)
    _REDEEM_FAILS.pop(email, None)
    return {"ok": True, "message": msg, "tier": tier,
            "tier_label": auth.TIER_LABEL.get(tier, tier)}
_REDEEM_FAILS: dict[str, list] = {}
@router.get("/api/admin/licenses")
def admin_list_licenses(request: Request):
    if not ctx._is_adminish(request):
        return JSONResponse({"error": "只有管理员能看"}, status_code=403)
    return {"stats": licenses.stats(), "codes": licenses.list_codes()}
@router.post("/api/admin/licenses/gen")
def admin_gen_licenses(body: dict, request: Request):
    """给直播间备货：生成 N 张卡密，明文只在这一步返回，赶紧复制走。"""
    if not ctx._is_adminish(request):
        return JSONResponse({"error": "只有管理员能生成"}, status_code=403)
    try:
        codes = licenses.generate(str(body.get("tier") or ""), int(body.get("count") or 0),
                                  str(body.get("note") or ""))
        # 发一批记一笔：谁发的、什么时候、几片、什么档、备注。
        # 没有这行流水，直播间卖完货对不上账时我们连"这张码是我给的"都证不了。
        licenses.log_issue(ctx._session_email(request) or "token",
                           str(body.get("tier") or ""), codes, str(body.get("note") or ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"codes": codes, "stats": licenses.stats()}
@router.get("/api/admin/licenses/audit")
def admin_license_audit(request: Request, limit: int = 100):
    """卡密发放流水（最近若干条，倒序）。只有管理员能看。"""
    if not ctx._is_adminish(request):
        return JSONResponse({"error": "只有管理员能看"}, status_code=403)
    return {"rows": licenses.list_audit(max(1, min(int(limit or 100), 1000)))}
@router.get("/api/admin/nodes")
def admin_nodes(request: Request):
    """管理员看成片台水位：哪几台在线、队列里还有几个没领。"""
    if not ctx._is_adminish(request):
        return JSONResponse({"error": "只有管理员能看"}, status_code=403)
    return {"enabled": True, "kind": "agent", **agenthub.snapshot()}
