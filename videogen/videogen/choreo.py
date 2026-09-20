"""开场编谱器：编舞引擎（renderer/src/choreo.tsx）的 Python 侧作曲家。

为什么要有这个文件：以前片头是渲染端一段写死的编排，每个选题放同一段动画。
现在把"开场怎么出场"变成一份谱（cues），按「种子+文案」现场编——
同一套模板下不同选题长出不同的开场，但每个元素、动效、锚位都在引擎词汇表内，
所以再怎么变都是设计过的样子。

- 种子 = 素材包名 + 选题标题：同一支片子重渲结果稳定，换个选题必然换谱。
- 谱式（motif）：几种开场骨架；每次在骨架内抖动参数（锚位镜像、动效选型、
  粗细长短、节奏伸缩），组合起来基本不重样。
- 兜底：编出来的谱过渲染端 sanitizeChoreo 校验，非法元素一律剔除；
  这里只从词汇表里取值，正常情况下永远合法。
"""

from __future__ import annotations

import hashlib
import random

_FALLBACK_CODE = "SIGNAL / 01"

# 左右镜像：谱式默认左布局，掷硬币翻到右边，同一谱式又多一倍长相
_MIRROR = {
    "top-left": "top-right", "mid-left": "mid-right", "low-left": "low-right",
    "bottom-left": "bottom-right", "top-right": "top-left", "mid-right": "mid-left",
    "low-right": "low-left", "bottom-right": "bottom-left",
}


def _rng(seed: str) -> random.Random:
    h = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return random.Random(int(h[:12], 16))


def _mirror_slots(cues: list[dict], rng: random.Random) -> None:
    if not rng.random() < 0.5:
        return
    for c in cues:
        slot = c.get("slot")
        if slot in _MIRROR:
            c["slot"] = _MIRROR[slot]


def _big_size(keyword: str) -> str:
    n = len(keyword)
    if n <= 2:
        return "XXL"
    if n <= 4:
        return "XL"
    return "L"


def _m_plumb(rng: random.Random, label: str, keyword: str, code: str) -> list[dict]:
    """竖脊式：竖条落下→横线伸出→压线大字→底部小标签，现版开场的近亲但参数每次不同。"""
    cues = [
        {"el": "vbar", "slot": rng.choice(["top-center", "top-left"]),
         "enter": rng.choice(["growH", "drop"]), "len": rng.choice(["S", "M"]), "at": 0},
        {"el": "rule", "slot": "mid-left", "row": 0, "enter": rng.choice(["growW", "wipeL"]),
         "len": rng.choice(["M", "L"]), "at": 5},
        {"el": "big", "text": keyword, "slot": "mid-left", "row": 1, "tone": "accent",
         "size": _big_size(keyword), "enter": rng.choice(["slideR", "blurIn", "rise"]), "at": 12},
    ]
    if label:
        cues.append({"el": "kicker", "text": label, "slot": "bottom-left",
                     "enter": "rise", "at": 26})
    cues.append({"el": "meta", "text": code, "slot": "bottom-right", "enter": "fade", "at": 32})
    cues.append({"el": "vbar", "slot": "bottom-center", "enter": "growH", "len": "S", "at": 34})
    return cues


def _m_cover(rng: random.Random, label: str, keyword: str, code: str) -> list[dict]:
    """封面式：细框+期号+徽标+居中大字，像一本杂志的封面页。居中构图，不镜像。"""
    cues = [
        {"el": "frame", "slot": "full", "enter": "fade", "at": 0},
        {"el": "issue", "text": code, "slot": "top-right", "enter": "slideR", "at": 2},
    ]
    if label:
        cues.append({"el": "chip", "text": label, "slot": "top-left", "enter": "pop", "at": 6})
    cues.append({"el": "big", "text": keyword, "slot": "center", "tone": "white",
                 "size": _big_size(keyword), "enter": "blurIn", "at": 12})
    cues.append({"el": "rule", "slot": "bottom-center", "enter": "growW", "len": "M", "at": 26})
    return cues


