"""依赖锁定策略自身的闸门（防"过两个月又有人把 == 改回 >="）。

跑法（在 videogen/ 目录下）：
    python -m unittest discover -s tests -t tests

为什么值得锁：`>=` 的清单等于"每次重建镜像重新赌一次上游"，而线上真栽过一次
（COS SDK 方法名对不上）。这类回退没有任何功能测试会红，所以单独钉一条。
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([A-Za-z0-9.*+!_-]+)$")


def lines(path: Path) -> list[str]:
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")]


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


class DependencyPolicyTest(unittest.TestCase):
    def test_requirements_txt_is_fully_pinned(self):
        for line in lines(ROOT / "requirements.txt"):
            with self.subTest(req=line):
                self.assertRegex(line, r"^[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9.*+!_-]+$",
                                 "直接依赖必须是 ==（用 >= 等于每次重建镜像赌一次上游）")

    def test_lock_is_fully_pinned(self):
        rows = [NAME_RE.match(l) for l in lines(ROOT / "requirements.lock")]
        self.assertTrue(all(rows), "锁定表里有一行不是 包==版本")
        self.assertGreaterEqual(len(rows), 20, "锁定表只剩这点，传递依赖丢了")

    def test_every_direct_dep_appears_in_the_lock(self):
        locked = {norm(NAME_RE.match(l).group(1)) for l in lines(ROOT / "requirements.lock")}
        for line in lines(ROOT / "requirements.txt"):
            name = norm(line.split("==")[0])
            self.assertIn(name, locked, "%s 在锁定表里没有对应版本" % name)

    def test_dockerfile_installs_from_the_lock(self):
        docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("pip install -r requirements.lock", docker,
                      "镜像构建装的不是锁定表，锁了等于没锁")
        self.assertNotIn("pip install -r requirements.txt\n", docker)
        self.assertIn("requirements.lock", docker.split("COPY requirements.txt")[1][:80],
                      "没把 requirements.lock COPY 进镜像，pip 会找不到文件")

    def test_build_entry_is_named_in_npm_scripts(self):
        """成片台的打包入口以前是散落的 `node _tool_bundle.mjs`，靠记忆；
        现在镜像必须走 npm script，改名/挪文件会被这条挡住。"""
        pkg = json.loads((ROOT / "renderer" / "package.json").read_text(encoding="utf-8"))
        self.assertIn("build:tool", pkg.get("scripts", {}),
                      "renderer/package.json 没有 build:tool 脚本")
        docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("npm run build:tool", docker, "镜像还在直接跑散脚本，没走 npm script")
        self.assertNotIn("RUN node _tool_bundle.mjs", docker)

    def test_requirement_files_declare_utf8(self):
        """带中文注释的 requirements 文件必须写编码声明。
        没写的话，pip 自带的解析器在非 UTF-8 区域设置（Windows 中文环境是 cp936）下
        会把整个文件读崩 —— 实测 `pip-audit -r requirements.lock` 就是这么挂的。"""
        for name in ("requirements.txt", "requirements.lock"):
            with self.subTest(name=name):
                head = ROOT.joinpath(name).read_text(encoding="utf-8").splitlines()[0]
                self.assertEqual(head, "# -*- coding: utf-8 -*-",
                                 "%s 缺编码声明，Windows 上的工具链读不了它" % name)

    def test_ci_installs_from_the_lock(self):
        wf = (ROOT.parent / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertIn("pip install -r requirements.lock", wf)
        self.assertIn("pip check", wf, "CI 不查依赖一致性")


if __name__ == "__main__":
    unittest.main(verbosity=2)
