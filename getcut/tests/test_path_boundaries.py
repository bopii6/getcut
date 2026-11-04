"""路径边界普查：凡是"用户给的名字 + 服务器的目录"拼起来读文件的地方，逐个钉住。

跑法（在 getcut/ 目录下）：
    python -m unittest discover -s tests -t tests

为什么要这一份：2026-09-21 修 /media 时只补了出事那一条边界，评审里留了一句
"同类边界待扫"。扫法不能靠读代码打勾 —— 读着都像是守住了，改一个写法就又漏了。
这里每个接口都配一对断言：
  · 正向：真在根目录里的文件必须 200（否则"404 挡得好"是假的，根目录压根没接通）
  · 越界：根目录**外面**放一个哨兵文件，用一堆写法够它，必须既拿不到 200、
    响应里也不能出现哨兵内容。
去掉 `root not in f.parents` 这一句，本文件立刻变红 —— 这就是它能当闸门的意思。
"""
from __future__ import annotations

import io
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

# config.py 在 import 时就读环境变量定死所有路径：先设环境，再 import 业务模块。
_TMP = tempfile.mkdtemp(prefix="getcut-boundary-")
os.environ.update({
    "GETCUT_WORKSPACE": _TMP,
    "GETCUT_USERS_FILE": str(Path(_TMP) / "users.json"),
    "GETCUT_LICENSES_FILE": str(Path(_TMP) / "licenses.json"),
    "GETCUT_USAGE_FILE": str(Path(_TMP) / "usage.json"),
    "GETCUT_AUTH_SECRET": str(Path(_TMP) / "auth-secret"),
    "GETCUT_BRAND_DIR": str(Path(_TMP) / "brand"),
    "GETCUT_JOBS_FILE": str(Path(_TMP) / "jobs.json"),
    "GETCUT_REGISTRY_FILE": str(Path(_TMP) / "registry.json"),
    "GETCUT_ACCESS_TOKEN": "",
    "EMAIL_SMTP_HOST": "",
})

from starlette.requests import Request  # noqa: E402
from starlette.responses import FileResponse, JSONResponse  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from getcut import agenthub, auth, ctx, remotion_render, server  # noqa: E402
from getcut.planner import Plan, Shot  # noqa: E402
from getcut.schemas import Content  # noqa: E402

ADMIN = "boundary-admin@example.invalid"
ADMIN_PASSWORD = "Yt7-nQz3WkRs9Lb4Xp2M"
SENTINEL = "SENTINEL-OUTSIDE-THE-ROOT-DO-NOT-SERVE"

# 越界写法。前四条走 HTTP 层（%2e 是必须的：httpx 会先把裸 .. 按 RFC 3986 化简掉，
# 用裸 .. 发出去测的其实是"客户端自己拦了"，测不到服务器）；后几条走 handler 层。
WIRE_PAYLOADS = [
    "..%2Fsentinel.txt",
    "..%2F..%2Fsentinel.txt",
    "%2e%2e/sentinel.txt",
    "..%2fassets%2f..%2fsentinel.txt",
]
HANDLER_PAYLOADS = [
    "../sentinel.txt",
    "../../sentinel.txt",
    "..\\sentinel.txt",
    "sub/../../sentinel.txt",
    "....//sentinel.txt",
    "/etc/absolutely-outside/sentinel.txt",
    "sentinel.txt",                    # 根目录同名？不，哨兵在根的外面
]
# 专门坑 str().startswith 那种"包含判断"：同级目录/文件名以根目录名开头时，
# startswith 会说"在根内"，真包含判断会说"不在"。2026-09-21 之前的 /poc 就是这个写法。
PREFIX_SENTINELS = ("root-sibling.txt", "ws-sibling.txt")



def setUpModule():
    auth.USERS_FILE = Path(_TMP) / "users.json"
    auth.SECRET_FILE = Path(_TMP) / "auth-secret"
    auth.create_user(ADMIN, ADMIN_PASSWORD, role="admin")
    assert auth.has_users(), "测试账号没建起来，断言无效"


