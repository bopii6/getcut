/**
 * 皮肤层：把「长什么样」从组件里抽出来。
 *
 * 一个模板 = 骨架(layout) × 皮肤(palette/font/decor/motion)。
 * 组件只认 T.*，渲染入口按 props.template 把对应皮肤写进 T。
 *
 * 注意：T 是模块级可变对象，但这套渲染里「一次渲染 = 一个模板」，
 * 皮肤在整次渲染里恒定不变，所以子组件渲染前赋值是安全的。
 * （Remotion 官方推荐 Context，这里沿用代码库既有的 T 写法以降低改动面。）
 */

import LAYOUTS from './layouts.json';

export type LayoutKind = 'editorial' | 'bleed' | 'lower' | 'poster' | 'data' | 'zhigu' | 'macro';
export type DecorKind = 'grain' | 'grid' | 'none';

/** 版式几何：从 layouts.json 读（TS 与 Python 共用同一份，防漂移） */
export type Rect = {left: number; top: number; width: number; height: number; radius?: number};
export type Geo = {
  layout: LayoutKind;
  paper?: Rect;
  panel?: Rect;
  mediaWin?: Rect;
  headline: {top: number; size: number; lineGap?: number; [k: string]: unknown};
  subtitle: {top?: number; bottom?: number; size: number; side?: number; [k: string]: unknown};
  footer: {top: number; size: number; width: number};
  bigText?: {size: number; subSize: number; side: number};
  card?: {side: number; topPct: number; size: number; titleSize?: number; subSize?: number};
  sectionLabel?: {left: number; top: number; size: number};
  columns?: {left: Rect; right: Rect};
  contentCenterY?: number;
  /** 派生：媒体窗在整帧里的位置 = panel + mediaWin（素材轨的落点） */
  mediaRect?: Rect;
};

export type Skin = {
  name: string;
  /** 骨架：元素怎么摆 */
  layout: LayoutKind;
  /** 版式几何（新增模板时也可只覆盖需要的项） */
  geo: Geo;

  // ---------- 画布 ----------
  bgTop: string;
  bgBottom: string;
  /** 画布装饰：颗粒 / 网格 / 无 */
  decor: DecorKind;
  /** 四角压暗 */
  vignette: boolean;

  // ---------- 纸卡 + 内嵌板 ----------
  paperTop: string;
  paper: string;
  paperBottom: string;
  paperTexture: DecorKind;
  paperShadow: string;
  panel: string;
  panelRadius: number;
  cardRadius: number;

  // ---------- 文字 ----------
  /** 纸卡上的正文字色（纸卡是浅色时给深色，深色时给浅色） */
  ink: string;
  /** 画面上的主字色 */
  onMedia: string;
  /** 画面上的次级字色 */
  mutedInk: string;
  /** 等宽小字（镜号 / 年份 / 代码） */
  codeInk: string;
  /** 字幕色 */
  white: string;
  gray: string;
  grayDim: string;

  // ---------- 强调色 ----------
  accent: string;
  accentSoft: string;
  /** 铺在 accent 上的字色 */
  onAccent: string;
  /** 第二强调色（对比卡右栏等） */
  teal: string;

  // ---------- 卡片 ----------
  cardWhite: string;
  cardInk: string;
  cardMuted: string;
  cardLine: string;
  chipBg: string;
  timelineBg: string;
  slotBg: string;
  /** 卡片底遮罩（叠在素材上，纯色） */
  scrim: string;
  /** 数字卡右侧渐变遮罩 */
  calloutScrim: string;

  // ---------- 标题带 ----------
  highlightBg: string;
  highlightInk: string;

  // ---------- 底部信息条（lower 骨架专用） ----------
  /** 信息条底色；不给就用默认深色（老模板维持原样） */
  barBg?: string;
  /** 信息条式字幕的底 */
  barSubBg?: string;
  /** 满屏骨架的页面底色（默认纯黑） */
  pageBg?: string;

  // ---------- 字体 ----------
  font: string;
  fontMono: string;

  // ---------- 动效 ----------
  /** 入场帧数：越小越快 */
  motionFrames: number;
};

