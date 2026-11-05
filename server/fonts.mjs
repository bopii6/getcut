// 字体：开发机（Windows/macOS）直接吃系统字体；Linux 服务器上必须自带，
// 否则中文会整片变成豆腐块，而且是静默失败——出片看起来正常，只是字全是方框。
//
// 绘制代码里的字体栈（见 draw.ts / styles.ts）：
//   HEAVY  = "Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif
//   LIGHT  = "Microsoft YaHei Light","PingFang SC","Microsoft YaHei",sans-serif
// 只要栈里任意一个能命中，就不会出问题。
import { GlobalFonts } from '@napi-rs/canvas';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** 打包自带的字体；Linux 上注册成绘制代码认的名字。 */
const BUNDLED = [
  { file: 'public/fonts/SourceHanSansCN-Heavy.otf', aliases: ['Microsoft YaHei', 'PingFang SC'] },
  { file: 'public/fonts/NotoSansSC-Light.otf', aliases: ['Microsoft YaHei Light'] },
];

/** 绘制代码的字体栈需要至少命中一个，否则一定出方框。 */
const REQUIRED = ['Microsoft YaHei', 'PingFang SC'];

export function ensureFonts({ verbose = true } = {}) {
  const before = new Set(GlobalFonts.families.map((f) => f.family));
  const registered = [];

  const missing = REQUIRED.filter((name) => !before.has(name));
  if (missing.length === REQUIRED.length) {
    for (const { file, aliases } of BUNDLED) {
      const full = path.join(ROOT, file);
      for (const alias of aliases) {
        if (before.has(alias)) continue;
        const ok = GlobalFonts.registerFromPath(full, alias);
        if (ok) registered.push(`${alias} ← ${path.basename(file)}`);
      }
    }
  }

  const after = new Set(GlobalFonts.families.map((f) => f.family));
  const resolved = REQUIRED.find((name) => after.has(name));

  if (!resolved) {
    throw new Error(
      `没有任何可用的中文字体（试过 ${REQUIRED.join(' / ')}）。` +
        `Linux 上请把 public/fonts 里的 otf 一起打进镜像，或 apt-get install fonts-noto-cjk。`,
    );
  }

  if (verbose) {
    const how = registered.length ? `自带字体注册（${registered.join('；')}）` : '系统字体';
    console.log(`[fonts] 中文使用「${resolved}」· ${how} · 共 ${after.size} 个族`);
  }

  return { resolved, registered, total: after.size };
}
