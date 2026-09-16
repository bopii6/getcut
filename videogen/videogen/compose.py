"""Stage 7: ffmpeg composition — segments, concat, ASS burn, audio mix."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from .overlays import MEDIA, PANEL, font, RED_SOFT
from .planner import Plan


def _run(cmd: list[str], cwd: Path) -> None:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + (p.stderr or "")[-3000:])


def _run_progress(cmd: list[str], cwd: Path, total_s: float, progress=None,
                  detail: str | None = None) -> None:
    """跑一次 ffmpeg，并把 -progress 的输出换算成百分比上报。

    total_s 是这步的预期时长（同一时间轴），用 out_time_us 对齐。抽不到进度
    时静默降级为普通执行，不影响渲染。
    """
    full = [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]
    tail: list[str] = []
    p = subprocess.Popen(full, cwd=str(cwd), stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if p.stdout is not None:
        for line in p.stdout:
            tail.append(line)
            if len(tail) > 120:
                tail = tail[-120:]
            if progress is None or total_s <= 0:
                continue
            k, _, v = line.strip().partition("=")
            if k in ("out_time_us", "out_time_ms") and v.isdigit():
                done = int(v) / 1_000_000.0
                pct = max(0, min(100, int(done / total_s * 100)))
                try:
                    progress(pct, detail)
                except TypeError:
                    progress(pct)
                except Exception:
                    pass
    err = p.stderr.read() if p.stderr is not None else ""
    p.wait()
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + (err or "".join(tail))[-3000:])


def _chapter_label_png(text: str, out: Path) -> Path:
    w, h = PANEL[2] - PANEL[0], PANEL[3] - PANEL[1]
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    y = 524
    dr.rectangle([36, y, 45, y + 34], fill=RED_SOFT)
    dr.text((60, y + 2), text, font=font(32), fill=RED_SOFT)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def _media_vf(is_img: bool, post: str = "") -> str:
    """Media window filter: videos cover-crop; images fit completely over a
    blurred backdrop (niwo spec: images are never cropped)."""
    if is_img:
        return (
            "split=2[bg][fg];"
            "[bg]scale=778:440:force_original_aspect_ratio=increase,crop=778:440,"
            "boxblur=16:2,eq=brightness=-0.05[bgb];"
            "[fg]scale=778:440:force_original_aspect_ratio=decrease[fgs];"
            "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30" + post
        )
    return "scale=778:440:force_original_aspect_ratio=increase,crop=778:440,setsar=1,fps=30" + post


def build_segment(base_png: Path, shot, media_file: Path | None, work: Path,
                  idx: int, bgmless: bool = False) -> Path:
    dur_s = (shot.end_ms - shot.start_ms) / 1000.0
    dur_s = max(dur_s, 1.2)
    out = work / f"seg_{idx:03d}.mp4"
    base = ["-loop", "1", "-t", f"{dur_s:.3f}", "-i", str(base_png)]
    is_img = bool(media_file) and media_file.suffix.lower() in (
        ".jpg", ".jpeg", ".png", ".webp", ".gif")

    if shot.kind == "footage" and media_file and media_file.is_file():
        label_png = _chapter_label_png(shot.chapter_label or "", work / f"label_{idx:03d}.png")
        cmd = ["ffmpeg", "-y", "-v", "error",
               *(["-stream_loop", "-1", "-t", f"{dur_s:.3f}"] if not is_img else []),
               "-i", str(media_file),
               *base,
               "-loop", "1", "-t", f"{dur_s:.3f}", "-i", str(label_png),
               "-filter_complex",
               "[0:v]" + _media_vf(is_img) + "[m];"
               f"[1:v][2:v]overlay={PANEL[0]}:{PANEL[1]}[b];"
               f"[b][m]overlay={MEDIA[0]}:{MEDIA[1]},format=yuv420p",
               "-t", f"{dur_s:.3f}", "-r", "30",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", str(out)]

    elif shot.kind in ("callout", "panel") and media_file and media_file.is_file():
        overlay_png = (work / f"call_{idx:03d}.png") if shot.kind == "callout" \
            else (work / f"pan_{idx:03d}.png")
        if shot.kind == "callout":
            from .overlays import make_callout
            o = shot.overlay
            make_callout(o.get("number", ""), o.get("label", ""), o.get("caption", ""), overlay_png)
        else:
            from .overlays import make_info_panel
            make_info_panel(shot.overlay, overlay_png)
        # panel dims+blurs the footage under the design; callout keeps it sharp
        post = ",boxblur=12:2,eq=brightness=-0.08" if shot.kind == "panel" else ""
        cmd = ["ffmpeg", "-y", "-v", "error",
               *(["-stream_loop", "-1", "-t", f"{dur_s:.3f}"] if not is_img else []),
               "-i", str(media_file),
               *base,
               "-loop", "1", "-t", f"{dur_s:.3f}", "-i", str(overlay_png),
               "-filter_complex",
               "[0:v]" + _media_vf(is_img, post) + "[m];"
               f"[1:v][m]overlay={MEDIA[0]}:{MEDIA[1]}[b];"
               f"[b][2:v]overlay={MEDIA[0]}:{MEDIA[1]},format=yuv420p",
               "-t", f"{dur_s:.3f}", "-r", "30",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", str(out)]
    else:
        art = work / ("art_title.png" if shot.kind == "title_card" else "art_quote.png")
        cmd = ["ffmpeg", "-y", "-v", "error",
               *base,
               "-loop", "1", "-t", f"{dur_s:.3f}", "-i", str(art),
               "-filter_complex",
               f"[0:v][1:v]overlay={PANEL[0]}:{PANEL[1]},format=yuv420p",
               "-t", f"{dur_s:.3f}", "-r", "30",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", str(out)]
    _run(cmd, work)
    return out


def concat(segments: list[Path], work: Path) -> Path:
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{s.name}'\n" for s in segments), encoding="utf-8")
    out = work / "concat.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
          "-i", listing.name, "-c", "copy", out.name], work)
    return out


def burn_subtitles(video: Path, ass_file: Path, work: Path) -> Path:
    out = work / "withsubs.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-i", video.name,
          "-vf", f"ass={ass_file.name}",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", out.name], work)
    return out


def synth_sfx(work: Path) -> dict[str, Path]:
    """从音效库（assets/sfx + library.json）按分类取音效，统一做低音量归一化。

    库结构：assets/sfx/*.mp3 + library.json（每项含 category: open/card/tick/emphasis）。
    用户想换音效：把 mp3 放进 assets/sfx/，在 library.json 里加一条同类别的即可。
    """
    lib = Path(__file__).resolve().parent.parent / "assets" / "sfx"
    manifest = lib / "library.json"
    pick: dict[str, str] = {}
    if manifest.is_file():
        try:
            for item in json.loads(manifest.read_text(encoding="utf-8")):
                pick.setdefault(item.get("category", ""), item["file"])
        except Exception:
            pick = {}
    # 兜底映射（库里缺类别时用合成音）
    order = {"open": "open-soft-sweep.mp3", "card": "card-light-pop.mp3",
             "tick": "tick-soft-click.mp3", "emphasis": "emph-zoom.mp3"}
    out: dict[str, Path] = {}
    for cat, fallback in order.items():
        src = lib / pick.get(cat, fallback)
        if not src.is_file():
            continue
        dst = work / f"sfx_{cat}.wav"
        # 轻柔化：低音量归一化（-26 LUFS，压在解说之下）+ 裁掉过长尾巴
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
              "-af", "loudnorm=I=-26:TP=-3,atrim=0:1.2,afade=t=out:st=0.7:d=0.5",
              "-ar", "44100", dst.name], work)
        out[cat] = dst
    if out:
        return out
    return _synth_sfx(work)


def _synth_sfx(work: Path) -> dict[str, Path]:
    """兜底：库里一个文件都没有时，用 ffmpeg 合成最小音效（噪音扫频/正弦点）。"""
    specs = {
        "open": ["-f", "lavfi", "-i", "anoisesrc=d=1.0:c=pink:a=0.5",
                 "-af", "lowpass=f=3000,afade=t=in:d=0.15,afade=t=out:st=0.6:d=0.4,volume=0.5"],
        "card": ["-f", "lavfi", "-i", "sine=f=880:d=0.12",
                 "-af", "afade=t=out:st=0.02:d=0.1,volume=0.4"],
        "emphasis": ["-f", "lavfi", "-i", "sine=f=110:d=0.4",
                     "-af", "afade=t=out:st=0.1:d=0.3,volume=0.5"],
    }
    out: dict[str, Path] = {}
    for cat, args in specs.items():
        dst = work / f"sfx_{cat}.wav"
        try:
            _run(["ffmpeg", "-y", "-v", "error", *args, "-ar", "44100", dst.name], work)
            if dst.is_file():
                out[cat] = dst
        except Exception:  # noqa: BLE001 - 兜底音效失败不应中断渲染
            pass
    return out


def mix_audio(tts_mp3: Path, duration_s: float, work: Path, bgm: Path | None = None,
              sfx_events: list[tuple[float, Path, float]] | None = None,
              progress=None) -> Path:
    out = work / "audio.m4a"
    fade_start = max(duration_s - 3.0, 0)
    inputs = ["-i", str(tts_mp3.resolve())]
    chains = ["[0:a]aresample=44100,apad[a0]"]
    mix_ins = "[a0]"
    n = 1
    if bgm and bgm.is_file():
        inputs += ["-stream_loop", "-1", "-i", str(bgm.resolve())]
        chains.append(f"[{n}:a]highpass=f=45,acompressor=threshold=0.22:ratio=5:attack=4:release=60,"
                      f"volume=0.2,aresample=44100,afade=t=out:st={fade_start:.2f}:d=3[bg]")
        mix_ins += f"[bg]"
        n += 1
    for at_s, sfx_file, vol in (sfx_events or []):
        delay_ms = int(at_s * 1000)
        inputs += ["-i", str(sfx_file.resolve())]
        chains.append(f"[{n}:a]volume={vol},aresample=44100,adelay={delay_ms}|{delay_ms}[s{n}]")
        mix_ins += f"[s{n}]"
        n += 1
    fc = ";".join(chains) + f";{mix_ins}amix=inputs={n}:duration=first:normalize=0[a]"
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs,
           "-filter_complex", fc, "-map", "[a]",
           "-t", f"{duration_s:.3f}", "-c:a", "aac", "-b:a", "192k", out.name]
    _run_progress(cmd, work, duration_s, progress=progress, detail="正在混合配音与音轨")
    return out


def mux(video: Path, audio: Path, out_mp4: Path, work: Path) -> Path:
    _run(["ffmpeg", "-y", "-v", "error", "-i", video.name, "-i", audio.name,
          "-c:v", "copy", "-c:a", "copy", "-shortest", str(out_mp4)], work)
    return out_mp4
