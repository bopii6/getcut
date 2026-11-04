// 新风格：新闻播报（newsroom）与财报数据（ledger）
// 每个风格自己画顶部/中部/字幕，不走通用卡片，才能真正"换骨架"。
import type { Beat, ThemeName } from './types';

type Ctx = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;
export const W = 1080;
export const H = 1920;
const HEAVY = '"Microsoft YaHei","PingFang SC",sans-serif';
const LIGHT = '"Microsoft YaHei Light","PingFang SC","Microsoft YaHei",sans-serif';

const ease = (x: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);

function wrap(ctx: Ctx, text: string, maxWidth: number): string[] {
  const out: string[] = [];
  let line = '';
  for (const ch of text) {
    const next = line + ch;
    if (ctx.measureText(next).width > maxWidth && line) { out.push(line); line = ch; } else line = next;
  }
  if (line) out.push(line);
  return out;
}

// ───────────────────────── 新闻播报 ─────────────────────────
const NEWS = {
  bg: '#0C1B2A', ink: '#FFFFFF', red: '#D8232A', blue: '#1E4E8C', dim: '#7C93AD',
};

function newsTop(ctx: Ctx, beat: Beat, t: number, index: number, total: number) {
  const wipe = ease(t / 0.3);
  // 状态条
  ctx.fillStyle = NEWS.bg;
  ctx.fillRect(0, 0, W, 96);
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(24, 20, 96 * wipe, 56);
  ctx.fillStyle = '#fff';
  ctx.font = `900 34px ${HEAVY}`;
  ctx.fillText('LIVE', 42, 60);
  ctx.font = `900 40px ${HEAVY}`;
  const topic = beat.topic || '现场报道';
  ctx.fillText(topic, 140, 62);
  ctx.font = `400 26px ${LIGHT}`;
  ctx.fillStyle = NEWS.dim;
  const tc = `${String(20 + (index % 4)).padStart(2, '0')}:14:${String((index * 7) % 60).padStart(2, '0')}`;
  ctx.fillText(tc, 900, 60);

  // 红条
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(0, 96, W, 54 * wipe);
  ctx.fillStyle = '#fff';
  ctx.font = `400 24px ${LIGHT}`;
  ctx.fillText('S P E C I A L   R E P O R T   ／   特 别 报 道', 64, 133);

  // 标题
  ctx.font = `900 84px ${HEAVY}`;
  const lines = wrap(ctx, beat.title || beat.text, 840).slice(0, 2);
  ctx.fillStyle = NEWS.ink;
  lines.forEach((ln, i) => {
    const s = ease((t - 0.12 - i * 0.06) / 0.25);
    if (s <= 0) return;
    ctx.save();
    ctx.globalAlpha = s;
    ctx.translate(0, (1 - s) * 18);
    ctx.fillText(ln, 64, 236 + i * 84);
    ctx.restore();
  });
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(40, 150, 6, 170);
  ctx.strokeStyle = 'rgba(255,255,255,.5)';
  ctx.lineWidth = 1;
  ctx.strokeRect(930, 150, 72, 72);
  ctx.font = `400 20px ${LIGHT}`;
  ctx.fillStyle = '#fff';
  ctx.fillText('HD', 950, 194);

  // 顶部进度
  ctx.fillStyle = 'rgba(255,255,255,.14)';
  ctx.fillRect(0, 290, W, 3);
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(0, 290, (W * (index + 1)) / total, 3);
}

function newsStage(ctx: Ctx, beat: Beat, t: number) {
  // 网格 + 同心弧
  ctx.strokeStyle = 'rgba(27,51,80,.55)';
  ctx.lineWidth = 1;
  for (let x = 0; x < W; x += 48) { ctx.beginPath(); ctx.moveTo(x, 300); ctx.lineTo(x, 1300); ctx.stroke(); }
  for (let y = 300; y < 1300; y += 48) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
  ctx.strokeStyle = 'rgba(30,78,140,.3)';
  [380, 480, 580].forEach((r) => { ctx.beginPath(); ctx.arc(540, 1300, r, Math.PI, 0); ctx.stroke(); });

  // 信息板
  ctx.fillStyle = 'rgba(16,35,58,.92)';
  ctx.fillRect(90, 400, 900, 560);
  ctx.strokeStyle = '#2C5A8E';
  ctx.lineWidth = 1;
  ctx.strokeRect(90, 400, 900, 560);
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(90, 400, 4, 64);

  const items = (beat.items?.length ? beat.items : String(beat.text).split(/[，。；]/)).filter(Boolean).slice(0, 3);
  if (beat.card === 'hook' || beat.card === 'quote' || items.length === 0) {
    ctx.font = '900 92px ' + HEAVY;
    ctx.fillStyle = '#fff';
    const big = wrap(ctx, beat.title || beat.text, 900).slice(0, 4);
    big.forEach((ln, i) => {
      const s2 = ease((t - 0.15 - i * 0.08) / 0.3);
      ctx.save(); ctx.globalAlpha = s2; ctx.fillText(ln, 90, 560 + i * 118); ctx.restore();
    });
    return;
  }
  items.forEach((item, i) => {
    const s = ease((t - 0.2 - i * 0.12) / 0.3);
    if (s <= 0) return;
    const y = 480 + i * 150;
    ctx.save();
    ctx.globalAlpha = s;
    ctx.fillStyle = NEWS.red;
    ctx.fillRect(140, y - 36, 40, 40);
    ctx.fillStyle = '#fff';
    ctx.font = `900 26px ${HEAVY}`;
    ctx.fillText(String(i + 1).padStart(2, '0'), 150, y - 7);

    ctx.font = `900 52px ${HEAVY}`;
    ctx.fillStyle = '#fff';
    let line = item;
    const maxW = 720;
    if (ctx.measureText(line).width > maxW) {
      while (line.length > 2 && ctx.measureText(line + '…').width > maxW) line = line.slice(0, -1);
      line += '…';
    }
    ctx.fillText(line, 210, y);
    ctx.fillStyle = 'rgba(30,62,96,.9)';
    ctx.fillRect(140, y + 42, 760, 1);
    ctx.fillStyle = '#9DB4CC';
    ctx.font = `900 26px ${HEAVY}`;
    ctx.fillText('›', 920, y + 8);
    ctx.restore();
  });
}

