export type Ctx2D = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

import type { Beat, ThemeName } from './types';
import { PALETTES, type Palette } from './theme';

export const W = 1080;
export const H = 1920;
export const FPS = 30;

const HEAVY = '"Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif';

const ease = (x: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);

function wrapText(ctx: Ctx2D, text: string, maxWidth: number): string[] {
  const lines: string[] = [];
  let line = '';
  for (const ch of text) {
    const next = line + ch;
    if (ctx.measureText(next).width > maxWidth && line) {
      lines.push(line);
      line = ch;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function drawBackground(ctx: Ctx2D, pal: Palette) {
  const g = ctx.createLinearGradient(0, 0, W, H);
  g.addColorStop(0, pal.bg1);
  g.addColorStop(1, pal.bg2);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  const glow = ctx.createRadialGradient(W * 0.15, H * 0.05, 0, W * 0.15, H * 0.05, 950);
  glow.addColorStop(0, pal.glow);
  glow.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W, H);
}

function drawChrome(ctx: Ctx2D, pal: Palette, index: number, total: number, topic?: string) {
  ctx.save();
  ctx.font = `700 26px ${HEAVY}`;
  ctx.fillStyle = pal.dark ? pal.ink : pal.ink;
  ctx.globalAlpha = 0.62;
  ctx.fillText('GETCUT', 64, 80);
  ctx.fillStyle = pal.accent;
  ctx.fillText('·', 64 + ctx.measureText('GETCUT').width + 6, 80);
  ctx.fillStyle = pal.ink;
  ctx.fillText('获客片', 64 + ctx.measureText('GETCUT·').width + 16, 80);
  ctx.globalAlpha = 1;

  if (topic) {
    ctx.font = `700 40px ${HEAVY}`;
    ctx.fillStyle = pal.accent;
    ctx.fillRect(64, 150, 78, 52);
    ctx.fillStyle = pal.accentInk;
    ctx.fillText(String(index + 1).padStart(2, '0'), 78, 187);
    ctx.fillStyle = pal.ink;
    ctx.fillText(topic, 162, 188);
  }

  ctx.font = `400 24px ${HEAVY}`;
  ctx.fillStyle = pal.muted;
  const page = `${index + 1} / ${total}`;
  ctx.fillText(page, W - 64 - ctx.measureText(page).width, 80);

  ctx.fillStyle = pal.hairline;
  ctx.fillRect(64, 218, W - 128, 3);
  ctx.fillStyle = pal.accent;
  ctx.fillRect(64, 218, ((W - 128) * (index + 1)) / total, 3);
  ctx.restore();
}

function drawSubtitle(ctx: Ctx2D, text: string) {
  ctx.save();
  ctx.font = `700 52px ${HEAVY}`;
  const lines = wrapText(ctx, text, 880);
  const lineH = 70;
  const boxH = lines.length * lineH + 24;
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.fillRect(60, H - 200 - boxH, W - 120, boxH);
  ctx.fillStyle = '#ffffff';
  lines.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W - w) / 2, H - 200 - boxH + 58 + i * lineH);
  });
  ctx.restore();
}

function drawBottom(ctx: Ctx2D, pal: Palette) {
  ctx.save();
  ctx.font = `400 22px ${HEAVY}`;
  ctx.fillStyle = pal.muted;
  ctx.fillText('GETCUT · 获客片', 64, H - 70);
  const tag = '#获客 #本地生意';
  ctx.fillText(tag, W - 64 - ctx.measureText(tag).width, H - 70);
  ctx.restore();
}

/** 关键词上色：把数字/金额拆出来单独画。 */
function drawRichText(ctx: Ctx2D, text: string, x: number, y: number, pal: Palette, color: string) {
  const parts = text.split(/(\d+(?:\.\d+)?\s*(?:万|亿|%|元|块|天|年|个月|倍|件|人|分)?)/);
  let cx = x;
  for (let i = 0; i < parts.length; i++) {
    const seg = parts[i];
    if (!seg) continue;
    ctx.fillStyle = i % 2 === 1 ? pal.accent : color;
    ctx.fillText(seg, cx, y);
    cx += ctx.measureText(seg).width;
  }
}

