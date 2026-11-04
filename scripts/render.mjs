// 一句话的入口：给一段文案，本机直接出片。
//   node scripts/render.mjs --script 文案.txt --theme magazine -o out.mp4
//   node scripts/render.mjs --text "文案内容" --theme poster
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { planScript } from './plan.mjs';
import { voiceBeats } from './voice.mjs';
import { fetchBroll } from './broll.mjs';
import { envOf, applyEnv } from '../lib/env.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const COMPOSITION = { magazine: 'Magazine', poster: 'Poster', dashboard: 'Dashboard' };

// 钥匙只从本项目的 .env（或环境变量）来，不依赖其它目录
applyEnv(['DEEPSEEK_API_KEY', 'PEXELS_API_KEY']);

function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

function runStreaming(cmd, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { cwd, stdio: ['ignore', 'inherit', 'inherit'] });
    child.on('error', reject);
    child.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} 退出码 ${code}`))));
  });
}

const theme = arg('--theme', 'magazine');
const composition = COMPOSITION[theme];
if (!composition) throw new Error(`不认识的风格：${theme}（可选 ${Object.keys(COMPOSITION).join(' / ')}）`);

const scriptFile = arg('--script', null);
const inlineText = arg('--text', null);
let text = inlineText;
if (!text && scriptFile) text = await readFile(scriptFile, 'utf8');
if (!text) throw new Error('用法：--script 文案.txt 或 --text "文案内容"');

const id = `${theme}-${Date.now()}`;
const audioDir = path.join(ROOT, 'public', 'audio', id);
await mkdir(audioDir, { recursive: true });

console.log(`[1/4] 拆稿（${theme}）…`);
const plan = await planScript(text, { apiKey: envOf('DEEPSEEK_API_KEY') });
console.log(`      切出 ${plan.beats.length} 个镜头：`, plan.beats.map((b) => b.card).join(' / '));

console.log('[2/4] 配音…');
const voiced = await voiceBeats(plan.beats, audioDir);
const total = voiced.reduce((n, b) => n + b.duration, 0);
console.log(`      ${voiced.length} 句，约 ${total.toFixed(1)} 秒`);

console.log('[3/5] 抓实拍空镜（Pexels）…');
const brollDir = path.join(ROOT, 'public', 'broll', id);
const brolls = await fetchBroll(voiced, brollDir, {
  onProgress: (p) => console.log(`      ${p.index + 1} · ${p.query}`),
});
const gotBroll = brolls.filter((b) => b.broll).length;
console.log(`      ${gotBroll}/${voiced.length} 个镜头配到了实拍`);

const beats = voiced.map((b, i) => ({
  text: b.text, card: b.card, topic: b.topic, title: b.title, value: b.value, unit: b.unit,
  label: b.label, items: b.items, left: b.left, right: b.right, cta: b.cta,
  broll: brolls[i]?.broll || '',
  audio: path.posix.join('audio', id, path.basename(b.audio)),
  duration: Number(b.duration.toFixed(2)),
}));

// 片头 + 章节页：把"第几部分"做成一张整屏，短视频靠它分段
const title = String(text).trim().slice(0, 14);
const timeline = [{ card: 'intro', title, text: '', audio: '', duration: 2.2 }];
let lastTopic = null;
let chapter = 0;
for (const b of beats) {
  if (b.topic && b.topic !== lastTopic) {
    chapter += 1;
    timeline.push({ card: 'chapter', title: b.topic, value: String(chapter), text: '', audio: '', duration: 1.4 });
    lastTopic = b.topic;
  }
  timeline.push(b);
}

const propsPath = path.join(ROOT, 'data', `props-${id}.json`);
await mkdir(path.dirname(propsPath), { recursive: true });
await writeFile(propsPath, JSON.stringify({
  theme, title, fps: 30, beats: timeline,
}, null, 2), 'utf8');

const output = path.resolve(arg('-o', path.join('data', `${id}.mp4`)));
console.log(`[4/5] 渲染 ${composition} → ${output}`);
// 直接调 @remotion/cli 的入口，绕开 npx（Windows 上要 shell，会多一行弃用警告）
const cli = path.join(ROOT, 'node_modules', '@remotion', 'cli', 'remotion-cli.js');
await runStreaming(process.execPath, [cli, 'render', 'src/index.ts', composition,
  output, `--props=${propsPath}`, '--codec=h264', '--log=info'], ROOT);
console.log('[5/5] 完成：', output);


