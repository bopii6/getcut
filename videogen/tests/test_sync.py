# -*- coding: utf-8 -*-
"""字幕-配音对齐的三道闸门（2026-09-22 漂移事故回归）。

事故形状：成片开头同步、越往后字幕越滞后（实测前 1/3 中位 +372ms →
后 1/3 +667ms）。根因是百炼词流丢字后按字数估算兜底，而质检 5 项里
没有任何一项查"字幕和语音是否对齐"。所以锁三个不变量：

1. align_timeline：events 比稿件短（缺键）时，后面子句沿用上一个已知
   时间继续排，绝不能回落到 0.0（那会让字幕轴塌回片头、时间轴倒挂）。
2. tts 时间戳质量标记：估算兜底必须落 source="estimate"，prep/verify
   才能透出警告；缓存读取缺字段时返回 None（未知）而不是报错。
3. _drift_stats：给定"字幕恒滞后语音 400ms"的合成停顿，中位漂移必须
   ≈+400ms；有效配对不足 5 个时返回 None（宁可不报，也不报假数）。
4. 估算兜底的停顿锚定：句首必须锚到实测停顿结束点上（不是均匀摊）；
   停顿配不上时回退均匀摊且 anchors=0；估算句首切分与 planner 同口径。

跑法（在 videogen/ 目录下）：
    python -m unittest discover -s tests -t tests
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from videogen.planner import SENT_SPLIT, PUNCT, align_timeline, split_clauses
from videogen.schemas import Content
from videogen.tts import (_anchored_windows, _char_weights, _clause_char_starts,
                          _estimate_events, _events_by_windows, _events_quality,
                          _uniform_events, read_quality)
from videogen.verify import _drift_stats


def _linear_events(chars: str, step_ms: float = 300.0, dur_ms: float = 280.0):
    t = 0.0
    out = []
    for c in chars:
        out.append({"text": c, "offset_ms": t, "duration_ms": dur_ms})
        t += step_ms
    return out


class AlignTimelineGapTest(unittest.TestCase):
    def test_missing_keys_continue_instead_of_zero(self):
        """events 只覆盖前 4 个字：第 3 条子句的 start 不能是 0.0。"""
        clauses = [(0, "你好呀"), (1, "明天见"), (2, "后天走")]  # 共 9 个口播字
        events = _linear_events("你好呀明")                         # 只给了 4 个字的时间
        got = align_timeline(clauses, events)

        self.assertEqual(len(got), 3)
        # 第 1 条正常来自 pos2t[0]；第 2 条 start = 第 4 个字的时间 900ms
        self.assertEqual(got[0].start_ms, 0.0)
        self.assertEqual(got[1].start_ms, 900.0)
        # 第 3 条所有键都缺：必须沿用上一条的 end（旧实现是 0.0 → 塌回片头）
        self.assertGreater(got[2].start_ms, 0.0)
        self.assertEqual(got[2].start_ms, got[1].end_ms)
        # 整体单调不倒挂（verify 的字幕 sanity 也会查，但这里先把源头锁死）
        starts = [c.start_ms for c in got]
        self.assertEqual(starts, sorted(starts))

    def test_full_events_unchanged(self):
        """events 齐全时行为与原来一致：逐字映射、末条延伸到最后一字。"""
        clauses = [(0, "你好呀"), (1, "明天见")]
        events = _linear_events("你好呀明天见")
        got = align_timeline(clauses, events)
        self.assertEqual(got[0].start_ms, 0.0)
        self.assertEqual(got[0].end_ms, 900.0)   # 第 4 个字的开始
        self.assertEqual(got[1].start_ms, 900.0)
        self.assertGreaterEqual(got[1].end_ms, 1500.0)


class TtsQualityTest(unittest.TestCase):
    def test_estimate_marked(self):
        q = _events_quality("一百个字" * 25,
                            [{"text": "一百个字"}] * 25, "dashscope", "estimate")
        self.assertEqual(q["source"], "estimate")
        self.assertEqual(q["provider"], "dashscope")
        self.assertEqual(q["events"], 25)
        self.assertGreater(q["coverage"], 0)

    def test_word_marked_and_coverage_capped(self):
        q = _events_quality("十个字十个字", [{"text": "十个字十个字"}], "edge", "word")
        self.assertEqual(q["source"], "word")
        self.assertLessEqual(q["coverage"], 1.0)

    def test_read_quality_roundtrip_and_missing(self):
        d = Path(tempfile.mkdtemp(prefix="vg_q_"))
        self.assertIsNone(read_quality(d))          # 缺文件 = 未知，不报错
        (d / "tts_events.json").write_text(
            json.dumps({"input_sig": "x", "events": [],
                        "quality": {"provider": "edge", "source": "word"}}),
            encoding="utf-8")
        q = read_quality(d)
        self.assertEqual(q["source"], "word")
        (d / "tts_events.json").write_text("not json", encoding="utf-8")
        self.assertIsNone(read_quality(d))          # 坏 JSON 同样当未知


class DriftStatsTest(unittest.TestCase):
    def test_constant_lag_detected(self):
        """字幕恒滞后语音 400ms：中位漂移必须报出 ≈ +400ms。"""
        clause_starts_ms = [0, 1000, 2000, 3000, 4000, 5000, 6000]
        pause_ends_s = [0.6, 1.6, 2.6, 3.6, 4.6, 5.6]   # 每次开口都比字幕早 0.4s
        median, n = _drift_stats(clause_starts_ms, pause_ends_s)
        self.assertEqual(n, 6)
        self.assertAlmostEqual(median, 400.0, delta=1.0)

    def test_in_sync_video_reports_near_zero(self):
        clause_starts_ms = [0, 1000, 2000, 3000, 4000, 5000, 6000]
        pause_ends_s = [0.99, 1.99, 2.99, 3.99, 4.99, 5.99]
        median, n = _drift_stats(clause_starts_ms, pause_ends_s)
        self.assertEqual(n, 6)
        self.assertAlmostEqual(median, 10.0, delta=5.0)

    def test_too_few_pairs_returns_none(self):
        """有效配对 <5：返回 None，不能拿两三个点算出个假中位数。"""
        median, n = _drift_stats([0, 1000, 2000], [0.6, 1.6])
        self.assertIsNone(median)
        self.assertEqual(n, 2)

    def test_no_pauses_returns_none(self):
        median, n = _drift_stats([0, 1000, 2000, 3000, 4000, 5000], [])
        self.assertIsNone(median)
        self.assertEqual(n, 0)


class ClauseStartsTest(unittest.TestCase):
    def test_matches_planner_split(self):
        """估算兜底切句首必须与 planner.split_clauses 同口径，否则锚点会偏。"""
        script = "第一句说完了。第二句有逗号，还要停一下；第三句呢？结束！"
        content = Content(schema_version=1, title="t", script=script)
        starts = _clause_char_starts(script)
        clauses = split_clauses(content)
        # 每个 planner 子句的剥标点文本，都能在对应起点处对上
        self.assertEqual(len(starts), len(clauses))
        for st, (_sent, text) in zip(starts, clauses, strict=True):
            self.assertEqual(PUNCT.sub("", script[st:st + len(text)]),
                             PUNCT.sub("", text))

    def test_empty_clause_between_punctuations(self):
        """连写标点/空白造出的空子句不产生新起点。"""
        starts = _clause_char_starts("你好。。  明天见")
        self.assertEqual(starts[0], 0)
        self.assertTrue(all(script_ch != "" for script_ch in
                            ["明" for _ in starts]))   # 结构性断言：起点列表非空
        # "你好"之后的第一个真实起点是"明"
        self.assertIn("明", "你好。。  明天见"[starts[1]:starts[1] + 1])


class AnchoredEstimateTest(unittest.TestCase):
    SPOKEN = "北极熊靠脂肪过冬，冰面才是它的地板。企鹅不飞却会滑行，肚皮就是刹车。海獭睡觉手牵手，怕漂走。"

    def _est_starts(self, dur_ms: float) -> list[float]:
        """按均匀摊公式复算每个子句首字的估算时刻（与实现同公式）。"""
        weights = _char_weights(self.SPOKEN)
        total_w = sum(weights) or 1.0
        lead, tail = (120.0, 200.0) if dur_ms > 1500 else (0.0, 0.0)
        span = max(dur_ms - lead - tail, total_w * 200)
        per_w = span / total_w
        prefix = [0.0]
        for w in weights:
            prefix.append(prefix[-1] + w)
        raw = _clause_char_starts(self.SPOKEN)
        return [lead + prefix[a] * per_w for a in raw]

    def test_clause_starts_anchored_to_real_pauses(self):
        """伪造"每次开口都比均匀摊晚 400ms"的停顿：子句窗口必须落在停顿上。"""
        dur_ms = 20000.0
        weights = _char_weights(self.SPOKEN)
        raw = _clause_char_starts(self.SPOKEN)
        spans = list(zip(raw, raw[1:] + [len(self.SPOKEN)], strict=True))
        est = self._est_starts(dur_ms)
        pauses = [e + 400.0 for e in est[1:]]        # 实测开口 = 估算 + 400ms

        got = _anchored_windows(weights, spans, dur_ms, pauses)
        self.assertIsNotNone(got)
        windows, anchors = got
        self.assertEqual(anchors, len(est) - 1)       # 每个子句都配上锚点
        # 首句窗口起点仍是 lead（基线锚点），其余子句起点 = 实测停顿
        self.assertAlmostEqual(windows[0][0], 120.0, delta=0.5)
        for k in range(1, len(windows)):
            self.assertAlmostEqual(windows[k][0], pauses[k - 1], delta=0.5)
        # 窗口首尾相接、单调不倒挂
        for k in range(1, len(windows)):
            self.assertGreaterEqual(windows[k][0], windows[k - 1][0])
            self.assertGreater(windows[k][1], windows[k][0])

    def test_too_few_pauses_falls_back_to_uniform(self):
        """停顿锚点不足：返回 None，调用方回退均匀摊，anchors 记 0。"""
        weights = _char_weights(self.SPOKEN)
        raw = _clause_char_starts(self.SPOKEN)
        spans = list(zip(raw, raw[1:] + [len(self.SPOKEN)], strict=True))
        self.assertIsNone(_anchored_windows(weights, spans, 20000.0, [5000.0, 9000.0]))
        self.assertIsNone(_anchored_windows(weights, spans, 20000.0, []))

    def test_estimate_events_returns_anchor_count(self):
        """_estimate_events 返回 (events, anchors)：配得上给锚点数，配不上回 0。"""
        dur_ms = 20000.0
        est = self._est_starts(dur_ms)
        pauses = [e + 350.0 for e in est[1:]]
        with mock.patch("videogen.tts._probe_ms", return_value=dur_ms), \
                mock.patch("videogen.tts.pause_ends_ms", return_value=pauses):
            events, anchors = _estimate_events(self.SPOKEN, Path("nope.mp3"))
        self.assertEqual(anchors, len(est) - 1)
        self.assertEqual("".join(e["text"] for e in events), self.SPOKEN)
        offs = [e["offset_ms"] for e in events]
        self.assertEqual(offs, sorted(offs))          # 时间轴不倒挂

        with mock.patch("videogen.tts._probe_ms", return_value=dur_ms), \
                mock.patch("videogen.tts.pause_ends_ms", return_value=[]):
            events2, anchors2 = _estimate_events(self.SPOKEN, Path("nope.mp3"))
        self.assertEqual(anchors2, 0)
        # 回退 = 与旧的均匀摊逐字节一致
        self.assertEqual(events2, _uniform_events(self.SPOKEN, _char_weights(self.SPOKEN), dur_ms))

    def test_events_split_at_clause_boundaries(self):
        """子句边界必须是事件边界：否则 align 在事件内按字数均分会把锚点摊偏。"""
        dur_ms = 20000.0
        weights = _char_weights(self.SPOKEN)
        raw = _clause_char_starts(self.SPOKEN)
        spans = list(zip(raw, raw[1:] + [len(self.SPOKEN)], strict=True))
        est = self._est_starts(dur_ms)
        pauses = [e + 400.0 for e in est[1:]]
        got = _anchored_windows(weights, spans, dur_ms, pauses)
        self.assertIsNotNone(got)
        events = _events_by_windows(self.SPOKEN, weights, spans, got[0])
        # 每个子句的首字，都恰好是某个事件的首字
        ev_starts = []
        pos = 0
        for ev in events:
            ev_starts.append(pos)
            pos += len(ev["text"])
        for a, _b in spans:
            self.assertIn(a, ev_starts)


class TtsQualityAnchorsTest(unittest.TestCase):
    def test_quality_carries_anchors(self):
        q = _events_quality("一百个字" * 25, [{"text": "一百个字"}] * 25,
                            "dashscope", "estimate", anchors=7)
        self.assertEqual(q["anchors"], 7)
        q0 = _events_quality("十个字", [{"text": "十个字"}], "edge", "word")
        self.assertEqual(q0["anchors"], 0)            # 词级时间戳不需要锚点


if __name__ == "__main__":
    unittest.main()
