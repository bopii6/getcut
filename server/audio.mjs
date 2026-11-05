// 音频：Node 里没有 WebAudio，用 ffmpeg 解码 + 纯数组混音。
// 混音逻辑照抄 app/src/lib/audio.ts 的 buildTimeline（人声铺轨 + BGM 闪避 + 首尾淡入淡出），
// 只是把 AudioBuffer 换成 { sampleRate, channels: Float32Array[] }，算法一个数都没改——
// 改一个数，服务端出的片和 Web 端听起来就不是一条了。
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, writeFile } from 'node:fs/promises';

const run = promisify(execFile);

export const OUT_RATE = 48000;

/** 解成单声道 48k 浮点；人声轨本来就只要第一声道。 */
export async function decodeMono(file, sampleRate = OUT_RATE) {
  const { stdout } = await run(
    'ffmpeg',
    ['-v', 'error', '-i', file, '-f', 'f32le', '-ac', '1', '-ar', String(sampleRate), '-'],
    { encoding: 'buffer', maxBuffer: 512 * 1024 * 1024 },
  );
  const buf = Buffer.isBuffer(stdout) ? stdout : Buffer.from(stdout);
  // Buffer 的底层可能没对齐到 4 字节，必须拷贝一份再当 Float32Array 使
  const copy = new Uint8Array(buf.byteLength);
  copy.set(buf);
  return {
    sampleRate,
    data: new Float32Array(copy.buffer, 0, Math.floor(copy.byteLength / 4)),
    seconds: copy.byteLength / 4 / sampleRate,
  };
}

export async function probeDuration(file) {
  const { stdout } = await run('ffprobe', [
    '-v', 'error',
    '-show_entries', 'format=duration',
    '-of', 'default=nw=1:nk=1',
    file,
  ]);
  const n = Number(String(stdout).trim());
  if (!Number.isFinite(n)) throw new Error(`读不出时长：${file}`);
  return n;
}

/**
 * 按时间轴铺一条完整音轨。
 * @param {{duration:number, pcm?:{sampleRate:number,data:Float32Array}|null}[]} segments
 * @param {{sampleRate?:number, channels?:number, bgm?:object|null, bgmGain?:number, duckTo?:number}} opts
 */
export function buildTimeline(segments, opts = {}) {
  const {
    sampleRate = OUT_RATE,
    channels = 2,
    bgm = null,
    bgmGain = 0.34,
    duckTo = 0.42,
  } = opts;

  const total = segments.reduce((n, v) => n + v.duration, 0);
  const frames = Math.max(1, Math.ceil(total * sampleRate));

  const voice = new Float32Array(frames);
  const speaking = new Uint8Array(frames);
  let offset = 0;

  for (const seg of segments) {
    const start = Math.round(offset * sampleRate);
    if (seg.pcm) {
      const src = seg.pcm.data;
      const ratio = seg.pcm.sampleRate / sampleRate;
      const outLen = Math.min(Math.ceil(src.length / ratio), Math.max(0, frames - start));
      for (let i = 0; i < outLen; i++) {
        const s = Math.min(src.length - 1, Math.floor(i * ratio));
        voice[start + i] = src[s];
      }
      // 说话区间前后各留 80ms，避免 BGM 提早抬起
      const pad = Math.round(0.08 * sampleRate);
      const from = Math.max(0, start - pad);
      const to = Math.min(frames, start + outLen + pad);
      for (let i = from; i < to; i++) speaking[i] = 1;
    }
    offset += seg.duration;
  }

  const music = new Float32Array(frames);
  if (bgm && bgm.data.length) {
    const src = bgm.data;
    const n = src.length;
    const step = bgm.sampleRate / sampleRate;
    const attack = 1 - Math.exp(-1 / (0.08 * sampleRate));
    const release = 1 - Math.exp(-1 / (0.35 * sampleRate));
    const fadeIn = Math.round(0.4 * sampleRate);
    const fadeOut = Math.round(1.2 * sampleRate);
    let env = 1;
    for (let i = 0; i < frames; i++) {
      const target = speaking[i] ? duckTo : 1;
      env += (target - env) * (target < env ? attack : release);
      let g = bgmGain * env;
      if (i < fadeIn) g *= i / fadeIn;
      if (i > frames - fadeOut) g *= Math.max(0, (frames - i) / fadeOut);
      music[i] = src[Math.floor(i * step) % n] * g;
    }
  }

  const out = [];
  for (let ch = 0; ch < channels; ch++) {
    const plane = new Float32Array(frames);
    for (let i = 0; i < frames; i++) {
      const s = voice[i] + music[i];
      plane[i] = s > 1 ? 1 : s < -1 ? -1 : s;
    }
    out.push(plane);
  }

  return { sampleRate, channels: out, frames, seconds: total };
}

/** 写 16bit PCM WAV。ffmpeg 收得下，体积也比 f32 小一半。 */
export async function writeWav(file, track) {
  const { sampleRate, channels, frames } = track;
  const chCount = channels.length;
  const bytesPerSample = 2;
  const dataBytes = frames * chCount * bytesPerSample;
  const buf = Buffer.alloc(44 + dataBytes);

  buf.write('RIFF', 0);
  buf.writeUInt32LE(36 + dataBytes, 4);
  buf.write('WAVE', 8);
  buf.write('fmt ', 12);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20); // PCM
  buf.writeUInt16LE(chCount, 22);
  buf.writeUInt32LE(sampleRate, 24);
  buf.writeUInt32LE(sampleRate * chCount * bytesPerSample, 28);
  buf.writeUInt16LE(chCount * bytesPerSample, 32);
  buf.writeUInt16LE(16, 34);
  buf.write('data', 36);
  buf.writeUInt32LE(dataBytes, 40);

  let p = 44;
  for (let i = 0; i < frames; i++) {
    for (let c = 0; c < chCount; c++) {
      const v = Math.max(-1, Math.min(1, channels[c][i]));
      buf.writeInt16LE(Math.round(v * 32767), p);
      p += 2;
    }
  }

  await writeFile(file, buf);
  return { file, bytes: buf.length };
}

/** BGM 文件读进来直接解码；没有就返回 null，没音乐也能出片。 */
export async function loadBgm(file) {
  if (!file) return null;
  try {
    await readFile(file, { length: 1 });
    return await decodeMono(file);
  } catch {
    return null;
  }
}
