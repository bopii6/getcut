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

function b64ToBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

/**
 * 逐句配音。5 句一批走 /api/tts/batch：
 * - 请求数从 N 次降到 N/5，服务端也能按批排队
 * - 某一批失败就退回单句，坏一句不毁整条
 */
export async function voiceAll(
  texts: string[],
  onProgress?: (done: number, total: number) => void,
  voice = 'zh-CN-YunxiNeural',
): Promise<Voiced[]> {
  const ac = new AudioContext({ sampleRate: 48000 });
  const out: Voiced[] = [];
  const BATCH = 5;

  const push = async (text: string, raw: ArrayBuffer) => {
    const buffer = await ac.decodeAudioData(raw);
    out.push({ text, buffer, duration: buffer.duration + 0.18 });
    onProgress?.(out.length, texts.length);
  };

  for (let start = 0; start < texts.length; start += BATCH) {
    const chunk = texts.slice(start, start + BATCH);
    let items: { i: number; b64?: string; error?: string }[] = [];
    try {
      const res = await fetch(api('/api/tts/batch'), {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ texts: chunk, voice }),
      });
      if (!res.ok) throw new Error(String(res.status));
      items = (await res.json()).items || [];
    } catch {
      items = chunk.map((_, i) => ({ i, error: 'batch failed' }));
    }

    for (let k = 0; k < chunk.length; k++) {
      const it = items.find((x) => x.i === k);
      if (it?.b64) {
        await push(chunk[k], b64ToBuffer(it.b64));
      } else {
        // 兜底：单句重试一次
        try {
          await push(chunk[k], await tts(chunk[k], voice));
        } catch (e) {
          throw new Error(`第 ${start + k + 1} 句配音失败：${e instanceof Error ? e.message : e}`);
        }
      }
    }
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
  segments: { duration: number; buffer?: AudioBuffer | null }[],
  { sampleRate = 48000, channels = 2, bgm = null, bgmGain = 0.34, duckTo = 0.42 } = {} as {
    sampleRate?: number; channels?: number; bgm?: AudioBuffer | null; bgmGain?: number; duckTo?: number;
  },
): AudioBuffer {
  const total = segments.reduce((n, v) => n + v.duration, 0);
  const frames = Math.max(1, Math.ceil(total * sampleRate));
  const buf = new AudioBuffer({ length: frames, numberOfChannels: channels, sampleRate });

  // 1. 配音（没有音频的段——片头卡、章节卡——留等长静音，保证音画严格同步）
  //    源音频的采样率可能和输出不同（手机上有时只支持 44.1k），按比例取样，避免变调走速
  const voice = new Float32Array(frames);
  const speaking = new Uint8Array(frames);
  let offset = 0;
  for (const v of segments) {
    const start = Math.round(offset * sampleRate);
    if (v.buffer) {
      const src = v.buffer.getChannelData(0);
      const ratio = v.buffer.sampleRate / sampleRate;
      const outLen = Math.min(Math.ceil(src.length / ratio), Math.max(0, frames - start));
      for (let i = 0; i < outLen; i++) {
        const s = Math.min(src.length - 1, Math.floor(i * ratio));
        voice[start + i] = src[s];
      }
      // 说话区间（前后各留 80ms，避免 BGM 提早抬起）
      const pad = Math.round(0.08 * sampleRate);
      const from = Math.max(0, start - pad);
      const to = Math.min(frames, start + outLen + pad);
      for (let i = from; i < to; i++) speaking[i] = 1;
    }
    offset += v.duration;
  }

  // 2. BGM + 闪避
  const music = new Float32Array(frames);
  if (bgm) {
    const src = bgm.getChannelData(0);
    const n = src.length;
    const step = bgm.sampleRate / sampleRate;
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
      music[i] = src[Math.floor(i * step) % n] * g;
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

export type AudioCfg = { codec: string; sampleRate: number; numberOfChannels: number; bitrate: number };

/**
 * 挑一个这台设备真的支持的音频配置。
 * 手机上有些机型只支持 44.1k，或者只支持单声道；支持不了就返回 null，让上层明确报错，
 * 绝不能像以前那样"配不上也继续跑"，最后出个没声音的片子。
 */
export async function pickAudioConfig(): Promise<AudioCfg | null> {
  if (typeof AudioEncoder === 'undefined') return null;
  const candidates: AudioCfg[] = [
    { codec: 'mp4a.40.2', sampleRate: 48000, numberOfChannels: 2, bitrate: 128000 },
    { codec: 'mp4a.40.2', sampleRate: 44100, numberOfChannels: 2, bitrate: 128000 },
    { codec: 'mp4a.40.2', sampleRate: 48000, numberOfChannels: 1, bitrate: 96000 },
    { codec: 'mp4a.40.2', sampleRate: 44100, numberOfChannels: 1, bitrate: 96000 },
  ];
  for (const c of candidates) {
    try {
      const r = await AudioEncoder.isConfigSupported(c);
      if (r.supported) return c;
    } catch {
      /* 试下一个 */
    }
  }
  return null;
}

/** 把音轨按 1024 帧切片，交给 AudioEncoder 编 AAC；返回实际编出来的 chunk 数。 */
export async function encodeAudio(
  buffer: AudioBuffer,
  onChunk: (chunk: EncodedAudioChunk, meta?: EncodedAudioChunkMetadata) => void,
  onProgress?: (p: number) => void,
  cfg: AudioCfg = { codec: 'mp4a.40.2', sampleRate: 48000, numberOfChannels: 2, bitrate: 128000 },
): Promise<number> {
  const channels = buffer.numberOfChannels;
  const sampleRate = buffer.sampleRate;
  let encoderError: Error | null = null;
  let chunks = 0;

  const encoder = new AudioEncoder({
    output: (chunk, meta) => { chunks += 1; onChunk(chunk, meta); },
    error: (e) => {
      // 关键：以前这里直接 throw，异常落在回调里没人接，跑完就出无声片
      encoderError = new Error(`音频编码器异常：${e instanceof Error ? e.message : String(e)}`);
    },
  });
  encoder.configure({
    codec: cfg.codec,
    sampleRate,
    numberOfChannels: channels,
    bitrate: cfg.bitrate,
    aac: { format: 'aac' },   // 必须是 raw AAC；ADTS 会让 MP4 的音轨不可播
  });

  const chunkFrames = 1024;
  const total = buffer.length;
  const chans: Float32Array[] = [];
  for (let c = 0; c < channels; c++) chans.push(buffer.getChannelData(c));

  for (let start = 0; start < total; start += chunkFrames) {
    if (encoderError) throw encoderError;
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
  if (encoderError) throw encoderError;
  encoder.close();
  onProgress?.(1);
  return chunks;
}