def _request(path: str, session: str) -> Request:
    """造一个够真的 Request：这些接口只读 cookies，不必绕一整圈 HTTP。

    handler 层断言走这条路，是为了绕开测试客户端的 URL 化简 —— 越界字符串必须
    原样抵达被检代码，否则测的是 httpx 的规范化，不是这行的包含判断。
    """
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "https", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "",
        "headers": [(b"cookie", f"{server.SESSION_COOKIE}={session}".encode())],
        "client": ("203.0.113.9", 51000), "server": ("getcut.test", 443),
    }
    return Request(scope)


class BoundaryFixture(unittest.TestCase):
    """给每条边界搭一套"根目录 + 根外哨兵"，用完还原被替换的模块常量。"""

    #: 子类覆盖：(模块名, 值) 形如 ("STATIC", Path(...))
    root_name = ""

    #: 子类覆盖：从各自根目录出发、够到"同名前缀邻居"的写法
    prefix_payloads: tuple = ()

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="vg-bound-", dir=_TMP))
        self.root = self.base / "root"
        self.root.mkdir(parents=True)
        # 哨兵放在根的父目录里：任何一次"逃出根目录"都会先踩到它
        self.sentinel = self.base / "sentinel.txt"
        self.sentinel.write_text(SENTINEL, encoding="utf-8")
        for name in PREFIX_SENTINELS:
            (self.base / name).write_text(SENTINEL, encoding="utf-8")
        self._saved = {}
        self.apply_roots()
        self.session = auth.make_session(ADMIN, auth.SESSION_TTL_SHORT)
        self.client = TestClient(server.app, base_url="http://boundary.test",
                                 cookies={server.SESSION_COOKIE: self.session})

    def tearDown(self):
        for name, (home, value) in self._saved.items():
            setattr(home, name, value)

    def patch(self, name: str, value) -> None:
        """把根目录指到临时目录。

        落到符号**真正的家**上：ROOT / STATIC / WORKSPACES / OUTPUTS /
        BROWSERPOC_DIR 已经搬进 ctx（server 和 api 都得读同一个值），只往
        server.__dict__ 里塞的话 handler 读到的还是原值 —— 测试会假绿，
        而「越界挡没挡住」恰恰是最不能假绿的那类。
        """
        home = ctx if hasattr(ctx, name) else server
        self._saved.setdefault(name, (home, getattr(home, name)))
        setattr(home, name, value)

    def apply_roots(self) -> None:
        raise NotImplementedError

    # ---- 断言小工具 -------------------------------------------------
    def assertServes(self, path: str, expect: bytes) -> None:
        """正向控制：根内的真文件必须真的到得了，否则"挡住了"没有意义。"""
        r = self.client.get(path)
        self.assertEqual(r.status_code, 200, f"{path} 根内文件取不到，正向控制失效")
        self.assertIn(expect, r.content)

    def assertBlockedWire(self, path: str) -> None:
        r = self.client.get(path)
        if r.status_code == 200:
            self.assertNotIn(SENTINEL, r.text, f"{path} 把根目录外的文件发出去了")
            self.fail(f"{path} 越界还 200")
        self.assertIn(r.status_code, (400, 404), f"{path} 越界返回 {r.status_code}")
        self.assertNotIn(SENTINEL, r.text)

    def assertBlockedHandler(self, got, label: str) -> None:
        if isinstance(got, FileResponse):
            self.fail(f"{label} 越界却给了 FileResponse：{got.path}")
        self.assertIsInstance(got, JSONResponse, f"{label} 越界该 404，拿到 {type(got)}")
        body = got.body.decode("utf-8", "replace")
        self.assertNotIn(SENTINEL, body, f"{label} 把哨兵内容写进了响应")
        self.assertEqual(got.status_code, 404, f"{label} 越界的返回码不是 404")