def _m_bigword(rng: random.Random, label: str, keyword: str, code: str) -> list[dict]:
    """满屏一字式：点阵垫底，题眼超大居中从糊到实，干脆没有第二根线。
    点阵/编码/小标签三个角落元素两两错开（查表保证），镜像翻转后依然不撞。"""
    dots_slot = rng.choice(["bottom-right", "top-right", "bottom-left"])
    meta_slot = {"bottom-right": "top-left", "top-right": "bottom-left",
                 "bottom-left": "top-right"}[dots_slot]
    kicker_slot = "bottom-left" if dots_slot == "bottom-right" else "bottom-right"
    cues = [
        {"el": "dots", "slot": dots_slot, "at": 0},
        {"el": "big", "text": keyword, "slot": "center", "tone": "accent",
         "size": _big_size(keyword), "enter": "blurIn", "at": 2},
    ]
    if label:
        cues.append({"el": "kicker", "text": label, "slot": kicker_slot, "enter": "rise", "at": 20})
    cues.append({"el": "meta", "text": code, "slot": meta_slot, "enter": "fade", "at": 28})
    return cues


def _m_ledger(rng: random.Random, label: str, keyword: str, code: str) -> list[dict]:
    """账本式：脊线+期号+压线大字，冷静的编辑感。编码只由期号展示，不再放右下角。"""
    cues = [
        {"el": "vbar", "slot": "top-left", "enter": "growH", "len": rng.choice(["S", "M"]), "at": 0},
        {"el": "issue", "text": code, "slot": "top-right", "enter": "slideR", "at": 3},
        {"el": "rule", "slot": "mid-left", "row": 0, "enter": "growW", "len": "L", "at": 6},
        {"el": "big", "text": keyword, "slot": "mid-left", "row": 1, "tone": "white",
         "size": _big_size(keyword), "enter": rng.choice(["slideR", "wipeL"]), "at": 10},
    ]
    if label:
        cues.append({"el": "kicker", "text": label, "slot": "bottom-left",
                     "enter": "rise", "at": 24})
    return cues


_MOTIFS = {
    "plumb": _m_plumb,
    "cover": _m_cover,
    "bigword": _m_bigword,
    "ledger": _m_ledger,
}

# 居中构图/框式构图的谱式不镜像（镜像会跟自己的元素撞位）
_NO_MIRROR = {"cover"}

# ---------- 谱子自查：与 renderer/src/choreo.tsx 的词汇表保持一致 ----------
# 编谱端先校验一遍，非法 cue 当场丢弃并告警——不要等渲染端悄悄回落，
# 那样元素会"飞"到默认锚位，很难从成片上看出原因。

_MEDIA_SLOTS = {"media-top-left", "media-top-right", "media-bottom-left", "media-bottom-right"}
_CUES_VOCAB: dict[str, dict] = {
    "vbar":   {"slots": {"top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right"},
               "enters": {"growH", "drop", "rise", "fade"}},
    "rule":   {"slots": {"mid-left", "center", "mid-right", "low-left", "low-right",
                         "bottom-left", "bottom-center", "bottom-right"} | _MEDIA_SLOTS,
               "enters": {"growW", "wipeL", "wipeR", "fade"}},
    "kicker": {"slots": {"top-left", "top-center", "top-right", "mid-left", "mid-right",
                         "low-left", "low-right", "bottom-left", "bottom-right"} | _MEDIA_SLOTS,
               "enters": {"rise", "fade", "slideL", "slideR", "drop"}},
    "big":    {"slots": {"center", "mid-left", "mid-right", "low-left", "low-right",
                         "bottom-left", "bottom-center", "bottom-right"},
               "enters": {"blurIn", "pop", "wipeL", "slideL", "slideR", "rise", "drop"}},
    "line":   {"slots": {"mid-left", "center", "low-left", "mid-right", "low-right",
                         "bottom-left", "bottom-right", "bottom-center"},
               "enters": {"rise", "slideL", "slideR", "wipeL", "fade", "pop"}},
    "meta":   {"slots": {"bottom-right", "bottom-left", "top-right", "top-left", "bottom-center"},
               "enters": {"fade", "slideR", "slideL", "rise"}},
    "chip":   {"slots": {"top-left", "top-right", "mid-left"}, "enters": {"pop", "fade", "drop"}},
    "issue":  {"slots": {"top-right", "top-left", "mid-right"}, "enters": {"fade", "slideR", "slideL"}},
    "dots":   {"slots": {"top-right", "top-left", "bottom-left", "bottom-right", "mid-right"},
               "enters": {"fade"}},
    "frame":  {"slots": {"full"}, "enters": {"fade"}},
    "photo":  {"slots": {"canvas"}, "enters": {"scaleIn", "fade"}},
    "scrim":  {"slots": {"canvas"}, "enters": {"fade"}},
    "number": {"slots": {"center", "mid-left", "mid-right", "low-left"},
               "enters": {"blurIn", "pop", "rise", "wipeL"}},
}


