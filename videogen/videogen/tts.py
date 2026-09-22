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
import time
import uuid
from pathlib import Path

import edge_tts

from . import config
from .planner import PUNCT

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
    entry = voices.get(voice or VOICE)
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
    """合成配音；返回服务端原样吐出的词事件流（未去重未排序），没给就返回 []。
    事件按到达顺序收集，与稿件的文本对位由 _reconcile_words 统一处理。"""
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
    raw_words: list[dict] = []
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
                    # CosyVoice 的流式回包是「累积重发」：同句已合成词会在后续
                    # 事件里反复出现（实测 302 次时间回跳），中英混排长稿还会
                    # 局部乱序。这里原样全收，交给 _reconcile_words 按文本续接
                    # 对位。旧版在这里按「时间必须单调」直接丢词，真词被当成
                    # 重发帧扔掉后事件流比稿件少字，字幕时间轴从出错点起永久
                    # 错位（2026-09-21 anthropic-ipo 条实锤丢 13 字）。
                    raw_words.append({"text": str(w.get("text") or ""),
                                      "begin_time": begin,
                                      "end_time": max(end, begin)})
            elif event == "task-failed":
                raise RuntimeError(_fail_info(ev))
            elif event == "task-finished":
                break
    if not audio:
        raise RuntimeError("cosyvoice 返回空音频")
    out_mp3.write_bytes(bytes(audio))
    return raw_words


# ---------- 词事件流按文本对位 ----------