class MediaBoundaryTest(BoundaryFixture):
    """/media/{包名}/{路径}：2026-09-21 出事的那条，如今按"根外取不到"复验。"""

    # 根 = <base>/ws，邻居 = <base>/ws-sibling.txt
    prefix_payloads = ("../../ws-sibling.txt",)

    def apply_roots(self):
        self.ws = self.base / "ws"
        (self.ws / "bundle-ok" / "images").mkdir(parents=True)
        (self.ws / "bundle-ok" / "images" / "a.png").write_text("PIXEL", encoding="utf-8")
        self.patch("WORKSPACES", self.ws)

    def test_real_asset_inside_the_bundle_is_served(self):
        self.assertServes("/media/bundle-ok/images/a.png", b"PIXEL")

    def test_dotdot_via_http_cannot_reach_outside_the_workspace(self):
        for p in WIRE_PAYLOADS:
            with self.subTest(payload=p):
                self.assertBlockedWire(f"/media/bundle-ok/{p}")
        # 包名这一格也是用户输入：/media/../ 想直接跳出工作区
        for p in WIRE_PAYLOADS:
            with self.subTest(bundle=p):
                self.assertBlockedWire(f"/media/{p}/a.png")

    def test_workspace_itself_is_not_a_file_to_download(self):
        """`/media/bundle-ok/` 结尾空路径会把根目录本身当文件：必须是 404 不是目录列表。"""
        self.assertBlockedHandler(server.media("bundle-ok", "", _request("/media/bundle-ok/", self.session)),
            "media 空路径")

    def test_every_traversal_spelling_is_blocked_at_the_handler(self):
        for payload in HANDLER_PAYLOADS + list(self.prefix_payloads):
            with self.subTest(payload=payload):
                req = _request(f"/media/bundle-ok/{payload}", self.session)
                self.assertBlockedHandler(server.media("bundle-ok", payload, req),
                                          f"media {payload}")

    def test_bundle_detail_name_cannot_escape_the_workspace(self):
        for payload in HANDLER_PAYLOADS + ["..", "../ws-sibling"]:
            with self.subTest(payload=payload):
                req = _request(f"/api/bundle/{payload}", self.session)
                self.assertBlockedHandler(server.bundle_detail(payload, req),
                                          f"bundle_detail {payload}")
        for payload in WIRE_PAYLOADS:
            with self.subTest(wire=payload):
                self.assertBlockedWire(f"/api/bundle/{payload}")


class PocBoundaryTest(BoundaryFixture):
    # 根 = <base>/root，邻居 = <base>/root-sibling.txt：startswith("<base>/root") 会说它在内
    """/poc/ 是公开路径（未登录也要能打开成片台外壳），所以边界只能靠这一句包含判断。"""

    prefix_payloads = ("../root-sibling.txt",)

    def apply_roots(self):
        self.patch("BROWSERPOC_DIR", self.root)
        (self.root / "sub").mkdir()
        (self.root / "sub" / "bundle.js").write_text("POC-ASSET", encoding="utf-8")

    def test_asset_inside_the_poc_dir_is_served(self):
        self.assertServes("/poc/sub/bundle.js", b"POC-ASSET")

    def test_escaping_poc_falls_back_to_the_shell_page_not_the_file(self):
        """逃出去不能给文件；这里回退到 SPA 外壳是设计，但外壳里不许带出哨兵内容。"""
        for payload in WIRE_PAYLOADS:
            with self.subTest(payload=payload):
                r = self.client.get(f"/poc/{payload}")
                self.assertNotIn(SENTINEL, r.text)

    def test_every_traversal_spelling_is_blocked_at_the_handler(self):
        for payload in HANDLER_PAYLOADS + list(self.prefix_payloads):
            with self.subTest(payload=payload):
                self.assertBlockedHandler(server.poc_page(payload), f"poc {payload}")


class StaticAssetBoundaryTest(BoundaryFixture):
    """/templates、/fonts 同属公开路径，写法一样所以放一起测。"""

    # 根 = <base>/root/templates，邻居 = <base>/root/templates-sibling.png
    prefix_payloads = ("../templates-sibling.png",)

    def apply_roots(self):
        self.patch("STATIC", self.root)
        (self.root / "templates").mkdir()
        (self.root / "fonts").mkdir()
        (self.root / "templates" / "tpl-x.png").write_text("THUMB", encoding="utf-8")
        (self.root / "templates-sibling.png").write_text(SENTINEL, encoding="utf-8")
        (self.root / "fonts" / "f.ttf").write_text("FONT", encoding="utf-8")

    def test_real_assets_are_served(self):
        self.assertServes("/templates/tpl-x.png", b"THUMB")
        self.assertServes("/fonts/f.ttf", b"FONT")

    def test_every_traversal_spelling_is_blocked_at_the_handler(self):
        for payload in HANDLER_PAYLOADS + list(self.prefix_payloads):
            with self.subTest(endpoint="templates", payload=payload):
                self.assertBlockedHandler(server.template_thumb(payload),
                                          f"templates {payload}")
            with self.subTest(endpoint="fonts", payload=payload):
                self.assertBlockedHandler(server.font(payload), f"fonts {payload}")

    def test_dotdot_via_http_cannot_reach_outside_the_root(self):
        for p in WIRE_PAYLOADS:
            with self.subTest(payload=p):
                self.assertBlockedWire(f"/templates/{p}")
                self.assertBlockedWire(f"/fonts/{p}")


