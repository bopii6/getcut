"""合规三件套：三页法定文本、账号注销、会话可按设备吊销、卡密发放流水。

跑法（在 videogen/ 目录下）：
    python -m unittest tests.test_compliance -v

这一节的判断标准只有一条：**政策里写的每句话，代码都得做得到**。
所以断言不是"页面有没有"，而是"说不留录音就不留、说能注销就真删、
说能踢某一台就只踢那一台"。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="videogen-legal-")
os.environ.update({
    "VIDEOGEN_WORKSPACE": _TMP,
    "VIDEOGEN_USERS_FILE": str(Path(_TMP) / "users.json"),
    "VIDEOGEN_LICENSES_FILE": str(Path(_TMP) / "licenses.json"),
    "VIDEOGEN_USAGE_FILE": str(Path(_TMP) / "usage.json"),
    "VIDEOGEN_AUTH_SECRET": str(Path(_TMP) / "auth-secret"),
    "VIDEOGEN_BRAND_DIR": str(Path(_TMP) / "brand"),
    "VIDEOGEN_JOBS_FILE": str(Path(_TMP) / "jobs.json"),
    "VIDEOGEN_REGISTRY_FILE": str(Path(_TMP) / "registry.json"),
    "VIDEOGEN_LICENSE_AUDIT": str(Path(_TMP) / "audit.jsonl"),
    "VIDEOGEN_TOKEN": "",
    "VIDEOGEN_ADMIN_EMAILS": "legal-boss@example.invalid",
    "EMAIL_SMTP_HOST": "",
})

from starlette.testclient import TestClient  # noqa: E402

from videogen import auth, config, legal, licenses, server  # noqa: E402

BOSS = "legal-boss@example.invalid"
BOSS_PW = "Kp7-3mQzRt8wLd2V"
CUST = "customer@example.invalid"
CUST_PW = "Zx4-9bNrYs3tHq7M"
PASSWORDS = {CUST: CUST_PW, BOSS: BOSS_PW}


def _login(email: str, pw: str) -> str:
    return auth.make_session(email, auth.SESSION_TTL_SHORT, device="pytest " + email[:3])


class _Base(unittest.TestCase):
    def setUp(self):
        self.ws = Path(_TMP) / ("ws-" + type(self).__name__)
        self.ws.mkdir(exist_ok=True)
        # 每个用例一套自己的文件：以前共用 users.json/auth-secret，
        #  setUp 里"删掉再建"会和别的模块的会话互相踩，出现偶发假失败
        tag = "%s.%s" % (type(self).__name__, self._testMethodName)
        auth.USERS_FILE = Path(_TMP) / ("users-%s.json" % tag)
        auth.SECRET_FILE = Path(_TMP) / ("secret-%s" % tag)
        auth.SESSIONS_FILE = Path(_TMP) / ("sessions-%s.json" % tag)
        auth._forget_sessions_cache()
        licenses._CODE_FILE = Path(_TMP) / ("licenses-%s.json" % tag)
        licenses._AUDIT_FILE = Path(_TMP) / ("audit-%s.jsonl" % tag)
        for f in (auth.USERS_FILE, auth.SECRET_FILE, auth.SESSIONS_FILE,
                  licenses._CODE_FILE, licenses._AUDIT_FILE):
            f.unlink(missing_ok=True)
        # 密钥自己先写好：不留"谁先去创建这个文件"的窗口（生产侧已改成独占创建，
        # 测试这边再固定一份，偶发变量就彻底没了）
        auth.SECRET_FILE.write_bytes(b"pytest-secret-" + tag.encode("utf-8").ljust(18, b"0")[:18])
        self.addCleanup(lambda: [f.unlink(missing_ok=True) for f in
                                 Path(_TMP).glob("*" + tag + "*")])
        self._ws = server.WORKSPACES
        server.WORKSPACES = self.ws
        self._meta = server.BUNDLES_META
        server.BUNDLES_META = self.ws / "bundles.json"
        # 成片目录也指到临时区：测试不许往仓库 outputs/ 里写 mp4
        self._outputs = server.OUTPUTS
        server.OUTPUTS = self.ws / "outputs"
        server.OUTPUTS.mkdir(exist_ok=True)
        auth.create_user(CUST, CUST_PW)
        auth.create_user(BOSS, BOSS_PW, role="admin")
        self.client = TestClient(server.app, base_url="http://legal.test")

    def as_user(self, email, pw):
        """带某个人身份的一次性客户端（不共用 cookie jar，避免跨请求互相污染）。"""
        tok = _login(email, pw)
        self.assertEqual(auth.session_status(tok), "ok",
                         "刚签的通行证自己就不认：查 session_status 的分支")
        c = TestClient(server.app, base_url="http://legal.test",
                       cookies={server.SESSION_COOKIE: tok})
        c._tok = tok
        return c

    def tearDown(self):
        server.WORKSPACES = self._ws
        server.BUNDLES_META = self._meta
        server.OUTPUTS = self._outputs


class LegalPagesTest(_Base):
    def test_pages_are_public_and_say_what_the_code_does(self):
        """匿名可读：付款前就得看到，抽查时"登录后可见"不算提供。"""
        for kind, must in (("privacy", ("录音", "90 天", "腾讯云", "注销")),
                           ("terms", ("一次性买断", "不支持退款", "自行核实")),
                           ("refund", ("不支持退款", "连续 7 天", "换绑"))):
            r = self.client.get("/" + kind)
            self.assertEqual(r.status_code, 200, kind + " 打不开")
            for w in must:
                self.assertIn(w, r.text, f"{kind} 里没提「{w}」")

    def test_retention_numbers_come_from_one_place(self):
        """文案里的天数必须与代码引用的是同一份常量。"""
        self.assertIn(f"{legal.RETENTION['bundle_days']} 天", legal.page("privacy"))
        self.assertIn(f"{legal.RETENTION['backup_days']} 天内", legal.page("privacy"))
        self.assertLess(legal.RETENTION["erase_after_days"], legal.RETENTION["backup_days"],
                        "承诺「注销后清除」却比备份窗口还长，等于永远清不干净")

    def test_pages_revalidate_and_are_not_stored(self):
        first = self.client.get("/privacy")
        self.assertEqual(first.headers["cache-control"], "no-cache")
        again = self.client.get("/privacy", headers={"if-none-match": first.headers["etag"]})
        self.assertEqual(again.status_code, 304)

    def test_unknown_kind_is_not_a_page(self):
        self.assertEqual(legal.page("anything-else"), "")


class DeleteAccountTest(_Base):
    def _seed(self, email: str) -> dict:
        """造一份"这个人确有东西在我们手上"的现场。"""
        bundle = self.ws / "cust-bundle"
        (bundle / "images").mkdir(parents=True, exist_ok=True)
        (bundle / "content.json").write_text('{"title":"t","script":"s"}', encoding="utf-8")
        (bundle / "images" / "a.jpg").write_text("x", encoding="utf-8")
        server._bundles_meta_save({**server._bundles_meta(), "cust-bundle": {"owner": email}})
        reg = server._reg()
        reg["projects"].append({"project_id": "p-1", "owner": email, "bundle": "cust-bundle",
                                "title": "客户的项目"})
        server._reg_save(reg)
        out = server.OUTPUTS
        vid = out / "cust-job.mp4"
        vid.write_text("mp4", encoding="utf-8")
        with server._LOCK:
            server.JOBS["cust-job"] = {"owner": email, "stage": "done", "video": str(vid),
                                       "project_id": "p-1"}
            server._jobs_save()
        server._usage_bump(email)
        codes = licenses.generate("premium", 1, "pytest")
        licenses.redeem(email, codes[0])
        return {"bundle": bundle, "video": vid}

    def test_requires_login_confirmation_and_password(self):
        self.assertEqual(self.client.post("/api/auth/delete-account", json={}).status_code, 401)
        sess = _login(CUST, CUST_PW)
        # 每次都用"干净的客户端"带 cookie：TestClient 自己的 cookie jar 会记住
        # 前一个匿名请求返回的清除指令，串到后面的请求上就变成假 401
        cookie = {server.SESSION_COOKIE: sess}
        r = TestClient(server.app, base_url="http://legal.test",
                       cookies=cookie).post("/api/auth/delete-account", json={"password": CUST_PW})
        self.assertEqual(r.status_code, 400, "没勾选确认就该拒绝")
        r2 = self.client.post("/api/auth/delete-account",
                              json={"confirm": True, "password": "错的密码"}, cookies=cookie)
        self.assertEqual(r2.status_code, 403)
        self.assertTrue(auth.user_exists(CUST), "密码不对却把账号删了")

    def test_deletes_everything_the_policy_promises(self):
        seeded = self._seed(CUST)
        cust = self.as_user(CUST, CUST_PW)
        sess = _login(CUST, CUST_PW)
        r = cust.post("/api/auth/delete-account", json={"confirm": True, "password": CUST_PW})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("cust-bundle", body["deleted"]["bundles"])
        self.assertEqual(body["deleted"]["projects"], 1)
        self.assertEqual(body["deleted"]["jobs"], 1)
        self.assertFalse(seeded["bundle"].exists(), "素材包目录还在盘上")
        self.assertFalse(seeded["video"].exists(), "成片文件还在盘上")
        self.assertFalse(auth.user_exists(CUST), "账号还在")
        self.assertEqual([p for p in server._reg()["projects"] if p.get("owner") == CUST], [])
        with server._LOCK:
            self.assertNotIn("cust-job", server.JOBS)
        self.assertNotIn(CUST, server._usage_load(), "用量账本里还留着这个人的邮箱")
        self.assertIsNone(auth.read_session(sess), "注销后旧通行证还能用")

    def test_license_records_survive_but_lose_the_email(self):
        """财务要能对账 → 卡密记录留着；但不能再指向这个人。"""
        self._seed(CUST)
        r = self.as_user(CUST, CUST_PW).post(
            "/api/auth/delete-account", json={"confirm": True, "password": CUST_PW})
        self.assertEqual(r.status_code, 200, r.text)   # 不先确认删成功，后面的断言都是空话
        raw = licenses._CODE_FILE.read_text(encoding="utf-8")
        self.assertNotIn(CUST, raw, "注销后卡密表里还能搜到这个邮箱")
        self.assertIn("erased-", raw, "核销记录整个没了：财务对不上账")

    def test_one_users_deletion_does_not_touch_others(self):
        other = "other@example.invalid"
        auth.create_user(other, "Ab7-cDefGh1iJk2")
        keep = self._seed(CUST)
        ob = self.ws / "other-bundle"
        ob.mkdir(exist_ok=True)
        (ob / "content.json").write_text("{}", encoding="utf-8")
        server._bundles_meta_save({**server._bundles_meta(), "other-bundle": {"owner": other}})
        r = self.as_user(CUST, CUST_PW).post(
            "/api/auth/delete-account", json={"confirm": True, "password": CUST_PW})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(ob.is_dir(), "别人的素材包被带走了")
        self.assertTrue(auth.user_exists(other), "别人的账号被删了")
        self.assertFalse(keep["bundle"].exists())


class SessionRevocationTest(_Base):
    def test_two_sessions_can_be_revoked_one_at_a_time(self):
        laptop = _login(CUST, CUST_PW)
        phone = auth.make_session(CUST, auth.SESSION_TTL_LONG, device="手机")
        rows = auth.list_sessions(CUST)
        self.assertEqual(len(rows), 2, "两台设备应该各一条记录")
        target = _sid_of(laptop)                   # 要踢的就是笔记本这张，不靠排序猜
        r = self.as_user(CUST, CUST_PW).post("/api/auth/session/revoke", json={"sid": target})
        self.assertEqual(r.status_code, 200, r.text)
        kept, gone = phone, laptop
        self.assertIsNotNone(auth.read_session(kept), "另一台被误伤了")
        self.assertIsNone(auth.read_session(gone), "被踢的那台还有效")

    def test_cannot_revoke_another_accounts_session(self):
        victim = _login(CUST, CUST_PW)
        sid = _sid_of(victim)
        r = self.as_user(BOSS, BOSS_PW).post("/api/auth/session/revoke", json={"sid": sid})
        self.assertEqual(r.status_code, 404, "别人的 sid 不该被认出来")
        self.assertIn(sid, [r["sid"] for r in auth.list_sessions(CUST)],
                      "别人的会话被踢掉了：归属校验没起作用")
        self.assertTrue(auth.revoke_session(CUST, sid), "自己的 sid 反而踢不掉")

    def test_password_change_kills_all_sessions(self):
        a, b = _login(CUST, CUST_PW), auth.make_session(CUST, auth.SESSION_TTL_LONG, device="平板")
        auth.set_password(CUST, "NewPw-4tYq7Zc2")
        self.assertIsNone(auth.read_session(a))
        self.assertIsNone(auth.read_session(b))
        self.assertEqual(auth.list_sessions(CUST), [], "改密后设备列表还在列旧票")

    def test_sessions_file_stays_bounded(self):
        """公开登录口能不断签新票：登记簿不设上限就是磁盘炸弹。"""
        for _ in range(60):
            auth.make_session(CUST, auth.SESSION_TTL_LONG, device="x")
        state = auth._sessions_load()
        self.assertLessEqual(len(state["records"]), auth._MAX_SESSION_RECORDS)

    def test_legacy_three_part_token_is_rejected(self):
        """旧格式（邮箱|到期|签名）撕不掉也不随改密作废 → 一律不再接受。"""
        import hashlib
        import hmac
        payload = f"{CUST}|{int(__import__('time').time()) + 3600}"
        sig = hmac.new(auth._secret(), payload.encode(), hashlib.sha256).hexdigest()
        self.assertIsNone(auth.read_session(f"{payload}|{sig}"))


class LicenseAuditTest(_Base):
    def test_issue_is_logged_with_operator(self):
        boss_client = self.as_user(BOSS, BOSS_PW)
        r = boss_client.post("/api/admin/licenses/gen",
                             json={"tier": "premium", "count": 3, "note": "直播间 9/21"})
        self.assertEqual(r.status_code, 200, r.text)
        rows = boss_client.get("/api/admin/licenses/audit").json()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["operator"], BOSS)
        self.assertEqual(rows[0]["count"], 3)
        self.assertEqual(rows[0]["note"], "直播间 9/21")
        joined = json.dumps(rows[0]["codes"])
        for c in r.json()["codes"]:
            self.assertNotIn(c, joined, "整码不该进流水：流水泄露也不能直接兑换")

    def test_audit_is_append_only_across_batches(self):
        boss_client = self.as_user(BOSS, BOSS_PW)
        for _ in range(2):
            rr = boss_client.post("/api/admin/licenses/gen", json={"tier": "basic", "count": 1})
            self.assertEqual(rr.status_code, 200, rr.text)
        lines = [x for x in licenses._AUDIT_FILE.read_text(encoding="utf-8").splitlines() if x]
        self.assertEqual(len(lines), 2, "两批只留了一行 = 前一批的账被抹了")

    def test_non_admin_cannot_read_the_trail(self):
        cust = self.as_user(CUST, CUST_PW)
        self.assertEqual(cust.get("/api/me").status_code, 200,
                         "登录状态不认：" + auth.session_status(cust._tok))
        self.assertEqual(cust.get("/api/admin/licenses/audit").status_code, 403)


def _sid_of(token: str) -> str:
    return (token or "").split("|")[3]


if __name__ == "__main__":
    unittest.main(verbosity=2)