def _reconcile_words(spoken: str, raw: list[dict], audio_ms: float) -> list[dict] | None:
    """把服务端乱序/重发/吞字的词事件流按文本续接对回稿件。

    实测的流形状（2026-09-22，439 字长稿，10585 帧）：
    - 逐字帧带标点 token，句子内累积重发（同词带原时间戳反复出现）；
    - 发到中段断流后，服务端把整条词流从头重放数遍（时间戳仍用原值）；
    - 个别字彻底不发（两轮实测都缺同一批 13 个字）。

    算法：按「时间大幅回跳（>15 秒）」把流切成多轮——句内重发回跳最多几秒，
    整轮重放回跳是几十秒，阈值分得开。每轮独立从字 0 做续接走查（文本接得
    上且时间相对本轮前进才收，收到的字先到先得写进全局时间表），轮与轮互补。
    全局表剩余缺口用前后邻居线性插值，尾部摊到 audio_ms。

    返回逐字事件，其去标点文本与 spoken 严格一致（下游分镜/字幕按字数查表
    的硬前提）。服务端给出的字数占比过低说明这轮流不可用，返回 None，由调
    用方退回按字数估算——宁可节奏略平，不能整体错位。
    """
    text = PUNCT.sub("", spoken)
    n = len(text)
    if n == 0:
        return None
    global _RECON_DEBUG

    # 1) 切轮：时间回跳超过 15 秒视为新一轮重放开始
    chunks: list[list[dict]] = []
    cur_chunk: list[dict] = []
    prev_begin = None
    for w in raw:
        b = float(w.get("begin_time") or 0)
        if prev_begin is not None and b < prev_begin - 15000 and cur_chunk:
            chunks.append(cur_chunk)
            cur_chunk = []
        cur_chunk.append(w)
        prev_begin = b
    if cur_chunk:
        chunks.append(cur_chunk)

    # 2) 每轮独立走查，先到先得
    table: list[float | None] = [None] * n
    for chunk in chunks:
        cur = 0
        last_t = 0.0

        def _claim(pos: int, begin: float, end: float, count: int) -> None:
            nonlocal last_t
            begin = max(begin, last_t)
            end = max(end, begin)
            for k in range(count):
                if table[pos + k] is None:
                    table[pos + k] = begin + (end - begin) * k / max(count, 1)
            last_t = end

        for w in chunk:
            t = PUNCT.sub("", str(w.get("text") or ""))
            if not t or cur >= n:
                continue
            L = len(t)
            begin = float(w.get("begin_time") or 0)
            end = float(w.get("end_time") or begin)
            fresh = begin >= last_t - 300
            if cur + L <= n and text[cur:cur + L] == t:
                if not fresh:
                    continue
                _claim(cur, begin, end, L)
                cur += L
                continue
            if cur - L >= 0 and text[cur - L:cur] == t:
                continue
            hit = -1
            for skip in range(1, 41):
                if cur + skip + L <= n and text[cur + skip:cur + skip + L] == t:
                    hit = skip
                    break
            if hit >= 0 and fresh:
                seg_end = max(begin, last_t + hit * 80)
                for k in range(hit):
                    if table[cur + k] is None:
                        table[cur + k] = last_t + (seg_end - last_t) * (k + 1) / (hit + 1)
                last_t = seg_end
                _claim(cur + hit, begin, end, L)
                cur += hit + L

    filled = sum(1 for v in table if v is not None)
    if filled < n * 0.6:
        _RECON_DEBUG = {"confirmed": filled, "n": n, "cur": filled, "frames": len(raw)}
        return None

    # 3) 缺口插值：无表字的段落在前后已知点之间线性摊
    k = 0
    while k < n:
        if table[k] is not None:
            k += 1
            continue
        j = k
        while j < n and table[j] is None:
            j += 1
        left = table[k - 1] if k > 0 else 0.0
        right = table[j] if j < n else max(
            audio_ms, (table[k - 1] if k > 0 else 0.0) + (j - k) * 250)
        span = j - k + 1
        for m in range(k, j):
            table[m] = left + (right - left) * (m - k + 1) / span
        k = j

    events = []
    for i, st in enumerate(table):
        st = float(st)
        if i + 1 < n:
            end = max(float(table[i + 1]), st)
        else:
            cap = min(audio_ms, st + 600) if audio_ms > st else st + 300
            end = max(st + 300, cap)
        events.append({"text": text[i], "offset_ms": st, "duration_ms": end - st})
    return events


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
    for ch, w in zip(spoken, weights, strict=True):
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
        for _attempt, want_words in enumerate((True, True, False)):
            try:
                words = asyncio.run(_dashscope_synth(
                    spoken, entry.get("pv") or "", speech_rate, mp3, want_words))
                # 前两次都要字级时间戳：一次失败可能只是网络/服务端偶发（比如合成
                # 中途连接被掐），直接降级会把偶发变成永久性的估算配音。第三次才
                # 放弃时间戳：个别音色确实不支持这个参数，会稳定 task-failed。
                events = None
                if words and want_words:
                    events = _reconcile_words(spoken, words, _probe_ms(mp3))
                    if events is None:
                        dbg = globals().get("_RECON_DEBUG") or {}
                        print(f"[tts] 词事件流对位失败（{len(words)} 帧）："
                              f"确认 {dbg.get('confirmed')}/{dbg.get('n')} 字，"
                              f"走到第 {dbg.get('cur')} 字，退回估算对齐", flush=True)
                        try:
                            (Path(out_dir) / "raw_debug.json").write_text(
                                json.dumps({"frames": len(words),
                                            "sample": words[:6000]},
                                           ensure_ascii=False), encoding="utf-8")
                        except Exception:  # noqa: BLE001 - 调试落盘失败不影响主流程
                            pass
                if events is None:
                    if want_words:
                        print("[tts] 未拿到词级时间戳，退回按字数估算对齐", flush=True)
                    events = _estimate_events(spoken, mp3)
                meta.write_text(json.dumps({"input_sig": sig, "events": events},
                                           ensure_ascii=False), encoding="utf-8")
                return mp3, events
            except Exception as e:  # noqa: BLE001 - 网络抖动重试；渠道真挂了就明说，不悄悄降级成微软音
                last_err = e
        raise RuntimeError(f"配音服务暂时不可用（百炼 CosyVoice：{last_err}）")

    edge_voice = entry.get("edge") or voice or VOICE
    if mp3.exists():
        mp3.unlink()
    # edge-tts 的 NoAudioReceived 是阵发性的（微软令牌/接口偶发抽风，几分钟一阵），
    # 重试必须带退避间隔硬扛过去，否则三连发全撞在同一个坑里
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            events = asyncio.run(_synth(spoken, edge_voice, rate or RATE, mp3))
            if events:
                meta.write_text(json.dumps({"input_sig": sig, "events": events},
                                           ensure_ascii=False), encoding="utf-8")
                return mp3, events
            last_err = RuntimeError("edge-tts 没有返回时间戳")
        except Exception as e:  # noqa: BLE001 - 偶发网络/令牌故障，退避重试
            last_err = e
        if attempt < 2:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(
        f"配音渠道暂时不可用（微软 edge-tts：{last_err}）。"
        f"这是偶发故障，通常半分钟后重提任务即可")


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
