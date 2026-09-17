"""videogen CLI: bundle in, video out.

    python -m videogen build <bundle_dir> -o out.mp4 [--work workdir]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import compose, llm, overlays, remotion_render, subtitle, tts, verify
from .config import DEFAULT_TEMPLATE, TEMPLATE_ALIAS, TEMPLATES
from .config import OUTPUTS as _OUTPUTS
from .planner import (align_timeline, build_plan, build_plan_clone, build_plan_llm,
                      clause_units, split_clauses, sentence_spans, unit_spans)
from .schemas import Content, Manifest, HIGHLIGHT

WORK = Path(__file__).resolve().parent.parent / "work"

# 模板注册表见 config.TEMPLATES（与 renderer/src/skin.ts 的 SKINS 一一对应）


# 标题卡关键词兜底：命中脚本里的事件性强动词就用；都没命中退回标题前几字。
# 关键词列表保持通用，不能只覆盖某一类选题。
_HOT_WORDS = ("宣布", "推出", "发布", "引发", "突破", "升级", "暴跌", "暴涨", "扩张",
              "停摆", "放缓", "减产", "裁员", "收购", "起诉", "警告", "曝光",
              "紧急", "首次", "转向", "回归", "签约", "停产", "断供", "涨价", "降价")


def _keyword_of(script: str, fallback: str) -> str:
    for kw in _HOT_WORDS:
        if kw in script:
            return kw
    return fallback


def _lighten(hex_color: str, amount: float = 0.18) -> str:
    """把 #rrggbb 亮一档，用于 accentSoft。非法输入原样返回。"""
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
    """把 LLM refine_copy 的返回应用到镜头 overlay 上（键为镜头 index 的字符串）。"""
    per_shot = refined.get("shots") or {}
    for i, shot in enumerate(plan.shots):
        patch = per_shot.get(str(i)) or per_shot.get(i)
        if not patch:
            continue
        if shot.kind == "callout":
            for k in ("label", "number", "caption"):
                if patch.get(k):
                    shot.overlay[k] = patch[k]
        elif shot.kind == "panel":
            for k, v in patch.items():
                if k == "variant" or v in (None, "", []):
                    continue
                shot.overlay[k] = v


def _quote_of(script: str) -> tuple[str, str]:
    """金句卡兜底：从结尾句里提炼（≤8 字），任何选题都适用。

    LLM 正常时这里不会被用到；这条只是保证兜底不再是单选题特供。
    """
    tail = script.rstrip("。！？!?,， ")        # 去掉句尾标点后的最后一段
    for sep in ("。", "！", "？", "；"):
        if sep in tail:
            tail = tail.rsplit(sep, 1)[-1]
    for sep in ("，", ","):
        tail = tail.rsplit(sep, 1)[-1]
    quote = tail.strip()[:8] or "值得盯紧"
    return "划重点", quote


