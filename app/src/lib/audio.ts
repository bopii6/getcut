// 配音：走本机代理（部署时换成 Worker）。拿 mp3 → WebAudio 解码 → 拼成一条音轨。
import { api } from './api';

export async function tts(text: string, voice = 'zh-CN-YunxiNeural'): Promise<ArrayBuffer> {
  const res = await fetch(api('/api/tts'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text, voice }),
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => '');
    throw new Error(`配音失败（${res.status}）：${msg.slice(0, 120)}`);
  }
  return res.arrayBuffer();
}

export type Voiced = { text: string; buffer: AudioBuffer; duration: number };

export async function voiceAll(
  texts: string[],
  onProgress?: (done: number, total: number) => void,
): Promise<Voiced[]> {
  const ac = new AudioContext({ sampleRate: 48000 });
  const out: Voiced[] = [];
  for (let i = 0; i < texts.length; i++) {
    const raw = await tts(texts[i]);
    const buffer = await ac.decodeAudioData(raw);
    out.push({ text: texts[i], buffer, duration: buffer.duration + 0.18 });
    onProgress?.(i + 1, texts.length);
  }
  await ac.close();
  return out;
}

/** 解码一首 BGM；失败返回 null（没音乐也能出片）。 */
export async function loadMusic(url: string): Promise<AudioBuffer | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const raw = await res.arrayBuffer();
    const ac = new AudioContext({ sampleRate: 48000 });
    const buf = await ac.decodeAudioData(raw);
    await ac.close();
    return buf;
  } catch {
    return null;
  }
}

/**
 * 把配音和 BGM 拼成一条音轨（48k 双声道）。
 * - BGM 循环铺满，整体音量压在人声之下
 * - 人声出现时自动压低 BGM（attack/release 一阶平滑），人声停了再抬回来
 * - 开头 0.4 秒淡入、结尾 1.2 秒淡出
 */
export function buildTimeline(
  voiced: Voiced[],
  { sampleRate = 48000, channels = 2, bgm = null, bgmGain = 0.34, duckTo = 0.42 } = {} as {
    sampleRate?: number; channels?: number; bgm?: AudioBuffer | null; bgmGain?: number; duckTo?: number;
  },
): AudioBuffer {
  const total = voiced.reduce((n, v) => n + v.duration, 0);
  const frames = Math.max(1, Math.ceil(total * sampleRate));
  const buf = new AudioBuffer({ length: frames, numberOfChannels: channels, sampleRate });

  // 1. 配音
  const voice = new Float32Array(frames);
  const speaking = new Uint8Array(frames);
  let offset = 0;
  for (const v of voiced) {
    const start = Math.round(offset * sampleRate);
    const src = v.buffer.getChannelData(0);
    for (let i = 0; i < src.length && start + i < frames; i++) voice[start + i] = src[i];
    // 说话区间（前后各留 80ms，避免 BGM 提早抬起）
    const pad = Math.round(0.08 * sampleRate);
    const from = Math.max(0, start - pad);
    const to = Math.min(frames, start + src.length + pad);
    for (let i = from; i < to; i++) speaking[i] = 1;
    offset += v.duration;
  }

  // 2. BGM + 闪避
  const music = new Float32Array(frames);
  if (bgm) {
    const src = bgm.getChannelData(0);
    const n = src.length;
    const attack = 1 - Math.exp(-1 / (0.08 * sampleRate));   // 80ms
    const release = 1 - Math.exp(-1 / (0.35 * sampleRate));  // 350ms
    let env = 1;
    const fadeIn = Math.round(0.4 * sampleRate);
    const fadeOut = Math.round(1.2 * sampleRate);
    for (let i = 0; i < frames; i++) {
      const target = speaking[i] ? duckTo : 1;
      env += (target - env) * (target < env ? attack : release);
      let g = bgmGain * env;
      if (i < fadeIn) g *= i / fadeIn;
      if (i > frames - fadeOut) g *= Math.max(0, (frames - i) / fadeOut);
      music[i] = src[i % n] * g;
    }
  }

  // 3. 混音（简单限幅，避免爆音）
  for (let ch = 0; ch < channels; ch++) {
    const out = new Float32Array(frames);
    for (let i = 0; i < frames; i++) {
      const s = voice[i] + music[i];
      out[i] = s > 1 ? 1 : s < -1 ? -1 : s;
    }
    buf.copyToChannel(out, ch);
  }
  return buf;
}

/** 把音轨按 1024 帧切片，交给 AudioEncoder 编 AAC。 */
export async function encodeAudio(
  buffer: AudioBuffer,
  onChunk: (chunk: EncodedAudioChunk, meta?: EncodedAudioChunkMetadata) => void,
  onProgress?: (p: number) => void,
  bitrate = 128000,
) {
  const channels = buffer.numberOfChannels;
  const sampleRate = buffer.sampleRate;
  const encoder = new AudioEncoder({
    output: (chunk, meta) => onChunk(chunk, meta),
    error: (e) => { throw e; },
  });
  encoder.configure({ codec: 'mp4a.40.2', sampleRate, numberOfChannels: channels, bitrate });

  const chunkFrames = 1024;
  const total = buffer.length;
  const chans: Float32Array[] = [];
  for (let c = 0; c < channels; c++) chans.push(buffer.getChannelData(c));

  for (let start = 0; start < total; start += chunkFrames) {
    const n = Math.min(chunkFrames, total - start);
    const interleaved = new Float32Array(n * channels);
    // f32-planar：先放所有声道的第 0 段，再放第 1 段…
    for (let c = 0; c < channels; c++) {
      interleaved.set(chans[c].subarray(start, start + n), c * n);
    }
    const data = new AudioData({
      format: 'f32-planar',
      sampleRate,
      numberOfFrames: n,
      numberOfChannels: channels,
      timestamp: Math.round((start / sampleRate) * 1_000_000),
      data: interleaved,
    });
    encoder.encode(data);
    data.close();
    if (start % (chunkFrames * 50) === 0) {
      onProgress?.(start / total);
      await new Promise((r) => setTimeout(r, 0));
    }
  }
  await encoder.flush();
  encoder.close();
  onProgress?.(1);
}




