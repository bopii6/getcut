"""生成剪映（JianYing 专业版）草稿包，供用户在剪映里二次剪辑。

分轨草稿（v2，推荐）：
    getcut_draft_<rid6>/
        draft_content.json          ← 时间线：画面 / 包装 / 字幕 / 配音 / 背景音乐 / 音效
        draft_meta_info.json
        media/*.mp4                 ← 按分镜切好的素材（可直接替换成自己的图片/视频）
        chrome/*.png                ← 每镜的包装层（带透明媒体窗）
        audio/*.mp3                 ← 按句切好的配音 + 背景音乐 + 音效
        draft_cover.jpg
    一键导入剪映.bat                 ← 拷贝草稿到剪映草稿库并改写素材绝对路径
    使用说明.txt

    每个元素都在自己的轨道上：文字能改字，图片/视频能替换，配音/BGM/音效各一条轨。

兜底（v1）：没有分轨资产时退回「整条成片按分镜切片 + 可编辑字幕」的单轨草稿。

格式基准：pyJianYingDraft (MIT) 的字段结构（JianYing 5.9 线，向上兼容）。
媒体路径在 JSON 里以 __VG_DRAFT_DIR__ 占位 + 正斜杠，由 bat 导入时改写为
真实路径的正斜杠形式（避免 JSON 反斜杠转义问题；Windows 文件 API 通用）。
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

_US = 1000  # 毫秒 -> 微秒
TMPL_DIR = Path(__file__).resolve().parent
PLACEHOLDER = "__VG_DRAFT_DIR__"

# 轨道渲染层级（大的在上）：画面 → 底板（带媒体窗洞）→ 卡片 → 字幕 → 叠加文字
RENDER_MEDIA, RENDER_BASE, RENDER_CARD = 0, 1, 2
RENDER_TEXT, RENDER_OVERLAY = 3, 4
RENDER_VOICE, RENDER_BGM, RENDER_SFX = 5, 6, 7

# 配音/字幕样式（字号与剪映定义一致；坐标见 NiwoVideo.tsx 的字幕位置）
SUBTITLE_SIZE = 9.0
SUBTITLE_Y = -0.40            # 负值向下：与成片字幕位置（画面 69% 高度处）对齐
SUBTITLE_MAX_W = 0.82
SUBTITLE_STROKE_W = 0.06
# 卡片文字的像素(1080x1920 画布) → 剪映字号 的换算系数（量出来的近似值，可整体微调）
TEXT_PX_TO_SIZE = 0.135


def _uid() -> str:
    return uuid.uuid4().hex


def _trange(start_ms: float, dur_ms: float) -> dict:
    return {"start": int(round(start_ms * _US)), "duration": int(round(dur_ms * _US))}


def _speed_entry() -> tuple[str, dict]:
    sid = _uid()
    return sid, {"curve_speed": None, "id": sid, "mode": 0, "speed": 1.0, "type": "speed"}


def _clip(transform_y: float = 0.0) -> dict:
    return {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False},
            "rotation": 0.0, "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": 0.0, "y": float(transform_y)}}


def _segment_base(material_id: str, target: dict, *, source: dict | None,
                  speed_id: str, render_index: int, volume: float = 1.0,
                  transform_y: float = 0.0, visual: bool = True) -> dict:
    seg = {
        "enable_adjust": True, "enable_color_correct_adjust": False,
        "enable_color_curves": True, "enable_color_match_adjust": False,
        "enable_color_wheels": True, "enable_lut": True, "enable_smart_color_adjust": False,
        "last_nonzero_volume": 1.0, "reverse": False, "track_attribute": 0,
        "track_render_index": 0,
        "visible": True,
        "id": _uid(), "material_id": material_id,
        "target_timerange": target,
        "source_timerange": source,
        "common_keyframes": [], "keyframe_refs": [],
        "speed": 1.0, "volume": volume,
        "extra_material_refs": [speed_id] if speed_id else [],
        "is_tone_modify": False,
    }
    if visual:
        seg["clip"] = _clip(transform_y)
        seg["uniform_scale"] = {"on": True, "value": 1.0}
    else:
        # 音频片段也必须带 clip 键（官方草稿里为 null）：剪映 11.5 的升级转换器
        # 对缺这个键的音频片段整段丢弃，升级后音频轨全部「媒体丢失」
        seg["clip"] = None
    seg["hdr_settings"] = None
    seg["render_index"] = render_index
    return seg


def _text_material(text: str, *, size: float = SUBTITLE_SIZE, bold: bool = True,
                   color: tuple[float, float, float] = (1.0, 1.0, 1.0),
                   max_w: float = SUBTITLE_MAX_W, stroke: bool = True) -> dict:
    style = {
        "fill": {"alpha": 1.0, "content": {
            "render_type": "solid", "solid": {"alpha": 1.0, "color": list(color)}}},
        "range": [0, len(text)], "size": float(size), "bold": bool(bold),
        "italic": False, "underline": False,
        "strokes": ([{"content": {"solid": {"alpha": 1.0, "color": [0.0, 0.0, 0.0]}},
                      "width": SUBTITLE_STROKE_W}] if stroke else []),
    }
    content = json.dumps({"styles": [style], "text": text}, ensure_ascii=False)
    return {
        "id": _uid(), "content": content, "typesetting": 0, "alignment": 1,
        "letter_spacing": 0.0, "line_spacing": 0.02, "line_feed": 1,
        "line_max_width": float(max_w), "force_apply_line_max_width": False,
        "check_flag": 15, "type": "text", "global_alpha": 1.0,
    }


def _parse_css_color(value: str) -> tuple[float, float, float]:
    """'rgb(r, g, b)' / 'rgba(...)' -> (0..1, 0..1, 0..1)"""
    import re
    m = re.search(r"rgba?\(([^)]+)\)", str(value or ""))
    if not m:
        return (1.0, 1.0, 1.0)
    parts = [p.strip() for p in m.group(1).split(",")]
    try:
        r, g, b = (max(0, min(255, float(parts[i]))) / 255.0 for i in range(3))
        return (round(r, 4), round(g, 4), round(b, 4))
    except Exception:
        return (1.0, 1.0, 1.0)


def _overlay_text_segments(plan: dict, shot: dict, tpl: dict, speeds: list) -> list[dict]:
    """把卡片上量出来的文字几何转成剪映文本片段（可改字的那一层）。"""
    width = float(plan.get("width") or 1080)
    height = float(plan.get("height") or 1920)
    start = float(shot.get("start_ms") or 0.0)
    dur = float(shot.get("end_ms") or start) - start
    segs: list[dict] = []
    if dur <= 0:
        return segs
    for item in shot.get("texts") or []:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        x = float(item.get("x") or 0.0)
        y = float(item.get("y") or 0.0)
        w = float(item.get("w") or 0.0)
        h = float(item.get("h") or 0.0)
        px_size = float(item.get("size") or 0.0)
        if px_size < 6 or w <= 0:
            continue
        size = max(3.0, min(60.0, round(px_size * TEXT_PX_TO_SIZE, 1)))
        bold = int(item.get("weight") or 400) >= 600
        tm = _text_material(text, size=size, bold=bold,
                           color=_parse_css_color(str(item.get("color") or "")),
                           max_w=max(0.1, min(0.98, (w + 60.0) / width)),
                           stroke=False)
        tpl["materials"]["texts"].append(tm)
        sid, sp = _speed_entry()
        speeds.append(sp)
        tx = (x + w / 2.0 - width / 2.0) / (width / 2.0)
        ty = -((y + h / 2.0 - height / 2.0) / (height / 2.0))
        seg = _segment_base(tm["id"], _trange(start, dur), source=None, speed_id=sid,
                            render_index=RENDER_OVERLAY, transform_y=ty)
        seg["clip"]["transform"]["x"] = round(tx, 4)
        seg["render_index"] = RENDER_OVERLAY
        segs.append(seg)
    return segs



def _video_material(mid: str, path: str, name: str, kind: str, duration_ms: float,
                    width: int, height: int) -> dict:
    """kind: video（分镜素材）｜photo（包装层 PNG，剪映按图片处理）"""
    dur_us = 10_800_000_000 if kind == "photo" else int(round(duration_ms * _US))
    return {
        "audio_fade": None, "category_id": "", "category_name": "local",
        "check_flag": 63487,
        "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0,
                 "upper_right_y": 0.0, "lower_left_x": 0.0, "lower_left_y": 1.0,
                 "lower_right_x": 1.0, "lower_right_y": 1.0},
        "crop_ratio": "free", "crop_scale": 1.0,
        "duration": dur_us,
        "height": int(height), "width": int(width),
        "id": mid, "local_material_id": "", "material_id": mid,
        "material_name": name, "media_path": "",
        "path": f"{PLACEHOLDER}/{path}", "type": kind,
    }


def _audio_material(mid: str, path: str, name: str, duration_ms: float) -> dict:
    return {
        "app_id": 0, "category_id": "", "category_name": "local", "check_flag": 3,
        "copyright_limit_type": "none", "duration": int(round(duration_ms * _US)),
        "effect_id": "", "formula_id": "", "id": mid, "local_material_id": mid,
        "music_id": mid, "name": name, "path": f"{PLACEHOLDER}/{path}",
        "source_platform": 0, "type": "extract_music", "wave_points": [],
    }


def dump_manifest(path, *, video: str, duration_ms: float, fps: int = 30,
                  width: int = 1080, height: int = 1920, title: str = "",
                  subtitles: bool = True, sources: bool = True, fmt: str = "",
                  sfx_mode: str = "", voice: str | None = None, bgm: str | None = None,
                  render_id: str | None = None,
                  shots: list | None = None, clauses: list | None = None,
                  sfx: list | None = None, props: str | None = None,
                  draft_dir: str | None = None) -> None:
    """渲染结束时把草稿需要的元数据落在成片旁（<成片名>.draft.json）。"""
    data = {"version": 2, "video": video, "duration_ms": float(duration_ms),
            "fps": int(fps), "width": int(width), "height": int(height),
            "title": title, "subtitles": bool(subtitles), "sources": bool(sources),
            "format": fmt, "sfx_mode": sfx_mode,
            "voice": voice, "bgm": bgm, "render_id": render_id,
            "shots": shots or [], "clauses": clauses or [], "sfx": sfx or [],
            "props": props, "draft_dir": draft_dir}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_manifest(video_path) -> dict | None:
    """读取成片旁的草稿清单；旧成片没有则返回 None。"""
    p = Path(video_path).with_suffix(".draft.json")
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------- 分轨草稿

def build_multitrack_content(plan: dict) -> dict:
    """按 draft_plan.json 构造多轨 draft_content.json。"""
    tpl = json.load(open(TMPL_DIR / "jianying_template.json", encoding="utf-8"))
    tpl["name"] = plan.get("title") or "getcut 成片"
    width = int(plan.get("width") or 1080)
    height = int(plan.get("height") or 1920)
    tpl["canvas_config"] = {"width": width, "height": height, "ratio": "original"}
    tpl["duration"] = int(round(float(plan.get("duration_ms") or 0) * _US))
    tpl["fps"] = float(plan.get("fps") or 30)

    speeds: list[dict] = []
    media_segs: list[dict] = []
    base_segs: list[dict] = []
    card_segs: list[dict] = []
    text_segs: list[dict] = []
    overlay_segs: list[dict] = []
    voice_segs: list[dict] = []
    bgm_segs: list[dict] = []
    sfx_segs: list[dict] = []

    # 底板轨：一张图铺满全片（页面底/纸卡/面板留洞/标题带/页脚）
    base = plan.get("base")
    if base:
        dur_all = float(plan.get("duration_ms") or 0.0)
        fid = _uid()
        tpl["materials"]["videos"].append(
            _video_material(fid, base, Path(base).name, "photo", dur_all, width, height))
        sid, sp = _speed_entry()
        speeds.append(sp)
        base_segs.append(_segment_base(fid, _trange(0, dur_all),
                                       source=_trange(0, dur_all), speed_id=sid,
                                       render_index=RENDER_BASE))

    for shot in plan.get("shots") or []:
        start = float(shot.get("start_ms") or 0.0)
        dur = float(shot.get("end_ms") or start) - start
        if dur <= 0:
            continue
        # 画面轨：素材片段（可整段替换成自己的图片/视频）
        media = shot.get("media")
        if media:
            mdur = float(shot.get("media_duration_ms") or 0.0) or dur
            fid = _uid()
            tpl["materials"]["videos"].append(
                _video_material(fid, media, Path(media).name, "video", mdur, width, height))
            sid, sp = _speed_entry()
            speeds.append(sp)
            media_segs.append(_segment_base(fid, _trange(start, dur),
                                            source=_trange(0, dur), speed_id=sid,
                                            render_index=RENDER_MEDIA))
        # 卡片轨：叠加信息的图形（对比卡/数字卡/事实卡…），文字已抽到叠加文字轨
        card = shot.get("card") or shot.get("chrome")
        if card:
            fid = _uid()
            tpl["materials"]["videos"].append(
                _video_material(fid, card, Path(card).name, "photo", dur, width, height))
            sid, sp = _speed_entry()
            speeds.append(sp)
            card_segs.append(_segment_base(fid, _trange(start, dur),
                                           source=_trange(0, dur), speed_id=sid,
                                           render_index=RENDER_CARD))
        # 叠加文字轨：卡片上的文字，逐条可改字
        overlay_segs.extend(_overlay_text_segments(plan, shot, tpl, speeds))

    # 字幕轨：一句一个文本片段，位置与成片一致（画面下方）
    for cl in plan.get("subtitles") or []:
        text = (cl.get("text") or "").strip()
        start = float(cl.get("start_ms") or 0.0)
        dur = float(cl.get("end_ms") or start) - start
        if not text or dur <= 0:
            continue
        tm = _text_material(text)
        tpl["materials"]["texts"].append(tm)
        sid, sp = _speed_entry()
        speeds.append(sp)
        seg = _segment_base(tm["id"], _trange(start, dur), source=None, speed_id=sid,
                            render_index=RENDER_TEXT, transform_y=SUBTITLE_Y)
        seg["render_index"] = RENDER_TEXT
        text_segs.append(seg)

    # 配音轨：按句切好的片段，逐句可替换
    for cl in plan.get("voice_clips") or []:
        f = cl.get("file")
        if not f:
            continue
        start = float(cl.get("start_ms") or 0.0)
        dur = float(cl.get("end_ms") or start) - start
        if dur <= 0:
            continue
        adur = float(cl.get("duration_ms") or 0.0) or dur
        aid = _uid()
        am = _audio_material(aid, f, Path(f).name, adur)
        tpl["materials"]["audios"].append(am)
        sid, sp = _speed_entry()
        speeds.append(sp)
        voice_segs.append(_segment_base(am["id"], _trange(start, dur),
                                        source=_trange(0, min(dur, adur)), speed_id=sid,
                                        render_index=RENDER_VOICE, visual=False))

    # 背景音乐轨
    bgm = plan.get("bgm") or None
    if bgm and bgm.get("file"):
        dur_total = float(plan.get("duration_ms") or 0.0)
        bdur = float(bgm.get("duration_ms") or 0.0) or dur_total
        aid = _uid()
        am = _audio_material(aid, bgm["file"], Path(bgm["file"]).name, bdur)
        tpl["materials"]["audios"].append(am)
        sid, sp = _speed_entry()
        speeds.append(sp)
        bgm_segs.append(_segment_base(am["id"], _trange(0, dur_total),
                                      source=_trange(0, min(dur_total, bdur)), speed_id=sid,
                                      render_index=RENDER_BGM, volume=float(bgm.get("volume") or 0.2),
                                      visual=False))

    # 音效轨：每个音效独立片段，起点/音量都保留了
    for ev in plan.get("sfx") or []:
        f = ev.get("file")
        if not f:
            continue
        dur = float(ev.get("duration_ms") or 0.0) or 1000.0
        aid = _uid()
        am = _audio_material(aid, f, Path(f).name, dur)
        tpl["materials"]["audios"].append(am)
        sid, sp = _speed_entry()
        speeds.append(sp)
        sfx_segs.append(_segment_base(am["id"], _trange(float(ev.get("at_ms") or 0.0), dur),
                                      source=_trange(0, dur), speed_id=sid,
                                      render_index=RENDER_SFX,
                                      # 音量键：volume 是现行写法，vol 是旧清单里的写法
                                      volume=float(ev.get("volume") or ev.get("vol") or 0.5),
                                      visual=False))

    tracks = []
    if media_segs:
        tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": False,
                       "name": "画面", "segments": media_segs, "type": "video"})
    if base_segs:
        tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": False,
                       "name": "底板", "segments": base_segs, "type": "video"})
    if card_segs:
        tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": False,
                       "name": "卡片", "segments": card_segs, "type": "video"})
    if text_segs:
        tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": False,
                       "name": "字幕", "segments": text_segs, "type": "text"})
    if overlay_segs:
        tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": False,
                       "name": "叠加文字", "segments": overlay_segs, "type": "text"})
    if voice_segs:
        tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": False,
                       "name": "配音", "segments": voice_segs, "type": "audio"})
    if bgm_segs:
        tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": False,
                       "name": "背景音乐", "segments": bgm_segs, "type": "audio"})
    if sfx_segs:
        tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": False,
                       "name": "音效", "segments": sfx_segs, "type": "audio"})

    tpl["materials"]["speeds"] = speeds
    tpl["tracks"] = tracks
    _clamp_to_timeline(tpl)
    # track_render_index 是「轨内第几个片段」（0 起），不是渲染层级——
    # 官方草稿如此，新版剪映的升级转换器按它重排轨内顺序
    for track in tracks:
        for i, seg in enumerate(track["segments"]):
            seg["track_render_index"] = i
    _validate_content(tpl)
    return tpl


def _clamp_to_timeline(tpl: dict) -> None:
    """任何片段都不许超出草稿时长。

    字幕/配音的尾句常比成片长一点（TTS 按整句给时长，最后一句常常顶过最后一帧）。
    不夹取的话剪映会把时间轴拉长，草稿比成片多出一截空画面；旧兜底路径
    build_flat_content:445 一直有这道夹取，多轨路径以前没有。整段都在片外的直接丢掉。
    """
    cap = int(tpl.get("duration") or 0)
    if cap <= 0:
        return
    kept: list[dict] = []
    for track in tpl["tracks"]:
        segs: list[dict] = []
        for seg in track["segments"]:
            target = seg["target_timerange"]
            start = int(target["start"])
            if start >= cap:
                continue
            target["start"] = start
            target["duration"] = min(int(target["duration"]), cap - start)
            if target["duration"] <= 0:
                continue
            segs.append(seg)
        track["segments"] = segs
        if segs:
            kept.append(track)
    tpl["tracks"] = kept


def _validate_content(tpl: dict) -> None:
    """自检：片段引用的素材/附加素材必须都存在（悬空引用会让剪映拒绝打开）。"""
    ids = {m["id"] for v in tpl["materials"].values() if isinstance(v, list)
           for m in v if isinstance(m, dict) and m.get("id")}
    for track in tpl["tracks"]:
        for seg in track["segments"]:
            if seg["material_id"] not in ids:
                raise RuntimeError(f"草稿自检失败：{track['name']} 轨有悬空素材引用")
            for ref in seg.get("extra_material_refs") or []:
                if ref not in ids:
                    raise RuntimeError(f"草稿自检失败：{track['name']} 轨有悬空附加素材引用")


# ---------------------------------------------------------------- 兜底：整条切片

def build_flat_content(manifest: dict, draft_dir_placeholder: str = PLACEHOLDER) -> dict:
    """旧路径：成片按分镜切片 + 可编辑字幕（没有分轨资产时使用）。"""
    media = f"{draft_dir_placeholder}/media"
    tpl = json.load(open(TMPL_DIR / "jianying_template.json", encoding="utf-8"))
    tpl["name"] = manifest.get("title") or "getcut 成片"
    tpl["canvas_config"] = {"width": manifest.get("width", 1080),
                            "height": manifest.get("height", 1920), "ratio": "original"}
    tpl["duration"] = int(round(manifest["duration_ms"] * _US))
    tpl["fps"] = int(manifest.get("fps", 30))

    vid = _uid()
    tpl["materials"]["videos"].append({
        "audio_fade": None, "category_id": "", "category_name": "local",
        "check_flag": 63487,
        "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0,
                 "upper_right_y": 0.0, "lower_left_x": 0.0, "lower_left_y": 1.0,
                 "lower_right_x": 1.0, "lower_right_y": 1.0},
        "crop_ratio": "free", "crop_scale": 1.0,
        "duration": int(round(manifest["duration_ms"] * _US)),
        "height": int(manifest.get("height", 1920)),
        "width": int(manifest.get("width", 1080)),
        "id": vid, "local_material_id": "", "material_id": vid,
        "material_name": manifest.get("video_name", "final.mp4"),
        "media_path": "", "path": f"{media}/final.mp4", "type": "video",
    })

    segments: list[dict] = []
    speeds: list[dict] = []
    shots = manifest.get("shots") or [{"start_ms": 0, "end_ms": manifest["duration_ms"]}]
    for shot in shots:
        start = max(0.0, float(shot.get("start_ms", 0)))
        end = min(float(manifest["duration_ms"]), float(shot.get("end_ms", manifest["duration_ms"])))
        if end - start <= 0:
            continue
        sid, sp = _speed_entry()
        speeds.append(sp)
        seg = _segment_base(vid, _trange(start, end - start),
                            source=_trange(start, end - start),
                            speed_id=sid, render_index=0)
        seg["audio_fade"] = None
        segments.append(seg)
    tracks = [{"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": True,
               "name": "", "segments": segments, "type": "video"}]

    if manifest.get("subtitles") is False and manifest.get("clauses"):
        tsegs: list[dict] = []
        for cl in manifest["clauses"]:
            text = (cl.get("text") or "").strip()
            start = float(cl.get("start_ms", 0))
            end = min(float(cl.get("end_ms", start)), float(manifest["duration_ms"]))
            if not text or end - start <= 0:
                continue
            tm = _text_material(text)
            tpl["materials"]["texts"].append(tm)
            sid, sp = _speed_entry()
            speeds.append(sp)
            seg = _segment_base(tm["id"], _trange(start, end - start), source=None,
                                speed_id=sid, render_index=1, transform_y=SUBTITLE_Y)
            seg["render_index"] = 1
            tsegs.append(seg)
        if tsegs:
            tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": True,
                           "name": "", "segments": tsegs, "type": "text"})

    tpl["materials"]["speeds"] = speeds
    tpl["tracks"] = tracks
    for track in tracks:
        for i, seg in enumerate(track["segments"]):
            seg["track_render_index"] = i
    return tpl


# ---------------------------------------------------------------- 打包

def build_meta_info(draft_name: str, duration_ms: float) -> dict:
    mi = json.load(open(TMPL_DIR / "jianying_meta_template.json", encoding="utf-8"))
    mi["draft_id"] = _uid()
    mi["draft_name"] = draft_name
    mi["draft_fold_path"] = PLACEHOLDER
    mi["draft_root_path"] = ""
    mi["tm_duration"] = int(round(duration_ms * _US))
    return mi


_BAT = r"""@echo off
setlocal
set "DEST=%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft"
set "DESTF=%DEST:\=/%"
set "NAME=__FOLDER__"

