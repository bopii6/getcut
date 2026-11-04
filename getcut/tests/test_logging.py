# -*- coding: utf-8 -*-
"""结构化日志闸门：JSON 形状、请求 ID 贯通、秘钥不落盘、print 收敛。

跑法（在 getcut/ 目录下）：
    python -m unittest tests.test_logging -v

为什么这些要钉死：
    日志是出事后唯一还查得动的东西，而它坏起来是**无声**的 —— 不报错，只是变成
    没用：不是 JSON 了、rid 断了、query 里的 token 被写进磁盘了。没有闸门的话，
    第一次发现"日志查不动"的那天，恰恰就是最需要查日志的那天。
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import re
import tempfile
import unittest
from pathlib import Path

# config.py 在 import 时就读环境变量定下所有路径，所以必须先设环境、再 import 业务模块。
_TMP = tempfile.mkdtemp(prefix="getcut-log-")
os.environ.update({
    "GETCUT_WORKSPACE": _TMP,
    "GETCUT_USERS_FILE": str(Path(_TMP) / "users.json"),
    "GETCUT_LICENSES_FILE": str(Path(_TMP) / "licenses.json"),
    "GETCUT_USAGE_FILE": str(Path(_TMP) / "usage.json"),
    "GETCUT_AUTH_SECRET": str(Path(_TMP) / "auth-secret"),
    "GETCUT_BRAND_DIR": str(Path(_TMP) / "brand"),
    "GETCUT_JOBS_FILE": str(Path(_TMP) / "jobs.json"),
    "GETCUT_REGISTRY_FILE": str(Path(_TMP) / "registry.json"),
    "GETCUT_ACCESS_TOKEN": "",            # 不启用全局令牌：只认账号会话
    "EMAIL_SMTP_HOST": "",
    # 级别由本文件的 capture() 控制（会把 getcut 调到 DEBUG），别让环境变量插一手
    "GETCUT_LOG_LEVEL": "",
})

from starlette.testclient import TestClient  # noqa: E402

from getcut import logx, server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent      # getcut/
PKG = ROOT / "getcut"

PROBE_PATH = "/log-rid-probe"
BOOM_PATH = "/log-boom-probe"


def read(rel: str) -> str:
    p = ROOT / rel
    assert p.is_file(), f"{rel} 不在了"
    return p.read_text(encoding="utf-8")


def _server_src() -> str:
    return read("getcut/server.py")


def _recs(lines, msg=None):
    """把 capture 收到的行解析成 dict；msg 给了就只留该消息的那几条。"""
    out = []
    for s in lines:
        try:
            d = json.loads(s)
        except ValueError:
            continue
        if msg is None or d.get("msg") == msg:
            out.append(d)
    return out


@contextlib.contextmanager
def _temp_route(path: str, endpoint):
    """临时挂一个探针路由并放行，退出时必须还原。

    放行 = 临时塞进 _PUBLIC_PATHS，否则 _auth_gate 先给个 401，探针根本跑不到；
    还原 = 按 path 从 routes 里摘掉（add_api_route 返回 None，拿不到路由对象）。
    漏了还原就是给后续用例乃至整个进程留一个匿名可达的口子。
    """
    server._PUBLIC_PATHS.add(path)
    server.app.add_api_route(path, endpoint, methods=["GET"])
    try:
        yield
    finally:
        server.app.routes[:] = [r for r in server.app.routes
                                if getattr(r, "path", None) != path]
        server._PUBLIC_PATHS.discard(path)


class _LogCase(unittest.TestCase):
    """每个用例单独收日志，并保证不把 handler / 级别状态漏给下一个用例。"""

    def setUp(self):
        self.h, self.lines = logx.capture()
        self.client = TestClient(server.app, base_url="http://log.test")

    def tearDown(self):
        logx.release(self.h)
        # configure() 动过的 root 必须收回去：留着的话后面的用例会看到别人的
        # 输出，甚至同一条日志被打两遍（而日志翻倍没人会去查）。
        root = logging.getLogger()
        for h in [x for x in root.handlers if getattr(x, "_getcut_json", False)]:
            root.removeHandler(h)
        root.setLevel(logging.WARNING)


class JsonShapeTest(_LogCase):
    def test_access_log_is_one_json_object_with_the_fixed_keys(self):
        r = self.client.get("/api/auth/status")
        self.assertEqual(r.status_code, 200)
        acc = _recs(self.lines, "access")
        self.assertTrue(acc, "没产出访问日志 —— 退回人肉翻 docker logs 了")
        rec = acc[0]
        for key in ("ts", "level", "logger", "msg"):
            self.assertIn(key, rec, f"固定键 {key} 不在")
        self.assertEqual(rec["logger"], "getcut.server")
        # 一行一个 JSON 对象：`docker logs | jq 'select(.level=="ERROR")'` 才直接可用
        self.assertTrue(all(s.startswith("{") and s.endswith("}") for s in self.lines))

    def test_timestamp_is_rfc3339_with_millis_and_offset(self):
        """要能直接读、也能跨机器排序：少了时区尾巴，跨机对时序就没法做。"""
        self.client.get("/api/auth/status")
        acc = _recs(self.lines, "access")
        self.assertTrue(acc)
        self.assertRegex(
            acc[0]["ts"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}$")

    def test_extra_fields_are_flattened_into_the_same_line(self):
        server.log.info("extra demo", extra={"job": "j-42", "count": 7})
        recs = _recs(self.lines, "extra demo")
        self.assertTrue(recs, "extra 没进 JSON")
        self.assertEqual(recs[0]["job"], "j-42")
        self.assertEqual(recs[0]["count"], 7)
        # LogRecord 自带的属性不许被摊平进来（否则每行都拖着 pathname/lineno 一坨）
        for noise in ("pathname", "filename", "lineno", "funcName", "process"):
            self.assertNotIn(noise, recs[0])

    def test_third_party_formatter_template_is_dropped(self):
        """uvicorn 用 `extra={"color_message": ...}` 给**它自己的**着色 formatter
        递模板：值里还是没替换的 %d 加 ANSI 色码。摊进我们的 JSON 就是同一句话出现
        两遍、其中一遍是坏的 —— 读日志的人会以为消息里真有个 %d。
        """
        server.log.info("tmpl demo %s", "x",
                        extra={"color_message": "tmpl demo \x1b[36m%x\x1b[0m"})
        recs = _recs(self.lines, "tmpl demo x")
        self.assertTrue(recs, "日志没出来")
        self.assertNotIn("color_message", recs[0], "别家 formatter 的模板混进来了")
        self.assertNotIn("\x1b", json.dumps(recs[0]), "ANSI 色码进了 JSON")

    def test_traceback_lands_in_exc_not_in_the_message(self):
        """只打 str(e) 的老写法把真因丢了 —— 这正是 print 最要命的地方。"""
        try:
            raise ValueError("底层真因")
        except ValueError as exc:
            server.log.error("boom demo", exc_info=exc)
        recs = _recs(self.lines, "boom demo")
        self.assertTrue(recs)
        self.assertIn("ValueError", recs[0].get("exc", ""))
        self.assertIn("底层真因", recs[0].get("exc", ""))
        self.assertEqual(recs[0]["msg"], "boom demo", "整段栈混进 msg 就没法按消息过滤了")


class RequestIdTest(_LogCase):
    def test_response_carries_request_id_and_the_log_matches_it(self):
        r = self.client.get("/api/auth/status")
        rid = r.headers.get("x-request-id")
        self.assertTrue(rid, "响应没回 x-request-id，请求与日志就串不起来")
        acc = _recs(self.lines, "access")
        self.assertTrue(acc)
        self.assertEqual(acc[0].get("rid"), rid)

    def test_upstream_request_id_is_honored(self):
        """上游（Caddy/网关）发来的合法 rid 要沿用 —— 自己另发一个就两份日志对不上。"""
        gw = "caddy-Abc_123-xy"
        r = self.client.get("/api/auth/status", headers={"x-request-id": gw})
        self.assertEqual(r.headers.get("x-request-id"), gw)
        acc = _recs(self.lines, "access")
        self.assertEqual(acc[0].get("rid"), gw)

    def test_illegal_upstream_request_id_is_replaced(self):
        # 只能用 ASCII 里的非法值：httpx 发头就只认 ASCII，中文在客户端就先炸，
        # 走不到服务端的校验。
        bad = "bad rid; drop table"
        r = self.client.get("/api/auth/status", headers={"x-request-id": bad})
        got = r.headers.get("x-request-id", "")
        self.assertNotEqual(got, bad, "非法 rid 被原样回写进响应头了")
        self.assertRegex(got, r"^[A-Za-z0-9_-]{1,64}$")

    def test_crlf_in_request_id_cannot_be_injected(self):
        """CRLF 只能直接喂 _request_id（httpx 拒发含控制字符的头值）。

        这个值会回写进 x-request-id 响应头并落进日志；`$` 会放过**尾部换行**，
        所以正则必须 fullmatch —— 放行就等于开一个响应头/日志文件的注入洞。
        """
        class _FakeReq:
            def __init__(self, rid: str) -> None:
                self.headers = {"x-request-id": rid}

        for evil in ("abc\r\nSet-Cookie: pwned=1", "abc\n", "a" * 65):
            with self.subTest(evil=evil[:20]):
                got = server._request_id(_FakeReq(evil))
                self.assertNotIn("\r", got)
                self.assertNotIn("\n", got)
                self.assertRegex(got, r"^[A-Za-z0-9_-]{1,64}$")

    def test_rid_reaches_a_sync_endpoint_running_in_a_threadpool(self):
        """这是整个方案的命门：同步端点跑在线程池里，contextvar 要是没被复制过去，
        rid 就只覆盖中间件自己那一行，端点内部的日志全部对不上号 —— 等于白做。
        """
        seen = {}

        def probe():
            seen["rid"] = logx.RID.get()
            server.log.warning("probe inside handler")
            return {"ok": True}

        with _temp_route(PROBE_PATH, probe):
            r = self.client.get(PROBE_PATH)

        self.assertEqual(r.status_code, 200, "探针路由没被放行，这条断言无效")
        rid = r.headers.get("x-request-id")
        self.assertTrue(seen.get("rid"), "同步端点里读不到 rid —— contextvar 没穿进线程池")
        self.assertEqual(seen["rid"], rid, "端点里看到的 rid 和响应头不是同一个")
        probes = _recs(self.lines, "probe inside handler")
        self.assertTrue(probes, "端点里那条日志没被收到")
        self.assertEqual(probes[0].get("rid"), rid)

    def test_each_request_gets_its_own_rid(self):
        """带 rid 发一次，再裸发一次：第二次不许顶着上一次的号。

        真正防的是"有人把 rid 提成模块级变量复用" —— 那会让两条无关请求
        在日志里长成同一条，比没有 rid 更糟。
        """
        self.client.get("/api/auth/status", headers={"x-request-id": "first-1"})
        self.lines.clear()
        self.client.get("/api/auth/status")
        acc = _recs(self.lines, "access")
        self.assertTrue(acc)
        self.assertNotEqual(acc[0].get("rid"), "first-1",
                            "第二次请求顶着上一次的 rid —— 号被复用了")


class SecretRedactionTest(_LogCase):
    SECRET = "SUPERSECRET-MASTER-TOKEN-9f2a"

    def test_query_string_never_reaches_the_log(self):
        """本站有 ?token= 这条带主钥匙的通道；query 进日志 = 钥匙写到磁盘上。"""
        r = self.client.get("/healthz", params={"token": self.SECRET})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(self.SECRET, "\n".join(self.lines),
                         "query 串进了日志 —— 访问令牌被落盘了")
        acc = _recs(self.lines, "access")
        self.assertTrue(acc, "healthz 没留访问日志")
        self.assertEqual(acc[0].get("path"), "/healthz", "只该记 path，不该带 query")
        self.assertNotIn("token", json.dumps(acc[0], ensure_ascii=False))

    def test_healthz_success_is_logged_at_debug(self):
        """容器 HEALTHCHECK 每 30 秒一次，一天 2880 行 —— 按 INFO 记会把
        `docker logs --tail` 淹掉，所以成功降 DEBUG；但探活开始失败是正经告警。
        """
        self.client.get("/healthz")
        acc = _recs(self.lines, "access")
        self.assertTrue(acc, "healthz 成功没记？")
        self.assertEqual(acc[0].get("level"), "DEBUG")


class AccessLevelTest(_LogCase):
    def test_success_is_logged_at_info(self):
        r = self.client.get("/api/auth/status")
        self.assertEqual(r.status_code, 200)
        acc = _recs(self.lines, "access")
        self.assertEqual(acc[0].get("level"), "INFO")
        self.assertEqual(acc[0].get("method"), "GET")
        self.assertEqual(acc[0].get("status"), 200)
        self.assertIsInstance(acc[0].get("ms"), (int, float), "耗时没记，慢查询查不出来")

    def test_401_is_logged_above_info_so_it_can_be_sifted_out(self):
        """401 要留痕：查不到"谁在什么时候撞了门"，访问日志就只剩成功请求。"""
        r = self.client.get("/api/me")
        self.assertEqual(r.status_code, 401, "这条断言依赖匿名 401")
        acc = _recs(self.lines, "access")
        self.assertTrue(acc, "401 没留痕 —— 中间件没在最外层？")
        self.assertEqual(acc[0].get("status"), 401)
        self.assertEqual(acc[0].get("level"), "WARNING")

    def test_unhandled_exception_leaves_a_traceback_and_a_500_line(self):
        def boom():
            raise RuntimeError("kaboom")

        with _temp_route(BOOM_PATH, boom):
            with self.assertRaises(RuntimeError):
                self.client.get(BOOM_PATH, headers={"x-request-id": "rid-of-the-crash"})

        fails = _recs(self.lines, "request failed")
        self.assertTrue(fails, "异常没留 traceback —— 又退回 print(str(e)) 了")
        exc = fails[0].get("exc", "")
        self.assertIn("RuntimeError", exc)
        self.assertIn("kaboom", exc)
        self.assertEqual(fails[0].get("rid"), "rid-of-the-crash")
        acc = _recs(self.lines, "access")
        self.assertTrue(acc)
        self.assertEqual(acc[0].get("status"), 500, "崩了还记 499/200 就查不出事故")
        self.assertEqual(acc[0].get("level"), "ERROR")


class MiddlewareWiringTest(unittest.TestCase):
    def test_access_log_is_the_outermost_middleware(self):
        """只有最外层才看得到 401 / 400 / 404；塞在鉴权里面就只记成功请求。
        Starlette 里**最后注册**的排最外（add_middleware 是 insert(0)）。
        """
        names = [getattr(m.kwargs.get("dispatch"), "__name__", "?")
                 for m in server.app.user_middleware
                 if m.cls.__name__ == "BaseHTTPMiddleware"]
        self.assertIn("_access_log", names, "访问日志中间件没了")
        self.assertEqual(names[0], "_access_log",
                         f"访问日志不在最外层（顺序 {names}），401/400/404 会漏记")

    def test_rid_contextvar_is_set_and_reset_in_the_access_log(self):
        """用 AST 而不是字符串找：忘 reset 的话，后台线程（渲染灶台、清扫线程）
        会顶着上一次请求的 rid 记日志 —— 那比没有 rid 还糟，是**错的**关联。

        字符串断言会被 `pass  # logx.RID.reset(token)` 这种"注释掉但字还在"
        骗过去，AST 只认真正的调用节点。
        """
        import ast
        tree = ast.parse(_server_src())
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == "_access_log"), None)
        self.assertIsNotNone(fn, "_access_log 中间件不在了")

        def calls_rid(method: str) -> bool:
            """认 `logx.RID.<method>(...)` 这条完整调用链，别认半截。"""
            for c in ast.walk(fn):
                if not isinstance(c, ast.Call):
                    continue
                f = c.func
                if not (isinstance(f, ast.Attribute) and f.attr == method):
                    continue
                inner = f.value                       # 期望是 logx.RID
                if (isinstance(inner, ast.Attribute) and inner.attr == "RID"
                        and isinstance(inner.value, ast.Name)
                        and inner.value.id == "logx"):
                    return True
            return False

        self.assertTrue(calls_rid("set"), "_access_log 没把 rid 放进 contextvar")
        self.assertTrue(calls_rid("reset"), "_access_log 忘了 reset —— rid 会串线程")


class ConfigureTest(unittest.TestCase):
    def tearDown(self):
        root = logging.getLogger()
        for h in [x for x in root.handlers if getattr(x, "_getcut_json", False)]:
            root.removeHandler(h)
        root.setLevel(logging.WARNING)

    def test_configure_is_idempotent_and_can_switch_stream(self):
        a, b = io.StringIO(), io.StringIO()
        self.assertIs(logx.configure(stream=a), logx.configure(stream=b))
        mine = [h for h in logging.getLogger().handlers
                if getattr(h, "_getcut_json", False)]
        self.assertEqual(len(mine), 1, "重复 configure 挂了第二个 handler —— 每条日志打两遍")
        logging.getLogger("getcut.probe").warning("only-once")
        self.assertIn("only-once", b.getvalue())
        self.assertNotIn("only-once", a.getvalue(),
                         "换了输出流旧流还在收 —— 没复用同一个 handler")

    def test_level_from_env_falls_back_to_info_on_garbage(self):
        """级别写错不许炸：服务起不来只为一个环境变量，代价太大。"""
        old = os.environ.get("GETCUT_LOG_LEVEL")
        try:
            for given, want in (("LOUD", logging.INFO),
                                ("debug", logging.DEBUG),
                                ("warning", logging.WARNING)):
                with self.subTest(given=given):
                    os.environ["GETCUT_LOG_LEVEL"] = given
                    self.assertEqual(logx.level_from_env(), want)
            os.environ.pop("GETCUT_LOG_LEVEL", None)
            self.assertEqual(logx.level_from_env(), logging.INFO)
        finally:
            if old is None:
                os.environ.pop("GETCUT_LOG_LEVEL", None)
            else:
                os.environ["GETCUT_LOG_LEVEL"] = old


class BarePrintTest(unittest.TestCase):
    """库里的 print 绕过了日志：没级别、没 rid、没 traceback，容器一重启还没了。

    命令行的 print 是**输出**给用户看的，必须留着 —— 所以这里分两条：
    库内一条都不许；CLI 那几个文件把数量钉死（新加的诊断只能走 logger）。
    """

    CLI_OUTPUT = {"cli.py", "version.py", "licenses.py", "tts.py"}
    ALLOWED = {"cli.py": 4, "version.py": 1, "licenses.py": 4, "tts.py": 3}

    def test_library_modules_never_print(self):
        bad = []
        for p in sorted(PKG.glob("*.py")):
            if p.name in self.CLI_OUTPUT:
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\bprint\s*\(", line):
                    bad.append(f"{p.name}:{i}: {line.strip()}")
        self.assertEqual(bad, [], "库代码里的 print 绕过了日志：\n" + "\n".join(bad))

    def test_cli_print_count_has_not_grown(self):
        for name, want in sorted(self.ALLOWED.items()):
            with self.subTest(module=name):
                src = (PKG / name).read_text(encoding="utf-8")
                got = len(re.findall(r"\bprint\s*\(", src))
                self.assertEqual(
                    got, want,
                    f"{name} 的 print 数变了（{got} != {want}）—— "
                    "命令行输出留 print 没问题，但新加的诊断必须走 logger")


class LogWiringTest(unittest.TestCase):
    """链路每一环都要有断言：漏一处就等于这条措施没做。"""

    def test_uvicorn_native_access_log_is_off_and_level_not_pinned(self):
        """访问日志归中间件（带 rid、分级、不记 query）。uvicorn 自己那条是纯
        文本、还会把 ?token= 打进日志，必须关掉；log_level 写死 warning 则连
        "服务是什么时候起的"都查不到。

        log_config 同理：uvicorn 自带配置给 uvicorn.* 挂的是纯文本 handler，开机
        4 行 `INFO: Started server process ...` 混进 stdout，`docker logs | jq`
        遇到非 JSON 行直接报错退出 —— 整条"看日志"的路就断在第一行。
        """
        raw = read("getcut/server.py")
        code = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("#"))
        self.assertIn("access_log=False", code, "uvicorn 自己的访问日志会重复且泄露 query")
        self.assertNotIn('log_level="warning"', code, "级别又被写死成 warning 了")
        self.assertIn("GETCUT_UVICORN_LOG_LEVEL", code, "级别不可调")
        self.assertIn("log_config=None", code,
                      "uvicorn 自己的启动信息是纯文本，会把 stdout 搅成非 JSON")

    def test_startup_hook_is_lifespan_not_on_event(self):
        """`@app.on_event("startup")` 自 FastAPI 0.93 起废弃，每次开机往 stderr
        喷 7 行 DeprecationWarning。Dockerfile 的 CMD 是 `python -m getcut.server`，
        模块即 `__main__`，Python 默认必显示这类警告 → `docker logs` 混流后 jq 噎死。
        """
        import ast
        tree = ast.parse(_server_src())

        def calls_named(attr: str) -> list:
            out = []
            for n in ast.walk(tree):
                if not isinstance(n, ast.Call):
                    continue
                f = n.func
                if isinstance(f, ast.Attribute) and f.attr == attr:
                    out.append(n)
            return out

        self.assertEqual(calls_named("on_event"), [],
                         "又用回废弃的 on_event 了 —— 开机 stderr 会喷警告")

        fastapi_calls = [n for n in ast.walk(tree)
                         if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Name) and n.func.id == "FastAPI"]
        self.assertEqual(len(fastapi_calls), 1, "app 的构造点变了，断言要跟着改")
        kws = {k.arg for k in fastapi_calls[0].keywords}
        self.assertIn("lifespan", kws, "开机收尾没挂上 lifespan —— 遗留录音不再清理")

        # 挂了 lifespan 但把清录音的活丢了 = 静默回归，必须一起断言
        life = next((n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == "_lifespan"), None)
        self.assertIsNotNone(life, "_lifespan 不在了")
        self.assertTrue(
            any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr == "purge_recordings" for c in ast.walk(life)),
            "_lifespan 里没调 purge_recordings —— 老客户的录音会一直留着备份")

    def test_startup_really_wires_the_logger(self):
        """Docker 的 CMD 是 `python -m getcut.server` → main()。main() 不
        configure 就等于生产环境一条日志都没有。"""
        self.assertIn("logx.configure()", _server_src())

    def test_docker_log_rotation_is_declared(self):
        """不设轮转时 json-file 驱动无限长：系统盘被吃满的表现是**整个容器起不来**，
        很难第一时间联想到是日志。
        """
        y = read("docker-compose.yml")
        self.assertIn("logging:", y, "compose 里没日志轮转")
        self.assertIn("max-size", y)
        self.assertIn("max-file", y)
        d = read("tools/deploy_new.sh")
        self.assertIn("--log-opt max-size", d, "deploy_new.sh 起的容器没有轮转")
        self.assertIn("--log-opt max-file", d)

    def test_env_example_documents_the_log_level(self):
        self.assertIn("GETCUT_LOG_LEVEL", read(".env.example"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
