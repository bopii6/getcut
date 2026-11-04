# -*- coding: utf-8 -*-
"""8-bit 配乐 + 音效，纯 numpy 合成。"""
import os, math, wave
import numpy as np

SR = 44100
DUR = 36.0
N = int(SR * DUR)
OUT = r"E:\getcut\pixel-video\build\bgm.wav"

def env(n, a=0.004, d=0.10, sus=0.0):
    t = np.arange(n) / SR
    e = np.ones(n)
    an = max(int(a * SR), 1)
    e[:an] = np.linspace(0, 1, an)
    e[an:] = np.exp(-t[an:] / max(d, 1e-4))
    return e

def square(freq, n, duty=0.25, phase=0.0):
    t = np.arange(n) / SR
    ph = (t * freq + phase) % 1.0
    return np.where(ph < duty, 1.0, -1.0)

def tri(freq, n):
    t = np.arange(n) / SR
    ph = (t * freq) % 1.0
    return 4 * np.abs(ph - 0.5) - 1

def add(buf, start, sig, gain=1.0):
    i = int(start * SR)
    j = min(i + len(sig), len(buf))
    if i >= len(buf):
        return
    buf[i:j] += sig[: j - i] * gain

def note(freq, dur, gain=1.0, duty=0.25, decay=0.10, kind="sq"):
    n = int(dur * SR)
    if kind == "tri":
        s = tri(freq, n)
    else:
        s = square(freq, n, duty)
    return s * env(n, 0.003, decay) * gain

def noise_burst(dur, gain=1.0, decay=0.03, lp=0.5):
    n = int(dur * SR)
    rng = np.random.default_rng(5)
    s = rng.uniform(-1, 1, n)
    out = np.zeros(n)
    prev = 0.0
    for i in range(n):
        prev = prev + lp * (s[i] - prev)
        out[i] = prev
    return out * env(n, 0.001, decay) * gain

def sweep(f0, f1, dur, gain=1.0, duty=0.5, decay=0.2):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = f0 * (f1 / f0) ** (t / dur)
    ph = np.cumsum(f) / SR
    s = np.where((ph % 1.0) < duty, 1.0, -1.0)
    return s * env(n, 0.002, decay) * gain

def chime(root, dur=0.9, gain=1.0):
    n = int(dur * SR)
    out = np.zeros(n)
    for k, m in enumerate([1.0, 2.0, 3.0, 4.02]):
        out += note(root * m, dur, gain / (k + 1.6), 0.5, 0.9 - k * 0.18)
    return out

def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)

buf = np.zeros(N)

# ---------------------------------------------------------------- BGM
BPM = 100.0
beat = 60.0 / BPM
prog = [
    (45, [57, 60, 64]),   # Am
    (41, [53, 57, 60]),   # F
    (48, [48, 52, 55]),   # C
    (43, [55, 59, 62]),   # G
]
t = 0.0
bar = 0
while t < DUR - 0.2:
    root, chord = prog[bar % 4]
    add(buf, t, note(midi(root - 12), beat * 1.6, 0.30, 0.5, 0.5, "tri"))
    add(buf, t + beat * 2, note(midi(root - 12), beat * 1.2, 0.22, 0.5, 0.5, "tri"))
    for k in range(8):
        deg = [0, 1, 2, 1, 0, 2, 1, 2][k % 8]
        f = midi(chord[deg] + 12)
        add(buf, t + k * beat / 2, note(f, beat * 0.42, 0.085, 0.125, 0.09))
    for k in range(4):
        add(buf, t + k * beat, noise_burst(0.03, 0.05, 0.012, 0.7))
        add(buf, t + k * beat + beat / 2, noise_burst(0.02, 0.028, 0.008, 0.9))
    t += beat * 4
    bar += 1

# ---------------------------------------------------------------- SFX
sfx = np.zeros(N)
add(sfx, 0.02, sweep(120, 1400, 0.35, 0.5, 0.5, 0.5))
add(sfx, 0.10, noise_burst(0.5, 0.20, 0.18, 0.25))
# 标题逐字
for i in range(5):
    add(sfx, 2.35 + i / 14, note(midi(72 + i * 2), 0.05, 0.16, 0.5, 0.03))
add(sfx, 2.15, sweep(900, 300, 0.12, 0.22, 0.25, 0.06))
add(sfx, 3.05, chime(midi(84), 0.7, 0.14))
# 掌机
add(sfx, 4.02, sweep(300, 900, 0.2, 0.25, 0.5, 0.12))
for i in range(10):
    add(sfx, 4.55 + i * 0.18, note(midi(76 + (i % 4) * 3), 0.05, 0.10, 0.25, 0.03))
add(sfx, 7.30, note(midi(43), 0.5, 0.34, 0.5, 0.4, "tri"))
# 抖动
add(sfx, 11.02, sweep(1100, 220, 0.22, 0.22, 0.25, 0.1))
add(sfx, 11.55, chime(midi(79), 1.0, 0.12))
add(sfx, 13.40, sweep(220, 700, 0.18, 0.16, 0.5, 0.1))
add(sfx, 15.40, note(midi(81), 0.10, 0.14, 0.5, 0.06))
add(sfx, 17.40, note(midi(84), 0.10, 0.14, 0.5, 0.06))
# 对比
add(sfx, 20.02, sweep(1400, 200, 0.25, 0.20, 0.25, 0.1))
add(sfx, 23.22, sweep(200, 600, 0.16, 0.18, 0.5, 0.1))
add(sfx, 23.26, note(midi(74), 0.3, 0.12, 0.5, 0.2))
add(sfx, 26.05, chime(midi(76), 1.1, 0.16))
# 片尾
add(sfx, 29.02, sweep(900, 260, 0.3, 0.20, 0.25, 0.12))
for i in range(4):
    add(sfx, 29.6 + i * 0.6, note(midi(69 + [0, 3, 7, 12][i]), 0.12, 0.10, 0.5, 0.09))
add(sfx, 31.4, chime(midi(72), 1.4, 0.13))

# ---------------------------------------------------------------- mix
bgm = buf * 0.9
mix = bgm * 0.52 + sfx * 0.72
# 压缩一点，让手机外放时更“顶”
mix = np.tanh(mix * 2.2)
# 柔化方波的高次谐波，避免 AAC 编码后过冲削波
k = np.array([0.25, 0.5, 0.25])
mix = np.convolve(mix, k, mode="same")
mix = np.convolve(mix, k, mode="same")
fade_in = int(0.06 * SR)
mix[:fade_in] *= np.linspace(0, 1, fade_in)
fo = int(1.6 * SR)
mix[-fo:] *= np.linspace(1, 0, fo) ** 1.4
mix /= max(1e-6, np.abs(mix).max()) / 0.72

st = np.stack([mix, np.roll(mix, 8) * 0.98], axis=1)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
pcm = (np.clip(st, -1, 1) * 32767).astype("<i2")
with wave.open(OUT, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print("audio ->", OUT, f"{DUR}s")
