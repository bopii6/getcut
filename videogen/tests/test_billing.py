"""卡密与档位（营收账本）的离线闸门：账号表与卡密表全部落在临时目录。

跑法（在 videogen/ 目录下）：
    python -m unittest discover -s tests -t tests

这一环翻过一次车（账号收费），所以把 licenses.py 文件头承诺的规矩逐条钉住，
最要紧的是**发错码不能白亏一张**：只有真升到档了才允许把卡密标记成已使用。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="videogen-bill-")
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

from videogen import auth, licenses, safestore  # noqa: E402

CUSTOMER = "buyer@example.invalid"
PASSWORD = "Qz7-Yb3Kd9Nm4Rt8Wx2L"
CONFUSABLE = set("0O1I5S")


class LicenseTest(unittest.TestCase):
    def setUp(self):
        # 每个用例一套独立的账号表/卡密表：不依赖模块 import 顺序，也不碰工作区正本。
        self.dir = Path(tempfile.mkdtemp(prefix="videogen-bill-case-"))
        self._saved = [(auth, "USERS_FILE", auth.USERS_FILE),
                       (auth, "SECRET_FILE", auth.SECRET_FILE),
                       (licenses, "_CODE_FILE", licenses._CODE_FILE)]
        auth.USERS_FILE = self.dir / "users.json"
        auth.SECRET_FILE = self.dir / "auth-secret"
        licenses._CODE_FILE = self.dir / "licenses.json"
        self.assertFalse(auth.has_users(), "改指临时账号表没生效，用例会互相污染")
        auth.create_user(CUSTOMER, PASSWORD, role="user")

    def tearDown(self):
        for module, name, value in self._saved:
            setattr(module, name, value)

    def redeem(self, code, email=CUSTOMER):
        ok, msg, tier = licenses.redeem(email, code)
        return ok, msg, tier, auth.user_tier(email)

    # ---------- 只升不降 ----------
    def test_free_account_upgrades_with_basic_code(self):
        code = licenses.generate("basic", 1)[0]
        ok, msg, tier = self.redeem(code)[:3]
        self.assertTrue(ok, msg)
        self.assertEqual(tier, "basic")
        self.assertIn("激活成功", msg)

    def test_basic_account_upgrades_with_premium_code(self):
        auth.set_tier(CUSTOMER, "basic")
        code = licenses.generate("premium", 1)[0]
        ok, _, tier = self.redeem(code)[:3]
        self.assertTrue(ok)
        self.assertEqual(tier, "premium", "基础版兑高级码要真的升上去")

    def test_premium_redeeming_basic_is_refused_without_burning_the_code(self):
        """直播间发错码不能白亏一张：拒绝的同时这张码必须还能给别人用。"""
        auth.set_tier(CUSTOMER, "premium")
        code = licenses.generate("basic", 1)[0]
        ok, msg, _, now = self.redeem(code)
        self.assertFalse(ok)
        self.assertEqual(now, "premium", "拒绝还顺手降了档")
        self.assertEqual(licenses.stats()["basic"]["used"], 0, "没成功却把码消耗掉了")
        auth.create_user("second@example.invalid", PASSWORD, role="user")
        ok2 = licenses.redeem("second@example.invalid", code)[0]
        self.assertTrue(ok2, "被拒的码应当仍可兑换")

    def test_same_tier_code_is_refused_without_burning_it(self):
        auth.set_tier(CUSTOMER, "basic")
        code = licenses.generate("basic", 1)[0]
        ok, msg, _, _ = self.redeem(code)
        self.assertFalse(ok)
        self.assertIn("别浪费", msg)
        self.assertEqual(licenses.stats()["basic"]["used"], 0)

    def test_used_code_cannot_be_redeemed_a_second_time(self):
        code = licenses.generate("premium", 1)[0]
        self.assertTrue(licenses.redeem(CUSTOMER, code)[0])
        auth.create_user("thief@example.invalid", PASSWORD, role="user")
        ok, msg, _, now = self.redeem(code, "thief@example.invalid")
        self.assertFalse(ok, "一张码不能兑换两次")
        self.assertIn("已被使用", msg)
        self.assertEqual(now, "free")

    # ---------- 手抄友好 ----------
    def test_code_is_case_insensitive_and_dash_optional(self):
        code = licenses.generate("premium", 1)[0]
        ok, _, tier = self.redeem(code.lower().replace("-", " "))[:3]
        self.assertTrue(ok, "微信里手抄，大小写和连字符不该影响兑换")
        self.assertEqual(tier, "premium")

    def test_generated_codes_contain_no_confusable_glyphs(self):
        codes = licenses.generate("premium", 200) + licenses.generate("basic", 200)
        self.assertEqual(len(set(codes)), 400, "卡密撞码")
        for c in codes:
            self.assertTrue(re.fullmatch(r"GC[BP]-[A-Z0-9]{4}-[A-Z0-9]{4}", c), c)
            self.assertFalse(CONFUSABLE & set(c[4:]), "%s 里有容易认错的字符" % c)

    def test_prefix_matches_tier(self):
        self.assertTrue(licenses.generate("basic", 1)[0].startswith("GCB"))
        self.assertTrue(licenses.generate("premium", 1)[0].startswith("GCP"))

    # ---------- 说人话的失败提示 ----------
    def test_unknown_code_says_so(self):
        ok, msg, _, now = self.redeem("GCP-ABCD-EFGH")
        self.assertFalse(ok)
        self.assertIn("没有这张卡密", msg)
        self.assertEqual(now, "free")

    def test_malformed_code_says_so(self):
        ok, msg, _, _ = self.redeem("GCP-12")
        self.assertFalse(ok)
        self.assertIn("格式不对", msg)

    def test_generate_rejects_unknown_tier_and_caps_count(self):
        with self.assertRaises(ValueError):
            licenses.generate("diamond", 1)
        self.assertEqual(len(licenses.generate("basic", 9999)), 200, "一次生成要有上限，别把账本撑爆")

    # ---------- 对账与展示 ----------
    def test_stats_tracks_actual_redemptions(self):
        b1, b2 = licenses.generate("basic", 2)
        p1 = licenses.generate("premium", 1)[0]
        licenses.redeem(CUSTOMER, b1)
        auth.create_user("other@example.invalid", PASSWORD, role="user")
        licenses.redeem("other@example.invalid", p1)
        st = licenses.stats()
        self.assertEqual(st["basic"], {"total": 2, "used": 1})
        self.assertEqual(st["premium"], {"total": 1, "used": 1})

    def test_admin_list_masks_the_code(self):
        code = licenses.generate("premium", 1)[0]
        row = licenses.list_codes()[0]
        self.assertEqual(row["code"], code[:7] + "…", "后台列表要脱敏，截图发群里不泄露整码")
        self.assertNotIn(code[7:], row["code"])

    def test_corrupt_license_book_refuses_to_look_empty(self):
        """账本坏了不能当"没有这张码"：那会让真码被判定无效，客户当场炸锅。"""
        licenses.generate("premium", 1)
        licenses._CODE_FILE.write_text('{"codes": [', encoding="utf-8")
        with self.assertRaises(safestore.StoreUnrecoverable):
            licenses.redeem(CUSTOMER, "GCP-ABCD-EFGH")

    def test_money_path_writes_atomically(self):
        codes = licenses.generate("premium", 3)
        raw = json.loads(licenses._CODE_FILE.read_text(encoding="utf-8"))
        self.assertEqual(len(raw["codes"]), 3)
        self.assertEqual(list(self.dir.glob(".licenses.json.tmp-*")), [], "留下半截临时文件")
        self.assertTrue(codes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
