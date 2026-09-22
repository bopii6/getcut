"""Stage 3: 配音合成（分句合成 + 实测摆放，2026-09-22 第四代）。

时间轴的正确来源只有一个：音频本身。前三天的事故链证明，任何服务端"自报"的
词级时间戳都不能采信——CosyVoice 的是句内匀速编造的（每字恒定 201.666ms），
paraformer 听写出来的同样句内匀速编造（66s 音频只切 2 个句段）。所以这一代
不再"合成完再重建时间轴"，而是让时间轴在物理拼接时自动精确：

  1. 稿子按句切开（_sentence_head_indices），逐句合成（并发、失败只重试该句）；
  2. 每段转 wav 后 ffprobe 实测时长——文件时长是物理事实，没人能编；
  3. 按实测时长 + 句间隔把各段物理拼接成整条配音，句 k 的字幕起点 =
     前面所有段实测时长之和，构造上即真值；
  4. 句内逗号子句用该段自己的 silencedetect 停顿吸附（段短，错也错不远）。

渠道两档（对时间轴无影响，只是音色不同）：
- dashscope（阿里百炼 CosyVoice，质量最好）：配了 DASHSCOPE_API_KEY 就走它。
- edge-tts（微软，免费兜底）：没配百炼密钥时用它，老项目里的 edge 音色 id 也认。

音色目录内置在 DEFAULT_VOICES，assets/voices.json 存在时整体覆盖（改清单不用改代码）。
旧的时间轴重建机器（词流对位 / 停顿 DP / ASR 自听）保留在文件后半部分：
测试还指着它们，也留作尸检证据，但 synthesize 不再调用。
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import logging
import math
import re
import subprocess
import uuid
from pathlib import Path

import edge_tts

from . import config
from .planner import PUNCT

log = logging.getLogger(__name__)

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
    """把服务端乱序/重发/吞字的词事件流按文本对回稿件。

    实测的流形状（2026-09-22，439 字长稿，10585 帧）：
    - 逐字帧带标点 token，句子内累积重发（同词带原时间戳反复出现）；
    - 发到中段断流后，服务端把整条词流从头重放数遍（时间戳仍用原值）；
    - 个别字彻底不发（两轮实测都缺同一批 13 个字）；
    - 还会出现畸形帧：一次 21 个字、时长却是 0，时刻整体错 4 秒。

    算法（2026-09-22 第二版，替换原"顺序走查"）：按时间大幅回跳切轮，**每轮
    独立用 difflib 把该轮的 token 序列与稿件对位**，命中的位置记时间；一个位置
    被多轮覆盖时取"覆盖最长的那一轮"的值（各轮都带原值，取最完整的一轮最稳）。
    改掉顺序走查的原因：走查一旦在中途脱轨（重放帧被当成跳字、或畸形帧抢注），
    后面的字就全部认领不到，只能吃兜底填充——实测有一整段 21 个字因此整体错 4 秒。
    difflib 对位是无状态的，脱不了轨。

    覆盖不足（<60%）说明这轮流不可用，返回 None 交调用方退回估算——宁可节奏略平，
    不能整体错位。
    """
    text = PUNCT.sub("", spoken)
    n = len(text)
    if n == 0:
        return None

    # 1) 切轮：时间回跳超过 15 秒视为新一轮重放开始（句内重发最多几秒，分得开）
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

    # 2) 每轮与稿件对位；同一位置保留"覆盖最长的那一轮"给出的时间
    best: list[tuple[int, float] | None] = [None] * n
    for chunk in chunks:
        toks: list[tuple[str, float, float]] = []
        for w in chunk:
            t = PUNCT.sub("", str(w.get("text") or ""))
            if t:
                b = float(w.get("begin_time") or 0)
                toks.append((t, b, max(float(w.get("end_time") or b), b)))
        if not toks:
            continue
        joined = "".join(t for t, _b, _e in toks)
        if not joined:
            continue
        hit = 0
        for blk in difflib.SequenceMatcher(None, text, joined, autojunk=False)                 .get_matching_blocks():
            if blk.size <= 0:
                continue
            hit += blk.size
            # joined 的第 j 个字落在哪一个 token 上
            acc, ti = 0, 0
            for k in range(blk.size):
                j = blk.b + k
                while ti < len(toks) and j >= acc + len(toks[ti][0]):
                    acc += len(toks[ti][0])
                    ti += 1
                if ti >= len(toks):
                    break
                t, b, e = toks[ti]
                off = j - acc
                at = b + (e - b) * off / max(len(t), 1)
                pos = blk.a + k
                cur = best[pos]
                if cur is None or hit >= cur[0]:
                    best[pos] = (hit, at)
    filled = sum(1 for v in best if v is not None)
    if filled < n * 0.6:
        global _RECON_DEBUG
        _RECON_DEBUG = {"confirmed": filled, "n": n, "cur": filled, "frames": len(raw)}
        return None
    table: list[float | None] = [v[1] if v else None for v in best]

    # 3) 缺口插值：没认领到的字在前后已知点之间线性摊
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

    # 4) 时间轴不允许倒挂（轮与轮混在同一张表里，个别字可能落在前一个字之前）
    for i in range(1, n):
        if table[i] is not None and table[i - 1] is not None and table[i] < table[i - 1]:
            table[i] = table[i - 1]

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


def _resync(cur: int, token: str, begin: float, table: list[float | None],
            text: str, span: int = 160, tol: float = 600.0) -> int | None:
    """重放帧回锚：拿已确认的时间表找这个 token 在稿件里的位置。

    服务端每次重放都带原始时间戳，所以「文本相同 + 时刻对得上」的字一定是同一个
    位置——用它把走查位置拉回去，而不是把重放当成往前跳字。找不到返回 None
    （丢掉这一帧，等下一轮重放再认领）。"""
    L = len(token)
    best, best_d = None, tol
    for p in range(max(0, cur - span), min(len(text) - L, cur + span) + 1):
        if text[p:p + L] != token:
            continue
        tv = table[p]
        if tv is None:
            continue
        d = abs(float(tv) - begin)
        if d < best_d:
            best, best_d = p, d
    return best


def _observed_step(table: list[float | None]) -> float:
    """已确认字之间的中位步长（毫秒/字）。兜底填充用实测步长，不写死常量。"""
    steps, prev = [], None
    for v in table:
        if v is None:
            continue
        if prev is not None and v > prev:
            steps.append(v - prev)
        prev = v
    if len(steps) >= 8:
        steps.sort()
        return min(max(steps[len(steps) // 2], 60.0), 600.0)
    return 200.0


# ---------- 没有词级时间戳时的估算兜底（停顿锚定） ----------
_ANCHOR_TOL_MS = 1000.0     # 句首与实测停顿的配对容差（词流自己的偏差 ≤0.7s）
_MIN_ANCHORS = 3            # 至少配齐几个句锚点才相信停顿锚定
# 停顿实测的唯一参数。verify 的漂移检查必须读同一个常量：两边看到的不是同一批
# 停顿的话，质检判"对得上"而时间轴按另一批停顿排，等于没有闸。
SILENCE_FILTER = "silencedetect=noise=-35dB:d=0.3"
_ANCHOR_V = 5               # 时间轴生成方式的版本号：旧缓存没有它就就地重算
_RECON_V = 2                # 词流对位算法版本号：变小了说明老缓存是旧算法产的
_BOUNDARY_RE = re.compile(r"[。！？；，、：]")


def _probe_ms(mp3: Path) -> float:
    try:
        outp = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(mp3)],
            capture_output=True, text=True, timeout=30)
        return float(outp.stdout.strip()) * 1000.0
    except Exception:  # noqa: BLE001 - 探不到时长就按每字 300ms 估
        return 0.0


def pause_ends_ms(audio: Path) -> list[float]:
    """ffmpeg silencedetect 实测的"停顿结束点"（毫秒）= 下一段话实际开口的时刻。
    与 verify 的漂移检查共用同一套参数，保证两边看到的是同一批停顿。"""
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "info", "-i", str(audio),
             "-af", SILENCE_FILTER, "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300)
    except Exception:  # noqa: BLE001 - ffmpeg 没装/超时都当"测不出停顿"
        return []
    ends: list[float] = []
    for line in (r.stderr or "").splitlines():
        if "silence_end:" in line:
            try:
                ends.append(float(line.split("silence_end:")[1].split("|")[0].strip()) * 1000.0)
            except ValueError:
                continue
    return ends


def _char_weights(spoken: str) -> list[float]:
    """逐字权重：汉字 1.0、ASCII 0.4、标点/空白 0.55（与原估算一致）。"""
    weights = []
    for ch in spoken:
        if re.match(r"[。！？；，、：…—\s]", ch):
            weights.append(0.55)
        elif re.match(r"[\x00-\x7f]", ch):
            weights.append(0.4)
        else:
            weights.append(1.0)
    return weights


def _clause_char_starts(spoken: str) -> list[int]:
    """每个子句首字在 spoken 里的下标，切分口径与 planner.split_clauses 一致
    （句读和逗号都算边界；连写标点/空白构成的空子句不产生新起点）。"""
    starts = [0]
    i, n = 0, len(spoken)
    while i < n:
        if not _BOUNDARY_RE.match(spoken[i]):
            i += 1
            continue
        j = i + 1
        while j < n and (spoken[j].isspace() or _BOUNDARY_RE.match(spoken[j])):
            j += 1
        if j < n and j > starts[-1]:
            starts.append(j)
        i = j if j > i else i + 1
    return starts


def _uniform_events(spoken: str, weights: list[float], dur_ms: float) -> list[dict]:
    """旧的均匀摊估算：整段音频按字重平铺。停顿锚定失败时的回退路径。"""
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


def _match_anchors(est: list[float], pauses: list[float],
                   tol: float = _ANCHOR_TOL_MS) -> list[tuple[int, int]]:
    """把估算句首和实测停顿按时间顺序配对（每个停顿最多用一次）。
    返回 [(句下标, 停顿下标), ...]。"""
    pairs: list[tuple[int, int]] = []
    used = -1
    for i, t in enumerate(est):
        best_j, best_d = -1, tol
        for j, p in enumerate(pauses):
            if j <= used:
                continue
            d = abs(p - t)
            if d <= best_d:
                best_j, best_d = j, d
        if best_j >= 0:
            pairs.append((i, best_j))
            used = best_j
    return pairs


def _anchored_windows(weights: list[float], spans: list[tuple[int, int]],
                      dur_ms: float, pauses: list[float],
                      est: list[float] | None = None
                      ) -> tuple[list[tuple[float, float]], int] | None:
    """给每个子句算出 [开始, 结束] 毫秒窗口：句首锚到实测停顿的结束点，
    没配上的子句在相邻锚点间线性插值。锚点不足返回 None（退回均匀摊）。
    成功时返回 (窗口列表, 实际配上的锚点数)。

    est：每个子句句首的"估计时刻"，缺省按字重均匀摊。词级时间戳那条路也走
    这里（2026-09-22 第二宗漂移）：百炼回的词级时间戳跟它自己的音频有
    0.1~0.7 秒的系统偏差，照它排字幕必然整体滞后。est 只用来决定"哪个句首
    配哪个停顿"，最终时刻一律以音频实测为准。"""
    if dur_ms <= 0 or len(spans) < 2:
        return None
    pauses = [p for p in pauses if 0 <= p < dur_ms - 100]
    if len(pauses) < _MIN_ANCHORS:
        return None
    lead, tail = (120.0, 200.0) if dur_ms > 1500 else (0.0, 0.0)
    total_w = sum(weights) or 1.0
    span = max(dur_ms - lead - tail, total_w * 200)
    per_w = span / total_w
    if est is None:
        prefix = [0.0]
        for w in weights:
            prefix.append(prefix[-1] + w)
        est = [lead + prefix[a] * per_w for a, _ in spans]
        est_end = lead + span
        head_y = lead
    else:
        est = [float(t) for t in est]
        for k in range(1, len(est)):      # 估计时刻必须单调，坏值往回压平
            est[k] = max(est[k], est[k - 1])
        # 词流的第一个字本来就该在片头（0 附近），别硬拽到 120ms 的引子
        est_end = est[-1] + max(est[-1] - est[-2], 200.0) if len(est) > 1 else dur_ms
        head_y = min(est[0], lead)

    # 估计句首 ↔ 实测停顿 单调配对，凑成锚点序列（首尾补基线锚点）
    matches = _match_anchors(est[1:], pauses)
    if len(matches) < _MIN_ANCHORS:
        return None
    pts: list[tuple[float, float, bool]] = [(est[0], head_y, False)]
    for i, j in matches:
        pts.append((est[i + 1], pauses[j], True))
    if est_end > pts[-1][0]:
        pts.append((est_end, dur_ms - tail, False))
    # 两个坐标都必须严格递增；相邻锚点之间的语速还要不离谱。词流在坏区会乱配
    # （实测有 4 个子句被吸到同一个停顿上），这种配对照样过不了语速闸，丢掉之后
    # 这一段退回相邻锚点之间插值——远好过让它把后面整条链平移一格。
    xs: list[float] = []
    ys: list[float] = []
    anchors = 0
    for x, y, is_anchor in pts:
        if xs and (x <= xs[-1] or y <= ys[-1]):
            continue
        if xs and not (1 / _SLOPE_BAND <= (y - ys[-1]) / (x - xs[-1]) <= _SLOPE_BAND):
            continue
        xs.append(x)
        ys.append(y)
        anchors += 1 if is_anchor else 0
    if anchors < _MIN_ANCHORS:
        return None

    def warp(t: float) -> float:
        if t <= xs[0]:
            return ys[0]
        if t >= xs[-1]:
            return ys[-1]
        k = 1
        while k < len(xs) - 1 and xs[k] < t:
            k += 1
        x0, x1, y0, y1 = xs[k - 1], xs[k], ys[k - 1], ys[k]
        return y0 + (y1 - y0) * (t - x0) / (x1 - x0)

    windows: list[tuple[float, float]] = []
    for k, e in enumerate(est):
        t0 = warp(e)
        t1 = warp(est[k + 1]) if k + 1 < len(est) else (dur_ms - tail)
        if windows:
            t0 = max(t0, windows[-1][1])
            t1 = max(t1, t0)
        windows.append((t0, t1))
    return windows, anchors