class AudioLibraryBoundaryTest(BoundaryFixture):
    """/api/bgm、/api/sfx 的写法是 `ROOT / "assets" / "music"`，所以按 ROOT 打桩。"""

    # 根 = <base>/root/assets/music，邻居 = <base>/root/assets/music-sibling.mp3
    prefix_payloads = ("../music-sibling.mp3",)

    def apply_roots(self):
        self.patch("ROOT", self.root)
        for kind, name in (("music", "bgm.mp3"), ("sfx", "hit.mp3")):
            d = self.root / "assets" / kind
            d.mkdir(parents=True)
            (d / name).write_text("AUDIO", encoding="utf-8")
            (d.parent / f"{kind}-sibling.mp3").write_text(SENTINEL, encoding="utf-8")

    def test_real_clips_are_served(self):
        self.assertServes("/api/bgm/bgm.mp3", b"AUDIO")
        self.assertServes("/api/sfx/hit.mp3", b"AUDIO")

    def test_every_traversal_spelling_is_blocked_at_the_handler(self):
        for payload in HANDLER_PAYLOADS + list(self.prefix_payloads):
            for suffix in ("", ".mp3"):
                p = payload if payload.endswith(".mp3") else payload + suffix
                with self.subTest(endpoint="bgm", payload=p):
                    self.assertBlockedHandler(server.bgm_file(p), f"bgm {p}")
                with self.subTest(endpoint="sfx", payload=p):
                    self.assertBlockedHandler(server.sfx_file(p), f"sfx {p}")

    def test_dotdot_via_http_cannot_reach_outside_the_root(self):
        for p in WIRE_PAYLOADS:
            with self.subTest(payload=p):
                self.assertBlockedWire(f"/api/bgm/{p}")
                self.assertBlockedWire(f"/api/sfx/{p}")


class IdShapeBoundaryTest(BoundaryFixture):
    """文件名即 id 的那几个：形状不对就在门口 404，压根不碰磁盘。"""

    def apply_roots(self):
        self.patch("OUTPUTS", self.root)

    def test_try_video_only_accepts_a_job_id_shaped_name(self):
        (self.root / "1a2b3c4d5e6f7890.mp4").write_text("OUTSIDE", encoding="utf-8")
        for name in ("..%2Fsentinel.txt", "%2e%2e/sentinel.txt", "1a2b3c4d5e6f7890.mp4"):
            with self.subTest(name=name):
                self.assertBlockedWire(f"/try/{name}")
        # 形状对但没登记过 → 走 JOBS 表，不是磁盘
        # 形状对但没登记过 → 走 JOBS 表，不是磁盘。两条都到不了归属判定
        # （形状不对先 404、没登记过也先 404），所以 request 传 None 就够
        self.assertBlockedHandler(server.try_video("1a2b3c4d5e6f7890.mp4", None), "try_video")
        self.assertBlockedHandler(server.try_video("../../sentinel.txt", None), "try_video 越界")

    def test_voice_clone_staging_needs_40_hex_and_nothing_else(self):
        for name in ("sentinel.txt", "%2e%2e%2fsentinel.txt",
                     "0" * 40 + ".mp3", "0" * 39 + ".mp3",
                     "0" * 40 + ".txt"):
            with self.subTest(name=name):
                self.assertBlockedWire(f"/vc-src/{name}")
        self.assertBlockedHandler(server.vc_src("../x.mp3"), "vc_src 越界")