const SANS = "'SSH','Source Han Sans CN','Microsoft YaHei',sans-serif";
/** 特粗黑体 → 思源宋体，用于复古/人文叙事 */
const SERIF = "'SSHSerif','Noto Serif SC','Source Han Serif SC','Songti SC',serif";
/** 细黑体，用于极简大留白 */
const LIGHT = "'SSHLight','Noto Sans SC','Source Han Sans CN',sans-serif";
const MONO = "'Consolas','DejaVu Sans Mono','Liberation Mono',monospace";

/** 杂志编辑：现有基线，暖灰纸卡 + 锈红 */
const editorial: Omit<Skin, 'geo'> = {
  name: '杂志编辑版',
  layout: 'editorial',
  bgTop: '#1c1a18',
  bgBottom: '#171411',
  decor: 'grain',
  vignette: false,
  paperTop: '#e8e6e5',
  paper: '#e4e2e0',
  paperBottom: '#dcd9d6',
  paperTexture: 'grain',
  paperShadow: '0 10px 30px rgba(0,0,0,0.55)',
  panel: '#1a1817',
  panelRadius: 16,
  cardRadius: 12,
  ink: '#1c1a18',
  onMedia: '#f5f3f0',
  mutedInk: '#b7b1aa',
  codeInk: '#d2cdc6',
  white: '#f5f3f0',
  gray: '#999590',
  grayDim: '#76706a',
  accent: '#a44231',
  accentSoft: '#c14f35',
  onAccent: '#f7f2ec',
  teal: '#7fd4c9',
  cardWhite: '#eee9e2',
  cardInk: '#1c1a18',
  cardMuted: '#5a5651',
  cardLine: '#b7b1aa',
  chipBg: 'rgba(120,40,20,0.78)',
  timelineBg: 'rgba(40,30,14,0.85)',
  slotBg: 'rgba(32,17,10,0.82)',
  scrim: 'rgba(18,14,11,0.55)',
  calloutScrim:
    'linear-gradient(to left, rgba(16,12,9,0.94) 55%, rgba(16,12,9,0.55) 80%, rgba(16,12,9,0) 100%)',
  highlightBg: '#16110e',
  highlightInk: '#f5f3f0',
  font: SANS,
  fontMono: MONO,
  motionFrames: 9,
};

/** 财经数据：深蓝黑终端感 + 青蓝数据色 + 网格 */
const finance: Omit<Skin, 'geo'> = {
  name: '财经数据版',
  layout: 'editorial',
  bgTop: '#0b1622',
  bgBottom: '#050b13',
  decor: 'grid',
  vignette: false,
  paperTop: '#12202f',
  paper: '#0e1a26',
  paperBottom: '#0a1420',
  paperTexture: 'grid',
  paperShadow: '0 10px 30px rgba(0,0,0,0.7)',
  panel: '#0b1622',
  panelRadius: 8,
  cardRadius: 6,
  ink: '#dbe7f1',
  onMedia: '#eaf4fb',
  mutedInk: '#7e94a8',
  codeInk: '#9fb4c6',
  white: '#eaf4fb',
  gray: '#6b8296',
  grayDim: '#4e6377',
  accent: '#2ea8d8',
  accentSoft: '#6fd0f0',
  onAccent: '#04141d',
  teal: '#f0b429',
  cardWhite: '#13212f',
  cardInk: '#dbe7f1',
  cardMuted: '#8ba1b4',
  cardLine: '#2c3d4e',
  chipBg: 'rgba(20,70,100,0.8)',
  timelineBg: 'rgba(14,38,56,0.9)',
  slotBg: 'rgba(8,26,40,0.88)',
  scrim: 'rgba(3,9,16,0.68)',
  calloutScrim:
    'linear-gradient(to left, rgba(4,12,20,0.96) 55%, rgba(4,12,20,0.6) 80%, rgba(4,12,20,0) 100%)',
  highlightBg: '#0b2436',
  highlightInk: '#6fd0f0',
  font: SANS,
  fontMono: MONO,
  motionFrames: 5,
};