function newsBottom(ctx: Ctx, beat: Beat, t: number) {
  ctx.fillStyle = 'rgba(12,27,42,.96)';
  ctx.fillRect(0, 1420, W, 140);
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(0, 1420, 24, 140);
  ctx.font = `900 58px ${HEAVY}`;
  ctx.fillStyle = '#fff';
  const lines = wrap(ctx, String(beat.text), 860).slice(0, 2);
  lines.forEach((ln, i) => ctx.fillText(ln, 96, 1478 + i * 62));

  // ticker
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(0, 1560, W, 56);
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 1560, W, 56);
  ctx.clip();
  ctx.font = `400 28px ${LIGHT}`;
  ctx.fillStyle = '#fff';
  const text = '  ● 开店三个数：投入 · 回本 · 流水    ● 评论区打「预算」领清单    ● 本片由 GetCut 生成  ';
  const w = ctx.measureText(text).width;
  const off = (t * 60) % w;
  ctx.fillText(text, 24 - off, 1598);
  ctx.fillText(text, 24 - off + w, 1598);
  ctx.restore();
}

export function drawNewsroom(ctx: Ctx, beat: Beat, t: number, index: number, total: number) {
  ctx.fillStyle = NEWS.bg;
  ctx.fillRect(0, 0, W, H);
  newsTop(ctx, beat, t, index, total);
  newsStage(ctx, beat, t);
  newsBottom(ctx, beat, t);
}

// ───────────────────────── 财报数据 ─────────────────────────
const LED = {
  bg: '#08090A', ink: '#F2F3F5', lime: '#C8FF00', gray: '#6B7280', line: '#23262B',
};

function ledgerTop(ctx: Ctx, beat: Beat, t: number) {
  ctx.fillStyle = LED.bg;
  ctx.fillRect(0, 0, W, H);
  ctx.font = `400 24px ${LIGHT}`;
  ctx.fillStyle = LED.gray;
  ctx.fillText('Q3 / FY2025', 64, 46);
  const right = 'CONFIDENTIAL';
  ctx.fillText(right, 1016 - ctx.measureText(right).width, 46);
  ctx.fillStyle = LED.line;
  ctx.fillRect(0, 64, W, 1);

  ctx.font = `900 72px ${HEAVY}`;
  ctx.fillStyle = LED.ink;
  const lines = wrap(ctx, beat.title || beat.topic || beat.text, 900).slice(0, 2);
  lines.forEach((ln, i) => {
    const s = ease((t - i * 0.06) / 0.25);
    ctx.save();
    ctx.globalAlpha = s;
    ctx.fillText(ln, 64, 160 + i * 84);
    ctx.restore();
  });
  const bar = ease(t / 0.3);
  ctx.fillStyle = LED.lime;
  ctx.fillRect(64, 228 + (lines.length - 1) * 84, 120 * bar, 6);
}

