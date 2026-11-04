// 配音：一条一条跑 edge-tts，拿到 mp3 和真实时长。时间轴以它为准。
import { spawn } from 'node:child_process';
import path from 'node:path';
import { probeDuration, run } from '../lib/ffmpeg.mjs';

export const DEFAULT_VOICE = 'zh-CN-YunxiNeural';

function edgeTtsOnce(text, outPath, { voice, rate }) {
  return new Promise((resolve, reject) => {
    const child = spawn('python', [
      '-m', 'edge_tts', '--text', text, '--voice', voice, '--rate', rate,
      '--write-media', outPath, '--no-progress',
    ], { windowsHide: true });
    let err = '';
    child.stderr.on('data', (d) => { err += d; });
    child.on('error', (e) => reject(new Error(`调不起 python/edge-tts：${e.message}`)));
    child.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`配音失败：${err.trim().slice(-400)}`))));
  });
}

/** edge-tts 是公网服务，偶发 403/超时很正常：重试三次，别让一条句子毁掉整条片子。 */
async function edgeTts(text, outPath, opts) {
  let last;
  for (let i = 0; i < 3; i++) {
    try {
      await edgeTtsOnce(text, outPath, opts);
      return;
    } catch (e) {
      last = e;
      await new Promise((r) => setTimeout(r, 800 * (i + 1)));
    }
  }
  throw last;
}

export async function voiceBeats(beats, outDir, { voice = DEFAULT_VOICE, rate = '+16%' } = {}) {
  const out = [];
  for (let i = 0; i < beats.length; i++) {
    const raw = path.join(outDir, `raw-${String(i).padStart(3, '0')}.mp3`);
    const file = path.join(outDir, `audio-${String(i).padStart(3, '0')}.mp3`);
    await edgeTts(beats[i].text, raw, { voice, rate });
    // 首尾静音剪掉：一句一条音轨，尾巴那一截会让整条片子的节奏越拖越慢
    await run('ffmpeg', [
      '-y', '-hide_banner', '-loglevel', 'error', '-i', raw,
      '-af', 'silenceremove=start_periods=1:start_duration=0.05:start_threshold=-45dB:'
        + 'stop_periods=-1:stop_duration=0.15:stop_threshold=-45dB',
      '-c:a', 'libmp3lame', '-q:a', '4', file,
    ]);
    const duration = await probeDuration(file);
    out.push({ ...beats[i], audio: file, duration: Math.max(1.4, duration + 0.18) });
  }
  return out;
}
