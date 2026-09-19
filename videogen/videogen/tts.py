"""Stage 3: 配音合成（词级时间戳 + 多音字替换）。

渠道两档：
- dashscope（阿里百炼 CosyVoice，质量最好）：配了 DASHSCOPE_API_KEY 就走它，
  WebSocket 协议，部分音色回字级时间戳；没回时间戳就按音频总长估算。
- edge-tts（微软，免费兜底）：没配百炼密钥时用它，老项目里的 edge 音色 id 也认。

音色目录内置在 DEFAULT_VOICES，assets/voices.json 存在时整体覆盖（改清单不用改代码）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import uuid
from pathlib import Path

import edge_tts

from . import config

VOICE = "xiaoxia"          # 默认音色 = 目录里的 id（不再是 edge 原生名）
RATE = "+10%"
DASHSCOPE_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference/"

# 没配百炼时的兜底音色目录（免费、稳，但用户说微软音"不好用"——只当临时替代）
LEGACY_EDGE_VOICES: dict[str, str] = {
    "zh-CN-YunxiNeural": "云希 · 清爽男声", "zh-CN-YunjianNeural": "云健 · 浑厚男声",
    "zh-CN-YunyangNeural": "云扬 · 新闻男声", "zh-CN-YunxiaNeural": "云夏 · 少年男声",
    "zh-CN-XiaoxiaoNeural": "晓晓 · 温暖女声", "zh-CN-XiaoyiNeural": "晓伊 · 年轻女声",
    "zh-CN-liaoning-XiaobeiNeural": "晓北 · 东北口音", "zh-CN-shaanxi-XiaoniNeural": "晓妮 · 陕西口音",
}


# 全片节奏固定 1.1 倍：不给用户调（界面上没有语速选项）。整条时间轴派生自 TTS，
# 所以这里一动，分镜、字幕、音效挂点、画面总帧数会一起跟着变。
# edge-tts 要 "+10%"，百炼要 1.1，rate_delta() 统一换算。

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


def rate_delta(rate: str | None) -> float:
    """+10% -> 0.10；坏值当 0。"""
    m = re.match(r"([+-]?\d+(?:\.\d+)?)%", rate or "")
    return float(m.group(1)) / 100.0 if m else 0.0


# ---------- 音色目录 ----------

# provider: dashscope（pv=百炼音色 id）/ edge（voice=edge-tts 音色 id）
# edge 字段同时是"百炼没配密钥时的兜底音色"。
DEFAULT_VOICES: dict[str, dict] = {
    "xiaoxia":  {"label": "龙小夏 · 知性女声", "provider": "dashscope", "pv": "longxiaoxia_v2",  "edge": "zh-CN-XiaoxiaoNeural"},
    "xiaochun": {"label": "龙小淳 · 阳光女声", "provider": "dashscope", "pv": "longxiaochun_v2", "edge": "zh-CN-XiaoyiNeural"},
    "wan":      {"label": "龙婉 · 温柔女声",   "provider": "dashscope", "pv": "longwan_v2",      "edge": "zh-CN-XiaoxiaoNeural"},
    "cheng":    {"label": "龙橙 · 沉稳男声",   "provider": "dashscope", "pv": "longcheng_v2",    "edge": "zh-CN-YunjianNeural"},
    "shuo":     {"label": "龙朔 · 新闻男声",   "provider": "dashscope", "pv": "longshuo_v2",     "edge": "zh-CN-YunyangNeural"},
    "fei":      {"label": "龙飞 · 活力男声",   "provider": "dashscope", "pv": "longfei_v2",      "edge": "zh-CN-YunxiNeural"},
    "shu":      {"label": "龙书 · 解说男声",   "provider": "dashscope", "pv": "longshu_v2",      "edge": "zh-CN-YunyangNeural"},
}


def load_voices() -> dict[str, dict]:
    """音色清单：assets/voices.json 整体覆盖内置目录（条目结构同 DEFAULT_VOICES）。"""
    f = config.ASSETS / "voices.json"
    if f.is_file():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except Exception:  # noqa: BLE001 - 清单坏了就退回内置，别让配音挂掉
            pass
    return DEFAULT_VOICES


def dashscope_ready() -> bool:
    if config.TTS_PROVIDER == "edge":
        return False
    return bool(config.DASHSCOPE_API_KEY)


def resolve_voice(voice: str | None) -> dict:
    """音色 id -> 目录条目。目录外：cosyvoice 复刻音色 id 走百炼；其余（老项目的
    edge 音色名）按 edge 渠道处理。"""
    voices = load_voices()
    entry = voices.get(voice or "")
    if entry:
        entry = dict(entry)
        entry.setdefault("id", voice)
        return entry
    vid = voice or VOICE
    if vid.startswith("cosyvoice") or vid.startswith("@clone"):
        # 声音复刻生成的音色 id（或占位符）：百炼渠道直通
        return {"id": vid, "label": "我的声音", "provider": "dashscope", "pv": vid}
    return {"id": vid, "label": vid, "provider": "edge", "edge": vid, "legacy": True}


# ---------- edge-tts ----------

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


# ---------- 阿里百炼 CosyVoice（WebSocket 协议） ----------

def _split_chunks(text: str, size: int = 480) -> list[str]:
    """按标点切成 continue-task 的小块（协议单块别太大）。"""
    chunks, cur, cur_len = [], [], 0
    for piece in re.split(r"(?<=[。！？；：,\n])", text):
        if not piece:
            continue
        if cur_len + len(piece) > size and cur:
            chunks.append("".join(cur))
            cur, cur_len = [], 0
        cur.append(piece)
        cur_len += len(piece)
    if cur:
        chunks.append("".join(cur))
    return chunks or [text]


async def _dashscope_synth(spoken: str, pv: str, speech_rate: float, out_mp3: Path,
                           want_words: bool) -> list[dict]:
    """返回词级时间戳 [{text, offset_ms, duration_ms}]；服务端没给就返回 []。"""
    import websockets
    headers = {"Authorization": f"bearer {config.DASHSCOPE_API_KEY}",
               "user-agent": "GetCut/1.0",
               "X-DashScope-DataInspection": "enable"}
    params = {"voice": pv, "text_type": "PlainText", "format": "mp3", "sample_rate": 22050,
              "volume": 50, "rate": speech_rate, "pitch": 1.0}
    if want_words:
        params["word_timestamp_enabled"] = True
    tid = uuid.uuid4().hex

    def _msg(action: str, payload_input: dict | None = None) -> str:
        # 探针实测（2026-09-19）：dashscope.aliyuncs.com/api-ws 这个老端点要求
        # streaming=duplex 且每条消息都带 task_group/parameters——官方文档页描述的是
        # 新 maas 端点（continue-task 只带 input），照抄会报 "input text is valid"。
        return json.dumps({
            "header": {"action": action, "task_id": tid, "streaming": "duplex"},
            "payload": {"task_group": "audio", "task": "tts",
                        "function": "SpeechSynthesizer", "model": config.TTS_MODEL,
                        "parameters": params, "input": payload_input or {}},
        }, ensure_ascii=False)

    audio = bytearray()
    words: list[dict] = []
    async with websockets.connect(DASHSCOPE_WS_URL, additional_headers=headers,
                                  max_size=None, open_timeout=20) as ws:
        await ws.send(_msg("run-task"))

        def _fail_info(ev: dict) -> str:
            h = ev.get("header") or {}
            return f"{h.get('error_code')} {h.get('error_message')}".strip() or "task-failed"

        # 1) 等 task-started
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            if isinstance(raw, bytes):
                continue
            ev = json.loads(raw)
            event = (ev.get("header") or {}).get("event")
            if event == "task-started":
                break
            if event == "task-failed":
                raise RuntimeError(_fail_info(ev))

        # 2) 送文本 + 收尾
        for chunk in _split_chunks(spoken):
            await ws.send(_msg("continue-task", {"text": chunk}))
        await ws.send(_msg("finish-task"))

        # 3) 收音频与时间戳
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            if isinstance(raw, bytes):
                audio.extend(raw)
                continue
            ev = json.loads(raw)
            event = (ev.get("header") or {}).get("event")
            if event == "result-generated":
                sentence = ((ev.get("payload") or {}).get("output") or {}).get("sentence") or {}
                for w in sentence.get("words") or []:
                    begin = float(w.get("begin_time") or 0)
                    end = float(w.get("end_time") or begin)
                    words.append({"text": str(w.get("text") or ""),
                                  "offset_ms": begin,
                                  "duration_ms": max(end - begin, 0.0)})
            elif event == "task-failed":
                raise RuntimeError(_fail_info(ev))
            elif event == "task-finished":
                break
    if not audio:
        raise RuntimeError("cosyvoice 返回空音频")
    out_mp3.write_bytes(bytes(audio))
    return words


# ---------- 没有词级时间戳时的估算兜底 ----------

def _probe_ms(mp3: Path) -> float:
    try:
        outp = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(mp3)],
            capture_output=True, text=True, timeout=30)
        return float(outp.stdout.strip()) * 1000.0
    except Exception:  # noqa: BLE001 - 探不到时长就按每字 300ms 估
        return 0.0


def _estimate_events(spoken: str, mp3: Path) -> list[dict]:
    """把音频总长按字符权重摊到每个字上。对齐器会剥标点，标点只当停顿权重。"""
    dur_ms = _probe_ms(mp3)
    weights = []
    for ch in spoken:
        if re.match(r"[。！？；，、：…—\s]", ch):
            weights.append(0.55)
        elif re.match(r"[\x00-\x7f]", ch):
            weights.append(0.4)
        else:
            weights.append(1.0)
    total_w = sum(weights) or 1.0
    lead, tail = (120.0, 200.0) if dur_ms > 1500 else (0.0, 0.0)
    span = max(dur_ms - lead - tail, total_w * 200) if dur_ms else total_w * 300
    per_w = span / total_w
    events, at, buf, buf_w, buf_t = [], lead, "", 0.0, 0.0
    for ch, w in zip(spoken, weights):
        buf, buf_w, buf_t = buf + ch, buf_w + w, buf_t + w * per_w
        if len(buf) >= 5 or buf_t > 700:
            events.append({"text": buf, "offset_ms": at, "duration_ms": buf_w * per_w})
            at += buf_w * per_w
            buf, buf_w, buf_t = "", 0.0, 0.0
    if buf:
        events.append({"text": buf, "offset_ms": at, "duration_ms": buf_w * per_w})
    return events


# ---------- 对外入口 ----------

def synthesize_preview(voice: str, out_mp3: Path, text: str) -> str:
    """试听样句：按音色实际会走的渠道合成，返回渠道名（缓存由调用方按渠道命名）。"""
    entry = resolve_voice(voice)
    if entry.get("provider") == "dashscope" and dashscope_ready():
        asyncio.run(_dashscope_synth(text, entry.get("pv") or "", 1.1, out_mp3, False))
        return "dashscope"
    asyncio.run(_synth(text, entry.get("edge") or voice or VOICE, RATE, out_mp3))
    return "edge"


def synthesize(script: str, pronunciations: dict[str, str], out_dir: Path,
               voice: str = VOICE, rate: str = RATE) -> tuple[Path, list[dict]]:
    """Synthesize the narration; word events align with the ORIGINAL script
    (homophone substitution is same-length, so boundaries still line up)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3 = out_dir / "tts.mp3"
    meta = out_dir / "tts_events.json"
    spoken = apply_pronunciations(script, pronunciations)
    entry = resolve_voice(voice)
    use_dash = entry.get("provider") == "dashscope" and dashscope_ready()
    # 缓存签名：脚本/多音字/渠道/音色/语速任一变化都会失效，避免复用过期配音
    sig = hashlib.sha1("\x00".join([
        spoken, json.dumps(pronunciations, ensure_ascii=False),
        "dash" if use_dash else "edge", str(entry.get("pv") or entry.get("edge")),
        rate or RATE]).encode("utf-8")).hexdigest()
    if mp3.exists() and meta.exists():
        try:
            cached = json.loads(meta.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("input_sig") == sig:
                return mp3, cached["events"]
        except Exception:  # noqa: BLE001 - 旧格式/损坏缓存一律重做
            pass

    if use_dash:
        speech_rate = round(1.0 + rate_delta(rate), 3)
        last_err = None
        for attempt, want_words in enumerate((True, False, False)):
            try:
                words = asyncio.run(_dashscope_synth(
                    spoken, entry.get("pv") or "", speech_rate, mp3, want_words))
                # 第二次起不再要字级时间戳：个别音色不支持这个参数会 task-failed
                events = words if (words and want_words) else _estimate_events(spoken, mp3)
                meta.write_text(json.dumps({"input_sig": sig, "events": events},
                                           ensure_ascii=False), encoding="utf-8")
                return mp3, events
            except Exception as e:  # noqa: BLE001 - 网络抖动重试；渠道真挂了就明说，不悄悄降级成微软音
                last_err = e
        raise RuntimeError(f"配音服务暂时不可用（百炼 CosyVoice：{last_err}）")

    edge_voice = entry.get("edge") or voice or VOICE
    if mp3.exists():
        mp3.unlink()
    for attempt in range(3):
        try:
            events = asyncio.run(_synth(spoken, edge_voice, rate or RATE, mp3))
            if events:
                meta.write_text(json.dumps({"input_sig": sig, "events": events},
                                           ensure_ascii=False), encoding="utf-8")
                return mp3, events
        except Exception:  # noqa: BLE001 - retry on transient network errors
            if attempt == 2:
                raise
    raise RuntimeError("tts failed")


if __name__ == "__main__":
    # 配好 DASHSCOPE_API_KEY 后跑一下：python -m videogen.tts
    # 能生成 tts-check.mp3 且打印 dashscope 就说明密钥、网络、音色都通了。
    import sys
    out = Path("tts-check.mp3")
    used = synthesize_preview(VOICE, out, "大家好，这是 GetCut 的配音渠道自检。")
    size = out.stat().st_size if out.is_file() else 0
    print(f"channel={used} file={out} bytes={size}")
    if used != "dashscope":
        print("（当前走的是 edge-tts 兜底：没配百炼密钥，或 TTS_PROVIDER=edge）")
        sys.exit(2)
    print("百炼 CosyVoice 通了。")