/** 极简白：纯白 + 黑字 + 零装饰 + 大留白 */
const minimal: Omit<Skin, 'geo'> = {
  name: '极简白版',
  layout: 'editorial',
  bgTop: '#f1f1ef',
  bgBottom: '#e3e3e0',
  decor: 'none',
  vignette: false,
  paperTop: '#ffffff',
  paper: '#ffffff',
  paperBottom: '#fafaf8',
  paperTexture: 'none',
  paperShadow: '0 8px 26px rgba(0,0,0,0.10)',
  panel: '#f6f6f4',
  panelRadius: 4,
  cardRadius: 4,
  ink: '#111111',
  onMedia: '#111111',
  mutedInk: '#6e6e6a',
  codeInk: '#9a9a96',
  white: '#111111',
  gray: '#8e8e8a',
  grayDim: '#b0b0ac',
  accent: '#111111',
  accentSoft: '#454542',
  onAccent: '#ffffff',
  teal: '#454542',
  cardWhite: '#f0f0ee',
  cardInk: '#111111',
  cardMuted: '#6e6e6a',
  cardLine: '#d9d9d5',
  chipBg: 'rgba(17,17,17,0.88)',
  timelineBg: 'rgba(232,232,229,0.96)',
  slotBg: 'rgba(240,240,237,0.92)',
  scrim: 'rgba(255,255,255,0.80)',
  calloutScrim:
    'linear-gradient(to left, rgba(255,255,255,0.97) 55%, rgba(255,255,255,0.65) 80%, rgba(255,255,255,0) 100%)',
  highlightBg: '#111111',
  highlightInk: '#ffffff',
  font: LIGHT,
  fontMono: MONO,
  motionFrames: 9,
};

/** 全出血沉浸：素材铺满，只有一层渐变压字 */
const bleed: Omit<Skin, 'geo'> = {
  name: '全出血沉浸版',
  layout: 'bleed',
  bgTop: '#000000',
  bgBottom: '#000000',
  decor: 'none',
  vignette: false,
  paperTop: '#111111',
  paper: '#0d0d0d',
  paperBottom: '#080808',
  paperTexture: 'none',
  paperShadow: 'none',
  panel: '#0d0d0d',
  panelRadius: 0,
  cardRadius: 12,
  ink: '#ffffff',
  onMedia: '#ffffff',
  mutedInk: 'rgba(255,255,255,0.76)',
  codeInk: 'rgba(255,255,255,0.66)',
  white: '#ffffff',
  gray: 'rgba(255,255,255,0.62)',
  grayDim: 'rgba(255,255,255,0.42)',
  accent: '#f0b429',
  accentSoft: '#ffd166',
  onAccent: '#1a1206',
  teal: '#7fd4c9',
  cardWhite: 'rgba(10,10,10,0.82)',
  cardInk: '#f7f4ef',
  cardMuted: '#c9c3bc',
  cardLine: 'rgba(255,255,255,0.28)',
  chipBg: 'rgba(190,130,20,0.85)',
  timelineBg: 'rgba(20,16,8,0.9)',
  slotBg: 'rgba(12,10,6,0.88)',
  scrim:
    'linear-gradient(180deg, rgba(0,0,0,0.72) 0%, rgba(0,0,0,0.10) 28%, rgba(0,0,0,0.16) 56%, rgba(0,0,0,0.88) 100%)',
  calloutScrim:
    'linear-gradient(to left, rgba(0,0,0,0.9) 55%, rgba(0,0,0,0.5) 80%, rgba(0,0,0,0) 100%)',
  highlightBg: '#f0b429',
  highlightInk: '#1a1206',
  font: SANS,
  fontMono: MONO,
  motionFrames: 9,
};

