// 服务端出片主链路：配音 → 铺时间轴 → 逐帧画 → raw 喂给 ffmpeg → MP4。
//
// 和 Web 端 app/src/lib/render.ts 一一对应，唯一区别是编码器：
//   浏览器用 WebCodecs（VideoEncoder/AudioEncoder），这里用 ffmpeg 子进程。
// 帧不落盘成 PNG——1800 张 1080×1920 的 PNG 要 3GB 且编码慢，
// 直接把 canvas 的 RGBA 缓冲写进 ffmpeg 的 stdin，省掉一次磁盘往返。
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { createCanvas } from '@napi-rs/canvas';

import { ensureFonts } from './fonts.mjs';
import { drawFrame, W, H, FPS } from './.build/draw.mjs';
import { buildTimeline, decodeMono, probeDuration, writeWav, loadBgm, OUT_RATE } from './audio.mjs';
import { synthBeats } from '../lib/tts.mjs';

/** 每套风格配一首 BGM，和 app/src/lib/render.ts 里的 BGM 表保持一致。 */
const BGM = {
  poster: 'public/music/breakbeat.mp3',
  magazine: 'public/music/cinematic.mp3',
  dashboard: 'public/music/chill.mp3',
};

/** 片头 + 章节页插进时间轴，和 Web 端 withChapterCards 同一套规则。 */
export function withChapterCards(beats, title) {
  const out = [{ card: 'intro', text: '', title, duration: 2 }];
  let lastTopic;
  let chapter = 0;
  for (const b of beats) {
    if (b.topic && b.topic !== lastTopic) {
      chapter += 1;
      out.push({ card: 'chapter', text: '', topic: b.topic, value: String(chapter), duration: 1.4 });
      lastTopic = b.topic;
    }
    out.push(b);
  }
  return out;
}

/** 同一种版式绝不连着出现两屏——Web 端靠这个避免"每屏一个样"。 */
function makeLayoutPicker(mode) {
  let last = 'content';
  return (b) => {
    if (mode !== 'auto') return mode;
    const base =
      b.card === 'stat' && b.value ? 'data' : b.card === 'hook' || b.card === 'quote' ? 'big' : 'content';
    if (base === last) return last === 'big' ? 'content' : 'big';
    last = base;
    return base;
  };
}

/** 往子进程 stdin 写数据，处理背压——不 await drain 会把内存顶爆。 */
function writeChunk(stream, buf) {
  return new Promise((resolve, reject) => {
    const ok = stream.write(buf, (err) => (err ? reject(err) : undefined));
    if (ok) resolve();
    else stream.once('drain', resolve);
  });
}

function runFfmpeg(args, { onStderr } = {}) {
  const child = spawn('ffmpeg', args, { windowsHide: true, stdio: ['pipe', 'ignore', 'pipe'] });
  let err = '';
  child.stderr.on('data', (d) => {
    err += d.toString();
    if (err.length > 8000) err = err.slice(-4000);
    onStderr?.(d.toString());
  });
  const done = new Promise((resolve, reject) => {
    child.on('error', (e) => reject(new Error(`调不起 ffmpeg：${e.message}`)));
    child.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`ffmpeg 退出码 ${code}：${err.trim().slice(-600) || '无输出'}`));
    });
  });
  return { child, done };
}

/**
 * 出一条片子。
 * @param {object} opts
 * @param {object[]} opts.beats     拆稿结果（PlanBeat[]）
 * @param {string}   opts.theme     风格名
 * @param {string}   opts.title     片头标题
 * @param {string}   opts.outFile   输出 mp4 路径
 * @param {string}   [opts.voice]   发音人
 * @param {string}   [opts.bgm]     BGM 路径，'' 表示不要
 * @param {string}   [opts.layoutMode] 'auto' | 'big' | 'data' | 'content'
 * @param {(p:{stage:string,percent:number})=>void} [opts.onProgress]
 */
