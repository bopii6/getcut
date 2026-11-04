// 渲染：一句一个镜头（图片或视频），拼成无声画面轨 → 拼配音 → 叠标题与字幕 → 出 MP4。
// 全部在本机跑：ffmpeg 直接吃素材，不需要浏览器、不需要排队。
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { run, probeDuration } from './ffmpeg.mjs';
import { wrapText } from './storyboard.mjs';

export const FPS = 30;
export const W = 1080;
export const H = 1920;

const FONT_TITLE = 'public/fonts/SourceHanSansCN-Heavy.otf';
const FONT_SUB = 'public/fonts/SourceHanSansCN-Heavy.otf';

const rel = (from, to) => path.relative(from, to).split(path.sep).join('/');

/** filter 里的路径：盘符冒号会被当成选项分隔符，必须转义（C:/x → C\:/x）。 */
const escPath = (from, to) => rel(from, to).replace(/:/g, '\\:');

async function beatClip(beat, duration, outPath, workDir) {
  const common = ['-y', '-hide_banner', '-loglevel', 'error', '-t', duration.toFixed(3)];
  if (!beat.asset) {
    // 没有素材就上一块深色底，保证时间轴不断
    await run('ffmpeg', [
      ...common, '-f', 'lavfi', '-i', `color=c=0x14120f:s=${W}x${H}:r=${FPS}`,
      '-vf', `format=yuv420p`, '-an', '-c:v', 'libx264', '-preset', 'veryfast', outPath,
    ]);
    return;
  }
  const vf = `scale=${W}:${H}:force_original_aspect_ratio=increase,crop=${W}:${H},setsar=1,format=yuv420p`;
  if (beat.asset.kind === 'video') {
    await run('ffmpeg', [
      ...common, '-stream_loop', '-1', '-i', beat.asset.absPath,
      '-vf', vf, '-r', String(FPS), '-an', '-c:v', 'libx264', '-preset', 'veryfast', outPath,
    ]);
  } else {
    await run('ffmpeg', [
      ...common, '-loop', '1', '-i', beat.asset.absPath,
      '-vf', vf, '-r', String(FPS), '-an', '-c:v', 'libx264', '-preset', 'veryfast', outPath,
    ]);
  }
  void workDir;
}

function subtitleFilter(file, start, end, { fontSize = 54, y = 'h-360' } = {}) {
  return [
    `drawtext=textfile=${file}`,
    `fontfile=${FONT_SUB}`,
    `fontsize=${fontSize}`,
    'fontcolor=white',
    'line_spacing=14',
    'borderw=4',
    'bordercolor=black@0.9',
    'box=1',
    'boxcolor=black@0.35',
    'boxborderw=16',
    `x=(w-text_w)/2`,
    `y=${y}`,
    `enable='between(t,${start.toFixed(3)},${end.toFixed(3)})'`,
  ].join(':');
}

/**
 * @returns {Promise<{output:string, duration:number}>}
 */
export async function renderVideo(bundle, beats, workDir, projectRoot, { onProgress } = {}) {
  const tmp = path.join(workDir, 'seg');
  await mkdir(tmp, { recursive: true });

  const clips = [];
  const timings = [];
  let t = 0;
  for (let i = 0; i < beats.length; i++) {
    const beat = beats[i];
    const duration = Math.max(1.2, beat.duration);
    const clip = path.join(tmp, `seg-${String(i).padStart(3, '0')}.mp4`);
    await beatClip(beat, duration, clip, tmp);
    const actual = await probeDuration(clip);
    clips.push(clip);
    timings.push({ start: t, end: t + actual, duration: actual });
    t += actual;
    onProgress?.({ stage: 'clip', done: i + 1, total: beats.length, percent: Math.round(((i + 1) / beats.length) * 70) });
  }

  // 画面轨：同编码参数，直接拼接
  const vlist = path.join(tmp, 'video.txt');
  await writeFile(vlist, clips.map((c) => `file '${rel(tmp, c)}'`).join('\n'), 'utf8');
  const videoOnly = path.join(tmp, 'video.mp4');
  await run('ffmpeg', ['-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
    '-i', vlist, '-c', 'copy', videoOnly]);

  // 配音轨
  const alist = path.join(tmp, 'audio.txt');
  await writeFile(alist, beats.map((b) => `file '${rel(tmp, b.audio)}'`).join('\n'), 'utf8');
  const audioOnly = path.join(tmp, 'audio.m4a');
  await run('ffmpeg', ['-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
    '-i', alist, '-c:a', 'aac', '-b:a', '192k', audioOnly]);

  // 标题 + 字幕：全部用 textfile，避免中文和冒号在 filter 里转义出错
  const titleText = wrapText(bundle.hookTitle || bundle.title, 12);
  const titleFile = path.join(tmp, 'title.txt');
  await writeFile(titleFile, titleText, 'utf8');

  const filters = [
    `drawbox=x=0:y=0:w=iw:h=${H}:color=black@0.45:t=fill:enable='between(t,0,3.2)'`,
    [`drawtext=textfile=${escPath(projectRoot, titleFile)}`,
      `fontfile=${FONT_TITLE}`, 'fontsize=82', 'fontcolor=white', 'line_spacing=20',
      'x=(w-text_w)/2', 'y=180', `enable='between(t,0,3.2)'`].join(':'),
  ];
  beats.forEach((beat, i) => {
    const file = path.join(tmp, `sub-${String(i).padStart(3, '0')}.txt`);
    const tm = timings[i];
    filters.push(subtitleFilter(escPath(projectRoot, file), tm.start + 0.15, tm.end - 0.05));
  });
  // 先落盘字幕文件（上面只算了路径）
  for (let i = 0; i < beats.length; i++) {
    await writeFile(path.join(tmp, `sub-${String(i).padStart(3, '0')}.txt`), wrapText(beats[i].text), 'utf8');
  }

  const output = path.join(workDir, 'output.mp4');
  onProgress?.({ stage: 'mux', percent: 85 });
  await run('ffmpeg', [
    '-y', '-hide_banner', '-loglevel', 'error',
    '-i', videoOnly, '-i', audioOnly,
    '-filter_complex', `[0:v]${filters.join(',')}[v]`,
    '-map', '[v]', '-map', '1:a',
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
    '-shortest', output,
  ], { cwd: projectRoot });

  const duration = await probeDuration(output);
  onProgress?.({ stage: 'done', percent: 100 });
  return { output, duration };
}
