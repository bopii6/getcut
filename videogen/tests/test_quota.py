"""免费档每日额度的账本闸门：被挡的那一次不许算进账。

跑法（在 videogen/ 目录下）：
    python -m unittest discover -s tests -t tests

两处真问题（2026-09-21 复查发现并修）：
  1. 以前是「先 _usage_bump 再判超限」，于是被 429 拒掉的尝试也一直往账上加数，
     「我的」里会出现 **已用 7 / 2 条** 这种让客户以为计量坏了的话。
  2. 账本读坏了以前是 `except: pass` 当"谁都没用过" —— 等于给所有免费档当场重发额度，
     与第 8 节刚修的"坏文件不许当空库"是同一个病。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="videogen-quota-")
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

from videogen import ctx, config, safestore, server  # noqa: E402

CUSTOMER = "quota@example.invalid"
TODAY = time.strftime("%Y-%m-%d")


def day(offset_days: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400 * offset_days))


class QuotaLedgerTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="videogen-quota-case-"))
        self._saved = (ctx.USAGE_FILE, server.config.FREE_DAILY_BUILDS)
        ctx.USAGE_FILE = self.dir / "usage.json"
        server.config.FREE_DAILY_BUILDS = 2

    def tearDown(self):
        ctx.USAGE_FILE, server.config.FREE_DAILY_BUILDS = self._saved

    def test_empty_ledger_allows_and_reports_zero(self):
        allowed, used = server._free_quota_check(CUSTOMER)
        self.assertTrue(allowed)
        self.assertEqual(used, 0)

    def test_quota_blocks_right_after_the_limit(self):
        server._usage_bump(CUSTOMER)
        self.assertTrue(server._free_quota_check(CUSTOMER)[0], "还有额度就被挡了")
        server._usage_bump(CUSTOMER)
        allowed, used = server._free_quota_check(CUSTOMER)
        self.assertFalse(allowed)
        self.assertEqual(used, 2)

    def test_rejected_attempts_do_not_inflate_the_ledger(self):
        """核心回归：判额度是只读的，被拒多少次账本都不该再涨。"""
        server._usage_bump(CUSTOMER)
        server._usage_bump(CUSTOMER)
        for _ in range(10):
            self.assertFalse(server._free_quota_check(CUSTOMER)[0])
        self.assertEqual(server._usage_today(CUSTOMER), 2, "被挡的尝试又记进账本了")
        # 账本文件本身也没被改写（判额度不许落盘）
        self.assertEqual(json.loads(ctx.USAGE_FILE.read_text(encoding="utf-8"))[CUSTOMER][TODAY], 2)

    def test_yesterday_does_not_count_against_today(self):
        ctx.USAGE_FILE.write_text(json.dumps({CUSTOMER: {day(1): 9}}), encoding="utf-8")
        allowed, used = server._free_quota_check(CUSTOMER)
        self.assertTrue(allowed)
        self.assertEqual(used, 0)

    def test_ledger_only_keeps_three_days(self):
        ctx.USAGE_FILE.write_text(json.dumps({CUSTOMER: {day(5): 3, day(2): 1, TODAY: 1}}),
                                    encoding="utf-8")
        server._usage_bump(CUSTOMER)
        kept = json.loads(ctx.USAGE_FILE.read_text(encoding="utf-8"))[CUSTOMER]
        self.assertNotIn(day(5), kept, "5 天前的旧记录没裁掉，账本会一直长大")
        self.assertIn(day(2), kept)

    def test_corrupt_ledger_is_not_treated_as_nobody_used_it(self):
        server._usage_bump(CUSTOMER)
        ctx.USAGE_FILE.write_text('{"quota@":', encoding="utf-8")     # 半截 JSON
        with self.assertRaises(safestore.StoreUnrecoverable):
            server._usage_load()

    def test_unknown_accounts_start_clean(self):
        self.assertEqual(server._usage_today("nobody@example.invalid"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
