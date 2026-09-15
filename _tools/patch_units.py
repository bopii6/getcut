#!/usr/bin/env python3
"""子句级分镜单元：让镜头可以做到 3-5 秒（原先以整句为单位，一说就是 7 秒）。"""
from pathlib import Path

# ---------- planner：新增 clause_units + build_plan_llm 支持单元制 ----------
p = Path(r'E:/短视频生成/videogen/videogen/planner.py')
s = p.read_text(encoding='utf-8')

old = '''def sentence_spans(clauses):'''
new = '''def clause_units(clauses):
    """把子句作为分镜最小单元：{index, text, start, end, sent}。

    导演可以把 1-3 个子句组成一个镜头 → 镜头时长可控在 3-5 秒。
    """
    return [{"index": i, "text": c.text, "start": c.start_ms, "end": c.end_ms, "sent": c.sent_index}
            for i, c in enumerate(clauses)]


def unit_spans(units):
    """unit_index -> [start_ms, end_ms, text]"""
    return {u["index"]: [u["start"], u["end"], u["text"]] for u in units}


def sentence_spans(clauses):'''
assert old in s, "clause_units anchor"
s = s.replace(old, new, 1)

# build_plan_llm 支持传入 spans/interior/title/quote（单元制）
old2 = '''def build_plan_llm(content: Content, manifest: Manifest, clauses, shots_spec) -> Plan | None:
    """Construct a Plan from the LLM director's shot list, with validation.
    Returns None when the spec fails validation (caller falls back to rules)."""
    spans = sentence_spans(clauses)
    ids = sorted(spans)
    if len(ids) < 3 or not shots_spec:
        return None
    interior = ids[1:-1]
    n_assets = len(manifest.assets)'''
new2 = '''def build_plan_llm(content: Content, manifest: Manifest, clauses, shots_spec,
                   spans=None, interior=None, edge_spans=None) -> Plan | None:
    """Construct a Plan from the LLM director's shot list, with validation.

    spans/interior/edge_spans：可传入"子句单元"制的切分（镜头可细化到 3-5 秒）；
    不传则退回整句制。edge_spans = (首句span, 末句span) 用于片头/金句卡。
    Returns None when the spec fails validation (caller falls back to rules)."""
    if spans is None:
        spans = sentence_spans(clauses)
        ids_all = sorted(spans)
        if len(ids_all) < 3:
            return None
        interior = ids_all[1:-1]
        edge_spans = (spans[ids_all[0]], spans[ids_all[-1]])
    ids = sorted(spans)
    if not ids or not shots_spec:
        return None
    n_assets = len(manifest.assets)'''
assert old2 in s, "build_plan_llm head anchor"
s = s.replace(old2, new2, 1)

# 片头/片尾构建改用 edge_spans
old3 = '''    plan = Plan()
    assets = manifest.assets
    shot_list: list[Shot] = []
    shot_list.append(Shot(kind="title_card", asset_path=None, sent_indexes=[ids[0]],
                          start_ms=spans[ids[0]][0], end_ms=spans[ids[0]][1]))'''
new3 = '''    plan = Plan()
    assets = manifest.assets
    shot_list: list[Shot] = []
    first_span, last_span = edge_spans if edge_spans else (spans[ids[0]], spans[ids[-1]])
    shot_list.append(Shot(kind="title_card", asset_path=None, sent_indexes=[],
                          start_ms=first_span[0], end_ms=first_span[1]))'''
assert old3 in s, "title card anchor"
s = s.replace(old3, new3, 1)

old4 = '''    last = ids[-1]
    shot_list.append(Shot(kind="quote_card", asset_path=None, sent_indexes=[last],
                          start_ms=max(shot_list[-1].end_ms, spans[last][0]), end_ms=spans[last][1]))'''
new4 = '''    shot_list.append(Shot(kind="quote_card", asset_path=None, sent_indexes=[],
                          start_ms=max(shot_list[-1].end_ms, last_span[0]), end_ms=last_span[1]))'''
