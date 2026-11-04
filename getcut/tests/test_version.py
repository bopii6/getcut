""""线上是哪一版"的闸门：版本来源优先级 + 端点不裸奔 + 部署链路上的三处接线。

跑法（在 getcut/ 目录下）：
    python -m unittest discover -s tests -t tests

这条治的是评估里"部署无版本"那一环：出事时答不出线上跑的是哪个 commit、
依赖是哪一版，就没法二分是代码引起的还是依赖引起的。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="getcut-ver-")
os.environ.update({
    "GETCUT_WORKSPACE": _TMP,
    "GETCUT_USERS_FILE": str(Path(_TMP) / "users.json"),
    "GETCUT_LICENSES_FILE": str(Path(_TMP) / "licenses.json"),
    "GETCUT_USAGE_FILE": str(Path(_TMP) / "usage.json"),
    "GETCUT_AUTH_SECRET": str(Path(_TMP) / "auth-secret"),
    "GETCUT_BRAND_DIR": str(Path(_TMP) / "brand"),
    "GETCUT_JOBS_FILE": str(Path(_TMP) / "jobs.json"),
    "GETCUT_REGISTRY_FILE": str(Path(_TMP) / "registry.json"),
    "GETCUT_ACCESS_TOKEN": "",
    "EMAIL_SMTP_HOST": "",
})

from starlette.testclient import TestClient  # noqa: E402

from getcut import auth, server, version  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent          # getcut/
PROBE = "ver-probe@example.invalid"
PASSWORD = "Hq2-Vn7Rt4Kw9Zx3Lb6M"


def setUpModule():
    auth.USERS_FILE = Path(_TMP) / "users.json"
    auth.SECRET_FILE = Path(_TMP) / "auth-secret"
    auth.create_user(PROBE, PASSWORD, role="user")


class VersionSourceTest(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in
                     ("GETCUT_BUILD_SHA", "GETCUT_BUILD_BRANCH", "GETCUT_BUILD_DATE")}
        self._files = version.INFO_FILES
        self.dir = Path(tempfile.mkdtemp(prefix="getcut-ver-case-"))

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        version.INFO_FILES = self._files

    def test_build_arg_env_wins(self):
        os.environ["GETCUT_BUILD_SHA"] = "deadbeef"
        os.environ["GETCUT_BUILD_BRANCH"] = "main"
        got = version.info()
        self.assertEqual((got["sha"], got["branch"], got["source"]), ("deadbeef", "main", "env"))

    def test_deploy_written_file_is_next_in_line(self):
        f = self.dir / "BUILD_INFO.json"
        f.write_text(json.dumps({"sha": "abc1234", "branch": "main", "built": "2026-09-21T12:00:00+08:00",
                                 "dirty": True}), encoding="utf-8")
        version.INFO_FILES = (f,)
        got = version.info()
        self.assertEqual((got["sha"], got["dirty"], got["source"]), ("abc1234", True, "BUILD_INFO.json"))
        self.assertTrue(got["built"], "部署时间要带出来，不然还是答不出几点上的线")

    def test_unknown_sha_in_file_is_not_a_version(self):
        f = self.dir / "BUILD_INFO.json"
        f.write_text(json.dumps({"sha": ""}), encoding="utf-8")
        version.INFO_FILES = (f,)
        self.assertEqual(version._from_file(), {}, "空 sha 不能当成一个可信版本号")

    def test_corrupt_file_falls_through_to_the_next_candidate(self):
        bad = self.dir / "bad.json"
        bad.write_text("{坏了", encoding="utf-8")
        good = self.dir / "good.json"
        good.write_text(json.dumps({"sha": "fcc0a8e"}), encoding="utf-8")
        version.INFO_FILES = (bad, good)
        self.assertEqual(version.info()["sha"], "fcc0a8e")

    def test_nothing_known_says_unknown(self):
        for k in self._env:
            os.environ.pop(k, None)
        version.INFO_FILES = (self.dir / "不存在.json",)
        orig_git = version._git
        version._git = lambda *a: ""
        try:
            got = version.info()
        finally:
            version._git = orig_git
        self.assertEqual(got["sha"], "unknown", "问不出来时不许编一个像样的假版本号")
        self.assertEqual(got["source"], "none")


class VersionEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url="http://ver.test")

    def test_version_endpoint_is_not_public(self):
        r = self.client.get("/api/version")
        self.assertEqual(r.status_code, 401, "匿名能读到精确版本与依赖清单，等于替人踩点")

    def test_logged_in_sees_commit_and_real_dependency_versions(self):
        session = auth.make_session(PROBE, auth.SESSION_TTL_SHORT)
        r = self.client.get("/api/version", cookies={server.SESSION_COOKIE: session})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("sha", body)
        self.assertIn("source", body)
        # 读的是运行时真装着的版本，不是 requirements 里的期望值
        for name in ("fastapi", "starlette", "websockets", "pillow"):
            self.assertIn(name, body["deps"])

    def test_healthz_still_answers_without_auth_but_lies_about_nothing(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("ok"))
        # 以前它回一个硬编码 "version": "1.0"：说了等于没说，还让人以为读到了线上版本
        self.assertNotIn("version", r.json(), "匿名探针别再回报一个写死的版本号")


class DeploymentWiringTest(unittest.TestCase):
    """链路每一环都要有断言，漏一处就等于这条措施没做。"""

    def test_dockerfile_declares_and_injects_the_build_args(self):
        d = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ARG GIT_SHA", d)
        self.assertIn("GETCUT_BUILD_SHA=$GIT_SHA", d)

    def test_ci_image_build_passes_the_commit(self):
        y = (ROOT.parent / ".github" / "workflows" / "docker.yml").read_text(encoding="utf-8")
        self.assertIn("build-args", y)
        self.assertIn("GIT_SHA=${{ github.sha }}", y)

    def test_deploy_script_records_the_commit_it_mounted(self):
        s = (ROOT / "tools" / "deploy_new.sh").read_text(encoding="utf-8")
        self.assertIn("BUILD_INFO.json", s)
        self.assertIn("git -C code rev-parse --short HEAD", s)

    def test_deploy_script_no_longer_installs_unpinned_dependencies(self):
        raw = (ROOT / "tools" / "deploy_new.sh").read_text(encoding="utf-8")
        # 只看真正会执行的行：注释里那句"以前是 pip install websockets>=14"是写给后人看的
        code = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("#"))
        self.assertNotIn("websockets>=", code, "部署时还在装不钉版本的包，等于每天重建一次依赖漂移")
        self.assertNotIn("cos-python-sdk-v5>=", code)
        self.assertRegex(code, r"install_if_missing\s+websockets\s+\"websockets==[0-9.]+\"")
        self.assertRegex(code, r"install_if_missing\s+qcloud_cos\s+\"cos-python-sdk-v5==[0-9.]+\"")
        self.assertNotIn("pip install --no-input -q \"$2\" || true", code, "装失败不许再被吞掉")

    def test_build_info_is_not_committable(self):
        """部署写出来的版本标记是每台机器各说各的，入库等于把一个假版本号钉进代码里
        （开发机上提交的 commit 会冒充生产在跑的那一版）。"""
        f = ROOT / "getcut" / "BUILD_INFO.json"
        f.write_text('{"sha":"deadbee"}', encoding="utf-8")
        try:
            r = subprocess.run(["git", "check-ignore", "-q", "getcut/getcut/BUILD_INFO.json"],
                               cwd=ROOT.parent, capture_output=True)
            if r.returncode == 128:
                self.skipTest("这里没有可用的 git")
            self.assertEqual(r.returncode, 0, "BUILD_INFO.json 没被 .gitignore 挡住")
        finally:
            f.unlink(missing_ok=True)

    def test_deploy_pins_match_the_lock(self):
        """部署脚本里钉的版本必须和 requirements.lock 一致，否则两处各说一套。"""
        locked = {}
        for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "==" in line and not line.startswith("#"):
                n, v = line.split("==", 1)
                locked[n.strip().lower()] = v.strip()
        sh = (ROOT / "tools" / "deploy_new.sh").read_text(encoding="utf-8")
        for name in ("websockets", "cos-python-sdk-v5"):
            hits = re.findall(r'%s==([0-9][0-9.]*)' % re.escape(name), sh)
            self.assertTrue(hits, "部署脚本里没钉 %s" % name)
            self.assertEqual(hits[0], locked.get(name),
                             "%s：部署脚本钉 %s，锁定表写 %s" % (name, hits[0], locked.get(name)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