def _events_by_windows(spoken: str, weights: list[float],
                       spans: list[tuple[int, int]],
                       windows: list[tuple[float, float]]) -> list[dict]:
    """按子句窗口出事件：窗口内按字重摊时长，≥5 字或 >700ms 切块，
    子句边界必定落在事件边界上——字幕查到的句首时刻因此就是窗口起点本身。"""
    events: list[dict] = []
    for (a, b), (t0, t1) in zip(spans, windows, strict=True):
        seg_w = sum(weights[a:b]) or 1.0
        per = (t1 - t0) / seg_w
        at, buf, buf_w, buf_t = t0, "", 0.0, 0.0
        for ch, w in zip(spoken[a:b], weights[a:b], strict=True):
            buf, buf_w, buf_t = buf + ch, buf_w + w, buf_t + w * per
            if len(buf) >= 5 or buf_t > 700:
                events.append({"text": buf, "offset_ms": at, "duration_ms": buf_w * per})
                at += buf_w * per
                buf, buf_w, buf_t = "", 0.0, 0.0
        if buf:
            events.append({"text": buf, "offset_ms": at, "duration_ms": buf_w * per})
    return events


def _estimate_events(spoken: str, mp3: Path) -> tuple[list[dict], int]:
    """停顿锚定的估算兜底：先用 silencedetect 实测配音里的停顿结束点，
    把估算句首配到实测停顿上，让每个子句窗口的起点等于真实开口时刻；
    配不齐（锚点 <3 个）就退回原来的均匀摊。返回 (事件列表, 锚点数)。"""
    dur_ms = _probe_ms(mp3)
    weights = _char_weights(spoken)
    raw = _clause_char_starts(spoken)
    spans = list(zip(raw, raw[1:] + [len(spoken)], strict=True)) if len(raw) > 1 else []
    got = _anchored_windows(weights, spans, dur_ms, pause_ends_ms(mp3)) if spans else None
    if got is not None:
        windows, anchors = got
        return _events_by_windows(spoken, weights, spans, windows), anchors
    return _uniform_events(spoken, weights, dur_ms), 0


