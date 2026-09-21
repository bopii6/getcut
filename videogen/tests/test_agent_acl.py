"""成片台任务归属的离线闸门：谁的单谁能动手。

跑法（在 videogen/ 目录下）：
    python -m unittest discover -s tests -t tests

2026-09-21 查出来的 P0：成片台五个接口只查"登录了吗"、没查"这是你的吗"，
配合 /api/jobs 泄漏的全站任务号，等于任何登录用户都能下载别人的配音（整篇口播能听见）
+ 素材 + logo。当时只有 tools/agent_acl_check.py 对着线上手工验过一轮；
这里把同一套判定钉成离线用例，改归属逻辑时本地就能挡住。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="videogen-acl-")
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

from videogen import auth, server  # noqa: E402

OWNER = "owner@example.invalid"          # 任务的正主
INTRUDER = "intruder@example.invalid"    # 另一个正常登录用户，不是管理员
PASSWORD = "Km4-Vb8Qz2Xw7Nt3Rd6P"

# (方法, 路径模板)：五个都走 _agent_job_ok 的接口
GUARDED = [
    ("GET", "/api/agent/job/{}/file"),
    ("POST", "/api/agent/job/{}/progress"),
    ("POST", "/api/agent/job/{}/visual"),
    ("POST", "/api/agent/job/{}/layer"),
    ("GET", "/agent-media/{}/images/x.jpg"),
]


def setUpModule():
    auth.USERS_FILE = Path(_TMP) / "users.json"
    auth.SECRET_FILE = Path(_TMP) / "auth-secret"
    auth.create_user(OWNER, PASSWORD, role="user")
    auth.create_user(INTRUDER, PASSWORD, role="user")
    assert not auth.is_admin(OWNER) and not auth.is_admin(INTRUDER), \
        "两个用例账号都得是普通用户，否则管理员豁免会掩盖归属漏洞"


class AgentJobAclTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url="http://acl.test")
        self._jobs = dict(server.JOBS)
        self._reg = server._reg
        server.JOBS.clear()
        server.JOBS["job-mine"] = {"owner": OWNER, "project_id": "p1", "stage": "queued"}
        server.JOBS["job-try"] = {"owner": OWNER, "try": True, "project_id": "p2", "stage": "queued"}
        self.owner = auth.make_session(OWNER, auth.SESSION_TTL_SHORT)
        self.other = auth.make_session(INTRUDER, auth.SESSION_TTL_SHORT)

    def tearDown(self):
        server.JOBS.clear()
        server.JOBS.update(self._jobs)
        server._reg = self._reg

    def hit(self, method, path, session, token=False):
        kw = {"headers": {"x-agent-token": session}} if token else {"cookies": {server.SESSION_COOKIE: session}}
        return self.client.request(method, path, json={}, **kw)

    # ---------- 别人的单：一律 403 ----------
    def test_intruder_blocked_on_every_guarded_endpoint(self):
        for method, template in GUARDED:
            for channel in ("cookie", "token"):
                with self.subTest(endpoint=template.format("job-mine"), channel=channel):
                    r = self.hit(method, template.format("job-mine"), self.other, token=channel == "token")
                    self.assertEqual(r.status_code, 403,
                                     "%s 放行了不是任务主人的请求（别人能拿这条下载你的口播配音）" % method)

    # ---------- 自己的单：不能被误伤 ----------
    def test_owner_passes_on_every_guarded_endpoint(self):
        for method, template in GUARDED:
            for channel in ("cookie", "token"):
                with self.subTest(endpoint=template.format("job-mine"), channel=channel):
                    r = self.hit(method, template.format("job-mine"), self.owner, token=channel == "token")
                    self.assertNotIn(r.status_code, (401, 403),
                                     "归属校验误伤了正主（令牌与 cookie 两条通道都要认）")

    # ---------- 匿名：先被闸门挡在门外 ----------
    def test_anonymous_gets_401_not_403(self):
        for method, template in GUARDED:
            with self.subTest(endpoint=template.format("job-mine")):
                r = self.client.request(method, template.format("job-mine"), json={})
                self.assertEqual(r.status_code, 401)

    # ---------- 试玩样片：本就是公开引流物 ----------
    def test_try_job_is_not_restricted_to_its_owner(self):
        for method, template in GUARDED:
            with self.subTest(endpoint=template.format("job-try")):
                r = self.hit(method, template.format("job-try"), self.other)
                self.assertNotIn(r.status_code, (401, 403), "试玩单要能让任何登录用户交回结果")

    # ---------- 不许当"存在性探针" ----------
    def test_unknown_job_id_looks_identical_for_owner_and_stranger(self):
        """任务号是 /api/jobs 会泄出去的东西：别人的号与不存在的号必须回一样的码。"""
        for method, template in GUARDED:
            with self.subTest(endpoint=template.format("job-nope")):
                stranger = self.hit(method, template.format("job-nope"), self.other)
                owner = self.hit(method, template.format("job-nope"), self.owner)
                self.assertEqual(stranger.status_code, 403)
                self.assertEqual(owner.status_code, stranger.status_code,
                                 "不存在的任务号与别人的任务号回话不同，等于白送一个探针")

    # ---------- 老任务没记 owner：退回项目归属 ----------
    def test_legacy_job_falls_back_to_project_owner(self):
        server.JOBS["job-legacy"] = {"project_id": "p9", "stage": "queued"}
        server._reg = lambda: {"projects": [{"project_id": "p9", "owner": OWNER}], "bundles": []}
        for method, template in GUARDED:
            with self.subTest(endpoint=template.format("job-legacy")):
                blocked = self.hit(method, template.format("job-legacy"), self.other)
                allowed = self.hit(method, template.format("job-legacy"), self.owner)
                self.assertEqual(blocked.status_code, 403, "老任务查项目归属这一步没生效")
                self.assertNotIn(allowed.status_code, (401, 403))

    # ---------- 管理员通道保留 ----------
    def test_admin_may_service_any_job(self):
        auth.create_user("boss@example.invalid", PASSWORD, role="admin")
        boss = auth.make_session("boss@example.invalid", auth.SESSION_TTL_SHORT)
        r = self.hit("POST", "/api/agent/job/job-mine/progress", boss)
        self.assertNotIn(r.status_code, (401, 403), "管理员兜底通道（运维/救单）不能被归属挡掉")


if __name__ == "__main__":
    unittest.main(verbosity=2)