/** 新闻播报：深蓝 + 正红，底部实色信息条 */
const news: Omit<Skin, 'geo'> = {
  name: '新闻播报版',
  layout: 'lower',
  bgTop: '#07101f',
  bgBottom: '#03080f',
  decor: 'none',
  vignette: false,
  paperTop: '#f7f9fc',
  paper: '#eef2f7',
  paperBottom: '#e3e9f0',
  paperTexture: 'none',
  paperShadow: '0 10px 30px rgba(0,0,0,0.6)',
  panel: '#0b1830',
  panelRadius: 6,
  cardRadius: 6,
  ink: '#08101f',
  onMedia: '#ffffff',
  mutedInk: 'rgba(255,255,255,0.8)',
  codeInk: 'rgba(255,255,255,0.72)',
  white: '#ffffff',
  gray: 'rgba(255,255,255,0.6)',
  grayDim: 'rgba(255,255,255,0.4)',
  accent: '#c8102e',
  accentSoft: '#ff3b52',
  onAccent: '#ffffff',
  teal: '#5aa9e6',
  cardWhite: 'rgba(7,16,32,0.88)',
  cardInk: '#ffffff',
  cardMuted: '#c3cede',
  cardLine: 'rgba(255,255,255,0.3)',
  chipBg: 'rgba(200,16,46,0.9)',
  timelineBg: 'rgba(8,20,40,0.92)',
  slotBg: 'rgba(6,14,30,0.9)',
  scrim:
    'linear-gradient(180deg, rgba(0,0,0,0.62) 0%, rgba(0,0,0,0.06) 30%, rgba(0,0,0,0.22) 58%, rgba(2,6,14,0.94) 100%)',
  calloutScrim:
    'linear-gradient(to left, rgba(2,7,16,0.95) 55%, rgba(2,7,16,0.6) 80%, rgba(2,7,16,0) 100%)',
  highlightBg: '#c8102e',
  highlightInk: '#ffffff',
  font: SANS,
  fontMono: MONO,
  motionFrames: 5,
};

/** 复古人文：米黄纸 + 陶土红 + 重颗粒 + 暗角 */
const retro: Omit<Skin, 'geo'> = {
  name: '复古人文版',
  layout: 'editorial',
  bgTop: '#2a231a',
  bgBottom: '#1b1610',
  decor: 'grain',
  vignette: true,
  paperTop: '#f4ead6',
  paper: '#ece0c9',
  paperBottom: '#e0d0b3',
  paperTexture: 'grain',
  paperShadow: '0 10px 30px rgba(0,0,0,0.6)',
  panel: '#2c2519',
  panelRadius: 10,
  cardRadius: 8,
  ink: '#2b2419',
  onMedia: '#f2e8d5',
  mutedInk: '#b3a68c',
  codeInk: '#c4b79c',
  white: '#f2e8d5',
  gray: '#a1927a',
  grayDim: '#7d7060',
  accent: '#b3542e',
  accentSoft: '#d07a4e',
  onAccent: '#faf3e6',
  teal: '#8fa37a',
  cardWhite: '#f5ecd8',
  cardInk: '#2b2419',
  cardMuted: '#6b5d47',
  cardLine: '#c3b294',
  chipBg: 'rgba(120,70,30,0.82)',
  timelineBg: 'rgba(60,45,25,0.9)',
  slotBg: 'rgba(45,34,20,0.86)',
  scrim: 'rgba(20,15,8,0.62)',
  calloutScrim:
    'linear-gradient(to left, rgba(20,14,8,0.95) 55%, rgba(20,14,8,0.55) 80%, rgba(20,14,8,0) 100%)',
  highlightBg: '#2b2419',
  highlightInk: '#f5ecd8',
  font: SERIF,
  fontMono: MONO,
  motionFrames: 9,
};

/** 竖屏满屏：旧版 portrait，保留兼容（骨架等同 bleed，配色沿用旧默认） */
const portrait: Omit<Skin, 'geo'> = {
  ...bleed,
  name: '竖屏满屏',
  accent: '#a44231',
  accentSoft: '#c14f35',
  onAccent: '#f7f2ec',
  teal: '#7fd4c9',
  chipBg: 'rgba(120,40,20,0.82)',
  highlightBg: '#a44231',
  highlightInk: '#ffffff',
  motionFrames: 9,
};

