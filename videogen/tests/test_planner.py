"""素材包解析与分镜节奏的离线闸门（纯函数，零 IO、零大模型、零配音）。

跑法（在 videogen/ 目录下）：
    python -m unittest discover -s tests -t tests

为什么值得锁：预备阶段与渲染阶段是两次进程内调用，Plan 靠落盘中转
（planner.py:49 那句"多缺字段都不致命"），节奏分块又直接决定客户看到的镜头切分。
这两处改坏了不会报错，只会**默默出错片**：字段丢在 JSON 往返里，或者同一个设计卡
连着弹两次、某句话根本不上屏。所以断言全部照各函数 docstring 里自己承诺的不变量写。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from videogen import planner, schemas
from videogen.planner import Clause, Plan, Shot


def spans_for(units, per_unit=2200, start=0):
    """给一串单元号造等长子句时间轴（真实配音里逗号级子句约 2.2 秒）。"""
    spans, t = {}, float(start)
    for u in units:
        spans[u] = (t, t + per_unit)
        t += per_unit
    return spans


# ---------------------------------------------------------------- Plan 往返
class PlanRoundTripTest(unittest.TestCase):
    def plan(self):
        return Plan(
            shots=[Shot(kind="footage", asset_path="images/a.jpg", sent_indexes=[0, 1],
                        start_ms=0.0, end_ms=4400.0, chapter_label="开场"),
                   Shot(kind="callout", asset_path=None, sent_indexes=[2],
                        start_ms=4400.0, end_ms=6600.0,
                        overlay={"title": "48架", "tone": "acc"})],
            clauses=[Clause("第一句", 0, 0.0, 2200.0), Clause("第二句", 0, 2200.0, 4400.0),
                     Clause("第三句", 1, 4400.0, 6600.0)],
            duration_ms=6600.0, theme={"accent": "#b4222f"}, style_pack="editorial",
            bg_asset="images/bg.jpg")

    def test_round_trip_is_lossless(self):
        p = self.plan()
        back = planner.plan_from_dict(planner.plan_to_dict(p))
        self.assertEqual(json.loads(json.dumps(planner.plan_to_dict(back))),
                         json.loads(json.dumps(planner.plan_to_dict(p))),
                         "Plan 过一道 JSON 就变样，等于渲染阶段拿到另一份分镜")

    def test_every_field_survives_the_disk_hop(self):
        p = self.plan()
        back = planner.plan_from_dict(planner.plan_to_dict(p))
        self.assertEqual(back.duration_ms, p.duration_ms)
        self.assertEqual(back.theme, p.theme)
        self.assertEqual(back.style_pack, p.style_pack)
        self.assertEqual(back.bg_asset, p.bg_asset)
        self.assertEqual([s.kind for s in back.shots], [s.kind for s in p.shots])
        self.assertEqual([s.sent_indexes for s in back.shots], [s.sent_indexes for s in p.shots])
        self.assertEqual(back.shots[1].overlay, {"title": "48架", "tone": "acc"})
        self.assertEqual(back.shots[1].asset_path, None, "None 被转成字符串会让渲染去找一个不存在的素材")
        self.assertEqual([c.text for c in back.clauses], ["第一句", "第二句", "第三句"])

    def test_empty_dict_yields_empty_plan_not_crash(self):
        back = planner.plan_from_dict({})
        self.assertEqual((back.shots, back.clauses, back.duration_ms), ([], [], 0.0))

    def test_partial_shot_json_falls_back_instead_of_losing_the_shot(self):
        back = planner.plan_from_dict({"shots": [{"sentences": [0]}]})   # kind 缺失
        self.assertEqual(len(back.shots), 1)
        self.assertEqual(back.shots[0].kind, "footage", "缺 kind 要按默认走，不能整镜头消失")

    def test_round_trip_does_not_alias_the_original(self):
        p = self.plan()
        back = planner.plan_from_dict(planner.plan_to_dict(p))
        back.shots[0].sent_indexes.append(99)
        back.theme["accent"] = "#000"
        self.assertEqual(p.shots[0].sent_indexes, [0, 1], "两份 Plan 共用同一个列表")
        self.assertEqual(p.theme["accent"], "#b4222f")


# ---------------------------------------------------------------- 节奏分块
class NormalizeRhythmTest(unittest.TestCase):
    def spec(self, sentences, asset=None, card=None):
        s = {"sentences": sentences}
        if asset:
            s["asset"] = asset
        if card:
            s["card"] = card
        return s

    def test_order_and_coverage_are_preserved(self):
        units = list(range(8))
        spans = spans_for(units)
        spec = [self.spec(units, asset="images/a.jpg")]
        out = planner.normalize_rhythm(spec, spans, units)
        flat = [u for b in out for u in b["sentences"]]
        self.assertEqual(flat, units, "重排节奏把单元重排或弄丢了")

    def test_no_block_exceeds_cap_when_units_fit(self):
        units = list(range(10))
        spans = spans_for(units, per_unit=2200)
        out = planner.normalize_rhythm([self.spec(units, asset="images/a.jpg")], spans, units)
        for b in out:
            s = b["sentences"]
            self.assertLessEqual(spans[s[-1]][1] - spans[s[0]][0], planner.SHOT_CAP_MS + 1,
                                 "还有一块超过 cap，客户看到的就是一镜到底的长镜头")

    def test_llm_missed_units_are_not_silently_filled(self):
        """模型漏讲的单元不许在这里被悄悄补上：下游"必须不重不漏"的校验该拒就拒。"""
        units = [0, 1, 2, 3]
        spans = spans_for(units)
        spec = [self.spec([0, 1], asset="images/a.jpg")]        # 2、3 没给设计
        out = planner.normalize_rhythm(spec, spans, units)
        flat = [u for b in out for u in b["sentences"]]
        self.assertEqual(sorted(set(flat)), [0, 1], "漏讲的单元被节奏重排补进来了")

    def test_block_inherits_exactly_its_head_units_design(self):
        """每块只认块首那个单元的设计：卡不能跟着尾巴复制，也不能串到别人的块上。"""
        units = list(range(6))
        spans = spans_for(units)
        spec = [self.spec([0], card={"t": "一"}, asset="images/a.jpg"),
                self.spec([1], card={"t": "二"}, asset="images/b.jpg"),
                self.spec([2], card={"t": "三"}, asset="images/c.jpg"),
                self.spec([3, 4, 5], asset="images/d.jpg")]
        cards = {u: c for u, c in ((0, "一"), (1, "二"), (2, "三"))}
        out = planner.normalize_rhythm(spec, spans, units)
        for b in out:
            head = b["sentences"][0]
            self.assertEqual(b.get("card", {}).get("t") if b.get("card") else None,
                             cards.get(head), "块的设计卡与块首单元对不上")
        seen = [b["card"]["t"] for b in out if b.get("card")]
        self.assertEqual(len(seen), len(set(seen)), "同一张设计卡出现两次，客户会连着看到同一张卡")

    def test_usable_units_absent_returns_spec_untouched(self):
        spec = [self.spec([7], asset="images/a.jpg")]
        self.assertEqual(planner.normalize_rhythm(spec, {}, [7], ), spec)
        self.assertEqual(planner.normalize_rhythm([], {}, []), [])

    def test_single_very_long_unit_stays_alone(self):
        spans = {0: (0.0, 9000.0), 1: (9000.0, 11000.0)}
        out = planner.normalize_rhythm([self.spec([0, 1], asset="images/a.jpg")], spans, [0, 1])
        self.assertEqual(out[0]["sentences"], [0], "切不动的超长单元要单独成块，别塞回上一块")


class UnitDesignTest(unittest.TestCase):
    def test_only_first_unit_inherits_full_design(self):
        got = planner._unit_design([{"sentences": [3, 4], "asset": "a.jpg",
                                     "chapterLabel": "章", "card": {"t": "x"} }])
        self.assertIn("card", got[3])
        self.assertEqual(set(got[4]), {"asset", "chapterLabel"})

    def test_dirty_sentences_are_dropped(self):
        self.assertEqual(planner._as_ints(None), [])
        self.assertEqual(planner._as_ints(["1", 2]), [1, 2])
        self.assertEqual(planner._as_ints(["一"]), [], "脏输入要安静地变成空，不能抛")
        self.assertEqual(planner._unit_design([{"sentences": "abc"}]), {})


# ---------------------------------------------------------------- 长镜头切分
class SplitLongShotsTest(unittest.TestCase):
    def test_coverage_and_order_unchanged(self):
        units = list(range(8))
        spans = spans_for(units, per_unit=2200)
        spec = [{"sentences": units, "asset": "images/a.jpg", "card": {"t": "卡"}}]
        out = planner.split_long_shots(spec, spans, cap_ms=4800)
        self.assertEqual([u for b in out for u in b["sentences"]], units, "切完不重不漏要成立")

    def test_tail_half_does_not_repeat_the_card(self):
        units = list(range(8))
        spans = spans_for(units, per_unit=2200)
        out = planner.split_long_shots(
            [{"sentences": units, "asset": "images/a.jpg", "card": {"t": "卡"}}], spans, cap_ms=4800)
        self.assertEqual(sum(1 for b in out if b.get("card")), 1, "同一张卡跟着后半段复制了一遍")
        self.assertTrue(all(b.get("asset") == "images/a.jpg" for b in out), "切完素材丢了")

    def test_short_shot_is_left_alone(self):
        spans = spans_for([0, 1], per_unit=1000)
        spec = [{"sentences": [0, 1], "asset": "a.jpg"}]
        self.assertEqual(planner.split_long_shots(spec, spans, cap_ms=4800), spec)

    def test_single_unit_shot_cannot_be_split(self):
        spans = {0: (0.0, 99000.0)}
        spec = [{"sentences": [0], "card": {"t": "卡"}}]
        self.assertEqual(planner.split_long_shots(spec, spans, cap_ms=4800), spec)

    def test_garbage_sentences_return_unchanged(self):
        spec = [{"sentences": "xyz"}, {"sentences": [1, "a"]}]
        self.assertEqual(planner.split_long_shots(spec, {1: (0.0, 100.0)}, cap_ms=1), spec)

    def test_unknown_boundary_units_return_unchanged(self):
        spec = [{"sentences": [0, 1, 2, 3]}]
        self.assertEqual(planner.split_long_shots(spec, {}, cap_ms=1), spec)


class ClauseChunksTest(unittest.TestCase):
    def test_chunks_are_contiguous_and_cover_everything(self):
        cs = [Clause(str(i), 0, i * 2200.0, (i + 1) * 2200.0) for i in range(9)]
        chunks = planner._clause_chunks(cs, 4800)
        self.assertEqual(chunks[0][0], cs[0].start_ms)
        self.assertEqual(chunks[-1][1], cs[-1].end_ms)
        for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:], strict=False):
            self.assertAlmostEqual(prev_end, next_start, places=6, msg="块之间留了空洞")

    def test_empty_input_gives_empty_output(self):
        self.assertEqual(planner._clause_chunks([], 4800), [])

    def test_one_clause_longer_than_cap_is_not_duplicated(self):
        cs = [Clause("长", 0, 0.0, 30000.0), Clause("短", 1, 30000.0, 31000.0)]
        chunks = planner._clause_chunks(cs, 4800)
        self.assertEqual(chunks[0], (0.0, 30000.0), "切不动的超长子句要原样成镜")
        self.assertEqual(len(chunks), 2)


# ---------------------------------------------------------------- 钩子标题
class HookHeadlineTest(unittest.TestCase):
    def test_dict_form_gets_brackets_not_dumped_verbatim(self):
        """getcut-bundle 投的包写的是 {"text","highlight"}；只按 str() 转会把字典打进成片标题。"""
        line = schemas._hook_line({"text": "美国批48架F35给沙特", "highlight": "48架"})
        self.assertEqual(line, "美国批[[48架]]F35给沙特")
        self.assertNotIn("{'", line)

    def test_explicit_index_wins_when_text_repeats(self):
        line = schemas._hook_line({"text": "涨涨涨", "highlight": "涨", "highlight_at": 2})
        self.assertEqual(line, "涨涨[[涨]]")

    def test_out_of_range_index_falls_back_to_search(self):
        line = schemas._hook_line({"text": "美联储加息", "highlight": "加息", "highlight_at": 99})
        self.assertEqual(line, "美联储[[加息]]")

    def test_already_bracketed_or_blank_highlight_pass_through(self):
        self.assertEqual(schemas._hook_line({"text": "已有[[高亮]]", "highlight": "高亮"}), "已有[[高亮]]")
        self.assertEqual(schemas._hook_line({"text": "没有高亮", "highlight": ""}), "没有高亮")
        self.assertEqual(schemas._hook_line({"text": "找不到就别切", "highlight": "别人"}), "找不到就别切")

    def test_non_dict_items_stay_strings(self):
        self.assertEqual(schemas._hook_line("纯字符串[[就行]]"), "纯字符串[[就行]]")
        self.assertEqual(schemas._hook_line(7), "7")

    def test_spans_point_at_the_highlight_in_the_plain_line(self):
        h = schemas.HookHeadline.parse({"lines": ["美国批[[48架]]F35给[[沙特]]"]})
        plain = h.plain(h.lines[0])
        self.assertEqual(plain, "美国批48架F35给沙特")
        for a, b in h.highlight_spans(h.lines[0]):
            self.assertIn(plain[a:b], {"48架", "沙特"}, "高亮下标错位，成片会把别的字涂成红色")

    def test_headline_tolerates_missing_lines_key(self):
        self.assertEqual(schemas.HookHeadline.parse({}).lines, [])


class ContentManifestTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="videogen-plan-"))

    def write(self, name, obj):
        p = self.dir / name
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return p

    def test_content_optional_keys_default_cleanly(self):
        c = schemas.Content.load(self.write("content.json", {"title": "T", "script": "句。"}))
        self.assertEqual((c.schema_version, c.sources, c.pronunciations, c.notes, c.hook_headline),
                         (1, [], {}, "", None))

    def test_content_missing_script_fails_loud(self):
        """缺口的包要当场说清楚，不能出一版没有口播的片。"""
        with self.assertRaises(KeyError):
            schemas.Content.load(self.write("content.json", {"title": "T"}))

    def test_manifest_ignores_unknown_asset_fields(self):
        m = schemas.Manifest.load(self.write("manifest.json", {"assets": [
            {"file": "images/a.jpg", "kind": "image", "summary": "s", "未来字段": 1}]}))
        self.assertEqual((m.assets[0].file, m.assets[0].kind, m.assets[0].tags),
                         ("images/a.jpg", "image", []))

    def test_manifest_without_assets_is_empty_not_crash(self):
        self.assertEqual(schemas.Manifest.load(self.write("manifest.json", {})).assets, [])


class CloneGuardTest(unittest.TestCase):
    def test_empty_clauses_or_empty_slots_say_so_instead_of_index_error(self):
        """复刻图纸是浏览器交上来的外部输入：以前空 slots 会在这里抛 IndexError，
        客户只看到任务失败、错误是一句看不懂的 traceback。"""
        with self.assertRaises(ValueError) as cm:
            planner.build_plan_clone(None, [], {"slots": [{"start": 0, "end": 1}]}, None, None)
        self.assertIn("子句", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            planner.build_plan_clone(None, [Clause("句子。", 0, 0.0, 2000.0)],
                                     {"slots": []}, None, None)
        self.assertIn("槽位", str(cm.exception))

    def test_slot_missing_fields_name_the_slot(self):
        clauses = [Clause("第一句。", 0, 0.0, 2000.0), Clause("第二句。", 1, 2000.0, 4000.0)]
        with self.assertRaises(ValueError) as cm:
            planner.build_plan_clone(None, clauses, {"ref_total": 4.0, "slots": [
                {"kind": "footage", "start": 0, "end": 2}, {"kind": "footage", "start": 2}]},
                                     None, None)
        msg = str(cm.exception)
        self.assertIn("第 2 个槽位", msg, "报错要说出是哪个槽位")
        self.assertIn("end", msg)

    def test_shot_seams_are_closed_without_gaps(self):
        c = planner.plan_to_dict(planner.build_plan_clone(
            None, [Clause("第一句。", 0, 0.0, 2000.0), Clause("第二句。", 1, 2000.0, 4000.0)],
            {"ref_total": 4.0, "slots": [{"kind": "footage", "start": 0, "end": 2},
                                         {"kind": "footage", "start": 2, "end": 4}]},
            None, None))
        shots = [s for s in c["shots"] if s["end_ms"] > s["start_ms"]]
        self.assertGreaterEqual(len(shots), 2)
        for a, b in zip(shots, shots[1:], strict=False):
            self.assertAlmostEqual(a["end_ms"], b["start_ms"], places=6, msg="镜头之间留了缝")


if __name__ == "__main__":
    unittest.main(verbosity=2)