def validate_cues(cues: list[dict], where: str = "") -> list[dict]:
    """自查：元素不存在、锚位/动效不在词汇表内的 cue 直接丢弃并告警。"""
    ok: list[dict] = []
    for c in cues:
        vocab = _CUES_VOCAB.get(c.get("el", ""))
        if not vocab:
            print(f"[choreo]{where} 丢弃未知元素 cue: {c}")
            continue
        if c.get("slot") and c["slot"] not in vocab["slots"]:
            print(f"[choreo]{where} 丢弃越界锚位 cue: {c}")
            continue
        if c.get("enter") and c["enter"] not in vocab["enters"]:
            print(f"[choreo]{where} 丢弃越界动效 cue: {c}")
            continue
        ok.append(c)
    return ok


def compose_footage(seed: str, label: str = "") -> dict:
    """素材镜头信息层谱：媒体窗里的角标/章节签/强调线按种子现场编。
    元素只压在画面窗内（media-* 锚位），镜头没标签就只给强调线换位置。"""
    rng = _rng(f"footage|{seed}")
    cues: list[dict] = [
        {"el": "rule", "slot": rng.choice(["media-bottom-left", "media-bottom-right"]),
         "enter": "growW", "len": "S", "thick": "thin", "tone": "accent", "at": 4},
    ]
    label = label.strip()[:4]
    if label:
        slot = rng.choice(["media-top-left", "media-top-right", "media-bottom-right"])
        cues.append({"el": "kicker", "text": label, "slot": slot,
                     "enter": rng.choice(["rise", "fade"]), "at": rng.randint(8, 20)})
    return {"v": 1, "form": "footage", "cues": validate_cues(cues, ":footage")}


def compose_panel(variant: str, spec: dict) -> dict:
    """正文信息卡谱：把卡上的字段当主角摆，而不是套死版式。
    fact：事实标题+正文两行；statement：观点大字+副题。字段缺失就少排。"""
    cues: list[dict] = []
    title = str(spec.get("card", {}).get("title") or spec.get("title") or "").strip()
    body = str(spec.get("card", {}).get("body") or spec.get("subtitle") or "").strip()
    label = str(spec.get("label") or "").strip()[:4]
    if label:
        cues.append({"el": "kicker", "text": label, "slot": "top-left", "enter": "rise", "at": 0})
    if title:
        cues.append({"el": "big", "text": title[:7], "slot": "center", "tone": "accent",
                     "size": _big_size(title[:7]), "enter": "blurIn", "at": 6})
    if body:
        cues.append({"el": "line", "text": body[:14], "slot": "bottom-left",
                     "tone": "white", "enter": "rise", "at": 20})
    badge = str(spec.get("badge") or "").strip()[:2]
    if badge:
        cues.append({"el": "chip", "text": badge, "slot": "top-right", "enter": "pop", "at": 14})
    return {"v": 1, "form": f"panel_{variant}", "cues": validate_cues(cues, f":{variant}")}


def compose_ending(form: str, label: str = "", quote: str = "",
                   code: str = "", has_media: bool = False) -> dict:
    """片尾金句谱：金句当主角——有素材就压在素材上（与开场错开的主角素材），
    没有就纯排版（竖条书挡式收尾）。"""
    code = code.strip() or _FALLBACK_CODE
    quote = (quote or "").strip()
    label = label.strip()
    if form == "media" and has_media:
        cues = [
            {"el": "photo", "slot": "canvas", "enter": "scaleIn", "at": 0},
            {"el": "scrim", "slot": "canvas", "enter": "fade", "at": 2},
            {"el": "big", "text": quote or label or "完", "slot": "center", "tone": "white",
             "size": _big_size(quote or label or "完"), "enter": "blurIn", "at": 10},
        ]
        if label:
            cues.append({"el": "kicker", "text": label, "slot": "top-left",
                         "enter": "rise", "at": 20})
        cues.append({"el": "meta", "text": code, "slot": "bottom-right", "enter": "fade", "at": 28})
        return {"v": 1, "form": "ending_media", "cues": validate_cues(cues, ":ending")}
    cues = [
        {"el": "vbar", "slot": "top-center", "enter": "growH", "len": "S", "at": 0},
        {"el": "big", "text": quote or label or "完", "slot": "center", "tone": "accent",
         "size": _big_size(quote or label or "完"), "enter": "blurIn", "at": 8},
        {"el": "rule", "slot": "bottom-center", "enter": "growW", "len": "S", "at": 22},
        {"el": "meta", "text": code, "slot": "bottom-right", "enter": "fade", "at": 28},
    ]
    if label:
        cues.append({"el": "kicker", "text": label, "slot": "bottom-left",
                     "enter": "rise", "at": 24})
    return {"v": 1, "form": "ending_plain", "cues": validate_cues(cues, ":ending")}