# ---------- 以音频为准的句子时间轴（2026-09-22 第二宗漂移） ----------

_SLOPE_BAND = 1.2           # 相邻锚点之间"音频时间/词流时间"的斜率允许范围
_BLEND_MS = 700.0           # 停顿 DP 与词流差多少以内算"互相印证"
_RATE_BAND = 2.2            # 停顿 DP 里，相邻锚点之间语速允许偏离全片均值多少倍
_GAP_TOL_MS = 1200.0        # 词流空洞与音频停顿的配对容差
_GAP_BAND = 1.35            # 两处停顿之间"词流时间/音频时间"的斜率允许范围


def _pause_anchors(bnd_w: list[float], total_w: float, pauses: list[float],
                   dur_ms: float, lead: float, tail: float
                   ) -> list[tuple[float, float]] | None:
    """把每个实测停顿配到稿件里"最像"的那个子句边界上，返回 (累计权重, 时刻) 锚点。

    为什么不能"就近吸附"到词级时间戳上：服务端在坏区会把一整串字塞进同一个
    时刻（实测 21 个字共用 14051ms），吸附的结果是每个子句都吸到隔壁那个停顿，
    整段平移一个停顿——比不修还错。

    所以准则用「相邻锚点之间那段话的语速必须接近全片平均语速」做动态规划：
    只依赖停顿顺序和字数权重，不依赖任何时间戳，坏区也拉得回来。
    """
    if len(pauses) < _MIN_ANCHORS or total_w <= 0 or dur_ms <= 0:
        return None
    span = max(dur_ms - lead - tail, total_w * 200)
    base_rate = span / total_w                       # ms / 权重，全片平均
    m = len(bnd_w)

    def seg_cost(dw: float, dt: float) -> float:
        if dw <= 0 or dt <= 0:
            return float("inf")
        return abs(math.log(dt / dw / base_rate))

    inf = float("inf")
    n = len(pauses)
    dp = [[inf] * m for _ in range(n)]
    par = [[-1] * m for _ in range(n)]
    for b in range(m):
        c = seg_cost(bnd_w[b], pauses[0] - lead)
        if c < inf:
            dp[0][b] = c
    for k in range(1, n):
        row, prev = dp[k - 1], dp[k]
        for b in range(m):
            for bp in range(b):
                if row[bp] == inf:
                    continue
                c = row[bp] + seg_cost(bnd_w[b] - bnd_w[bp], pauses[k] - pauses[k - 1])
                if c < prev[b]:
                    prev[b] = c
                    par[k][b] = bp
    best, best_b = inf, -1
    for b in range(m):
        if dp[n - 1][b] == inf:
            continue
        c = dp[n - 1][b] + seg_cost(total_w - bnd_w[b], dur_ms - tail - pauses[n - 1])
        if c < best:
            best, best_b = c, b
    if best_b < 0:
        return None
    picked = [0] * n
    b = best_b
    for k in range(n - 1, -1, -1):
        picked[k] = b
        b = par[k][b]
        if b < 0 and k > 0:
            return None
    pts = [(0.0, lead)]
    pts += [(bnd_w[picked[k]], pauses[k]) for k in range(n)]
    pts.append((total_w, dur_ms - tail))
    # 两个坐标都必须严格递增，且语速不能离谱——离谱就说明这次配对不可信
    out: list[tuple[float, float]] = []
    for w, t in pts:
        if out and (w <= out[-1][0] or t <= out[-1][1]):
            continue
        if out and not (1 / _RATE_BAND <= (t - out[-1][1]) / (w - out[-1][0]) / base_rate
                        <= _RATE_BAND):
            return None
        out.append((w, t))
    return out if len(out) >= _MIN_ANCHORS + 2 else None


