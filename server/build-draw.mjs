// 把 app/src/lib 里那套「纯 Canvas 2D」绘制代码打包成 Node 能直接 import 的 ESM。
// 为什么不用 Node 原生跑 TS：那批文件用的都是无扩展名 import（./types、./theme），
// Node ESM 解析不了；而且生产机上不该带 esbuild 之外的构建依赖。
import { build } from 'esbuild';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT_DIR = path.join(ROOT, 'server', '.build');

await mkdir(OUT_DIR, { recursive: true });

const result = await build({
  entryPoints: [path.join(ROOT, 'app/src/lib/draw.ts')],
  outfile: path.join(OUT_DIR, 'draw.mjs'),
  bundle: true,
  format: 'esm',
  platform: 'node',
  target: 'node20',
  // 类型文件在打包时被剥掉，运行时一点痕迹都不留
  logLevel: 'info',
  metafile: true,
});

const bytes = Object.values(result.metafile.outputs)[0]?.bytes ?? 0;
console.log(`✓ 绘制层已打包：server/.build/draw.mjs（${(bytes / 1024).toFixed(1)} KB）`);
