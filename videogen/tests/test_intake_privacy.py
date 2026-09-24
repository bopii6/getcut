"""收件口（一次性票 → PUT → 认领）的两条底线：不泄露、不越权。

2026-09-23 隔离定调：「一条片子只有本人能经手」。这条链上原来有两处不合格：
1. `/api/intake/<code>/meta` **匿名**回标题、口播前 400 字、字数与图片视频数 ——
   而 /i/<码> 天生就是会被转发、会被别人扫到的东西（skill 打完包把码发到群里，
   等于把没发布的稿子全群公开）。intake 这条链以前一条测试都没有。
2. 收件口是匿名的：单包 512MB、同 IP 一小时 10 次 → 一小时能塞 5GB，而线上那块
   40G 系统盘只剩十几 G（账号/密钥/备份都在同一块盘）；客户端工具还得拿**站点
   主钥匙**才能上传，那张钥匙能领走并看见全站任何客户的素材与成片。
   现在改成：登录领一次性票（owner 写死在票上）→ 凭票 PUT → 只有票主能认领。

跑法（在 videogen/ 目录下）：
    python -m unittest tests.test_intake_privacy
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from urllib.parse import quote

_TMP = tempfile.mkdtemp(prefix="videogen-intake-")
os.environ.update({
    "VIDEOGEN_WORKSPACE": _TMP,
    "VIDEOGEN_USERS_FILE": str(Path(_TMP) / "users.json"),
    "VIDEOGEN_LICENSES_FILE": str(Path(_TMP) / "licenses.json"),
    "VIDEOGEN_USAGE_FILE": str(Path(_TMP) / "usage.json"),
    "VIDEOGEN_AUTH_SECRET": str(Path(_TMP) / "auth-secret"),
    "VIDEOGEN_BRAND_DIR": str(Path(_TMP) / "brand"),
    "VIDEOGEN_JOBS_FILE": str(Path(_TMP) / "jobs.json"),
    "VIDEOGEN_REGISTRY_FILE": str(Path(_TMP) / "registry.json"),
    "VIDEOGEN_TOKEN": "",
    "EMAIL_SMTP_HOST": "",
})

from starlette.testclient import TestClient  # noqa: E402

from videogen import auth, ctx, server  # noqa: E402
from videogen.api import transfer  # noqa: E402

A = "author@example.invalid"             # 做这条片子的人
B = "stranger@example.invalid"           # 拿到链接的另一个人
PW = "Km4-Vb8Qz2Xw7Nt3Rd6P"
SECRET_TITLE = "美联储加息内幕-未发布选题"
SECRET_LINE = "这一句是口播稿的第一句，绝不能出现在别人的屏幕上。"
BASE = "http://intake.test"


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("content.json", json.dumps(
            {"title": SECRET_TITLE, "script": SECRET_LINE + "补" * 500},
            ensure_ascii=False))
        zf.writestr("manifest.json", json.dumps(
            {"assets": [{"kind": "image"}, {"kind": "image"}, {"kind": "video"}]}))
    return buf.getvalue()


def setUpModule():
    auth.USERS_FILE = Path(_TMP) / "users.json"
    auth.SECRET_FILE = Path(_TMP) / "auth-secret"
    auth.create_user(A, PW, role="user")
    auth.create_user(B, PW, role="user")
    assert not auth.is_admin(A) and not auth.is_admin(B), "两个都得是普通用户"


class Base(unittest.TestCase):
    """走一遍真实流程：A 登录领票 → 凭票 PUT → 返回 /i/码。"""

    def setUp(self):
        self.client = TestClient(server.app, base_url=BASE)
        self.ck_a = {server.SESSION_COOKIE: auth.make_session(A, auth.SESSION_TTL_SHORT)}
        self.ck_b = {server.SESSION_COOKIE: auth.make_session(B, auth.SESSION_TTL_SHORT)}
        # 每条用例都从空收件区开始：上一张没用掉的票会算进"最多攒 5 张"那道上限，
        # 而领票的按 IP 滑窗是模块级的，不清就会在第十条用例上撞 429
        transfer._INTAKE_RATE.clear()
        ctx.INTAKES.mkdir(parents=True, exist_ok=True)
        for f in ctx.INTAKES.iterdir():
            f.unlink(missing_ok=True)

    def new_ticket(self, email_a=True):
        r = self.client.post("/api/intake/ticket", cookies=self.ck_a if email_a else self.ck_b)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def deliver(self, tk=None):
        tk = tk or self.new_ticket()
        path = tk["put_url"].replace(BASE, "") + "&name=" + quote("我的选题.zip")
        up = self.client.put(path, content=_zip())
        self.assertEqual(up.status_code, 200, up.text)
        return tk["code"]


class IntakeTicketTest(Base):
    def test_ticket_requires_login(self):
        r = self.client.post("/api/intake/ticket")
        self.assertEqual(r.status_code, 401, "领收件地址不再要登录，等于退回匿名收件口")

    def test_put_needs_the_ticket(self):
        tk = self.new_ticket()
        path = tk["put_url"].replace(BASE, "").split("?")[0]
        for bad in (path, path + "?t=" + "0" * 40):
            with self.subTest(url=bad):
                r = self.client.put(bad, content=_zip())
                self.assertIn(r.status_code, (403, 404), "没有票也能往收件口塞包")

    def test_size_cap_is_enforced_while_reading(self):
        tk = self.new_ticket()
        path = tk["put_url"].replace(BASE, "")
        keep = transfer.MAX_INTAKE_BYTES
        transfer.MAX_INTAKE_BYTES = 2048
        try:
            r = self.client.put(path, content=b"z" * 4096)
        finally:
            transfer.MAX_INTAKE_BYTES = keep
        self.assertEqual(r.status_code, 413, "超过单包上限的包该被当场拒收")

    def test_only_the_owner_may_claim(self):
        code = self.deliver()
        r = self.client.post(f"/api/intake/{code}/claim", json={}, cookies=self.ck_b)
        self.assertEqual(r.status_code, 403, "B 用 A 的码把 A 的稿子导进自己账号")
        r = self.client.post(f"/api/intake/{code}/claim", json={}, cookies=self.ck_a)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(ctx._bundle_owner(r.json()["name"]), A)

    def test_inbox_lists_only_my_packages(self):
        """手机端「素材」入口读的 /api/intake：只能看见自己领的票，别人的一条都不列。"""
        mine = self.deliver()
        code_b = self.new_ticket(email_a=False)          # B 自己领一张并传上去
        self.deliver(code_b)
        r = self.client.get("/api/intake", cookies=self.ck_a)
        self.assertEqual(r.status_code, 200)
        codes = [i["code"] for i in r.json()["intakes"]]
        self.assertEqual(codes, [mine], f"收件箱列出了别人的包：{codes}")
        self.assertEqual(self.client.get("/api/intake").status_code, 401, "匿名也能列收件箱")
        b_seen = [i["code"] for i in
                  self.client.get("/api/intake", cookies=self.ck_b).json()["intakes"]]
        self.assertEqual(b_seen, [code_b["code"]])

    def test_inbox_state_moves_from_ready_to_imported(self):
        code = self.deliver()
        item = self.client.get("/api/intake", cookies=self.ck_a).json()["intakes"][0]
        self.assertEqual(item["state"], "ready")
        self.assertTrue(item["ready"])
        self.assertFalse(item["claimed"])
        self.assertIsNone(item["bundle"])

        claim = self.client.post(f"/api/intake/{code}/claim", json={}, cookies=self.ck_a)
        self.assertEqual(claim.status_code, 200, claim.text)
        item = self.client.get("/api/intake", cookies=self.ck_a).json()["intakes"][0]
        self.assertEqual(item["state"], "imported")
        self.assertFalse(item["ready"])
        self.assertTrue(item["claimed"])
        self.assertEqual(item["projectId"], claim.json()["project_id"])
        self.assertEqual(item["bundle"], claim.json()["name"])

    def test_inbox_does_not_show_empty_upload_ticket(self):
        self.new_ticket()
        items = self.client.get("/api/intake", cookies=self.ck_a).json()["intakes"]
        self.assertEqual(items, [], "没上传的空白收件单不应出现在客户手机里")

    def test_ticket_is_single_use(self):
        tk = self.new_ticket()
        self.deliver(tk)
        r = self.client.put(tk["put_url"].replace(BASE, ""), content=_zip())
        self.assertEqual(r.status_code, 409, "一张票能反复塞包，水位就白设了")


class IntakePrivacyTest(Base):
    def _meta(self, ck=None):
        return self.client.get(self.url, cookies=ck or {})

    def setUp(self):
        super().setUp()
        self.code = self.deliver()
        self.url = f"/api/intake/{self.code}/meta"

    def test_anonymous_caller_gets_no_content(self):
        r = self._meta()
        self.assertEqual(r.status_code, 200)
        body = r.text
        for leak in (SECRET_TITLE, SECRET_LINE, "scriptPreview", "scriptChars",
                     "estSeconds", "title", "我的选题"):
            self.assertNotIn(leak, body, f"取件概要里还能读到 {leak}")
        self.assertIs(bool(r.json().get("logged")), False)

    def test_logged_in_stranger_gets_no_content_either(self):
        """登录不等于能看：正主之外的登录用户同样只该看到"有个包在等你"。"""
        body = self._meta(self.ck_b).text
        self.assertNotIn(SECRET_TITLE, body)
        self.assertNotIn("我的选题", body)     # 客户常把选题直接写进 zip 名

    def test_meta_still_says_what_a_visitor_needs(self):
        j = self._meta().json()
        self.assertFalse(j["claimed"])
        self.assertTrue(j["expiresAt"] > 0, "还得告诉人家 24 小时内有效")

    def test_claim_requires_login(self):
        r = self.client.post(f"/api/intake/{self.code}/claim", json={})
        self.assertEqual(r.status_code, 401)

    def test_claimed_code_does_not_leak_the_project(self):
        pid = self.client.post(f"/api/intake/{self.code}/claim", json={},
                               cookies=self.ck_a).json()["project_id"]
        self.assertNotIn(pid, json.dumps(self._meta(self.ck_b).json()),
                         "已导入的码把项目号漏给了别人")
        self.assertEqual(self._meta(self.ck_a).json().get("projectId"), pid)
        with ctx._LOCK:
            p = next(x for x in ctx._reg()["projects"] if x["project_id"] == pid)
        self.assertEqual(p["owner"], A)


if __name__ == "__main__":
    unittest.main(verbosity=2)
