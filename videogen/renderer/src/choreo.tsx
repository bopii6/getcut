import React from 'react';
import {Easing, Img, interpolate, Loop, spring, Video} from 'remotion';
import {T} from './skin';
import {heavy, Tick, useAnimFrame, hideMedia} from './anim';

/**
 * 编舞引擎（choreo）：把"开场/金句怎么出场"从一套死编排变成一份可以现场编的谱。
 *
 * - 词汇表（EL）：每种元素只允许出现在它设计过的锚位（slot），只允许搭配调过的入场（enter）。
 *   丑的可能性被排除在词汇表之外——谱子再怎么变，每个出场元素都是设计过的样子。
 * - 谱（cues）：[{el, text, slot, enter, at, ...参数}]，at 是出场帧（动效帧轴）。
 * - 校验（sanitizeChoreo）：不认识的元素/动效/锚位一律剔除或回落默认，谱废了返回 null，
 *   调用方回落到老版死编排。渲染永远能出片。
 */

export type Cue = {
  el: string;
  text?: string;
  slot?: string;
  enter?: string;
  at: number;
  /** 尺寸档位（big/line/vbar/rule 各自解释） */
  size?: string;
  len?: string;
  thick?: string;
  tone?: string;
  /** line 元素的堆叠行号 0-2 */
  row?: number;
};

// ---------------- 词汇表 ----------------

const P = 52; // 面板内边距

type ElDef = {
  slots: string[];
  enters: string[];
  slot: string;
  enter: string;
};

const EL: Record<string, ElDef> = {
  // 竖向色条（杂志脊线）
  vbar: {
    slots: ['top-left', 'top-center', 'top-right', 'bottom-left', 'bottom-center', 'bottom-right'],
    enters: ['growH', 'drop', 'rise', 'fade'],
    slot: 'top-center',
    enter: 'growH',
  },
  // 横向强调线
  rule: {
    slots: ['mid-left', 'center', 'mid-right', 'low-left', 'low-right',
            'bottom-left', 'bottom-center', 'bottom-right',
            'media-top-left', 'media-top-right', 'media-bottom-left', 'media-bottom-right'],
    enters: ['growW', 'wipeL', 'wipeR', 'fade'],
    slot: 'mid-left',
    enter: 'growW',
  },
  // 小标签（色标+短语）
  kicker: {
    slots: ['top-left', 'top-center', 'top-right', 'mid-left', 'mid-right',
            'low-left', 'low-right', 'bottom-left', 'bottom-right',
            'media-top-left', 'media-top-right', 'media-bottom-left', 'media-bottom-right'],
    enters: ['rise', 'fade', 'slideL', 'slideR', 'drop'],
    slot: 'top-left',
    enter: 'rise',
  },
  // 超大题眼
  big: {
    slots: ['center', 'mid-left', 'mid-right', 'low-left', 'low-right',
            'bottom-left', 'bottom-center', 'bottom-right'],
    enters: ['blurIn', 'pop', 'wipeL', 'slideL', 'slideR', 'rise', 'drop'],
    slot: 'center',
    enter: 'blurIn',
  },
  // 中号一行字（目录/导语行）
  line: {
    slots: ['mid-left', 'center', 'low-left', 'mid-right', 'low-right',
            'bottom-left', 'bottom-right', 'bottom-center'],
    enters: ['rise', 'slideL', 'slideR', 'wipeL', 'fade', 'pop'],
    slot: 'mid-left',
    enter: 'rise',
  },
  // 等宽小字（编号/信号码）
  meta: {
    slots: ['bottom-right', 'bottom-left', 'top-right', 'top-left', 'bottom-center'],
    enters: ['fade', 'slideR', 'slideL', 'rise'],
    slot: 'bottom-right',
    enter: 'fade',
  },
  // 胶囊徽标
  chip: {
    slots: ['top-left', 'top-right', 'mid-left'],
    enters: ['pop', 'fade', 'drop'],
    slot: 'top-left',
    enter: 'pop',
  },
  // 期号/卷号大号等宽字
  issue: {
    slots: ['top-right', 'top-left', 'mid-right'],
    enters: ['fade', 'slideR', 'slideL'],
    slot: 'top-right',
    enter: 'slideR',
  },
  // 装饰点阵
  dots: {
    slots: ['top-right', 'top-left', 'bottom-left', 'bottom-right', 'mid-right'],
    enters: ['fade'],
    slot: 'bottom-right',
    enter: 'fade',
  },
  // 细边框（封面式）
  frame: {
    slots: ['full'],
    enters: ['fade'],
    slot: 'full',
    enter: 'fade',
  },
  // 素材铺满（开场主角：照片/视频）
  photo: {
    slots: ['canvas'],
    enters: ['scaleIn', 'fade'],
    slot: 'canvas',
    enter: 'scaleIn',
  },
  // 压暗层（保证素材上的文字可读）
  scrim: {
    slots: ['canvas'],
    enters: ['fade'],
    slot: 'canvas',
    enter: 'fade',
  },
  // 主角数字（稿子里提取的量级数字，自动适配宽度）
  number: {
    slots: ['center', 'mid-left', 'mid-right', 'low-left'],
    enters: ['blurIn', 'pop', 'rise', 'wipeL'],
    slot: 'center',
    enter: 'blurIn',
  },
};