function ledgerStage(ctx: Ctx, beat: Beat, t: number) {
  const p = Math.min(1, t / 0.6);
  const raw = String(beat.value || '').replace(/[^\d.]/g, '');
  const num = Number(raw);
  const shown = Number.isFinite(num) && raw ? (num * p).toFixed(raw.includes('.') ? 1 : 0) : beat.value || '—';

  ctx.font = `400 36px ${LIGHT}`;
  ctx.fillStyle = '#8A8F98';
  ctx.fillText(beat.label || beat.topic || '关键数据', 64, 330);

  ctx.font = `900 300px ${HEAVY}`;
  ctx.fillStyle = LED.ink;
  ctx.fillText(String(shown), 64, 610);
  const w = ctx.measureText(String(shown)).width;
  ctx.font = `900 60px ${HEAVY}`;
  ctx.fillStyle = LED.lime;
  ctx.fillText(beat.unit || '', 64 + w + 16, 600);

  // 右下角框
  ctx.strokeStyle = LED.line;
  ctx.lineWidth = 1;
  ctx.strokeRect(880, 400, 120, 120);
  ctx.font = `900 44px ${HEAVY}`;
  ctx.fillStyle = LED.lime;
  ctx.fillText('↑', 905, 470);
  ctx.font = `400 20px ${LIGHT}`;
  ctx.fillStyle = LED.gray;
  ctx.fillText('vs 同行', 900, 500);

  ctx.fillStyle = LED.line;
  ctx.fillRect(64, 660, 952, 1);

  // 3×2 指标
  const cells = [
    ['前期投入', '28 万'], ['回本周期', '11 个月'],
    ['日均流水', '4,300'], ['毛利率', '38%'],
  ];
  cells.forEach(([k, v], i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 64 + col * 476;
    const y = 740 + row * 150;
    ctx.font = `400 22px ${LIGHT}`;
    ctx.fillStyle = LED.gray;
    ctx.fillText(k, x, y);
    ctx.font = `900 48px ${HEAVY}`;
    ctx.fillStyle = i === 3 ? LED.lime : LED.ink;
    ctx.fillText(v, x, y + 58);
    ctx.fillStyle = LED.line;
    ctx.fillRect(x, y + 78, 420, 1);
  });

  // 柱状图
  const baseY = 1210;
  ctx.fillStyle = '#2E3238';
  ctx.fillRect(64, baseY, 952, 2);
  for (let i = 0; i < 12; i++) {
    const grow = ease((t - 0.15 - i * 0.03) / 0.4);
    const h = (40 + ((i * 37) % 120)) * grow;
    ctx.fillStyle = i === 10 ? LED.lime : '#23262B';
    ctx.fillRect(64 + i * 78, baseY - h, 44, h);
  }
  ctx.font = `400 18px ${LIGHT}`;
  ctx.fillStyle = '#4A4F57';
  ctx.fillText('单位：万元', 880, baseY + 26);
}

function ledgerBottom(ctx: Ctx, beat: Beat) {
  ctx.fillStyle = LED.line;
  ctx.fillRect(64, 1440, 952, 1);
  ctx.font = `400 52px ${LIGHT}`;
  ctx.fillStyle = LED.ink;
  const lines = wrap(ctx, String(beat.text), 900).slice(0, 2);
  lines.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W - w) / 2, 1500 + i * 62);
  });
  ctx.fillStyle = LED.line;
  ctx.fillRect(64, 1580, 952, 1);
  ctx.font = `400 22px ${LIGHT}`;
  ctx.fillStyle = LED.gray;
  ctx.fillText('1080·30·A7F2', 64, 1650);
  const tag = 'CONFIDENTIAL — 仅供内部演示';
  ctx.fillText(tag, 1016 - ctx.measureText(tag).width, 1650);
}

export function drawLedger(ctx: Ctx, beat: Beat, t: number, index: number, total: number) {
  ledgerTop(ctx, beat, t);
  ledgerStage(ctx, beat, t);
  ledgerBottom(ctx, beat);
  // 进度
  ctx.fillStyle = 'rgba(255,255,255,.12)';
  ctx.fillRect(64, 1690, 952, 2);
  ctx.fillStyle = LED.lime;
  ctx.fillRect(64, 1690, (952 * (index + 1)) / total, 2);
}

// ───────────────────────── 白板讲解 ─────────────────────────
const MK = { bg: '#F7F4EC', ink: '#141414', red: '#E5342B', yellow: '#FFD400', sub: '#6B6B6B' };

/** 手抖矩形：四边各取三个点，做 2–3px 随机起伏。 */
function wobbleRect(ctx: Ctx, x: number, y: number, w: number, h: number, rnd: number) {
  ctx.beginPath();
  const j = (n: number) => Math.sin(rnd + n * 12.9898) * 2.6;
  ctx.moveTo(x + j(1), y + j(2));
  ctx.lineTo(x + w + j(3), y + j(4));
  ctx.lineTo(x + w + j(5), y + h + j(6));
  ctx.lineTo(x + j(7), y + h + j(8));
  ctx.closePath();
}