class AgentMediaBoundaryTest(BoundaryFixture):
    """成片台取素材：放行表是唯一依据，`fonts/` 回退是唯一的例外通道。"""

    def apply_roots(self):
        self.patch("ROOT", self.root)
        media = self.root / "renderer" / "public"
        (media / "fonts").mkdir(parents=True)
        (media / "fonts" / "brand.ttf").write_text("SUBSET", encoding="utf-8")
        self.job = "1a2b3c4d5e6f7890"

    def test_unregistered_path_is_not_read_even_when_the_file_exists(self):
        """登记表是唯一依据：文件名合法、磁盘上真有这个文件，没挂过单也取不到。"""
        (self.root / "frames").mkdir()
        (self.root / "frames" / "shot_001.png").write_text("PIXEL", encoding="utf-8")
        self.assertIsNone(agenthub.file_path(self.job, "frames/shot_001.png"))

    def test_registered_path_still_works(self):
        real = self.root / "props.json"
        real.write_text('{"a": 1}', encoding="utf-8")
        agenthub.register(self.job, ADMIN, {}, {"props.json": str(real)},
                          str(self.root / "out.mp4"))
        self.assertEqual(agenthub.file_path(self.job, "props.json"), real)
        # 表里没有的名字，无论怎么写都取不到（越界写法在这里根本不构成攻击面）
        for payload in HANDLER_PAYLOADS + ["props.json/../sentinel.txt", ""]:
            with self.subTest(payload=payload):
                self.assertIsNone(agenthub.file_path(self.job, payload),
                                  f"file_path {payload} 竟然放行")

    def test_anonymous_cannot_use_agent_media_as_a_file_reader(self):
        anon = TestClient(server.app, base_url="http://boundary.test")
        r = anon.get(f"/agent-media/{self.job}/props.json")
        self.assertEqual(r.status_code, 401)

    def test_fonts_fallback_refuses_traversal(self):
        """fonts/ 是唯一"不进登记表也放行"的通道（模板公共字体子集），
        它的全部护栏就是 startswith("fonts/") + 不含 ".."，所以每种写法都得试。
        """
        for payload in ("fonts/../sentinel.txt", "fonts/../../sentinel.txt",
                        "fonts/%2e%2e/sentinel.txt", "fonts/sub/../../sentinel.txt",
                        "fonts/../../../requirements.txt",   # 仓库里真存在的文件
                        "fonts/..", "fonts"):
            with self.subTest(payload=payload):
                r = _request(f"/agent-media/{self.job}/{payload}", self.session)
                self.assertBlockedHandler(server.agent_media(self.job, r, payload), f"fonts {payload}")


class RenderAssetBoundaryTest(unittest.TestCase):
    """渲染包出口：素材路径必须是 bundle-relative，不能把包外文件拷进媒体目录。"""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="vg-render-boundary-", dir=_TMP))
        self.bundle = self.base / "bundle"
        self.bundle.mkdir()
        self.outside = self.base / "outside.png"
        self.outside.write_bytes(SENTINEL.encode("utf-8"))
        self.renderer = self.base / "renderer"
        self.patch = patch.object(remotion_render, "RENDERER", self.renderer)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.media_dir = self.renderer / "public" / "media"
        self.content = Content(schema_version=1, title="边界", script="")

    def build(self, plan, template="editorial"):
        return remotion_render.build_props(
            self.bundle, plan, self.content, {}, {}, template=template)

    def assert_outside_not_copied(self):
        self.assertEqual(list(self.media_dir.iterdir()), [])

    def test_shot_asset_path_outside_bundle_is_not_copied(self):
        plan = Plan(duration_ms=1000, shots=[
            Shot(kind="footage", asset_path="../outside.png", sent_indexes=[]),
        ])
        props = self.build(plan)
        self.assertNotIn("media", props["shots"][0])
        self.assert_outside_not_copied()

    def test_next_asset_path_outside_bundle_is_not_copied(self):
        class Shots:
            def __iter__(self):
                yield Shot(kind="title_card", asset_path=None, sent_indexes=[])
                yield Shot(kind="footage", asset_path="../outside.png", sent_indexes=[])

        plan = Plan(duration_ms=1000, shots=Shots())
        props = self.build(plan, template="zhigu")
        self.assertNotIn("media", props["shots"][0])
        self.assert_outside_not_copied()

    def test_macro_background_path_outside_bundle_is_not_copied(self):
        plan = Plan(duration_ms=1000, bg_asset="../outside.png")
        props = self.build(plan, template="macro")
        self.assertEqual(props["bgImage"], "rep__macro_bg.jpg")
        self.assert_outside_not_copied()


