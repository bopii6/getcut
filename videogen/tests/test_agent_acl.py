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

from videogen import agenthub, ctx, auth, server  # noqa: E402

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
# 这三个在归属之外还查认领凭据（见 test_compositor_endpoints_require_the_claim）：
# 没有"真领一次单"就没法断言"正主不被误伤"，这类循环只挑不用凭据的那两个口
CLAIMED = ("progress", "visual", "layer")


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
        self._reg = ctx._reg
        server.JOBS.clear()
        server.JOBS["job-mine"] = {"owner": OWNER, "project_id": "p1", "stage": "queued"}
        self.raw_try = Path(_TMP) / "try-raw.mp4"
        self.raw_try.write_bytes(b"RAW-TRY-PRIVATE")
        server.JOBS["job-try"] = {
            "owner": OWNER, "try": True, "project_id": None, "stage": "done",
            "video": str(self.raw_try), "try_video": str(self.raw_try),
        }
        server.JOBS["job-try-anon"] = {"try": True, "project_id": None, "stage": "queued"}
        self.owner = auth.make_session(OWNER, auth.SESSION_TTL_SHORT)
        self.other = auth.make_session(INTRUDER, auth.SESSION_TTL_SHORT)
        # 真领一次单，拿这张任务此刻的认领凭据：progress/visual/layer 认的是它，
        # 不再认客户端自报的设备名（自报名能让同账号另一个标签页冒充在渲的那台）
        agenthub._JOBS.clear()
        agenthub._DEVICES.clear()
        agenthub.register("job-mine", OWNER, {"a": 1}, {},
                          str(Path(_TMP) / "out.mp4"))
        got = agenthub.wait_for_job([OWNER], "owner-pc", timeout=0.0)
        self.claim = (got or {}).get("claim") or ""

    def tearDown(self):
        server.JOBS.clear()
        server.JOBS.update(self._jobs)
        agenthub._JOBS.clear()
        agenthub._DEVICES.clear()
        ctx._reg = self._reg

    def hit(self, method, path, session, token=False, claim=None):
        if token:
            kw = {"headers": {"x-agent-token": session}}
        else:
            kw = {"cookies": {server.SESSION_COOKIE: session}}
        if claim:
            kw.setdefault("headers", {})["x-agent-claim"] = claim
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
                    r = self.hit(method, template.format("job-mine"), self.owner,
                                 token=channel == "token", claim=self.claim)
                    self.assertNotIn(r.status_code, (401, 403),
                                     "归属校验误伤了正主（令牌与 cookie 两条通道都要认）")

    # ---------- 认领凭据：不是领取者就别想改写这一单 ----------
    def test_compositor_endpoints_require_the_claim(self):
        """同账号另一台设备（拿着自己的会话、没有凭据）不能冒充在渲的那台。

        以前这三个口认的是 `?device=` 自报的名字：另一个标签页填同一个名字
        就能把这台正在渲的单 requeue 掉，甚至交一份别的 mp4 当成片。
        """
        for path in ("/api/agent/job/job-mine/progress",
                     "/api/agent/job/job-mine/visual",
                     "/api/agent/job/job-mine/layer?name=base.png"):
            for claim in (None, "wrong-claim"):
                with self.subTest(path=path, claim=bool(claim)):
                    head = {} if claim is None else {"x-agent-claim": claim}
                    r = self.client.request("POST", path, json={}, headers=head,
                                            cookies={server.SESSION_COOKIE: self.owner})
                    self.assertIn(r.status_code, (403, 410),
                                  "%s 没查认领凭据：任何同账号页面都能改写这一单" % path)
        # 媒体与文件下载只查归属（页面刷新后要能接着取素材）
        r = self.hit("GET", "/api/agent/job/job-mine/file?path=props.json", self.owner)
        self.assertNotIn(r.status_code, (401, 403))

    # ---------- 匿名：先被闸门挡在门外 ----------
    def test_anonymous_gets_401_not_403(self):
        for method, template in GUARDED:
            with self.subTest(endpoint=template.format("job-mine")):
                r = self.client.request(method, template.format("job-mine"), json={})
                self.assertEqual(r.status_code, 401)

    # ---------- 试玩任务：本人可见，通用接口不得泄露内部路径 ----------
    def test_try_job_is_not_open_to_strangers(self):
        """2026-09-23 隔离定调：一条片子只有本人（与本来就能领它的站长通道）能经手。

        以前这条反过来断言（"试玩单要能让任何登录用户交回结果"），配合无主 owner
        等于给"往别人的任务上塞 mp4"开了门。
        """
        for job in ("job-try", "job-try-anon"):
            for method, template in GUARDED:
                with self.subTest(job=job, endpoint=template.format(job)):
                    r = self.hit(method, template.format(job), self.other)
                    self.assertEqual(r.status_code, 403, "试玩单对不是正主的登录用户放行了")
                    own = self.hit(method, template.format(job), self.owner, claim=self.claim)
                    if job == "job-try" and not any(c in template for c in CLAIMED):
                        self.assertNotIn(own.status_code, (401, 403))

    def test_generic_job_status_does_not_expose_try_paths(self):
        for session in (self.owner, self.other):
            with self.subTest(owner=session == self.owner):
                r = self.client.get(
                    "/api/job/job-try",
                    cookies={server.SESSION_COOKIE: session},
                )
                self.assertNotIn(str(self.raw_try), r.text)
                self.assertNotIn("try_video", r.text)
                self.assertNotIn("work_dir", r.text)

    def test_raw_try_video_is_never_served_by_generic_video_route(self):
        for session in (self.owner, self.other):
            with self.subTest(owner=session == self.owner):
                r = self.client.get(
                    "/video/job-try",
                    cookies={server.SESSION_COOKIE: session},
                )
                self.assertEqual(r.status_code, 404)
                self.assertNotIn(b"RAW-TRY-PRIVATE", r.content)

    # ---------- 管理员的兜底：看得到、救得了，但不冒充渲染方 ----------
    def test_admin_can_look_but_not_report_without_claim(self):
        auth.create_user("boss@example.invalid", PASSWORD, role="admin")
        boss = auth.make_session("boss@example.invalid", auth.SESSION_TTL_SHORT)
        r = self.hit("GET", "/api/agent/job/job-mine/file?path=props.json", boss)
        self.assertNotIn(r.status_code, (401, 403),
                         "管理员兜底通道（运维/救单）不能被归属挡掉")
        r = self.hit("POST", "/api/agent/job/job-mine/progress", boss)
        self.assertEqual(r.status_code, 403,
                         "没领单的管理员不该能改写这一单的进度与状态")

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
        ctx._reg = lambda: {"projects": [{"project_id": "p9", "owner": OWNER}], "bundles": []}
        for method, template in GUARDED:
            with self.subTest(endpoint=template.format("job-legacy")):
                blocked = self.hit(method, template.format("job-legacy"), self.other)
                allowed = self.hit(method, template.format("job-legacy"), self.owner)
                self.assertEqual(blocked.status_code, 403, "老任务查项目归属这一步没生效")
                if not any(c in template for c in CLAIMED):
                    self.assertNotIn(allowed.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main(verbosity=2)
