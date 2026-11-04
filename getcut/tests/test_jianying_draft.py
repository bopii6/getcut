"""剪映分轨草稿（draft_content.json / manifest）的离线闸门。

跑法（在 getcut/ 目录下）：
    python -m unittest discover -s tests -t tests

为什么值得锁：这条是评估认到的三处翻车里唯一还没测试的（b29c1dc、d7d77f2 两次都是
真机打开剪映才暴露）。草稿 JSON 错一个键、多一帧、少一个 clip，剪映不是报错给你看，
而是「媒体丢失」「整段丢音」「时间轴比成片长一截」——客户只会说"装不上"。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from getcut import jianying_draft as jd

US = 1000


def plan(**over):
    p = {
        "title": "离线草稿", "width": 1080, "height": 1920, "duration_ms": 6000.0, "fps": 30.0,
        "base": "layers/base.png",
        "shots": [
            {"start_ms": 0.0, "end_ms": 3000.0, "media": "media/a.mp4", "media_duration_ms": 5000.0,
             "card": "layers/card1.png",
             "texts": [{"text": "48架", "x": 100, "y": 200, "w": 300, "h": 90,
                        "color": "rgb(180, 34, 47)", "size": 64, "bold": True}]},
            {"start_ms": 3000.0, "end_ms": 6000.0, "chrome": "layers/card2.png",
             "texts": [{"text": "美联储加息", "x": 80, "y": 1400, "w": 900, "h": 120}]},
            {"start_ms": 6000.0, "end_ms": 5000.0},              # 时长为负：要跳过
        ],
        "subtitles": [{"text": "第一句字幕", "start_ms": 0.0, "end_ms": 2900.0},
                      {"text": "   ", "start_ms": 100.0, "end_ms": 200.0},   # 空文本：要跳过
                      {"text": "尾句顶过片尾", "start_ms": 3000.0, "end_ms": 9999.0}],
        "voice_clips": [{"file": "voice/v0.mp3", "start_ms": 0.0, "end_ms": 2900.0,
                         "duration_ms": 2900.0},
                        {"start_ms": 3000.0, "end_ms": 4000.0}],            # 没有 file：要跳过
        "bgm": {"file": "assets/music/x.mp3", "duration_ms": 60000.0, "volume": 0.25},
        "sfx": [{"file": "assets/sfx/hit.mp3", "start_ms": 500.0}],
    }
    p.update(over)
    return p


class DraftHelperTest(unittest.TestCase):
    def test_timerange_is_microseconds_and_rounded(self):
        self.assertEqual(jd._trange(1500.4, 2200.6), {"start": 1500400, "duration": 2200600})

    def test_ids_unique_and_hex(self):
        ids = {jd._uid() for _ in range(500)}
        self.assertEqual(len(ids), 500)
        self.assertTrue(all(len(i) == 32 and int(i, 16) >= 0 for i in ids))

    def test_text_material_range_matches_text_length(self):
        """range 与文本长度不符，剪映会把字幕截断或整行不显示。"""
        for text in ("48架", "美联储加息 2026", "a"):
            m = jd._text_material(text)
            style = json.loads(m["content"])["styles"][0]
            self.assertEqual(style["range"], [0, len(text)])
            self.assertEqual(json.loads(m["content"])["text"], text, "中文不许被转义成 \\uXXXX")

    def test_css_color_only_accepts_rgb_forms(self):
        self.assertEqual(jd._parse_css_color("rgb(180, 34, 47)"), (0.7059, 0.1333, 0.1843))
        self.assertEqual(jd._parse_css_color("rgba(0, 0, 0, 0.5)"), (0.0, 0.0, 0.0))
        self.assertEqual(jd._parse_css_color("rgb(300, -5, 12)"), (1.0, 0.0, 0.0471), "通道值要夹进 0~255")
        # 现状是明说的坑，不是 bug：浏览器算出来的是 rgb()，十六进制会被当"没给颜色"→ 白色。
        # 以后要支持 #b4222f，改这条断言并同时改 _parse_css_color。
        self.assertEqual(jd._parse_css_color("#b4222f"), (1.0, 1.0, 1.0), "非 rgb() 形式一律退回白色")
        self.assertEqual(jd._parse_css_color(None), (1.0, 1.0, 1.0))
        self.assertEqual(jd._parse_css_color("rgb(a, b, c)"), (1.0, 1.0, 1.0))


class MultitrackDraftTest(unittest.TestCase):
    def setUp(self):
        self.content = jd.build_multitrack_content(plan())

    def segs(self, *types):
        return [s for t in self.content["tracks"] if t["type"] in types for s in t["segments"]]

    def test_validation_passes_and_no_dangling_reference(self):
        jd._validate_content(self.content)          # 不抛就是过（悬空引用 = 剪映拒绝打开）
        with self.assertRaises(RuntimeError):
            jd._validate_content({"materials": self.content["materials"],
                                  "tracks": [{"name": "配音", "segments": [
                                      {"material_id": "不存在", "extra_material_refs": []}]}]})

    def test_no_segment_overruns_the_timeline(self):
        """尾句字幕/配音顶过最后一帧，剪映会把时间轴拉长：草稿比成片长一截空画面。"""
        cap = self.content["duration"]
        for seg in self.segs("text", "video", "audio"):
            t = seg["target_timerange"]
            with self.subTest(material=seg["material_id"][:6], start=t["start"]):
                self.assertLessEqual(t["start"] + t["duration"], cap)

    def test_timeline_units_and_canvas(self):
        self.assertEqual(self.content["duration"], 6000 * US)
        self.assertEqual((self.content["canvas_config"]["width"],
                          self.content["canvas_config"]["height"]), (1080, 1920))
        self.assertEqual(self.content["name"], "离线草稿")

    def test_segments_do_not_overlap_within_a_track(self):
        for track in self.content["tracks"]:
            spans = sorted((s["target_timerange"]["start"],
                            s["target_timerange"]["start"] + s["target_timerange"]["duration"])
                           for s in track["segments"])
            for (_, prev_end), (next_start, _) in zip(spans, spans[1:], strict=False):
                self.assertLessEqual(prev_end, next_start, "%s 轨内片段重叠" % track["name"])

    def test_track_render_index_is_contiguous_per_track(self):
        for track in self.content["tracks"]:
            self.assertEqual([s["track_render_index"] for s in track["segments"]],
                             list(range(len(track["segments"]))),
                             "%s 轨的轨内序号断了，新版剪映按它重排顺序" % track["name"])

    def test_audio_segments_still_carry_the_clip_key(self):
        """剪映 11.5 的升级转换器会丢掉缺 clip 键的音频片段（整条音轨「媒体丢失」）。"""
        audio = self.segs("audio")
        self.assertTrue(audio, "这个用例该有音频片段，不然锁不住")
        self.assertTrue(all("clip" in s and s["clip"] is None for s in audio))
        self.assertTrue(all(isinstance(s["clip"], dict) for s in self.segs("video")))

    def test_every_segment_speed_reference_exists(self):
        speed_ids = {m["id"] for m in self.content["materials"]["speeds"]}
        for seg in self.segs("text", "video", "audio"):
            for ref in seg.get("extra_material_refs") or []:
                self.assertIn(ref, speed_ids)

    def test_garbage_items_are_skipped_not_rendered(self):
        texts = [json.loads(m["content"])["text"] for m in self.content["materials"]["texts"]]
        self.assertNotIn("   ", texts, "空白字幕进了草稿")
        self.assertIn("48架", texts)
        self.assertEqual(len(self.segs("audio")), 3, "配音一条 + 背景乐一条 + 音效一条")

    def test_overlay_text_needs_measurable_geometry(self):
        """浏览器量不出字号/宽度的文字项宁可不给可编辑层，也别放一坨看不见的空文本。"""
        p = plan(shots=[{"start_ms": 0.0, "end_ms": 3000.0,
                         "texts": [{"text": "没字号", "x": 0, "y": 0, "w": 100, "h": 40},
                                   {"text": "字号太小", "x": 0, "y": 0, "w": 100, "h": 40, "size": 4},
                                   {"text": "零宽", "x": 0, "y": 0, "w": 0, "h": 40, "size": 40},
                                   {"text": "合格", "x": 0, "y": 0, "w": 200, "h": 40, "size": 40}]}],
                 duration_ms=3000.0, base=None, subtitles=[], voice_clips=[], bgm=None, sfx=[])
        c = jd.build_multitrack_content(p)
        texts = [json.loads(m["content"])["text"] for m in c["materials"]["texts"]]
        self.assertEqual(texts, ["合格"])

    def test_empty_plan_yields_no_tracks(self):
        c = jd.build_multitrack_content({"duration_ms": 0, "title": ""})
        self.assertEqual(c["tracks"], [])
        jd._validate_content(c)

    def test_layer_cards_are_one_segment_each(self):
        """32 张卡片就得是 32 个片段（d7d77f2 那次真机才暴露：卡片合并/丢失）。"""
        many = plan(shots=[{"start_ms": float(i) * 1000, "end_ms": float(i + 1) * 1000,
                            "card": "layers/c%d.png" % i,
                            "texts": [{"text": "字%d" % i, "x": 10, "y": 20, "w": 100, "h": 40,
                                       "size": 40}]}
                           for i in range(32)],
                    duration_ms=32000.0, base=None, subtitles=[], voice_clips=[], bgm=None, sfx=[])
        c = jd.build_multitrack_content(many)
        cards = [t for t in c["tracks"] if t["name"] == "卡片"]
        overlay = [t for t in c["tracks"] if t["name"] == "叠加文字"]
        self.assertEqual(sum(len(t["segments"]) for t in cards), 32)
        self.assertEqual(sum(len(t["segments"]) for t in overlay), 32)
        self.assertLessEqual(max(s["target_timerange"]["start"] + s["target_timerange"]["duration"]
                                 for t in cards + overlay for s in t["segments"]), c["duration"])


class FlatDraftTest(unittest.TestCase):
    def manifest(self, **over):
        m = {"video_name": "final.mp4", "duration_ms": 4000.0, "width": 1080, "height": 1920,
             "title": "兜底草稿", "shots": [{"start_ms": 0, "end_ms": 2000},
                                            {"start_ms": 2000, "end_ms": 2000},   # 零长：跳过
                                            {"start_ms": 2000, "end_ms": 4000}],
             "clauses": [{"text": "字幕一", "start_ms": 0, "end_ms": 1800},
                         {"text": "尾句超片尾", "start_ms": 2000, "end_ms": 9999}]}
        m.update(over)
        return m

    def test_placeholder_survives_and_substitutes_cleanly(self):
        c = jd.build_flat_content(self.manifest())
        raw = json.dumps(c, ensure_ascii=False)
        self.assertIn(jd.PLACEHOLDER, raw, "路径要留占位符，装进剪映时才改写")
        self.assertNotIn(jd.PLACEHOLDER, raw.replace(jd.PLACEHOLDER, "/draft/dir"),
                         "占位符被拆断了，替换后仍有残留")
        self.assertIn("/draft/dir/media/final.mp4", raw.replace(jd.PLACEHOLDER, "/draft/dir"))

    def test_zero_length_shots_dropped_and_timeline_clamped(self):
        c = jd.build_flat_content(self.manifest())
        video = next(t for t in c["tracks"] if t["type"] == "video")
        self.assertEqual(len(video["segments"]), 2)
        cap = c["duration"]
        for track in c["tracks"]:
            for seg in track["segments"]:
                t = seg["target_timerange"]
                self.assertLessEqual(t["start"] + t["duration"], cap)

    def test_editable_subtitle_track_only_in_no_burn_mode(self):
        """subtitles=False（成片不烧字幕）才给剪映补一条可编辑字幕轨。"""
        withsub = jd.build_flat_content(self.manifest(subtitles=True))
        without = jd.build_flat_content(self.manifest(subtitles=False))
        self.assertNotIn("text", [t["type"] for t in withsub["tracks"]])
        self.assertIn("text", [t["type"] for t in without["tracks"]])

    def test_missing_shots_still_makes_one_full_length_segment(self):
        c = jd.build_flat_content({"duration_ms": 3000.0, "video_name": "final.mp4"})
        self.assertEqual(len(c["tracks"][0]["segments"]), 1)
        self.assertEqual(c["tracks"][0]["segments"][0]["target_timerange"]["duration"], 3000 * US)


class DraftManifestIOTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="getcut-jy-"))

    def test_dump_then_load_round_trip(self):
        """清单落在成片旁边：<成片名>.draft.json（cli.py:442 传的就是这个路径）。"""
        mp4 = self.dir / "GetCut-成片.mp4"
        jd.dump_manifest(mp4.with_suffix(".draft.json"), video="final.mp4", duration_ms=6000.0,
                         title="T", shots=[{"start_ms": 0}], clauses=[{"text": "句"}],
                         sfx=["hit.mp3"], props="props.json", render_id="r1")
        self.assertTrue(mp4.with_suffix(".draft.json").is_file())
        got = jd.load_manifest(mp4)
        self.assertEqual((got["version"], got["duration_ms"], got["render_id"]), (2, 6000.0, "r1"))
        self.assertEqual((got["shots"], got["clauses"], got["sfx"]),
                         ([{"start_ms": 0}], [{"text": "句"}], ["hit.mp3"]))

    def test_missing_or_corrupt_manifest_reads_as_none(self):
        """旧成片没有清单是常态：要安静地回 None，让上层走兜底，而不是把出片流程炸掉。"""
        self.assertIsNone(jd.load_manifest(self.dir / "none.mp4"))
        (self.dir / "bad.draft.json").write_text("{不是 JSON", encoding="utf-8")
        self.assertIsNone(jd.load_manifest(self.dir / "bad.mp4"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
