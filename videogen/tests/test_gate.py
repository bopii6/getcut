"""后端鉴权边界与状态文件的离线闸门：不起服务器、不碰工作区里的真账号。

跑法（在 videogen/ 目录下）：
    python -m unittest discover -s tests -t tests -v
需要 httpx（只装在 CI / 开发环境，不进 requirements.txt）：
    pip install httpx

锁住 2026-09-21 两个 P0 的修法，改接口时别再漏回去：
  1. 未登录一律拿不到素材、账号、卡密、成片台任务（当年 /media 只校验"在工作区内"，
     而签名密钥与素材包同处 /data → 注册个免费号拖个 zip 就能自签管理员）。
  2. 状态文件写坏不许当空库 —— 旧行为会让 has_users() 变假 → 开放模式 → 全站开门。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

# config.py 在 import 时就读环境变量定下所有路径，所以必须先设环境、再 import 业务模块。
_TMP = tempfile.mkdtemp(prefix="videogen-gate-")
os.environ.update({
    "VIDEOGEN_WORKSPACE": _TMP,
    "VIDEOGEN_USERS_FILE": str(Path(_TMP) / "users.json"),
    "VIDEOGEN_LICENSES_FILE": str(Path(_TMP) / "licenses.json"),
    "VIDEOGEN_USAGE_FILE": str(Path(_TMP) / "usage.json"),
    "VIDEOGEN_AUTH_SECRET": str(Path(_TMP) / "auth-secret"),
    "VIDEOGEN_BRAND_DIR": str(Path(_TMP) / "brand"),
    "VIDEOGEN_JOBS_FILE": str(Path(_TMP) / "jobs.json"),
    "VIDEOGEN_REGISTRY_FILE": str(Path(_TMP) / "registry.json"),
    "VIDEOGEN_TOKEN": "",          # 不启用全局访问令牌：只认账号会话
    "EMAIL_SMTP_HOST": "",
})

from starlette.testclient import TestClient  # noqa: E402

from videogen import auth, safestore, server  # noqa: E402

PROBE_USER = "gate-probe@example.invalid"
PROBE_PASSWORD = "Zk9-mVx4QsT7pLd2Rb8H"

# 未登录必须挡住的（401，不是 403/404：挡住时不许透露"这个资源存在"）
LOCKED_OUT = [
    ("GET", "/media/any-bundle/images/x.jpg"),
    ("GET", "/api/bundles"),
    ("GET", "/api/projects"),
    ("GET", "/api/jobs"),
    ("GET", "/api/me"),
    ("GET", "/api/brand"),
    ("POST", "/api/admin/licenses/gen"),
    ("POST", "/api/build"),
]
# 新访客也要能用的：这些落到 401 就说明闸门写宽了，把首页/登录页本身关在门外
PUBLIC = [
    ("GET", "/healthz"),
    ("GET", "/api/auth/status"),
    ("GET", "/api/pricing"),
    ("GET", "/api/templates"),
    ("GET", "/poc/"),
]


def setUpModule():
    # 状态路径要自己钉死：auth.USERS_FILE / SECRET_FILE 是 import 时抓走的模块常量，
    # 别的测试模块（test_billing）会临时改它们。不钉死的话结果取决于文件谁先被 import。
    auth.USERS_FILE = Path(_TMP) / "users.json"
    auth.SECRET_FILE = Path(_TMP) / "auth-secret"
    # 没有这一步，"库里没账号 → 开放模式"会让上面那批 401 断言集体假绿。
    auth.create_user(PROBE_USER, PROBE_PASSWORD, role="admin")
    assert auth.has_users(), "测试账号没建起来，闸门断言无效"


class AuthGateTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url="http://gate.test")

    def test_anonymous_cannot_reach_data_or_media(self):
        for method, path in LOCKED_OUT:
            with self.subTest(path=path):
                r = self.client.request(method, path, json={} if method == "POST" else None)
                self.assertEqual(r.status_code, 401, "%s %s 不该对匿名开放" % (method, path))

    def test_public_paths_stay_open(self):
        for method, path in PUBLIC:
            with self.subTest(path=path):
                r = self.client.request(method, path)
                self.assertNotEqual(r.status_code, 401, "%s 是公开路径，不该被闸门挡住" % path)

    def test_session_cookie_and_device_token_both_pass_the_gate(self):
        """成片台有两条身份通道（浏览器 vg_session cookie 与 x-agent-token 设备令牌）。

        2026-09-21 那轮归属校验的自伤风险就在这里：只认 cookie 会把令牌那条正路
        误伤成 401/403。/api/me 按设计只读 cookie（那是浏览器外壳的接口），
        所以这里用受闸门管的取货口断言"两条通道都放行"。
        """
        session = auth.make_session(PROBE_USER, auth.SESSION_TTL_SHORT)
        by_cookie = self.client.get("/api/me", cookies={server.SESSION_COOKIE: session})
        self.assertEqual(by_cookie.status_code, 200)
        self.assertEqual(by_cookie.json()["email"], PROBE_USER)
        channels = {"cookie": {"cookies": {server.SESSION_COOKIE: session}},
                    "agent-token": {"headers": {"x-agent-token": session}}}
        for name, kw in channels.items():
            with self.subTest(channel=name):
                r = self.client.get("/media/any-bundle/images/x.jpg", **kw)
                self.assertNotEqual(r.status_code, 401, "闸门误伤了一条身份通道")

    def test_forged_session_is_rejected(self):
        r = self.client.get("/api/me", cookies={server.SESSION_COOKIE: "not-a-real-session"})
        self.assertEqual(r.status_code, 401)


class SafeStoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="videogen-store-"))
        self.path = self.dir / "users.json"
        # 备份目录指到空目录：这一类断言要的是"救不回来时必须拒绝"，不能靠翻到备份蒙过
        self._backup_dir = safestore.BACKUP_DIR
        safestore.BACKUP_DIR = self.dir / "no-backups-here"

    def tearDown(self):
        safestore.BACKUP_DIR = self._backup_dir

    def test_missing_file_gives_default(self):
        self.assertEqual(safestore.read_json(self.path, default={}), {})

    def test_corrupt_file_without_backup_refuses_to_look_empty(self):
        """坏文件当空库 = 全站开门：宁可抛错让这一单 500，也不许返回 default。"""
        self.path.write_text('{"users": {"a":', encoding="utf-8")  # 半截 JSON
        with self.assertRaises(safestore.StoreUnrecoverable):
            safestore.read_json(self.path, default={}, shape=lambda d: isinstance(d, dict))

    def test_corrupt_file_leaves_the_scene_behind(self):
        self.path.write_text("not json at all", encoding="utf-8")
        with self.assertRaises(safestore.StoreUnrecoverable):
            safestore.read_json(self.path, default={})
        self.assertTrue(list(self.dir.glob("users.json.bad-*")), "现场没留住，事后查不了")

    def test_wrong_shape_is_treated_as_corrupt(self):
        self.path.write_text(json.dumps({"users": "不是表"}), encoding="utf-8")
        with self.assertRaises(safestore.StoreUnrecoverable):
            safestore.read_json(self.path, default={}, shape=lambda d: isinstance(d.get("users"), dict))

    def test_shrinking_record_count_snapshots_first(self):
        """记录数变短（3→1）先另存 .pre-*，别把误删当正常写入。"""
        data = {"users": [{"email": "a@x"}, {"email": "b@x"}, {"email": "c@x"}]}
        safestore.write_json(self.path, data, count=lambda d: len(d["users"]))
        safestore.write_json(self.path, {"users": data["users"][:1]}, count=lambda d: len(d["users"]))
        self.assertTrue(list(self.dir.glob("users.json.pre-*")), "变短没留底")

    def test_atomic_write_leaves_no_temp_file(self):
        safestore.atomic_write_text(self.path, "ok")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "ok")
        self.assertEqual(list(self.dir.glob(".users.json.tmp-*")), [])


class ResponseHeaderTest(unittest.TestCase):
    """缓存与安全头策略。重点是"默认不许缓存客户数据"与"别把自己的 iframe 挡死"。"""

    def setUp(self):
        self.client = TestClient(server.app, base_url="http://gate.test")

    def test_every_response_carries_the_baseline_headers(self):
        r = self.client.get("/api/auth/status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["referrer-policy"], "same-origin")
        self.assertEqual(r.headers["x-frame-options"], "SAMEORIGIN")
        self.assertEqual(r.headers["content-security-policy"], "frame-ancestors 'self'")
        self.assertTrue(r.headers.get("cache-control"), "没分类的路径不许裸奔")

    def test_frame_options_must_not_be_deny(self):
        """工作台首页是用 iframe 打开 /poc/ 成片台的（index.html:1153）。

        写 DENY 会把自己那条正路挡死，成片台直接开不出来 —— 所以这里钉死 SAMEORIGIN。
        """
        r = self.client.get("/poc/index.html")
        self.assertNotEqual(r.status_code, 404, "成片台产物没打包，这条断言失去意义")
        self.assertEqual(r.headers["x-frame-options"], "SAMEORIGIN")
        self.assertEqual(r.headers["content-security-policy"], "frame-ancestors 'self'")

    def test_customer_data_is_never_storable(self):
        """拿 **200 响应**来验：401 会被"错误响应不缓存"那条规则顺手盖住，验不出分类器。"""
        session = auth.make_session(PROBE_USER, auth.SESSION_TTL_SHORT)
        for path in ("/api/me", "/api/jobs", "/api/bundles", "/api/pricing"):
            with self.subTest(path=path):
                r = self.client.get(path, cookies={server.SESSION_COOKIE: session})
                self.assertEqual(r.status_code, 200, "这条断言依赖 200，状态变了要一起改")
                self.assertEqual(r.headers["cache-control"], "no-store",
                                 "%s 会被共享缓存留下别人家的口播稿与任务号" % path)
        # 未登录被闸门挡下的，同样不许落缓存
        self.assertEqual(self.client.get("/media/any/x.jpg").headers["cache-control"], "no-store")

    def test_error_responses_are_not_cached(self):
        r = self.client.get("/fonts/根本没有这个字体.woff2")
        self.assertGreaterEqual(r.status_code, 400)
        self.assertEqual(r.headers["cache-control"], "no-store", "404 被缓存 7 天会把好字体一直挡在门外")

    def test_static_bundle_gets_a_short_public_cache(self):
        r = self.client.get("/poc/bundle.js")
        if r.status_code == 404:
            self.skipTest("成片台产物未打包")
        self.assertEqual(r.headers["cache-control"], "public, max-age=3600")

    def test_html_revalidates_and_answers_304(self):
        """回访最该省的是整页 HTML：必须回源校验，内容没变就一个字节都不传。"""
        first = self.client.get("/studio")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["cache-control"], "no-cache")
        tag = first.headers.get("etag")
        self.assertTrue(tag, "没配 ETag 的话 no-cache 等于每次都重拉整页")
        again = self.client.get("/studio", headers={"if-none-match": tag})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.content, b"")
        stale = self.client.get("/studio", headers={"if-none-match": 'W/"stale00000000000000"'})
        self.assertEqual(stale.status_code, 200, "标签不匹配时必须回整页")

    def test_hsts_only_when_served_over_https(self):
        plain = self.client.get("/api/auth/status")
        self.assertNotIn("strict-transport-security", plain.headers)
        tls = self.client.get("/api/auth/status", headers={"x-forwarded-proto": "https"})
        self.assertIn("max-age", tls.headers.get("strict-transport-security", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
