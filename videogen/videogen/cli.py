"""videogen CLI: bundle in, video out.

    python -m videogen build <bundle_dir> -o out.mp4 [--work workdir]

流水线拆成两段（双通道排队的基础）：
  build_prep   配音(TTS) → AI 分镜(LLM) → 画面版式(props) → 剧照，网络等待为主
  build_render 画面渲染(Remotion) → 音效混音 → 封装 → 校验，吃 CPU 为主
两段之间靠 work_dir 里的 props.json / prep.json 落盘中转；build() = 两段顺序执行。
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import threading
from pathlib import Path

from . import brand as brand_kit
from . import compose, llm, remotion_render, tts, verify
from .config import DEFAULT_TEMPLATE, TEMPLATE_ALIAS, TEMPLATES
from .planner import (align_timeline, build_plan, build_plan_clone, build_plan_llm,
                      build_plan_macro, clause_units, split_clauses, sentence_spans,
                      unit_spans, plan_to_dict, plan_from_dict)
from .schemas import Content, Manifest, JobCancelled

log = logging.getLogger(__name__)

WORK = Path(__file__).resolve().parent.parent / "work"

# 模板注册表见 config.TEMPLATES（与 renderer/src/skin.ts 的 SKINS 一一对应）


# TTS 缓存目录按素材包共享（同包重建不重复花钱合成）；同一包并发预备时串行合成
_TTS_LOCKS: dict[str, threading.Lock] = {}
_TTS_LOCKS_GUARD = threading.Lock()


def _tts_lock(name: str) -> threading.Lock:
    with _TTS_LOCKS_GUARD:
        return _TTS_LOCKS.setdefault(name, threading.Lock())


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


def _report_of(progress):
    """统一的进度上报：兼容只接受 (stage, pct) 的旧回调。"""
    def report(stage: str, pct: int, detail: str | None = None) -> None:
        if progress:
            try:
                progress(stage, pct, detail)
            except TypeError:
                progress(stage, pct)
            except Exception:
                pass
    return report


def build_prep(bundle_dir: Path, work_dir: Path | None = None,
               voice: str | None = None, rate: str | None = None,
               clone: Path | None = None, format: str = DEFAULT_TEMPLATE,
               use_llm: bool = True, theme: str = "auto",
               disclaimer: str | None = None, watermark: bool = True,
               brand: dict | None = None, series: dict | None = None,
               job_id: str | None = None, progress=None,
               show_subtitles: bool = True, show_sources: bool = True,
               renderer: str = "remotion") -> dict:
    """流水线前半程：等外部 API 的活（配音/分镜/文案/版式）。

    产物全部落盘到 work_dir，渲染阶段凭 prep.json + props.json 继续，
    不再发起任何外部请求。返回的 dict 会原样传给 build_render。
    """
    report = _report_of(progress)
    bundle = Path(bundle_dir)
    work = Path(work_dir) if work_dir else WORK / bundle.name
    work.mkdir(parents=True, exist_ok=True)
    template = TEMPLATE_ALIAS.get(format, format)
    if template not in TEMPLATES:
        raise NotImplementedError(
            f"模板 '{format}' 不存在，可选：{'、'.join(TEMPLATES)}")

    content = Content.load(bundle / "content.json")
    manifest = Manifest.load(bundle / "manifest.json")
    # 固定开场白已下线（用户拍板：开场不加口播，直接进片）；账号级发音库合并保留
    user_terms = (brand or {}).get("terms") or {}
    if user_terms:
        content.pronunciations = {**(content.pronunciations or {}), **user_terms}
    badge = str((series or {}).get("badge") or "").strip()[:24]

    # 1) TTS + timeline（缓存目录按素材包共享：同包重建直接命中缓存，不再扣费）
    report("tts", 8, "正在合成配音（通常 30–90 秒）")
    tts_dir = work.parent / "_tts" / bundle.name
    with _tts_lock(bundle.name):
        mp3, events = tts.synthesize(content.script, content.pronunciations,
                                     tts_dir, voice=voice or tts.VOICE,
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
    elif template == "macro":
        # 宏观棱镜式：按「章」规划，不吃素材、不出设计卡；LLM 挂了走兜底章
        report("plan", 18, "AI 导演正在按章规划宏观解读")
        chapters = None
        if use_llm:
            units_all = clause_units(clauses)
            payload_units = [{"index": u["index"], "text": u["text"]} for u in units_all]
            asset_choices = [{"index": i, "kind": a.kind, "tags": a.tags, "summary": a.summary}
                             for i, a in enumerate(manifest.assets)]
            chapters = llm.design_chapters(content.script, payload_units, asset_choices)
        plan = build_plan_macro(content, clauses, clause_units(clauses), chapters)
        if chapters and isinstance(chapters.get("bg_asset"), int):
            assets_all = manifest.assets
            if 0 <= chapters["bg_asset"] < len(assets_all) \
                    and assets_all[chapters["bg_asset"]].kind == "image":
                plan.bg_asset = assets_all[chapters["bg_asset"]].file
        llm_used = chapters is not None
    else:
        if use_llm:
            spec = llm.design_shots(content.script, sent_payload, asset_payload, template=template)
        plan = build_plan_llm(content, manifest, clauses, spec["shots"],
                              spans=u_spans, interior=interior_units,
                              edge_spans=edge, template=template) if spec else None
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
    # macro 的文案在章节规划里一次成型，标题/金句卡也不存在，不需要这次改写
    if use_llm and template != "macro":
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
    # 品牌套件（高级档）最后压上来：品牌色盖过一切主题色，片尾卡加时长
    brand = brand_kit.apply_to_plan(plan, brand)
    duration_s = plan.duration_ms / 1000.0

    props = None
    if renderer == "remotion":
        # 预演复用：分镜预览已落盘 props.json（且配音已生成）时直接用它，
        # 保证预览所见与成片一致。helper 未就绪或数据不全时静默回落到正常路径。
        pre_props = None
        if job_id:
            try:
                from . import preview as _preview
                saved = _preview.load_plan(job_id)
                pdir = _preview.preview_dir(job_id)
                if saved and (pdir / "props.json").is_file():
                    cand = json.loads((pdir / "props.json").read_text(encoding="utf-8"))
                    pmp3 = pdir / "tts" / "voice.mp3"
                    if cand and pmp3.is_file():
                        pre_props = cand
                        mp3 = pmp3
                        duration_s = (saved.get("duration_ms") or duration_s * 1000) / 1000.0
            except Exception:
                pre_props = None
        if pre_props is None:
            # 正常路径：按导演分镜重新设计画面版式（TTS/分镜已在上面算好）
            report("props", 26, "正在设计画面版式")
            props = remotion_render.build_props(
                bundle, plan, content,
                title_card={"label": title_label, "keyword": title_kw},
                quote_card={"label": q_label, "quote": q_text},
                theme=getattr(plan, "theme", {}),
                show_subtitles=show_subtitles, show_sources=show_sources,
                disclaimer=disclaimer, template=template, watermark=watermark,
                brand=brand, series={"badge": badge} if badge else None)
        else:
            report("props", 30, "使用分镜预览确认过的画面设计")
            props = pre_props
        # 草稿分轨要用同一份 props：拷到 work 里存档（渲染阶段从这里读）
        try:
            (work / "props.json").write_text(
                json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    prep = {
        "work_dir": str(work),
        "bundle_dir": str(bundle),
        "template": template,
        "renderer": renderer,
        "plan": plan_to_dict(plan),
        # duration_ms = 真正用于混音/封装的时长（预演复用时可能与 plan 里的不同）
        "duration_ms": duration_s * 1000.0,
        "voice": str(mp3) if mp3 else None,
        # 时间戳质量：source=estimate 表示按字数估算，字幕/分镜会逐渐漂移（verify 会报）
        "tts_quality": tts.read_quality(tts_dir),
        "llm_used": bool(llm_used),
        "title_card": {"label": title_label, "keyword": title_kw},
        "quote_card": {"label": q_label, "quote": q_text},
    }
    try:
        (work / "prep.json").write_text(json.dumps(prep, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    except Exception:
        pass
    return prep


def build_render(bundle_dir: Path, out_mp4: Path, work_dir: Path | None = None,
                 prep: dict | None = None, bgm: Path | None = None,
                 renderer: str = "remotion", sfx: bool = True, sfx_mode: str = "full",
                 show_subtitles: bool = True, show_sources: bool = True,
                 job_id: str | None = None, progress=None,
                 vision: bool = True, defer_verify: bool = False,
                 cancel_check=None, visual_fn=None) -> Path:
    """流水线后半程：吃 CPU 的活（画面渲染/混音/封装/校验），全程不碰外部 API。

    prep = build_prep 的返回（缺省时从 work_dir/prep.json 读，兜底自愈）。
    defer_verify=True 时跳过末尾的画面校验（那是等外部视觉 API 的活），
    由调用方跑完后用 run_verify 在灶台之外补上——server 双通道走这条路。
    visual_fn：画面渲染的替身 (props, out_path, progress=, cancel_check=, audio=) -> Path，
    浏览器成片台挂单代理（server._agent_visual）用；None 直接报错——云端渲染已退役。
    """
    report = _report_of(progress)
    bundle = Path(bundle_dir)
    work = Path(work_dir) if work_dir else WORK / bundle.name
    if prep is None:
        prep = json.loads((work / "prep.json").read_text(encoding="utf-8"))
    template = prep.get("template") or "editorial"
    renderer = prep.get("renderer") or renderer
    plan = plan_from_dict(prep.get("plan") or {})
    duration_s = (prep.get("duration_ms") or plan.duration_ms) / 1000.0
    content = Content.load(bundle / "content.json")
    manifest = Manifest.load(bundle / "manifest.json")

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    if _cancelled():
        raise JobCancelled("任务已被停止")

    # ---- 混音备料：先于渲染算好 ----
    # 新版浏览器成片台领任务时要拿完整混音计划（配音/BGM/音效事件）自行合成，
    # 不能再等渲染完之后；云端混音/封装复用同一组变量，行为不变。
    # 阶段间隙的取消哨：混音/封装是阻塞的 ffmpeg 子进程，中途杀不了，
    # 所以只在它们开跑前拦——已开始的最后一步会跑完（几秒），不再往下走。
    if _cancelled():
        raise JobCancelled("任务已被停止")
    mode = sfx_mode if sfx else "off"
    # 音效：按"画面什么时候弹出一个东西"逐事件挂（开场/切换/卡片/数字/金句/结尾），
    # 不再有"全片最多 5 声"的老上限；音量由 compose.SFX_LEVELS 统一压在解说之下
    sfx_bank = compose.sfx_bank() if mode != "off" else {}
    sfx_events = compose.plan_sfx_events(plan, sfx_bank, mode=mode)
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
    mp3 = Path(prep["voice"]) if prep.get("voice") else None
    audio_plan = {"voice": mp3, "bgm": bgm, "sfx": sfx_events,
                  "duration_s": duration_s}

    # 画面渲染只剩一条路：客户的浏览器成片台（web-renderer 逐帧合成，
    # visual_fn 由 server._agent_visual 提供挂单/等件代理）。
    # 云端 Remotion CLI 渲染与 Node 成片台已于 2026-09-20 双双退役。
    if visual_fn is None:
        raise RuntimeError("缺少 visual_fn：画面渲染必须由浏览器成片台承接")
    report("render", 0, "等待浏览器成片台领取")
    props = json.loads((work / "props.json").read_text(encoding="utf-8"))
    visual = visual_fn(props, work / "visual.mp4",
                       progress=lambda p, d=None: report("render", max(0, min(p, 100)), d),
                       cancel_check=cancel_check,
                       audio=audio_plan)
    withsubs = visual

    # audio(sfx) -> mux -> verify
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    if _cancelled():
        raise JobCancelled("任务已被停止")
    if visual_fn is not None and getattr(visual_fn, "delivered_final", False):
        # 浏览器成片台已把混好音的完整成片整体交回：云端原样收下，
        # 不再混音/封装（重编码会把音轨丢掉，裁剪对成片也无意义）
        if Path(visual).resolve() != out_mp4.resolve():
            shutil.move(str(visual), str(out_mp4))
        report("mux", 94, "本机成片已交回")
    else:
        report("audio", 88, f"正在合成音效与背景音乐（{len(sfx_events)} 处声音）")
        audio_out = compose.mix_audio(mp3, duration_s, work, bgm=bgm, sfx_events=sfx_events,
                                      progress=lambda p, d=None: report("audio", p, d))
        if _cancelled():
            raise JobCancelled("任务已被停止")
        report("mux", 94, "正在封装成片")
        compose.mux(withsubs, audio_out, out_mp4, work)

    # 落盘剪映草稿清单（供「下载剪映草稿」用）：分镜/字幕时间点 + 配音与配置
    try:
        from . import remotion_render as _rr
        from .jianying_draft import dump_manifest
        media_dir = _rr.RENDERER / "public" / "media"
        # work 目录渲染后会被清理（容器重建也会丢），分轨草稿要用的输入存到成片旁
        keep = Path(out_mp4).with_suffix(".draftsrc")
        try:
            keep.mkdir(parents=True, exist_ok=True)
        except Exception:
            keep = None
        props_keep = None
        if keep is not None and renderer == "remotion" and (work / "props.json").is_file():
            try:
                props_keep = keep / "props.json"
                shutil.copyfile(work / "props.json", props_keep)
            except Exception:
                props_keep = None
        voice_keep = None
        if keep is not None:
            try:
                if mp3 and Path(mp3).is_file():
                    voice_keep = keep / "voice.mp3"
                    shutil.copyfile(mp3, voice_keep)
            except Exception:
                voice_keep = None
        sfx_rows = []
        for idx, (at_s, f, vol) in enumerate(sfx_events):
            f = Path(f)
            path = f
            if keep is not None and f.is_file():
                try:
                    path = keep / f"sfx_{idx:02d}{f.suffix or '.wav'}"
                    shutil.copyfile(f, path)
                except Exception:
                    path = f
            # volume/vol 两个键都写：剪映草稿读 volume，旧的草稿构建读 vol（此前只写了 vol，
            # 草稿里音效音量永远回落 50%、长度永远 1 秒）
            sfx_rows.append({"at_ms": at_s * 1000.0, "file": str(path),
                             "volume": vol, "vol": vol,
                             "duration_ms": _sfx_duration_ms(path)})
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
                      sfx_mode=mode, voice=str(voice_keep or mp3) if mp3 else None,
                      bgm=str(bgm) if bgm else None, render_id=job_id,
                      shots=shot_rows,
                      clauses=[{"text": c.text, "start_ms": c.start_ms, "end_ms": c.end_ms}
                               for c in plan.clauses],
                      sfx=sfx_rows,
                      props=str(props_keep) if props_keep else None)
    except Exception as exc:  # noqa: BLE001 - 清单失败不影响成片
        log.warning("draft manifest skipped", exc_info=exc)

    line = (f"renderer: {renderer} | director: {'llm' if prep.get('llm_used') else 'rules'} | "
            f"shots: {len(plan.shots)} | clauses: {len(plan.clauses)} | "
            f"duration: {duration_s:.1f}s -> {out_mp4}")
    if defer_verify:
        # 服务端走的就是这条（server 调 build_render 时 defer_verify=True），
        # 所以"这单渲完了"这行必须进日志：裸 print 没级别、没 rid，出事后
        # 对不上是哪一单、哪一分钟。下面 defer_verify=False 那条是命令行，
        # 输出给人看，保留 print。
        log.info("render done", extra={"renderer": renderer,
                                       "director": "llm" if prep.get("llm_used") else "rules",
                                       "shots": len(plan.shots),
                                       "clauses": len(plan.clauses),
                                       "duration_s": round(duration_s, 1),
                                       "out": str(out_mp4),
                                       "job": job_id})
        return out_mp4

    summaries = {a.file: a.summary for a in manifest.assets}
    report("verify", 0, "正在逐镜校验画面")
    vreport = verify.verify(out_mp4, plan, work, vision=vision,
                            summaries=summaries, bundle=bundle,
                            progress=lambda p, d=None: report("verify", p, d))
    print(line)
    print("verify:", "OK" if vreport["ok"] else "FAILED", vreport["errors"], vreport["warnings"])
    return out_mp4


def run_verify(bundle_dir: Path, out_mp4: Path, work_dir: Path | None = None,
               vision: bool = True, progress=None) -> dict:
    """画面校验独立入口（配合 build_render 的 defer_verify）。

    校验只依赖成片 + prep.json 里的 plan + 素材包 manifest，不吃渲染中间产物；
    放在灶台之外跑，等外部视觉 API 时不再占渲染位。
    """
    bundle = Path(bundle_dir)
    work = Path(work_dir) if work_dir else WORK / bundle.name
    prep = json.loads((work / "prep.json").read_text(encoding="utf-8"))
    plan = plan_from_dict(prep.get("plan") or {})
    manifest = Manifest.load(bundle / "manifest.json")
    summaries = {a.file: a.summary for a in manifest.assets}
    return verify.verify(Path(out_mp4), plan, work, vision=vision,
                         summaries=summaries, bundle=bundle, progress=progress)


def build(bundle_dir: Path, out_mp4: Path, work_dir: Path | None = None,
          voice: str | None = None, rate: str | None = None,
          bgm: Path | None = None, renderer: str = "remotion",
          progress=None, clone: Path | None = None,
          format: str = DEFAULT_TEMPLATE, sfx: bool = True,
          sfx_mode: str = "full",
          show_subtitles: bool = True, show_sources: bool = True,
          theme: str = "auto", disclaimer: str | None = None,
          use_llm: bool = True, job_id: str | None = None,
          vision: bool = True, watermark: bool = True,
          brand: dict | None = None, series: dict | None = None) -> Path:
    """bundle in, video out：前半程（等 API）+ 后半程（吃 CPU）顺序执行。"""
    prep = build_prep(bundle_dir, work_dir=work_dir, voice=voice, rate=rate,
                      clone=clone, format=format, use_llm=use_llm, theme=theme,
                      disclaimer=disclaimer, watermark=watermark, brand=brand,
                      series=series, job_id=job_id, progress=progress,
                      show_subtitles=show_subtitles, show_sources=show_sources,
                      renderer=renderer)
    return build_render(bundle_dir, out_mp4, work_dir=work_dir, prep=prep, bgm=bgm,
                        renderer=renderer, sfx=sfx, sfx_mode=sfx_mode,
                        show_subtitles=show_subtitles, show_sources=show_sources,
                        job_id=job_id, progress=progress, vision=vision)


def _sfx_duration_ms(path: Path, default: float = 1000.0) -> float:
    """音效时长（毫秒）：剪映草稿要把音效片段按真实长度摆上时间线。"""
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=20)
        val = float((p.stdout or "").strip())
        return val * 1000.0 if val > 0 else default
    except Exception:  # noqa: BLE001 - 量不到就按 1 秒摆，不影响出片
        return default


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
    b.add_argument("--renderer", default="remotion", choices=["remotion"])
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
    d.add_argument("-o", "--out", type=Path, default=None, help="输出的草稿 zip")
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