assert old4 in s, "quote card anchor"
s = s.replace(old4, new4, 1)

p.write_text(s, encoding='utf-8')
print("✓ planner: 子句单元制（含片头/片尾改用 edge_spans）")

# ---------- cli：传子句单元 ----------
c = Path(r'E:/短视频生成/videogen/videogen/cli.py')
s2 = c.read_text(encoding='utf-8')
old5 = '''    spans = sentence_spans(clauses)
    ids = sorted(spans)
    sent_payload = [{"index": i, "text": spans[i][2]} for i in ids[1:-1]]'''
new5 = '''    # 子句单元制：导演按 1-3 个子句成镜，镜头可细到 3-5 秒（整句制最短也要 6-8 秒）
    units = clause_units(clauses)
    u_spans = unit_spans(units)
    s_spans = sentence_spans(clauses)
    s_ids = sorted(s_spans)
    edge = (s_spans[s_ids[0]], s_spans[s_ids[-1]]) if len(s_ids) >= 2 else None
    skip_sents = {s_ids[0], s_ids[-1]} if len(s_ids) >= 2 else set()
    interior_units = [u["index"] for u in units if u["sent"] not in skip_sents]
    sent_payload = [{"index": u["index"], "text": u["text"]} for u in units if u["sent"] not in skip_sents]'''
assert old5 in s2, "cli unit anchor"
s2 = s2.replace(old5, new5, 1)

old6 = '''        spec = llm.design_shots(content.script, sent_payload, asset_payload)
        plan = build_plan_llm(content, manifest, clauses, spec["shots"]) if spec else None'''
new6 = '''        spec = llm.design_shots(content.script, sent_payload, asset_payload)
        plan = build_plan_llm(content, manifest, clauses, spec["shots"],
                              spans=u_spans, interior=interior_units,
                              edge_spans=edge) if spec else None'''
assert old6 in s2, "cli call anchor"
s2 = s2.replace(old6, new6, 1)

s2 = s2.replace("from .planner import (align_timeline, build_plan, build_plan_clone, build_plan_llm,\n                      split_clauses, sentence_spans)",
                "from .planner import (align_timeline, build_plan, build_plan_clone, build_plan_llm,\n                      clause_units, split_clauses, sentence_spans, unit_spans)")
c.write_text(s2, encoding='utf-8')
print("✓ cli: 改传子句单元")

# ---------- llm：提示词改为子句单元 + 更明确的节奏目标 ----------
l = Path(r'E:/短视频生成/videogen/videogen/llm.py')
s3 = l.read_text(encoding='utf-8')
old7 = '''            "把句子按语义连贯分组为镜头，每组1-2句，按顺序覆盖所有句子且不重叠",'''
new7 = '''            "输入是**子句单元**（逗号级短句，各带 index）：把 1-3 个语义连贯的子句组成一个镜头，"
            "按顺序覆盖所有单元且不重叠。永远不要把一个单元拆开跨镜头",
            "节奏：普通镜头配 1-2 个单元（约 3-5 秒），重要转折可用 3 个；"
            "目标不是句号对齐，而是每 3-5 秒换一次画面——全片镜头数应为 18-26 个",'''
assert old7 in s3, "llm unit rule anchor"
s3 = s3.replace(old7, new7, 1)

# 风格包里的节奏要求同步（子句单位）
s3 = s3.replace('"节奏硬要求": "按所选风格包的镜头时长目标分组句子——data/opinion 每镜 1 句、3-4 秒；"\n                        "profile/investigation 每镜 1-2 句、4-6 秒。全片镜头数随之上升（90 秒片约 20-26 镜）",',
                '"节奏硬要求": "data/opinion 每镜 1-2 个子句单元（3-4 秒）；profile/investigation 每镜 2 个单元（4-6 秒）。"\n                        "90 秒片总镜头数应为 18-26 个；宁可多切镜头，也不要出现超过 6 秒不换画面",')
l.write_text(s3, encoding='utf-8')
print("✓ llm: 导演提示词改为子句单元 + 3-5 秒节奏硬要求")
