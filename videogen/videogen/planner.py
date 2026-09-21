"""Stage 2+3: shot planning and clause-level timeline from TTS word boundaries."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import templates
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
    # macro（宏观棱镜式）：全片暗背景素材（bundle 相对路径），None=用渲染器自带底图
    bg_asset: str | None = None


# ---------- Plan <-> JSON ----------
# 双通道流水线里，预备阶段（配音/分镜）与渲染阶段分两次进程内调用，
# Plan 靠落盘中转；字段与 dataclass 严格对应，多缺字段都不致命。

def plan_to_dict(plan: Plan) -> dict:
    return {
        "duration_ms": plan.duration_ms,
        "theme": dict(plan.theme or {}),
        "style_pack": plan.style_pack or "",
        "bg_asset": plan.bg_asset,
        "shots": [{"kind": s.kind, "asset_path": s.asset_path,
                   "sent_indexes": list(s.sent_indexes or []),
                   "start_ms": s.start_ms, "end_ms": s.end_ms,
                   "chapter_label": s.chapter_label,
                   "overlay": dict(s.overlay or {})} for s in plan.shots],
        "clauses": [{"text": c.text, "sent_index": c.sent_index,
                     "start_ms": c.start_ms, "end_ms": c.end_ms} for c in plan.clauses],
    }


def plan_from_dict(d: dict) -> Plan:
    return Plan(
        shots=[Shot(kind=s.get("kind") or "footage", asset_path=s.get("asset_path"),
                    sent_indexes=list(s.get("sent_indexes") or []),
                    start_ms=s.get("start_ms") or 0.0, end_ms=s.get("end_ms") or 0.0,
                    chapter_label=s.get("chapter_label") or "",
                    overlay=dict(s.get("overlay") or {})) for s in d.get("shots") or []],
        clauses=[Clause(text=c.get("text") or "", sent_index=int(c.get("sent_index") or 0),
                        start_ms=c.get("start_ms") or 0.0, end_ms=c.get("end_ms") or 0.0)
                 for c in d.get("clauses") or []],
        duration_ms=d.get("duration_ms") or 0.0,
        theme=dict(d.get("theme") or {}),
        style_pack=d.get("style_pack") or "",
        bg_asset=d.get("bg_asset"),
    )


# ---------- 节奏：由规则算，不由大模型决定 ----------
# 大模型只看得见文字、看不见"这句话在耳朵里多长"，所以它的镜头切分总会忽长忽短。
# 这里做的是：把它给的每个单元的设计（素材/卡/章节标签）记下来，然后**按真实时间轴
# 重新分块**——每块落在 target~cap 之间。大模型仍然决定"说什么、配什么画面、用哪张卡"，
# 只是不再决定"切多长"。
#
# 参数是拿真实配音标定的：中文口播的"逗号级子句"平均 2.2-2.3 秒，所以两段成镜约 4.5 秒。
# cap 要放到 4800 才能让"两段一镜"成立——卡在 4200 时两段就超限，只能一段一镜（2.2 秒），
# 那是更快但比参考片碎的节奏。实测这套参数平均 3.6 秒/拍，与参考片（3.6 秒/拍）一致。
TARGET_MS = 3800
SHOT_CAP_MS = 4800
# 一张设计卡至少要配这么长的画面，太短就不给它单独开一块了
_MIN_BLOCK_MS = 2100


def normalize_rhythm(shots_spec: list[dict], spans: dict, interior: list[int],
                     target_ms: int = TARGET_MS, cap_ms: int = SHOT_CAP_MS) -> list[dict]:
    """按时间轴重新分块，让每个镜头落在 target~cap 之间。

    - 设计（素材/卡/章节标签）来自大模型：每块继承「块首那个单元」的设计，
      设计卡所属的单元会被优先当成块边界（保住它的露出时机），除非那会让上一块太短。
    - 顺序与覆盖范围按定义不变，下游的"必须不重不漏"校验照旧通过。
    """
    design = _unit_design(shots_spec)
    # 只重切模型真正给了设计的单元：它漏掉的单元不要在这里补，
    # 否则会把"漏讲"悄悄抹平——下游的覆盖校验该拒就拒，退回规则分镜。
    units = [u for u in interior if u in spans and u in design]
    if not units:
        return shots_spec

    blocks: list[list[int]] = []
    cur: list[int] = []
    for u in units:
        if cur:
            dur = spans[u][1] - spans[cur[0]][0]
            cur_dur = spans[cur[-1]][1] - spans[cur[0]][0]
            # 块首带设计卡的单元：只要上一块已经够长，就在这里断开，让卡从新块开始
            anchor = bool((design.get(u) or {}).get("card")) and cur_dur >= _MIN_BLOCK_MS
            if dur > cap_ms or cur_dur >= target_ms or anchor:
                blocks.append(cur)
                cur = []
        cur.append(u)
    if cur:
        blocks.append(cur)

    out: list[dict] = []
    for block in blocks:
        spec = dict(design.get(block[0]) or {})
        spec["sentences"] = block
        out.append(spec)
    return out


def _unit_design(shots_spec: list[dict]) -> dict[int, dict]:
    """单元 index → 该单元所在镜头带的设计字段。

    一个镜头里只有**首个单元**继承全部设计（含设计卡）；其余单元只继承
    素材与章节标签——设计卡是画面上的一次弹出，不该跟着整段复制。
    """
    out: dict[int, dict] = {}
    for spec in shots_spec:
        sents = _as_ints(spec.get("sentences"))
        if not sents:
            continue
        full = {k: v for k, v in spec.items() if k != "sentences"}
        light = {k: v for k, v in full.items() if k in ("asset", "chapterLabel")}
        for k, u in enumerate(sents):
            out[u] = full if k == 0 else light
    return out


def _as_ints(raw) -> list[int]:
    try:
        return [int(i) for i in (raw or [])]
    except (TypeError, ValueError):
        return []


def split_long_shots(shots_spec: list[dict], spans: dict, cap_ms: int = SHOT_CAP_MS) -> list[dict]:
    """把超过 cap 的镜头按单元对半切开（单单元镜头切不动，原样保留）。

    切分只按顺序拆分句子列表，不复制设计卡——后半段只留句子/素材/章节标签，
    否则同一张卡会连着出两次。切完顺序与覆盖范围不变，下游校验照旧通过。
    """
    out: list[dict] = []
    for spec in shots_spec:
        out.extend(_split_one(spec, spans, cap_ms))
    return out


def _split_one(spec: dict, spans: dict, cap_ms: int) -> list[dict]:
    try:
        sents = [int(i) for i in spec.get("sentences", [])]
    except (TypeError, ValueError):
        return [spec]
    if len(sents) < 2:
        return [spec]
    first, last = sents[0], sents[-1]
    if first not in spans or last not in spans:
        return [spec]
    if spans[last][1] - spans[first][0] <= cap_ms:
        return [spec]
    mid = len(sents) // 2
    head = dict(spec)
    head["sentences"] = sents[:mid]
    tail = {k: v for k, v in spec.items() if k in ("sentences", "asset", "chapterLabel")}
    tail["sentences"] = sents[mid:]
    return _split_one(head, spans, cap_ms) + _split_one(tail, spans, cap_ms)


def _clause_chunks(cs: list[Clause], cap_ms: int) -> list[tuple[float, float]]:
    """按 cap 把连续子句分组（规则分镜用）：返回首尾相接的 [(start_ms, end_ms), ...]。

    贪心从头攒，攒满 cap 就断一刀；单个子句自身超长时无法再切，原样成镜。
    """
    if not cs:
        return []
    out: list[list[float]] = [[cs[0].start_ms, cs[0].end_ms]]
    for c in cs[1:]:
        if c.end_ms - out[-1][0] > cap_ms:
            out.append([c.start_ms, c.end_ms])
        else:
            out[-1][1] = c.end_ms
    return [(a, b) for a, b in out]


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
                # 节奏保险丝：整句太长时按子句再切几刀，画面每 ~4 秒换一次
                chunks = _clause_chunks(cs, SHOT_CAP_MS)
                if len(chunks) > 1:
                    for cs_start, cs_end in chunks:
                        plan.shots.append(Shot(kind="footage", asset_path=a.file, sent_indexes=[i],
                                               start_ms=cs_start, end_ms=cs_end, chapter_label=label))
                    continue
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


# ---------- 内容驱动开场：开场从稿子和素材里长出来，纯排版只做兜底 ----------

_CHART_TAGS = ("图表", "走势", "数据", "K线", "行情", "屏幕")
_HERO_NUM = re.compile(
    "(" + _ARABIC.pattern + "|" + _CN_NUM.pattern + r")\s*(个基点|基点|万亿?美元|亿美元|万亿|亿|万|倍|%)"
)


def _hero_number(script: str) -> str | None:
    """开场主角数字：全稿第一个「数+量级」（百分比/基点/亿/万/倍）。
    前 40% 篇幅里的优先——开场就该亮最狠的那个。中文数字直接转阿拉伯。"""
    head_cut = int(len(script) * 0.4)
    for seg in (script[:head_cut], script):
        m = _HERO_NUM.search(seg)
        if m:
            src, unit = m.group(1), m.group(2)
            display = src if _ARABIC.fullmatch(src) else _cn_to_arabic(src)
            if 1 <= len(display) <= 6:
                return display + unit
    return None


def _pick_hero_asset(assets: list, prefer_chart: bool = False,
                     title: str = "", exclude: str | None = None) -> str | None:
    """开场/片尾主角素材：数字形态优先图表打底；素材形态优先视频，照片按「标签对上
    选题标题」排序（标题点名的主体优先出镜），图表垫底。exclude 用来跟开场错开主角。"""
    def _is_chart(a) -> bool:
        return any(t in _CHART_TAGS for t in (a.tags or []))

    def _photo_rank(a) -> tuple:
        hit = sum(len(t) for t in (a.tags or []) if t and t in title)
        return (0 if hit else 1, -hit)

    videos = [a for a in assets if a.kind == "video" and a.file != exclude]
    images = [a for a in assets if a.kind == "image" and a.file != exclude]
    charts = [a for a in images if _is_chart(a)]
    photos = sorted((a for a in images if not _is_chart(a)), key=_photo_rank)
    pool = (charts + photos + videos) if prefer_chart else (videos + photos + charts)
    return pool[0].file if pool else None


def plan_opening(content: Content, manifest: Manifest, template: str = "") -> dict | None:
    """决定这支出什么形态的开场：
    - 稿子有扎眼数字 → number（数字当主角，图表/素材打底）
    - 没数字但有素材 → media（照片/视频铺满，标题压上去）
    - 两样都没有 → plain（纯排版，编舞引擎的谱式兜底）
    返回 None = 该模板不启用（目前只有 editorial 系）。"""
    if template != "editorial":
        return None
    num = _hero_number(content.script or "")
    if num:
        return {"form": "number", "hero_number": num,
                "hero_asset": _pick_hero_asset(manifest.assets, prefer_chart=True)}
    hero = _pick_hero_asset(manifest.assets, prefer_chart=False, title=content.title or "")
    if hero:
        return {"form": "media", "hero_asset": hero, "hero_number": None}
    return {"form": "plain", "hero_asset": None, "hero_number": None}


def plan_ending(manifest: Manifest, template: str = "", exclude: str | None = None) -> dict | None:
    """片尾形态：有素材 → media（主角素材与开场错开，呼应但不重复）；没有 → plain。"""
    if template != "editorial":
        return None
    hero = _pick_hero_asset(manifest.assets, prefer_chart=False, exclude=exclude)
    return {"form": "media" if hero else "plain", "hero_asset": hero}


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
                   spans=None, interior=None, edge_spans=None,
                   template: str = "") -> Plan | None:
    """Construct a Plan from the LLM director's shot list, with validation.

    spans/interior/edge_spans：可传入"子句单元"制的切分（镜头可细化到 3-5 秒）；
    不传则退回整句制。edge_spans = (首句span, 末句span) 用于片头/金句卡。
    template：模板 id——用来做「这套模板画不出来的卡一律回落」的校验。
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
    shots_spec = normalize_rhythm(shots_spec, spans, interior)
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
        # 模板语汇校验：这套模板画不出来的卡一律回落成普通镜头。
        # 提示词里已经把取值收成枚举，这里是最后一道兜底——宁可少一张卡，
        # 也不要出现一张渲染出来是空块的设计卡。
        allowed_cards = templates.template_cards(template) if template else None
        if card and allowed_cards is not None and card not in allowed_cards:
            card = None
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
        # 智谷三段式：舞台动作字段（chips/tree/table）随镜头直通，不认识也不能丢
        stage = {k: spec.get(k) for k in ("chips", "tree", "table")
                 if spec.get(k) not in (None, "", [])}
        if stage:
            entry["stage"] = stage
        entries.append(entry)

    if covered != interior:
        return None  # must cover interior sentences exactly, in order

    plan = Plan()
    assets = manifest.assets
    shot_list: list[Shot] = []
    first_span, last_span = edge_spans if edge_spans else (spans[ids[0]], spans[ids[-1]])
    shot_list.append(Shot(kind="title_card", asset_path=None, sent_indexes=[],
                          start_ms=first_span[0], end_ms=first_span[1]))
    # 内容驱动开场：数字/素材当主角——主角素材直接挂在片头镜头上，形态决定留到渲染前编谱
    opening = plan_opening(content, manifest, template)
    if opening:
        if opening.get("hero_asset"):
            shot_list[0].asset_path = opening["hero_asset"]
        shot_list[0].overlay = {"opening": opening}
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
                                  chapter_label=label,
                                  overlay=({"stage": e["stage"]} if e.get("stage") else {})))
    shot_list.append(Shot(kind="quote_card", asset_path=None, sent_indexes=[],
                          start_ms=max(shot_list[-1].end_ms, last_span[0]), end_ms=last_span[1]))
    # 内容驱动片尾：换个主角素材呼应开场，形态留给渲染前编谱
    if template == "editorial":
        ending = plan_ending(manifest, template, exclude=(opening or {}).get("hero_asset"))
        if ending:
            if ending.get("hero_asset"):
                shot_list[-1].asset_path = ending["hero_asset"]
            shot_list[-1].overlay = {"ending": ending}
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

