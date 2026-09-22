"""隐私留存：客户的原始录音不在服务器上留档（2026-09-21 站长拍板「不要存人家的」）。

跑法（在 videogen/ 目录下）：
    python -m unittest tests.test_privacy -v

这条不是"合规装饰"：`sample.mp3` 全仓没有任何一处读它，纯粹是过去顺手留下的，
而它落在 /state/.videogen-brand 下、每天还跟着进 90 天备份。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="videogen-privacy-")
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

from videogen import ctx, brand, server, voice_clone  # noqa: E402

EMAIL = "voice-owner@example.invalid"
RECording = b"ID3\x03fake-customer-voice-data"


class RecordingRetentionTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="vg-privacy-", dir=_TMP))
        self.saved_dir = brand.DIR
        brand.DIR = self.dir

    def tearDown(self):
        brand.DIR = self.saved_dir

    def _sample(self) -> Path:
        return brand._dir(EMAIL) / "sample.mp3"

    def test_set_clone_keeps_only_the_reference(self):
        """登记成功后只剩 voice_id —— 磁盘上不许出现录音本体。"""
        clone = brand.set_clone(EMAIL, "vc-abc123")
        self.assertEqual(clone["voice_id"], "vc-abc123")
        self.assertFalse(self._sample().exists(), "登记路径又把客户录音写回磁盘了")
        self.assertIn("vc-abc123", brand.clone_info(EMAIL)["voice_id"])

    def test_set_clone_clears_a_legacy_copy(self):
        """老数据：同一个人再登记一次，顺手把他那份旧的删掉。"""
        self._sample().parent.mkdir(parents=True, exist_ok=True)
        self._sample().write_bytes(RECording)
        brand.set_clone(EMAIL, "vc-new")
        self.assertFalse(self._sample().exists())

    def test_purge_removes_every_leftover_and_counts(self):
        for who in ("a", "b"):
            p = self.dir / who
            p.mkdir()
            (p / "sample.mp3").write_bytes(RECording)
            (p / "logo.png").write_bytes(b"\x89PNG")
        self.assertEqual(brand.purge_recordings(), 2)
        self.assertEqual(list(self.dir.glob("*/sample.mp3")), [])
        self.assertTrue((self.dir / "a" / "logo.png").is_file(), "别把 logo 一起删了")

    def test_worker_returns_an_id_not_the_recording(self):
        """工作者函数不许把录音字节往外传 —— 一旦有返回值带 bytes，就总有人会存它。"""
        def fake_convert(src, dst):
            dst.write_bytes(RECording)
        seen = {}

        def fake_enroll(mp3, prefix, base):
            seen["tmp"] = Path(mp3).parent
            self.assertTrue(Path(mp3).is_file(), "登记时录音得在场，否则百炼取不到")
            return "vc-from-worker"

        real = (voice_clone.convert_audio, voice_clone.enroll, ctx._preview_file,
                server.tts_mod.synthesize_preview)
        voice_clone.convert_audio, voice_clone.enroll = fake_convert, fake_enroll
        ctx._preview_file = lambda voice: Path(_TMP) / "no-preview-cache.mp3"
        server.tts_mod.synthesize_preview = lambda *a, **k: None   # 不碰真配音服务
        try:
            out = server._clone_worker(RECording, "getcut-test", "https://getcut.test")
        finally:
            voice_clone.convert_audio, voice_clone.enroll = real[0], real[1]
            ctx._preview_file = real[2]
            server.tts_mod.synthesize_preview = real[3]
        self.assertEqual(out, "vc-from-worker")
        self.assertFalse(seen["tmp"].exists(), "临时目录没随登记结束一起清掉")


if __name__ == "__main__":
    unittest.main(verbosity=2)