def compose_callout(label: str = "", number: str = "", caption: str = "",
                    has_media: bool = True) -> dict:
    """中间数字卡的谱：数字当主角压在素材画面上，标注在上、说明在下。"""
    cues: list[dict] = []
    if has_media:
        cues += [
            {"el": "photo", "slot": "canvas", "enter": "scaleIn", "at": 0},
            {"el": "scrim", "slot": "canvas", "enter": "fade", "at": 2},
        ]
    if label.strip():
        cues.append({"el": "kicker", "text": label.strip()[:6], "slot": "top-left",
                     "enter": "rise", "at": 8})
    cues.append({"el": "number", "text": number.strip(), "slot": "center",
                 "tone": "white" if has_media else "accent", "enter": "blurIn", "at": 14})
    if caption.strip():
        cues.append({"el": "line", "text": caption.strip()[:14], "slot": "bottom-left",
                     "tone": "white", "enter": "rise", "at": 26})
    return {"v": 1, "form": "callout", "cues": validate_cues(cues, ":callout")}


def compose_opening(seed: str, label: str = "", keyword: str = "",
                    code: str = "") -> dict:
    """按种子现场编一份开场谱。同一 seed 结果稳定，换 seed 必换长相。"""
    rng = _rng(seed)
    motif = rng.choice(list(_MOTIFS))
    cues = _MOTIFS[motif](rng, label.strip(), keyword.strip(),
                          (code.strip() or _FALLBACK_CODE))
    if motif not in _NO_MIRROR:
        _mirror_slots(cues, rng)
    # 节奏伸缩：同一谱式每次快慢略有不同
    scale = rng.uniform(0.85, 1.2)
    for c in cues:
        c["at"] = round(c["at"] * scale)
    return {"v": 1, "motif": motif, "cues": validate_cues(cues, where=f":{motif}")}


def compose_content_opening(form: str, label: str = "", keyword: str = "",
                            code: str = "", hero_number: str | None = None,
                            has_media: bool = False) -> dict:
    """内容驱动开场的谱：主角是稿子里的数字或素材包里的照片/视频。

    - number：大数字糊变清晰当主角（有素材就压在素材上，没有就落在纸卡上）
    - media：照片/视频铺满 + 标题压上去（黑底板线条完全不出现）
    - plain：两样都没有，回落排版谱式（compose_opening）
    """
    code = code.strip() or _FALLBACK_CODE
    label = label.strip()
    keyword = keyword.strip()
    cues: list[dict] = []
    if has_media:
        cues.append({"el": "photo", "slot": "canvas", "enter": "scaleIn", "at": 0})
        cues.append({"el": "scrim", "slot": "canvas", "enter": "fade", "at": 2})
    if form == "number":
        hero = (hero_number or "").strip()
        if label:
            cues.append({"el": "kicker", "text": label, "slot": "top-left",
                         "enter": "rise", "at": 10})
        if hero:
            cues.append({"el": "number", "text": hero, "slot": "center",
                         "tone": "white" if has_media else "accent", "enter": "blurIn", "at": 16})
        if keyword:
            # 锚在底边（从下往上长），超大字也不会被面板底边裁掉
            cues.append({"el": "big", "text": keyword, "slot": "bottom-left",
                         "tone": "white", "size": _big_size(keyword), "enter": "rise", "at": 30})
        cues.append({"el": "meta", "text": code, "slot": "bottom-right", "enter": "fade", "at": 38})
    elif form == "media":
        if label:
            cues.append({"el": "kicker", "text": label, "slot": "top-left",
                         "enter": "rise", "at": 10})
        cues.append({"el": "big", "text": keyword or label, "slot": "low-left", "row": 0,
                     "tone": "white", "size": _big_size(keyword or label),
                     "enter": "blurIn", "at": 16})
        cues.append({"el": "rule", "slot": "bottom-left", "enter": "growW", "len": "M",
                     "thick": "thin", "tone": "teal", "at": 30})
        cues.append({"el": "meta", "text": code, "slot": "bottom-right", "enter": "fade", "at": 34})
    else:
        return compose_opening(f"plain|{keyword}|{label}", label, keyword, code)
    return {"v": 1, "form": form, "cues": validate_cues(cues, where=f":{form}")}
