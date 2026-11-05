// 单帧预览：把每种卡片、每套风格各渲一张 PNG，用来跟 Web 端逐像素比对版面。
// 这一步不通，后面渲 1800 帧全白费。
import { createCanvas } from '@napi-rs/canvas';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ensureFonts } from './fonts.mjs';
import { drawFrame, W, H, FPS } from './.build/draw.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'server', '.preview');

ensureFonts();

/** 每种卡片一份真实形状的样本（文案借 demo 里的加盟题材，够长够典型）。 */
const BEATS = {
  intro: { card: 'intro', text: '', title: '开一家餐饮店，先算清这三个数', duration: 2 },
  chapter: { card: 'chapter', text: '', topic: '选址', value: '1', duration: 1.4 },
  hook: { card: 'hook', text: '别急着交定金', title: '别急着交定金', duration: 3 },
  plain: { card: 'plain', text: '三十八万加盟费，两年才能回本', duration: 3 },
  stat: { card: 'stat', text: '每天要卖一百二十单', value: '120', unit: '单', label: '日均保本单量', duration: 3 },
  list: {
    card: 'list',
    text: '选址、算账、看合同',
    items: ['选址决定一半生死', '三十八万只是开始', '合同里藏着三个坑'],
    duration: 3,
  },
  compare: {
    card: 'compare',
    text: '直营和加盟差在哪',
    left: '总部收完加盟费就不管了，物料还必须从总部进',
    right: '有人带你跑通前三个月，但抽成高',
    duration: 3,
  },
  quote: { card: 'quote', text: '', title: '真正赚钱的从来不是最火的那个', duration: 3 },
  cta: { card: 'cta', text: '', cta: '想开店的，私信我算一笔账', duration: 3 },
};

const THEMES = ['poster', 'magazine', 'dashboard'];
const T = 0.9; // 入场动画已经走完、又还没到片尾的稳定态

await mkdir(OUT, { recursive: true });

const canvas = createCanvas(W, H);
const ctx = canvas.getContext('2d');

const made = [];
let index = 0;
for (const [name, beat] of Object.entries(BEATS)) {
  for (const theme of THEMES) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, W, H);
    drawFrame(ctx, beat, T, theme, index, Object.keys(BEATS).length, 'auto');
    const file = path.join(OUT, `${theme}-${name}.png`);
    await writeFile(file, await canvas.encode('png'));
    made.push(file);
  }
  index += 1;
}

// 再渲一张完整尺寸的做像素体检：确认不是空白、不是纯色
const probe = createCanvas(W, H);
const pctx = probe.getContext('2d');
drawFrame(pctx, BEATS.stat, T, 'poster', 4, 9, 'auto');
const pixels = pctx.getImageData(0, 0, W, H).data;
const colors = new Set();
for (let i = 0; i < pixels.length; i += 4 * 997) {
  colors.add(`${pixels[i]},${pixels[i + 1]},${pixels[i + 2]}`);
}

console.log(`\n✓ 出了 ${made.length} 张：${path.relative(ROOT, OUT)}`);
console.log(`✓ 抽样 ${colors.size} 种颜色（纯色或空白会只有 1~2 种）· ${W}×${H} @ ${FPS}fps`);
