"""按域拆路由之后，**注册顺序**和**挂载完整性**必须有人盯着。

跑法（在 videogen/ 目录下）：
    python -m unittest tests.test_route_order

为什么值得单开一个文件：`server.py` 拆成 `videogen/api/*.py` 之后，"哪些路由存在"
和"以什么顺序注册"分居两处 —— 路由在 api 模块里，顺序在 server 的 include_router 里。
FastAPI 按**注册顺序**匹配，于是有两类错是无声的，浏览器上只表现为 404 或串数据：

  1. 顺序错：A 是通配路由（带 {param}），B 是字面路由，A 一旦先注册就会把 B 吃掉；
     或者跨域重排后，某域的通配排到了另一域字面路由前面。
  2. 挂漏：加了一个 api 模块却忘了 include —— 模块里路由写得好好的，一请求就 404。

这两类都不会让任何现有测试变红（它们只测"该通的通"，不测"该通的这个地址
是不是被别人吃了"），所以在这里补一条结构断言。
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # videogen/
PKG = ROOT / "videogen"
APIDIR = PKG / "api"
METHODS = {"get", "post", "put", "delete", "patch"}


def _segs(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def _matches(pattern: str, path: str) -> bool:
    """pattern（可含 {param}）能不能匹配一个**字面** path。"""
    a, b = _segs(pattern), _segs(path)
    i = 0
    for seg in a:
        if seg.startswith("{") and seg.endswith(":path}"):
            return i <= len(b)                # {x:path} 吞掉余下所有段
        if i >= len(b):
            return False
        if seg.startswith("{"):               # {x} 吞掉一段
            i += 1
            continue
        if seg != b[i]:
            return False
        i += 1
    return i == len(b)


def _routes() -> list[tuple[str, str, str, int]]:
    """(模块名, 方法, 路径, 行号)，按文件行号序 —— 同模块内就是真实注册序。"""
    out = []
    for f in sorted(APIDIR.glob("*.py")):
        if f.name == "__init__.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in node.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and d.func.attr in METHODS
                        and isinstance(d.func.value, ast.Name)
                        and d.func.value.id == "router"):
                    p = (d.args[0].value if d.args and isinstance(d.args[0], ast.Constant)
                         else "?")
                    out.append((f.stem, d.func.attr.upper(), p, node.lineno))
                    break
    return out


def _include_order() -> list[str]:
    """server.py 里 include_router 的真实顺序，换成 api 模块名。"""
    src = (PKG / "server.py").read_text(encoding="utf-8")
    # `from .api import (try_api as api_try, brand as api_brand, ...)` -> 别名表
    alias = dict(re.findall(
        r"^\s*(\w+)\s+as\s+(api_\w+)\s*,?\s*$", src, re.M))
    alias = {v: k for k, v in alias.items()}
    return [alias.get(a, a) for a in
            re.findall(r"^app\.include_router\((api_\w+)\.router\)\s*$", src, re.M)]


class IncludeCompletenessTest(unittest.TestCase):
    """写了域模块却没 include —— 路由全在，一请求就 404。"""

    def test_every_api_module_with_routes_is_included(self):
        with_routes = {m for m, _, _, _ in _routes()}
        included = set(_include_order())
        self.assertTrue(with_routes, "api/ 下一条路由都没解析到，本测试的前提坏了")
        self.assertEqual(with_routes, included,
                         "模块与 include 对不上：%s" % sorted(with_routes ^ included))

    def test_include_order_has_no_duplicates_or_strays(self):
        order = _include_order()
        self.assertTrue(order, "server.py 里一条 include_router 都没有")
        self.assertEqual(len(order), len(set(order)), "有域被 include 了两次")


class CrossDomainOrderTest(unittest.TestCase):
    """跨域顺序反转会不会改变匹配结果 —— 拆分唯一真正的行为风险。"""

    def test_reordering_includes_cannot_change_who_wins(self):
        routes = _routes()
        rank = {m: i for i, m in enumerate(_include_order())}
        risky = []
        for i, (m1, meth1, p1, _l1) in enumerate(routes):
            for m2, meth2, p2, _l2 in routes[i + 1:]:
                if meth1 != meth2 or p1 == p2 or m1 == m2:
                    continue
                # 原来 p1 注册在前（rank 更小）却能吃掉 p2；重排后 p1 反而靠后 -> 危险
                if rank[m1] > rank[m2] and _matches(p1, p2):
                    risky.append("[%s] %s 会被 [%s] %s 吃掉" % (m1, p1, m2, p2))
                if rank[m2] > rank[m1] and _matches(p2, p1):
                    risky.append("[%s] %s 会被 [%s] %s 吃掉" % (m2, p2, m1, p1))
        self.assertEqual(risky, [], "顺序一反就改变匹配结果：\n  " + "\n  ".join(risky))


class SameModuleShadowsTest(unittest.TestCase):
    """同模块内：通配注册在字面之前 -> 字面那条永远匹配不上（与顺序无关的坏）。"""

    def test_no_wildcard_is_registered_before_a_literal_it_covers(self):
        routes = _routes()
        bad = []
        for i, (m1, meth1, p1, l1) in enumerate(routes):
            for m2, meth2, p2, l2 in routes[i + 1:]:
                if meth1 == meth2 and m1 == m2 and p1 != p2 and _matches(p1, p2):
                    bad.append("%s: %s(L%d) 先注册，会吃掉 %s(L%d)" % (m1, p1, l1, p2, l2))
        self.assertEqual(bad, [], "通配压在字面前：\n  " + "\n  ".join(bad))


if __name__ == "__main__":
    unittest.main(verbosity=2)
