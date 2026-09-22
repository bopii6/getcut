"""Stage 5 (parity): automated visual/timing verification of the finished video.

Mirrors niwo's checking_visuals stage: sample frames per shot to catch broken
media, and validate subtitle/audio/video alignment.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .llm import vision_check as llm_vision
from . import tts
# 素材窗矩形（原 overlays.py 常量，PIL 合成器退役后唯此一处还在用）
MEDIA = (151, 667, 929, 1107)
from .planner import Plan


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return -1.0


def _frame_at(video: Path, t: float, tmp: Path) -> Path | None:
    out = tmp / f"chk_{t:.2f}.png"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}",
                        "-i", str(video), "-frames:v", "1", str(out)],
                       capture_output=True)
    if r.returncode:
        return None
    return out if out.is_file() and out.stat().st_size else None


def _silence_ends(audio: Path) -> list[float]:
    """纯人声轨里的"停顿结束点"（单位秒）= 下一段话实际开口的时刻。"""
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(audio),
         "-af", "silencedetect=noise=-35dB:d=0.3", "-f", "null", "-"],
        capture_output=True, text=True)
    ends: list[float] = []
    for line in (r.stderr or "").splitlines():
        if "silence_end:" in line:
            try:
                ends.append(float(line.split("silence_end:")[1].split("|")[0].strip()))
            except ValueError:
                continue
    return ends


def _drift_stats(clause_starts_ms: list[float], pause_ends_s: list[float],
                 tol_s: float = 1.0) -> tuple[float | None, int]:
    """字幕开始时刻 vs 语音实际开口时刻的漂移（毫秒，正=字幕滞后语音）。

    单调配对：每条字幕（跳过首条，前面没有停顿）在 ±tol_s 内找"最近的
    停顿结束点"，且配对顺序不得倒退。不足 5 个有效配对返回 (None, n)——
    停顿太少时宁可不报，也不报假数。"""
    pairs: list[float] = []
    used_until = -1
    for cs in sorted(clause_starts_ms)[1:]:
        t = cs / 1000.0
        best_j, best_d = -1, tol_s
        for j, pe in enumerate(pause_ends_s):
            if j <= used_until:
                continue
            d = abs(pe - t)
            if d <= best_d:
                best_j, best_d = j, d
        if best_j >= 0:
            pairs.append((t - pause_ends_s[best_j]) * 1000.0)
            used_until = best_j
    if len(pairs) < 5:
        return None, len(pairs)
    pairs.sort()
    return pairs[len(pairs) // 2], len(pairs)


def verify(video: Path, plan: Plan, work: Path, vision: bool = False,
           summaries: dict | None = None, bundle: Path | None = None,
           progress=None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    def report(pct: int, detail: str | None = None) -> None:
        if progress:
            try:
                progress(pct, detail)
            except TypeError:
                progress(pct)
            except Exception:
                pass

    dur = _probe_duration(video)
    if dur <= 0:
        return {"ok": False, "errors": ["无法读取成片时长"], "warnings": []}
    if abs(dur - plan.duration_ms / 1000) > 1.5:
        errors.append(f"成片时长 {dur:.1f}s 与计划 {plan.duration_ms/1000:.1f}s 偏差过大")

    tmp = Path(tempfile.mkdtemp(prefix="vg_verify_"))
    # 1. media shots: media region must have detail (not black/blank)
    shots_total = len(plan.shots) or 1
    for i, shot in enumerate(plan.shots):
        if shot.asset_path is None:
            continue
        mid = (shot.start_ms + shot.end_ms) / 2000.0
        f = _frame_at(video, min(mid, max(dur - 0.2, 0)), tmp)
        if f is None:
            errors.append(f"镜头 {i}: 无法取样帧")
            continue
        img = Image.open(f).crop(MEDIA).convert("L")
        hist = img.histogram()
        total = sum(hist)
        dark = sum(hist[:24]) / total
        extrema = sum(1 for v in hist if v > total * 0.001)
        if dark > 0.995 and img.mean() < 6:
            errors.append(f"镜头 {i} ({shot.asset_path}): 媒体区域近乎全黑，素材可能加载失败")
        elif extrema < 4:
            warnings.append(f"镜头 {i}: 媒体区域内容过于单一")
        report(int((i + 1) / shots_total * 70), f"抽检画面 {i + 1} / {shots_total} 镜")

    # 2. subtitle timing sanity
    if not plan.clauses:
        errors.append("没有生成任何字幕")
    else:
        if plan.clauses[0].start_ms > 1600:
            warnings.append(f"首条字幕出现较晚 ({plan.clauses[0].start_ms:.0f}ms)")
        if plan.clauses[-1].end_ms < plan.duration_ms - 2000:
            warnings.append("末条字幕结束过早")
        for a, b in zip(plan.clauses, plan.clauses[1:], strict=False):
            if b.start_ms < a.start_ms - 0.1:
                errors.append(f"字幕时间轴倒挂: {a.text!r} -> {b.text!r}")
                break

    # 2.4 subtitle-vs-voice alignment（2026-09-22：此前质检不查对齐，
    # 估算时间戳造成的累积漂移直接漏到成片——开头同步、越往后字幕越滞后）
    prep_path = work / "prep.json"
    voice_path: Path | None = None
    tts_quality: dict | None = None
    try:
        prep = json.loads(prep_path.read_text(encoding="utf-8"))
        if prep.get("voice"):
            voice_path = Path(prep["voice"])
        q = prep.get("tts_quality")
        tts_quality = q if isinstance(q, dict) else None
    except Exception:  # noqa: BLE001 - 缺 prep 不挡其余质检
        pass
    if tts_quality is None and voice_path is not None:
        tts_quality = tts.read_quality(voice_path.parent)
    if tts_quality and tts_quality.get("source") == "estimate" \
            and int(tts_quality.get("anchors") or 0) < 3:
        warnings.append(
            f"配音时间戳来自按字数估算，且停顿锚点不足（渠道 {tts_quality.get('provider', '?')}），"
            f"字幕可能与语音逐渐漂移")
    if voice_path is not None and voice_path.is_file() and len(plan.clauses) >= 6:
        report(70, "正在核对字幕与配音的对齐")
        pauses = _silence_ends(voice_path)
        starts = [c.start_ms for c in plan.clauses]
        median, n = _drift_stats(starts, pauses)
        if median is not None:
            if abs(median) >= 800:
                errors.append(
                    f"字幕与配音明显不同步：中位偏差 {median:+.0f}ms（{n} 个句锚点）")
            elif abs(median) >= 300:
                warnings.append(
                    f"字幕与配音有漂移倾向：中位偏差 {median:+.0f}ms（{n} 个句锚点）")

    # 2.5 vision check (parity: niwo checking_visuals uses a vision model)
    if vision and summaries and bundle:
        checked = 0
        for i, shot in enumerate(plan.shots):
            if checked >= 4 or not shot.asset_path:
                continue
            mid = (shot.start_ms + shot.end_ms) / 2000.0
            f = _frame_at(video, min(mid, max(dur - 0.2, 0)), tmp)
            if f is None:
                continue
            desc = summaries.get(shot.asset_path, "")[:60]
            report(70 + int(checked / 4 * 28), f"AI 视觉复核第 {checked + 1} / 4 镜")
            res = llm_vision(f, f"这是竖屏短视频的一个镜头画面。请检查：1画面是否正常显示"
                             f"（无黑屏、无破图、无乱码）；2画面内容是否与描述相符。画面描述：{desc}")
            checked += 1
            if res is None:
                continue
            if res.get("ok") is False:
                warnings.append(f"镜头 {i}: 视觉校验未过 —— {res.get('reason', '')[:60]}")

    # 3. audio stream present
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_name", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True)
    if not r.stdout.strip():
        errors.append("成片缺少音频流")

    result = {"ok": not errors, "errors": errors, "warnings": warnings,
              "duration_s": round(dur, 2), "shots": len(plan.shots),
              "clauses": len(plan.clauses)}
    (work / "verify_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