# ---------- macro（宏观棱镜式）：按「章」规划，一拍=一章 ----------
# macro 的分镜单位不是 4 秒一镜，而是叙述章：导演把子句单元组织成 5-9 章，
# 章内元素跟着句子逐个弹出。这里负责三件事：校验覆盖、数字防编造、LLM 挂了给兜底章。

_MACRO_BLOCK_TYPES = ("list", "bars", "line", "big", "cards", "grid", "vs", "arrow")

_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def _cn_section(s: str) -> int:
    """「二百四十三」这类连续段 → 243（不含 万/亿）。"""
    total, cur = 0, 0
    for ch in s:
        if ch in _CN_DIGIT:
            cur = cur * 10 + _CN_DIGIT[ch] if cur else _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            total += (cur or 1) * _CN_UNIT[ch]
            cur = 0
    return total + cur


def _cn_to_int(s: str) -> int | None:
    """「二百四十三亿」→ 243（末尾单位剥掉，留给 display）；纯阿拉伯数字直接转。"""
    try:
        return int(s)
    except ValueError:
        pass
    for unit in ("亿", "万"):
        if s.endswith(unit):
            s = s[:-1]
            break
    if not s:
        return None
    if all(ch in "0123456789" for ch in s):
        return int(s)
    if all(ch in _CN_DIGIT or ch in _CN_UNIT for ch in s):
        return _cn_section(s) or None
    return None


