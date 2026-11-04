"""并发原子性回归：额度、卡密与匿名收件链都必须在竞争下守住账。"""
from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

_TMP = tempfile.mkdtemp(prefix="getcut-atomicity-")
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

from getcut import auth, config, ctx, licenses, server  # noqa: E402
from getcut.api import transfer  # noqa: E402

A = "atomic-a@example.invalid"
B = "atomic-b@example.invalid"
PASSWORD = "Qz7-Yb3Kd9Nm4Rt8Wx2L"
BASE = "http://atomic.test"


def _zip_bytes(title: str = "并发测试") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.json", json.dumps({"title": title}, ensure_ascii=False))
    return buf.getvalue()


def _request(method: str, path: str, email: str | None = None,
             query: str = "") -> Request:
    headers = []
    if email:
        token = auth.make_session(email, auth.SESSION_TTL_SHORT)
        headers.append((b"cookie", f"{ctx.SESSION_COOKIE}={token}".encode()))
    return Request({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path,
        "raw_path": path.encode(), "query_string": query.encode(), "root_path": "",
        "headers": headers, "client": ("127.0.0.1", 40000), "server": ("atomic.test", 80),
    })


def _put_request(code: str, secret: str, body: bytes, name: str = "并发包.zip") -> Request:
    query = urlencode({"t": secret, "name": name})
    request = _request("PUT", f"/api/intake/{code}", query=query)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request._receive = receive
    return request


def _status(response) -> int:
    return int(getattr(response, "status_code", 200))


class AtomicityTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vg-atomic-case-", dir=_TMP))
        self.workspaces = self.root / "workspaces"
        self.intakes = self.workspaces / ".intakes"
        self.workspaces.mkdir(parents=True)
        self.intakes.mkdir()
        self.saved = [
            (auth, "USERS_FILE", auth.USERS_FILE),
            (auth, "SECRET_FILE", auth.SECRET_FILE),
            (ctx, "WORKSPACES", ctx.WORKSPACES),
            (ctx, "INTAKES", ctx.INTAKES),
            (ctx, "BUNDLES_META", ctx.BUNDLES_META),
            (ctx, "USAGE_FILE", ctx.USAGE_FILE),
            (ctx, "JOBS_FILE", ctx.JOBS_FILE),
            (ctx, "REG", ctx.REG),
            (config, "FREE_DAILY_BUILDS", config.FREE_DAILY_BUILDS),
            (licenses, "_CODE_FILE", licenses._CODE_FILE),
        ]
        auth.USERS_FILE = self.root / "users.json"
        auth.SECRET_FILE = self.root / "auth-secret"
        ctx.WORKSPACES = self.workspaces
        ctx.INTAKES = self.intakes
        ctx.BUNDLES_META = self.workspaces / "bundles.json"
        ctx.USAGE_FILE = self.root / "usage.json"
        ctx.JOBS_FILE = self.root / "jobs.json"
        ctx.REG = self.root / "registry.json"
        ctx._bundles_meta_save({})
        licenses._CODE_FILE = self.root / "licenses.json"
        config.FREE_DAILY_BUILDS = 2
        self.saved_jobs = dict(ctx.JOBS)
        self.saved_pending = dict(ctx._PENDING)
        self.saved_prep = list(ctx._PREP_WAIT)
        ctx.JOBS.clear()
        ctx._PENDING.clear()
        ctx._PREP_WAIT.clear()
        auth.create_user(A, PASSWORD, role="user")
        auth.create_user(B, PASSWORD, role="user")
        # 先完成一次签名密钥落盘；否则并发测试会同时撞上“首次创建密钥”，
        # 偶发拿到尚未写完的密钥而把业务并发失败误报成 401。
        auth.make_session(A, auth.SESSION_TTL_SHORT)
        auth.make_session(B, auth.SESSION_TTL_SHORT)
        self.addCleanup(self._restore)

    def _restore(self):
        ctx.JOBS.clear()
        ctx.JOBS.update(self.saved_jobs)
        ctx._PENDING.clear()
        ctx._PENDING.update(self.saved_pending)
        ctx._PREP_WAIT[:] = self.saved_prep
        for module, name, value in self.saved:
            setattr(module, name, value)

    def _ticket(self, code: str = "abcdef123456", secret: str = "s" * 40) -> tuple[str, str]:
        transfer._intake_sidecar_save(code, {
            "owner": A, "secret": secret, "created": time.time(),
        })
        return code, secret

    def test_free_quota_check_and_bump_cannot_double_spend(self):
        gate = threading.Barrier(12)
        accepted: list[bool] = []

        def spend():
            gate.wait()
            allowed, _ = transfer._free_quota_claim(A)
            if allowed:
                accepted.append(True)

        threads = [threading.Thread(target=spend) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(len(accepted), 2, "并发把 2 条免费额度花成了多次")
        self.assertEqual(transfer._usage_today(A), 2)

    def test_duplicate_active_project_409_does_not_consume_quota(self):
        bundle = self.workspaces / "bundle"
        bundle.mkdir()
        (bundle / "content.json").write_text("{}", encoding="utf-8")
        ctx._bundles_meta_save({"bundle": {"owner": A, "created": "now"}})
        ctx.JOBS["already-running"] = {
            "stage": "render", "project_id": "project-1", "owner": A,
        }
        response = transfer.start_build(
            {"bundle": "bundle", "project_id": "project-1", "format": ctx.DEFAULT_TEMPLATE},
            _request("POST", "/api/build", A),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(transfer._usage_today(A), 0, "重复项目的 409 先扣了免费额度")

    def test_generic_job_status_does_not_expose_try_internals(self):
        raw = self.root / "private-try.mp4"
        raw.write_bytes(b"private")
        ctx.JOBS["tryjob"] = {
            "stage": "done", "stage8": 100, "progress": 100, "detail": "完成",
            "error": None, "owner": A, "try": {"topic": "t1"},
            "video": str(raw), "try_video": str(raw), "work_dir": str(self.root),
        }
        body = transfer.job_status("tryjob", _request("GET", "/api/job/tryjob", A))
        self.assertEqual(set(body), {"stage", "stage8", "progress", "detail", "error"})
        encoded = json.dumps(body)
        for secret in (str(raw), str(self.root), "try_video", "work_dir"):
            self.assertNotIn(secret, encoded)

    def test_one_license_can_only_be_redeemed_once_under_concurrency(self):
        code = licenses.generate("premium", 1)[0]
        gate = threading.Barrier(8)
        results: list[tuple[bool, str, str]] = []

        def redeem(email):
            gate.wait()
            results.append(licenses.redeem(email, code))

        threads = [threading.Thread(target=redeem, args=(email,))
                   for email in (A, B) * 4]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(sum(1 for ok, _, _ in results if ok), 1, "同一张卡被并发兑了多次")
        self.assertEqual(licenses.stats()["premium"]["used"], 1)
        self.assertEqual({auth.user_tier(A), auth.user_tier(B)}, {"free", "premium"})

    def test_license_save_failure_rolls_back_tier_and_keeps_code(self):
        code = licenses.generate("basic", 1)[0]
        with patch.object(licenses, "_save", side_effect=OSError("disk full")):
            ok, message, tier = licenses.redeem(A, code)
        self.assertFalse(ok)
        self.assertIn("重试", message)
        self.assertEqual(tier, "free")
        self.assertEqual(auth.user_tier(A), "free", "卡密落盘失败后账号升档没有恢复")
        self.assertEqual(licenses.stats()["basic"]["used"], 0)
        self.assertTrue(licenses.redeem(A, code)[0], "失败恢复后卡密应仍可重试")

    def test_concurrent_put_uses_one_ticket_once(self):
        code, secret = self._ticket()
        body = _zip_bytes()
        original_save = transfer._intake_sidecar_save

        def slow_reservation(ticket, data):
            original_save(ticket, data)
            if int(data.get("put_reserved") or 0) > 0:
                time.sleep(0.05)

        gate = threading.Barrier(2)
        statuses: list[int] = []

        def put():
            gate.wait()
            response = asyncio.run(transfer.intake_put(
                code, _put_request(code, secret, body)))
            statuses.append(_status(response))

        with patch.object(transfer, "_intake_sidecar_save", side_effect=slow_reservation):
            threads = [threading.Thread(target=put) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        self.assertEqual(sorted(statuses), [200, 409], "一张票被并发 PUT 两次")
        self.assertFalse(transfer._intake_sidecar(code).get("put_claim"))
        self.assertEqual([p.name for p in self.intakes.glob("*.zip")], [f"{code}.zip"])

    def test_concurrent_put_reservations_cannot_cross_waterline(self):
        payload = _zip_bytes("水位")
        first, first_secret = self._ticket("first123456", "a" * 40)
        second, second_secret = self._ticket("second12345", "b" * 40)
        keep = transfer._INTAKE_WATERLINE_BYTES
        transfer._INTAKE_WATERLINE_BYTES = len(payload) + 1
        gate = threading.Barrier(2)
        statuses: list[int] = []

        def put(code, secret):
            gate.wait()
            response = asyncio.run(transfer.intake_put(
                code, _put_request(code, secret, payload)))
            statuses.append(_status(response))

        try:
            threads = [
                threading.Thread(target=put, args=(first, first_secret)),
                threading.Thread(target=put, args=(second, second_secret)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        finally:
            transfer._INTAKE_WATERLINE_BYTES = keep
        self.assertEqual(sorted(statuses), [200, 503], "并发 PUT 一起按旧水位放行了")
        self.assertLessEqual(transfer._intake_stored_bytes(), len(payload) + 1)

    def test_concurrent_claim_creates_one_project_and_releases_marker(self):
        code, _ = self._ticket()
        payload = _zip_bytes("双领测试")
        (self.intakes / f"{code}.zip").write_bytes(payload)
        original_extract = transfer._safe_extract
        gate = threading.Barrier(2)
        responses: list[object] = []

        def slow_extract(zf, dest):
            time.sleep(0.05)
            return original_extract(zf, dest)

        def claim():
            gate.wait()
            responses.append(transfer.intake_claim(
                code, _request("POST", f"/api/intake/{code}/claim", A), {}))

        with patch.object(transfer, "_safe_extract", side_effect=slow_extract):
            threads = [threading.Thread(target=claim) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        self.assertEqual(sorted(_status(r) for r in responses), [200, 409],
                         "同一素材包被双领")
        self.assertEqual(len(ctx._reg()["projects"]), 1)
        side = transfer._intake_sidecar(code)
        self.assertTrue(side["claimed"])
        self.assertNotIn("claim_token", side)
        self.assertFalse((self.intakes / f"{code}.zip").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
