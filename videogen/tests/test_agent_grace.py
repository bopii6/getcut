"""渲染包素材链接的「摘牌宽限」：成片交回后，还开着的页面不该当场取不到素材。

为什么值得锁：成片交回那一刻灶台会 agenthub.discard(job_id)，放行表随之消失。
但页面停在「已完成」上，刷新回预览态、或过一会儿点「重试这一步」，都会重新
去 /agent-media 取素材——链接已经作废，浏览器拿到的是 404 的 JSON，喂给
mediabunny 就变成一句客户看不懂的 "Unknown container format"
（2026-09-21 线上「美国批48架F35给沙特」那条撞过：片子其实已经出好了）。

跑法（在 videogen/ 目录下）：
    python -m unittest discover -s tests -t tests
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from videogen import agenthub


class MediaGraceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.asset = Path(self.dir.name) / "shot.mp4"
        self.asset.write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
        agenthub._JOBS.clear()
        agenthub._GRACE_FILES.clear()
        agenthub.register("j1", "a@b.c", {"x": 1},
                          {"media/m0.mp4": str(self.asset)}, "/tmp/out.mp4")

    def tearDown(self):
        agenthub._JOBS.clear()
        agenthub._GRACE_FILES.clear()
        self.dir.cleanup()

    def test_挂着时取得到_摘牌后宽限期内也取得到(self):
        self.assertEqual(agenthub.file_path("j1", "media/m0.mp4"), self.asset)
        agenthub.discard("j1")
        self.assertEqual(agenthub.file_path("j1", "media/m0.mp4"), self.asset,
                         "摘牌后宽限期内页面还要靠这个链接渲预览与剪映图层")

    def test_宽限一过就取不到(self):
        agenthub.discard("j1")
        stamp = agenthub._GRACE_FILES["j1"][1]
        agenthub._GRACE_FILES["j1"] = (agenthub._GRACE_FILES["j1"][0],
                                       stamp - agenthub._MEDIA_GRACE - 1)
        self.assertIsNone(agenthub.file_path("j1", "media/m0.mp4"))

    def test_没登记过的路径一律不放行(self):
        self.assertIsNone(agenthub.file_path("j1", "../etc/passwd"))
        self.assertIsNone(agenthub.file_path("j1", "media/没这个.mp4"))
        agenthub.discard("j1")
        self.assertIsNone(agenthub.file_path("j1", "../etc/passwd"),
                          "宽限期只延长已登记文件的可见性，不放宽边界")

    def test_文件本体没了也不放行(self):
        agenthub.discard("j1")
        self.asset.unlink()
        self.assertIsNone(agenthub.file_path("j1", "media/m0.mp4"))

    def test_重新挂单以新表为准(self):
        agenthub.discard("j1")
        other = Path(self.dir.name) / "other.mp4"
        other.write_bytes(b"\x00\x00\x00\x18ftypmp42v2")
        agenthub.register("j1", "a@b.c", {"x": 2}, {"media/m0.mp4": str(other)},
                          "/tmp/out.mp4")
        self.assertEqual(agenthub.file_path("j1", "media/m0.mp4"), other)


if __name__ == "__main__":
    unittest.main()
