"""取件链接（/api/intake/<code>/meta）的隐私闸门。

2026-09-23 隔离定调：「一条片子只有本人能看见」。这条接口原先**匿名**回标题、
口播前 400 字、字数与图片视频数 —— 而这条链接天生就是会被转发、会被别人扫到的
东西（skill 打完包把 /i/<码> 发到群里，等于把没发布的选题稿全群公开）。
现在只许说"有个包在等你、24 小时内有效"，内容等认领之后由项目页给正主看。

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

A = "author@example.invalid"             # 做这条片子的人
B = "stranger@example.invalid"           # 拿到链接的另一个人
PW = "Km4-Vb8Qz2Xw7Nt3Rd6P"
SECRET_TITLE = "美联储加息内幕-未发布选题"
SECRET_LINE = "这一句是口播稿的第一句，绝不能出现在别人的屏幕上。"


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


class IntakePrivacyTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url="http://intake.test")
        r = self.client.post("/api/intake", files={"file": ("我的选题.zip", _zip(),
                                                            "application/zip")})
        self.assertEqual(r.status_code, 200, r.text)
        self.code = r.json()["code"]
        self.url = f"/api/intake/{self.code}/meta"

    def _get(self, email=None):
        ck = {server.SESSION_COOKIE: auth.make_session(email, auth.SESSION_TTL_SHORT)} \
            if email else {}
        return self.client.get(self.url, cookies=ck)

    # ---------- 核心：谁都不许从这条链接读到内容 ----------
    def test_anonymous_caller_gets_no_content(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        body = r.text
        for leak in (SECRET_TITLE, SECRET_LINE, "scriptPreview", "scriptChars",
                     "estSeconds", "title"):
            self.assertNotIn(leak, body, f"取件概要里还能读到 {leak}")
        self.assertIs(bool(r.json().get("logged")), False)

    def test_logged_in_stranger_gets_no_content_either(self):
        """登录不等于能看：正主之外的登录用户同样只该看到"有个包在等你"。"""
        body = self._get(B).text
        self.assertNotIn(SECRET_TITLE, body)
        self.assertNotIn("scriptPreview", body)

    def test_meta_still_says_what_a_visitor_needs(self):
        j = self._get().json()
        self.assertFalse(j["claimed"])
        self.assertTrue(j["expiresAt"] > 0, "还得告诉人家 24 小时内有效")
        # 文件名也算内容：客户习惯把选题直接写进 zip 名
        self.assertNotIn("我的选题", json.dumps(j, ensure_ascii=False))

    # ---------- 认领之后：只跟正主走 ----------
    def test_claim_requires_login_and_only_owner_gets_the_project(self):
        self.assertEqual(self.client.post(f"/api/intake/{self.code}/claim",
                                          json={}).status_code, 401)
        r = self.client.post(f"/api/intake/{self.code}/claim", json={},
                             cookies={server.SESSION_COOKIE: auth.make_session(A, auth.SESSION_TTL_SHORT)})
        self.assertEqual(r.status_code, 200, r.text)
        pid = r.json()["project_id"]
        # 别人再拿同一个码：说"已导入"，但不告诉他落到了哪个项目
        j = self._get(B).json()
        self.assertTrue(j.get("claimed"))
        self.assertNotIn(pid, json.dumps(j), "已导入的码把项目号漏给了别人")
        # 正主自己：给项目号
        self.assertEqual(self._get(A).json().get("projectId"), pid)
        # 归属落地：这个项目只有 A 与管理员看得见
        with ctx._LOCK:
            p = next(x for x in ctx._reg()["projects"] if x["project_id"] == pid)
        self.assertEqual(p["owner"], A)


if __name__ == "__main__":
    unittest.main(verbosity=2)