function drawMarker(ctx: Ctx, beat: Beat, t: number, index: number, _total: number) {
  ctx.fillStyle = MK.bg;
  ctx.fillRect(0, 0, W, H);

  // 板擦痕
  ctx.save();
  ctx.globalAlpha = 0.06;
  ctx.fillStyle = '#fff';
  for (let i = 0; i < 3; i++) {
    ctx.save();
    ctx.translate(120 + i * 300, 300 + i * 380);
    ctx.rotate((-20 + i * 3) * Math.PI / 180);
    ctx.fillRect(0, 0, 120, 900);
    ctx.restore();
  }
  ctx.restore();

  // 标题 + 手抖框
  const title = beat.title || beat.topic || beat.text;
  ctx.font = '900 66px ' + HEAVY;
  const lines = wrap(ctx, title, 820).slice(0, 2);
  ctx.strokeStyle = MK.ink;
  ctx.lineWidth = 4;
  const boxH = lines.length * 80 + 26;
  const boxW = Math.min(880, Math.max(...lines.map((l) => ctx.measureText(l).width)) + 56);
  wobbleRect(ctx, 64, 92, boxW, boxH, 3);
  ctx.stroke();
  ctx.fillStyle = MK.ink;
  lines.forEach((ln, i) => ctx.fillText(ln, 88, 160 + i * 80));

  // 黄色马克笔波浪
  const bw = 620 * ease(t / 0.4);
  ctx.strokeStyle = MK.yellow;
  ctx.lineWidth = 12;
  ctx.beginPath();
  for (let x = 0; x < bw; x += 8) {
    const y = 120 + boxH + Math.sin(x / 26) * 6;
    if (x === 0) ctx.moveTo(80 + x, y); else ctx.lineTo(80 + x, y);
  }
  ctx.stroke();

  // 右上手绘圆 + 序号
  ctx.strokeStyle = MK.red;
  ctx.lineWidth = 5;
  ctx.beginPath();
  ctx.ellipse(940, 130, 54, 50, 0.1, 0, Math.PI * 2);
  ctx.stroke();
  ctx.font = '900 52px ' + HEAVY;
  ctx.fillStyle = MK.red;
  ctx.fillText(String(index + 1).padStart(2, '0'), 912, 150);

  // 主卡（硬阴影）
  const items = (beat.items?.length ? beat.items : String(beat.text).split(/[，。；]/)).filter(Boolean).slice(0, 3);
  const startY = 640;
  items.forEach((item, i) => {
    const p = ease((t - 0.15 - i * 0.1) / 0.35);
    if (p <= 0) return;
    const y = startY + i * 210;
    ctx.save();
    ctx.globalAlpha = p;
    ctx.translate((1 - p) * -20, 0);
    // 硬阴影
    ctx.fillStyle = 'rgba(0,0,0,0.12)';
    ctx.fillRect(84, y + 10, 880, 170);
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(76, y, 880, 170);
    ctx.strokeStyle = MK.ink;
    ctx.lineWidth = 2;
    ctx.strokeRect(76, y, 880, 170);
    ctx.fillStyle = MK.ink;
    ctx.font = '900 40px ' + HEAVY;
    ctx.fillText(String(i + 1), 108, y + 108);
    ctx.font = '900 52px ' + HEAVY;
    const txt = wrap(ctx, item, 720)[0];
    ctx.fillText(txt, 168, y + 104);
    ctx.restore();
  });

  // 字幕 + 马克笔底
  ctx.font = '900 54px ' + HEAVY;
  const sub = wrap(ctx, String(beat.text), 860).slice(0, 2);
  const subY = 1470;
  ctx.fillStyle = 'rgba(255,212,0,0.55)';
  const subW = Math.max(...sub.map((l) => ctx.measureText(l).width));
  ctx.fillRect((W - subW) / 2 - 10, subY + 20, (subW + 20) * ease(t / 0.5), 24);
  ctx.fillStyle = '#111';
  sub.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W - w) / 2, subY + i * 62);
  });

  // 元信息
  ctx.font = '400 22px ' + LIGHT;
  ctx.fillStyle = '#8A857C';
  ctx.fillText('板书 · 第 ' + (index + 1) + ' 页', 64, H - 90);
  ctx.fillText('GETCUT', W - 64 - ctx.measureText('GETCUT').width, H - 90);
}

// ───────────────────────── 极简瑞士 ─────────────────────────
const SW = { bg: '#F7F7F5', ink: '#111111', red: '#E2231A', gray: '#8A8A8A' };