/** 智谷三段式：顶带大标题 / 中段近白舞台 / 底带字幕，三段全程钉死 */
const zhigu: Omit<Skin, 'geo'> = {
  name: '智谷三段式',
  layout: 'zhigu',
  bgTop: '#0c0f14',
  bgBottom: '#0c0f14',
  decor: 'none',
  vignette: false,
  paperTop: '#ffffff',
  paper: '#ffffff',
  paperBottom: '#f2f1ed',
  paperTexture: 'none',
  paperShadow: '0 18px 44px rgba(0,0,0,0.45)',
  panel: '#ffffff',
  panelRadius: 20,
  cardRadius: 16,
  ink: '#171a20',
  onMedia: '#ffffff',
  mutedInk: '#5c6470',
  codeInk: '#8a93a1',
  white: '#ffffff',
  gray: '#aab2bd',
  grayDim: '#6d7684',
  accent: '#ffd93d',
  accentSoft: '#ffe680',
  onAccent: '#171a20',
  teal: '#34d399',
  cardWhite: '#ffffff',
  cardInk: '#171a20',
  cardMuted: '#5c6470',
  cardLine: '#e7e5dd',
  chipBg: 'rgba(255,217,61,0.92)',
  timelineBg: '#171a20',
  slotBg: '#f0efe9',
  scrim: 'linear-gradient(180deg, rgba(6,8,12,0.55), rgba(6,8,12,0.15) 40%, rgba(6,8,12,0.75))',
  calloutScrim: 'linear-gradient(180deg, rgba(6,8,12,0.7), rgba(6,8,12,0.2))',
  highlightBg: '#ffd93d',
  highlightInk: '#171a20',
  font: SANS,
  fontMono: MONO,
  motionFrames: 5,
};

/** 大字报：黑底 + 荧光黄 + 左对齐超大字，一句一屏，冲击力优先 */
const poster: Omit<Skin, 'geo'> = {
  name: '大字报版',
  layout: 'poster',
  bgTop: '#0d0d0f',
  bgBottom: '#0d0d0f',
  decor: 'none',
  vignette: false,
  pageBg: '#0d0d0f',
  barBg: 'rgba(13,13,15,0.88)',
  paperTop: '#141416',
  paper: '#141416',
  paperBottom: '#101012',
  paperTexture: 'none',
  paperShadow: 'none',
  panel: '#141416',
  panelRadius: 4,
  cardRadius: 4,
  ink: '#f4f4f6',
  onMedia: '#ffffff',
  mutedInk: '#b9bac2',
  codeInk: '#8d8f99',
  white: '#ffffff',
  gray: '#a9aab3',
  grayDim: '#7c7e88',
  accent: '#ffd400',
  accentSoft: '#ffe457',
  onAccent: '#101014',
  teal: '#4ea8ff',
  cardWhite: '#141416',
  cardInk: '#f4f4f6',
  cardMuted: '#a9aab3',
  cardLine: '#2a2b30',
  chipBg: 'rgba(255,212,0,0.92)',
  timelineBg: '#1a1b1f',
  slotBg: '#1a1b1f',
  scrim: 'rgba(10,10,12,0.62)',
  calloutScrim: 'rgba(10,10,12,0.72)',
  highlightBg: '#ffd400',
  highlightInk: '#101014',
  font: SANS,
  fontMono: MONO,
  motionFrames: 5,
};

/** 数据面板：浅色仪表盘 + 左数据右素材的双栏，全是深色/细节版式里唯一的亮底 */
const data: Omit<Skin, 'geo'> = {
  name: '数据面板版',
  layout: 'data',
  bgTop: '#eceff4',
  bgBottom: '#e4e8ef',
  decor: 'none',
  vignette: false,
  pageBg: '#e9edf3',
  barBg: 'rgba(20,24,31,0.90)',
  barSubBg: 'rgba(20,24,31,0.88)',
  paperTop: '#ffffff',
  paper: '#f7f8fa',
  paperBottom: '#eef1f5',
  paperTexture: 'none',
  paperShadow: '0 8px 26px rgba(24,32,48,0.10)',
  panel: '#ffffff',
  panelRadius: 20,
  cardRadius: 10,
  ink: '#14181f',
  onMedia: '#ffffff',
  mutedInk: '#5b6472',
  codeInk: '#7a8494',
  white: '#ffffff',
  gray: '#5b6472',
  grayDim: '#7a8494',
  accent: '#2f6fed',
  accentSoft: '#6b9bff',
  onAccent: '#ffffff',
  teal: '#16a34a',
  cardWhite: '#ffffff',
  cardInk: '#14181f',
  cardMuted: '#5b6472',
  cardLine: '#d8dde6',
  chipBg: 'rgba(47,111,237,0.12)',
  timelineBg: '#eef1f5',
  slotBg: '#f1f4f8',
  scrim: 'rgba(20,24,31,0.45)',
  calloutScrim: 'rgba(20,24,31,0.55)',
  highlightBg: '#2f6fed',
  highlightInk: '#ffffff',
  font: SANS,
  fontMono: MONO,
  motionFrames: 6,
};

