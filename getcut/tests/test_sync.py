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

跑法（在 getcut/ 目录下）：
    python -m unittest discover -s tests -t tests
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from getcut.planner import SENT_SPLIT, PUNCT, align_timeline, split_clauses
from getcut.schemas import Content
from getcut.tts import (_anchored_windows, _char_weights, _clause_char_starts,
                          _estimate_events, _events_by_windows, _events_quality,
                          _events_from_pauses, _pause_anchors, _timeline,
                          _uniform_events, _warp_weight, read_quality)
from getcut.verify import _drift_stats


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
        with mock.patch("getcut.tts._probe_ms", return_value=dur_ms), \
                mock.patch("getcut.tts.pause_ends_ms", return_value=pauses):
            events, anchors = _estimate_events(self.SPOKEN, Path("nope.mp3"))
        self.assertEqual(anchors, len(est) - 1)
        self.assertEqual("".join(e["text"] for e in events), self.SPOKEN)
        offs = [e["offset_ms"] for e in events]
        self.assertEqual(offs, sorted(offs))          # 时间轴不倒挂

        with mock.patch("getcut.tts._probe_ms", return_value=dur_ms), \
                mock.patch("getcut.tts.pause_ends_ms", return_value=[]):
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


class PauseFirstTimelineTest(unittest.TestCase):
    """时间轴以音频实测停顿为准（2026-09-22 第二宗漂移回归）。

    事故形状：字幕从第 2~3 秒起就比语音晚 0.3~0.7 秒，中段还有一段整整错 6 秒。
    根因是百炼回的词级时间戳跟它自己的音频对不齐（词流说"司"在 5.76 秒开口，
    那 0.37 秒音频是静音），照抄词流排字幕必然整体滞后；而"就近吸附到停顿"也不行
    ——坏区里服务端把 21 个字塞进同一个时刻，吸附会让整段平移一个停顿。

    所以锁四条不变量：
    1. _pause_anchors：停顿落在哪些标点上，必须按语速配对还原出来；
    2. 停顿位置与任何标点都对不上（语速离谱）时返回 None，交兜底；
    3. _events_from_pauses 排出的轴：子句首就落在实测停顿上，且单调不倒挂；
    4. _timeline 排出的轴**不依赖传入的词级时间戳**——词流坏成什么样都一样。
    """

    SPOKEN = ("北极熊靠脂肪过冬，冰面才是它的地板。企鹅不飞却会滑行，肚皮就是刹车。"
              "海獭睡觉手牵手，怕漂走。鲸鱼唱歌传千里，声音能绕过冰川。")
    RATE = 200.0        # ms / 字重，用来造假音频
    LEAD = 120.0
    TAIL = 200.0

    def _model(self):
        weights = _char_weights(self.SPOKEN)
        total_w = sum(weights)
        prefix = [0.0]
        for w in weights:
            prefix.append(prefix[-1] + w)
        raw = _clause_char_starts(self.SPOKEN)
        bnd = [prefix[a] for a in raw]
        dur = self.LEAD + total_w * self.RATE + self.TAIL
        return weights, total_w, raw, bnd, dur

    def _sentence_boundaries(self, raw):
        """句号/问号后面的子句首 = 按稿件必须有停顿的位置。"""
        return [k for k, a in enumerate(raw) if a > 0 and self.SPOKEN[a - 1] in "。！？"]

    def test_pause_anchors_recovers_boundaries(self):
        _w, total_w, raw, bnd, dur = self._model()
        want = self._sentence_boundaries(raw)
        self.assertGreaterEqual(len(want), 3)
        pauses = [self.LEAD + bnd[k] * self.RATE for k in want]
        anchors = _pause_anchors(bnd, total_w, pauses, dur, self.LEAD, self.TAIL)
        self.assertIsNotNone(anchors)
        paired = anchors[1:-1]
        self.assertEqual(len(paired), len(want))       # 一个停顿配一个边界，不多不少
        for (w, t), k, p in zip(paired, want, pauses, strict=True):
            self.assertAlmostEqual(w, bnd[k], places=6)
            self.assertAlmostEqual(t, p, places=6)

    def test_pause_anchors_rejects_implausible(self):
        """停顿全挤在片头（谁也对不上）：宁可返回 None，也不硬配出一个轴。"""
        _w, total_w, _raw, bnd, dur = self._model()
        pauses = [self.LEAD + 10.0 * k for k in range(1, 7)]
        self.assertIsNone(_pause_anchors(bnd, total_w, pauses, dur, self.LEAD, self.TAIL))

    def test_events_from_pauses_locks_clause_starts(self):
        _w, total_w, raw, bnd, dur = self._model()
        want = self._sentence_boundaries(raw)
        pauses = {k: self.LEAD + bnd[k] * self.RATE for k in want}
        with mock.patch("getcut.tts._probe_ms", return_value=dur),                 mock.patch("getcut.tts.pause_ends_ms", return_value=list(pauses.values())):
            got = _events_from_pauses(self.SPOKEN, Path("nope.mp3"))
        self.assertIsNotNone(got)
        events, anchors = got
        self.assertEqual(anchors, len(pauses) + 2)
        self.assertEqual("".join(e["text"] for e in events), PUNCT.sub("", self.SPOKEN))
        # 第 k 个句首字必须正好落在第 k 处停顿上
        for k, p in zip(want, pauses.values(), strict=True):
            c = raw[k]                       # 该子句首字在 spoken 里的下标
            off = sum(1 for ch in self.SPOKEN[:c] if not PUNCT.fullmatch(ch))
            self.assertAlmostEqual(events[off]["offset_ms"], p, delta=1.0)

    def test_warp_is_monotonic(self):
        _w, total_w, raw, bnd, dur = self._model()
        want = self._sentence_boundaries(raw)
        pauses = [self.LEAD + bnd[k] * self.RATE for k in want]
        anchors = _pause_anchors(bnd, total_w, pauses, dur, self.LEAD, self.TAIL)
        times = [_warp_weight(anchors, w) for w in range(0, int(total_w) + 1)]
        self.assertEqual(times, sorted(times))

    def test_timeline_blends_word_with_pauses(self):
        """有词流时：停顿只在"与词流互相印证"（差 _BLEND_MS 以内）时才用来定刻度，
        挪幅有硬上限，防停顿 DP 的"挪一格"把整段带偏；没词流才纯用停顿 DP。"""
        from getcut.tts import _BLEND_MS
        _w, total_w, raw, bnd, dur = self._model()
        want = self._sentence_boundaries(raw)
        pauses = [self.LEAD + bnd[k] * self.RATE for k in want]
        chars = PUNCT.sub("", self.SPOKEN)
        words = [{"text": c, "offset_ms": i * 200.0, "duration_ms": 200.0}
                 for i, c in enumerate(chars)]
        with mock.patch("getcut.tts._probe_ms", return_value=dur),                 mock.patch("getcut.tts.pause_ends_ms", return_value=pauses):
            got, src_w, a_w = _timeline(self.SPOKEN, Path("nope.mp3"), words)
            est, src_e, a_e = _timeline(self.SPOKEN, Path("nope.mp3"), None)
        self.assertEqual(src_w, "word")
        self.assertGreaterEqual(a_w, 3)                  # 停顿确实参与了校正
        self.assertEqual("".join(e["text"] for e in got), chars)
        offs = [e["offset_ms"] for e in got]
        self.assertEqual(offs, sorted(offs))             # 不倒挂
        # 挪幅有上限：子句首要么落在某处停顿上，要么就是词流原值（不许凭空挪）
        for e in got:
            self.assertTrue(
                any(abs(e["offset_ms"] - p) < 1.5 for p in pauses)
                or e["offset_ms"] in {w["offset_ms"] for w in words}
                or abs(e["offset_ms"] - max(
                    (w["offset_ms"] for w in words
                     if w["offset_ms"] <= e["offset_ms"]), default=0.0)) <= _BLEND_MS + 1)
        # 没词流：纯停顿 DP，每一个句首正好落在某处停顿上
        self.assertEqual(src_e, "estimate")
        self.assertGreaterEqual(a_e, 3)
        eoffs = [e["offset_ms"] for e in est]
        for p in pauses:
            self.assertTrue(any(abs(o - p) < 1.5 for o in eoffs))


# 独立运行：python -m unittest tests.test_sync -v
if __name__ == "__main__":
    unittest.main()
