"""运维文件不许悄悄消失或悄悄变松（Caddyfile / 部署脚本 / 自检查脚本）。

跑法（在 getcut/ 目录下）：
    python -m unittest tests.test_ops_files -v

这类文件的特点是"平时不干活，出事时才用"，最容易发生的事是：被人顺手改松、
或者线上和仓库两份各说一套。这里不测功能（功能要上机），只钉住几条
"少了一条就说明有人动了它"的硬要求。
"""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # getcut/


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
        self.assertIn("getcut) keep=always", self.s)

    def test_assets_are_never_deleted_on_the_server(self):
        """字体与样片只存在于线上过一次就被删掉过；删除范围必须锁死在 .py。"""
        self.assertIn("grep -E '[.]py$'", self.s)
        self.assertIn("server_static) keep=clean", self.s)

    def test_frontend_bundle_is_verified_before_upload(self):
        """源码更新但 bundle 没重建时必须阻断，不能把旧前端静默发上去。"""
        self.assertIn("build_frontend.sh", self.s)
        self.assertIn("server_static/poc/bundle.js", read("tools/build_frontend.sh"))

    def test_deploy_skips_non_runtime_hash_noise_and_scans_changed_dirs(self):
        """pycache/source map/备份不该拖慢部署，未改资源目录也不必全量扫描。"""
        self.assertIn("__pycache__", self.s)
        self.assertIn("*.map", self.s)
        self.assertIn("*.bak*", self.s)
        self.assertIn("git diff-tree", self.s)

    def test_gate_is_scoped_to_what_actually_ships(self):
        """只改成片台时不必重跑后端 21 个测试模块；判不准的那一侧一律多跑。"""
        self.assertIn("gate_scope.sh", self.s, "门禁又退回无条件全套了")
        self.assertIn("BUILD_INFO.json", self.s,
                      "不读线上版本戳就不知道这次要送哪些文件，闸门也就没法按改动面选")
        self.assertIn("merge-base", self.s, "线上那版不在本分支上时必须退回全套")

    def test_check_mode_does_not_pay_for_a_bundle_build(self):
        """--check 承诺零改动，却要为整包 webpack 付一分半 —— 只准部署模式打这个包。"""
        self.assertIn('if [ "$MODE" = deploy ]; then\n  if ! bash tools/build_frontend.sh', self.s,
                      "--check 又在打 bundle 了")
        self.assertIn("不判「源码与产物漂移」", self.s, "跳过校验必须说出来，不能悄悄跳过")

    def test_check_still_scans_both_code_dirs(self):
        """--check 只扫"这次改过的目录"，就看不见别人 scp 上去却没提交的文件 ——
        而那正是它该抓的东西，所以两处代码目录一律扫。"""
        self.assertIn('for d in renderer/src server_static; do', self.s)


class SelfCheckScriptTest(unittest.TestCase):
    def test_all_three_gates_are_present_and_it_can_fail(self):
        s = read("tools/selfcheck.sh")
        for needle in ("run_backend.sh", "ruff check", "--test tests/frontend.test.cjs"):
            self.assertIn(needle, s, f"自检查脚本少了一条门禁：{needle}")
        self.assertIn("--fail-demo", s, "不会红的闸门等于没在把关")
        self.assertNotIn("pip install", s, "自检查必须只读，不许顺手装包")

    def test_backend_runs_one_process_per_module(self):
        """这些模块都改 import 期全局常量，同进程混跑会偶发假红 —— 分开跑才可信。"""
        s = read("tools/run_backend.sh")
        self.assertIn("for f in tests/test_*.py", s)
        self.assertIn('python -m unittest "$m"', s)

    def test_it_takes_a_gate_list_and_refuses_a_typo(self):
        """--only 写错名字会让"一条都没跑"看起来像"全绿"，所以名单必须当场验。"""
        s = read("tools/selfcheck.sh")
        self.assertIn("--only=frontend,ts", s, "逗号拼多条门禁的用法没了")
        self.assertIn('不认得「$g」', s)
        self.assertIn("没跑的那几条不等于绿", s, "子集跑完要自报没跑哪些，不然会被当成全套")


