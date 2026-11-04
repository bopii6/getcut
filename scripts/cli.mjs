// 命令行入口：给一个素材包目录或 zip，本机直接出一条 mp4。
//   node scripts/cli.mjs <素材包目录|zip> -o 成片.mp4
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import AdmZip from 'adm-zip';
import { loadBundle } from '../lib/bundle.mjs';
import { buildBeats } from '../lib/storyboard.mjs';
import { synthBeats } from '../lib/tts.mjs';
import { renderVideo } from '../lib/render.mjs';
import { probeDuration } from '../lib/ffmpeg.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const input = process.argv[2];
const output = arg('-o', 'output.mp4');
const voice = arg('--voice', undefined);

if (!input || input.startsWith('-')) {
  console.error('用法：node scripts/cli.mjs <素材包目录|zip> -o 成片.mp4 [--voice zh-CN-YunxiNeural]');
  process.exit(1);
}

// 工作目录放在项目里的 data/ 下：filter 里用相对路径，不带盘符冒号，中文/空格也不会炸
const work = path.join(ROOT, 'data', 'jobs', `cli-${Date.now()}`);
let bundleDir = path.resolve(input);
try {
  if (!existsSync(bundleDir)) throw new Error(`找不到素材包：${bundleDir}`);
  if (!(await import('node:fs/promises')).stat(bundleDir).then((s) => s.isDirectory())) {
    const zipDir = path.join(work, 'bundle');
    await mkdir(zipDir, { recursive: true });
    new AdmZip(bundleDir).extractAllTo(zipDir, true);
    bundleDir = zipDir;
  }

  const bundle = await loadBundle(bundleDir);
  console.log(`素材包：${bundle.title}｜${bundle.assets.length} 个素材`);

  const beats = buildBeats(bundle);
  console.log(`分镜：${beats.length} 句`);

  const voiced = await synthBeats(beats, work, { voice });
  for (const b of voiced) b.duration = await probeDuration(b.audio);
  const total = voiced.reduce((n, b) => n + b.duration, 0);
  console.log(`配音完成：约 ${total.toFixed(1)} 秒`);

  const { output: mp4, duration } = await renderVideo(bundle, voiced, work, ROOT, {
    onProgress: (p) => process.stdout.write(`\r${p.stage} ${p.percent ?? ''}%   `),
  });
  process.stdout.write('\n');

  const target = path.resolve(output);
  await mkdir(path.dirname(target), { recursive: true });
  await import('node:fs/promises').then(({ copyFile }) => copyFile(mp4, target));
  console.log(`完成：${target}（${duration.toFixed(1)} 秒）`);
} catch (e) {
  console.error(`\n失败：${e.message}`);
  process.exitCode = 1;
} finally {
  await rm(work, { recursive: true, force: true }).catch(() => {});
}
