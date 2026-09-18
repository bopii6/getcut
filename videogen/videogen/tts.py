"""Stage 3: edge-tts synthesis with word-boundary timestamps + pronunciation overrides."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path

import edge_tts

VOICE = "zh-CN-YunxiNeural"
# 全片节奏固定 1.1 倍：不给用户调（界面上没有语速选项）。整条时间轴派生自 TTS，
# 所以这里一动，分镜、字幕、音效挂点、画面总帧数会一起跟着变。
RATE = "+10%"


# edge-tts exposes no phoneme API, so pronunciation overrides are applied as
# same-length homophone substitutions on the TTS input only (subtitles keep
# the original text). Keyed by pinyin syllable with tone number.
_HOMOPHONES: dict[str, str] = {
    "chang2": "常", "diao4": "掉", "zhong4": "众", "chong3": "宠",
    "gan4": "赣", "jiang4": "将", "xing2": "形", "hang2": "航",
    "chu3": "楚", "chu4": "触", "chuan2": "传", "jiang1": "僵",
}


def apply_pronunciations(text: str, pronunciations: dict[str, str]) -> str:
    """长文: chang2 wen2 -> replaces 长 with 常 so TTS reads diào/cháng correctly."""
    out = text
    for word, pinyin in pronunciations.items():
        if word not in out:
            continue
        fixed = list(word)
        for i, syll in enumerate(pinyin.split()):
            ch = fixed[i] if i < len(fixed) else ""
            if syll != "-" and ch in _HOMOPHONES.get(syll, ""):
                fixed[i] = _HOMOPHONES[syll]
        if "".join(fixed) != word:
            out = out.replace(word, "".join(fixed))
    return out


async def _synth(text: str, voice: str, rate: str, out_mp3: Path) -> list[dict]:
    events: list[dict] = []
    com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    async for chunk in com.stream():
        if chunk["type"] == "audio":
            # stream() yields bytes per chunk; accumulate
            with open(out_mp3, "ab") as f:
                f.write(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            events.append({
                "text": chunk["text"],
                "offset_ms": chunk["offset"] / 1e4,
                "duration_ms": chunk["duration"] / 1e4,
            })
    return events


def synthesize(script: str, pronunciations: dict[str, str], out_dir: Path,
               voice: str = VOICE, rate: str = RATE) -> tuple[Path, list[dict]]:
    """Synthesize the narration; word events align with the ORIGINAL script
    (homophone substitution is same-length, so boundaries still line up)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3 = out_dir / "tts.mp3"
    meta = out_dir / "tts_events.json"
    spoken = apply_pronunciations(script, pronunciations)
    # 缓存签名：脚本/多音字/音色/语速任一变化都会失效，避免复用过期配音
    sig = hashlib.sha1(
        "\x00".join([spoken, json.dumps(pronunciations, ensure_ascii=False),
                     voice, rate]).encode("utf-8")).hexdigest()
    if mp3.exists() and meta.exists():
        try:
            cached = json.loads(meta.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("input_sig") == sig:
                return mp3, cached["events"]
        except Exception:  # noqa: BLE001 - 旧格式/损坏缓存一律重做
            pass
    if mp3.exists():
        mp3.unlink()
    for attempt in range(3):
        try:
            events = asyncio.run(_synth(spoken, voice, rate, mp3))
            if events:
                meta.write_text(json.dumps({"input_sig": sig, "events": events},
                                           ensure_ascii=False), encoding="utf-8")
                return mp3, events
        except Exception:  # noqa: BLE001 - retry on transient network errors
            if attempt == 2:
                raise
    raise RuntimeError("tts failed")