function drawSwiss(ctx: Ctx, beat: Beat, t: number, index: number, total: number) {
  ctx.fillStyle = SW.bg;
  ctx.fillRect(0, 0, W, H);

  // 顶部：红点 + 页码 + 基准线
  ctx.fillStyle = SW.red;
  ctx.beginPath();
  ctx.arc(78, 96, 12, 0, Math.PI * 2);
  ctx.fill();
  ctx.font = '400 24px ' + LIGHT;
  ctx.fillStyle = SW.gray;
  ctx.fillText(`${String(index + 1).padStart(2, '0')} / ${String(total).padStart(2, '0')}`, 104, 104);
  const right = 'STRATEGY';
  ctx.fillText(right, 1008 - ctx.measureText(right).width, 104);
  ctx.fillStyle = SW.ink;
  ctx.fillRect(72, 120, 936 * ease(t / 0.3), 1);

  // 标题
  ctx.font = '900 92px ' + HEAVY;
  ctx.fillStyle = SW.ink;
  const lines = wrap(ctx, beat.title || beat.topic || beat.text, 880).slice(0, 2);
  lines.forEach((ln, i) => ctx.fillText(ln, 72, 220 + i * 100));

  // 中线
  ctx.fillStyle = SW.ink;
  ctx.fillRect(72, 380, 388 * ease(t / 0.4), 2);

  // 巨数字
  const raw = String(beat.value || '').replace(/[^\d.]/g, '');
  const num = Number(raw);
  const p = Math.min(1, t / 0.5);
  const shown = Number.isFinite(num) && raw ? String(Math.round(num * p)) : (beat.value || '');
  ctx.font = '900 360px ' + HEAVY;
  ctx.fillStyle = SW.ink;
  ctx.fillText(shown, 60, 800);
  const wNum = ctx.measureText(shown).width;
  ctx.font = '900 72px ' + HEAVY;
  ctx.fillText(beat.unit || '', 72 + wNum + 28, 790);

  // 唯一红方块
  ctx.fillStyle = SW.red;
  const sq = 90 * ease((t - 0.2) / 0.25);
  ctx.fillRect(820, 470, sq, sq);

  // 两条细线 + 正文
  ctx.fillStyle = SW.ink;
  ctx.fillRect(72, 840, 936, 1);
  ctx.font = '400 34px ' + LIGHT;
  ctx.fillStyle = '#333';
  const body = wrap(ctx, beat.label || String(beat.text), 860).slice(0, 2);
  body.forEach((ln, i) => ctx.fillText(ln, 72, 920 + i * 50));

  // 底部
  ctx.fillStyle = SW.ink;
  ctx.fillRect(72, 1400, 936, 1);
  ctx.font = '900 54px ' + HEAVY;
  const sub = wrap(ctx, String(beat.text), 860).slice(0, 2);
  sub.forEach((ln, i) => ctx.fillText(ln, 72, 1470 + i * 62));
  ctx.font = '400 18px ' + LIGHT;
  ctx.fillStyle = '#999';
  ctx.fillText('1080×1920 ／ 30FPS ／ GETCUT', 72, 1640);

  // 页码角标
  ctx.fillStyle = '#BBB';
  ctx.fillText(String(index + 1).padStart(2, '0'), 970, 1300);
}

// ───────────────────────── 赛博终端 ─────────────────────────
const TM = { bg: '#050607', ink: '#E8FFF2', green: '#39FF88', dim: '#4A5A50', pane: '#0A0F0C', line: '#16201A' };

function drawTerminal(ctx: Ctx, beat: Beat, t: number, index: number, _total: number) {
  ctx.fillStyle = TM.bg;
  ctx.fillRect(0, 0, W, H);

  // 扫描线
  ctx.fillStyle = 'rgba(0,0,0,.35)';
  for (let y = 0; y < H; y += 4) ctx.fillRect(0, y, W, 1);

  // 顶部窗口条
  const dots = ['#FF5F57', '#FEBC2E', '#28C840'];
  dots.forEach((c, i) => { ctx.fillStyle = c; ctx.beginPath(); ctx.arc(76 + i * 30, 40, 7, 0, Math.PI * 2); ctx.fill(); });
  ctx.font = '400 24px ' + LIGHT;
  ctx.fillStyle = TM.dim;
  ctx.fillText('root@leadgen:~/campaign', 180, 50);
  ctx.fillStyle = TM.line;
  ctx.fillRect(0, 68, W, 1);

  // 标题
  ctx.font = '900 64px ' + HEAVY;
  ctx.fillStyle = TM.green;
  ctx.fillText('›', 64, 168);
  ctx.fillStyle = TM.ink;
  const titleLines = wrap(ctx, beat.title || beat.topic || beat.text, 800).slice(0, 2);
  titleLines.forEach((ln, i) => ctx.fillText(ln, 112, 160 + i * 70));
  const title = titleLines[titleLines.length - 1];
  const caretY = 112 + (titleLines.length - 1) * 70;
  const caretOn = Math.floor(t * 2) % 2 === 0;
  if (caretOn) { ctx.fillStyle = TM.green; ctx.fillRect(112 + ctx.measureText(title).width + 12, caretY, 24, 54); }

  // 日志窗口
  ctx.fillStyle = TM.pane;
  ctx.fillRect(64, 240, 952, 300);
  ctx.strokeStyle = '#1E2A22';
  ctx.lineWidth = 1;
  ctx.strokeRect(64, 240, 952, 300);
  ctx.font = '400 22px ' + LIGHT;
  ctx.fillStyle = '#6B8578';
  ctx.fillText('SCAN_REPORT.LOG', 84, 272);
  ctx.fillStyle = TM.line;
  ctx.fillRect(64, 286, 952, 1);

  const logs = ['01 解析口播文案 …… DONE', '02 匹配行业模板 …… DONE', '03 渲染 1080×1920 …… 100%'];
  ctx.font = '400 28px ' + LIGHT;
  logs.forEach((ln, i) => {
    const p = ease((t - 0.1 - i * 0.12) / 0.3);
    if (p <= 0) return;
    ctx.save();
    ctx.globalAlpha = p;
    ctx.fillStyle = TM.green;
    ctx.fillText('✓', 88, 350 + i * 62);
    ctx.fillStyle = '#8FA899';
    ctx.fillText(ln, 116, 350 + i * 62);
    ctx.restore();
  });

  // 巨数字
  const raw = String(beat.value || '').replace(/[^\d.]/g, '');
  const num = Number(raw);
  const shown = Number.isFinite(num) && raw ? String(Math.round(num * Math.min(1, t / 0.5))) : (beat.value || '');
  if (shown) {
  ctx.font = '900 180px ' + HEAVY;
  ctx.fillStyle = 'rgba(255,59,59,.35)';
  ctx.fillText(shown, 68, 880);
  ctx.fillStyle = 'rgba(0,217,255,.35)';
  ctx.fillText(shown, 60, 872);
  ctx.fillStyle = TM.green;
  ctx.fillText(shown, 64, 876);
  }

  // 进度条
  ctx.fillStyle = TM.line;
  ctx.fillRect(64, 950, 952, 18);
  ctx.fillStyle = TM.green;
  ctx.fillRect(64, 950, 952 * 0.92, 18);
  if (caretOn) { ctx.fillStyle = TM.green; ctx.fillRect(1020, 944, 8, 30); }

  // 四角 L
  ctx.strokeStyle = TM.green;
  ctx.lineWidth = 2;
  [[40, 210], [1008, 210], [40, 1330], [1008, 1330]].forEach(([x, y]) => {
    const sx = x === 40 ? 1 : -1;
    const sy = y === 210 ? 1 : -1;
    ctx.beginPath();
    ctx.moveTo(x, y + 32 * sy);
    ctx.lineTo(x, y);
    ctx.lineTo(x + 32 * sx, y);
    ctx.stroke();
  });

  // 底部
  ctx.font = '400 26px ' + LIGHT;
  ctx.fillStyle = TM.dim;
  ctx.fillText('OUT›', 64, 1462);
  ctx.font = '900 52px ' + HEAVY;
  ctx.fillStyle = TM.ink;
  const sub = wrap(ctx, String(beat.text), 760).slice(0, 2);
  sub.forEach((ln, i) => ctx.fillText(ln, 170, 1462 + i * 58));
  ctx.fillStyle = TM.line;
  for (let x = 64; x < 1016; x += 16) ctx.fillRect(x, 1560, 8, 1);
  ctx.font = '400 20px ' + LIGHT;
  ctx.fillStyle = '#33463B';
  ctx.fillText(`// FRAME ${String(index + 1).padStart(4, '0')} · 30FPS · RENDER OK`, 64, 1620);
}