function cardHook(ctx: Ctx2D, beat: Beat, t: number, pal: Palette) {
  const p = ease(t / 0.45);
  ctx.font = `700 30px ${HEAVY}`;
  ctx.fillStyle = pal.accent;
  ctx.fillText('获客 · 一分钟说清', 96, 520);

  ctx.font = `900 112px ${HEAVY}`;
  const lines = wrapText(ctx, beat.title || beat.text, 880);
  lines.forEach((ln, i) => {
    ctx.save();
    ctx.globalAlpha = ease((t - 0.1 * i) / 0.45);
    ctx.fillStyle = pal.ink;
    ctx.fillText(ln, 96, 680 + i * 132 + (1 - p) * 26);
    ctx.restore();
  });
  ctx.fillStyle = pal.accent;
  ctx.fillRect(96, 700 + (lines.length - 1) * 132, 260 * p, 10);
}

function cardPlain(ctx: Ctx2D, beat: Beat, t: number, pal: Palette) {
  const words = beat.text.split(/[，。！？；、,.;!?]/).map((s) => s.trim()).filter((s) => s.length >= 2).slice(0, 3);
  ctx.font = `900 72px ${HEAVY}`;
  words.forEach((w, i) => {
    const p = ease((t - i * 0.18) / 0.4);
    if (p <= 0) return;
    ctx.save();
    ctx.globalAlpha = p;
    ctx.translate((1 - p) * -26, 0);
    ctx.fillStyle = pal.accent;
    ctx.fillRect(96, 700 + i * 130, 12, 12);
    drawRichText(ctx, w, 132, 726 + i * 130, pal, pal.ink);
    ctx.restore();
  });
}

function cardStat(ctx: Ctx2D, beat: Beat, t: number, pal: Palette) {
  ctx.font = `400 30px ${HEAVY}`;
  ctx.fillStyle = pal.muted;
  ctx.fillText('数据', 96, 540);

  const num = Number(String(beat.value || '').replace(/[^\d.]/g, ''));
  const shown = Number.isFinite(num) ? Math.round(num * Math.min(1, t / 0.6)) : beat.value;
  ctx.font = `900 260px ${HEAVY}`;
  ctx.fillStyle = pal.accent;
  ctx.fillText(String(shown), 90, 820);
  const numW = ctx.measureText(String(shown)).width;
  ctx.font = `900 84px ${HEAVY}`;
  ctx.fillStyle = pal.ink;
  ctx.fillText(beat.unit || '', 90 + numW + 14, 810);

  ctx.fillStyle = pal.hairline;
  ctx.fillRect(96, 880, 620, 3);
  ctx.font = `400 48px ${HEAVY}`;
  ctx.fillStyle = pal.muted;
  if (beat.label) ctx.fillText(wrapText(ctx, beat.label, 820)[0], 96, 950);

  // 三根柱子
  const bars = [0.42, 0.68, 1];
  bars.forEach((h, i) => {
    const bp = ease((t - 0.1 - i * 0.08) / 0.5);
    ctx.fillStyle = i === 2 ? pal.accent : pal.hairline;
    ctx.fillRect(96 + i * 90, 1140 - 200 * h * bp, 66, 200 * h * bp);
  });
}