// ---------------- 校验 ----------------

const clampAt = (v: unknown): number =>
  Math.max(0, Math.min(96, Math.round(typeof v === 'number' && isFinite(v) ? v : 0)));

const pickText = (v: unknown): string | undefined => {
  if (typeof v !== 'string') return undefined;
  const s = v.trim();
  return s ? s.slice(0, 22) : undefined;
};

const pickEnum = <T extends string>(v: unknown, allowed: string[], fallback: T): T =>
  (typeof v === 'string' && allowed.includes(v) ? v : fallback) as T;

/** 校验并清洗一份谱；没有有效 cue 就返回 null（调用方回落死编排）。 */
export function sanitizeChoreo(raw: unknown): Cue[] | null {
  if (!raw || typeof raw !== 'object') return null;
  const cuesRaw = (raw as {cues?: unknown}).cues;
  if (!Array.isArray(cuesRaw)) return null;
  const cues: Cue[] = [];
  for (const r of cuesRaw.slice(0, 12)) {
    if (!r || typeof r !== 'object') continue;
    const o = r as Record<string, unknown>;
    const def = EL[String(o.el)];
    if (!def) continue;
    cues.push({
      el: String(o.el),
      text: pickText(o.text),
      slot: pickEnum(o.slot, def.slots, def.slot),
      enter: pickEnum(o.enter, def.enters, def.enter),
      at: clampAt(o.at),
      size: pickEnum(o.size, ['L', 'XL', 'XXL'], 'XL'),
      len: pickEnum(o.len, ['S', 'M', 'L'], 'M'),
      thick: pickEnum(o.thick, ['thin', 'thick'], 'thick'),
      tone: pickEnum(o.tone, ['accent', 'white', 'muted', 'teal'], 'accent'),
      row: Math.max(0, Math.min(2, Math.round(Number(o.row) || 0))),
    });
  }
  if (!cues.length) return null;
  cues.sort((a, b) => a.at - b.at);
  return cues;
}

// ---------------- 入场动效 ----------------

const easeOut = Easing.out(Easing.cubic);
const prog = (f: number, at: number, dur: number, from: number, to: number): number =>
  interpolate(f, [at, at + dur], [from, to], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeOut,
  });

type EnterStyle = React.CSSProperties;

/** 每种入场：f=动效帧，at=起跳帧，dur=时长。返回叠加在元素内层的样式。 */
function enterStyle(enter: string, f: number, at: number, dur: number, fps: number,
                    origin: string): EnterStyle {
  switch (enter) {
    case 'fade':
      return {opacity: prog(f, at, dur, 0, 1)};
    case 'rise':
      return {opacity: prog(f, at, dur, 0, 1), transform: `translateY(${prog(f, at, dur, 44, 0)}px)`};
    case 'drop':
      return {opacity: prog(f, at, dur, 0, 1), transform: `translateY(${prog(f, at, dur, -56, 0)}px)`};
    case 'slideL':
      return {opacity: prog(f, at, dur, 0, 1), transform: `translateX(${prog(f, at, dur, -90, 0)}px)`};
    case 'slideR':
      return {opacity: prog(f, at, dur, 0, 1), transform: `translateX(${prog(f, at, dur, 90, 0)}px)`};
    case 'wipeL':
      return {clipPath: `inset(0 ${prog(f, at, dur, 100, 0)}% 0 0)`};
    case 'wipeR':
      return {clipPath: `inset(0 0 0 ${prog(f, at, dur, 100, 0)}%)`};
    case 'wipeUp':
      return {clipPath: `inset(${prog(f, at, dur, 100, 0)}% 0 0 0)`};
    case 'growW':
      return {transform: `scaleX(${prog(f, at, dur, 0, 1)})`, transformOrigin: origin};
    case 'growH':
      return {transform: `scaleY(${prog(f, at, dur, 0, 1)})`, transformOrigin: origin};
    case 'scaleIn': {
      // 素材专用：慢速沉降（略放大→原大），配合快淡入
      const t = prog(f, at, 42, 0, 1);
      return {opacity: Math.min(1, t * 1.8), transform: `scale(${1.08 - 0.08 * t})`};
    }
    case 'blurIn': {
      const t = prog(f, at, dur + 6, 0, 1);
      return {
        opacity: t,
        filter: `blur(${(1 - t) * 14}px)`,
        transform: `scale(${1 + (1 - t) * 0.06})`,
      };
    }
    case 'pop': {
      const s = spring({frame: f - at, fps, config: {damping: 12, stiffness: 170}});
      return {opacity: Math.min(1, s * 1.6), transform: `scale(${0.55 + 0.45 * s})`};
    }
    default:
      return {opacity: prog(f, at, dur, 0, 1)};
  }
}