def _warp_weight(anchors: list[tuple[float, float]], w: float) -> float:
    """累计权重 -> 时刻（锚点之间线性插值）。"""
    if w <= anchors[0][0]:
        return anchors[0][1]
    for (w0, t0), (w1, t1) in zip(anchors, anchors[1:], strict=False):
        if w <= w1:
            return t0 + (t1 - t0) * (w - w0) / max(w1 - w0, 1e-6)
    return anchors[-1][1]


def _events_from_pauses(spoken: str, mp3: Path) -> tuple[list[dict], int] | None:
    """只用「音频实测停顿 + 稿件标点」排出逐字时间轴，不采信任何服务端时间戳。

    字幕对不对得上，唯一判据是配音。所以时间轴的主路径是：找出配音里的每处
    停顿，按语速把它们配到稿件的标点边界上（_pause_anchors），中间按字数权重
    摊。返回 (事件, 锚点数)；配不出足够锚点返回 None（交给调用方走词流兜底）。"""
    dur_ms = _probe_ms(mp3)
    if dur_ms <= 0:
        return None
    pauses = pause_ends_ms(mp3)
    weights = _char_weights(spoken)
    total_w = sum(weights) or 1.0
    lead, tail = (120.0, 200.0) if dur_ms > 1500 else (0.0, 0.0)
    raw = _clause_char_starts(spoken)
    if len(raw) < 2:
        return None
    prefix = [0.0]
    for w in weights:
        prefix.append(prefix[-1] + w)
    anchors = _pause_anchors([prefix[a] for a in raw], total_w, pauses,
                             dur_ms, lead, tail)
    if anchors is None:
        return None
    events: list[dict] = []
    cum = 0.0
    for ch, w in zip(spoken, weights, strict=True):
        if not PUNCT.fullmatch(ch):
            t0 = _warp_weight(anchors, cum)
            t1 = _warp_weight(anchors, cum + w)
            events.append({"text": ch, "offset_ms": t0,
                           "duration_ms": max(t1 - t0, 1.0)})
        cum += w
    return (events, len(anchors)) if events else None


def _timeline(spoken: str, mp3: Path,
              word_events: list[dict] | None) -> tuple[list[dict], str, int]:
    """定字幕时间轴。返回 (事件, source, 锚点数)。

    路线按优先级：
    0. **自己听配音**拿逐字真实发声时刻（_asr_char_times）。这是 2026-09-22
       第三宗漂移的正解：配音渠道自报的词级时间戳是句内匀速编的（同一句每个
       字都是 201.666ms），真人却句内赶着说、停顿留句尾，照自报的排必然整体
       晚半秒。拿能量起振当硬尺量：自报轴句首平均晚 +0.57s，听出来的轴 +0.04s。
    1. 听不出来（没密钥/识别挂了/命中率 <0.75）：用词级时间戳 + 停顿小步校正。
    2. 连词流也没有：用配音实测停顿 + 稿件标点排（_events_from_pauses）。
    3. 都不成：按字数均匀摊。

    ⚠️ 2026-09-22 试过两条"用实测停顿给词流重新定刻度"的路，都**没有**上线，
    因为实测更差，别再走一遍：
      a) 只用停顿 + 字数的动态规划重排整条轴：事故段确实能压到 0ms，但它假设
         全片语速均匀——遇到"某句本来就念得慢"（实测 300ms/字 vs 均值 199）
         会把整段挪一格，尾部误差 1.7~2.5 秒，比不动还差；
      b) 把词流的子句首/空洞配到停顿上再拉伸：配对错一格就把同样的量带进来，
         尾部会连续几个子句塌到同一个时刻。
      c) 先把词流整体平移到停顿刻度上再判"是否互相印证"：听着对，实测 0.31→
         1.20 秒、58/58 全偏早——那个"不印证"本来就是 DP 挪格的表现，平移等于
         把判据作废。三条共同的教训：**停顿只能当刻度，不能当形状**。
    """
    at = _asr_char_times(spoken, mp3)
    if at is not None:
        ev = _events_from_char_times(spoken, at)
        if ev:
            return ev, "asr", len(pause_ends_ms(mp3))
    if word_events:
        ev, a = _blend_with_pauses(spoken, word_events, mp3)
        if a > 0:
            return ev, "word", a
        return word_events, "word", 0
    got = _events_from_pauses(spoken, mp3)
    if got is not None:
        return got[0], "estimate", got[1]
    ev, a = _estimate_events(spoken, mp3)
    return ev, "estimate", a


def _est_from_events(spoken: str, events: list[dict]) -> list[float] | None:
    """事件时间轴 → 每个字（含标点位置）的估计时刻。标点位置沿用前一个字的时刻。"""
    times: list[float] = []
    for ev in events:
        t = str(ev.get("text") or "")
        if not t:
            continue
        base = float(ev.get("offset_ms") or 0.0)
        dur = float(ev.get("duration_ms") or 0.0)
        for k, ch in enumerate(t):
            if PUNCT.fullmatch(ch):
                continue
            times.append(base + dur * k / max(len(t), 1))
    if len(times) < 2:
        return None
    out: list[float] = []
    j = 0
    prev = 0.0
    for ch in spoken:
        if PUNCT.fullmatch(ch):
            out.append(prev)
            continue
        if j < len(times):
            prev = times[j]
        out.append(prev)
        j += 1
    return out


