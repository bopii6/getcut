"""分镜预览：渲染前先出「待确认的分镜」，确认后成片复用同一份规划。

预演（plan_only）跑 cli.build 的前半程：TTS → 分镜 → props，
把 plan/props 落盘到 work/_preview/<project_id>/，正式渲染读这份
props.json，跳过 TTS 与 LLM，保证预览与成片一致。
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

from . import brand as brand_kit
from . import config, llm, remotion_render, tts
from .config import DEFAULT_TEMPLATE, TEMPLATE_ALIAS, TEMPLATES
from .planner import (align_timeline, build_plan, build_plan_llm, clause_units,
                      split_clauses, sentence_spans, unit_spans)
from .schemas import Content, Manifest

WORK = config.WORK / "_preview"
PREVIEW_TASKS: dict[str, dict] = {}      # project_id -> task state
_LOCK = threading.Lock()

# 与 cli.build 相同的标题/金句兜底（预演时 LLM 改写已含 title_card/quote_card）
_HOT_WORDS = ("宣布", "推出", "发布", "引发", "突破", "升级", "暴跌", "暴涨", "扩张",
              "停摆", "放缓", "减产", "裁员", "收购", "起诉", "警告", "曝光",
              "紧急", "首次", "转向", "回归", "签约", "停产", "断供", "涨价", "降价")


def _keyword_of(script: str, fallback: str) -> str:
    for kw in _HOT_WORDS:
        if kw in script:
            return kw
    return fallback


def _quote_of(script: str) -> tuple[str, str]:
    tail = script.rstrip("。！？!?,， ")
    for sep in ("。", "！", "？", "；"):
        if sep in tail:
            tail = tail.rsplit(sep, 1)[-1]
    for sep in ("，", ","):
        tail = tail.rsplit(sep, 1)[-1]
    quote = tail.strip()[:8] or "值得盯紧"
    return "划重点", quote


def _lighten(hex_color: str, amount: float = 0.18) -> str:
    s = hex_color.lstrip("#")
    if len(s) != 6:
        return hex_color
    try:
        r, g, b = (int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return hex_color
    r = min(255, int(r + (255 - r) * amount))
    g = min(255, int(g + (255 - g) * amount))
    b = min(255, int(b + (255 - b) * amount))
    return f"#{r:02x}{g:02x}{b:02x}"


def _apply_refined_copy(plan, refined: dict) -> None:
    per_shot = refined.get("shots") or {}
    for i, shot in enumerate(plan.shots):
        patch = per_shot.get(str(i)) or per_shot.get(i)
        if not patch:
            continue
        if shot.kind == "callout":
            for k in ("label", "number", "caption"):
                if patch.get(k):
                    shot.overlay[k] = copy_patch(patch[k])
        elif shot.kind == "panel":
            for k, v in patch.items():
                if k == "variant" or v in (None, "", []):
                    continue
                if isinstance(v, str):
                    v = copy_patch(v)
                shot.overlay[k] = v


def copy_patch(v):
    """llm 返回的字符串直接用；浅拷贝 dict/list 防止两份 plan 共享引用。"""
    if isinstance(v, dict):
        return {k: copy_patch(x) for k, x in v.items()}
    if isinstance(v, list):
        return [copy_patch(x) for x in v]
    return v


def preview_dir(project_id: str) -> Path:
    return WORK / project_id


def plan_file(project_id: str) -> Path:
    return preview_dir(project_id) / "plan.json"


def load_plan(project_id: str) -> dict | None:
    f = plan_file(project_id)
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def preview_state(project_id: str) -> dict:
    with _LOCK:
        t = PREVIEW_TASKS.get(project_id)
        if t:
            return {"state": t["state"], "error": t.get("error"),
                    "progress": t.get("progress", 0), "detail": t.get("detail", "")}
    p = load_plan(project_id)
    if p:
        return {"state": "ready", "error": None, "progress": 100}
    return {"state": "none"}


def invalidate(project_id: str) -> None:
    """配置/素材变更后让预演数据失效（预览与成片必须一致）。"""
    with _LOCK:
        t = PREVIEW_TASKS.get(project_id)
        if t and t["state"] == "running":
            return
        PREVIEW_TASKS.pop(project_id, None)
    shutil.rmtree(preview_dir(project_id), ignore_errors=True)


def run_preview(project_id: str, body: dict) -> None:
    """后台预演：TTS → 分镜规划 → props 落盘（不渲染成片）。"""
    with _LOCK:
        PREVIEW_TASKS[project_id] = {"state": "running", "progress": 0, "detail": "正在合成配音"}

    def set_state(progress: int, detail: str) -> None:
        with _LOCK:
            t = PREVIEW_TASKS.get(project_id)
            if t and t["state"] == "running":
                t["progress"] = progress
                t["detail"] = detail

    try:
        bundle_dir = Path(body["bundle_dir"])
        content = Content.load(bundle_dir / "content.json")
        manifest = Manifest.load(bundle_dir / "manifest.json")

        set_state(5, "正在合成配音（首次约 30–90 秒，之后有缓存）")
        voice = body.get("voice") or tts.VOICE
        rate = body.get("rate") or tts.RATE
        mp3, events = tts.synthesize(content.script, content.pronunciations,
                                     preview_dir(project_id) / "tts", voice=voice, rate=rate)
        clauses = align_timeline(split_clauses(content), events)
        set_state(30, "AI 导演正在规划分镜与设计卡")

        units = clause_units(clauses)
        u_spans = unit_spans(units)
        s_spans = sentence_spans(clauses)
        s_ids = sorted(s_spans)
        edge = (s_spans[s_ids[0]], s_spans[s_ids[-1]]) if len(s_ids) >= 2 else None
        skip_sents = {s_ids[0], s_ids[-1]} if len(s_ids) >= 2 else set()
        interior_units = [u["index"] for u in units if u["sent"] not in skip_sents]
        sent_payload = [{"index": u["index"], "text": u["text"]} for u in units if u["sent"] not in skip_sents]
        asset_payload = [{"index": i, "kind": a.kind, "tags": a.tags, "summary": a.summary}
                         for i, a in enumerate(manifest.assets)]

        template = TEMPLATE_ALIAS.get(body.get("format") or DEFAULT_TEMPLATE,
                                      body.get("format") or DEFAULT_TEMPLATE)
        if template not in TEMPLATES:
            template = DEFAULT_TEMPLATE
        if template == "macro":
            # 宏观棱镜式：按章规划，不吃素材/设计卡（与 cli.build 的 macro 分支一致）
            from .planner import build_plan_macro
            chapters = llm.design_chapters(
                content.script,
                [{"index": u["index"], "text": u["text"]} for u in units],
                asset_payload)
            plan = build_plan_macro(content, clauses, units, chapters)
            if chapters and isinstance(chapters.get("bg_asset"), int) \
                    and 0 <= chapters["bg_asset"] < len(manifest.assets) \
                    and manifest.assets[chapters["bg_asset"]].kind == "image":
                plan.bg_asset = manifest.assets[chapters["bg_asset"]].file
        else:
            spec = llm.design_shots(content.script, sent_payload, asset_payload, template=template)
            plan = build_plan_llm(content, manifest, clauses, spec["shots"],
                                  spans=u_spans, interior=interior_units,
                                  edge_spans=edge, template=template) if spec else None
            if plan is not None and spec.get("theme"):
                plan.theme = spec["theme"]
            if plan is not None and spec.get("style_pack"):
                plan.style_pack = spec["style_pack"]
        if plan is None:
            plan = build_plan(content, manifest, clauses)

        title_label = "AI 观察｜突发信号"
        title_kw = _keyword_of(content.script, content.title[:4])
        q_label, q_text = _quote_of(content.script)
        # macro 的文案在章节规划里一次成型，标题/金句卡不存在，跳过这次改写调用
        refined = None if template == "macro" else llm.refine_copy(
            content.script,
            [{"index": i, "kind": s.kind, "variant": (s.overlay or {}).get("variant"),
              "sentence": "", "current": s.overlay}
             for i, s in enumerate(plan.shots) if s.overlay],
        )
        if refined:
            _apply_refined_copy(plan, refined)
            tc = refined.get("title_card") or {}
            title_label = tc.get("label") or title_label
            title_kw = tc.get("keyword") or title_kw
            qc = refined.get("quote_card") or {}
            q_label = qc.get("label") or q_label
            q_text = qc.get("quote") or q_text
        theme = body.get("theme") or "auto"
        if theme and theme != "auto" and theme.startswith("#"):
            plan.theme = {"accent": theme, "accentSoft": _lighten(theme)}
        brand = brand_kit.apply_to_plan(plan, body.get("brand"))

        set_state(60, "正在设计画面版式")
        props = remotion_render.build_props(
            bundle_dir, plan, content,
            title_card={"label": title_label, "keyword": title_kw},
            quote_card={"label": q_label, "quote": q_text},
            theme=getattr(plan, "theme", {}),
            show_subtitles=bool(body.get("subtitles", True)),
            show_sources=bool(body.get("sources", True)),
            disclaimer=body.get("disclaimer"),
            template=template,
            watermark=body.get("watermark", True) is not False,
            brand=brand)
        d = preview_dir(project_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "props.json").write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
        (d / "plan.json").write_text(json.dumps({
            "project_id": project_id,
            "created": time.time(),
            "voice": voice, "rate": rate, "format": template,
            "subtitles": bool(body.get("subtitles", True)),
            "sources": bool(body.get("sources", True)),
            "duration_ms": plan.duration_ms,
            "clauses": [{"text": c.text, "start_ms": c.start_ms, "end_ms": c.end_ms} for c in plan.clauses],
            "shots": [{"kind": s.kind, "asset_path": s.asset_path,
                       "start_ms": s.start_ms, "end_ms": s.end_ms,
                       "chapter": s.chapter_label or "", "overlay": s.overlay or {}} for s in plan.shots],
            "meta": {"llm": bool(spec)},
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        with _LOCK:
            t = PREVIEW_TASKS.get(project_id)
            if t:
                t.update(state="ready", progress=100)
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            t = PREVIEW_TASKS.get(project_id)
            if t:
                t.update(state="failed", error=str(e)[-500:])
        print(f"preview failed: {e}")


def build_preview_payload(project_id: str, body: dict) -> dict:
    """前端分镜页数据：逐镜头（口播、素材、overlay、时间）。

    画面静帧不在这里出：服务器不再有渲染器，看画面得去成片台。
    """
    p = load_plan(project_id)
    props_path = preview_dir(project_id) / "props.json"
    if not p or not props_path.is_file():
        return {}
    props = json.loads(props_path.read_text(encoding="utf-8"))
    bundle_name = body.get("bundle") or ""
    shots_out = []
    props_shots = props.get("shots") or []
    clauses = p.get("clauses") or []
    for i, s in enumerate(p.get("shots") or []):
        # 该镜头覆盖到的子句文本（按时间重叠）
        start_ms, end_ms = s.get("start_ms") or 0, s.get("end_ms") or 0
        text = ""
        for c in clauses:
            if (c.get("start_ms") or 0) < end_ms and (c.get("end_ms") or 0) > start_ms:
                text += c.get("text", "")
        # 素材名 → bundle 内相对路径（回 /media/ 给前端预览）
        asset_url = None
        media_name = None
        if i < len(props_shots) and props_shots[i].get("media"):
            media_name = props_shots[i]["media"]
            rel = media_name.split("__", 1)[1] if "__" in media_name else media_name
            asset_url = f"/media/{bundle_name}/{rel}"
        overlay = (props_shots[i].get("overlay") if i < len(props_shots) else None) or s.get("overlay") or {}
        shots_out.append({
            "index": i,
            "kind": s.get("kind"),
            "text": text,
            "startMs": round(start_ms), "endMs": round(end_ms),
            "overlay": overlay or ({"chapterLabel": s.get("chapter", "")} if s.get("chapter") else {}),
            "media": asset_url,
            "mediaKind": (props_shots[i].get("mediaKind") if i < len(props_shots) else None),
        })
    return {
        "project_id": project_id,
        "durationMs": p.get("duration_ms"),
        "durationInFrames": props.get("durationInFrames"),
        "accent": props.get("accent"),
        "template": p.get("format"),
        "headline": props.get("headline"),
        "voice": p.get("voice"), "rate": p.get("rate"),
        "shots": shots_out,
    }
