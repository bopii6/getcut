// 批量出片：一个话题一行，串行渲染成 N 条，共用同一批截图和同一个主题。
//   node scripts/batch.mjs --topics topics.txt --theme cartoon --screens shots --out out/batch
// 话题行里如果写了 | 分隔，左边当文案、右边当文件名前缀（方便对号入座）。
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const arg = (n, d) => {
  const i = process.argv.indexOf(n);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : d;
};

const topicsFile = arg('--topics', null);
const theme = arg('--theme', 'cartoon');
const screens = arg('--screens', null);
const outDir = path.resolve(arg('--out', path.join('out', 'batch')));
if (!topicsFile) throw new Error('用法：node scripts/batch.mjs --topics topics.txt');

const raw = await readFile(topicsFile, 'utf8');
const lines = raw.split(/\r?\n/).map((s) => s.trim()).filter((s) => s && !s.startsWith('#'));
if (!lines.length) throw new Error('topics.txt 里没有内容');

await mkdir(outDir, { recursive: true });
await mkdir(path.join(ROOT, 'data', 'batch'), { recursive: true });

console.log(`准备渲染 ${lines.length} 条，主题 ${theme}${screens ? `，截图目录 ${screens}` : ''}`);

let ok = 0;
const failed = [];
for (let i = 0; i < lines.length; i += 1) {
  const [text, label] = lines[i].split('|').map((s) => s.trim());
  const name = (label || String(i + 1).padStart(2, '0')).replace(/[\\/:*?"<>|]/g, '_');
  const scriptPath = path.join(ROOT, 'data', 'batch', `${name}.txt`);
  await writeFile(scriptPath, text, 'utf8');
  const output = path.join(outDir, `${name}.mp4`);
  const args = [path.join(ROOT, 'scripts', 'render.mjs'), '--script', scriptPath, '--theme', theme, '-o', output];
  if (screens) args.push('--screens', screens);

  console.log(`\n[${i + 1}/${lines.length}] ${name}`);
  const started = Date.now();
  const code = await new Promise((resolve) => {
    const child = spawn(process.execPath, args, { cwd: ROOT, stdio: ['ignore', 'inherit', 'inherit'] });
    child.on('close', resolve);
  });
  if (code === 0) {
    ok += 1;
    console.log(`  ✓ ${name}（${Math.round((Date.now() - started) / 1000)}s）`);
  } else {
    failed.push(name);
    console.log(`  ✗ ${name} 失败（退出码 ${code}）`);
  }
}

console.log(`\n完成 ${ok}/${lines.length} 条 → ${outDir}`);
if (failed.length) console.log('失败：', failed.join(', '));
