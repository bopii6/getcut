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

export const NEW_STYLES: Partial<Record<ThemeName, (c: Ctx, b: Beat, t: number, i: number, n: number) => void>> = {
  newsroom: drawNewsroom,
  ledger: drawLedger,
};