def build(bundle_dir: Path, out_mp4: Path, work_dir: Path | None = None,
          voice: str | None = None, rate: str | None = None,
          bgm: Path | None = None, renderer: str = "remotion",
          progress=None, clone: Path | None = None,
          format: str = DEFAULT_TEMPLATE, sfx: bool = True,
          sfx_mode: str = "full",
          show_subtitles: bool = True, show_sources: bool = True,
          theme: str = "auto", disclaimer: str | None = None,
          use_llm: bool = True, job_id: str | None = None) -> Path:
    def report(stage: str, pct: int, detail: str | None = None) -> None:
        if progress:
            try:
                progress(stage, pct, detail)
            except TypeError:
                progress(stage, pct)
            except Exception:
                pass
    bundle = Path(bundle_dir)
    work = Path(work_dir) if work_dir else WORK / bundle.name
    work.mkdir(parents=True, exist_ok=True)
    template = TEMPLATE_ALIAS.get(format, format)
    if template not in TEMPLATES:
        raise NotImplementedError(
            f"模板 '{format}' 不存在，可选：{'、'.join(TEMPLATES)}")

    content = Content.load(bundle / "content.json")
    manifest = Manifest.load(bundle / "manifest.json")

    # 1) TTS + timeline
    report("tts", 8, "正在合成配音（通常 30–90 秒）")
    mp3, events = tts.synthesize(content.script, content.pronunciations,
                                 work / "tts", voice=voice or tts.VOICE,
                                 rate=rate or tts.RATE)
    clauses = align_timeline(split_clauses(content), events)

    # storyboard director: LLM plans shots + card copy; rules are the fallback
    # 子句单元制：导演按 1-3 个子句成镜，镜头可细到 3-5 秒（整句制最短也要 6-8 秒）
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
    report("plan", 18, "AI 导演正在规划分镜与设计卡")
    spec = None
    if clone:
        plan = build_plan_clone(content, clauses,
                                json.loads(Path(clone).read_text(encoding="utf-8")),
                                manifest, bundle)
        llm_used = False
    else:
        if use_llm:
            spec = llm.design_shots(content.script, sent_payload, asset_payload)
        plan = build_plan_llm(content, manifest, clauses, spec["shots"],
                              spans=u_spans, interior=interior_units,
                              edge_spans=edge) if spec else None
        llm_used = plan is not None
        if plan is not None and spec.get("theme"):
            plan.theme = spec["theme"]
        if plan is not None and spec.get("style_pack"):
            plan.style_pack = spec["style_pack"]
        if plan is None:
            plan = build_plan(content, manifest, clauses)

    title_label = "AI 观察｜突发信号"
    title_kw = _keyword_of(content.script, content.title[:4])
    q_label, q_text = _quote_of(content.script)
    # 标题/金句文案优先走 LLM 改写（规则版本仅作兜底），避免固定关键词只适配单条片子
    if use_llm:
        refined = llm.refine_copy(
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
    # 用户显式指定主题色时覆盖
    if theme and theme != "auto" and theme.startswith("#"):
        plan.theme = {"accent": theme, "accentSoft": _lighten(theme)}
    duration_s = plan.duration_ms / 1000.0

    if renderer == "remotion":
        # Remotion renders the full visual track (layout, subs, overlays)
        report("props", 26, "正在设计画面版式")
        props = remotion_render.build_props(
            bundle, plan, content,
            title_card={"label": title_label, "keyword": title_kw},
            quote_card={"label": q_label, "quote": q_text},
            theme=getattr(plan, "theme", {}),
            show_subtitles=show_subtitles, show_sources=show_sources,
            disclaimer=disclaimer, template=template)
        # 草稿分轨要用同一份 props：拷到 work 里存档（renderer/props.json 会被下次渲染覆盖）
        try:
            (work / "props.json").write_text(
                json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
        # 分镜剧照：先把几张关键画面拍出来，等待期间用户能看到片子长什么样
        if job_id:
            report("props", 32, "正在拍分镜剧照")
            try:
                stills = remotion_render.render_stills(props, _OUTPUTS, job_id)
                if stills:
                    report("props", 38, f"分镜剧照 {len(stills)} 张已就绪")
            except Exception:
                pass
        report("render", 0, "启动渲染引擎")
        visual = remotion_render.render_visual(
            props, work / "visual.mp4",
            progress=lambda p, d=None: report("render", max(0, min(p, 100)), d))
        withsubs = visual
    else:
        # legacy PIL compositor (fallback)
        hook = content.hook_headline
        lines: list[tuple[str, list[tuple[int, int]]]] = []
        if hook and hook.lines:
            for ln in hook.lines:
                lines.append((hook.plain(ln), hook.highlight_spans(ln)))
        else:
            lines.append((content.title[:14], []))
            if len(lines[0][0]) < len(content.title):
                lines.append((content.title[14:26], []))
        base_png = overlays.make_base(lines, content.sources,
                                      disclaimer or remotion_render.DISCLAIMER, work / "base.png")
        overlays.make_title_card(title_label, title_kw, "SIGNAL / 01", work / "art_title.png")
        overlays.make_quote_card(q_label, q_text, work / "art_quote.png")
        segments = []
        for idx, shot in enumerate(plan.shots):
            media = None
            if shot.asset_path:
                media = bundle / shot.asset_path
                if not media.is_file():
                    media = None
            segments.append(compose.build_segment(base_png, shot, media, work, idx))
        cat = compose.concat(segments, work)
        if show_subtitles:
            ass_path = work / "subs.ass"
            subtitle.build_ass(plan, ass_path)
            withsubs = compose.burn_subtitles(cat, ass_path, work)
        else:
            withsubs = cat

    # audio(sfx) -> mux -> verify
    mode = sfx_mode if sfx else "off"
    sfx_bank = compose.synth_sfx(work) if mode != "off" else {}
    # 档位：off 无｜hook 仅开场｜accent 开场+设计卡轻点｜full 再加金句强调
    sfx_events = []
    if mode != "off" and "open" in sfx_bank:
        sfx_events.append((0.08, sfx_bank["open"], 0.5))
    if mode in ("accent", "full") and not clone:
        for shot in plan.shots:
            if len(sfx_events) >= 5:
                break
            if shot.kind in ("panel", "callout") and "card" in sfx_bank:
                sfx_events.append((shot.start_ms / 1000.0 + 0.03, sfx_bank["card"], 0.4))
    if mode == "full" and not clone:
        quote = next((q for q in plan.shots if q.kind == "quote_card"), None)
        if quote and "emphasis" in sfx_bank:
            sfx_events.append((quote.start_ms / 1000.0 + 0.05, sfx_bank["emphasis"], 0.45))
    report("audio", 88, "正在合成音效与背景音乐")
    # 风格包 -> 默认 BGM（用户没指定时按形态气质自动配）
    if bgm is None:
        pack_bgm = {"data": "bgm-electronic", "opinion": "bgm-trap",
                    "profile": "bgm-cinematic", "investigation": "bgm-news"}
        want = pack_bgm.get(getattr(plan, "style_pack", ""), "")
        music_dir = Path(__file__).resolve().parent.parent / "assets" / "music"
        if want and music_dir.is_dir():
            hit = next((f for f in sorted(music_dir.glob("*.mp3")) if f.stem.startswith(want)), None)
            if hit:
                bgm = hit
                report("audio", 85, f"自动配乐：{bgm.stem}")

    audio = compose.mix_audio(mp3, duration_s, work, bgm=bgm, sfx_events=sfx_events,
                              progress=lambda p, d=None: report("audio", p, d))
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    report("mux", 94, "正在封装成片")
    compose.mux(withsubs, audio, out_mp4, work)

    # 落盘剪映草稿清单（供「下载剪映草稿」用）：分镜/字幕时间点 + 配音与配置
    try:
        from . import remotion_render as _rr
        from .jianying_draft import dump_manifest
        media_dir = _rr.RENDERER / "public" / "media"
        shot_rows = []
        props_shots = (props.get("shots") if renderer == "remotion" and props else None) or []
        for i, s in enumerate(plan.shots):
            row = {"start_ms": s.start_ms, "end_ms": s.end_ms, "kind": s.kind,
                   "chapter": s.chapter_label or ""}
            row["overlay"] = dict(s.overlay or {})
            if i < len(props_shots):
                name = props_shots[i].get("media")
                if name:
                    # renderer/public/media 里的副本：与成片用的是同一份素材
                    row["asset"] = str(media_dir / name)
            shot_rows.append(row)
        dump_manifest(out_mp4.with_suffix(".draft.json"),
                      video=str(out_mp4), duration_ms=plan.duration_ms, fps=30,
                      width=1080, height=1920, title=content.title,
                      subtitles=show_subtitles, sources=show_sources, fmt=template,
                      sfx_mode=mode, voice=str(Path(mp3)) if mp3 else None,
                      bgm=str(bgm) if bgm else None, render_id=job_id,
                      shots=shot_rows,
                      clauses=[{"text": c.text, "start_ms": c.start_ms, "end_ms": c.end_ms}
                               for c in plan.clauses],
                      sfx=[{"at_ms": at_s * 1000.0, "file": str(f), "vol": vol}
                           for at_s, f, vol in sfx_events],
                      props=str(work / "props.json") if (work / "props.json").is_file() else None)
    except Exception as exc:  # 清单失败不影响成片
        print(f"draft manifest skipped: {exc}")

    summaries = {a.file: a.summary for a in manifest.assets}
    report("verify", 0, "正在逐镜校验画面")
    vreport = verify.verify(out_mp4, plan, work, vision=True,
                            summaries=summaries, bundle=bundle,
                            progress=lambda p, d=None: report("verify", p, d))
    print(f"renderer: {renderer} | director: {'llm' if llm_used else 'rules'} | shots: {len(plan.shots)} | clauses: {len(plan.clauses)} | "
          f"duration: {duration_s:.1f}s -> {out_mp4}")
    print("verify:", "OK" if vreport["ok"] else "FAILED", vreport["errors"], vreport["warnings"])
    return out_mp4


def build_draft_zip(video: Path, out_zip: Path | None = None, progress=None,
                    install: bool = False) -> Path:
    """把已渲染的成片打包成剪映草稿 zip（分轨；缺清单/资产时退回整条切片）。

    install=True 时顺带装进剪映草稿库（等价于包里的「一键导入剪映.bat」）。
    """
    from . import jianying_draft as jyd
    video = Path(video)
    manifest = jyd.load_manifest(video)
    if manifest is None:
        raise SystemExit(f"找不到草稿清单：{video.with_suffix('.draft.json')}")
    voice = manifest.get("voice")
    out_zip = Path(out_zip) if out_zip else video.with_suffix(".draft.zip")
    zip_path = jyd.build_zip(manifest, video, Path(voice) if voice else None, out_zip,
                             progress=progress)
    if install:
        dest = jyd.install_draft(zip_path)
        print(f"installed: {dest}")
    return zip_path


def main() -> None:
    ap = argparse.ArgumentParser(prog="videogen")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build a video from a bundle directory")
    b.add_argument("bundle", type=Path)
    b.add_argument("-o", "--out", type=Path, default=Path("out.mp4"))
    b.add_argument("--work", type=Path, default=None)
    b.add_argument("--voice", default=None)
    b.add_argument("--rate", default=None)
    b.add_argument("--bgm", type=Path, default=None)
    b.add_argument("--renderer", default="remotion", choices=["remotion", "pil"])
    b.add_argument("--clone", type=Path, default=None)
    b.add_argument("--format", default=DEFAULT_TEMPLATE,
                   choices=list(TEMPLATES) + list(TEMPLATE_ALIAS),
                   help="模板：editorial 杂志 / finance 财经 / minimal 极简白 / "
                        "bleed 全出血 / news 新闻 / retro 复古 / portrait 竖屏满屏")
    b.add_argument("--no-sfx", action="store_true", help="关闭音效")
    b.add_argument("--no-subtitles", action="store_true", help="关闭字幕")
    b.add_argument("--no-sources", action="store_true", help="关闭来源行")
    b.add_argument("--theme", default="auto", help="主题色 hex（如 #a44231）或 auto")
    b.add_argument("--disclaimer", default=None)
    b.add_argument("--no-llm", action="store_true", help="禁用 LLM 导演/文案，走规则引擎")
    d = sub.add_parser("draft", help="export a JianYing draft zip for a rendered video")
    d.add_argument("video", type=Path, help="成片 mp4（旁边要有同名 .draft.json）")
    d.add_argument("-o", "--out", type=Path, default=None, help="输出的草稿 zip 路径")
    d.add_argument("--install", action="store_true", help="同时装进剪映草稿库（免手动导入）")
    a = ap.parse_args()
    if a.cmd == "draft":
        out = build_draft_zip(a.video, a.out, install=a.install)
        print(f"draft: {out}")
        return
    build(a.bundle, a.out, a.work, a.voice, a.rate, a.bgm,
          renderer=a.renderer, clone=a.clone, format=a.format, sfx=not a.no_sfx,
          show_subtitles=not a.no_subtitles, show_sources=not a.no_sources,
          theme=a.theme, disclaimer=a.disclaimer, use_llm=not a.no_llm)


if __name__ == "__main__":
    main()
