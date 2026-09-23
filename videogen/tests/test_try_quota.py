"""试玩额度：花真钱的公开接口，账本要挡得住"换张脸再来一次"。

跑法（在 videogen/ 目录下）：
    python -m unittest discover -s tests -t tests

锁住 2026-09-21 傍晚那一轮的三处修法（评审 §7 P0-④）：
  1. `_client_ip` 只在**直连来源本身就是代理**时才认 X-Forwarded-For。
     以前第一段随便客户端写 → 一行 curl 就能凭空造额度（试玩要跑 LLM 与 TTS）。
  2. `guard()` 判定与记账在同一把锁里、一次写盘。以前"先判后记"分两步，
     并发几个请求各自都看到"今天还没用过"。
  3. 账本键数有上限。以前只按时间清理，公开接口可以拿新 cookie 把状态文件撑大。
"""
from __future__ import annotations

import ipaddress
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="videogen-try-")
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

from starlette.requests import Request  # noqa: E402

from videogen import auth, server, try_topics  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


def _req(peer: str, fwd: str = "") -> Request:
    headers = []
    if fwd:
        headers.append((b"x-forwarded-for", fwd.encode()))
    return Request({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                    "method": "GET", "scheme": "https", "path": "/api/try",
                    "raw_path": b"/api/try", "query_string": b"", "root_path": "",
                    "headers": headers, "client": (peer, 40000) if peer else None,
                    "server": ("getcut.test", 443)})


class ClientIpTest(unittest.TestCase):
    """IP 是限流的锚点：锚点能被客户端涂改，额度就等于没有。"""

    def test_public_peer_ignores_spoofed_forwarded_header(self):
        """直连就是公网 IP（裸端口的接法）→ XFF 是客户端自己写的，不认。"""
        for peer in ("203.0.113.7", "8.8.8.8"):
            r = _req(peer, "1.2.3.4")
            self.assertEqual(server._client_ip(r), peer,
                             "换一行 XFF 就换一张脸，试玩与发码额度全部作废")

    def test_proxy_peer_may_supply_the_real_customer_ip(self):
        """生产是 Caddy 与容器同机：peer 是回环，这时 XFF 第一段才可信。
        把这条改坏，服务器上看到的就是 127.0.0.1 一个桶 —— 所有人一起被限流。"""
        for peer in ("127.0.0.1", "::1"):
            r = _req(peer, "203.0.113.55, 10.0.0.1")
            self.assertEqual(server._client_ip(r), "203.0.113.55")

    def test_private_peer_is_treated_as_a_proxy_too(self):
        """同内网反代（10./172.16-31./192.168.）也常见，认。"""
        self.assertEqual(server._client_ip(_req("10.0.0.9", "203.0.113.60")), "203.0.113.60")

    def test_missing_forwarded_header_falls_back_to_the_peer(self):
        self.assertEqual(server._client_ip(_req("203.0.113.7")), "203.0.113.7")
        self.assertEqual(server._client_ip(_req("203.0.113.7", "   ")), "203.0.113.7")
        self.assertEqual(server._client_ip(_req("")), "?")

    def test_env_override_for_explicitly_trusted_proxies(self):
        old = os.environ.get("VIDEOGEN_TRUST_PROXY_HEADERS")
        os.environ["VIDEOGEN_TRUST_PROXY_HEADERS"] = "1"
        try:
            self.assertEqual(server._client_ip(_req("203.0.113.7", "198.51.100.4")),
                             "198.51.100.4")
        finally:
            if old is None:
                os.environ.pop("VIDEOGEN_TRUST_PROXY_HEADERS", None)
            else:
                os.environ["VIDEOGEN_TRUST_PROXY_HEADERS"] = old

    def test_peers_are_real_addresses(self):
        """这条只是自校验：上面用的样例地址形状要对，否则前面的断言在测空气。"""
        for peer in ("203.0.113.7", "127.0.0.1", "10.0.0.9", "8.8.8.8"):
            ipaddress.ip_address(peer)


