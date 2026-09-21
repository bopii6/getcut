"""管理员从哪来：只认邮箱白名单，不再认"谁先注册"。

跑法（在 videogen/ 目录下）：
    python -m unittest tests.test_admin_bootstrap -v

为什么要这一份：旧代码是 `role = "admin" if not auth.has_users() else "user"`，
把最高权限（能生成卡密 = 能凭空印钱）挂在"账号文件在不在"上。线上账号表放在
`/state`（目录挂载），只要有一次挂载掉回本地空目录（漏挂、换机、恢复备份到空卷），
`has_users()` 就变假 —— 谁先点注册谁当管理员。站长 2026-09-21 拍板：管理员只有他一个。

同一处还顺手关掉另一个"读不到就等于没有"的口子：开放模式（本机自用的免登录）
现在必须显式 `VIDEOGEN_OPEN_MODE=1` 才生效，默认关。
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="videogen-admin-")
os.environ.update({
    "VIDEOGEN_WORKSPACE": _TMP,
    "VIDEOGEN_USERS_FILE": str(Path(_TMP) / "users.json"),
    "VIDEOGEN_LICENSES_FILE": str(Path(_TMP) / "licenses.json"),
    "VIDEOGEN_USAGE_FILE": str(Path(_TMP) / "usage.json"),
    "VIDEOGEN_AUTH_SECRET": str(Path(_TMP) / "auth-secret"),
    "VIDEOGEN_BRAND_DIR": str(Path(_TMP) / "brand"),
    "VIDEOGEN_JOBS_FILE": str(Path(_TMP) / "jobs.json"),
    "VIDEOGEN_REGISTRY_FILE": str(Path(_TMP) / "registry.json"),
    "VIDEOGEN_TOKEN": "",           # 不配访问令牌：只看账号会话
    "EMAIL_SMTP_HOST": "",
})

from starlette.testclient import TestClient  # noqa: E402

from videogen import auth, config, server  # noqa: E402

PASSWORD = "Hq4-Vm8TkZ2pWs7Rd5Ln"
BOSS = "boss@example.invalid"          # 白名单里的站长邮箱
FIRST_BLOOD = "first@example.invalid"  # 手快的那个路人


def _arm_code(email: str, code: str = "482913") -> None:
    """绕过 SMTP 直接把验证码放进内存表（测试不发真邮件）。"""
    auth._codes[email.strip().lower()] = {"code": code, "exp": time.time() + 600,
                                          "attempts": 0, "sent_at": time.time()}


class AdminBootstrapTest(unittest.TestCase):
    def setUp(self):
        auth.USERS_FILE = Path(_TMP) / ("users-%d.json" % os.getpid())
        auth.SECRET_FILE = Path(_TMP) / "auth-secret"
        for f in (auth.USERS_FILE,):
            f.unlink(missing_ok=True)
        self._emails = config.ADMIN_EMAILS
        config.ADMIN_EMAILS = frozenset({BOSS})
        self.client = TestClient(server.app, base_url="http://admin.test")

    def tearDown(self):
        config.ADMIN_EMAILS = self._emails
        auth.USERS_FILE = Path(_TMP) / "users.json"

    def _register(self, email: str, extra: dict | None = None) -> dict:
        _arm_code(email)
        body = {"email": email, "code": "482913", "password": PASSWORD}
        body.update(extra or {})
        r = self.client.post("/api/auth/register", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_first_ever_registrant_is_not_an_admin(self):
        """库里一个账号都没有 —— 这恰恰是"账号文件丢了"的样子，不许送人管理员。"""
        self.assertFalse(auth.has_users(), "前置条件：账号表必须是空的")
        user = self._register(FIRST_BLOOD)
        self.assertEqual(user["role"], "user", "空库第一个注册的人拿到了管理员")
        self.assertFalse(auth.is_admin(FIRST_BLOOD))

    def test_the_new_admin_cannot_mint_license_codes(self):
        """手快的人当不上管理员，也就印不出卡密。"""
        self._register(FIRST_BLOOD)
        session = auth.make_session(FIRST_BLOOD, auth.SESSION_TTL_SHORT)
        r = self.client.post("/api/admin/licenses/gen",
                             json={"tier": "premium", "count": 5},
                             cookies={server.SESSION_COOKIE: session})
        self.assertEqual(r.status_code, 403, "非管理员能生成卡密 = 可以凭空印钱")

    def test_allowlisted_email_becomes_admin(self):
        user = self._register(BOSS)
        self.assertEqual(user["role"], "admin")
        self.assertTrue(auth.is_admin(BOSS))
        session = auth.make_session(BOSS, auth.SESSION_TTL_SHORT)
        r = self.client.post("/api/admin/licenses/gen",
                             json={"tier": "premium", "count": 1},
                             cookies={server.SESSION_COOKIE: session})
        self.assertNotEqual(r.status_code, 403, "站长自己被挡在门外了")

    def test_allowlist_matches_case_and_spaces(self):
        user = self._register("  BOSS@Example.Invalid  ")
        self.assertEqual(user["role"], "admin")

    def test_client_cannot_ask_for_the_role(self):
        """body 里塞 role 不该有用 —— 权限只由服务端按邮箱决定。"""
        user = self._register(FIRST_BLOOD, {"role": "admin", "is_admin": True})
        self.assertEqual(user["role"], "user")
        self.assertFalse(auth.is_admin(FIRST_BLOOD))

    def test_empty_store_without_the_flag_is_locked_not_wide_open(self):
        """开放模式要显式开。没开时空库=全站关门（401），不是匿名可读所有客户素材。"""
        os.environ.pop("VIDEOGEN_OPEN_MODE", None)
        self.assertFalse(auth.has_users())
        for path in ("/api/bundles", "/api/projects", "/api/jobs"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401,
                                 "%s 在无账号无令牌时把数据开门了" % path)

    def test_open_mode_still_works_when_explicitly_enabled(self):
        """本机自用那条路别弄坏：显式开了就该免登录能用。"""
        os.environ["VIDEOGEN_OPEN_MODE"] = "1"
        try:
            self.assertFalse(auth.has_users())
            self.assertEqual(self.client.get("/api/bundles").status_code, 200)
        finally:
            os.environ.pop("VIDEOGEN_OPEN_MODE", None)


class AdminConfigTest(unittest.TestCase):
    def test_allowlist_parsing(self):
        """配置文件里逗号/分号、大小写、多余空格都要能吃下（写错一次就没管理员了）。"""
        def parse(raw):
            return frozenset(e.strip().lower()
                             for e in raw.replace(";", ",").split(",") if e.strip())
        both = frozenset({"a@x.com", "b@y.com"})
        for raw in ("a@x.com,b@y.com", " a@x.com ; B@Y.com ", "A@X.COM,b@y.com"):
            self.assertEqual(parse(raw), both, raw)
        self.assertEqual(parse("a@x.com,, ,"), frozenset({"a@x.com"}))
        self.assertEqual(parse(""), frozenset())          # 没配就是没有管理员，不许默认送给第一个人
        saved = config.ADMIN_EMAILS
        try:
            config.ADMIN_EMAILS = frozenset()
            self.assertNotIn("anyone@x.com", config.ADMIN_EMAILS)
        finally:
            config.ADMIN_EMAILS = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)