if not exist "%DEST%" (
  echo [X] JianYing draft folder not found: %DEST%
  echo     See README.txt for manual install steps.
  pause
  exit /b 1
)

echo Copying draft ...
robocopy "%~dp0__FOLDER__" "%DEST%\__FOLDER__" /E /NFL /NDL /NJH /NJS >nul
if errorlevel 8 (
  echo [X] Copy failed. Please copy folder "__FOLDER__" manually to:
  echo     %DEST%
  pause
  exit /b 1
)

echo Fixing media paths ...
powershell -NoProfile -Command "$d='%DESTF%/__FOLDER__'; $f=$d+'/draft_content.json'; $t=[IO.File]::ReadAllText($f); [IO.File]::WriteAllText($f, $t.Replace('__VG_DRAFT_DIR__', $d)); $f2=$d+'/draft_meta_info.json'; $t2=[IO.File]::ReadAllText($f2); [IO.File]::WriteAllText($f2, $t2.Replace('__VG_DRAFT_DIR__', $d))"

echo.
echo Done! Restart JianYing - the draft appears in the draft list.
pause
"""


def build_bat(draft_folder_name: str) -> str:
    return _BAT.replace("__FOLDER__", draft_folder_name)


README = """getcut 剪映草稿 · 使用说明
================================