class TryLedgerTest(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="vg-try-", dir=_TMP))
        self.path = try_topics._store_path(self.ws)
        self._limits = (try_topics.IP_LIMIT, try_topics.MAX_KEYS)

    def tearDown(self):
        try_topics.IP_LIMIT, try_topics.MAX_KEYS = self._limits

    def _ledger(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_first_visit_passes_and_is_recorded(self):
        ok, why, issued = try_topics.guard(self.ws, "203.0.113.10", "")
        self.assertTrue(ok, why)
        self.assertTrue(issued, "没回一个可记住的浏览器标识")
        self.assertIn(issued, self._ledger()["cookies"])

    def test_same_browser_cannot_ask_twice(self):
        ok, _, issued = try_topics.guard(self.ws, "203.0.113.11", "")
        self.assertTrue(ok)
        ok2, why, got = try_topics.guard(self.ws, "203.0.113.11", issued)
        self.assertFalse(ok2, "同一个浏览器第二次也放行了")
        self.assertEqual(why, "这个浏览器已经试做过了")
        self.assertEqual(got, "")

    def test_ip_allowance_is_per_ip_not_global(self):
        """两个客户不该共用一个额度桶。"""
        for _ in range(try_topics.IP_LIMIT):
            self.assertTrue(try_topics.guard(self.ws, "203.0.113.20", "")[0])
        self.assertFalse(try_topics.guard(self.ws, "203.0.113.20", "")[0])
        self.assertTrue(try_topics.guard(self.ws, "198.51.100.20", "")[0],
                        "隔壁 IP 被一起限死了")

    def test_concurrent_requests_cannot_double_spend(self):
        """没有锁的话这 12 个线程会各自读到"今天还没用过"，额度形同虚设。"""
        try_topics.IP_LIMIT = 2
        accepted: list = []
        gate = threading.Barrier(12)

        def one():
            gate.wait()
            ok, _, _ = try_topics.guard(self.ws, "203.0.113.30", "")
            if ok:
                accepted.append(ok)

        ts = [threading.Thread(target=one) for _ in range(12)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(20)
        self.assertEqual(len(accepted), try_topics.IP_LIMIT,
                         "并发把 %d 次额度花成了 %d 次" % (try_topics.IP_LIMIT, len(accepted)))
        self.assertEqual(len(self._ledger()["ips"]["203.0.113.30"]), try_topics.IP_LIMIT)

    def test_ledger_stays_bounded_under_flood(self):
        """公开接口不许被拿新 cookie 撑大：这是状态文件，每天还进备份。"""
        try_topics.MAX_KEYS = 40
        for i in range(200):
            try_topics.guard(self.ws, "203.0.113.%d" % (i % 250 + 1), "c%05d" % i)
        data = self._ledger()
        self.assertLessEqual(len(data["cookies"]), 40, "cookie 表无界增长")
        self.assertLessEqual(len(data["ips"]), 40, "ip 表无界增长")
        self.assertLess(self.path.stat().st_size, 64 * 1024, "账本文件体积失控")

    def test_expired_entries_are_dropped_on_write(self):
        now = try_topics.time.time()
        self.path.write_text(json.dumps(
            {"cookies": {"old": now - 90 * 86400, "fresh": now},
             "ips": {"203.0.113.40": [now - 48 * 3600]}}), encoding="utf-8")
        self.assertTrue(try_topics.guard(self.ws, "203.0.113.41", "")[0])
        data = self._ledger()
        self.assertNotIn("old", data["cookies"], "90 天前的浏览器记录还留着")
        self.assertNotIn("203.0.113.40", data["ips"], "两天前的 IP 记录还算在今天额度里")

    def test_newest_keys_survive_the_cap(self):
        """淘汰要留最新的：留下最旧的那批等于把刚来的客户踢掉、把老记录当宝。"""
        try_topics.MAX_KEYS = 2
        keep = try_topics._newest({"a": 1.0, "b": 3.0, "c": 2.0}, 2)
        self.assertEqual(sorted(keep), ["b", "c"])
        keep2 = try_topics._newest({"x": [1.0], "y": [9.0], "z": [5.0]}, 2)
        self.assertEqual(sorted(keep2), ["y", "z"])


class TryLoginAndOwnershipTest(unittest.TestCase):
    """试玩：必须登录才能玩，出好的样片只给本人（2026-09-23 隔离定调）。

    以前 `/api/try` 匿名可提交、`/try/<id>.mp4` 匿名可下载 —— 任务号会直接出现在
    链接里，等于谁拿到号就能下别人的片子；而试玩单没有归属，普通客户的成片台
    按"只领自己的单"领不走 ⇒ 线上 100% 不出片，还每条占死一条渲染线程最长 24 小时。
    """

    A = "try-a@example.invalid"
    B = "try-b@example.invalid"
    PW = "Km4-Vb8Qz2Xw7Nt3Rd6P"

    def setUp(self):
        auth.USERS_FILE = Path(_TMP) / "try-users.json"
        auth.SECRET_FILE = Path(_TMP) / "try-secret"
        for e in (self.A, self.B):
            try:
                auth.create_user(e, self.PW, role="user")
            except Exception:  # noqa: BLE001 - 同一条用例重复建号
                pass
        self.ck_a = {server.SESSION_COOKIE: auth.make_session(self.A, auth.SESSION_TTL_SHORT)}
        self.ck_b = {server.SESSION_COOKIE: auth.make_session(self.B, auth.SESSION_TTL_SHORT)}
        self.client = TestClient(server.app, base_url="http://try.test")
        self._jobs = dict(server.JOBS)
        server.JOBS.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        server.JOBS.clear()
        server.JOBS.update(self._jobs)

    def test_anonymous_submission_is_rejected_with_the_freebie_promise(self):
        r = self.client.post("/api/try", json={"topic": "anything"})
        self.assertEqual(r.status_code, 401, "免登录还能提交试玩 = 陌生人白烧服务器额度")
        self.assertIn("2 条", r.json()["error"], "被挡住时该告诉他登录后能得到什么")

    def test_sample_video_is_owner_only(self):
        mp4 = Path(_TMP) / "sample.mp4"
        mp4.write_bytes(b"x" * 64)
        jid = "a1b2c3d4e5f6"
        server.JOBS[jid] = {"stage": "done", "owner": self.A,
                            "try": {"topic": "t1", "title": "别人的样片"},
                            "try_video": str(mp4)}
        self.assertEqual(self.client.get(f"/try/{jid}.mp4").status_code, 403, "匿名能下别人的样片")
        self.assertEqual(self.client.get(f"/try/{jid}.mp4", cookies=self.ck_b).status_code, 403,
                         "别的登录用户能下别人的样片")
        self.assertEqual(self.client.get(f"/try/{jid}.mp4", cookies=self.ck_a).status_code, 200,
                         "正主反而下不到自己那条")
        self.assertEqual(self.client.get(f"/api/try/{jid}", cookies=self.ck_b).status_code, 403)

    def test_orphan_try_jobs_belong_to_nobody_but_the_station(self):
        """老数据里那些没记归属的试玩单：不给任何登录用户，只给站长通道。"""
        mp4 = Path(_TMP) / "old.mp4"
        mp4.write_bytes(b"y" * 64)
        server.JOBS["f0e1d2c3b4a5"] = {"stage": "done", "try": {"topic": "t"},
                                       "try_video": str(mp4)}
        self.assertEqual(self.client.get("/try/f0e1d2c3b4a5.mp4",
                                         cookies=self.ck_a).status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