class ZipExtractBoundaryTest(unittest.TestCase):
    """上传口的解包：素材包 zip 是**任意注册用户**能递给服务器的文件名列表。

    名字过检 ≠ 安全：`link` 与 `link/evil.txt` 各自都在包内，解压器却会先建软链
    再把文件"穿过"它写到外面。所以成员类型也必须限死（只收普通文件与目录）。
    """

    def _zip(self, members):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data, kind in members:
                if kind == "file":
                    zf.writestr(name, data)
                else:   # symlink / 目录，external_attr 得手工摆
                    info = zipfile.ZipInfo(name)
                    mode = (stat.S_IFLNK if kind == "symlink" else stat.S_IFDIR) | 0o777
                    info.external_attr = mode << 16
                    zf.writestr(info, data)
        buf.seek(0)
        return zipfile.ZipFile(buf)

    def _extract(self, members, tmp):
        dest = Path(tmp) / "bundle"
        dest.mkdir(parents=True)
        with self._zip(members) as zf:
            server._safe_extract(zf, dest)
        return dest

    def test_a_normal_bundle_still_unpacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = self._extract([("content.json", "{}", "file"),
                                  ("images/a.png", "PIXEL", "file"),
                                  ("images/", "", "dir")], tmp)
            self.assertEqual((dest / "images" / "a.png").read_text(), "PIXEL")

    def test_zip_slip_names_are_refused(self):
        names = ["../../escaped.txt", "/etc/passwd"]
        if os.name == "nt":
            names.append("..\\escaped.txt")     # 反斜杠只在 Windows 上才是分隔符
        for name in names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    self._extract([(name, "X", "file")], tmp)
                self.assertFalse((Path(tmp).parent / "escaped.txt").exists())

    def test_symlink_member_is_refused_even_though_its_name_is_clean(self):
        """这条是 2026-09-21 普查新补的：老代码只看名字，两种名字都"合法"。"""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                self._extract([("link", "../", "symlink"),
                               ("link/evil.txt", "X", "file")], tmp)
            self.assertIn("不支持的文件类型", str(ctx.exception))
            # 真解出来才算越界；POSIX 上 os.symlink 会成功，Windows 上本就建不了
            self.assertFalse((Path(tmp) / "evil.txt").exists())
            self.assertFalse((Path(tmp).parent / "evil.txt").exists())

    def test_other_special_types_are_refused_too(self):
        for name, mode in (("fifo", stat.S_IFIFO), ("dev", stat.S_IFCHR)):
            with self.subTest(kind=name):
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as zf:
                    info = zipfile.ZipInfo("x")
                    info.external_attr = (mode | 0o644) << 16
                    zf.writestr(info, "")
                buf.seek(0)
                with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(buf) as zf:
                    with self.assertRaises(ValueError):
                        server._safe_extract(zf, Path(tmp))


class NullByteTest(unittest.TestCase):
    """%00 不是路径：以前会一路走到 pathlib，抛 ValueError → 匿名访客一发就一个 500。"""

    PATHS = ["/poc/%00index.html", "/poc/index.html%00.js", "/fonts/%00f.ttf",
             "/templates/%00x.png", "/api/bgm/%00a.mp3", "/api/sfx/%00a.wav",
             "/media/b/%00.png", "/try/%00.mp4", "/vc-src/%00.mp3"]

    def test_public_routes_reject_embedded_null_without_500(self):
        client = TestClient(server.app, base_url="http://boundary.test",
                            raise_server_exceptions=False)
        for path in self.PATHS:
            with self.subTest(path=path):
                r = client.get(path)
                self.assertEqual(r.status_code, 400, "%s 没在门口拦下空字节" % path)
                self.assertEqual(r.headers["cache-control"], "no-store")

    def test_the_gate_still_serves_ordinary_paths(self):
        """别把闸门写成"什么都是 400"：正常页与探针必须照旧 200。"""
        client = TestClient(server.app, base_url="http://boundary.test")
        for path in ("/healthz", "/api/auth/status", "/poc/"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