def _blend_with_pauses(spoken: str, events: list[dict],
                       mp3: Path) -> tuple[list[dict], int]:
    """词流定形状、停顿做"互相印证过的小步校正"。

    服务端的词级时间戳整体偏 0.2~0.7 秒（实测），字幕跟着偏——就是用户听到的
    "从第 4 秒起声音领先字幕"。停顿 DP（_pause_anchors）能给出精确刻度，但它
    假设全片语速均匀，遇到某句本来就念得慢会把整段挪一格。

    所以只取两边**互相印证**的部分：某个子句首，DP 给的时刻与词流差在
    _BLEND_MS 内 → 说明 DP 这次没挪格，用 DP 的（刻度准）；差得更多 → 认定 DP
    这次错了，保留词流的（形状准）。两边都不足以单独定轴，合起来才既准又稳。"""
    dur_ms = _probe_ms(mp3)
    if dur_ms <= 0:
        return events, 0
    weights = _char_weights(spoken)
    total_w = sum(weights) or 1.0
    raw = _clause_char_starts(spoken)
    if len(raw) < 2:
        return events, 0
    prefix = [0.0]
    for w in weights:
        prefix.append(prefix[-1] + w)
    lead, tail = (120.0, 200.0) if dur_ms > 1500 else (0.0, 0.0)
    anchors = _pause_anchors([prefix[a] for a in raw], total_w,
                             pause_ends_ms(mp3), dur_ms, lead, tail)
    if anchors is None:
        return events, 0
    est_all = _est_from_events(spoken, events)
    if est_all is None:
        return events, 0
    spans = list(zip(raw, raw[1:] + [len(spoken)], strict=True))
    starts: list[float] = []
    for a, _b in spans:
        t_word = est_all[a]
        t_dp = _warp_weight(anchors, prefix[a])
        starts.append(t_dp if abs(t_dp - t_word) <= _BLEND_MS else t_word)
    for k in range(1, len(starts)):                    # 校正后仍不许倒挂
        starts[k] = max(starts[k], starts[k - 1])
    windows: list[tuple[float, float]] = []
    for k, (_a, b) in enumerate(spans):
        t0 = starts[k]
        t1 = starts[k + 1] if k + 1 < len(starts) else max(t0, est_all[b - 1] + 200.0)
        if windows:
            t0 = max(t0, windows[-1][1])
        windows.append((t0, max(t1, t0)))
    # 事件不带标点（与词流那条路同一个形状：下游 align_timeline 本来就按去标点
    # 的字数查表，形状一致才不会在子句边界上错位）
    out: list[dict] = []
    for e in _events_by_windows(spoken, weights, spans, windows):
        t = PUNCT.sub("", str(e["text"]))
        if t:
            out.append({"text": t, "offset_ms": e["offset_ms"],
                        "duration_ms": e["duration_ms"]})
    return out, len(anchors)


# ---------- 独立声学时间轴（2026-09-22 第三宗漂移：字幕整体晚半秒） ----------

_ASR_MODEL = "paraformer-realtime-v2"
_ASR_MIN_HIT = 0.75           # 逐字对位命中率低于此就不采信，退回词流那条路


def _asr_key(ch: str) -> str:
    """稿件字与识别字的公共比较键：汉字原样，数字（中文或阿拉伯）一律 #，
    拉丁字母一律 L。不这么归一，稿件"一千八百三十"对识别"1830"永远配不上。"""
    if re.match(r"[一-鿿]", ch):
        return ch
    if re.match(r"[0-9零一二两三四五六七八九十百千万亿]", ch):
        return "#"
    if re.match(r"[A-Za-z]", ch):
        return "L"
    return ""


def _dp_align(src: str, ref: str) -> list[int]:
    """全局对齐：src 每个字符对到 ref 的下标（-1=没对上）。

    不能用 str.find 逐个找：某一句没命中时游标不前进，后面每一句都会命中到
    **更晚的那一次重复**，一处错就整条链全错（实测把真值算成 0 秒）。"""
    n, m = len(src), len(ref)
    if not n or not m:
        return [-1] * n
    gap = 1.5
    prev = [float(j) for j in range(m + 1)]
    back: list[bytes] = []
    for i in range(1, n + 1):
        cur = [i * gap] + [0.0] * m
        row = bytearray(m + 1)
        row[0] = 1
        si = src[i - 1]
        for j in range(1, m + 1):
            c1 = prev[j] + gap
            c2 = cur[j - 1] + gap
            c3 = prev[j - 1] + (0.0 if si == ref[j - 1] else 1.0)
            best, k = c3, 3
            if c1 < best:
                best, k = c1, 1
            if c2 < best:
                best, k = c2, 2
            cur[j], row[j] = best, k
        back.append(bytes(row))
        prev = cur
    out = [-1] * n
    i, j = n, m
    while i > 0:
        k = back[i - 1][j]
        if k == 3:
            out[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif k == 1:
            i -= 1
        else:
            j -= 1
    return out


async def _asr_listen(mp3: Path) -> list[tuple[str, float, float]]:
    """让 paraformer 独立听一遍配音，返回逐字 (字, 起, 止) 毫秒。"""
    import websockets
    wav = mp3.with_suffix(".asr.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3),
                    "-ar", "16000", "-ac", "1", str(wav)], check=True, timeout=300)
    try:
        data = wav.read_bytes()
    finally:
        wav.unlink(missing_ok=True)
    url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference/"
    tid = uuid.uuid4().hex
    params = {"model": _ASR_MODEL, "format": "pcm", "sample_rate": 16000,
              "language_hints": ["zh"], "disfluency_removal_enabled": False,
              "punctuation_prediction_enabled": True, "word_timestamp_enabled": True}

    def msg(action):
        return json.dumps({"header": {"action": action, "task_id": tid, "streaming": "duplex"},
                           "payload": {"task_group": "audio", "task": "asr",
                                       "function": "recognition", "model": _ASR_MODEL,
                                       "parameters": params, "input": {}}})
    headers = {"Authorization": f"bearer {config.DASHSCOPE_API_KEY}",
               "user-agent": "GetCut/1.0"}
    live: dict = {}
    done: list[dict] = []
    async with websockets.connect(url, additional_headers=headers,
                                  max_size=None, open_timeout=20) as ws:
        await ws.send(msg("run-task"))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            if isinstance(raw, bytes):
                continue
            ev = json.loads(raw)
            e = (ev.get("header") or {}).get("event")
            if e == "task-started":
                break
            if e == "task-failed":
                raise RuntimeError(json.dumps(ev, ensure_ascii=False)[:300])
        for i in range(0, len(data), 6400):
            await ws.send(data[i:i + 6400])
        await ws.send(msg("finish-task"))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=180)
            if isinstance(raw, bytes):
                continue
            ev = json.loads(raw)
            e = (ev.get("header") or {}).get("event")
            if e == "result-generated":
                s = (((ev.get("payload") or {}).get("output") or {}).get("sentence")) or {}
                if not s:
                    continue
                rec = {"begin": s.get("begin_time"), "flag": s.get("sentence_end"),
                       "words": [(w.get("text") or "", w.get("begin_time") or 0,
                                  w.get("end_time") or 0) for w in (s.get("words") or [])]}
                if s.get("begin_time") in live and rec["flag"] is not True:
                    continue
                live[s.get("begin_time")] = rec
                if rec["flag"]:
                    done.append(rec)
                    live.pop(s.get("begin_time"), None)
            elif e == "task-finished":
                break
            elif e == "task-failed":
                raise RuntimeError(json.dumps(ev, ensure_ascii=False)[:300])
    out: list[tuple[str, float, float]] = []
    for rec in sorted(done + list(live.values()), key=lambda r: r["begin"] or 0):
        for t, b, e in rec["words"]:
            ks = [c for c in ("".join(_asr_key(ch) for ch in t)) if c]
            for k, ch in enumerate(ks):
                out.append((ch, b + (e - b) * k / max(len(ks), 1),
                            b + (e - b) * (k + 1) / max(len(ks), 1)))
    return out


