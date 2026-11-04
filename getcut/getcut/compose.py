"""音频工序：音效编排 + ffmpeg 混音/封装（PIL 贴片合成器已随云端渲染退役）。"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


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


SFX_CATEGORIES = ("open", "cut", "card", "number", "emphasis", "end")


def sfx_bank() -> dict[str, list[Path]]:
    """按分类返回可用音效，每类可能多条（编排时轮换，避免整片一个声音）。

    归一化结果缓存在 assets/sfx/.norm/：一条音效只跑一次 loudnorm，之后每次渲染
    直接读缓存——否则库里 30 多条音效会在每次出片时串行跑 30 多次 ffmpeg。
    换音效（丢新 mp3 进 assets/sfx/ 并在 library.json 加一条）后，缓存靠源文件
    大小/时间戳自动失效。
    """
    lib = Path(__file__).resolve().parent.parent / "assets" / "sfx"
    manifest = lib / "library.json"
    cache = lib / ".norm"
    bank: dict[str, list[Path]] = {}
    if not manifest.is_file():
        return _synth_sfx()
    try:
        items = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 清单坏了就退回合成音，不阻断出片
        return _synth_sfx()
    cache.mkdir(exist_ok=True)
    for item in items:
        cat = item.get("category") or ""
        if cat not in SFX_CATEGORIES:
            continue
        src = lib / item["file"]
        if not src.is_file():
            continue
        try:
            bank.setdefault(cat, []).append(_normalized(src, cache))
        except Exception as exc:  # noqa: BLE001 - 单条音效坏了不该毁整片
            log.warning("sfx normalize failed, skipped",
                        extra={"file": src.name}, exc_info=exc)
    return bank or _synth_sfx()


def _normalized(src: Path, cache: Path) -> Path:
    """把一条音效归一化到固定响度并缓存；源文件变了自动重做。"""
    dst = cache / (src.stem + ".wav")
    stamp = cache / (src.stem + ".stamp")
    key = f"{src.stat().st_size}:{int(src.stat().st_mtime)}"
    if dst.is_file() and stamp.is_file() and stamp.read_text(encoding="utf-8") == key:
        return dst
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
          # 统一响度，让 30 多条音效彼此音量一致；尾巴削平，避免长尾压过解说
          "-af", "loudnorm=I=-20:TP=-3,atrim=0:3.0,afade=t=out:st=2.4:d=0.5",
          "-ar", "44100", dst.name], cache)
    stamp.write_text(key, encoding="utf-8")
    return dst


def _synth_sfx() -> dict[str, list[Path]]:
    """兜底：库里一条可用音效都没有时，用 ffmpeg 合成最小音效（噪音扫频/正弦点）。

    临时文件写在系统临时目录——这是"库坏了也要能出片"的最后一道保险，不该污染资产目录。
    """
    specs = {
        "open": ["-f", "lavfi", "-i", "anoisesrc=d=1.0:c=pink:a=0.5",
                 "-af", "lowpass=f=3000,afade=t=in:d=0.15,afade=t=out:st=0.6:d=0.4,volume=0.5"],
        "card": ["-f", "lavfi", "-i", "sine=f=880:d=0.12",
                 "-af", "afade=t=out:st=0.02:d=0.1,volume=0.4"],
        "emphasis": ["-f", "lavfi", "-i", "sine=f=110:d=0.4",
                     "-af", "afade=t=out:st=0.1:d=0.3,volume=0.5"],
    }
    import tempfile
    out: dict[str, list[Path]] = {}
    tmpdir = Path(tempfile.mkdtemp(prefix="vg-sfx-"))
    for cat, args in specs.items():
        dst = tmpdir / f"sfx_{cat}.wav"
        try:
            _run(["ffmpeg", "-y", "-v", "error", *args, "-ar", "44100", dst.name], tmpdir)
            if dst.is_file():
                out[cat] = [dst]
        except Exception:  # noqa: BLE001 - 兜底音效失败不应中断渲染
            pass
    return out


SFX_CATEGORIES = ("open", "cut", "card", "number", "emphasis", "end")

# 每个画面事件的音量：一律压在解说之下——配音才是主角，音效只做"手感"
SFX_LEVELS = {"open": 0.50, "cut": 0.22, "card": 0.38,
              "number": 0.34, "emphasis": 0.46, "end": 0.42}
# 挤在一起的声音会糊成一片：这个窗口内只留更重的那个（轻"切"让位给卡片/金句）
_MIN_GAP_S = 0.32
_WEIGHT = {"emphasis": 3, "open": 3, "card": 2, "number": 2, "end": 2, "cut": 1}


def _thin(raw: list[tuple[float, str, Path, float]]) -> list[tuple[float, str, Path, float]]:
    """按时间排序后压掉挤在一起的声音。"""
    out: list[tuple[float, str, Path, float]] = []
    for ev in sorted(raw, key=lambda e: e[0]):
        if out and ev[0] - out[-1][0] < _MIN_GAP_S:
            if _WEIGHT.get(ev[1], 1) > _WEIGHT.get(out[-1][1], 1):
                out[-1] = ev
            continue
        out.append(ev)
    return out


def plan_sfx_events(plan, bank: dict[str, list[Path]], mode: str = "all"):
    """把每个画面事件挂上对应音效，返回 [(秒, 文件, 音量), ...]。

    旧版有三道锁：全片最多 5 声、只有 panel/callout 卡有声、只有第一张金句卡有声，
    所以用户"几乎听不到音效"。现在按"画面什么时候弹出一个东西"逐事件挂：
    开场、每次镜头切换、每张卡、每个数字、每句金句（全部）、章节标签、智谷舞台动作、结尾。

    音量一律压在解说之下——配音才是主角，音效只做"手感"。
    """
    if mode == "off" or not bank:
        return []
    counters: dict[str, int] = {}

    def pick(cat: str) -> Path | None:
        files = bank.get(cat) or []
        if not files:
            return None
        i = counters.get(cat, 0)
        counters[cat] = i + 1
        return files[i % len(files)]        # 同类多条轮换，别整片一个声音

    shots = list(getattr(plan, "shots", []) or [])
    if not shots:
        return []

    raw: list[tuple[float, str, Path, float]] = []
    f = pick("open")
    if f:
        raw.append((0.08, "open", f, SFX_LEVELS["open"]))

    for i, shot in enumerate(shots):
        t = shot.start_ms / 1000.0
        kind = getattr(shot, "kind", "") or ""
        overlay = getattr(shot, "overlay", None) or {}
        variant = overlay.get("variant") if isinstance(overlay, dict) else None
        stage = overlay.get("stage") if isinstance(overlay, dict) else None
        is_card = kind in ("panel", "callout")
        if i > 0:                                        # 换画面：一声轻"切"
            f = pick("cut")
            if f:
                raw.append((t + 0.02, "cut", f, SFX_LEVELS["cut"]))
        if stage:                                        # 智谷舞台动作（胶囊/关系树/榜单）
            f = pick("card")
            if f:
                raw.append((t + 0.04, "card", f, SFX_LEVELS["card"]))
        if is_card:                                      # 设计卡弹出
            f = pick("card")
            if f:
                raw.append((t + 0.03, "card", f, SFX_LEVELS["card"]))
        if kind == "callout" or (is_card and variant in ("stat", "compare")):
            f = pick("number")                           # 数字/数字卡：稍后一点落字
            if f:
                raw.append((t + 0.16, "number", f, SFX_LEVELS["number"]))
        if kind == "quote_card":                         # 金句：每一张都强调
            f = pick("emphasis")
            if f:
                raw.append((t + 0.05, "emphasis", f, SFX_LEVELS["emphasis"]))

    last = shots[-1]
    if (last.end_ms - last.start_ms) > 600:
        f = pick("end")
        if f:
            raw.append((last.start_ms / 1000.0 + 0.05, "end", f, SFX_LEVELS["end"]))

    return [(t, path, vol) for t, _cat, path, vol in _thin(raw)]
def mix_audio(tts_mp3: Path, duration_s: float, work: Path, bgm: Path | None = None,
              sfx_events: list[tuple[float, Path, float]] | None = None,
              progress=None) -> Path:
    out = work / "audio.m4a"
    fade_start = max(duration_s - 3.0, 0)
    inputs = ["-i", str(tts_mp3.resolve())]
    chains = ["[0:a]aresample=44100,apad[a0]"]
    mix_ins = "[a0]"
    n = 1          # ffmpeg 输入序号（-i 的个数）
    links = 1      # 送进 amix 的链路数：asplit 之后一个输入会产生多条链路，两者不再相等
    if bgm and bgm.is_file():
        inputs += ["-stream_loop", "-1", "-i", str(bgm.resolve())]
        chains.append(f"[{n}:a]highpass=f=45,acompressor=threshold=0.22:ratio=5:attack=4:release=60,"
                      f"volume=0.2,aresample=44100,afade=t=out:st={fade_start:.2f}:d=3[bg]")
        mix_ins += "[bg]"
        n += 1
        links += 1
    # 同一个音效被触发多次时只解码一次、用 asplit 分流到各自的延迟链：
    # 一条十分钟的片子有几十个音效事件，逐个 -i 会让 ffmpeg 反复打开同一文件
    by_file: dict[Path, list[tuple[float, int]]] = {}
    for at_s, sfx_file, vol in (sfx_events or []):
        by_file.setdefault(Path(sfx_file), []).append((at_s, vol))
    for sfx_file, uses in by_file.items():
        inputs += ["-i", str(sfx_file.resolve())]
        tags = "".join(f"[x{n}_{k}]" for k in range(len(uses)))
        chains.append(f"[{n}:a]aresample=44100,asplit={len(uses)}{tags}")
        for k, (at_s, vol) in enumerate(uses):
            delay_ms = int(at_s * 1000)
            chains.append(f"[x{n}_{k}]volume={vol},adelay={delay_ms}|{delay_ms}[s{n}_{k}]")
            mix_ins += f"[s{n}_{k}]"
            links += 1
        n += 1
    fc = ";".join(chains) + f";{mix_ins}amix=inputs={links}:duration=first:normalize=0[a]"
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs,
           "-filter_complex", fc, "-map", "[a]",
           "-t", f"{duration_s:.3f}", "-c:a", "aac", "-b:a", "192k", out.name]
    _run_progress(cmd, work, duration_s, progress=progress, detail="正在混合配音与音轨")
    return out


def mux(video: Path, audio: Path, out_mp4: Path, work: Path) -> Path:
    # 输出路径转绝对：ffmpeg 的 cwd 在 work/，相对路径会落到工作目录里去
    # 必须显式 -map：视频里的 <Video> 素材若带原声（历史遗留），ffmpeg 默认选流
    # 会在声道数打平时选输入序号更靠前的视觉轨原声，把混好的人声/BGM/音效整个丢掉
    # （2026-09-19 实测踩过：成片只剩素材的机房嗡嗡声，人声消失）。
    _run(["ffmpeg", "-y", "-v", "error", "-i", video.name, "-i", audio.name,
          "-map", "0:v:0", "-map", "1:a:0",
          "-c:v", "copy", "-c:a", "copy", "-shortest", str(Path(out_mp4).resolve())], work)
    return out_mp4