class GateScopeTest(unittest.TestCase):
    """选闸门这件事本身要真跑着测：选错闸门的后果是"少查了东西"，
    而 grep 脚本内容是看不出来少查了什么的。"""

    def plan(self, *paths: str) -> str:
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("没有 bash，跑不了这个脚本")
        # 字节进出：Windows 上 text=True 会把 \n 翻成 \r\n，脚本收到的就不是这些路径了
        data = "".join(p + "\n" for p in paths).encode("utf-8")
        r = subprocess.run([bash, str(ROOT / "tools" / "gate_scope.sh")],
                           input=data, capture_output=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        return r.stdout.decode("utf-8", "replace").splitlines()[0]

    def test_crlf_manifest_is_still_understood(self):
        """清单会从 Windows 侧管道进来：带着 \\r 就会被判成"认不出来"，白跑全套。"""
        self.assertEqual(self.plan("getcut/renderer/src/tool/ui.css\r"), "frontend,ts")

    def test_compositor_only_skips_the_backend(self):
        self.assertEqual(
            self.plan("getcut/renderer/src/tool/ui.css", "getcut/server_static/poc/bundle.js"),
            "frontend,ts")

    def test_python_only_skips_the_frontend(self):
        self.assertEqual(self.plan("getcut/getcut/server.py"), "backend,ruff")

    def test_both_sides_run_everything(self):
        self.assertEqual(self.plan("getcut/renderer/src/a.tsx", "getcut/getcut/auth.py"),
                         "backend,ruff,frontend,ts")

    def test_ops_and_ci_files_run_everything(self):
        """部署脚本 / CI / 线上配置自己不在任何一条门禁覆盖里 —— 动它们就全套。"""
        for p in ("getcut/tools/deploy_to_prod.sh", ".github/workflows/tests.yml",
                  "getcut/deploy/Caddyfile"):
            self.assertEqual(self.plan(p), "backend,ruff,frontend,ts", p)

    def test_docs_and_assets_run_nothing(self):
        self.assertEqual(self.plan("getcut/README.md", "design-mockups/a.png"), "none")

    def test_missing_manifest_falls_back_to_full(self):
        """拿不到清单（认不出线上是哪一版）必须等于全套，不许当成"没改动"而跳过。"""
        self.assertEqual(self.plan(), "backend,ruff,frontend,ts")


class BackupScriptTest(unittest.TestCase):
    def test_retention_and_verification_stay(self):
        s = read("tools/backup_state.sh")
        self.assertIn("GETCUT_BACKUP_KEEP", s, "保留天数写死了或没了：会攒爆磁盘或悄悄不备")
        self.assertIn("tar tzf", s, "打包后不校验，坏包要到恢复那天才发现")

    def test_big_files_get_mirrored(self):
        """成片（付过钱的交付物，云端没底片）与素材包必须有镜像，且随 run 一起跑。"""
        s = read("tools/backup_state.sh")
        self.assertIn("mirror_big_files", s, "大件镜像没了：成片/素材包又回到零备份")
        self.assertIn("outputs-mirror", s, "成片没进备份")
        self.assertIn("bundles-mirror", s, "素材包没进备份")
        # 成片镜像不许带 --delete：正本被误删后镜像必须还在，删除不能被同步
        run_arm = s.split("mirror_big_files() {", 1)[1]
        self.assertNotIn('rsync -a --delete "$BASE/outputs', run_arm, "成片镜像把删除也同步了")
        # 余量守卫要在：备份不能反过来把盘写爆
        self.assertIn("mirror_guard", s)


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


class TypeCheckGateTest(unittest.TestCase):
    """类型检查不许被"SKIP 当通过"糊过去，也不许把上限抬高。"""

    def test_baseline_is_zero_and_skip_is_loud(self):
        s = read("tools/ts_check.sh")
        self.assertIn('MAX="${GETCUT_TS_MAX_ERRORS:-0}"', s, "基线不再是 0")
        self.assertIn("SKIP 不等于通过", s)

    def test_selfcheck_reports_the_fourth_gate(self):
        s = read("tools/selfcheck.sh")
        self.assertIn("ts_check.sh", s)
        self.assertIn("跳过 前端类型检查", s, "跳过要单独显示，不能混进绿")

    def test_rollback_by_sha_exists(self):
        s = read("tools/rollback_prod.sh")
        self.assertIn("pre-$SHA-", s, "回滚不是按 sha 找备份，还是要人肉挑")
        self.assertIn("code.before-rollback-", s, "回滚前不给当前代码留底")
        self.assertIn("healthz", s, "回滚完不探活")
