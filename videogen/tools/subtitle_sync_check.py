#!/usr/bin/env python3
"""字幕↔配音对齐评分器：把一条素材包跑完整服务端链路，再用独立测量给字幕时间轴打分。

    python tools/subtitle_sync_check.py work/bundles/<bundle> [--json out.json]

为什么需要它：2026-09-22 一天里字幕漂移修了两轮（dd061da / 9802579），两轮都只
能靠耳朵判好坏，结果第二轮改完仍然"从头到尾晚一点点"却没人说得清差多少。这个
脚本把"差多少"变成一个数，任何改动改完跑一遍就知道是真好还是假好。

三条独立真值，互相校验：
  1. ffmpeg silencedetect 实测的"停顿结束点" = 下一段话真实开口的时刻（能量，最硬）
  2. paraformer 逐字时间戳 = 每个字真实被说出来的时刻（能覆盖句内，但字头偏早）
  3. 两者在"句首"这一批可配对的位置上求中位差，作为 2 的尺子校准量

判据为什么是"晚/早"不对称：纯抖动应该两边各半。若 46 句里 38 句都朝一个方向偏，
那就是时间轴被系统性推后了，常数平移能治；若平移后 mean|d| 不降，说明主体是抖动，
得换真值来源（句内形状），别再去调常数。

退出码：mean|d| 或 p90 超阈值返回 1，可直接进 CI/门禁。
阈值定在 0.55 / 1.10 的依据 = 2026-09-22 两条真实素材包的实测上包络
（Anthropic 0.31/0.71、F35 0.41/0.78）；它拦得住真实回归（一次误改实测 1.20/1.61），
又不误伤现状。要收紧必须先有更好的一条成片作证据。

前置：需要 DASHSCOPE_API_KEY（配音走百炼、真值走 paraformer）。没有它本机
会退回 edge 渠道，测出来的时间戳质量跟线上不是一回事，数字不可信。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, os.environ.get("VG_PKG")
                or str(Path(__file__).resolve().parent.parent))

from videogen import tts                                          # noqa: E402
from videogen.planner import align_timeline, split_clauses        # noqa: E402
from videogen.schemas import Content                              # noqa: E402

GATE_MEAN_S = 0.55
GATE_P90_S = 1.10

_CJK = re.compile(r"[一-鿿]")
_NUMC = re.compile(r"[0-9零一二两三四五六七八九十百千万亿]")
_LATC = re.compile(r"[A-Za-z]")
_PUNCT = re.compile(r"[\s，。、；：！？…—・·\"'“”‘’（）()《》\[\]【】,.!?;:\-]")


def norm(s: str) -> str:
    """逐字归一成稿件与 ASR 的公共键：汉字原样、数字（中文或阿拉伯）统一 #、
    拉丁字母统一 L。稿件写"一千八百三十"、ASR 回"1830"，字符数不同，
    长度差异交给 DP 用插空吸收——绝不能用 find() 硬找。"""
    out = []
    for ch in _PUNCT.sub("", s or ""):
        if _CJK.match(ch):
            out.append(ch)
        elif _NUMC.match(ch):
            out.append("#")
        elif _LATC.match(ch):
            out.append("L")
    return "".join(out)


def align(src: str, ref: str) -> list[int]:
    """全局 DP：src 每个字符对到 ref 的下标（-1=没对上）。O(len(src)*len(ref))。"""
    n, m = len(src), len(ref)
    if not n or not m:
        return [-1] * n
    gap = 1.5
    prev = list(range(m + 1))
    back: list[bytes] = []
    for i in range(1, n + 1):
        cur = [i * gap] + [0.0] * m
        row = bytearray(m + 1)
        row[0] = 1
        for j in range(1, m + 1):
            c1 = prev[j] + gap              # src 这个字在 ASR 里没有对应
            c2 = cur[j - 1] + gap           # ASR 这个字是插入
            c3 = prev[j - 1] + (0.0 if src[i - 1] == ref[j - 1] else 1.0)
            best, k = (c3, 3)
            if c1 < best:
                best, k = (c1, 1)
            if c2 < best:
                best, k = (c2, 2)
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
            i, j = i - 1, j
        else:
            j -= 1
    return out


async def asr_words(mp3: Path) -> list[list]:
    """独立真值：让 paraformer 听一遍，返回逐字 [char, begin_ms, end_ms]。"""
    import websockets
    fd, wav_name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    wav = Path(wav_name)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3),
                    "-ar", "16000", "-ac", "1", str(wav)], check=True, timeout=300)
    data = wav.read_bytes()
    wav.unlink(missing_ok=True)
    url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference/"
    tid = uuid.uuid4().hex
    params = {"model": "paraformer-realtime-v2", "format": "pcm", "sample_rate": 16000,
              "language_hints": ["zh"], "disfluency_removal_enabled": False,
              "punctuation_prediction_enabled": True, "word_timestamp_enabled": True}

    def msg(action):
        return json.dumps({"header": {"action": action, "task_id": tid, "streaming": "duplex"},
                           "payload": {"task_group": "audio", "task": "asr",
                                       "function": "recognition", "model": params["model"],
                                       "parameters": params, "input": {}}})
    headers = {"Authorization": f"bearer {os.environ['DASHSCOPE_API_KEY']}",
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
                       "words": [[w.get("text") or "", w.get("begin_time") or 0,
                                  w.get("end_time") or 0] for w in (s.get("words") or [])]}
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
    out: list[list] = []
    for rec in sorted(done + list(live.values()), key=lambda r: r["begin"] or 0):
        for t, b, e in rec["words"]:
            ks = norm(t)
            for k, ch in enumerate(ks):
                out.append([ch, b + (e - b) * k / max(len(ks), 1),
                            b + (e - b) * (k + 1) / max(len(ks), 1)])
    return out


def measure(bundle: Path, verbose: bool = True) -> dict:
    """跑一遍服务端链路并打分，返回指标 dict（含 'ok' 与逐子句明细）。"""
    lines: list[str] = []
    w = lines.append
    content = Content.load(bundle / "content.json")
    w("bundle : %s" % bundle.name)
    w("title  : %s" % content.title)
    if not tts.dashscope_ready():
        w("!! 百炼不可用，配音会退回 edge 渠道 —— 下面的数字与线上不同源，别拿去做判断")

    work = Path(tempfile.mkdtemp(prefix="sync-check-"))
    mp3, events = tts.synthesize(content.script, content.pronunciations, work / "tts",
                                 voice=tts.VOICE, rate=tts.RATE)
    clauses = align_timeline(split_clauses(content), events)
    dur = tts._probe_ms(mp3)
    spoken = tts.apply_pronunciations(content.script, content.pronunciations)
    ev_chars = sum(len(str(e["text"])) for e in events)
    pauses = tts.pause_ends_ms(mp3)
    w("audio  : %.2fs  clauses=%d  实测停顿(锚点)=%d  词级覆盖率=%.3f" % (
        dur / 1000.0, len(clauses), len(pauses), ev_chars / max(len(spoken), 1)))

    cache = Path(tempfile.gettempdir()) / "vg_asr_cache"
    cache.mkdir(exist_ok=True)
    ck = cache / (hashlib.md5(mp3.read_bytes()).hexdigest() + ".json")
    if ck.is_file():
        words = json.loads(ck.read_text(encoding="utf-8"))
    else:
        words = asyncio.run(asr_words(mp3))
        ck.write_text(json.dumps(words), encoding="utf-8")
    chars = [(c, b, e) for c, b, e in words]
    ref = "".join(c for c, _b, _e in chars)
    src_pairs = [(ch, ci) for ci, c in enumerate(clauses) for ch in norm(c.text)]
    src = "".join(ch for ch, _c in src_pairs)
    part = align(src, ref)
    first_t: dict[int, float] = {}
    for k, j in enumerate(part):
        if j >= 0 and src_pairs[k][1] not in first_t:
            first_t[src_pairs[k][1]] = chars[j][1]
    hit = sum(1 for p in part if p >= 0)
    w("真值   : ASR %d 字 / DP 命中 %d (%.0f%%)" % (
        len(chars), hit, 100 * hit / max(len(src), 1)))
    if hit / max(len(src), 1) < 0.8:
        w("!! 对位命中率过低，本次指标不可用（ASR 质量或稿件被改过）")

    # 尺子校准：ASR 字头比能量起振早，用句首可配对的两列求中位差
    head = [0] + [i for i in range(1, len(clauses))
                  if clauses[i].sent_index != clauses[i - 1].sent_index]
    triples, jj = [], 0
    for i in head:
        if i not in first_t:
            continue
        a = first_t[i] / 1000.0
        while jj < len(pauses) and pauses[jj] / 1000.0 < a - 1.5:
            jj += 1
        if jj < len(pauses) and abs(pauses[jj] / 1000.0 - a) <= 1.5:
            triples.append((a, clauses[i].start_ms / 1000.0, pauses[jj] / 1000.0))
            jj += 1
    pairs = sorted(t[0] - t[2] for t in triples)
    bias = pairs[len(pairs) // 2] if pairs else 0.0
    w("校准   : 句首配对 %d 对，ASR 字头比能量起振早 %.2fs（已从 real 中扣除）" % (
        len(pairs), bias))

    # 同一把硬尺（能量起振）量两条候选轴的刻度精度：ASR 逐字时间戳 vs 现在这条。
    # 谁在"真实开口时刻"上散度小，谁才配当轴；不这么比就是拿一把尺去量另一把尺。
    def _scatter(xs: list[float]) -> str:
        if len(xs) < 5:
            return "样本不足"
        s = sorted(abs(x) for x in xs)
        return "p50=%.2fs p90=%.2fs 均值=%+.2fs" % (
            s[len(s) // 2], s[min(int(len(s) * 0.9), len(s) - 1)], sum(xs) / len(xs))
    w("刻度对比: ASR 轴对能量起振  %s" % _scatter([t[0] - t[2] - bias for t in triples]))
    w("刻度对比: 现轴对能量起振    %s" % _scatter([t[1] - t[2] for t in triples]))

    deltas = []
    for i, c in enumerate(clauses):
        if i not in first_t:
            continue
        deltas.append({"i": i, "text": c.text,
                       "plan_s": round(c.start_ms / 1000.0, 3),
                       "real_s": round(first_t[i] / 1000.0 - bias, 3),
                       "delta_s": round(c.start_ms / 1000.0 - (first_t[i] / 1000.0 - bias), 3)})
    if not deltas:
        w("!! 没有任何子句可对位，指标无法计算")
        return {"ok": False, "reason": "no-deltas", "lines": lines}

    v = [d["delta_s"] for d in deltas]
    av = sorted(abs(x) for x in v)
    n = len(v)
    mean_abs = sum(av) / n
    p90 = av[min(int(n * 0.9), n - 1)]
    signed = sum(v) / n
    late = sum(1 for x in v if x > 0)
    early = n - late
    gaps = sorted((b - a) / 1000.0 for a, b in zip(pauses, pauses[1:], strict=False))
    w("")
    w("mean|d|=%.2fs  p50=%.2fs  p90=%.2fs  max=%.2fs" % (
        mean_abs, av[n // 2], p90, av[-1]))
    w(">0.5s: %d/%d   >1.0s: %d   带符号均值=%+.2fs   晚=%d 早=%d" % (
        sum(1 for x in v if abs(x) > 0.5), n, sum(1 for x in v if abs(x) > 1.0),
        signed, late, early))
    w("相邻停顿: 中位 %.1fs 最长 %.1fs（最长那段没有锚点，全靠摊）" % (
        gaps[len(gaps) // 2] if gaps else 0, gaps[-1] if gaps else 0))
    w("门禁   : mean|d|<=%.2f 且 p90<=%.2f -> %s" % (
        GATE_MEAN_S, GATE_P90_S, "PASS" if mean_abs <= GATE_MEAN_S and p90 <= GATE_P90_S else "FAIL"))
    if verbose:
        w("")
        w("逐子句（正=字幕晚于声音）")
        for d in deltas:
            w("  [%2d] %8.2f %8.2f %+7.2f  %s" % (
                d["i"], d["plan_s"], d["real_s"], d["delta_s"], d["text"][:24]))
    ok = mean_abs <= GATE_MEAN_S and p90 <= GATE_P90_S
    return {"ok": ok, "mean_abs_s": round(mean_abs, 3), "p50_s": round(av[n // 2], 3),
            "p90_s": round(p90, 3), "max_s": round(av[-1], 3), "signed_s": round(signed, 3),
            "late": late, "early": early, "n": n, "clauses": len(clauses),
            "anchors": len(pauses), "coverage": round(ev_chars / max(len(spoken), 1), 3),
            "asr_bias_s": round(bias, 3), "max_pause_gap_s": round(gaps[-1], 2) if gaps else None,
            "deltas": deltas, "lines": lines}


def main() -> int:
    ap = argparse.ArgumentParser(description="字幕↔配音对齐评分器")
    ap.add_argument("bundle", type=Path, help="素材包目录（含 content.json）")
    ap.add_argument("--json", type=Path, default=None, help="指标输出到该文件")
    ap.add_argument("--quiet", action="store_true", help="不打印逐子句明细")
    a = ap.parse_args()
    r = measure(a.bundle, verbose=not a.quiet)
    for ln in r.pop("lines", []):
        print(ln)
    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(
            json.dumps(r, ensure_ascii=False, indent=1))
        print("wrote %s" % a.json)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