// ───────────────────────── 报纸铅印 ─────────────────────────
const BS = { paper: '#F3EDE1', ink: '#141414', red: '#A5121A', gray: '#6E6659' };

/** 网点圆：越靠中心点越大，形成抽象剪影。 */
function halftone(ctx: Ctx, cx: number, cy: number, r: number, cell = 12) {
  ctx.fillStyle = BS.ink;
  for (let y = -r; y <= r; y += cell) {
    for (let x = -r; x <= r; x += cell) {
      const d = Math.sqrt(x * x + y * y) / r;
      if (d > 1) continue;
      const dot = 0.6 + (1 - d) * 3.6;
      ctx.beginPath();
      ctx.arc(cx + x, cy + y, dot, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function drawBroadsheet(ctx: Ctx, beat: Beat, _t: number, index: number, _total: number) {
  ctx.fillStyle = BS.paper;
  ctx.fillRect(0, 0, W, H);

  // 报头
  ctx.fillStyle = BS.ink;
  ctx.fillRect(64, 40, 952, 3);
  ctx.font = '900 92px ' + HEAVY;
  const mast = '每 日 商 讯';
  ctx.fillText(mast, (W - ctx.measureText(mast).width) / 2, 130);
  ctx.font = '400 20px ' + LIGHT;
  ctx.fillStyle = BS.gray;
  ctx.fillText('创刊于 2019', 64, 128);
  const issue = '第 ' + (100 + index) + ' 期';
  ctx.fillText(issue, 1016 - ctx.measureText(issue).width, 128);
  ctx.fillStyle = BS.ink;
  ctx.fillRect(64, 136, 952, 1);

  // 日期条
  ctx.font = '400 22px ' + LIGHT;
  ctx.fillStyle = BS.gray;
  ctx.fillText('2026 年 11 月 4 日 星期三', 64, 176);
  const price = '零售价 ¥1.00';
  ctx.fillText(price, 1016 - ctx.measureText(price).width, 176);
  ctx.fillStyle = BS.ink;
  ctx.fillRect(64, 190, 952, 1);

  // 主标题
  ctx.font = '900 80px ' + HEAVY;
  ctx.fillStyle = BS.ink;
  const title = wrap(ctx, beat.title || beat.topic || beat.text, 860).slice(0, 2);
  title.forEach((ln, i) => ctx.fillText(ln, 64, 330 + i * 90));
  // 独家章
  ctx.fillStyle = BS.red;
  ctx.fillRect(64, 206, 96, 36);
  ctx.fillStyle = '#fff';
  ctx.font = '900 24px ' + HEAVY;
  ctx.fillText('独家', 82, 232);
  ctx.fillStyle = BS.ink;
  ctx.fillRect(64, 440, 952, 2);

  // 双栏
  ctx.fillRect(506, 460, 1, 500);
  ctx.font = '400 26px ' + LIGHT;
  ctx.fillStyle = '#2B2720';
  const body = wrap(ctx, `${beat.label || ''}${String(beat.text)}`, 400).slice(0, 5);
  body.forEach((ln, i) => ctx.fillText(ln, 64, 510 + i * 48));

  // 右栏网点图
  halftone(ctx, 760, 600, 150);
  ctx.font = '400 20px ' + LIGHT;
  ctx.fillStyle = BS.gray;
  ctx.fillText('图：2019—2026 门店增长', 560, 780);

  // 引言框（双线）
  ctx.strokeStyle = BS.ink;
  ctx.lineWidth = 3;
  ctx.strokeRect(64, 830, 952, 180);
  ctx.lineWidth = 1;
  ctx.strokeRect(74, 840, 932, 160);
  ctx.font = '900 56px ' + HEAVY;
  ctx.fillStyle = BS.ink;
  const quote = (beat.value ? `${beat.value}${beat.unit || ''}` : title[0] || '');
  const qw = ctx.measureText(quote).width;
  ctx.fillText(quote, (W - qw) / 2, 920);
  ctx.font = '400 24px ' + LIGHT;
  ctx.fillStyle = BS.gray;
  const by = '—— 本报记者';
  ctx.fillText(by, (W - ctx.measureText(by).width) / 2, 970);

  // 底部
  ctx.fillStyle = BS.ink;
  ctx.fillRect(64, 1420, 952, 3);
  ctx.font = '900 54px ' + HEAVY;
  ctx.fillStyle = BS.ink;
  const sub = wrap(ctx, String(beat.text), 900).slice(0, 2);
  sub.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W - w) / 2, 1470 + i * 60);
  });
  ctx.fillRect(64, 1560, 952, 1);
  ctx.font = '400 20px ' + LIGHT;
  ctx.fillStyle = BS.gray;
  const end = '— 未 完 待 续 —';
  ctx.fillText(end, (W - ctx.measureText(end).width) / 2, 1650);
}