function cardList(ctx: Ctx2D, beat: Beat, t: number, pal: Palette) {
  const items = (beat.items?.length ? beat.items : beat.text.split(/[、，,；;]/)).filter(Boolean).slice(0, 4);
  ctx.font = `900 56px ${HEAVY}`;
  items.forEach((item, i) => {
    const p = ease((t - i * 0.2) / 0.4);
    if (p <= 0) return;
    ctx.save();
    ctx.globalAlpha = p;
    const y = 560 + i * 150;
    ctx.fillStyle = i === 0 ? pal.accent : 'rgba(255,255,255,0.08)';
    ctx.fillRect(96, y - 46, 56, 56);
    ctx.fillStyle = i === 0 ? pal.accentInk : pal.muted;
    ctx.font = `700 26px ${HEAVY}`;
    ctx.fillText(String(i + 1).padStart(2, '0'), 108, y - 8);
    ctx.font = `900 56px ${HEAVY}`;
    const lines = wrapText(ctx, item, 760);
    lines.slice(0, 2).forEach((ln, k) => {
      drawRichText(ctx, ln, 186, y + k * 72, pal, pal.ink);
    });
    ctx.restore();
  });
}

function cardCompare(ctx: Ctx2D, beat: Beat, t: number, pal: Palette) {
  const p = ease(t / 0.45);
  const panels = [
    { head: '别人', body: beat.left || '', hot: false },
    { head: '我们', body: beat.right || '', hot: true },
  ];
  panels.forEach((pn, i) => {
    const x = 80 + i * 470;
    ctx.save();
    ctx.globalAlpha = ease((t - i * 0.12) / 0.4);
    ctx.fillStyle = pn.hot ? pal.panel : 'rgba(0,0,0,0.18)';
    ctx.fillRect(x, 470, 440, 620);
    ctx.strokeStyle = pn.hot ? pal.accent : pal.hairline;
    ctx.lineWidth = 3;
    ctx.strokeRect(x, 470, 440, 620);
    ctx.font = `700 26px ${HEAVY}`;
    ctx.fillStyle = pn.hot ? pal.accent : pal.muted;
    ctx.fillText(pn.head, x + 32, 530);
    ctx.font = `900 56px ${HEAVY}`;
    wrapText(ctx, pn.body, 380).slice(0, 4).forEach((ln, k) => {
      drawRichText(ctx, ln, x + 32, 610 + k * 74, pal, pal.ink);
    });
    ctx.restore();
  });
  // VS
  ctx.save();
  ctx.globalAlpha = Math.min(1, p * 1.3);
  ctx.fillStyle = pal.accent;
  ctx.beginPath();
  ctx.arc(W / 2, 780, 58, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = pal.accentInk;
  ctx.font = `900 36px ${HEAVY}`;
  ctx.fillText('VS', W / 2 - 28, 794);
  ctx.restore();
}

function cardQuote(ctx: Ctx2D, beat: Beat, t: number, pal: Palette) {
  const p = ease(t / 0.5);
  ctx.save();
  ctx.globalAlpha = 0.25;
  ctx.font = `900 260px ${HEAVY}`;
  ctx.fillStyle = pal.accent;
  ctx.fillText('“', 80, 700);
  ctx.restore();

  ctx.font = `900 92px ${HEAVY}`;
  const lines = wrapText(ctx, beat.title || beat.text, 860);
  ctx.save();
  ctx.globalAlpha = p;
  ctx.translate((1 - p) * -26, 0);
  lines.slice(0, 4).forEach((ln, i) => {
    drawRichText(ctx, ln, 96, 780 + i * 118, pal, pal.ink);
  });
  ctx.restore();
}

function cardCta(ctx: Ctx2D, beat: Beat, t: number, pal: Palette) {
  const p = ease(t / 0.45);
  ctx.save();
  ctx.globalAlpha = p;
  ctx.translate(0, (1 - p) * 30);
  ctx.fillStyle = pal.accent;
  const boxH = 320;
  ctx.fillRect(80, 600, W - 160, boxH);
  ctx.fillStyle = pal.accentInk;
  ctx.font = `900 72px ${HEAVY}`;
  const lines = wrapText(ctx, beat.cta || beat.title || beat.text, 820).slice(0, 2);
  lines.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W - w) / 2, 720 + i * 92);
  });
  ctx.restore();

  ctx.save();
  ctx.globalAlpha = ease((t - 0.25) / 0.4);
  ctx.font = `400 32px ${HEAVY}`;
  ctx.fillStyle = pal.ink;
  const pills = ['私信', '评论', '到店咨询'];
  let x = 170;
  pills.forEach((s) => {
    const w = ctx.measureText(s).width + 56;
    ctx.strokeStyle = pal.hairline;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(x, 980, w, 74, 37);
    ctx.stroke();
    ctx.fillText(s, x + 28, 1028);
    x += w + 18;
  });
  ctx.restore();
}

