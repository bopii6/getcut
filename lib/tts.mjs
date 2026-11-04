// 配音：本机调 edge-tts（Python 包），一句一条 mp3，顺带拿到逐字时间轴。
// 不依赖任何自建服务；edge-tts 本身走微软的公开接口，断网时这一句会明确失败。
import { spawn } from 'node:child_process';
import path from 'node:path';

export const DEFAULT_VOICE = 'zh-CN-YunxiNeural';

function edgeTts(text, voice, mediaPath, subtitlePath, rate = '+10%') {
  return new Promise((resolve, reject) => {
    const args = [
      '-m', 'edge_tts',
      '--text', text,
      '--voice', voice,
      '--rate', rate,
      '--write-media', mediaPath,
      '--write-subtitles', subtitlePath,
      '--no-progress',
    ];
    const child = spawn('python', args, { windowsHide: true });
    let err = '';
    child.stderr.on('data', (d) => { err += d; });
    child.on('error', (e) => reject(new Error(`调不起 python/edge-tts：${e.message}`)));
    child.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`配音失败（${voice}）：${err.trim().slice(-500) || `退出码 ${code}`}`));
    });
  });
}

/**
 * 逐句配音。返回 [{ text, audio, duration }]，duration 由调用方用 ffprobe 补。
 */
export async function synthBeats(beats, workDir, { voice = DEFAULT_VOICE } = {}) {
  const out = [];
  for (let i = 0; i < beats.length; i++) {
    const beat = beats[i];
    const audio = path.join(workDir, `tts-${String(i).padStart(3, '0')}.mp3`);
    const subs = path.join(workDir, `tts-${String(i).padStart(3, '0')}.vtt`);
    await edgeTts(beat.text, voice, audio, subs);
    out.push({ ...beat, audio, subtitle: subs });
  }
  return out;
}