// ───────────────────────── 杂志封面 ─────────────────────────
const CV = { paper: '#EDE6DA', ink: '#141414', blue: '#2B3CFF', white: '#FFFFFF' };

function drawCover(ctx: Ctx, beat: Beat, t: number, index: number, _total: number) {
  ctx.fillStyle = CV.paper;
  ctx.fillRect(0, 0, W, H);

  // 刊名
  ctx.font = '900 150px ' + HEAVY;
  ctx.fillStyle = CV.ink;
  ctx.fillText('老  板', 52, 196);
  ctx.font = '400 24px ' + LIGHT;
  const issue = `NO.${String(index + 1).padStart(2, '0')} / 2026`;
  ctx.fillText(issue, 1016 - ctx.measureText(issue).width, 176);
  ctx.fillStyle = CV.ink;
  ctx.fillRect(56, 216, 960, 1);

  // 蓝色主几何（微旋转）
  const p = ease(t / 0.5);
  ctx.save();
  ctx.translate(540, 700);
  ctx.rotate(-2 * Math.PI / 180);
  ctx.fillStyle = CV.blue;
  ctx.fillRect(-450, -280 * p, 900, 560 * p);
  ctx.restore();

  // 米色圆
  ctx.fillStyle = CV.paper;
  ctx.beginPath();
  ctx.arc(540, 640, 210 * p, 0, Math.PI * 2);
  ctx.fill();

  // 竖排侧标
  ctx.font = '400 28px ' + LIGHT;
  ctx.fillStyle = CV.ink;
  const sides = ['回本模型', '316 家店', '加盟真相'];
  sides.forEach((s, i) => {
    ctx.save();
    ctx.translate(1008, 340 + i * 190);
    ctx.rotate(Math.PI / 2);
    ctx.fillText(s, 0, 0);
    ctx.restore();
  });

  // 大标题压蓝块
  ctx.font = '900 96px ' + HEAVY;
  ctx.fillStyle = CV.ink;
  const title = wrap(ctx, beat.title || beat.topic || beat.text, 940).slice(0, 2);
  title.forEach((ln, i) => ctx.fillText(ln, 44, 1070 + i * 104));

  // 条形码
  ctx.fillStyle = CV.white;
  ctx.fillRect(780, 1290, 200, 110);
  ctx.save();
  ctx.fillStyle = CV.ink;
  let x = 792;
  let seed = 7;
  while (x < 968) {
    seed = (seed * 1103515245 + 12345) % 2147483647;
    const w = 1 + (seed % 5);
    ctx.fillRect(x, 1300, w, 80);
    x += w + 2 + ((seed >> 8) % 4);
  }
  ctx.restore();
  ctx.font = '400 16px ' + LIGHT;
  ctx.fillStyle = CV.ink;
  ctx.fillText('9 771234 567003', 782, 1394);

  // 左下圆标
  ctx.strokeStyle = CV.ink;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(150, 1330, 62, 0, Math.PI * 2);
  ctx.stroke();
  ctx.font = '900 22px ' + HEAVY;
  ctx.fillStyle = CV.ink;
  ['本期附赠', '口播模板', '3 套'].forEach((s, i) => ctx.fillText(s, 106, 1318 + i * 28));

  // 底部黑条
  ctx.fillStyle = CV.ink;
  ctx.fillRect(0, 1420, W, 160);
  ctx.fillStyle = CV.blue;
  ctx.fillRect(0, 1416, W, 4);
  ctx.font = '900 56px ' + HEAVY;
  ctx.fillStyle = CV.paper;
  const sub = wrap(ctx, String(beat.text), 900).slice(0, 2);
  sub.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W - w) / 2, 1490 + i * 62);
  });
}