export async function renderVideo(opts) {
  const {
    beats,
    theme = 'poster',
    title = '',
    outFile,
    voice = 'zh-CN-YunxiNeural',
    bgm: bgmFile = BGM[theme] ?? BGM.poster,
    layoutMode = 'auto',
    onProgress = () => {},
  } = opts;

  if (!Array.isArray(beats) || beats.length === 0) throw new Error('拆稿结果为空，没有可以画的内容');
  if (!outFile) throw new Error('没有指定输出路径');

  ensureFonts({ verbose: false });

  const workDir = await mkdtemp(path.join(os.tmpdir(), 'getcut-'));
  const started = Date.now();

  try {
    // ── 1. 配音：逐句 mp3
    const spoken = beats.filter((b) => b.text && !['intro', 'chapter'].includes(b.card));
    if (spoken.length === 0) throw new Error('没有一个镜头有文案，出不了片');

    onProgress({ stage: '配音', percent: 4 });
    await synthBeats(
      spoken.map((b, i) => ({ ...b, _idx: i })),
      workDir,
      { voice },
    );

    // ── 2. 读时长、解 PCM
    const voiced = [];
    for (let i = 0; i < spoken.length; i += 1) {
      const file = path.join(workDir, `tts-${String(i).padStart(3, '0')}.mp3`);
      const duration = await probeDuration(file);
      const pcm = await decodeMono(file);
      voiced.push({ text: spoken[i].text, file, duration, pcm });
      onProgress({ stage: `配音 ${i + 1}/${spoken.length}`, percent: 4 + Math.round(((i + 1) / spoken.length) * 26) });
    }

    // ── 3. 组时间轴
    const voicedBeats = beats.map((b) => {
      if (b.card === 'intro' || b.card === 'chapter') {
        return { ...b, duration: b.card === 'intro' ? 2 : 1.4 };
      }
      const v = voiced.find((x) => x.text === b.text);
      // 最短 1.4 秒：配音太短的句子也要留出画面反应的余地
      return { ...b, duration: v ? Math.max(1.4, v.duration) : 2, pcm: v?.pcm ?? null };
    });
    const timeline = withChapterCards(voicedBeats, title);

    // ── 4. 音轨
    onProgress({ stage: '合成音轨', percent: 32 });
    const bgm = bgmFile ? await loadBgm(path.resolve(bgmFile)) : null;
    const track = buildTimeline(
      timeline.map((b) => ({ duration: b.duration, pcm: b.pcm ?? null })),
      { sampleRate: OUT_RATE, channels: 2, bgm },
    );
    const wavFile = path.join(workDir, 'audio.wav');
    await writeWav(wavFile, track);

    const videoSec = timeline.reduce((n, b) => n + b.duration, 0);
    const totalFrames = Math.max(1, Math.round(videoSec * FPS));

    // ── 5. 逐帧画 → ffmpeg
    onProgress({ stage: '渲染画面', percent: 36 });
    await mkdir(path.dirname(path.resolve(outFile)), { recursive: true });

    const { child, done } = runFfmpeg([
      '-y',
      '-v', 'error',
      '-f', 'rawvideo',
      '-pix_fmt', 'rgba',
      '-s', `${W}x${H}`,
      '-r', String(FPS),
      '-i', '-',
      '-i', wavFile,
      '-c:v', 'libx264',
      '-preset', 'veryfast',
      '-crf', '20',
      '-pix_fmt', 'yuv420p',
      '-c:a', 'aac',
      '-b:a', '128k',
      '-ar', String(OUT_RATE),
      '-movflags', '+faststart',
      '-shortest',
      path.resolve(outFile),
    ]);

    const canvas = createCanvas(W, H);
    const ctx = canvas.getContext('2d');
    const layoutOf = makeLayoutPicker(layoutMode);

    let drawn = 0;
    for (let bi = 0; bi < timeline.length; bi += 1) {
      const beat = timeline[bi];
      const frames = Math.max(1, Math.round(beat.duration * FPS));
      const layout = layoutOf(beat);
      for (let f = 0; f < frames; f += 1) {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        drawFrame(ctx, beat, f / FPS, theme, bi, timeline.length, layout);
        await writeChunk(child.stdin, canvas.data());
        drawn += 1;
      }
      onProgress({
        stage: `画帧 ${bi + 1}/${timeline.length}`,
        percent: 36 + Math.round(((bi + 1) / timeline.length) * 58),
      });
    }

    child.stdin.end();
    await done;

    if (drawn !== totalFrames) {
      throw new Error(`帧数对不上：计划 ${totalFrames}，实画 ${drawn}`);
    }

    onProgress({ stage: '完成', percent: 100 });
    return {
      outFile: path.resolve(outFile),
      seconds: Number(videoSec.toFixed(2)),
      frames: drawn,
      audioSeconds: Number(track.seconds.toFixed(2)),
      bgm: Boolean(bgm),
      // 60 秒的片在 2 核机器上大约 3 分钟，这个数字直接决定并发和定价
      elapsedSec: Number(((Date.now() - started) / 1000).toFixed(1)),
    };
  } finally {
    await rm(workDir, { recursive: true, force: true }).catch(() => {});
  }
}