def _asr_char_times(spoken: str, mp3: Path) -> list[float] | None:
    """每个稿件字的**真实发声时刻**（毫秒）。听不出来或命中率不够返回 None。

    为什么要多花这一次识别：配音渠道自报的词级时间戳是句内匀速编出来的
    （实测同一句每个字都是 201.666ms，一字不差），而真人是句内赶着说、
    把停顿留在句尾，所以照自报的排，字幕必然整体偏晚——实测晚 0.57 秒。"""
    side = mp3.with_suffix(".asr.json")
    try:
        if side.is_file():
            words = [tuple(x) for x in json.loads(side.read_text(encoding="utf-8"))]
        else:
            if not config.DASHSCOPE_API_KEY:
                return None
            words = asyncio.run(_asr_listen(mp3))
            if not words:
                return None
            side.write_text(json.dumps(words), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - 听不了就用词流那条路，绝不能让配音挂掉
        logging.warning("asr timeline unavailable: %s", e)
        return None
    if not words:
        return None
    ref = "".join(c for c, _b, _e in words)
    keys = [_asr_key(ch) for ch in spoken]
    src_idx = [i for i, k in enumerate(keys) if k]
    part = _dp_align("".join(keys[i] for i in src_idx), ref)
    if not src_idx or sum(1 for p in part if p >= 0) / len(src_idx) < _ASR_MIN_HIT:
        return None
    times: list[float | None] = [None] * len(spoken)
    for k, j in enumerate(part):
        if j >= 0:
            times[src_idx[k]] = words[j][1]
    # 没听出来的字（识别吞字/听错）在两侧已知的时刻之间线性补，不硬摊
    prev_i = None
    for i, t in enumerate(times):
        if t is None:
            continue
        if prev_i is not None and i - prev_i > 1:
            span = times[i] - times[prev_i]
            for k in range(prev_i + 1, i):
                times[k] = times[prev_i] + span * (k - prev_i) / (i - prev_i)
        prev_i = i
    if prev_i is not None:
        for k in range(prev_i + 1, len(times)):
            times[k] = times[prev_i]
    head = next((t for t in times if t is not None), None)
    if head is None:
        return None
    for k in range(len(times)):
        if times[k] is None:
            times[k] = head
    return _shift_by_onsets(spoken, [float(t) for t in times], pause_ends_ms(mp3))


def _shift_by_onsets(spoken: str, times: list[float], pauses: list[float]) -> list[float]:
    """把整条轴平移到"句首正好落在真实开口时刻"。

    识别服务报的字头比声音物理起振早 0.2~0.3 秒（它把前导也算进字头了）。直接
    拿它定轴，成片表现就是字幕先蹦出来、声音还没到。这里拿配音实测的停顿结束点
    当基准，把这一个整体提前量现算出来扣掉——不是拍脑袋填的常数。"""
    if not pauses or len(times) < 2:
        return times
    pts: list[float] = []
    j = 0
    for h in _sentence_head_indices(spoken):
        if h >= len(times):
            break
        t = times[h] / 1000.0
        while j < len(pauses) and pauses[j] / 1000.0 < t - 1.5:
            j += 1
        if j < len(pauses) and abs(pauses[j] / 1000.0 - t) <= 1.5:
            pts.append(t - pauses[j] / 1000.0)
            j += 1
    if len(pts) < 5:                      # 基准点太少就别动，宁可不校也别校错
        return times
    pts.sort()
    off = pts[len(pts) // 2] * 1000.0
    return [max(t - off, 0.0) for t in times]


def _sentence_head_indices(spoken: str) -> list[int]:
    """句子开头的字符下标。只用句读（。！？；），不把逗号当句首——逗号处往往
    根本没有停顿，拿它去配停顿会成片错配，把整条轴拽偏。"""
    out = [0]
    for i, ch in enumerate(spoken):
        if ch in "。！？；" and i + 1 < len(spoken):
            k = i + 1
            while k < len(spoken) and (spoken[k].isspace() or spoken[k] in "。！？；，、："):
                k += 1
            if k < len(spoken):
                out.append(k)
    return out


def _events_from_char_times(spoken: str, times: list[float]) -> list[dict]:
    """逐字时刻 → 事件流。不带标点，与词流那条路同一个形状，
    下游 planner.align_timeline 本来就按去标点的字数查表。"""
    out: list[dict] = []
    for i, ch in enumerate(spoken):
        if PUNCT.fullmatch(ch):
            continue
        nxt = next((j for j in range(i + 1, len(spoken))
                    if not PUNCT.fullmatch(spoken[j])), None)
        dur = max(times[nxt] - times[i], 1.0) if nxt is not None else 200.0
        out.append({"text": ch, "offset_ms": times[i], "duration_ms": dur})
    return out


# ---------- 时间戳质量（2026-09-22 字幕漂移修复） ----------

def _events_quality(spoken: str, events: list[dict], provider: str, source: str,
                    anchors: int = 0) -> dict:
    """标记时间戳从哪来：source="estimate"（按字数估算）时，字幕/分镜的
    句边界会随字数均匀摊，和真实语音的停顿逐渐对不上——成片表现为
    开头同步、越往后字幕越滞后。落进 tts_events.json 供 prep/verify 透出。
    anchors = 配到实测停顿上的锚点数（含词级路径的音频校正；≥3 才算真锚定）。"""
    chars = sum(len(str(e.get("text") or "")) for e in events)
    return {
        "provider": provider,
        "source": source,               # "word"=词级时间戳 | "estimate"=按字数估算
        "anchors": int(anchors),
        "anchor_v": _ANCHOR_V,          # 时间轴生成方式：旧缓存按它就地重算
        "recon_v": _RECON_V,            # 词流对位算法：对不上只能重新合成
        "events": len(events),
        "coverage": round(chars / max(len(spoken), 1), 3),
    }


def read_quality(out_dir: Path) -> dict | None:
    """读取配音时间戳的质量标记（旧缓存没有该字段时返回 None=未知）。"""
    try:
        meta = json.loads((Path(out_dir) / "tts_events.json").read_text(encoding="utf-8"))
        q = meta.get("quality")
        return q if isinstance(q, dict) else None
    except Exception:  # noqa: BLE001 - 缺文件/坏 JSON 一律当"未知"，不挡主流程
        return None


# ---------- 分句合成 + 实测摆放（2026-09-22 第四代：construct, don't reconstruct） ----------

SENTENCE_GAP_MS = 400        # 句间停顿（风格参数：资讯紧凑可降到 250，总长随之变短）
_SPLICE_V = 1                # 分句方案版本号：进缓存签名，旧时间轴缓存自动全部失效
_CLIP_CONCURRENCY = 4        # 逐句并发（百炼账号有并发上限，别拉满）
_CLIP_MAX_CHARS = 280        # 超长句保护：按逗号细切，子段之间无缝拼接
_SNAP_TOL_MS = 500.0         # 句内子句边界吸附该段实测停顿的容差
_SNAP_BAND = (0.4, 3.0)      # 锚点间"每权重耗时"允许偏离本段均值的倍数区间


def _split_long(seg: str) -> list[str]:
    """超长句按标点细切成 ≤_CLIP_MAX_CHARS 的子段（之间不留间隔）。"""
    pieces, start = [], 0
    for m in _BOUNDARY_RE.finditer(seg):
        if m.end() - start >= _CLIP_MAX_CHARS:
            pieces.append(seg[start:m.end()])
            start = m.end()
    pieces.append(seg[start:])
    return [p for p in pieces if p.strip()] or [seg]


def _clip_plan(spoken: str) -> list[tuple[str, int]]:
    """把稿子切成合成片段，返回 [(片段文本, 片段后间隔ms)]。
    句（。！？；）是天然切点；一句超过上限再按逗号细切（子段间 gap=0，
    拼起来仍是连续一句话，字幕不受影响）。"""
    heads = _sentence_head_indices(spoken) + [len(spoken)]
    plan: list[tuple[str, int]] = []
    for a, b in zip(heads, heads[1:], strict=False):
        seg = spoken[a:b]
        if not seg.strip():
            continue
        if len(seg) <= _CLIP_MAX_CHARS:
            plan.append((seg, SENTENCE_GAP_MS))
        else:
            pieces = _split_long(seg)
            plan.extend((p, 0 if k < len(pieces) - 1 else SENTENCE_GAP_MS)
                        for k, p in enumerate(pieces))
    return plan


async def _synth_clips(specs: list[tuple[str, int]], entry: dict, use_dash: bool,
                       rate: str, work: Path) -> list[Path]:
    """逐句合成（并发 _CLIP_CONCURRENCY，单句重试 3 次带退避）。
    一句失败只影响一句——这正是分句合成的另一半好处。"""
    sem = asyncio.Semaphore(_CLIP_CONCURRENCY)
    pv = entry.get("pv") or ""
    speech_rate = round(1.0 + rate_delta(rate), 3)
    edge_voice = entry.get("edge") or entry.get("id") or VOICE

    async def one(i: int, text: str) -> Path:
        out = work / f"clip_{i:03d}.mp3"
        async with sem:
            for attempt in range(3):
                try:
                    if out.exists():
                        out.unlink()
                    if use_dash:
                        await _dashscope_synth(text, pv, speech_rate, out, False)
                    else:
                        await _synth(text, edge_voice, rate or RATE, out)
                    if out.stat().st_size > 500:
                        return out
                    raise RuntimeError("合成返回空音频")
                except Exception:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.5 * (attempt + 1))
        return out

    return list(await asyncio.gather(*[one(i, t) for i, (t, _g) in enumerate(specs)]))


def _to_wav(mp3: Path) -> Path:
    """mp3 → 22050 单声道 wav。时长/停顿一律在 wav 上量：mp3 帧有编码器
    延迟和填充，拿它对时刻会把每段带进 ~0.1s 的系统误差。"""
    wav = mp3.with_suffix(".wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3),
                    "-ar", "22050", "-ac", "1", str(wav)], check=True, timeout=120)
    return wav


