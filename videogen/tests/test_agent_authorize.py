"""Agent 一次性账号授权：未登录不能授权，令牌只回到持有 poll secret 的 Agent。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="videogen-agent-authorize-")
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

from videogen import auth, server, agent_auth  # noqa: E402

EMAIL = "agent-authorize@example.invalid"
PASSWORD = "Zk9-mVx4QsT7pLd2Rb8H"
BASE = "http://agent-authorize.test"


def setUpModule():
    auth.USERS_FILE = Path(_TMP) / "users.json"
    auth.SECRET_FILE = Path(_TMP) / "auth-secret"
    auth.create_user(EMAIL, PASSWORD, role="user")


class AgentAuthorizeTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url=BASE)
        self.cookie = {server.SESSION_COOKIE: auth.make_session(EMAIL, auth.SESSION_TTL_SHORT)}

    def start(self):
        r = self.client.post("/api/agent/authorize/start", json={"device": "我的电脑 Agent"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_start_is_public_but_page_never_returns_token(self):
        out = self.start()
        self.assertIn("request_id", out)
        self.assertIn("poll_secret", out)
        page = self.client.get("/agent/authorize", params={"request_id": out["request_id"]})
        self.assertEqual(page.status_code, 200)
        self.assertIn("授权这台电脑", page.text)
        self.assertNotIn(out["poll_secret"], page.text)

    def test_approval_requires_browser_login_and_binds_current_account(self):
        out = self.start()
        path = "/api/agent/authorize/approve"
        body = {"request_id": out["request_id"]}
        self.assertEqual(self.client.post(path, json=body).status_code, 401)
        approved = self.client.post(path, json=body, cookies=self.cookie)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["email"], EMAIL)
        self.assertNotIn("token", approved.text)

    def test_agent_poll_receives_token_once_and_then_consumes_request(self):
        out = self.start()
        body = {"request_id": out["request_id"], "poll_secret": out["poll_secret"]}
        self.client.post("/api/agent/authorize/approve", json={"request_id": out["request_id"]},
                         cookies=self.cookie)
        first = self.client.post("/api/agent/authorize/poll", json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["status"], "approved")
        token = first.json()["token"]
        self.assertTrue(token)
        who = self.client.get("/api/agent/whoami", headers={"x-agent-token": token})
        self.assertEqual(who.status_code, 200, who.text)
        self.assertEqual(who.json()["email"], EMAIL)
        second = self.client.post("/api/agent/authorize/poll", json=body)
        self.assertEqual(second.json()["status"], "consumed")

    def test_wrong_poll_secret_cannot_receive_approved_token(self):
        out = self.start()
        self.client.post("/api/agent/authorize/approve", json={"request_id": out["request_id"]},
                         cookies=self.cookie)
        wrong = self.client.post("/api/agent/authorize/poll", json={
            "request_id": out["request_id"], "poll_secret": "not-the-secret"})
        self.assertEqual(wrong.status_code, 404)

    def test_authorization_request_cannot_be_approved_twice(self):
        out = self.start()
        body = {"request_id": out["request_id"]}
        self.assertEqual(self.client.post("/api/agent/authorize/approve", json=body,
                                          cookies=self.cookie).status_code, 200)
        self.assertEqual(self.client.post("/api/agent/authorize/approve", json=body,
                                          cookies=self.cookie).status_code, 409)

    def test_expired_request_is_not_approved(self):
        out = self.start()
        with agent_auth._lock:
            data = agent_auth._load()
            data["requests"][out["request_id"]]["expires"] = 0
            agent_auth._save(data)
        r = self.client.post("/api/agent/authorize/approve",
                             json={"request_id": out["request_id"]}, cookies=self.cookie)
        self.assertEqual(r.status_code, 404)
        self.assertIn("过期", r.json()["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