def _script_numbers(script: str) -> set[int]:
    """口播文案里出现过的所有数（阿拉伯+中文数字都算），供图表数字防编造校验。"""
    pool: set[int] = set()
    for raw in re.findall(r"[0-9]+(?:\.[0-9]+)?|[零一二两三四五六七八九十百千]+[亿万]?", script):
        v = _cn_to_int(raw)
        if v is not None:
            pool.add(v)
    return pool


def _macro_num_ok(value, pool: set[int]) -> bool:
    if not isinstance(value, (int, float)):
        return False
    v = abs(value)
    return int(v) in pool or int(round(v * 10)) in pool or int(round(v * 100)) in pool


def _sanitize_macro_block(block: dict, pool: set[int]) -> dict | None:
    """章动作清洗：类型白名单 + 数字校验，不合法的行/点直接丢，丢完为空则整个 block 丢弃。"""
    if not isinstance(block, dict):
        return None
    t = block.get("type")
    if t not in _MACRO_BLOCK_TYPES:
        return None
    if t == "bars":
        rows = [r for r in (block.get("rows") or []) if isinstance(r, dict)
                and _macro_num_ok(r.get("value"), pool)]
        if not rows:
            return None
        for r in rows:
            r.setdefault("display", f"{r['value']:+g}%")
        return {"type": t, "axis": True, "rows": rows}
    if t == "line":
        pts = [p for p in (block.get("points") or []) if isinstance(p, dict)
               and _macro_num_ok(p.get("y"), pool)]
        if len(pts) < 4:  # 少于 4 个可信点撑不起一条趋势线
            return None
        return {"type": t, "unit": block.get("unit") or "%", "points": pts,
                "ticks": [x for x in (block.get("ticks") or []) if isinstance(x, (int, float))]
                or None}
    if t == "big":
        num = str(block.get("number") or "")
        digits = "".join(ch for ch in num if ch.isdigit() or ch == ".")
        if not digits or not _macro_num_ok(float(digits or 0), pool):
            return None
        return {"type": t, "number": num or "0", "label": str(block.get("label") or "")[:10],
                "deco": block.get("deco") if block.get("deco") in ("dots",) else None}
    if t == "cards":
        rows = [{"text": str(r.get("text") or r)[:16] if isinstance(r, dict) else str(r)[:16],
                 "gold": bool(isinstance(r, dict) and r.get("gold"))}
                for r in (block.get("rows") or []) if r]
        return {"type": t, "rows": rows[:4]} if rows else None
    if t == "grid":
        items = [{"title": str((r.get("title") if isinstance(r, dict) else r) or "")[:8],
                  "sub": str((r.get("sub") if isinstance(r, dict) else "") or "")[:10]}
                 for r in (block.get("items") or []) if r]
        return {"type": t, "cols": 2, "items": items[:6]} if items else None
    if t == "vs":
        l, r = block.get("left") or {}, block.get("right") or {}
        if not isinstance(l, dict) or not isinstance(r, dict):
            return None

        def _side(v):
            # 导演给字段名飘忽（lines/text/head/body/title 都见过），逐个兜底
            lines = [str(x)[:10] for x in (v.get("lines") or []) if x]
            for k in ("text", "body", "title"):
                if not lines and v.get(k):
                    lines = [str(v[k])[:14]]
            label = str(v.get("label") or v.get("head") or "")[:6]
            return {"label": label, "lines": lines[:3]}

        left, right = _side(l), _side(r)
        if not left["lines"] and not right["lines"]:
            return None
        return {"type": t, "left": left, "right": right}
    if t == "arrow":
        return {"type": t, "from": str(block.get("from") or "")[:6],
                "to": str(block.get("to") or "")[:6], "note": str(block.get("note") or "")[:14] or None}
    if t == "list":
        # 渲染端统一读 rows（与 cards 同构），LLM 给的 items 在这里归一
        rows = [{"text": str(r.get("text") if isinstance(r, dict) else r)[:8]}
                for r in (block.get("items") or block.get("rows") or []) if r]
        return {"type": t, "rows": rows[:4], "goldLast": bool(block.get("goldLast"))} if rows else None
    return None


