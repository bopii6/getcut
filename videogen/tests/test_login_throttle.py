"""登录防爆破限流的离线闸门。

跑法（在 videogen/ 目录下）：
    python -m unittest discover -s tests -t tests

为什么补这一条：登录接口以前只有一句 `time.sleep(0.6)`，而**兑换卡密那条早就有
"连错 5 次歇 60 秒"** —— 门后面是别人的选题稿、卡密和站长后台，门外反而最松。
客户 40~50 岁、弱口令概率高，哈希救不了字典攻击，只能靠次数上限。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="videogen-login-")
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

GOOD = "login-probe@example.invalid"
OTHER = "someone-else@example.invalid"
PASSWORD = "Nm4-Wq7Zk2Vb8Tr3Xy6"
WRONG = "完全不对的密码-1"
IP = "203.0.113.7"          # TEST-NET，不会是真客户地址
IP2 = "203.0.113.8"


def setUpModule():
    auth.USERS_FILE = Path(_TMP) / "users.json"
    auth.SECRET_FILE = Path(_TMP) / "auth-secret"
    auth.create_user(GOOD, PASSWORD, role="user")
    auth.create_user(OTHER, PASSWORD + "x", role="user")


class LoginThrottleTest(unittest.TestCase):
    def setUp(self):
        auth._login_fail.clear()
        self.client = TestClient(server.app, base_url="http://login.test")
        # 拖慢用的 sleep 不在本条测试范围内，去掉好让用例跑得快
        self._sleep = mock.patch.object(server.time, "sleep", lambda *_a, **_k: None)
        self._sleep.start()
        self.addCleanup(self._sleep.stop)

    def try_login(self, email, password, ip=IP):
        return self.client.post("/api/auth/login",
                                json={"email": email, "password": password},
                                headers={"x-forwarded-for": ip})

    # ---------- 基本行为 ----------
    def test_correct_password_still_logs_in(self):
        r = self.try_login(GOOD, PASSWORD)
        self.assertEqual(r.status_code, 200, "限流不能把正常登录挡在门外")

    def test_wrong_password_is_401_not_locked_immediately(self):
        r = self.try_login(GOOD, WRONG)
        self.assertEqual(r.status_code, 401)
        self.assertIn("邮箱或密码不对", r.json()["error"])

    def test_five_wrong_then_the_sixth_is_rejected_before_hashing(self):
        for n in range(auth.LOGIN_FAIL_LIMIT):
            self.assertEqual(self.try_login(GOOD, WRONG).status_code, 401, f"第 {n + 1} 次不该挡")
        r = self.try_login(GOOD, WRONG)
        self.assertEqual(r.status_code, 429)
        self.assertIn("试错次数太多", r.json()["error"])

    def test_lock_message_is_plain_and_offers_a_way_out(self):
        for _ in range(auth.LOGIN_FAIL_LIMIT):
            self.try_login(GOOD, WRONG)
        msg = self.try_login(GOOD, WRONG).json()["error"]
        self.assertIn("忘记密码", msg, "被挡时要顺手告诉人怎么办，别让人干等")
        self.assertTrue(any(ch.isdigit() for ch in msg), "要说清等多久")

    def test_a_different_ip_is_not_collaterally_locked(self):
        """按 (账号, IP) 计，而不是按账号全局计 —— 否则谁都能拿错密码把客户锁死。"""
        for _ in range(auth.LOGIN_FAIL_LIMIT):
            self.try_login(GOOD, WRONG, ip=IP)
        self.assertEqual(self.try_login(GOOD, WRONG, ip=IP2).status_code, 401,
                         "别人在爆破，不该把这台机器的正常用户一起关在门外")

    def test_other_accounts_are_unaffected_by_one_accounts_lockout(self):
        """这条盯着一个很容易写错的实现：按 IP 汇总时只准数这台机器自己的失败。"""
        for _ in range(auth.LOGIN_FAIL_LIMIT):
            self.try_login(GOOD, WRONG, ip=IP)
        self.assertEqual(self.try_login(OTHER, WRONG, ip=IP).status_code, 401,
                         "同一 IP 换一个邮箱就被连坐挡住了，等于替爆破者清场")

    def test_successful_login_clears_the_counter(self):
        for _ in range(auth.LOGIN_FAIL_LIMIT - 1):
            self.try_login(GOOD, WRONG)
        self.assertEqual(self.try_login(GOOD, PASSWORD).status_code, 200)
        # 前面那几次错不该累积到下一次：还能再错 4 次才挡
        for _ in range(auth.LOGIN_FAIL_LIMIT - 1):
            self.assertEqual(self.try_login(GOOD, WRONG).status_code, 401)
        self.assertEqual(self.try_login(GOOD, WRONG).status_code, 401, "登录成功后计数没清")

    def test_ip_wide_cap_stops_email_rotating_credential_stuffing(self):
        """换邮箱猛试：单账号没超上限，但这台 IP 的总失败数该封顶。"""
        for n in range(auth.LOGIN_IP_LIMIT):
            self.try_login(f"probe{n}@example.invalid", WRONG, ip=IP)
        self.assertEqual(self.try_login(GOOD, WRONG, ip=IP).status_code, 429,
                         "只按账号计数的话，换邮箱撞库可以无限试")

    def test_the_two_limits_sound_identical_to_the_caller(self):
        for n in range(auth.LOGIN_IP_LIMIT):        # 触发 IP 总量那条
            self.try_login(f"probe{n}@example.invalid", WRONG, ip=IP)
        by_ip = self.try_login(GOOD, WRONG, ip=IP).json()["error"]
        auth._login_fail.clear()
        for _ in range(auth.LOGIN_FAIL_LIMIT):      # 触发单账号那条
            self.try_login(GOOD, WRONG, ip=IP2)
        by_pair = self.try_login(GOOD, WRONG, ip=IP2).json()["error"]
        self.assertRegex(by_ip, r"试错次数太多.*再登录")
        self.assertEqual(by_ip.split("；")[0], by_pair.split("；")[0],
                         "两个维度说的话不一样，等于告诉对方自己是哪条挡的")

    def test_locked_out_does_not_burn_password_hashing(self):
        """被挡时不该再去跑 PBKDF2：那正是爆破者想看到的开销。"""
        for _ in range(auth.LOGIN_FAIL_LIMIT):
            self.try_login(GOOD, WRONG, ip=IP)
        orig = auth.verify_login
        calls = []
        auth.verify_login = lambda *a, **k: (calls.append(a), False)[1]
        try:
            self.assertEqual(self.try_login(GOOD, WRONG, ip=IP).status_code, 429)
        finally:
            auth.verify_login = orig
        self.assertEqual(calls, [], "挡在门外还去算哈希，白送对方一个 CPU 消耗点")

    def test_state_is_in_memory_by_design(self):
        """重启清零是**故意**的：宁可重启后多放行一次，也不把真客户永久锁在门外。
        这条断言存在，是为了让以后改成落盘的人必须回来解释清楚。"""
        self.assertIsInstance(auth._login_fail, dict)
        self.addCleanup(auth._login_fail.clear)


class AgentLoginThrottleTest(LoginThrottleTest):
    """/api/agent/login 必须和普通登录共用同一道闸门（整批断言直接继承过来跑）。

    它以前是一句裸 `verify_login`：不排队、不延时，每试一次还替对方跑一次 PBKDF2，
    试对了就签一张 90 天、不记设备的票。这条路口虽然不在匿名公开名单里
    （要先有一张会话才够得到），但**注册是开放的** —— 任何注册进来的人都能拿它
    去爆破别人的邮箱密码，而这台成片台票的分量比网页登录更重：拿到它就能领走
    那个客户的全部任务，连他还没交回服务器的口播、素材与成片都看得到。
    """

    def setUp(self):
        super().setUp()
        # 够得到这道口要先有一张会话（它不在 _PUBLIC_PATHS 里）：模拟"已登录的
        # 别人"来换票，正是要限流的那个身份
        self.sess = auth.make_session(OTHER, auth.SESSION_TTL_SHORT)

    def try_login(self, email, password, ip=IP):
        return self.client.post("/api/agent/login",
                                json={"email": email, "password": password,
                                      "device": "客厅那台"},
                                headers={"x-forwarded-for": ip},
                                cookies={server.SESSION_COOKIE: self.sess})

    def test_token_records_which_device_it_was_issued_to(self):
        """90 天的设备令牌不能是匿名的一张空白票：得能在「登录设备」里被认出来踢掉。"""
        r = self.try_login(GOOD, PASSWORD)
        self.assertEqual(r.status_code, 200, r.text)
        rows = [x for x in auth.list_sessions(GOOD) if x["ip"] == IP]
        self.assertTrue(rows, "设备令牌没登记来源 IP，登录设备列表里查不到它")
        self.assertTrue(any(x["device"] == "客厅那台" for x in rows),
                        "设备令牌没记是哪台机器，客户想只踢这一台都挑不出来")


if __name__ == "__main__":
    unittest.main(verbosity=2)
