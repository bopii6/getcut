"""整包上传口（/api/upload）的四道闸：限流、单账号配额、水位、单包上限（流式）。

2026-09-24 补齐前这条口只有"单包 512MB"一道闸：登录用户可以无限次循环传大包
（重名自动 -1/-2 永不覆盖），照收件口那起"3 小时写崩整机"事故的算法，几小时
就能把盘写满 —— 而账号/密钥/备份都在同一块盘上。本文件把四道闸逐个钉住：
去掉任何一道（比如把限流判据改回"只查不记"），对应用例立刻变红。

跑法（在 getcut/ 目录下）：
    python -m unittest tests.test_upload_gates
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

# config.py 在 import 时就读环境变量定死所有路径：先设环境，再 import 业务模块。
_TMP = tempfile.mkdtemp(prefix="getcut-upload-gates-")
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

from starlette.testclient import TestClient  # noqa: E402

from getcut import auth, ctx, server  # noqa: E402
from getcut.api import transfer  # noqa: E402

A = "uploader@example.invalid"
PW = "Km4-Vb8Qz2Xw7Nt3Rd6P"
BASE = "http://upload.test"


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("content.json", json.dumps({"title": "水位测试包"}, ensure_ascii=False))
    return buf.getvalue()


def setUpModule():
    auth.USERS_FILE = Path(_TMP) / "users.json"
    auth.SECRET_FILE = Path(_TMP) / "auth-secret"
    auth.create_user(A, PW, role="user")
    # 工作区指到本模块自己的空目录：ctx 在更早的模块 import 时就定死了路径，
    # 跟它们共用会数到别人的包；INTAKES 是 import 时绑定的派生路径，一起搬。
    ctx.WORKSPACES = Path(_TMP) / "ws"
    ctx.INTAKES = ctx.WORKSPACES / ".intakes"
    ctx.WORKSPACES.mkdir(parents=True, exist_ok=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, base_url=BASE)
        self.ck = {server.SESSION_COOKIE: auth.make_session(A, auth.SESSION_TTL_SHORT)}
        # 每条用例从空库开始：限流账本是模块级的，不清会在第二十条用例上撞 429
        transfer._UPLOAD_RATE.clear()
        ctx._bundles_meta_save({})
        for d in ctx.WORKSPACES.iterdir():
            import shutil
            shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True)

    def upload(self, content=None, name="bundle.zip", cookies=None):
        return self.client.post(
            "/api/upload",
            files={"file": (name, content if content is not None else _zip(),
                            "application/zip")},
            cookies=cookies if cookies is not None else self.ck)


class UploadGatesTest(Base):
    def test_upload_requires_login(self):
        r = self.upload(cookies={})
        self.assertEqual(r.status_code, 401, "匿名也能整包上传，四道闸等于白装")

    def test_valid_upload_lands_and_records_owner(self):
        r = self.upload()
        self.assertEqual(r.status_code, 200, r.text)
        name = r.json()["name"]
        self.assertTrue((ctx.WORKSPACES / name / "content.json").is_file())
        self.assertEqual(ctx._bundle_owner(name), A, "素材包归属没记到上传账号头上")

    def test_rate_limit_20_per_hour_per_ip(self):
        for i in range(transfer._UPLOADS_PER_HOUR):
            r = self.upload(name=f"rl-{i}.zip")
            self.assertEqual(r.status_code, 200, r.text)
        r = self.upload(name="rl-over.zip")
        self.assertEqual(r.status_code, 429, "同一地址一小时内第 21 个包没被拦下")

    def test_per_user_bundle_cap(self):
        ctx._bundles_meta_save({f"old-{i:03d}": {"owner": A, "created": "2026/09/01"}
                                for i in range(transfer._USER_BUNDLE_CAP)})
        r = self.upload()
        self.assertEqual(r.status_code, 429, "名下包数到上限后还让传")

    def test_waterline_rejects_when_workspaces_full(self):
        fat = ctx.WORKSPACES / "fat-bundle"
        fat.mkdir()
        (fat / "big.bin").touch()
        # 稀疏文件：只记账面大小，不真占 7GB 磁盘
        with open(fat / "big.bin", "rb+") as f:
            f.truncate(transfer._WORKSPACES_WATERLINE_BYTES + 1)
        try:
            r = self.upload()
            self.assertEqual(r.status_code, 503, "素材库过水位后没拒收")
        finally:
            import shutil
            shutil.rmtree(fat, ignore_errors=True)

    def test_size_cap_is_enforced_while_streaming(self):
        keep = transfer.MAX_UPLOAD_BYTES
        transfer.MAX_UPLOAD_BYTES = 2048
        try:
            r = self.upload(content=b"z" * 4096, name="big.zip")
        finally:
            transfer.MAX_UPLOAD_BYTES = keep
        self.assertEqual(r.status_code, 413, "超过单包上限的包该在收包途中被掐断")
        leftovers = [p.name for p in ctx.WORKSPACES.iterdir()
                     if p.name.startswith(("big", ".upload-"))]
        self.assertEqual(leftovers, [], "拒收后不能留半包或空目录")