这是什么
  一个剪映专业版（Windows 桌面版）**分轨草稿**。时间线上每样东西都在自己的轨道：
    · 画面     —— 按分镜切好的素材片段。要换图/换视频：右键片段「替换」，位置和时长自动保持
    · 底板     —— 页面底 / 纸卡 / 面板（媒体窗留洞）/ 标题带 / 页脚，一张图铺满全片
    · 卡片     —— 每镜的「叠加信息」图形：对比卡、数字卡、事实卡、观点卡、角标、章节标签…
                  可单独拖动 / 改时长 / 删除 / 换成自己的图
    · 字幕     —— 一句一条，双击即可改字
    · 叠加文字 —— 卡片上的文字（标题/数字/标签/对比两侧…），逐条可改字、改颜色、改位置
    · 配音     —— 按句切好的配音，可单独重录/替换某一句
    · 背景音乐 —— 已循环铺满全片，音量默认 20%；右键「替换」换歌
    · 音效     —— 开场、卡片、强调音效各自独立，可单独替换或删除

  关于「叠加文字」的字体：成片用的是思源黑体特粗，剪映里用的是剪映自带字体，
  所以字形会有差异；字号与位置是量出来的近似值（定位是准的）。全选这一轨
  可以一次性调字体/字号。

怎么导入（推荐）
  1. 把整个压缩包解压到任意位置
  2. 关闭正在运行的剪映
  3. 双击「一键导入剪映.bat」
  4. 打开剪映 → 首页草稿列表即可看到这条草稿

