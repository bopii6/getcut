"""运维文件不许悄悄消失或悄悄变松（Caddyfile / 部署脚本 / 自检查脚本）。

跑法（在 videogen/ 目录下）：
    python -m unittest tests.test_ops_files -v

这类文件的特点是"平时不干活，出事时才用"，最容易发生的事是：被人顺手改松、
或者线上和仓库两份各说一套。这里不测功能（功能要上机），只钉住几条
"少了一条就说明有人动了它"的硬要求。
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # videogen/


def read(rel: str) -> str:
    p = ROOT / rel
    assert p.is_file(), f"{rel} 不在了"
    return p.read_text(encoding="utf-8")


class CaddyfileTest(unittest.TestCase):
    def test_repo_copy_carries_what_production_needs(self):
        s = read("deploy/Caddyfile")
        self.assertIn("acme-v02.api.letsencrypt.org", s, "证书被指回 staging 会发不出可信证书")
        self.assertIn("encode zstd gzip", s, "没这行成片台主包要裸传 3.7MB，首屏白页十秒")
        self.assertIn("reverse_proxy 127.0.0.1:8600", s, "反代目标写错整站 502")
        for host in ("gc.hellojoy.top", "getcut.cn", "hellojoy.top"):
            self.assertIn(host, s, f"少了 {host} 这个入口")

    def test_the_check_script_exists_and_refuses_to_push_blindly(self):
        s = read("tools/caddy_check.sh")
        self.assertIn("caddy validate", s, "不校验语法就 reload，写错一行整站下线")
        self.assertIn("cp -a $REMOTE", s, "覆盖前不留备份")
        self.assertIn("--push", s, "默认必须只比对，装上去要显式说")


class DeployScriptTest(unittest.TestCase):
    def setUp(self):
        self.s = read("tools/deploy_to_prod.sh")

    def test_gates_run_before_anything_ships(self):
        self.assertIn("selfcheck.sh", self.s, "门禁不过也能上线，闸门就白建了")

    def test_ships_committed_content_not_working_tree(self):
        """工作树里可能混着别的会话未提交的改动，顺手上线迟早出事。"""
        self.assertIn("git archive", self.s)
        self.assertNotIn("git add -A", self.s)

    def test_compares_hashes_not_sizes(self):
        """换色值长度一样，只比字节数会漏传（2026-09-21 真踩过：线上静默留旧产物）。"""
        self.assertIn("md5sum", self.s)
        self.assertNotIn("-printf '%P %s", self.s, "退回了只比字节数的写法")

    def test_verifies_after_sending(self):
        """传完必须回读校验：否则"上线了"只是愿望。"""
        self.assertIn("校验失败", self.s)
        self.assertIn("已校验一致", self.s)

    def test_backs_up_and_rolls_back(self):
        self.assertIn("cp -a $BASE/code", self.s, "改前不备份，出问题只能干瞪眼")
        self.assertIn("探活失败，回滚", self.s)

    def test_code_dir_is_shipped_whole(self):
        """代码目录才 0.4MB：整包发 + 校验，不给行尾差异之类的误判留空间。"""
        self.assertIn("videogen) keep=always", self.s)

    def test_assets_are_never_deleted_on_the_server(self):
        """字体与样片只存在于线上过一次就被删掉过；删除范围必须锁死在 .py。"""
        self.assertIn("grep -E '[.]py$'", self.s)
        self.assertIn("server_static) keep=clean", self.s)


class SelfCheckScriptTest(unittest.TestCase):
    def test_all_three_gates_are_present_and_it_can_fail(self):
        s = read("tools/selfcheck.sh")
        for needle in ("unittest discover -s tests", "ruff check", "--test tests/frontend.test.cjs"):
            self.assertIn(needle, s, f"自检查脚本少了一条门禁：{needle}")
        self.assertIn("--fail-demo", s, "不会红的闸门等于没在把关")
        self.assertNotIn("pip install", s, "自检查必须只读，不许顺手装包")


class BackupScriptTest(unittest.TestCase):
    def test_retention_and_verification_stay(self):
        s = read("tools/backup_state.sh")
        self.assertIn("VIDEOGEN_BACKUP_KEEP", s, "保留天数写死了或没了：会攒爆磁盘或悄悄不备")
        self.assertIn("tar tzf", s, "打包后不校验，坏包要到恢复那天才发现")


if __name__ == "__main__":
    unittest.main(verbosity=2)

class NormalizationTest(unittest.TestCase):
    """归一那行断过一次：转义把 \r 吃成换行，CRLF 一直没剥掉，比对全是假差异。"""

    def test_text_files_really_get_normalized_to_lf(self):
        s = read("tools/deploy_to_prod.sh")
        r = chr(92) + "r"
        self.assertIn("sed -i 's/" + r + "$//'", s, "归一命令不见了或被写坏")
        self.assertNotIn(r + "n  -o", s, "find 条件里混进了字面 \n，这条 find 已经不成立")

    def test_check_and_ship_share_one_ruler(self):
        """--check 与上传必须同一套判据，否则"检查说一致、上线却漏传"会回来。"""
        s = read("tools/deploy_to_prod.sh")
        self.assertNotIn("-printf '%P %s", s, "报告还在比字节数：换等长色值会被判成没变")
        self.assertIn("md5sum", s)