function cardIntro(ctx: Ctx2D, beat: Beat, t: number, pal: Palette) {
  const p = ease(t / 0.5);
  ctx.save();
  ctx.globalAlpha = p;
  ctx.textAlign = 'center';
  ctx.font = `900 44px ${HEAVY}`;
  ctx.fillStyle = pal.accent;
  ctx.fillText('GETCUT', W / 2, 700);
  ctx.font = `400 26px ${HEAVY}`;
  ctx.fillStyle = pal.muted;
  ctx.fillText('本机出片 · 一分钟说清', W / 2, 748);
  ctx.font = `900 84px ${HEAVY}`;
  ctx.fillStyle = pal.ink;
  const lines = wrapText(ctx, beat.title || beat.text, 860);
  lines.slice(0, 3).forEach((ln, i) => ctx.fillText(ln, W / 2, 900 + i * 104));
  ctx.fillStyle = pal.accent;
  ctx.fillRect(W / 2 - 90, 900 + lines.length * 104, 180, 6);
  ctx.restore();
}

function cardChapter(ctx: Ctx2D, beat: Beat, t: number, pal: Palette) {
  const p = ease(t / 0.45);
  ctx.save();
  ctx.textAlign = 'center';
  ctx.globalAlpha = p;
  ctx.font = `900 260px ${HEAVY}`;
  ctx.strokeStyle = pal.accent;
  ctx.lineWidth = 4;
  ctx.strokeText(String(beat.value || '1').padStart(2, '0'), W / 2, 760);
  ctx.font = `400 28px ${HEAVY}`;
  ctx.fillStyle = pal.muted;
  ctx.fillText(`第 ${String(beat.value || '1').padStart(2, '0')} 部分`, W / 2, 830);
  ctx.font = `900 92px ${HEAVY}`;
  ctx.fillStyle = pal.ink;
  wrapText(ctx, beat.topic || beat.title || '', 860).slice(0, 2).forEach((ln, i) => ctx.fillText(ln, W / 2, 960 + i * 110));
  ctx.fillStyle = pal.accent;
  ctx.fillRect(W / 2 - 110, 1090, 220, 8);
  ctx.restore();
}

const CARDS: Record<string, (ctx: Ctx2D, beat: Beat, t: number, pal: Palette) => void> = {
  hook: cardHook, plain: cardPlain, stat: cardStat, list: cardList,
  compare: cardCompare, quote: cardQuote, cta: cardCta,
  intro: cardIntro, chapter: cardChapter,
};

export function drawFrame(
  ctx: Ctx2D,
  beat: Beat,
  t: number,
  theme: ThemeName,
  index: number,
  total: number,
) {
  const pal = PALETTES[theme];
  ctx.save();
  drawBackground(ctx, pal);

  const isCover = beat.card === 'intro' || beat.card === 'chapter';
  if (isCover) {
    CARDS[beat.card](ctx, beat, t, pal);
  } else {
    drawChrome(ctx, pal, index, total, beat.topic);
    // 舞台轻微推近
    const push = 1 + 0.03 * Math.min(1, t / Math.max(0.5, beat.duration));
    ctx.translate(W / 2, H / 2);
    ctx.scale(push, push);
    ctx.translate(-W / 2, -H / 2);
    CARDS[beat.card]?.(ctx, beat, t, pal);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const speaks = ['hook', 'quote', 'cta', 'list', 'plain'].includes(beat.card);
    if (!speaks) drawSubtitle(ctx, beat.text);
    drawBottom(ctx, pal);
  }
  ctx.restore();
}