/** macro：宏观棱镜复刻——暗背景 + 金色数据工作室，金色是唯一强调色 */
const macro: Omit<Skin, 'geo'> = {
  name: '宏观棱镜版',
  layout: 'macro',
  bgTop: '#04080a',
  bgBottom: '#04080a',
  decor: 'none',
  vignette: false,
  paperTop: '#0a1113',
  paper: '#081012',
  paperBottom: '#060b0d',
  paperTexture: 'none',
  paperShadow: 'none',
  panel: '#081012',
  panelRadius: 6,
  cardRadius: 6,
  ink: '#f2f4f3',
  onMedia: '#ffffff',
  mutedInk: 'rgba(255,255,255,0.55)',
  codeInk: 'rgba(255,255,255,0.6)',
  white: '#ffffff',
  gray: 'rgba(255,255,255,0.55)',
  grayDim: 'rgba(255,255,255,0.38)',
  accent: '#e8a833',
  accentSoft: '#f2bd5c',
  onAccent: '#12100a',
  teal: '#3fbfae',
  cardWhite: 'rgba(5,10,11,0.55)',
  cardInk: '#f2f4f3',
  cardMuted: 'rgba(255,255,255,0.55)',
  cardLine: 'rgba(255,255,255,0.45)',
  chipBg: 'rgba(232,168,51,0.92)',
  timelineBg: 'rgba(5,10,11,0.8)',
  slotBg: 'rgba(8,16,18,0.85)',
  scrim: 'rgba(2,7,8,0.86)',
  calloutScrim: 'rgba(2,7,8,0.7)',
  highlightBg: '#e8a833',
  highlightInk: '#12100a',
  font: SANS,
  fontMono: MONO,
  motionFrames: 6,
};

const GEOMETRY = LAYOUTS as unknown as Record<string, Geo>;

/** 取某个模板的版式几何：优先按模板 id，其次按骨架，最后回落 editorial */
function buildGeo(id: string, layout: string): Geo {
  const geo: Geo = {...(GEOMETRY[id] ?? GEOMETRY[layout] ?? GEOMETRY.editorial)};
  if (geo.panel && geo.mediaWin) {
    geo.mediaRect = {
      left: geo.panel.left + geo.mediaWin.left,
      top: geo.panel.top + geo.mediaWin.top,
      width: geo.mediaWin.width,
      height: geo.mediaWin.height,
    };
  }
  return geo;
}

export const SKINS: Record<string, Skin> = Object.fromEntries(
  Object.entries({editorial, finance, minimal, bleed, news, retro, portrait, zhigu, poster, data, macro}).map(
    ([id, s]) => [id, {...s, geo: buildGeo(id, s.layout)}],
  ),
) as Record<string, Skin>;

/** 旧 format 别名 → 新模板 id */
export const FORMAT_ALIAS: Record<string, string> = {
  portrait_editorial: 'editorial',
  portrait_full: 'portrait',
};

export function resolveSkin(template?: string): Skin {
  if (!template) return editorial;
  const key = FORMAT_ALIAS[template] ?? template;
  return SKINS[key] ?? editorial;
}

/**
 * T：模块级可变 token 表。组件直接读 T.xxx，渲染入口按皮肤赋值。
 * red / redBright 是历史别名，等同 accent / accentSoft。
 */
export const T: Skin & {red: string; redBright: string} = {
  ...(SKINS.editorial as Skin),
  red: editorial.accent,
  redBright: editorial.accentSoft,
};

export function applySkin(skin: Skin): void {
  Object.assign(T, skin);
  T.red = skin.accent;
  T.redBright = skin.accentSoft;
  // 供非 React 的遗留代码读取
  (globalThis as unknown as {__motionFrames: number}).__motionFrames = skin.motionFrames;
}