/** growW/growH 的生长起点跟锚位走：右边锚的从右长，底锚的从底长。 */
function growOrigin(slot: string, enter: string): string {
  if (enter === 'growH') return slot.startsWith('bottom') ? 'bottom' : 'top';
  if (enter === 'growW') {
    if (slot.endsWith('right')) return 'right';
    if (slot === 'center' || slot === 'top-center' || slot === 'bottom-center') return 'center';
    return 'left';
  }
  return 'center';
}

// ---------------- 锚位几何 ----------------

type AnchorStyle = React.CSSProperties;

/**
 * 面板内锚位：外层定位（内层做动效，两层互不干扰）。
 * media 前缀 = 相对媒体窗（footage 镜头的画面窗），其余相对整个面板。
 */
function anchorStyle(slot: string, row: number): AnchorStyle {
  const rowDy = row * 118;
  const base: AnchorStyle = {position: 'absolute'};
  switch (slot) {
    case 'top-left':
      return {...base, left: P, top: 40};
    case 'top-center':
      return {...base, left: '50%', top: 40, transform: 'translateX(-50%)'};
    case 'top-right':
      return {...base, right: P, top: 40};
    case 'mid-left':
      return {...base, left: P, top: `calc(38% + ${rowDy}px)`};
    case 'center':
      return {...base, left: '50%', top: '50%', transform: 'translate(-50%, -50%)'};
    case 'mid-right':
      return {...base, right: P, top: `calc(38% + ${rowDy}px)`, textAlign: 'right'};
    case 'low-left':
      return {...base, left: P, top: `calc(60% + ${rowDy}px)`};
    case 'low-right':
      return {...base, right: P, top: `calc(60% + ${rowDy}px)`, textAlign: 'right'};
    case 'bottom-left':
      return {...base, left: P, bottom: 40};
    case 'bottom-center':
      return {...base, left: '50%', bottom: 40, transform: 'translateX(-50%)'};
    case 'bottom-right':
      return {...base, right: P, bottom: 40};
    case 'full':
      return {...base, inset: 30};
    case 'canvas':
      return {...base, inset: 0};
    // ---- media 窗内锚位（footage 信息层用：压在素材画面上）。
    // 用百分比相对窗口定位：CueView 平移 origin 后，percent 相对窗尺寸解析 ----
    case 'media-top-left':
      return {...base, left: '4%', top: '5%'};
    case 'media-top-right':
      return {...base, left: '96%', top: '5%', transform: 'translateX(-100%)'};
    case 'media-bottom-left':
      return {...base, left: '4%', top: '95%', transform: 'translateY(-100%)'};
    case 'media-bottom-right':
      return {...base, left: '96%', top: '95%', transform: 'translate(-100%, -100%)'};
    default:
      return {...base, left: P, top: 40};
  }
}

// ---------------- 元素渲染 ----------------

const toneColor = (tone: string): string =>
  tone === 'white' ? T.white : tone === 'muted' ? T.mutedInk : tone === 'teal' ? T.teal : T.accentSoft;

const LEN_H = {S: 176, M: 300, L: 500} as const;
const RULE_W = {S: 0.34, M: 0.6, L: 0.86} as const;
const BIG_SIZE = {L: 88, XL: 118, XXL: 170} as const;

/** 宽度估算（@fontSize=100）：CJK 记全宽，其余记 0.56 宽——用来给主角数字定字号 */
const estW100 = (text: string): number => {
  let total = 0;
  for (const ch of text) total += ch.charCodeAt(0) > 0x2e80 ? 100 : 56;
  return total;
};

