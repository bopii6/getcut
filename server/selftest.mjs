// 版面自检：不靠眼睛，靠像素统计。
// 要抓的是三类真实故障：整帧空白、中日韩字符变豆腐块、所有卡片画成一模一样。
import { createCanvas } from '@napi-rs/canvas';

import { ensureFonts } from './fonts.mjs';
import { drawFrame, W, H } from './.build/draw.mjs';

ensureFonts({ verbose: false });

const SAMPLE = {
  intro: { card: 'intro', text: '', title: '开一家餐饮店，先算清这三个数', duration: 2 },
  chapter: { card: 'chapter', text: '', topic: '选址', value: '1', duration: 1.4 },
  hook: { card: 'hook', text: '别急着交定金', title: '别急着交定金', duration: 3 },
  plain: { card: 'plain', text: '三十八万加盟费，两年才能回本', duration: 3 },
  stat: { card: 'stat', text: '每天要卖一百二十单', value: '120', unit: '单', label: '日均保本单量', duration: 3 },
  list: { card: 'list', text: '选址、算账、看合同', items: ['选址决定一半生死', '三十八万只是开始', '合同里藏着三个坑'], duration: 3 },
  compare: { card: 'compare', text: '直营和加盟差在哪', left: '总部收完加盟费就不管了，物料还必须从总部进', right: '有人带你跑通前三个月，但抽成高', duration: 3 },
  quote: { card: 'quote', text: '', title: '真正赚钱的从来不是最火的那个', duration: 3 },
  cta: { card: 'cta', text: '', cta: '想开店的，私信我算一笔账', duration: 3 },
};

const ctx = createCanvas(W, H).getContext('2d');

function snap(beat, theme = 'poster', t = 0.9) {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, W, H);
  drawFrame(ctx, beat, t, theme, 4, 9, 'auto');
  return ctx.getImageData(0, 0, W, H).data;
}

/** 抽稀取样：1080×1920 全量遍历太慢，隔 13 个像素足够判断。 */
function signature(data) {
  const set = new Set();
  for (let i = 0; i < data.length; i += 4 * 13) {
    set.add((data[i] >> 3) * 1024 + (data[i + 1] >> 3) * 32 + (data[i + 2] >> 3));
  }
  return set;
}

function diffRatio(a, b) {
  let diff = 0;
  let total = 0;
  for (let i = 0; i < a.length; i += 4 * 13) {
    total += 1;
    if (Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]) > 24) diff += 1;
  }
  return diff / total;
}

const fails = [];
const seen = new Map();

console.log('卡片类型          独立色数   与 poster/hook 差异');
for (const [name, beat] of Object.entries(SAMPLE)) {
  const data = snap(beat);
  const sig = signature(data);
  const base = seen.get('hook') ?? null;
  const ratio = base ? diffRatio(data, base) : null;

  // 1. 空白帧：纯色/渐变背景撑不起几十种颜色
  if (sig.size < 20) fails.push(`${name}: 只有 ${sig.size} 种颜色，疑似空白或纯背景`);

  // 2. 重复帧：不同卡片画出来几乎一样，说明用错了分支
  if (name !== 'hook' && ratio !== null && ratio < 0.004) {
    fails.push(`${name}: 与 hook 只差 ${(ratio * 100).toFixed(2)}%，疑似画成了同一张`);
  }

  seen.set(name, data);
  console.log(
    `${name.padEnd(12)}   ${String(sig.size).padStart(6)}    ${ratio === null ? '—' : (ratio * 100).toFixed(1) + '%'}`,
  );
}

// 3. 豆腐块：缺失字体时汉字会退化成等宽的 .notdef 方框，墨量异常低
const probe = createCanvas(200, 120);
const pctx = probe.getContext('2d');
function inkRatio(ch, size = 80) {
  pctx.setTransform(1, 0, 0, 1, 0, 0);
  pctx.clearRect(0, 0, 200, 120);
  pctx.font = `700 ${size}px "Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif`;
  pctx.fillStyle = '#000';
  pctx.fillText(ch, 20, 100);
  const d = pctx.getImageData(0, 0, 200, 120).data;
  let ink = 0;
  for (let i = 3; i < d.length; i += 4) if (d[i] > 32) ink += 1;
  return ink / (200 * 120);
}
const cjk = inkRatio('国');
const ascii = inkRatio('M');
console.log(`\n墨量比  汉字『国』${(cjk * 100).toFixed(1)}%  字母『M』${(ascii * 100).toFixed(1)}%`);
if (cjk < 0.02) fails.push(`汉字墨量只有 ${(cjk * 100).toFixed(1)}%，中文很可能没渲染出来`);

console.log(`\n${fails.length ? '✗ ' + fails.length + ' 项不通过：\n  - ' + fails.join('\n  - ') : '✓ 全部通过'}`);
process.exitCode = fails.length ? 1 : 0;