// ───────────────────────── 胶片纪实 ─────────────────────────
const RL = { black: '#0B0A09', cream: '#F0E6D6', brown: '#6B4A32', orange: '#D9822B', dim: '#8C7B6B' };

function drawReel(ctx: Ctx, beat: Beat, _t: number, index: number, _total: number) {
  ctx.fillStyle = RL.black;
  ctx.fillRect(0, 0, W, H);

  // 画框渐变
  const g = ctx.createLinearGradient(0, 200, W, 1280);
  g.addColorStop(0, '#2A1F18');
  g.addColorStop(0.55, '#4A3428');
  g.addColorStop(1, '#6B4A32');
  ctx.fillStyle = g;
  ctx.fillRect(0, 200, W, 1080);

  // 漏光
  const lg = ctx.createRadialGradient(180, 320, 0, 180, 320, 420);
  lg.addColorStop(0, 'rgba(217,130,43,0.38)');
  lg.addColorStop(1, 'rgba(217,130,43,0)');
  ctx.fillStyle = lg;
  ctx.fillRect(0, 200, W, 1080);

  // 颗粒（每帧随机，确定性种子）
  ctx.fillStyle = 'rgba(255,255,255,0.055)';
  let seed = 97 + index * 31;
  for (let i = 0; i < 900; i++) {
    seed = (seed * 1103515245 + 12345) % 2147483647;
    const x = seed % W;
    seed = (seed * 1103515245 + 12345) % 2147483647;
    const y = 200 + (seed % 1080);
    ctx.fillRect(x, y, 2, 2);
  }

  // 齿孔
  ctx.fillStyle = RL.black;
  for (let y = 200; y < 1280; y += 56) {
    ctx.fillRect(36, y + 8, 30, 40);
    ctx.fillRect(1014, y + 8, 30, 40);
  }

  // 顶部黑边信息
  ctx.font = '400 24px ' + LIGHT;
  ctx.fillStyle = RL.dim;
  ctx.fillText(`ROLL ${String(index + 1).padStart(2, '0')} ｜ 00:${String(12 + index).padStart(2, '0')}:04:18`, 64, 96);
  const iso = 'ISO 400 · f/2.0';
  ctx.fillText(iso, 1016 - ctx.measureText(iso).width, 96);

  // 画框内文案：一句细字 + 署名
  ctx.fillStyle = '#B5A08A';
  ctx.fillRect(510, 560, 60, 2);
  ctx.font = '400 60px ' + LIGHT;
  ctx.fillStyle = RL.cream;
  const line = wrap(ctx, beat.title || beat.text, 820).slice(0, 2);
  line.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W - w) / 2, 660 + i * 76);
  });
  ctx.font = '400 26px ' + LIGHT;
  ctx.fillStyle = '#B5A08A';
  const by = `—— ${beat.topic || '当事人'} · 第 ${index + 1} 段`;
  ctx.fillText(by, (W - ctx.measureText(by).width) / 2, 830);

  // 右下时间
  ctx.font = '400 20px ' + LIGHT;
  ctx.fillStyle = RL.dim;
  ctx.fillText(`01:${String(20 + index).padStart(2, '0')}`, 940, 1210);

  // 底部字幕（细体描边）
  ctx.font = '400 54px ' + LIGHT;
  const sub = wrap(ctx, String(beat.text), 880).slice(0, 2);
  sub.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    const x = (W - w) / 2;
    const y = 1470 + i * 64;
    ctx.lineWidth = 6;
    ctx.strokeStyle = 'rgba(0,0,0,0.85)';
    ctx.strokeText(ln, x, y);
    ctx.fillStyle = RL.cream;
    ctx.fillText(ln, x, y);
  });
  ctx.font = '400 18px ' + LIGHT;
  ctx.fillStyle = RL.dim;
  const end = '导 演 剪 辑 版';
  ctx.fillText(end, (W - ctx.measureText(end).width) / 2, 1620);
}

export const NEW_STYLES: Partial<Record<ThemeName, (c: Ctx, b: Beat, t: number, i: number, n: number) => void>> = {
  newsroom: drawNewsroom,
  ledger: drawLedger,
  marker: drawMarker,
  swiss: drawSwiss,
  terminal: drawTerminal,
  broadsheet: drawBroadsheet,
  cover: drawCover,
  reel: drawReel,
};