def _macro_fallback_chapters(units: list[dict], script: str) -> list[dict]:
    """LLM 挂了的兜底：每 4 个单元一章，卡链块保证一定有画面。"""
    chapters = []
    for i in range(0, len(units), 4):
        chunk = units[i:i + 4]
        first = chunk[0]["text"].replace("，", "").replace("。", "")[:9]
        rows = [{"text": u["text"].replace("，", "")[:14]} for u in chunk[:3]]
        chapters.append({"kicker": f"{len(chapters) + 1:02d} / 解读", "title": first,
                         "block": {"type": "cards", "rows": rows}, "rule": True,
                         "units": [u["index"] for u in chunk]})
    return chapters


def build_plan_macro(content: Content, clauses, units: list[dict],
                     chapters_spec: dict | None = None) -> Plan:
    """macro 模板的分镜构建：一拍=一章，覆盖全部子句单元。"""
    spans = unit_spans(units)
    ids = [u["index"] for u in units]
    chapters_raw = None
    if chapters_spec and isinstance(chapters_spec.get("chapters"), list):
        raw = chapters_spec["chapters"]
        # 宽容对齐：LLM 的章节边界偶尔会漏一两个单元/轻微越界，不至于全盘兜底。
        # 以「每章第一个有效单元」定章界，按 ids 顺序补齐区间，缺失的单元归前一章。
        starts: list[tuple[int, list]] = []  # (首个有效单元在 ids 中的位置, 章 dict)
        for ch in raw:
            if not isinstance(ch, dict):
                continue
            us = [u for u in (ch.get("units") or []) if u in spans]
            if not us:
                continue
            pos = next((ids.index(u) for u in us if u in ids), None)
            if pos is None or (starts and pos <= starts[-1][0]):
                continue  # 章界必须严格递增，否则章序会乱
            starts.append((pos, ch))
        if starts:
            aligned: list[dict] = []
            for j, (pos, ch) in enumerate(starts):
                end_pos = starts[j + 1][0] if j + 1 < len(starts) else len(ids)
                ch_us = ids[pos:end_pos]
                if ch_us:
                    aligned.append({**ch, "units": ch_us})
            if aligned:
                chapters_raw = aligned
            else:
                print("[macro] 章节覆盖不合法，改用兜底分章")
    if not chapters_raw:
        chapters_raw = _macro_fallback_chapters(units, content.script)

    plan = Plan()
    plan.clauses = list(clauses)
    pool = _script_numbers(content.script)
    shots: list[Shot] = []
    for ci, ch in enumerate(chapters_raw):
        us = [u for u in ch.get("units") if u in spans]
        if not us:
            continue
        start, end = spans[us[0]][0], spans[us[-1]][1]
        if ci == len(chapters_raw) - 1:
            end = max(end, spans[ids[-1]][1])
        block = _sanitize_macro_block(ch.get("block") or {}, pool)
        title = str(ch.get("title") or "").strip()[:10]
        if not title:
            title = spans[us[0]][2].replace("，", "").replace("。", "")[:9]
        stage = {"mode": "macro",
                 "kicker": str(ch.get("kicker") or f"{ci + 1:02d}")[:14],
                 "title": title,
                 "sub": str(ch.get("sub") or "").strip()[:16] or None,
                 "rule": bool(ch.get("rule"))}
        if block:
            stage["block"] = block
            # 元素弹出时刻：按本章单元均分（LLM 不知道毫秒，不逐元素指定）
            n = max(_macro_block_count(block), len(us))
            step = (end - start) / max(n, 1)
            offset = 0
            if block["type"] == "bars":
                stage["block"]["rows"] = [dict(r, atMs=round(offset + i * step))
                                          for i, r in enumerate(stage["block"]["rows"])]
                offset = len(stage["block"]["rows"]) * step
            elif block["type"] in ("list", "cards"):
                rows = [dict(r, atMs=round(offset + i * step))
                        for i, r in enumerate(stage["block"]["rows"])]
                if block["type"] == "list" and block.get("goldLast") and rows:
                    rows[-1]["gold"] = True
                stage["block"]["rows"] = rows
                offset = len(rows) * step
            elif block["type"] == "big":
                stage["block"]["atMs"] = round(offset)
            elif block["type"] == "grid":
                stage["block"]["items"] = [dict(r, atMs=round(offset + i * step))
                                           for i, r in enumerate(stage["block"]["items"])]
            elif block["type"] == "vs":
                stage["block"]["atMs"] = round(offset)
            elif block["type"] == "arrow":
                stage["block"]["atMs"] = round(offset)
            elif block["type"] == "line":
                stage["block"]["spanMs"] = max(end - start - 300, 1200)
        if ch.get("caption"):
            stage["caption"] = {"text": str(ch["caption"])[:16],
                                "atMs": round(min(max(offset, (end - start) * 0.55), end - start - 200))}
        shots.append(Shot(kind="footage", asset_path=None, sent_indexes=[],
                          start_ms=start, end_ms=end + 350, overlay={"macro": stage}))
    plan.shots = shots
    plan.duration_ms = shots[-1].end_ms if shots else 0.0
    return plan