def _splice(wavs: list[Path], gaps: list[int], out_mp3: Path, work: Path) -> None:
    """按实测时长把各段物理拼接（wav 无缝 concat，最后一次性编码）。"""
    gap_files: dict[int, Path] = {}
    lines: list[str] = []
    for i, wav in enumerate(wavs):
        lines.append(f"file '{wav.resolve().as_posix()}'")
        g = gaps[i]
        if g > 0 and i < len(wavs) - 1:
            gp = gap_files.get(g)
            if gp is None:
                gp = work / f"gap_{g}.wav"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                                "-i", f"anullsrc=r=22050:cl=mono:d={g / 1000:.3f}",
                                "-c:a", "pcm_s16le", str(gp)], check=True, timeout=60)
                gap_files[g] = gp
            lines.append(f"file '{gp.resolve().as_posix()}'")
    lst = work / "concat.txt"
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c:a", "libmp3lame", "-q:a", "2", str(out_mp3)],
                   check=True, timeout=600)


def _clip_char_marks(text: str, wav: Path, dur_ms: float
                     ) -> tuple[list[tuple[str, float]], int]:
    """片段内每个非标点字符的相对时刻（ms）。

    均匀摊定形，句内子句边界（，、：后）吸附该段自己的实测停顿——段只有
    几秒，停顿和标点错也错不远，这正是整段音频上做不到的。"""
    weights = _char_weights(text)
    total_w = sum(weights) or 1.0
    prefix = [0.0]
    for w in weights:
        prefix.append(prefix[-1] + w)
    base = dur_ms / total_w
    anchors = [(0.0, 0.0), (total_w, dur_ms)]
    pauses = [p for p in pause_ends_ms(wav) if 80.0 < p < dur_ms - 80.0]
    used: list[float] = []
    for i in range(1, len(text)):
        if text[i - 1] not in "，、：":
            continue
        est = prefix[i] * dur_ms / total_w
        cand = [p for p in pauses
                if abs(p - est) <= _SNAP_TOL_MS and all(abs(p - u) > 60.0 for u in used)]
        if not cand:
            continue
        p = min(cand, key=lambda q: abs(q - est))
        used.append(p)
        anchors.append((prefix[i], p))
    anchors.sort()
    # 锚点间的语速不许离谱（离谱=吸附错了位置），丢掉肇事的内点重查
    while len(anchors) > 2:
        bad = None
        for k in range(1, len(anchors) - 1):
            (w0, t0), (w1, t1) = anchors[k - 1], anchors[k]
            slope = (t1 - t0) / max(w1 - w0, 1e-6)
            if not (base * _SNAP_BAND[0] <= slope <= base * _SNAP_BAND[1]):
                bad = k
                break
        if bad is None:
            break
        anchors.pop(bad)
    marks = [(ch, _warp_weight(anchors, prefix[j]))
             for j, ch in enumerate(text) if not PUNCT.fullmatch(ch)]
    return marks, len(anchors)


_SILENCE_FILTER_LEAD = "silencedetect=noise=-35dB:d=0.08"