/** 素材铺满：图直接放，视频循环播放（开场只有几秒，短素材循环才不穿帮） */
const MediaFill: React.FC<{src: string; kind?: 'video' | 'image'; dur: number}> =
    ({src, kind, dur}) => {
  if (kind === 'video') {
    return (
      <Loop durationInFrames={Math.max(1, dur)}>
        <Video src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      </Loop>
    );
  }
  return <Img src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} />;
};

const ElementBody: React.FC<{cue: Cue; w: number; media?: string;
                             mediaKind?: 'video' | 'image'; dur: number}> =
    ({cue, w, media, mediaKind, dur}) => {
  const inner = (w2: number, h: number, bg: string): React.CSSProperties => ({
    width: w2,
    height: h,
    background: bg,
  });
  switch (cue.el) {
    case 'vbar':
      return <div style={inner(cue.thick === 'thin' ? 14 : 26, LEN_H[cue.len as keyof typeof LEN_H], T.accent)} />;
    case 'rule':
      return (
        <div
          style={inner(
            (w - P * 2) * RULE_W[cue.len as keyof typeof RULE_W],
            cue.thick === 'thin' ? 3 : 8,
            cue.tone === 'white' ? T.white : cue.tone === 'teal' ? T.teal : T.accent,
          )}
        />
      );
    case 'kicker':
      return (
        <div style={{display: 'flex', alignItems: 'center'}}>
          <span style={{...Tick, height: 32}} />
          <span style={{...heavy, fontSize: 34, color: T.accentSoft}}>{cue.text}</span>
        </div>
      );
    case 'big': {
      // 尺寸档位是上限，超宽的文案（长金句）按宽度自适应缩小，保证不溢出面板
      const text = cue.text || '';
      const cap = BIG_SIZE[cue.size as keyof typeof BIG_SIZE];
      const fit = ((w - P * 2 - 20) / Math.max(estW100(text), 1)) * 100;
      return (
        <div style={{...heavy, fontSize: Math.min(cap, Math.max(40, fit)), color: toneColor(cue.tone || 'accent'), lineHeight: 1.12, whiteSpace: 'nowrap'}}>
          {text}
        </div>
      );
    }
    case 'line': {
      const text = cue.text || '';
      const fit = ((w - P * 2 - 20) / Math.max(estW100(text), 1)) * 100;
      return (
        <div style={{...heavy, fontSize: Math.min(54, Math.max(30, fit)), color: cue.tone === 'accent' ? T.accentSoft : T.white, whiteSpace: 'nowrap'}}>
          {text}
        </div>
      );
    }
    case 'meta':
      return (
        <div style={{fontSize: 26, color: T.codeInk, letterSpacing: 2, fontFamily: T.fontMono, whiteSpace: 'nowrap'}}>
          {cue.text}
        </div>
      );
    case 'chip':
      return (
        <div
          style={{
            background: T.accent,
            color: T.onAccent,
            fontSize: 24,
            padding: '8px 22px',
            borderRadius: 26,
            ...heavy,
          }}
        >
          {cue.text}
        </div>
      );
    case 'issue':
      return (
        <div style={{fontSize: 42, color: T.gray, letterSpacing: 6, fontFamily: T.fontMono, whiteSpace: 'nowrap'}}>
          {cue.text}
        </div>
      );
    case 'dots':
      return (
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(6, 7px)', gap: 16}}>
          {Array.from({length: 24}).map((_, i) => (
            <div key={i} style={{width: 7, height: 7, borderRadius: 4, background: T.grayDim, opacity: 0.65}} />
          ))}
        </div>
      );
    case 'frame':
      return <div style={{position: 'absolute', inset: 0, border: `2px solid ${T.cardLine}`}} />;
    case 'photo':
      // 分轨导出的卡片层不放素材（媒体在底板/画面轨），回落纯色板
      return media && !hideMedia()
        ? <MediaFill src={media} kind={mediaKind} dur={dur} />
        : <div style={{position: 'absolute', inset: 0, background: T.panel}} />;
    case 'scrim':
      if (hideMedia()) return null;
      return (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background:
              'linear-gradient(to bottom, rgba(10,8,6,0.55) 0%, rgba(10,8,6,0.45) 45%, rgba(10,8,6,0.82) 100%)',
          }}
        />
      );
    case 'number': {
      const text = cue.text || '';
      const maxW = w - P * 2 - 20;
      const size = Math.min(168, Math.max(64, (maxW / Math.max(estW100(text), 1)) * 100));
      return (
        <div style={{...heavy, fontSize: size, color: toneColor(cue.tone || 'white'), lineHeight: 1.05, whiteSpace: 'nowrap'}}>
          {text}
        </div>
      );
    }
    default:
      return null;
  }
};

