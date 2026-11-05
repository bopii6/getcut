// 全站设计令牌。所有组件只允许引用这里的值，不许在 CSS 里写死数字。
//
// 规则（来自客户）：
// - 只允许黑 / 白 / 灰 + 一个强调色
// - 卡片圆角 ≤ 8px，不许用阴影
// - 靠留白和字号分层，不靠边框和色块
// - 字号只有：标题 48 / 28 / 18，正文 15，辅助 12（不许出现第 4 个）
// - 行高 1.6，标题字距 -0.02em
// - 动效 120–200ms，禁止超过 300ms，禁止弹跳

export const TYPE = {
  h1: 48,
  h2: 28,
  h3: 18,
  body: 15,
  aux: 12,
} as const;

export const LINE = 1.6;
export const TRACK = '-0.02em';

export const RADIUS = 8;

export const DUR = {
  fast: 120,
  base: 160,
  slow: 200,
} as const;

/** 只有一个强调色。其余一律灰阶。 */
export const COLOR = {
  bg: '#0B0B0C',
  surface: '#141416',
  surface2: '#1A1A1D',
  ink: '#F2F2F3',
  dim: '#8E8E95',
  faint: '#5A5A61',
  line: 'rgba(255,255,255,0.10)',
  accent: '#F0B429',
  accentInk: '#161006',
} as const;

/** 只保留三档间距，避免随手写 padding。 */
export const SPACE = {
  s: 12,
  m: 24,
  l: 48,
} as const;

/** 生成一份 CSS 变量串，注入到 <style> 里，组件里只写 var(--t-h2) 这种。 */
export function cssVars() {
  return `
    --bg:${COLOR.bg}; --surface:${COLOR.surface}; --surface2:${COLOR.surface2};
    --ink:${COLOR.ink}; --dim:${COLOR.dim}; --faint:${COLOR.faint}; --line:${COLOR.line};
    --accent:${COLOR.accent}; --accent-ink:${COLOR.accentInk};
    --r:${RADIUS}px;
    --t-h1:${TYPE.h1}px; --t-h2:${TYPE.h2}px; --t-h3:${TYPE.h3}px; --t-body:${TYPE.body}px; --t-aux:${TYPE.aux}px;
    --lh:${LINE}; --track:${TRACK};
    --s1:${SPACE.s}px; --s2:${SPACE.m}px; --s3:${SPACE.l}px;
    --fast:${DUR.fast}ms; --base:${DUR.base}ms; --slow:${DUR.slow}ms;
  `;
}
