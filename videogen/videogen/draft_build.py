"""剪映分轨草稿 · 素材准备。

把成片的「合成结果」拆回可编辑的多轨工程：
    media/   按分镜切好的素材片段（图片也合成为视频，位置与成片一致）
    chrome/  每镜的「包装层」透明 PNG（纸卡/面板/卡片/标题带；素材窗留洞）
    audio/   按句切好的配音、循环好的背景音乐、用到的音效
    draft_plan.json  轨道清单（jianying_draft.build_draft_content 消费）

坐标基准与 renderer/src/NiwoVideo.tsx 保持一致（editorial 版面）：
    纸卡 (91,124,892,1432)｜面板 (115,596,849,844)｜媒体窗 (151,667,778,440)
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

FRAME_W, FRAME_H = 1080, 1920
# 媒体窗入场动画在成片里是 ~7 帧淡入，草稿里也给素材加个短淡入，观感接近
FADE_IN_S = 0.20

# 版式几何的唯一来源：renderer/src/layouts.json（TS 渲染器读同一份）。
# 改模板的纸卡/面板/媒体窗尺寸只需要改那个文件，草稿的洞与素材位自动跟上。
_LAYOUTS_PATH = Path(__file__).resolve().parent.parent / "renderer" / "src" / "layouts.json"
_layouts_cache: dict | None = None


def _layouts() -> dict:
    global _layouts_cache
    if _layouts_cache is None:
        try:
            _layouts_cache = json.loads(_LAYOUTS_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 配置缺失时退化为满屏，不阻断出片
            _layouts_cache = {}
    return _layouts_cache


# 媒体窗挖洞的变体（只有它需要在底板上留洞）
CLONE_VARIANTS = {"statement_media"}

# 旧 format 别名 → 现模板 id
_ID_ALIAS = {"portrait_editorial": "editorial", "portrait_full": "portrait"}


def _normalize_id(fmt: str) -> str:
    key = (fmt or "").strip()
    return _ID_ALIAS.get(key, key)


def layout_of(fmt: str) -> str:
    """模板 id → 骨架名。旧别名先归一，未知模板回落 editorial。"""
    key = _normalize_id(fmt)
    entry = _layouts().get(key) or {}
    return entry.get("layout") or "editorial"


def media_rect(fmt: str) -> tuple[int, int, int, int]:
    """该模板媒体窗在整帧里的 (x, y, w, h)：只有带内嵌媒体窗的骨架才有洞，其余满屏。"""
    entry = _layouts().get(_normalize_id(fmt)) or _layouts().get("editorial") or {}
    panel, win = entry.get("panel"), entry.get("mediaWin")
    if panel and win:
        return (panel["left"] + win["left"], panel["top"] + win["top"],
                win["width"], win["height"])
    return (0, 0, FRAME_W, FRAME_H)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + (p.stderr or "")[-2500:])


def _dur_ms(shot: dict) -> float:
    return max(0.0, float(shot["end_ms"]) - float(shot["start_ms"]))


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _shot_clip(asset: Path, dur_s: float, rect: tuple[int, int, int, int],
               out: Path, layout: str, zoom: bool = True) -> None:
    """把素材合成到 1080x1920 画布的指定矩形里（与成片画面一致）。"""
    x, y, w, h = rect
    dur_s = max(dur_s, 0.5)
    if _is_image(asset):
        # 图片：模糊铺底 + 完整显示（niwo 规则：图片不裁切）
        fit = (
            "[1:v]split=2[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            "boxblur=16:2,eq=brightness=-0.05[bgb];"
            f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fgs];"
            "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30"
        )
        # 轻微推近（成片里静帧有运镜，草稿里保留一点呼吸感）
        if zoom:
            fit += ",zoompan=z='min(1+0.0006*on,1.05)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=%dx%d" % (w, h)
        cmd = ["ffmpeg", "-y", "-v", "error",
               "-f", "lavfi", "-i", f"color=c=black:s={FRAME_W}x{FRAME_H}:r=30",
               "-loop", "1", "-t", f"{dur_s:.3f}", "-i", str(asset),
               "-filter_complex",
               f"{fit}[m];[0:v][m]overlay={x}:{y},fade=t=in:st=0:d={FADE_IN_S},format=yuv420p[v]",
               "-map", "[v]", "-t", f"{dur_s:.3f}", "-r", "30",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-an", str(out)]
    else:
        cmd = ["ffmpeg", "-y", "-v", "error",
               "-f", "lavfi", "-i", f"color=c=black:s={FRAME_W}x{FRAME_H}:r=30",
               "-stream_loop", "-1", "-t", f"{dur_s:.3f}", "-i", str(asset),
               "-filter_complex",
               f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
               f"setsar=1,fps=30[m];"
               f"[0:v][m]overlay={x}:{y},fade=t=in:st=0:d={FADE_IN_S},format=yuv420p[v]",
               "-map", "[v]", "-t", f"{dur_s:.3f}", "-r", "30",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-an", str(out)]
    _run(cmd)


def _cut_audio(src: Path, start_ms: float, end_ms: float, out: Path) -> None:
    """按时间点切一段配音（对齐到分句边界，两端加极短淡入淡出防爆音）。"""
    dur = max(0.05, (end_ms - start_ms) / 1000.0)
    fade_out = max(0.0, dur - 0.02)
    af = f"afade=t=in:d=0.008,afade=t=out:st={fade_out:.3f}:d=0.02"
    _run(["ffmpeg", "-y", "-v", "error",
          "-ss", f"{start_ms / 1000.0:.3f}", "-to", f"{end_ms / 1000.0:.3f}",
          "-i", str(src), "-af", af, "-c:a", "libmp3lame", "-q:a", "3", str(out)])


def _prepare_bgm(src: Path, dur_s: float, out: Path) -> None:
    """背景音乐循环铺满全片，结尾 3 秒淡出（音量在剪映里以片段音量 20% 呈现）。"""
    fade = max(0.5, dur_s - 3.0)
    _run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src),
          "-t", f"{dur_s:.3f}", "-af", f"afade=t=out:st={fade:.2f}:d=3",
          "-c:a", "libmp3lame", "-q:a", "3", str(out)])


def _probe_ms(path: Path) -> float:
    """读媒体时长（毫秒）；失败返回 0，由调用方兜底。"""
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                           capture_output=True, text=True, timeout=30)
        return max(0.0, float(p.stdout.strip()) * 1000.0)
    except Exception:
        return 0.0


def layers_dir_for(video: Path) -> Path:
    """成片台交回剪映分轨图层的目录：挨着成片放，交没到手一眼就看得见。"""
    return Path(video).with_suffix(".layers")


def import_layers(layers_dir: Path | None, folder: Path, ids: list[str]) -> dict:
    """把成片台在浏览器里渲好的分轨图层搬进草稿目录，返回 {镜头id: 文字几何}。

    少任何一张就抛错：宁可让调用方退回「整条成片一条轨」的粗草稿，也不能给剪映
    一份缺层的工程——那种工程打开来看是坏的，比不给更糟。
    """
    src = Path(layers_dir) if layers_dir else None
    if not src or not src.is_dir():
        raise RuntimeError("成片台没交回分轨图层：渲完请留在成片台页面，等它把图层出完")

    def need(rel: str, min_bytes: int = 1024) -> Path:
        p = src / rel
        if not p.is_file():
            raise RuntimeError(f"分轨图层不完整，缺 {rel}")
        if p.stat().st_size < min_bytes:
            raise RuntimeError(f"分轨图层 {rel} 是空的（{p.stat().st_size} 字节）")
        return p

    shutil.copyfile(need("base.png"), folder / "base.png")
    (folder / "cards").mkdir(parents=True, exist_ok=True)
    for i in ids:
        f = need(f"cards/{i}.png")
        shutil.copyfile(f, folder / "cards" / f.name)
    tp = need("texts.json", 2)      # 全片没有一张文字卡时 {} 也是合法结果
    try:
        raw = json.loads(tp.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 坏 JSON 同样按缺层处理
        raise RuntimeError(f"分轨图层的文字几何读不出来：{exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("分轨图层的文字几何格式不对")
    return {i: (raw.get(i) or []) for i in ids}


def build_draft_assets(manifest: dict, folder: Path, progress=None,
                       layers_dir: Path | None = None) -> dict:
    """产出草稿资产 + draft_plan.json，返回 plan 字典。

    失败会抛异常，由调用方兜底（退回旧的「整条成片切片」草稿）。
    layers_dir=成片台交回的剪映图层目录，缺它就没有分轨可言。
    """

    def report(pct: int, detail: str = "") -> None:
        if progress:
            try:
                progress(pct, detail)
            except TypeError:
                progress(pct)
            except Exception:
                pass

    folder = Path(folder)
    for sub in ("media", "cards", "audio"):
        (folder / sub).mkdir(parents=True, exist_ok=True)

    shots = manifest.get("shots") or []
    clauses = manifest.get("clauses") or []
    fmt = manifest.get("format") or ""
    layout = layout_of(fmt)
    rect = media_rect(fmt)
    fps = int(manifest.get("fps") or 30)
    duration_ms = float(manifest.get("duration_ms") or 0.0)

    if any((s.get("overlay") or {}).get("variant") in CLONE_VARIANTS for s in shots):
        raise RuntimeError("clone 版面暂不支持分轨草稿")

    # 1) 每镜素材片段
    plan_shots: list[dict] = []
    for i, s in enumerate(shots):
        entry = {"index": i, "kind": s.get("kind") or "", "start_ms": float(s["start_ms"]),
                 "end_ms": float(s["end_ms"]), "card": f"cards/shot_{i:03d}.png",
                 "media": None, "media_kind": None, "texts": []}
        asset = s.get("asset")
        if asset and Path(asset).is_file() and (s.get("kind") not in ("title_card", "quote_card")):
            name = f"media/shot_{i:03d}.mp4"
            report(min(80, int(i / max(1, len(shots)) * 80)), f"正在切分镜素材 {i + 1}/{len(shots)}")
            _shot_clip(Path(asset), _dur_ms(s) / 1000.0, rect, folder / name, layout,
                       zoom=layout == "editorial")
            entry["media"] = name
            entry["media_kind"] = "image" if _is_image(Path(asset)) else "video"
            entry["media_duration_ms"] = _probe_ms(folder / name)
        plan_shots.append(entry)
    report(80, "正在取回浏览器交回的剪映图层")

    # 2) 底板层（一张）+ 卡片层（每镜一张）+ 文字几何：成片台在浏览器里渲好交回的
    raw_texts = import_layers(layers_dir, folder,
                              [f"shot_{i:03d}" for i in range(len(plan_shots))])
    for i, entry in enumerate(plan_shots):
        entry.pop("chrome", None)
        entry["texts"] = raw_texts.get(f"shot_{i:03d}") or []
    report(88, "正在处理配音与音轨")

    # 3) 配音按句切段
    voice = manifest.get("voice")
    voice_clips: list[dict] = []
    subtitles = [{"text": (cl.get("text") or "").strip(),
                  "start_ms": float(cl.get("start_ms") or 0.0),
                  "end_ms": float(cl.get("end_ms") or 0.0)}
                 for cl in clauses if (cl.get("text") or "").strip()]
    if voice and Path(voice).is_file():
        for i, cl in enumerate(clauses):
            text = (cl.get("text") or "").strip()
            start = float(cl.get("start_ms") or 0.0)
            end = min(float(cl.get("end_ms") or start), duration_ms)
            if not text or end - start <= 0.05:
                continue
            name = f"audio/voice_{i:03d}.mp3"
            _cut_audio(Path(voice), start, end, folder / name)
            voice_clips.append({"start_ms": start, "end_ms": end, "file": name,
                                "duration_ms": _probe_ms(folder / name)})
        shutil.copy2(voice, folder / "audio" / "voice_full.mp3")

    # 4) 背景音乐
    bgm_entry = None
    bgm = manifest.get("bgm")
    if bgm and Path(bgm).is_file() and duration_ms > 0:
        name = "audio/bgm.mp3"
        _prepare_bgm(Path(bgm), duration_ms / 1000.0, folder / name)
        bgm_entry = {"file": name, "volume": 0.2, "name": Path(bgm).stem,
                     "duration_ms": _probe_ms(folder / name)}

    # 5) 音效
    sfx_entries: list[dict] = []
    for i, ev in enumerate(manifest.get("sfx") or []):
        src = Path(str(ev.get("file") or ""))
        if not src.is_file():
            continue
        name = f"audio/sfx_{i:02d}{src.suffix.lower() or '.mp3'}"
        shutil.copy2(src, folder / name)
        sfx_entries.append({"at_ms": float(ev.get("at_ms") or 0.0), "file": name,
                            "volume": float(ev.get("volume") or ev.get("vol") or 0.5),
                            "name": src.stem,
                            "duration_ms": _probe_ms(folder / name)})

    plan = {
        "version": 3, "fps": fps, "width": FRAME_W, "height": FRAME_H,
        "duration_ms": duration_ms, "title": manifest.get("title") or "成片",
        "layout": layout, "media_rect": list(rect),
        "base": "base.png",
        "shots": plan_shots, "subtitles": subtitles, "voice_clips": voice_clips,
        "bgm": bgm_entry, "sfx": sfx_entries,
        "voice_full": "audio/voice_full.mp3" if (folder / "audio" / "voice_full.mp3").is_file() else None,
    }
    (folder / "draft_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    report(96, "草稿分轨已就绪")
    return plan


def load_plan(folder: Path) -> dict | None:
    p = Path(folder) / "draft_plan.json"
    if not p.is_file():
        return None
    try:
        plan = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return plan if isinstance(plan, dict) and plan.get("version") == 3 else None


def plan_fresh(folder: Path, video: Path) -> bool:
    """资产是否已备好且不比成片旧。"""
    folder = Path(folder)
    if not (folder / "draft_plan.json").is_file():
        return False
    try:
        return (folder / "draft_plan.json").stat().st_mtime >= Path(video).stat().st_mtime
    except OSError:
        return False