def _lead_ms(wav: Path) -> float:
    """片段文件开头那段静音的时长（ms）。字幕要锚的是真实开口，不是文件头。
    只认"从 0 就开始"的静音（silence_start ≤ 0.05s），中途的停顿不当引子。"""
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "info", "-i", str(wav),
             "-af", _SILENCE_FILTER_LEAD, "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120)
    except Exception:  # noqa: BLE001 - 测不出就当 0，宁早勿晚的量级也只有几十毫秒
        return 0.0
    start = None
    for line in (r.stderr or "").splitlines():
        if "silence_start:" in line:
            try:
                start = float(line.split("silence_start:")[1].split("|")[0].strip())
            except ValueError:
                return 0.0
        elif "silence_end:" in line and start is not None:
            try:
                end = float(line.split("silence_end:")[1].split("|")[0].strip())
            except ValueError:
                return 0.0
            return end * 1000.0 if start <= 0.05 else 0.0
    return 0.0


def _splice_selfcheck(spoken: str, events: list[dict], mp3: Path) -> dict:
    """自检：构造的句首时刻 vs 成片配音能量实测的开口时刻（都换算成秒）。
    这是新方案唯一的"信不信"问题——理论上应≈0，量出来大就是拼接出了错。
    配对窗口收紧到 0.25s：句内逗号停顿离句首常常只有零点几秒，窗口宽了
    会把上一句的逗号开口配进来，报出假错。"""
    heads = set(_sentence_head_indices(spoken))
    starts: list[float] = []
    idx = 0
    for j, ch in enumerate(spoken):
        if PUNCT.fullmatch(ch):
            continue
        if j in heads and idx < len(events):
            starts.append(float(events[idx]["offset_ms"]))
        idx += 1
    pauses = [p / 1000.0 for p in pause_ends_ms(mp3)]      # pause_ends_ms 返回毫秒！
    pairs: list[float] = []
    j = 0
    for s in starts[1:]:
        t = s / 1000.0
        while j < len(pauses) and pauses[j] < t - 0.25:
            j += 1
        if j < len(pauses) and abs(pauses[j] - t) <= 0.25:
            pairs.append(t - pauses[j])
            j += 1
    return {"pairs": len(pairs), "expected": max(len(starts) - 1, 0),
            "signed_mean_s": round(sum(pairs) / len(pairs), 3) if pairs else 0.0,
            "worst_s": round(max((abs(x) for x in pairs), default=0.0), 3)}


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
    """合成配音，返回 (整条 mp3, 逐字事件)。

    事件与稿件同构（多音字替换等长，去标点后逐字对齐），下游
    planner.align_timeline 照旧按字数查表。时间轴来源见模块头注释：
    分句合成 + 实测摆放，不采信任何服务端时间戳。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3 = out_dir / "tts.mp3"
    meta = out_dir / "tts_events.json"
    spoken = apply_pronunciations(script, pronunciations)
    entry = resolve_voice(voice)
    use_dash = entry.get("provider") == "dashscope" and dashscope_ready()
    # 缓存签名：脚本/多音字/渠道/音色/语速/句间隔/方案版本任一变化都失效
    sig = hashlib.sha1("\x00".join([
        "splice", str(_SPLICE_V), str(SENTENCE_GAP_MS), spoken,
        json.dumps(pronunciations, ensure_ascii=False),
        "dash" if use_dash else "edge", str(entry.get("pv") or entry.get("edge")),
        rate or RATE]).encode("utf-8")).hexdigest()
    if mp3.exists() and meta.exists():
        try:
            cached = json.loads(meta.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("input_sig") == sig:
                return mp3, cached["events"]
        except Exception:  # noqa: BLE001 - 旧格式/损坏缓存一律重做
            pass

    specs = _clip_plan(spoken)
    if not specs:
        raise RuntimeError("稿件没有可合成的内容")
    work = out_dir / "clips"
    work.mkdir(parents=True, exist_ok=True)
    try:
        clips = asyncio.run(_synth_clips(specs, entry, use_dash, rate, work))
    except Exception as e:  # noqa: BLE001 - 渠道真挂了就明说，不悄悄降级成微软音
        channel = "百炼 CosyVoice" if use_dash else "微软 edge-tts"
        raise RuntimeError(f"配音服务暂时不可用（{channel}：{e}）") from e

    wavs = [_to_wav(c) for c in clips]
    durs = [_probe_ms(w) for w in wavs]
    if min(durs, default=0.0) <= 0.0:
        raise RuntimeError("配音片段时长测量失败（ffprobe），拒绝构造时间轴")
    _splice(wavs, [g for _t, g in specs], mp3, work)

    # 字幕时刻：句 k 起点 = 前面所有段实测时长 + 句间隔之和（构造上即真值）。
    # 每段再扣掉自己文件开头的静音（_lead_ms），让句首锚在真实开口而不是文件头；
    # 段内字符按 _clip_char_marks（均匀定形 + 段内停顿吸附）。
    events: list[dict] = []
    marks: list[tuple[str, float]] = []
    at = 0.0
    anchors = 0
    for (text, gap), wav, d in zip(specs, wavs, durs, strict=True):
        ms, n = _clip_char_marks(text, wav, d)
        anchors += n
        lead = _lead_ms(wav)
        marks.extend((ch, at + lead + t) for ch, t in ms)
        at += d + gap
    total = at - (specs[-1][1] if specs else 0.0)
    prev_t = -1.0
    for k, (ch, t) in enumerate(marks):
        t = max(t, prev_t)                       # 任何情况下不允许倒挂
        prev_t = t
        nxt = marks[k + 1][1] if k + 1 < len(marks) else min(total, t + 300.0)
        events.append({"text": ch, "offset_ms": t, "duration_ms": max(nxt - t, 1.0)})

    chk = _splice_selfcheck(spoken, events, mp3)
    if chk["expected"] > 0 and chk["pairs"] == 0:
        raise RuntimeError(
            f"配音时间轴自检失败：{chk['expected']} 个句首都配不上实测开口，"
            f"拼接或测量环节有错，拒绝出片")
    if chk["worst_s"] > 0.25:
        raise RuntimeError(
            f"配音时间轴自检失败：句首与实测开口最大偏差 {chk['worst_s']}s，拒绝出片")
    quality = {"provider": "dashscope" if use_dash else "edge", "source": "splice",
               "anchors": anchors, "anchor_v": _SPLICE_V,
               "events": len(events),
               "coverage": round(sum(len(e["text"]) for e in events)
                                 / max(len(spoken), 1), 3),
               "selfcheck": chk}
    meta.write_text(json.dumps(
        {"input_sig": sig, "events": events, "quality": quality},
        ensure_ascii=False), encoding="utf-8")
    log.info("timeline resolved", extra={"source": "splice", "clips": len(specs),
                                         "events": len(events), "selfcheck": chk})
    return mp3, events


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