const CueView: React.FC<{cue: Cue; w: number; fps: number; media?: string;
                         mediaKind?: 'video' | 'image'; dur: number;
                         origin?: {left: number; top: number; width: number; height: number}}> =
    ({cue, w, fps, media, mediaKind, dur: shotDur, origin}) => {
  const f = useAnimFrame();
  const dur = cue.enter === 'blurIn' ? 18 : 13;
  const st = enterStyle(cue.enter || 'fade', f, cue.at, dur, fps, growOrigin(cue.slot || '', cue.enter || ''));
  const anchor = anchorStyle(cue.slot || 'top-left', cue.row || 0);
  // media-* 锚位：元素坐标系换到媒体窗（origin=窗的 left/top + width/height，
  // 百分比 left/top 换算成窗内像素，translate 的入场动效保留在外层 transform 之外）
  if (origin && (cue.slot || '').startsWith('media-')) {
    // 右侧锚位靠 translateX(-100%) 反推，元素必须保持自然宽度，否则会被
    // 剩余空间压成竖排窄条
    anchor.width = 'max-content';
    anchor.whiteSpace = 'nowrap';
    // left 按窗宽换算，top 按窗高换算
    const pct = (v: string, base: number): number => {
      const m = /(-?[\d.]+)%/.exec(v);
      return m ? (parseFloat(m[1]) / 100) * base : 0;
    };
    const l = anchor.left;
    const t = anchor.top;
    if (typeof l === 'string' && l.includes('%')) anchor.left = pct(l, origin.width) + origin.left;
    else if (typeof l === 'number') anchor.left = l + origin.left;
    if (typeof t === 'string' && t.includes('%')) anchor.top = pct(t, origin.height) + origin.top;
    else if (typeof t === 'number') anchor.top = t + origin.top;
    // 右/底对齐的 translate 语义保留（相对元素自身尺寸），无需改
  }
  // canvas/full 铺满型：内层要撑满锚位盒子，否则带 transform 的入场会让 absolute 子元素塌成 0 尺寸
  const fill = cue.slot === 'canvas' || cue.slot === 'full'
    ? {width: '100%', height: '100%', position: 'absolute' as const, inset: 0}
    : undefined;
  return (
    <div style={anchor}>
      <div style={{...st, ...fill}}>
        <ElementBody cue={cue} w={w} media={media} mediaKind={mediaKind} dur={shotDur} />
      </div>
    </div>
  );
};

// 点阵的逐点浮现（stagger）单独处理：整体 fade 里再按序号补延迟
const DotsCue: React.FC<{cue: Cue}> = ({cue}) => {
  const f = useAnimFrame();
  return (
    <div style={anchorStyle(cue.slot || 'bottom-right', 0)}>
      <div style={{display: 'grid', gridTemplateColumns: 'repeat(6, 7px)', gap: 16}}>
        {Array.from({length: 24}).map((_, i) => (
          <div
            key={i}
            style={{
              width: 7,
              height: 7,
              borderRadius: 4,
              background: T.grayDim,
              opacity: interpolate(f, [cue.at + i * 1.1, cue.at + 10 + i * 1.1], [0, 0.65], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              }),
            }}
          />
        ))}
      </div>
    </div>
  );
};

// ---------------- 谱 → 画面 ----------------

/** 编舞卡：把一份谱画成整屏。媒体背景由 media/mediaKind 带入（开场主角素材）。
 * mediaOrigin = 媒体窗的位置和尺寸——media-* 锚位的元素挂进窗里（footage 信息层）。
 * bare = 信息层模式：不画底色板，只画谱里的元素（footage 镜头叠加在媒体窗之上）。 */
export const ChoreoCard: React.FC<{cues: Cue[]; fps: number; media?: string;
                                   mediaKind?: 'video' | 'image'; dur: number;
                                   mediaOrigin?: {left: number; top: number; width: number; height: number};
                                   bare?: boolean}> =
    ({cues, fps, media, mediaKind, dur, mediaOrigin, bare}) => {
  const geo = T.geo?.panel || {width: 849, height: 844};
  return (
    <div style={{position: 'absolute', inset: 0, overflow: 'hidden',
                 background: bare ? 'transparent' : T.panel}}>
      {cues.map((c, i) =>
        c.el === 'dots'
          ? <DotsCue key={i} cue={c} />
          : <CueView key={i} cue={c} w={geo.width} fps={fps}
                     media={media} mediaKind={mediaKind} dur={dur} origin={mediaOrigin} />,
      )}
    </div>
  );
};
