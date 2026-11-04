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

/** 把每句按时间轴拼成一条完整音轨（48k 双声道）。 */
export function buildTimeline(voiced: Voiced[], sampleRate = 48000, channels = 2): AudioBuffer {
  const total = voiced.reduce((n, v) => n + v.duration, 0);
  const frames = Math.ceil(total * sampleRate);
  const buf = new AudioBuffer({ length: Math.max(1, frames), numberOfChannels: channels, sampleRate });
  let offset = 0;
  for (const v of voiced) {
    for (let ch = 0; ch < channels; ch++) {
      const src = v.buffer.getChannelData(Math.min(ch, v.buffer.numberOfChannels - 1));
      buf.copyToChannel(src, ch, Math.round(offset * sampleRate));
    }
    offset += v.duration;
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