手动导入（bat 不工作时）
  1. 解压后，把 getcut_draft_xxx 整个文件夹复制到：
     %LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft\\
  2. 用记事本打开其中的 draft_content.json 和 draft_meta_info.json，
     把里面的 __VG_DRAFT_DIR__ 全部替换为该文件夹的实际路径
     ⚠ 路径要用正斜杠（C:/Users/...），反斜杠会被 JSON 当转义符、草稿会打不开
  3. 打开剪映即可看到草稿

小提示
  · 素材轨/卡片轨的片段都是 1080x1920 画布（已按成片位置摆好），替换后仍在原位
  · 成片渲染时若烧入了字幕，草稿里另有独立字幕轨；两套不会同时出现

常见问题
  · 打开草稿提示素材丢失：说明草稿文件夹被移动过，重新跑一次 bat，
    或在剪映里对缺失素材点「查找」并指向草稿文件夹
  · Mac 版剪映：本包仅支持 Windows 专业版
  · 草稿建立在剪映 5.9 兼容格式上，新版剪映打开时会自动升级
"""


def make_cover(final_mp4: Path, out_jpg: Path) -> bool:
    """从成片取一帧做草稿封面（列表里显示真实画面而非黑块）。失败返回 False。"""
    import subprocess
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", "3", "-i", str(final_mp4),
             "-frames:v", "1", "-vf", "scale=540:-2", str(out_jpg)],
            capture_output=True, timeout=60)
        return r.returncode == 0 and Path(out_jpg).is_file()
    except Exception:
        return False


def draft_dir_for(video: Path) -> Path:
    return Path(video).with_suffix(".draft")


def jianying_draft_dir() -> Path:
    """剪映专业版的草稿库目录（Windows）。"""
    import os
    return (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "JianyingPro"
            / "User Data" / "Projects" / "com.lveditor.draft")


def prepare_draft(video: Path, manifest: dict, progress=None) -> Path | None:
    """确保这条成片的分轨草稿资产已备好（切素材 / 收浏览器交回的图层 / 切片配音）。

    渲染一结束就在后台跑这一步：等用户走到导出页，草稿通常已经就绪，点「一键导入剪映」
    秒装——不用再让用户干等 1-2 分钟。已经是新的就直接复用。
    返回草稿目录；不需要（成片台没交回图层）或失败时返回 None。
    """
    from . import draft_build

    video = Path(video)
    plan_dir = Path(manifest.get("draft_dir") or draft_dir_for(video))
    try:
        if draft_build.load_plan(plan_dir) and draft_build.plan_fresh(plan_dir, video):
            return plan_dir
        layers = draft_build.layers_dir_for(video)
        if not layers.is_dir():
            return None        # 老成片没有分轨图层：交给「整条切片」粗草稿兜底
        draft_build.build_draft_assets(manifest, plan_dir, progress=progress,
                                       layers_dir=layers)
        return plan_dir
    except Exception as exc:  # noqa: BLE001 - 备草稿失败不该影响成片与下载
        log.warning("draft prepare skipped", exc_info=exc)
        return None


def install_draft(zip_path: Path, dest_root: Path | None = None) -> Path:
    """把草稿 zip 装进剪映草稿库（等价于「一键导入剪映.bat」，但带 JSON 校验）。

    路径统一改写成正斜杠绝对路径：反斜杠会被 JSON 当转义符，草稿会打不开。
    """
    import shutil
    import zipfile

    zip_path = Path(zip_path)
    dest_root = Path(dest_root) if dest_root else jianying_draft_dir()
    if not dest_root.is_dir():
        raise RuntimeError(f"找不到剪映草稿目录：{dest_root}（请先运行一次剪映）")
    with zipfile.ZipFile(zip_path) as z:
        folder = next((n.split("/")[0] for n in z.namelist() if "/" in n), "")
        if not folder:
            raise RuntimeError("草稿包结构异常")
        tmp = dest_root / f"_vg_import_{uuid.uuid4().hex[:8]}"
        try:
            z.extractall(tmp)
            dest = dest_root / folder
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(tmp / folder), str(dest))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    destf = str(dest).replace("\\", "/")
    for f in ("draft_content.json", "draft_meta_info.json"):
        p = dest / f
        text = p.read_text(encoding="utf-8").replace(PLACEHOLDER, destf)
        json.loads(text)          # 自检：坏 JSON 直接抛错，不塞给剪映
        p.write_text(text, encoding="utf-8", newline="")
    return dest


def build_zip(manifest: dict, final_mp4: Path, voice_mp3: Path | None,
              out_zip: Path, progress=None) -> Path:
    """打包剪映草稿 zip：优先分轨草稿，资产缺失/失败时退回整条切片草稿。"""
    import tempfile
    import zipfile

    from . import draft_build

    final_mp4 = Path(final_mp4)
    rid = (manifest.get("render_id") or uuid.uuid4().hex)[:6]
    title = (manifest.get("title") or "成片").strip() or "成片"
    folder = f"getcut_draft_{rid}"
    draft_name = f"{title}（getcut·分轨）"

    plan_dir = Path(manifest.get("draft_dir") or draft_dir_for(final_mp4))
    plan = draft_build.load_plan(plan_dir) if draft_build.plan_fresh(plan_dir, final_mp4) else None
    if plan is None:
        # 首次导出：现做分轨资产（切素材 + 收浏览器交回的图层 + 切配音）
        try:
            plan = draft_build.build_draft_assets(
                manifest, plan_dir, progress=progress,
                layers_dir=draft_build.layers_dir_for(final_mp4))
        except Exception as exc:  # noqa: BLE001 - 分轨失败不阻塞，退回整条草稿
            log.warning("multitrack draft skipped", exc_info=exc)
            plan = None

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cover = td / "draft_cover.jpg"
        has_cover = make_cover(final_mp4, cover)

        if plan is not None:
            content = build_multitrack_content(plan)
            meta = build_meta_info(draft_name, plan.get("duration_ms") or manifest["duration_ms"])
            if has_cover:
                meta["draft_cover"] = f"{PLACEHOLDER}/draft_cover.jpg"
                content["cover"] = f"{PLACEHOLDER}/draft_cover.jpg"
            out_zip.parent.mkdir(parents=True, exist_ok=True)
            # MP4/PNG/MP3 are already compressed. Deflating them again burns CPU
            # before the first response byte without making the archive smaller.
            with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_STORED) as z:
                z.writestr(f"{folder}/draft_content.json",
                           json.dumps(content, ensure_ascii=False, indent=1),
                           compress_type=zipfile.ZIP_DEFLATED)
                z.writestr(f"{folder}/draft_meta_info.json",
                           json.dumps(meta, ensure_ascii=False, indent=1),
                           compress_type=zipfile.ZIP_DEFLATED)
                # 底板（根目录单图）+ 画面/卡片/音频目录
                files = [plan_dir / plan["base"]] if plan.get("base") else []
                for sub in ("media", "cards", "audio"):
                    files += [f for f in sorted((plan_dir / sub).glob("*")) if f.is_file()]
                for f in files:
                    if f.is_file():
                        z.write(f, f"{folder}/{f.relative_to(plan_dir).as_posix()}",
                                compress_type=zipfile.ZIP_STORED)
                if has_cover:
                    z.write(cover, f"{folder}/draft_cover.jpg", compress_type=zipfile.ZIP_STORED)
                z.writestr("一键导入剪映.bat", build_bat(folder).replace("\n", "\r\n"),
                           compress_type=zipfile.ZIP_DEFLATED)
                z.writestr("使用说明.txt", README.replace("\n", "\r\n"),
                           compress_type=zipfile.ZIP_DEFLATED)
            return out_zip

        # 兜底：整条成片按分镜切片
        draft_name = f"{title}（getcut）"
        content = build_flat_content({**manifest, "title": draft_name},
                                     draft_dir_placeholder=PLACEHOLDER)
        meta = build_meta_info(draft_name, manifest["duration_ms"])
        if has_cover:
            meta["draft_cover"] = f"{PLACEHOLDER}/draft_cover.jpg"
            content["cover"] = f"{PLACEHOLDER}/draft_cover.jpg"
        out_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_STORED) as z:
            z.writestr(f"{folder}/draft_content.json",
                       json.dumps(content, ensure_ascii=False, indent=1),
                       compress_type=zipfile.ZIP_DEFLATED)
            z.writestr(f"{folder}/draft_meta_info.json",
                       json.dumps(meta, ensure_ascii=False, indent=1),
                       compress_type=zipfile.ZIP_DEFLATED)
            z.write(final_mp4, f"{folder}/media/final.mp4", compress_type=zipfile.ZIP_STORED)
            if voice_mp3 and Path(voice_mp3).is_file():
                z.write(voice_mp3, f"{folder}/media/voice.mp3", compress_type=zipfile.ZIP_STORED)
            if has_cover:
                z.write(cover, f"{folder}/draft_cover.jpg", compress_type=zipfile.ZIP_STORED)
            z.writestr("一键导入剪映.bat", build_bat(folder).replace("\n", "\r\n"),
                       compress_type=zipfile.ZIP_DEFLATED)
            z.writestr("使用说明.txt", README.replace("\n", "\r\n"),
                       compress_type=zipfile.ZIP_DEFLATED)
    return out_zip


def build_zip_cached(manifest: dict, final_mp4: Path, voice_mp3: Path | None,
                     cache_zip: Path, progress=None) -> Path:
    """Build an archive once and atomically reuse it for later downloads."""
    import os

    final_mp4 = Path(final_mp4)
    cache_zip = Path(cache_zip)
    plan_dir = Path(manifest.get("draft_dir") or draft_dir_for(final_mp4))
    refs = [final_mp4]
    plan_file = plan_dir / "draft_plan.json"
    if plan_file.is_file():
        refs.append(plan_file)
    try:
        if cache_zip.is_file() and cache_zip.stat().st_mtime_ns >= max(
                ref.stat().st_mtime_ns for ref in refs if ref.is_file()):
            return cache_zip
    except OSError:
        pass

    cache_zip.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_zip.with_name(f".{cache_zip.name}.{uuid.uuid4().hex}.part")
    try:
        build_zip(manifest, final_mp4, voice_mp3, tmp, progress=progress)
        os.replace(tmp, cache_zip)
    finally:
        tmp.unlink(missing_ok=True)
    return cache_zip
