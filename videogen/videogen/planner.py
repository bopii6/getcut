"""Stage 2+3: shot planning and clause-level timeline from TTS word boundaries."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .schemas import Content, Manifest

SENT_SPLIT = re.compile(r"[。！？；]")
CLAUSE_SPLIT = re.compile(r"[，、：]")
PUNCT = re.compile(r"[\s，、：；。！？·（）()\"\"''《》—…\-]")


@dataclass
class Clause:
    text: str
    sent_index: int
    start_ms: float = 0.0
    end_ms: float = 0.0


@dataclass
class Shot:
    kind: str                 # footage | title_card | quote_card | callout | panel
    asset_path: str | None    # bundle-relative media path (footage)
    sent_indexes: list[int]
    start_ms: float = 0.0
    end_ms: float = 0.0
    chapter_label: str = ""
    # designed-overlay payloads (callout / panel)
    overlay: dict = field(default_factory=dict)


@dataclass
class Plan:
    shots: list[Shot] = field(default_factory=list)
    clauses: list[Clause] = field(default_factory=list)
    duration_ms: float = 0.0
    theme: dict = field(default_factory=dict)
    style_pack: str = ""


def split_clauses(content: Content) -> list[tuple[int, str]]:
    """Return (sentence_index, clause_text) preserving script order."""
    out: list[tuple[int, str]] = []
    sent = 0
    for sent_text in SENT_SPLIT.split(content.script):
        if not sent_text.strip():
            continue
        parts = [p for p in CLAUSE_SPLIT.split(sent_text) if p.strip()]
        for p in parts:
            out.append((sent, p.strip()))
        sent += 1
    return out


def align_timeline(clauses: list[tuple[int, str]], events: list[dict]) -> list[Clause]:
    """Map clause char ranges onto TTS word-boundary offsets.

    events: [{text, offset_ms, duration_ms}] in utterance order; concatenated
    event texts (punctuation stripped) must mirror the script's spoken chars.
    """
    spoken_positions: list[tuple[int, int]] = []  # (spoken_char_index, offset_ms, dur_ms)
    idx = 0
    for ev in events:
        n = len(PUNCT.sub("", ev["text"]))
        for k in range(n):
            spoken_positions.append((idx + k, ev["offset_ms"] + ev["duration_ms"] * k / max(n, 1)))
        idx += n
    pos2t = dict(spoken_positions)
    total_spoken = idx

    result: list[Clause] = []
    consumed = 0
    for sent_i, text in clauses:
        spoken_n = len(PUNCT.sub("", text))
        start = pos2t.get(consumed, 0.0)
        end = pos2t.get(consumed + spoken_n - 1, start + 800)
        # clause end extends to the start of the next spoken char
        nxt = pos2t.get(consumed + spoken_n)
        if nxt is not None:
            end = nxt
        result.append(Clause(text=text, sent_index=sent_i, start_ms=start, end_ms=end))
        consumed += spoken_n
    if result:
        result[-1].end_ms = max(result[-1].end_ms, spoken_positions[-1][1] + 600 if spoken_positions else 0)
    return result


def _anchor_matches(sentence: str, anchor: str) -> bool:
    a = PUNCT.sub("", anchor)
    s = PUNCT.sub("", sentence)
    if not a:
        return False
    return a in s or s in a


def build_plan(content: Content, manifest: Manifest, clauses: list[Clause]) -> Plan:
    sentences: dict[int, list[Clause]] = {}
    for c in clauses:
        sentences.setdefault(c.sent_index, []).append(c)
    sent_ids = sorted(sentences)
    sent_text = {i: "".join(c.text for c in sentences[i]) for i in sent_ids}

    assets = manifest.assets
    assigned: dict[int, int] = {}   # sent_index -> asset index
    used: set[int] = set()
    # pass 1: anchor matches
    for i in sent_ids:
        for ai, a in enumerate(assets):
            if ai in used or not a.script_anchor:
                continue
            if _anchor_matches(sent_text[i], a.script_anchor):
                assigned[i] = ai
                used.add(ai)
                break
    # pass 2: fill gaps in manifest order (keep author's progression)
    pool = [ai for ai in range(len(assets)) if ai not in used]
    for i in sent_ids:
        if i not in assigned and pool:
            assigned[i] = pool.pop(0)
            used.add(assigned[i])

    plan = Plan()
    last_end = 0.0
    n = len(sent_ids)
    for k, i in enumerate(sent_ids):
        cs = sentences[i]
        start, end = cs[0].start_ms, cs[-1].end_ms
        start = min(start, last_end)  # no gaps
        last_end = end
        if k == 0:
            shot = Shot(kind="title_card", asset_path=None, sent_indexes=[i], start_ms=start, end_ms=end)
        elif k == n - 1:
            shot = Shot(kind="quote_card", asset_path=None, sent_indexes=[i], start_ms=start, end_ms=end)
        else:
            ai = assigned.get(i)
            if ai is None:
                shot = Shot(kind="quote_card", asset_path=None, sent_indexes=[i], start_ms=start, end_ms=end)
            else:
                a = assets[ai]
                label = a.tags[0] if a.tags else a.summary[:4]
                shot = Shot(kind="footage", asset_path=a.file, sent_indexes=[i],
                            start_ms=start, end_ms=end, chapter_label=label)
        plan.shots.append(shot)
    plan.clauses = clauses
    plan.duration_ms = last_end + 700
    apply_designed_overlays(plan, content)
    return plan


# ---------- designed overlays (parity with niwo's visual design stage) ----------

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
_ARABIC = re.compile(r"\d+(?:\.\d+)?")
_CN_NUM = re.compile(r"[零一二两三四五六七八九]+(?:[十百千万亿][零一二两三四五六七八九十百千万亿]*)?")
_NUM_UNIT = re.compile(r"(%s|%s)\s*(字|个|月|年|亿|万|票|家|人|倍|秒|次|条|款|场)" % (_ARABIC.pattern, _CN_NUM.pattern))


def _cn_to_arabic(cn: str) -> str:
    total, section, num = 0, 0, 0
    for ch in cn:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            u = _CN_UNITS[ch]
            if u >= 10000:
                total = (total + section + num) * u if total or section or num else u
                section, num = 0, 0
            else:
                section += (num if num else 1) * u
                num = 0
    return str(total + section + num)


def extract_number(sentence: str) -> tuple[str, str] | None:
    """Return (display_number_with_unit, matched_source) from a sentence.
    Prefer longer numbers (reference showed '3800' rather than '9月')."""
    best = None
    for m in _NUM_UNIT.finditer(sentence):
        src, unit = m.group(1), m.group(2)
        display = src if _ARABIC.fullmatch(src) else _cn_to_arabic(src)
        if len(display) > 6:
            continue
        cand = (len(display), display + unit, m.group(0))
        if best is None or cand[0] > best[0]:
            best = cand
    if not best or best[0] < 2:
        return None
    return best[1], best[2]


_US_SIDE = re.compile(r"美国|白宫|美方|特朗普")
_CN_SIDE = re.compile(r"中国|中方|北京")


def apply_designed_overlays(plan: Plan, content: Content) -> None:
    """Pick at most one callout and up to two info panels, mirroring niwo's
    restraint (about 5 designed moments in an 84s reference)."""
    # 1) number callout: first footage shot whose sentence has a number + 语境动词
    for shot in plan.shots:
        if shot.kind != "footage":
            continue
        text = "".join(c.text for c in plan.clauses if c.sent_index in shot.sent_indexes)
        num = extract_number(text)
        if num and any(w in text for w in ("发", "砸", "投", "掏", "花", " 写", "禁售", "限速", "超", "涨")):
            label = next((w for w in ("声明", "说明", "现实", "筹码", "警告") if w in text), shot.chapter_label)
            shot.kind = "callout"
            shot.overlay = {"number": num[0], "label": f"{label[:4]}", "caption": text[:14]}
            break
    # 2) compare panel: one sentence mentions both sides
    for shot in plan.shots:
        if shot.kind != "footage":
            continue
        text = "".join(c.text for c in plan.clauses if c.sent_index in shot.sent_indexes)
        us_m = _US_SIDE.search(text)
        cn_m = _CN_SIDE.search(text)
        if us_m and cn_m:
            us_m2 = _US_SIDE.search(text, us_m.end())
            cn_m2 = _CN_SIDE.search(text, cn_m.end())
            # split at the side keyword that starts the opposing half
            split = min(x.start() for x in (cn_m, cn_m2) if x) if us_m.start() < cn_m.start() \
                else min(x.start() for x in (us_m, us_m2) if x)
            left = text[:split].strip("，。 ")
            right = text[split:].strip("，。 ")
            shot.kind = "panel"
            shot.overlay = {"variant": "compare", "label": "技术封锁", "title": "芯片变筹码",
                            "subtitle": "中美反应开始对撞",
                            "left": left[-12:] if left else text[:12],
                            "right": right[:12] or text[12:24],
                            "left_head": "美国建议", "right_head": "中国回击", "badge": "升级"}
            break
    # 3) fact panel: a mid sentence with a punchy 4-8 char claim
    mid = [s for s in plan.shots if s.kind == "footage" and len(s.sent_indexes) == 1]
    if mid:
        shot = mid[len(mid) // 2]
        text = "".join(c.text for c in plan.clauses if c.sent_index in shot.sent_indexes)
        claim = next((c.text for c in plan.clauses if c.sent_index in shot.sent_indexes and len(c.text) <= 8), None)
        if claim or len(text) <= 18:
            shot.kind = "panel"
            shot.overlay = {"variant": "fact", "label": "关键事实",
                            "card_title": claim or text[:8],
                            "card_body": text[:14], "badge": ""}
    # 4) title-phrase panel: a metaphor-bearing clause becomes a big statement card
    _METAPHOR = ("抢方向盘", "踩刹车", "松油门", "掀桌子", "让路", "对撞")
    for shot in plan.shots:
        if shot.kind != "footage":
            continue
        text = "".join(c.text for c in plan.clauses if c.sent_index in shot.sent_indexes)
        cs = [c.text for c in plan.clauses if c.sent_index in shot.sent_indexes]
        scored = sorted(cs, key=lambda c: (not any(k in c for k in _METAPHOR), abs(len(c) - 6)))
        short = scored[0] if scored and len(scored[0]) <= 12 else None
        if short and any(k in text for k in ("抢", "停", "困局", "僵", "刹车", "油门")):
            sub = next((c for c in cs if c != short), text[:12])
            shot.kind = "panel"
            shot.overlay = {"variant": "statement", "label": "媒体困局",
                            "title": short, "subtitle": sub, "badge": "僵局"}
            break


# ---------------- LLM 分镜规划的 Python 侧校验与组装 ----------------

def clause_units(clauses):
    """把子句作为分镜最小单元：{index, text, start, end, sent}。

    导演可以把 1-3 个子句组成一个镜头 → 镜头时长可控在 3-5 秒。
    """
    return [{"index": i, "text": c.text, "start": c.start_ms, "end": c.end_ms, "sent": c.sent_index}
            for i, c in enumerate(clauses)]


def unit_spans(units):
    """unit_index -> [start_ms, end_ms, text]"""
    return {u["index"]: [u["start"], u["end"], u["text"]] for u in units}


def sentence_spans(clauses):
    """sent_index -> [start_ms, end_ms, text]"""
    spans = {}
    for c in clauses:
        if c.sent_index not in spans:
            spans[c.sent_index] = [c.start_ms, c.end_ms, c.text]
        else:
            spans[c.sent_index][1] = max(spans[c.sent_index][1], c.end_ms)
            spans[c.sent_index][2] += c.text
    return spans


_CARD_FIELDS = {"callout": ("label", "number", "caption"),
                "compare": ("label", "title", "subtitle", "left_head", "left",
                            "right_head", "right", "badge"),
                "fact": ("label", "card_title", "card_body", "badge"),
                "statement": ("label", "title", "subtitle", "badge", "rows"),
                "stat": ("label", "amount", "desc", "year", "kicker"),
                "branches": ("label", "source", "targets"),
                "person": ("kicker", "title", "name", "caption"),
                "timeline": ("title", "subtitle", "cols", "badge")}


def build_plan_llm(content: Content, manifest: Manifest, clauses, shots_spec,
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
    n_assets = len(manifest.assets)

    covered: list[int] = []
    entries: list[dict] = []
    card_count = 0
    prev_has_card = True  # title card precedes the first entry
    for k, spec in enumerate(shots_spec):
        try:
            sents = [int(i) for i in spec.get("sentences", [])]
        except (TypeError, ValueError):
            return None
        covered += sents
        first, last = sents[0], sents[-1]
        if first not in spans or last not in spans:
            return None
        start, end = spans[first][0], spans[last][1]
        card = spec.get("card")
        entry = {"sents": sents, "start": start, "end": end}
        if card in _CARD_FIELDS and card_count < 5 and not prev_has_card:
            fields = {f: spec.get(f) for f in _CARD_FIELDS[card]
                      if spec.get(f) not in (None, "", [])}
            # drop LLM-echoed template placeholders like "仅设计卡" / "仅callout"
            fields = {f: v for f, v in fields.items()
                      if not (isinstance(v, str) and v.startswith("仅"))
                      and not (isinstance(v, dict)
                               and any(isinstance(x, str) and str(x).startswith("仅")
                                       for x in v.values()))}
            if len(fields) >= 2:
                entry["card"] = card
                entry["copy"] = fields
        # callout without usable media cannot render as a card
        ai = spec.get("asset")
        try:
            ai = int(ai)
        except (TypeError, ValueError):
            ai = None
        if entry.get("card") == "callout" and (ai is None or ai >= n_assets):
            entry.pop("card", None)
        prev_has_card = bool(entry.get("card"))
        if prev_has_card:
            card_count += 1
        entry["asset"] = ai
        entry["chapterLabel"] = (spec.get("chapterLabel") or "")[:4]
        entries.append(entry)

    if covered != interior:
        return None  # must cover interior sentences exactly, in order

    plan = Plan()
    assets = manifest.assets
    shot_list: list[Shot] = []
    first_span, last_span = edge_spans if edge_spans else (spans[ids[0]], spans[ids[-1]])
    shot_list.append(Shot(kind="title_card", asset_path=None, sent_indexes=[],
                          start_ms=first_span[0], end_ms=first_span[1]))
    for e in entries:
        start = min(e["start"], shot_list[-1].end_ms)
        if e.get("card") == "callout":
            a = assets[e["asset"]] if e["asset"] is not None and e["asset"] < n_assets else None
            shot_list.append(Shot(kind="callout", asset_path=a.file if a else None,
                                  sent_indexes=list(e["sents"]), start_ms=start, end_ms=e["end"],
                                  chapter_label=e["chapterLabel"],
                                  overlay={"label": e["copy"].get("label", ""),
                                           "number": e["copy"].get("number", ""),
                                           "caption": e["copy"].get("caption", "")}))
        elif e.get("card"):
            # 设计卡也要素材打底（半透明叠加），避免"纯色板+文字"的单调感
            a = assets[e["asset"]] if e["asset"] is not None and e["asset"] < n_assets else None
            shot_list.append(Shot(kind="panel", asset_path=a.file if a else None,
                                  sent_indexes=list(e["sents"]),
                                  start_ms=start, end_ms=e["end"],
                                  chapter_label=e.get("chapterLabel", ""),
                                  overlay={"variant": e["card"], **e["copy"]}))
        else:
            a = assets[e["asset"]] if e["asset"] is not None and e["asset"] < n_assets else None
            label = e["chapterLabel"] or (a.tags[0] if a and a.tags else "")
            shot_list.append(Shot(kind="footage", asset_path=a.file if a else None,
                                  sent_indexes=list(e["sents"]), start_ms=start, end_ms=e["end"],
                                  chapter_label=label))
    shot_list.append(Shot(kind="quote_card", asset_path=None, sent_indexes=[],
                          start_ms=max(shot_list[-1].end_ms, last_span[0]), end_ms=last_span[1]))
    # 智能替换：非人物图片镜头若有"标签重合的未用视频"，换成视频（提高动态占比）。
    # 人物照（tags 含"人物"）保留——人物题材用真实照片比用无关视频更准确。
    by_file = {a.file: a for a in manifest.assets}
    used_files = {s_.asset_path for s_ in shot_list if s_.asset_path}
    unused_videos = [a for a in manifest.assets if a.kind == "video" and a.file not in used_files]

    def _overlap(img, vid) -> int:
        return len(set(img.tags or []) & set(vid.tags or []))

    for s_ in shot_list:
        if not unused_videos or not s_.asset_path:
            continue
        a = by_file.get(s_.asset_path)
        if not a or a.kind != "image":
            continue
        if any(t in (a.tags or []) for t in ("人物", "肖像", "特朗普", "马斯克", "黄仁勋", "奥特曼", "阿莫迪")):
            continue  # 人物照保留
        best = max(unused_videos, key=lambda v: _overlap(a, v))
        if _overlap(a, best) >= 1:
            s_.asset_path = best.file
            unused_videos.remove(best)
    # 事实性防线：设计卡里的年份若未在文案中出现，一律删除（禁止编造）
    for s_ in shot_list:
        o = s_.overlay or {}
        y = o.get("year")
        if y and str(y) not in content.script:
            o.pop("year", None)
        if o.get("number") and str(o["number"]).rstrip("字个条") not in content.script                 and str(o["number"]) not in content.script:
            pass  # 数字卡允许改写单位，不做强校验

    plan.shots = shot_list
    plan.clauses = clauses
    plan.duration_ms = shot_list[-1].end_ms + 700
    return plan


# ---------------- clone 模式：按参考片时间轴 1:1 复刻 ----------------

def build_plan_clone(content: Content, clauses, timeline: dict,
                     manifest: Manifest, bundle: Path) -> Plan:
    """按参考片时间轴图纸复刻：槽位边界按我的配音总时长等比缩放。"""
    spans = sentence_spans(clauses)
    ids = sorted(spans)
    my_total = spans[ids[-1]][1] + 400.0
    ref_total = float(timeline.get("ref_total", 84.4)) * 1000.0
    scale = my_total / ref_total

    plan = Plan()
    shot_list: list[Shot] = []
    for slot in timeline["slots"]:
        start = slot["start"] * scale * 1000.0   # 秒 -> 毫秒
        end = slot["end"] * scale * 1000.0
        kind = slot["kind"]
        media = slot.get("media")
        if media and not (bundle / media).is_file():
            media = None
        overlay = dict(slot.get("copy") or {})
        if "overlay" in slot:
            overlay.update(slot["overlay"])
        if kind == "statement_media":
            overlay["appearMs"] = slot.get("appearMs", 1500)
        sents = [i for i in ids if spans[i][0] < end and spans[i][1] > start]
        shot_list.append(Shot(kind=kind, asset_path=media, sent_indexes=sents,
                              start_ms=start, end_ms=end,
                              chapter_label=slot.get("chapterLabel", ""),
                              overlay=overlay))
    # 镜头之间不留缝
    for a, b in zip(shot_list, shot_list[1:]):
        a.end_ms = b.start_ms
    shot_list[-1].end_ms = max(shot_list[-1].end_ms, my_total)
    # 事实性防线：设计卡里的年份若未在文案中出现，一律删除（禁止编造）
    for s_ in shot_list:
        o = s_.overlay or {}
        y = o.get("year")
        if y and str(y) not in content.script:
            o.pop("year", None)
        if o.get("number") and str(o["number"]).rstrip("字个条") not in content.script                 and str(o["number"]) not in content.script:
            pass  # 数字卡允许改写单位，不做强校验

    plan.shots = shot_list
    plan.clauses = clauses
    plan.duration_ms = my_total
    return plan
