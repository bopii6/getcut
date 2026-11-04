"""成片台认领凭据与收回的闸门（2026-09-23 隔离定调那一轮加的）。

要钉住的是四件以前钉不住的事：
1. 领单发下来的 `claim` 才是"这台在渲这一单"的凭证；`?device=` 只是标签。
   以前上报认的是设备名，同账号另开一页填同一个名字就能把别人的单 requeue 掉。
2. 无主的公开试玩单只能由站长/开放模式那台领，普通客户的成片台领不走。
3. 收回重排（失联、主动交还）必须把设备表里"它在渲这条"那行抹掉，
   并换一张新凭据 —— 旧凭据从此不能再改写这一单。
4. `wait_result` 的 patience 生效：公开入口那种单不能把渲染灶台线程占满 24 小时。
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="getcut-claim-")
os.environ.update({
    "GETCUT_WORKSPACE": _TMP,
    "GETCUT_USERS_FILE": str(Path(_TMP) / "users.json"),
    "GETCUT_AUTH_SECRET": str(Path(_TMP) / "auth-secret"),
    "GETCUT_BRAND_DIR": str(Path(_TMP) / "brand"),
    "GETCUT_JOBS_FILE": str(Path(_TMP) / "jobs.json"),
    "GETCUT_REGISTRY_FILE": str(Path(_TMP) / "registry.json"),
    "GETCUT_ACCESS_TOKEN": "",
})

from getcut import agenthub                      # noqa: E402
from getcut.api import agent as agent_api        # noqa: E402

OWNER = "owner@example.invalid"


class Base(unittest.TestCase):
    def setUp(self):
        agenthub._JOBS.clear()
        agenthub._DEVICES.clear()
        agenthub._LAYER_SLOTS.clear()
        self.out = str(Path(_TMP) / "out.mp4")

    def register(self, job="j1", owner=OWNER):
        agenthub.register(job, owner, {"durationInFrames": 3}, {}, self.out)
        got = agenthub.wait_for_job([owner] if owner else [], "pc-a", timeout=0.0)
        self.assertIsNotNone(got, "正常领单没领到")
        return got

    def tearDown(self):
        agenthub._JOBS.clear()
        agenthub._DEVICES.clear()
        agenthub._LAYER_SLOTS.clear()


class ClaimTest(Base):
    def test_poll_hands_out_a_claim(self):
        got = self.register()
        claim = got.get("claim") or ""
        self.assertGreaterEqual(len(claim), 16, "领单没发认领凭据")
        # 拿凭据才报得动进度；拿不到就一直 403
        self.assertNotIn("claim_bad", agenthub.progress("j1", claim, 40, "生成中"))
        self.assertIn("claim_bad", agenthub.progress("j1", "steal", 41, "x"))
        self.assertIn("claim_bad", agenthub.progress("j1", "", 42, "x"))

    def test_stale_claim_dies_on_reclaim(self):
        got = self.register()
        claim = got["claim"]
        # 模拟失联：直接把 t_progress 推到超时线之前，再跑一轮 wait_result 的判定
        with agenthub._CV:
            agenthub._JOBS["j1"]["t_progress"] = time.time() - agenthub._STALL_SECONDS - 1
        try:
            agenthub.wait_result("j1", patience=1.0)
        except RuntimeError:
            pass
        with agenthub._CV:
            j = agenthub._JOBS["j1"]
            self.assertEqual(j["status"], "waiting", "失联没收回")
            self.assertNotEqual(j.get("claim"), claim, "旧凭据居然还能用")
            self.assertIsNone(agenthub._DEVICES.get(
                agenthub._dev_key(OWNER, "pc-a"))["job"],
                "设备表里那行「它在渲」没抹掉，排障时以为它还在干活")
        self.assertIn("claim_bad", agenthub.progress("j1", claim, 50, "旧页面上报"))

    def test_layer_name_rejects_trailing_newline(self):
        got = self.register()
        self.assertIsNone(agenthub.layer_target("j1", got["claim"], "texts.json\n"),
                          "尾随换行的图层名能过白名单（会写出一个野文件名、真图层却缺失）")
        self.assertIsNone(agenthub.layer_target("j1", "nope", "base.png"))


class OwnershipTest(Base):
    def test_anonymous_try_job_only_the_station_can_claim(self):
        agenthub.register("try1", None, {"a": 1}, {}, self.out)
        # 普通客户：只领自己的，无主单领不走
        self.assertIsNone(agenthub.wait_for_job(agent_api._claim_owners(OWNER),
                                                "pc-cust", timeout=0.0))
        # 站长那台（管理员）与开放模式那台能领
        self.assertIsNotNone(agenthub.wait_for_job(agent_api._claim_owners("__admin__"),
                                                   "pc-boss", timeout=0.0))

    def test_wait_result_honours_patience(self):
        """公开试玩那种单最多占一条渲染灶台线程几分钟，不是 24 小时。"""
        agenthub.register("j2", None, {"a": 1}, {}, self.out)
        t0 = time.time()
        with self.assertRaises(RuntimeError):
            agenthub.wait_result("j2", patience=1.0)
        self.assertLess(time.time() - t0, 5.0, "patience 没生效，线程被这条单占死了")


if __name__ == "__main__":
    unittest.main(verbosity=2)