def _macro_block_count(block: dict) -> int:
    if block["type"] == "bars":
        return len(block.get("rows") or [])
    if block["type"] == "list":
        return len(block.get("items") or [])
    if block["type"] == "cards":
        return len(block.get("rows") or [])
    if block["type"] == "grid":
        return len(block.get("items") or [])
    if block["type"] == "line":
        return max(len(block.get("points") or []) // 2, 2)
    return 1


def build_plan_clone(content: Content, clauses, timeline: dict,
                     manifest: Manifest, bundle: Path) -> Plan:
    """按参考片时间轴图纸复刻：槽位边界按我的配音总时长等比缩放。"""
    spans = sentence_spans(clauses)
    ids = sorted(spans)
    if not ids:
        raise ValueError("复刻分镜要先有对齐好的子句")
    slots = timeline.get("slots") or []
    if not slots:
        # 图纸是浏览器交上来的外部输入：空槽位以前会在这里 IndexError，
        # 客户只看到任务失败、错误信息是一句看不懂的 traceback。
        raise ValueError("复刻图纸里没有任何槽位（slots 是空的）")
    for i, slot in enumerate(slots):
        # 槽位字段也是浏览器交上来的：缺 start/end/kind 以前是当场 KeyError，
        # 错误信息里连是哪个槽位都不说。
        missing = [k for k in ("start", "end", "kind") if k not in slot]
        if missing:
            raise ValueError("复刻图纸第 %d 个槽位缺字段：%s" % (i + 1, "、".join(missing)))
    my_total = spans[ids[-1]][1] + 400.0
    ref_total = float(timeline.get("ref_total", 84.4)) * 1000.0
    scale = my_total / ref_total

    plan = Plan()
    shot_list: list[Shot] = []
    for slot in slots:
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
    for a, b in zip(shot_list, shot_list[1:], strict=False):
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
