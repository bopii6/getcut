# -*- coding: utf-8 -*-
"""_reconcile_words：模拟 CosyVoice 的重发/乱序/吞字/断流重放，验证逐字对位。"""
import pytest

from videogen.planner import PUNCT
from videogen.tts import _reconcile_words


def _evtext(events):
    return "".join(PUNCT.sub("", e["text"]) for e in events)


def _monotonic(events):
    last = -1.0
    for e in events:
        if e["offset_ms"] < last - 1e-6 or e["duration_ms"] < 0:
            return False
        last = e["offset_ms"]
    return True


def _linear(chars, step=300.0, dur=280.0, skip=()):
    t = 0.0
    out = []
    for c in chars:
        if c in skip:
            continue
        out.append({"text": c, "begin_time": t, "end_time": t + dur})
        t += step
    return out


def _snapshots(occ, dur=280.0):
    """句子内/整轮累积重发：每帧把已合成词整段重发一遍（各自真实时间）。"""
    out, done = [], []
    for c, tm in occ:
        done.append((c, tm))
        for cc, ct in done:
            out.append({"text": cc, "begin_time": ct, "end_time": ct + dur})
    return out


SCRIPT = "一家公司一年翻十倍两万亿等于两个沙特阿美"
OCC = [(c, i * 300.0) for i, c in enumerate(SCRIPT)]


def test_clean_stream_exact():
    raw = _linear(SCRIPT)
    r = _reconcile_words(SCRIPT, raw, len(SCRIPT) * 300)
    assert r and _evtext(r) == SCRIPT and _monotonic(r)


def test_resend_frames_ignored():
    raw = []
    for i, c in enumerate(SCRIPT):
        raw.append({"text": c, "begin_time": i * 300.0, "end_time": (i + 1) * 300.0})
        if i % 7 == 3:
            raw.append({"text": SCRIPT[0], "begin_time": 80.0, "end_time": 200.0})
    r = _reconcile_words(SCRIPT, raw, len(SCRIPT) * 300)
    assert r and _evtext(r) == SCRIPT


def test_dropped_words_interpolated():
    script = "什么概念要抢人类历史上最大的IPO这个纪录"
    missing = "要抢人类历"
    raw = _linear(script, skip=set(missing))
    r = _reconcile_words(script, raw, 12000)
    assert r and _evtext(r) == script and _monotonic(r)
    i = next(k for k, e in enumerate(r) if e["text"] == "抢")
    prev_end = r[i - 1]["offset_ms"] + r[i - 1]["duration_ms"]
    nxt = r[i + len(missing)]["offset_ms"]
    assert prev_end - 1 <= r[i]["offset_ms"] <= nxt


def test_local_reorder_with_resend():
    raw = [
        {"text": "张", "begin_time": 0, "end_time": 200},
        {"text": "张", "begin_time": 100, "end_time": 250},
        {"text": "口", "begin_time": 250, "end_time": 450},
        {"text": "就要", "begin_time": 450, "end_time": 800},
        {"text": "两万亿", "begin_time": 800, "end_time": 1400},
    ]
    r = _reconcile_words("张口就要两万亿", raw, 1500)
    assert r and _evtext(r) == "张口就要两万亿"


def test_latin_word_split_frames():
    raw = [
        {"text": "刚被Sp", "begin_time": 0, "end_time": 500},
        {"text": "aceX", "begin_time": 500, "end_time": 900},
        {"text": "创下", "begin_time": 900, "end_time": 1300},
    ]
    r = _reconcile_words("刚被SpaceX创下", raw, 1400)
    assert r and _evtext(r) == "刚被SpaceX创下"


def test_cumulative_snapshots_full_replay():
    r = _reconcile_words(SCRIPT, _snapshots(OCC), len(SCRIPT) * 300 + 500)
    assert r and _evtext(r) == SCRIPT and _monotonic(r)
    worst = max(abs(e["offset_ms"] - tm) for e, (c, tm) in zip(r, OCC, strict=True))
    assert worst <= 400


def test_snapshots_with_midstream_drop():
    script = "什么概念要抢人类历史上最大"
    missing = "人类历"
    occ = [(c, i * 300.0) for i, c in enumerate(script)]
    raw = _snapshots([(c, tm) for c, tm in occ if c not in missing])
    r = _reconcile_words(script, raw, 10000)
    assert r and _evtext(r) == script


def test_pass_split_after_midstream_truncation():
    """第一轮发到一半断掉，第二轮从头完整重放（时间回跳 22800 > 15s 切轮）。"""
    occ = [(c, i * 1200.0) for i, c in enumerate(SCRIPT)]
    raw = _snapshots(occ[:6], dur=800.0) + _snapshots(occ, dur=800.0)
    r = _reconcile_words(SCRIPT, raw, 26000)
    assert r and _evtext(r) == SCRIPT
    worst = max(abs(e["offset_ms"] - tm) for e, (c, tm) in zip(r, occ, strict=True))
    assert worst <= 600


def test_unrelated_stream_falls_back_to_none():
    raw = _linear("完全不相干的一段文字内容", step=100.0, dur=50.0)
    assert _reconcile_words(SCRIPT, raw, 5000) is None


def test_empty_stream_falls_back_to_none():
    assert _reconcile_words(SCRIPT, [], 5000) is None


def test_real_stream_from_incident_replays_exact():
    """2026-09-22 线上事故的原始流样本（10585 帧截前 6000）重放：373 字逐字对齐。"""
    import json
    from pathlib import Path
    sample = Path(__file__).parent / "data" / "tts_replay_anthropic_ipo.json"
    if not sample.is_file():
        pytest.skip("事故流样本未随仓入库")
    d = json.loads(sample.read_text(encoding="utf-8"))
    script = d["script"]
    r = _reconcile_words(script, d["frames"], d["audio_ms"])
    assert r is not None
    assert _evtext(r) == PUNCT.sub("", script)
    assert _monotonic(r)


# 独立运行：python tests/test_tts_reconcile.py
if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
