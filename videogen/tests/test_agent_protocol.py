"""成片台（客户浏览器）↔ 服务端协议字段的离线契约闸门。

跑法（在 videogen/ 目录下）：
    python -m unittest discover -s tests -t tests

为什么值得锁：两端靠**裸字符串**对齐 —— 浏览器发 `x-agent-final: 1`、`?final=1`，
服务端 `request.headers.get("x-agent-final") == "1"` 才认。任何一边改名或漏传都不报错，
只会让成片悄悄退化成"没有声音的一版"或卡在进度条。评估认到的三处翻车之一就是这里。

这里不动两端源码（共享常量文件要改渲染器，那是另一件事），只把"浏览器发出的每个字段
服务端确实在读"钉成断言：**任何一侧单独改名，CI 立刻红。**
"""
from __future__ import annotations

import inspect
import re
import unittest
from pathlib import Path

from videogen import server

RENDERER_DIR = Path(__file__).resolve().parent.parent / "renderer" / "src" / "tool"
AGENT_PATHS = ("/api/agent", "/agent-media/")
HEADER_OBJ_RE = re.compile(r"headers\s*:\s*\{([^}]*)\}", re.S)
HEADER_KEY_RE = re.compile(r"['\"]([A-Za-z0-9_-]+)['\"]\s*:")
QUERY_KEY_RE = re.compile(r"[?&]([A-Za-z_][A-Za-z0-9_]*)=")
FETCH_RE = re.compile(r"fetch\(\s*[`'\"]([^`'\"]*)[`'\"]", re.S)
# 传输层标配头，不属于两端协议约定（FastAPI 自己按 content-type 解 body）
TRANSPORT_HEADERS = {"content-type", "accept", "accept-encoding", "connection", "cookie"}


def _segments(path: str) -> list[str]:
    """`${cur.job}` 与 `{job_id}` 都归一成一个通配段。"""
    return [re.sub(r"^(\{[^}]*\}|\$\{[^}]*\})$", "*", s) for s in path.split("?")[0].split("/")]


def _same(a: list[str], b: list[str]) -> bool:
    return len(a) == len(b) and all(x == y or x == "*" or y == "*" for x, y in zip(a, b, strict=True))


def server_routes() -> dict[str, tuple[set[str], set[str]]]:
    """path → (服务端会读的 query 键, 会读的 header 键)。"""
    out = {}
    for r in server.app.routes:
        path = getattr(r, "path", "")
        if not path.startswith(AGENT_PATHS):
            continue
        dep = getattr(r, "dependant", None)
        q = {p.name for p in (dep.query_params if dep else [])}
        h = {p.name.lower() for p in (dep.header_params if dep else [])}
        src = inspect.getsource(r.endpoint)
        q |= set(re.findall(r"""query_params\.get\(\s*['"]([^'"]+)""", src))
        h |= {k.lower() for k in re.findall(r"""headers\.get\(\s*['"]([^'"]+)""", src)}
        out[path] = (q, h)
    return out


def client_calls() -> list[tuple[list[str], set[str], set[str], str]]:
    """渲染器源码里的每一个成片台请求：(路径段, query 键, header 键, 原文)。"""
    calls = []
    for tsx in sorted(RENDERER_DIR.glob("*.tsx")):
        src = tsx.read_text(encoding="utf-8")
        for m in FETCH_RE.finditer(src):
            raw = m.group(1)
            if not raw.startswith(AGENT_PATHS):
                continue
            tail = src[m.end():m.end() + 400]
            hdr = HEADER_OBJ_RE.search(tail)
            calls.append((
                _segments(raw),
                set(QUERY_KEY_RE.findall(raw)),
                {k.lower() for k in HEADER_KEY_RE.findall(hdr.group(1))} - TRANSPORT_HEADERS if hdr else set(),
                raw,
            ))
    return calls


class AgentProtocolContractTest(unittest.TestCase):
    def setUp(self):
        self.routes = server_routes()
        self.calls = client_calls()

    def match(self, segs):
        for path in self.routes:
            if _same(segs, _segments(path)):
                return path
        return None

    def test_renderer_does_call_the_agent_api(self):
        self.assertTrue(self.calls, "渲染器里一个成片台请求都没扫到：目录或写法变了，这套闸门已经失效")
        self.assertGreaterEqual(len(self.routes), 5, "服务端成片台接口少于 5 个，归属校验覆盖面要重查")

    def test_every_query_key_the_browser_sends_is_still_read(self):
        for segs, keys, _, raw in self.calls:
            with self.subTest(call=raw[:72]):
                path = self.match(segs)
                self.assertIsNotNone(path, "服务端没有这个成片台接口：%s" % "/".join(segs))
                accepted, _ = self.routes[path]
                self.assertFalse(keys - accepted,
                                 "浏览器还在发 %s，%s 已经不读它了（字段名对不上＝静默降级）"
                                 % (sorted(keys - accepted), path))

    def test_every_header_the_browser_sends_is_still_read(self):
        for segs, _, hs, raw in self.calls:
            with self.subTest(call=raw[:72]):
                path = self.match(segs)
                self.assertIsNotNone(path)
                _, accepted = self.routes[path]
                self.assertFalse(hs - accepted,
                                 "浏览器还在发 %s，服务端没人读（声轨声明就是这样丢的）" % sorted(hs - accepted))

    def test_no_agent_call_is_unmatched(self):
        """反向：渲染器不许打到一个服务端不存在的成片台地址（404 在浏览器里只是 console 一行红）。"""
        for segs, _, _, raw in self.calls:
            with self.subTest(call=raw[:72]):
                self.assertIsNotNone(self.match(segs))

    def test_final_capability_sentinel_matches_on_both_sides(self):
        """`x-agent-final: 1` / `?final=1` 是"浏览器能自己混音出完整 mp4"的声明。

        值一改（或改成 true），只要一边没跟上，服务端就当对面是老客户端、按"只有画面"处理，
        客户拿到的是一条没声的片 —— 所以两边的字面值必须仍是 1。
        """
        browser_says = [raw for _, _, _, raw in self.calls
                        if "final=1" in raw or "x-agent-final" in raw]
        self.assertTrue(browser_says, "浏览器端不再声明 final 能力，服务端那条分支就是死代码")
        src = inspect.getsource(server)
        self.assertRegex(src, r"""['"]x-agent-final['"]""", "服务端不再读 x-agent-final 头")
        self.assertRegex(src, r"""final['"]?\)?\s*(==\s*['"]1['"]|=\s*['"]?1)""",
                         "服务端 final 的哨兵值不再是 1，要同步改浏览器端")


if __name__ == "__main__":
    unittest.main(verbosity=2)
