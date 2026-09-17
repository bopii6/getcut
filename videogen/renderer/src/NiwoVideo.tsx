import React from 'react';
import {
  AbsoluteFill,
  Img,
  continueRender,
  delayRender,
  interpolate,
  Loop,
  Sequence,
  staticFile,
  Video,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {T, resolveSkin, applySkin, type Skin} from './skin';

// ---------------- tokens ----------------
// T 与皮肤定义在 ./skin，渲染入口按 props.template 调 applySkin 赋值。

/**
 * 字体清单。weight 写成区间（100 900）表示「这个字面覆盖所有字重」，
 * 这样组件里沿用 fontWeight:900 也不会触发浏览器伪粗体，细体字面能保持细。
 */
const FONTS: {family: string; file: string; weight: string; loadWeight: string}[] = [
  {family: 'SSH', file: 'fonts/SourceHanSansCN-Heavy.otf', weight: '900', loadWeight: '900'},
  {family: 'SSHSerif', file: 'fonts/NotoSerifSC-Bold.otf', weight: '100 900', loadWeight: '400'},
  {family: 'SSHLight', file: 'fonts/NotoSansSC-Light.otf', weight: '100 900', loadWeight: '300'},
];

const FontFace: React.FC = () => {
  const [handle] = React.useState(() => delayRender('loading font'));
  // 只等当前皮肤真正用到的那一款，避免每次渲染都拖三份 CJK 字体
  const used = FONTS.filter((f) => (T.font || '').includes(f.family));
  React.useEffect(() => {
    const list = used.length ? used : [FONTS[0]];
    Promise.all(list.map((f) => document.fonts.load(`${f.loadWeight} 64px '${f.family}'`)))
      .then(() => continueRender(handle))
      .catch(() => continueRender(handle));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <style
      dangerouslySetInnerHTML={{
        __html: FONTS.map(
          (f) =>
            `@font-face { font-family: '${f.family}'; src: url('${staticFile(f.file)}') ` +
            `format('opentype'); font-weight: ${f.weight}; font-display: block; }`,
        ).join('\n'),
      }}
    />
  );
};

// ---------------- props types ----------------
export type Clause = {text: string; startMs: number; endMs: number};
export type ShotOverlay = {
  variant?: 'pace' | 'compare' | 'fact' | 'statement';
  label?: string;
  title?: string;
  subtitle?: string;
  number?: string;
  caption?: string;
  badge?: string;
  rightNote?: string;
  left?: {head: string; body: string};
  right?: {head: string; body: string};
  card?: {title: string; body: string};
  rows?: {code: string; text: string}[];
};
export type Shot = {
  kind: 'title_card' | 'quote_card' | 'footage' | 'callout' | 'panel';
  media?: string;
  mediaKind?: 'video' | 'image';
  startMs: number;
  endMs: number;
  chapterLabel?: string;
  code?: string;
  overlay?: ShotOverlay;
};
export type NiwoProps = {
  durationInFrames: number;
  accent?: string;
  accentSoft?: string;
  stylePack?: string;   // data/profile/investigation/opinion — 决定动效强度与默认色
  headline: {lines: {text: string; highlight?: string}[]};
  sources: string[];
  disclaimer: string;
  showSubtitles?: boolean;
  /** 模板 id：editorial / finance / minimal / bleed / news / retro / portrait */
  template?: string;
  shots: Shot[];
  clauses: Clause[];
  /**
   * 分轨草稿导出模式：card=只出卡片/包装层（文字转剪映文本轨），base=只出底板层。
   * 供剪映草稿分层合成。
   */
  exportMode?: ExportMode;
  /** @deprecated 旧字段，等价于 exportMode="card" */
  chromeOnly?: boolean;
  /** 分轨导出：文字测量结果回传地址（Node 侧小 HTTP 服务） */
  probeUrl?: string;
  /** 测量结果的分组标签（通常是镜头 id） */
  probeTag?: string;
};

export const estW = (text: string, size: number) => {
  let w = 0;
  for (const ch of text) w += ch.charCodeAt(0) > 0x2e80 ? size : size * 0.56;
  return w;
};
const fitSize = (text: string, maxSize: number, maxW: number) =>
  Math.min(maxSize, Math.max(20, (maxW / Math.max(estW(text, maxSize), 1)) * maxSize));

const msToF = (ms: number, fps: number) => Math.round((ms / 1000) * fps);

// ---------------- 分轨导出（exportMode） ----------------
// full：正常成片
// card：只出「卡片/包装」层（页面底/纸卡/面板/页脚不出，素材与字幕不出，文字只留几何位置）
// base：只出「底板」层（页面底/纸卡/面板留洞/标题带/页脚，镜头内容与字幕不出）
// 剪映草稿的轨道顺序（下→上）：底板 → 画面 → 卡片 → 字幕 → 叠加文字
export type ExportMode = 'full' | 'card' | 'base';
let EXPORT_MODE: ExportMode = 'full';
const setExportMode = (m: ExportMode) => {
  EXPORT_MODE = m;
};
/** 素材/字幕是否隐藏（分轨导出时） */
const hideMedia = () => EXPORT_MODE !== 'full';
const isCard = () => EXPORT_MODE === 'card';
const isBase = () => EXPORT_MODE === 'base';
/** 内层面板几何：与 EditorialVideo 中的面板 rect 保持一致 */
const PANEL_RECT = {left: 115, top: 596, width: 849, height: 844, radius: 16};
/** 面板内媒体窗几何（ShotView 用）：相对面板左上角 */
const MEDIA_WINDOW = {left: 36, top: 71, width: 778, height: 440};
/** 媒体窗在整帧里的 rect（= 面板 rect + 窗口相对偏移）：素材轨的落点 */
export const MEDIA_RECT = {
  left: PANEL_RECT.left + MEDIA_WINDOW.left,
  top: PANEL_RECT.top + MEDIA_WINDOW.top,
  width: MEDIA_WINDOW.width,
  height: MEDIA_WINDOW.height,
};
/** 纸卡 rect（editorial 版面） */
const PAPER_RECT = {left: 91, top: 124, width: 892, height: 1432, radius: 26};

type Rect = {left: number; top: number; width: number; height: number};

/** 全帧坐标 -> clip-path polygon(evenodd) 字符串：整块挖掉 hole 矩形 */
const holeClip = (frameW: number, frameH: number, hole: Rect) =>
  `polygon(evenodd, 0 0, ${frameW}px 0, ${frameW}px ${frameH}px, 0 ${frameH}px, 0 0, ` +
  `${hole.left}px ${hole.top}px, ${hole.left}px ${hole.top + hole.height}px, ` +
  `${hole.left + hole.width}px ${hole.top + hole.height}px, ` +
  `${hole.left + hole.width}px ${hole.top}px, ${hole.left}px ${hole.top}px)`;

/** 分轨导出：把整层按媒体窗挖洞（页面底、纸卡等整层不透明元素用） */
const ChromeClip: React.FC<{hole: Rect; children?: React.ReactNode}> = ({hole, children}) => {
  const {width, height} = useVideoConfig();
  return <AbsoluteFill style={{clipPath: holeClip(width, height, hole)}}>{children}</AbsoluteFill>;
};

/**
 * 带矩形洞的底板：把 hole 之外的部分画成 4 条边带（共用 fill 样式）。
 * 分轨导出时，媒体窗才能透出下层的素材轨。
 */
const RectWithHole: React.FC<{
  rect: Rect;
  hole: Rect;
  radius?: number;
  fill: React.CSSProperties;
  style?: React.CSSProperties;
}> = ({rect, hole, radius = 0, fill, style}) => {
  const hx = hole.left - rect.left;
  const hy = hole.top - rect.top;
  const w = rect.width;
  const h = rect.height;
  const band = (s: React.CSSProperties, key: string) => (
    <div key={key} style={{position: 'absolute', ...fill, ...s}} />
  );
  return (
    <div
      style={{
        position: 'absolute',
        left: rect.left,
        top: rect.top,
        width: w,
        height: h,
        borderRadius: radius,
        overflow: 'hidden',
        ...style,
      }}
    >
      {band({left: 0, top: 0, width: w, height: hy}, 'top')}
      {band({left: 0, top: hy + hole.height, width: w, height: h - hy - hole.height}, 'bottom')}
      {band({left: 0, top: hy, width: hx, height: hole.height}, 'left')}
      {band({left: hx + hole.width, top: hy, width: w - hx - hole.width, height: hole.height}, 'right')}
    </div>
  );
};

// 注意：这两个是模块级常量，但 T 是在渲染时才被 applySkin 改写的。
// 用 getter 而不是普通属性，保证每次展开/读取时取到当前皮肤的值，
// 否则它们会永久固化成 import 那一刻的 editorial 配色与字体。
const heavy: React.CSSProperties = {
  get fontFamily() {
    return T.font;
  },
  get fontWeight() {
    return 900;
  },
};

const Tick: React.CSSProperties = {
  get display() {
    return 'inline-block';
  },
  get width() {
    return 8;
  },
  get height() {
    return 30;
  },
  get background() {
    return T.accent;
  },
  get marginRight() {
    return 14;
  },
};

const Label: React.FC<{text: string; delay?: number}> = ({text, delay = 0}) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [delay, delay + 10], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <div style={{display: 'flex', alignItems: 'center', opacity: o}}>
      <span style={Tick} />
      <span style={{...heavy, fontSize: 30, color: T.accentSoft}}>{text}</span>
    </div>
  );
};

const Badge: React.FC<{text: string; delay?: number}> = ({text, delay = 0}) => {
  const frame = useCurrentFrame();
  const s = interpolate(frame, [delay, delay + 12], [0, 1], {
    extrapolateRight: 'clamp',
    extrapolateLeft: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        top: 30,
        right: 28,
        background: T.accent,
        color: T.onAccent,
        fontSize: 24,
        padding: '6px 20px',
        borderRadius: 22,
        transform: `scale(${s})`,
        ...heavy,
      }}
    >
      {text}
    </div>
  );
};

const RedRule: React.FC<{width: number; delay?: number; style?: React.CSSProperties}> = ({
  width,
  delay = 0,
  style,
}) => {
  const frame = useCurrentFrame();
  const w = interpolate(frame, [delay, delay + 14], [0, width], {
    extrapolateRight: 'clamp',
    extrapolateLeft: 'clamp',
  });
  return <div style={{position: 'absolute', height: 2, background: T.accent, width: w, ...style}} />;
};

// ---------------- designed overlays ----------------
const TitleCard: React.FC<{spec: ShotOverlay; fps: number}> = ({spec, fps}) => {
  const f = useCurrentFrame();
  const w = 849;
  const h = 844;
  const cx = w / 2;
  const barH = interpolate(f, [2, 12], [0, 124], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const ruleW = interpolate(f, [8, 20], [0, w - 72], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const kwO = interpolate(f, [22, 34], [0, 1], {extrapolateRight: 'clamp'});
  const kwY = interpolate(f, [22, 34], [26, 0], {extrapolateRight: 'clamp'});
  const codeO = interpolate(f, [36, 46], [0, 1], {extrapolateRight: 'clamp'});
  const tealW = interpolate(f, [40, 56], [0, 264], {extrapolateRight: 'clamp'});
  const botH = interpolate(f, [46, 58], [0, 94], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0, background: T.panel, overflow: 'hidden'}}>
      <div
        style={{
          position: 'absolute',
          left: cx - 12,
          top: 26,
          width: 24,
          height: barH,
          background: T.accent,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 36,
          top: 178,
          width: ruleW,
          height: 8,
          background: T.accent,
        }}
      />
      <div style={{position: 'absolute', left: 36, top: 224, opacity: kwO}}>
        <div style={{display: 'flex', alignItems: 'center'}}>
          <span style={{...Tick, height: 32}} />
          <span style={{...heavy, fontSize: 34, color: T.accentSoft}}>{spec.label}</span>
        </div>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 52,
          top: 380 + kwY,
          opacity: kwO,
          ...heavy,
          fontSize: 120,
          color: T.accentSoft,
        }}
      >
        {spec.keyword}
      </div>
      <div
        style={{
          position: 'absolute',
          right: 60,
          bottom: 148,
          opacity: codeO,
          fontSize: 26,
          color: T.codeInk,
          letterSpacing: 2,
          fontFamily: T.fontMono,
        }}
      >
        {spec.code}
      </div>
      <div
        style={{
          position: 'absolute',
          left: 36,
          bottom: 147,
          width: tealW,
          height: 3,
          background: T.teal,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: cx - 12,
          bottom: 26,
          width: 24,
          height: botH,
          background: T.accent,
        }}
      />
    </div>
  );
};

const QuoteCard: React.FC<{spec: ShotOverlay}> = ({spec}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [8, 30], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0, background: T.panel, overflow: 'hidden'}}>
      <div style={{position: 'absolute', left: 36, top: 118, display: 'flex', alignItems: 'center'}}>
        <span style={{...Tick, height: 32}} />
        <span style={{...heavy, fontSize: 36, color: T.accentSoft}}>{spec.label}</span>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 52,
          top: 250,
          opacity: o * 0.55,
          ...heavy,
          fontSize: 96,
          color: T.mutedInk,
        }}
      >
        {spec.quote}
      </div>
    </div>
  );
};

const NumberCallout: React.FC<{spec: ShotOverlay}> = ({spec}) => {
  const f = useCurrentFrame();
  const barH = interpolate(f, [4, 12], [0, 240], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const numO = interpolate(f, [10, 22], [0, 1], {extrapolateRight: 'clamp'});
  const numX = interpolate(f, [10, 22], [30, 0], {extrapolateRight: 'clamp'});
  const capO = interpolate(f, [20, 30], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        width: '46%',
        background: T.calloutScrim,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 40,
          width: 8,
          height: barH,
          background: T.accent,
        }}
      />
      <div style={{position: 'absolute', left: 34, top: 44}}>
        <div style={{...heavy, fontSize: 32, color: T.accentSoft}}>{spec.label}</div>
        <div
          style={{
            ...heavy,
            fontSize: 84, whiteSpace: 'nowrap',
            color: T.white,
            opacity: numO,
            transform: `translateX(${numX}px)`,
            marginTop: 8,
          }}
        >
          {spec.number}
        </div>
        <div style={{fontSize: 26, color: T.mutedInk, opacity: capO, marginTop: 6}}>
          — {spec.caption}
        </div>
      </div>
    </div>
  );
};

const PacePanel: React.FC<{spec: ShotOverlay}> = ({spec}) => {
  const f = useCurrentFrame();
  const tO = interpolate(f, [4, 14], [0, 1], {extrapolateRight: 'clamp'});
  const cardY = interpolate(f, [12, 24], [40, 0], {extrapolateRight: 'clamp'});
  const cardO = interpolate(f, [12, 24], [0, 1], {extrapolateRight: 'clamp'});
  const lineW = interpolate(f, [26, 44], [0, 640], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const check = interpolate(f, [46, 56], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0, background: T.scrim}}>
      <div style={{position: 'absolute', left: 36, top: 30, opacity: tO}}>
        <div style={{...heavy, fontSize: 72, color: T.white}}>{spec.title}</div>
        <div style={{fontSize: 30, color: T.mutedInk, marginTop: 8}}>{spec.subtitle}</div>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 36,
          right: 36,
          top: 210 + cardY,
          height: 180,
          background: T.cardWhite,
          borderRadius: 14,
          opacity: cardO,
          padding: '26px 30px',
        }}
      >
        <div style={{display: 'flex', gap: 16}}>
          <span style={{...heavy, fontSize: 26, color: T.onAccent, background: T.accent, padding: '6px 20px', borderRadius: 20}}>
            {spec.pillA}
          </span>
          <span style={{...heavy, fontSize: 26, color: T.cardMuted, border: `2px solid ${T.cardLine}`, padding: '4px 18px', borderRadius: 20}}>
            {spec.pillB}
          </span>
        </div>
        <div style={{marginTop: 22, height: 12, width: 420, background: T.cardLine, borderRadius: 6}} />
        <div style={{position: 'relative', marginTop: 20}}>
          <div style={{height: 4, width: lineW, background: T.accent, borderRadius: 2}} />
          <div
            style={{
              position: 'absolute',
              right: 0,
              top: -26,
              width: 56,
              height: 56,
              borderRadius: 28,
              border: `3px solid ${T.red}`,
              opacity: check,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: T.red,
              fontSize: 34,
              ...heavy,
            }}
          >
            ✓
          </div>
        </div>
      </div>
    </div>
  );
};

const ComparePanel: React.FC<{spec: ShotOverlay}> = ({spec}) => {
  const f = useCurrentFrame();
  const tO = interpolate(f, [4, 14], [0, 1], {extrapolateRight: 'clamp'});
  const colO = interpolate(f, [24, 36], [0, 1], {extrapolateRight: 'clamp'});
  const ruleW = interpolate(f, [34, 50], [0, 320], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0, background: T.scrim}}>
      <div style={{position: 'absolute', left: 36, top: 30, display: 'flex', alignItems: 'center', opacity: tO}}>
        <span style={Tick} />
        <span style={{...heavy, fontSize: 30, color: T.accentSoft}}>{spec.label}</span>
      </div>
      <div style={{position: 'absolute', left: 34, top: 84, opacity: tO, ...heavy, fontSize: 64, color: T.accentSoft}}>
        {spec.title}
      </div>
      <div style={{position: 'absolute', left: 36, top: 168, fontSize: 28, color: T.white, opacity: tO}}>
        {spec.subtitle}
      </div>
      {spec.badge ? <Badge text={spec.badge} delay={18} /> : null}
      {([
        {x: 30, d: spec.left},
        {x: 30 + 334 + 30, d: spec.right},
      ] as const).map((col, ci) => (
        <div
          key={ci}
          style={{
            position: 'absolute',
            left: col.x,
            top: 218,
            width: 334,
            height: 190,
            background: T.slotBg,
            border: `2px solid ${T.accentSoft}`,
            borderRadius: 10,
            opacity: colO,
            padding: '16px 20px',
          }}
        >
          <div style={{...heavy, fontSize: 27, color: T.accentSoft}}>{col.d?.head}</div>
          <div style={{fontSize: 25, color: T.white, marginTop: 8, lineHeight: 1.35}}>
            {col.d?.body}
          </div>
          <div
            style={{
              position: 'absolute',
              left: 20,
              bottom: 16,
              width: ruleW / 2,
              height: 2,
              background: T.accent,
            }}
          />
        </div>
      ))}
    </div>
  );
};

const FactPanel: React.FC<{spec: ShotOverlay}> = ({spec}) => {
  const f = useCurrentFrame();
  const cardY = interpolate(f, [10, 22], [36, 0], {extrapolateRight: 'clamp'});
  const cardO = interpolate(f, [10, 22], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0, background: T.scrim}}>
      <div style={{position: 'absolute', left: 36, top: 30, display: 'flex', alignItems: 'center'}}>
        <span style={Tick} />
        <span style={{...heavy, fontSize: 30, color: T.accentSoft}}>{spec.label}</span>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 30,
          right: 200,
          top: 110 + cardY,
          background: T.cardWhite,
          borderRadius: 12,
          opacity: cardO,
          padding: '26px 30px',
        }}
      >
        <div style={{...heavy, fontSize: 40, color: T.cardInk}}>{spec.card?.title}</div>
        <div style={{fontSize: 26, color: T.cardMuted, marginTop: 14, lineHeight: 1.4}}>
          {spec.card?.body}
        </div>
      </div>
    </div>
  );
};

const StatementPanel: React.FC<{spec: ShotOverlay}> = ({spec}) => {
  const f = useCurrentFrame();
  const tO = interpolate(f, [4, 14], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0, background: T.scrim}}>
      <div style={{position: 'absolute', left: 36, top: 30, opacity: tO}}>
        <div style={{...heavy, fontSize: 64, color: T.white}}>{spec.title}</div>
        <div style={{fontSize: 28, color: T.mutedInk, marginTop: 10}}>{spec.subtitle}</div>
      </div>
      {spec.rightNote ? (
        <div style={{position: 'absolute', right: 40, top: 190, ...heavy, fontSize: 30, color: T.accentSoft}}>
          {spec.rightNote}
        </div>
      ) : null}
      {(spec.rows ?? []).map((row, i) => {
        const d = 20 + i * 14;
        const o = interpolate(f, [d, d + 10], [0, 1], {extrapolateRight: 'clamp', extrapolateLeft: 'clamp'});
        const w = interpolate(f, [d + 6, d + 22], [0, 560], {extrapolateRight: 'clamp', extrapolateLeft: 'clamp'});
        return (
          <div key={i} style={{position: 'absolute', left: 40, top: 250 + i * 92, opacity: o, width: 600}}>
            <div style={{display: 'flex', alignItems: 'baseline', gap: 16}}>
              <span style={{fontSize: 24, color: T.accentSoft, fontFamily: T.fontMono}}>{row.code}</span>
              <span style={{...heavy, fontSize: 32, color: T.white}}>{row.text}</span>
            </div>
            <div style={{marginTop: 12, height: 2, width: w, background: T.red}} />
          </div>
        );
      })}
      {spec.badge ? <Badge text={spec.badge} delay={30} /> : null}
    </div>
  );
};

const StatementMedia: React.FC<{spec: ShotOverlay; media?: string}> = ({spec, media}) => {
  const f = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const tO = interpolate(f, [4, 14], [0, 1], {extrapolateRight: 'clamp'});
  const appear = msToF((spec.appearMs ?? 3500) as number, fps);
  const imgX = interpolate(f, [appear, appear + 12], [420, 0], {extrapolateRight: 'clamp', extrapolateLeft: 'clamp'});
  const imgO = interpolate(f, [appear, appear + 12], [0, 1], {extrapolateRight: 'clamp', extrapolateLeft: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0, background: T.panel}}>
      <div style={{position: 'absolute', left: 36, top: 60, opacity: tO, ...heavy, fontSize: 76, color: T.white}}>
        {spec.title}
      </div>
      {media && !hideMedia() ? (
        <div
          style={{
            position: 'absolute',
            right: 0,
            bottom: 0,
            width: 480,
            height: 460,
            opacity: imgO,
            transform: `translateX(${imgX}px)`,
            overflow: 'hidden',
          }}
        >
          <Img src={media} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
        </div>
      ) : null}
    </div>
  );
};

// ---------------- media + shots ----------------
const MediaWindow: React.FC<{shot: Shot; index?: number}> = ({shot, index = 0}) => {
  const fps = useVideoConfig().fps;
  const frame = useCurrentFrame();
  const durFrames = msToF(shot.endMs - shot.startMs, fps) + 1;
  if (!shot.media || hideMedia()) return null;
  const src = staticFile(`media/${shot.media}`);
  // 图片运镜：推近/拉远交替 + 轻微平移（让静帧有呼吸感）
  const zoom = interpolate(frame, [0, durFrames], index % 2 === 0 ? [1.0, 1.12] : [1.12, 1.0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const panX = interpolate(frame, [0, durFrames],
    index % 3 === 0 ? [0, -14] : index % 3 === 1 ? [10, -6] : [0, 12],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  if (shot.mediaKind === 'image') {
    return (
      <div style={{position: 'absolute', inset: 0, overflow: 'hidden'}}>
        <Img
          src={src}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            filter: 'blur(18px) brightness(0.82)',
            transform: 'scale(1.15)',
          }}
        />
        <Img
          src={src}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'contain',
            transform: `scale(${zoom}) translateX(${panX}px)`,
          }}
        />
      </div>
    );
  }
  return (
    <div style={{position: 'absolute', inset: 0, overflow: 'hidden'}}>
      <Loop durationInFrames={durFrames}>
        <Video src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      </Loop>
    </div>
  );
};

const ChapterLabel: React.FC<{text: string}> = ({text}) => {
  if (!text) return null;
  return (
    <div style={{position: 'absolute', left: 36, top: 522, display: 'flex', alignItems: 'center'}}>
      <span style={{...Tick, height: 30}} />
      <span style={{...heavy, fontSize: 30, color: T.accentSoft}}>{text}</span>
    </div>
  );
};

const ShotView: React.FC<{shot: Shot; index?: number}> = ({shot, index = 0}) => {
  const fps = useVideoConfig().fps;
  const shotFrame = useCurrentFrame();   // 本镜头内的相对帧号
  const from = msToF(shot.startMs, fps);
  const dur = msToF(shot.endMs - shot.startMs, fps) + 1;
  const mediaSrc = shot.media ? staticFile(`media/${shot.media}`) : undefined;
  const shotInner = (
    <div
      style={{
        position: 'absolute',
        left: PANEL_RECT.left,
        top: PANEL_RECT.top,
        width: PANEL_RECT.width,
        height: PANEL_RECT.height,
        borderRadius: PANEL_RECT.radius,
        background: hideMedia() ? 'transparent' : T.panel,
        overflow: 'hidden',
      }}
    >
      {shot.kind === 'title_card' ? (
        <TitleCard spec={shot.overlay ?? {}} fps={fps} />
      ) : shot.kind === 'quote_card' ? (
        <QuoteCard spec={shot.overlay ?? {}} />
      ) : shot.kind === 'statement' && shot.overlay?.variant === 'statement_media' ? (
        <StatementMedia spec={{...shot.overlay, appearMs: (shot.overlay as any).appearMs} as any} media={mediaSrc} />
      ) : (
        <div style={{position: 'absolute', inset: 0}}>
          {/* media window: 778x440 at panel-relative (36,71) */}
          <div
            style={{
              position: 'absolute',
              left: MEDIA_WINDOW.left,
              top: MEDIA_WINDOW.top,
              width: MEDIA_WINDOW.width,
              height: MEDIA_WINDOW.height,
              overflow: 'hidden',
              opacity: interpolate(shotFrame, [0, (globalThis as any).__motionFrames || 7], [0, 1], {extrapolateRight: 'clamp'}),
              transform: `scale(${interpolate(shotFrame, [0, ((globalThis as any).__motionFrames || 7) + 2], [1.05, 1.0], {extrapolateRight: 'clamp'})})`,
            }}
          >
            <MediaWindow shot={shot} index={index} />
            {shot.kind === 'callout' ? <NumberCallout spec={shot.overlay ?? {}} /> : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'pace' ? (
              <PacePanel spec={shot.overlay} />
            ) : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'compare' ? (
              <ComparePanel spec={shot.overlay} />
            ) : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'fact' ? (
              <FactPanel spec={shot.overlay} />
            ) : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'statement' ? (
              <StatementPanel spec={shot.overlay} />
            ) : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'stat' ? (
              <StatCard spec={shot.overlay} />
            ) : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'branches' ? (
              <Branches spec={shot.overlay} />
            ) : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'timeline' ? (
              <Timeline3 spec={shot.overlay} />
            ) : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'person' ? (
              <PersonCard spec={shot.overlay} />
            ) : null}
            {shot.code ? (
              <div
                style={{
                  position: 'absolute',
                  left: 24,
                  top: 14,
                  fontSize: 22,
                  color: T.codeInk,
                  fontFamily: T.fontMono,
                  letterSpacing: 2,
                }}
              >
                {shot.code}
              </div>
            ) : null}
            {shot.kind === 'footage' ? (
              <div
                style={{
                  position: 'absolute',
                  left: 24,
                  bottom: 18,
                  width: 220,
                  height: 2,
                  background: T.accent,
                }}
              />
            ) : null}
          </div>
          {shot.kind === 'footage' ? <ChapterLabel text={shot.chapterLabel ?? ''} /> : null}
        </div>
      )}
    </div>
  );
  return (
    <Sequence from={from} durationInFrames={dur}>
      {shotInner}
    </Sequence>
  );
};

// ---------------- global layers ----------------

/** #rrggbb -> rgba(...)，用于给皮肤色加透明度 */
function hexA(hex: string, a: number): string {
  const s = String(hex).replace('#', '');
  if (s.length !== 6) return hex;
  const r = parseInt(s.slice(0, 2), 16);
  const g = parseInt(s.slice(2, 4), 16);
  const b = parseInt(s.slice(4, 6), 16);
  if ([r, g, b].some((n) => Number.isNaN(n))) return hex;
  return `rgba(${r},${g},${b},${a})`;
}

/** 装饰层：颗粒 / 网格 / 无 */
function decorLayer(kind: Skin['decor'], tint: string, strength = 1): React.CSSProperties {
  if (kind === 'grid') {
    const c = hexA(tint, 0.075 * strength);
    return {
      backgroundImage:
        `repeating-linear-gradient(0deg, ${c} 0 1px, transparent 1px 92px),` +
        `repeating-linear-gradient(90deg, ${c} 0 1px, transparent 1px 92px)`,
    };
  }
  if (kind === 'grain') {
    const a = 0.05 * strength;
    return {
      backgroundImage:
        "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.02' numOctaves='3'/><feColorMatrix type='matrix' values='0 0 0 0 0.5 0 0 0 0 0.48 0 0 0 0 0.45 0 0 0 " +
        a.toFixed(3) +
        " 0'/></filter><rect width='240' height='240' filter='url(%23n)'/></svg>\")",
    };
  }
  return {};
}

const Background: React.FC = () => (
  <AbsoluteFill
    style={{
      background: `radial-gradient(120% 90% at 50% 30%, ${T.bgTop} 0%, ${T.bgBottom} 78%, ${T.bgBottom} 100%)`,
    }}
  >
    <AbsoluteFill style={decorLayer(T.decor, T.decor === 'grid' ? T.accent : '#78736e')} />
    {T.vignette ? (
      <AbsoluteFill
        style={{
          background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 40%, rgba(0,0,0,0.78) 100%)',
        }}
      />
    ) : null}
  </AbsoluteFill>
);

const HeadlineBand: React.FC<{lines: {text: string; highlight?: string}[]}> = ({lines}) => {
  return (
    <div style={{position: 'absolute', left: 0, top: 0, width: '100%'}}>
      {lines.map((line, i) => {
        if (i === 0 || !line.highlight) {
          return (
            <div
              key={i}
              style={{
                ...heavy,
                fontSize: 88,
                color: T.ink,
                textAlign: 'center',
                marginTop: i === 0 ? 210 : 14,
              }}
            >
              {line.text}
            </div>
          );
        }
        const idx = line.text.indexOf(line.highlight);
        const before = idx > 0 ? line.text.slice(0, idx) : '';
        const after = idx >= 0 ? line.text.slice(idx + line.highlight.length) : line.text;
        // 高亮块「顶到卡片右缘」是参考片的招牌样式，但只有它后面没有文字时才成立；
        // 后面还有字时若仍 flex:1，会把后半句挤出画面。这种情况改为按内容排布并整体居中，
        // 同时按整行可见宽度缩字号，保证再长的标题也放得下。
        const stretch = !after;
        const budget = 840;
        const totalW = estW(before, 88) + estW(line.highlight, 88) + estW(after, 88) + (stretch ? 0 : 48);
        const fs = stretch ? 88 : Math.min(88, Math.max(46, (budget / Math.max(totalW, 1)) * 88));
        return (
          <div
            key={i}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: stretch ? 'flex-start' : 'center',
              marginTop: 14,
              paddingLeft: stretch ? 115 : 40,
              paddingRight: 22,
            }}
          >
            {before ? (
              <span style={{...heavy, fontSize: fs, color: T.ink, whiteSpace: 'pre'}}>{before}</span>
            ) : null}
            <div
              style={{
                flex: stretch ? 1 : '0 0 auto',
                marginLeft: 8,
                background: T.highlightBg,
                borderRadius: T.panelRadius - 4,
                padding: stretch ? '2px 0 6px 0' : '2px 18px 6px 18px',
                position: 'relative',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: 104,
              }}
            >
              <div style={{position: 'absolute', left: 2, top: 0, bottom: 0, width: 10, background: T.red}} />
              <span style={{...heavy, fontSize: fs, color: T.highlightInk}}>{line.highlight}</span>
            </div>
            {after ? (
              <span style={{...heavy, fontSize: fs, color: T.ink, whiteSpace: 'pre'}}>{after}</span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
};

const Footer: React.FC<{sources: string[]; disclaimer: string}> = ({sources, disclaimer}) => (
  <div style={{position: 'absolute', left: 0, top: 1600, width: '100%', textAlign: 'center'}}>
    {sources.length ? (
      <div style={{fontSize: fitSize('资料来源：' + sources.join(' ｜ '), 27, 1010), color: T.gray, marginBottom: 12, whiteSpace: 'nowrap'}}>
        资料来源：{sources.join(' ｜ ')}
      </div>
    ) : null}
    {disclaimer ? <div style={{fontSize: fitSize(disclaimer, 27, 1010), color: T.gray, whiteSpace: 'nowrap'}}>{disclaimer}</div> : null}
  </div>
);

const buildSubtitleChunks = (clauses: Clause[]) => {
  // long clauses are split into <=12-char chunk cards, timing proportional
  // to character count (matches the reference: short constant-size cards)
  const chunks: {text: string; startMs: number; endMs: number}[] = [];
  for (const c of clauses) {
    const n = c.text.length;
    const parts = Math.max(1, Math.ceil(n / 12));
    const size = Math.ceil(n / parts);
    let at = 0;
    while (at < n) {
      let end = Math.min(at + size, n);
      // never break inside a latin word/number run
      if (end < n && /[A-Za-z0-9]/.test(c.text[end - 1]) && /[A-Za-z0-9]/.test(c.text[end])) {
        let e = end;
        while (e < n && /[A-Za-z0-9]/.test(c.text[e])) e += 1;
        if (e - at <= 16) end = e;
      }
      chunks.push({
        text: c.text.slice(at, end),
        startMs: c.startMs + ((c.endMs - c.startMs) * at) / n,
        endMs: c.startMs + ((c.endMs - c.startMs) * end) / n,
      });
      at = end;
    }
  }
  return chunks;
};

const Subtitles: React.FC<{clauses: Clause[]}> = ({clauses}) => {
  const frame = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const t = (frame / fps) * 1000;
  const chunks = buildSubtitleChunks(clauses);
  const active = chunks.find((c) => t >= c.startMs && t < c.endMs);
  if (!active || hideMedia()) return null;
  return (
    <div
      style={{
        position: 'absolute',
        left: 60,
        right: 60,
        top: 1282,
        textAlign: 'center',
        ...heavy,
        fontSize: 70,
        color: T.white,
        textShadow: '0 2px 10px rgba(0,0,0,0.45)',
      }}
    >
      {active.text}
    </div>
  );
};

// ---------------- portrait template (full-bleed, from niwo samples) ----------------
// 对照 niwo「portrait」样品：满屏素材 + 顶部大标题（高亮块）+ 底部大字幕 + 底部来源。

const PortraitMedia: React.FC<{shot: Shot; index: number}> = ({shot, index}) => {
  const fps = useVideoConfig().fps;
  const frame = useCurrentFrame();
  if (!shot.media || hideMedia()) return null;
  const src = staticFile(`media/${shot.media}`);
  const durFrames = msToF(shot.endMs - shot.startMs, fps) + 1;
  if (shot.mediaKind === 'image') {
    const zoom = interpolate(frame, [0, durFrames], index % 2 === 0 ? [1.02, 1.14] : [1.14, 1.02], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    });
    return (
      <AbsoluteFill style={{overflow: 'hidden'}}>
        <Img src={src} style={{position: 'absolute', inset: 0, width: '100%', height: '100%',
          objectFit: 'cover', transform: `scale(${zoom})`}} />
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <Loop durationInFrames={durFrames}>
        <Video src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      </Loop>
    </AbsoluteFill>
  );
};

const PortraitSectionLabel: React.FC<{text: string}> = ({text}) => {
  if (!text) return null;
  return (
    <div style={{position: 'absolute', left: 64, top: 84, display: 'flex', alignItems: 'center',
      textShadow: '0 2px 10px rgba(0,0,0,0.7)'}}>
      <span style={{...Tick, height: 28}} />
      <span style={{...heavy, fontSize: 28, color: T.white, letterSpacing: 1}}>{text}</span>
    </div>
  );
};

const PortraitHeadline: React.FC<{lines: {text: string; highlight?: string}[]}> = ({lines}) => (
  <div style={{position: 'absolute', left: 0, top: 150, width: '100%'}}>
    {lines.map((l, i) => {
      const parts = l.highlight && l.text.includes(l.highlight) ? l.text.split(l.highlight) : null;
      return (
        <div key={i} style={{...heavy, fontSize: 76, color: T.white, textAlign: 'center',
          marginTop: i === 0 ? 0 : 12, textShadow: '0 3px 18px rgba(0,0,0,0.65)'}}>
          {parts ? (
            <>
              {parts[0]}
              <span style={{background: T.red, color: T.white, padding: '0 12px 4px',
                borderRadius: 8, marginLeft: 6}}>{l.highlight}</span>
              {parts[1]}
            </>
          ) : l.text}
        </div>
      );
    })}
  </div>
);

const PortraitSubtitles: React.FC<{clauses: Clause[]}> = ({clauses}) => {
  const frame = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const t = (frame / fps) * 1000;
  const active = buildSubtitleChunks(clauses).find((c) => t >= c.startMs && t < c.endMs);
  if (!active || hideMedia()) return null;
  return (
    <div style={{position: 'absolute', left: 80, right: 80, bottom: 330, textAlign: 'center',
      ...heavy, fontSize: 62, color: T.white, textShadow: '0 3px 16px rgba(0,0,0,0.75)'}}>
      {active.text}
    </div>
  );
};

const PortraitCard: React.FC<{spec: Record<string, any>}> = ({spec}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [0, 10], [0, 1], {extrapolateRight: 'clamp'});
  const y = interpolate(f, [0, 14], [24, 0], {extrapolateRight: 'clamp'});
  const main = spec.amount || spec.title || spec.card?.title || spec.number || spec.card_title || spec.name || '';
  const sub = spec.desc || spec.subtitle || spec.card?.body || spec.card_body || spec.caption || '';
  const showCompare = spec.left || spec.right;
  return (
    <div style={{position: 'absolute', left: 110, right: 110, top: '40%', transform: `translateY(${y}px)`,
      opacity: o, background: T.cardWhite, border: `2px solid ${T.red}`, borderRadius: T.cardRadius,
      padding: '30px 34px', boxShadow: '0 18px 50px rgba(0,0,0,0.5)'}}>
      {spec.label ? (
        <div style={{...heavy, fontSize: 26, color: T.redBright, marginBottom: 12, letterSpacing: 1}}>{spec.label}</div>
      ) : null}
      {main ? <div style={{...heavy, fontSize: 54, color: T.white, lineHeight: 1.15}}>{main}</div> : null}
      {sub ? <div style={{fontSize: 30, color: T.cardMuted, marginTop: 10}}>{sub}</div> : null}
      {showCompare ? (
        <div style={{display: 'flex', gap: 22, marginTop: 18}}>
          {[spec.left, spec.right].map((side, i) => side ? (
            <div key={i} style={{flex: 1, background: hexA(T.cardInk, 0.08), borderRadius: T.cardRadius, padding: '16px 18px'}}>
              <div style={{...heavy, fontSize: 28, color: i === 0 ? T.redBright : T.teal}}>{side.head}</div>
              <div style={{fontSize: 28, color: T.cardInk, marginTop: 6}}>{side.body}</div>
            </div>
          ) : null)}
        </div>
      ) : null}
    </div>
  );
};

const PortraitBigText: React.FC<{label?: string; main?: string; sub?: string; centerY?: number}> = ({
  label,
  main,
  sub,
  centerY,
}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [0, 12], [0, 1], {extrapolateRight: 'clamp'});
  // centerY：在带底部信息条的骨架里，大标题要居中到上半区，避免压住信息条
  const box: React.CSSProperties =
    centerY === undefined
      ? {position: 'absolute', inset: 0}
      : {position: 'absolute', left: 0, right: 0, top: centerY - 420, height: 840};
  return (
    <AbsoluteFill style={{...box, justifyContent: 'center', alignItems: 'center', opacity: o, padding: '0 110px'}}>
      {label ? <div style={{...heavy, fontSize: 30, color: T.redBright, marginBottom: 22, letterSpacing: 2}}>{label}</div> : null}
      {main ? <div style={{...heavy, fontSize: 108, color: T.white, textAlign: 'center', lineHeight: 1.1,
        textShadow: '0 4px 22px rgba(0,0,0,0.7)'}}>{main}</div> : null}
      {sub ? <div style={{fontSize: 34, color: T.onMedia, marginTop: 22, textAlign: 'center'}}>{sub}</div> : null}
    </AbsoluteFill>
  );
};

const PortraitShot: React.FC<{shot: Shot; index: number}> = ({shot, index}) => {
  const fps = useVideoConfig().fps;
  const from = msToF(shot.startMs, fps);
  const dur = msToF(shot.endMs - shot.startMs, fps) + 1;
  const card = shot.kind === 'panel' || shot.kind === 'callout';
  return (
    <Sequence from={from} durationInFrames={dur}>
      <AbsoluteFill style={{overflow: 'hidden'}}>
        <PortraitMedia shot={shot} index={index} />
        <AbsoluteFill style={{background: T.scrim}} />
        {shot.kind === 'title_card'
          ? <PortraitBigText label={shot.overlay?.label} main={shot.overlay?.number || shot.overlay?.keyword || shot.overlay?.title} />
          : null}
        {shot.kind === 'quote_card'
          ? <PortraitBigText label={shot.overlay?.label} main={shot.overlay?.quote || shot.overlay?.title} />
          : null}
        {card ? <PortraitCard spec={(shot.overlay ?? {}) as Record<string, any>} /> : null}
        {shot.chapterLabel && !card ? <PortraitSectionLabel text={shot.chapterLabel} /> : null}
      </AbsoluteFill>
    </Sequence>
  );
};

const PortraitFooter: React.FC<{sources: string[]; disclaimer: string}> = ({sources, disclaimer}) => (
  <div style={{position: 'absolute', left: 0, top: 1690, width: '100%', textAlign: 'center'}}>
    {sources.length ? (
      <div style={{fontSize: fitSize('资料来源：' + sources.join(' ｜ '), 24, 980), color: T.gray,
        marginBottom: 10, whiteSpace: 'nowrap', textShadow: '0 2px 8px rgba(0,0,0,0.8)'}}>
        资料来源：{sources.join(' ｜ ')}
      </div>
    ) : null}
    {disclaimer ? (
      <div style={{fontSize: fitSize(disclaimer, 24, 980), color: T.grayDim,
        whiteSpace: 'nowrap', textShadow: '0 2px 8px rgba(0,0,0,0.8)'}}>{disclaimer}</div>
    ) : null}
  </div>
);

const PortraitVideo: React.FC<NiwoProps> = (props) => (
  <AbsoluteFill data-vg-frame="1"
    style={{background: hideMedia() ? 'transparent' : T.bgTop, fontFamily: T.font}}>
    <FontFace />
    {isBase() ? null : props.shots.map((shot, i) => (
      <PortraitShot key={i} shot={shot} index={i} />
    ))}
    {isCard() ? null : <PortraitHeadline lines={props.headline.lines} />}
    {props.showSubtitles !== false ? <PortraitSubtitles clauses={props.clauses} /> : null}
    {isCard() ? null : <PortraitFooter sources={props.sources} disclaimer={props.disclaimer} />}
  </AbsoluteFill>
);

// ---------------- 分轨导出：文字测量探针 ----------------
// card 模式下文字只留形状与位置（颜色透明），这里把每个文字元素的几何/样式量出来，
// 由 Python 侧生成剪映文本片段（可改字的那一层）。
const TextProbe: React.FC<{url?: string; tag?: string}> = ({url, tag}) => {
  const [handle] = React.useState(() => delayRender('draft text probe'));
  React.useEffect(() => {
    const items: Record<string, unknown>[] = [];
    const seen = new Set<string>();
    // 画面原点：Remotion 会把画面整体放在缩放容器里，rect 是屏幕坐标，需要换算
    const frame = document.querySelector('[data-vg-frame]') as HTMLElement | null;
    const fr = frame ? frame.getBoundingClientRect() : {x: 0, y: 0};
    // 关掉「文字透明」再量，拿到设计里的真实字色；量完恢复
    const hideStyle = document.getElementById('vg-hide-text') as HTMLStyleElement | null;
    if (hideStyle) hideStyle.disabled = true;
    const walk = (el: Element) => {
      const node = el as HTMLElement;
      const box = node.getBoundingClientRect();
      if (box.width > 0.5 && box.height > 0.5) {
        for (const child of Array.from(node.childNodes)) {
          if (child.nodeType !== 3) continue;
          const text = (child.textContent || '').replace(/\s+/g, ' ').trim();
          if (!text) continue;
          const cs = getComputedStyle(node);
          if (parseFloat(cs.fontSize) < 6) continue;
          // 用 Range 量「文字本身」的框：元素框常是整行宽度，不能代表文字位置
          const range = document.createRange();
          range.selectNodeContents(child);
          const r = range.getBoundingClientRect();
          if (r.width <= 0.5 || r.height <= 0.5) continue;
          const key = `${text}|${Math.round(r.x)}|${Math.round(r.y)}`;
          if (seen.has(key)) continue;
          seen.add(key);
          items.push({
            text, x: r.x - fr.x, y: r.y - fr.y, w: r.width, h: r.height,
            size: parseFloat(cs.fontSize),
            weight: parseInt(cs.fontWeight, 10) || 400,
            color: cs.color,
            align: cs.textAlign,
          });
        }
      }
      for (const c of Array.from(el.children)) walk(c);
    };
    walk(document.body);
    if (hideStyle) hideStyle.disabled = false;
    const done = () => continueRender(handle);
    if (url) {
      const payload = JSON.stringify({tag, items});
      // 通道 A：no-cors POST
      fetch(url, {method: 'POST', mode: 'no-cors', body: payload}).then(done).catch(done);
      // 通道 B：图片信标（file:// 页面也能发）
      try {
        const img = new Image();
        const b64 = btoa(unescape(encodeURIComponent(payload)));
        img.src = `${url}?chunk=${encodeURIComponent(b64)}`;
      } catch (err) {
        /* 忽略 */
      }
    } else {
      done();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
};

// ---------------- root video ----------------
export const NiwoVideo: React.FC<NiwoProps> = (props) => {
  // 模板决定整套配色 / 字体 / 装饰 / 动效节奏。必须在子组件渲染前赋值。
  // 配色由模板独家控制：LLM 的 stylePack 从此只影响「用哪些信息卡」，
  // 不再影响画面颜色（否则每个模板都会被同一套主题色染色，等于没换模板）。
  const skin = resolveSkin(props.template);
  applySkin(skin);
  const mode = props.exportMode ?? (props.chromeOnly ? 'card' : 'full');
  setExportMode(mode);
  const probe =
    mode === 'card' ? (
      <>
        {/* 只留形状与位置：字形交给剪映文本轨 */}
        <style
          id="vg-hide-text"
          dangerouslySetInnerHTML={{
            __html: '*{color:transparent !important;text-shadow:none !important;}',
          }}
        />
        <TextProbe url={props.probeUrl} tag={props.probeTag} />
      </>
    ) : null;
  if (skin.layout === 'bleed') {
    return (
      <>
        {probe}
        <PortraitVideo {...props} />
      </>
    );
  }
  if (skin.layout === 'lower') {
    return (
      <>
        {probe}
        <LowerVideo {...props} />
      </>
    );
  }
  return (
    <>
      {probe}
      <EditorialVideo props={props} />
    </>
  );
};

// ---------------- editorial layout（纸卡 + 顶标题带 + 内嵌媒体窗） ----------------
const EditorialVideo: React.FC<{props: NiwoProps}> = ({props}) => (
  <AbsoluteFill data-vg-frame="1"
    style={{background: hideMedia() ? 'transparent' : T.bgTop, fontFamily: T.font}}>
    <FontFace />
    {/* 页面底：card 模式不出（卡片层要能叠在素材上） */}
    {isCard() ? null : isBase() ? (
      <ChromeClip hole={MEDIA_RECT}>
        <Background />
      </ChromeClip>
    ) : (
      <Background />
    )}
    {/* paper card：card 模式不出；base 模式留出媒体窗的洞 */}
    {isCard() ? null : isBase() ? (
      <RectWithHole
        rect={PAPER_RECT}
        hole={MEDIA_RECT}
        radius={PAPER_RECT.radius}
        fill={{background: `linear-gradient(160deg, ${T.paperTop} 0%, ${T.paper} 55%, ${T.paperBottom} 100%)`}}
        style={{boxShadow: T.paperShadow}}
      />
    ) : (
      <div
        style={{
          position: 'absolute',
          left: PAPER_RECT.left,
          top: PAPER_RECT.top,
          width: PAPER_RECT.width,
          height: PAPER_RECT.height,
          borderRadius: PAPER_RECT.radius,
          background: `linear-gradient(160deg, ${T.paperTop} 0%, ${T.paper} 55%, ${T.paperBottom} 100%)`,
          boxShadow: T.paperShadow,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            ...decorLayer(T.paperTexture, T.paperTexture === 'grid' ? T.accent : '#78736e', 1.4),
          }}
        />
      </div>
    )}
    {isCard() ? null : <HeadlineBand lines={props.headline.lines} />}
    {/* inner panel：分轨导出时改成带媒体窗留洞的面板（card 模式不出） */}
    {isCard() ? null : isBase() ? (
      <RectWithHole rect={PANEL_RECT} hole={MEDIA_RECT} radius={T.panelRadius} fill={{background: T.panel}} />
    ) : (
      <div
        style={{
          position: 'absolute',
          left: PANEL_RECT.left,
          top: PANEL_RECT.top,
          width: PANEL_RECT.width,
          height: PANEL_RECT.height,
          borderRadius: T.panelRadius,
          background: T.panel,
        }}
      />
    )}
    {/* base 层只出底板：镜头内容（卡片/角标/章节标签）交给卡片层 */}
    {isBase() ? null : props.shots.map((shot, i) => (
      <ShotView key={i} shot={shot} index={i} />
    ))}
    {props.showSubtitles !== false ? <Subtitles clauses={props.clauses} /> : null}
    {isCard() ? null : <Footer sources={props.sources} disclaimer={props.disclaimer} />}
  </AbsoluteFill>
);

// ---------------- lower layout（满屏素材 + 底部实色信息条） ----------------
const LowerVideo: React.FC<{props: NiwoProps}> = (props) => (
  <AbsoluteFill data-vg-frame="1"
    style={{background: hideMedia() ? 'transparent' : '#000', fontFamily: T.font}}>
    <FontFace />
    {isBase() ? null : props.shots.map((shot, i) => (
      <LowerShot key={i} shot={shot} index={i} />
    ))}
    {isCard() ? null : <LowerBar lines={props.headline.lines} />}
    {props.showSubtitles !== false ? <LowerSubtitles clauses={props.clauses} /> : null}
    {isCard() ? null : <Footer sources={props.sources} disclaimer={props.disclaimer} />}
  </AbsoluteFill>
);

const LowerShot: React.FC<{shot: Shot; index: number}> = ({shot, index}) => {
  const fps = useVideoConfig().fps;
  const from = msToF(shot.startMs, fps);
  const dur = msToF(shot.endMs - shot.startMs, fps) + 1;
  const card = shot.kind === 'panel' || shot.kind === 'callout';
  return (
    <Sequence from={from} durationInFrames={dur}>
      <AbsoluteFill style={{overflow: 'hidden'}}>
        <PortraitMedia shot={shot} index={index} />
        <AbsoluteFill style={{background: T.scrim}} />
        {shot.kind === 'title_card' ? (
          <PortraitBigText
            centerY={560}
            label={shot.overlay?.label}
            main={shot.overlay?.number || shot.overlay?.keyword || shot.overlay?.title}
          />
        ) : null}
        {shot.kind === 'quote_card' ? (
          <PortraitBigText
            centerY={560}
            label={shot.overlay?.label}
            main={shot.overlay?.quote || shot.overlay?.title}
          />
        ) : null}
        {card ? <PortraitCard spec={(shot.overlay ?? {}) as Record<string, any>} /> : null}
      </AbsoluteFill>
    </Sequence>
  );
};

/** 底部实色信息条：播报式 lower third */
const LowerBar: React.FC<{lines: {text: string; highlight?: string}[]}> = ({lines}) => (
  <div
    style={{
      position: 'absolute',
      left: 0,
      top: 1160,
      width: '100%',
      background: 'rgba(3,8,16,0.94)',
      borderTop: `6px solid ${T.accent}`,
      padding: '26px 0 30px 0',
    }}
  >
    {lines.map((l, i) => {
      const parts = l.highlight && l.text.includes(l.highlight) ? l.text.split(l.highlight) : null;
      return (
        <div
          key={i}
          style={{
            ...heavy,
            fontSize: i === 0 ? 68 : 60,
            color: i === 0 ? T.white : T.highlightInk,
            textAlign: 'left',
            paddingLeft: 64,
            paddingRight: 64,
            marginTop: i === 0 ? 0 : 10,
          }}
        >
          {parts ? (
            <>
              {parts[0]}
              <span
                style={{
                  background: i === 0 ? T.accent : T.highlightBg,
                  color: T.onAccent,
                  padding: '0 12px 4px',
                  marginLeft: 6,
                }}
              >
                {l.highlight}
              </span>
              {parts[1]}
            </>
          ) : (
            l.text
          )}
        </div>
      );
    })}
  </div>
);

const LowerSubtitles: React.FC<{clauses: Clause[]}> = ({clauses}) => {
  const frame = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const t = (frame / fps) * 1000;
  const active = buildSubtitleChunks(clauses).find((c) => t >= c.startMs && t < c.endMs);
  if (!active || hideMedia()) return null;
  return (
    <div style={{position: 'absolute', left: 70, right: 70, bottom: 800, textAlign: 'center'}}>
      <span
        style={{
          ...heavy,
          fontSize: 58,
          color: T.white,
          background: 'rgba(3,8,16,0.74)',
          padding: '6px 22px 12px 22px',
          borderRadius: 8,
          lineHeight: 1.3,
        }}
      >
        {active.text}
      </span>
    </div>
  );
};


// ---------------- v11 new card templates (from demo research) ----------------

const StatCard: React.FC<{spec: any}> = ({spec}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [4, 14], [0, 1], {extrapolateRight: 'clamp'});
  const numO = interpolate(f, [12, 24], [0, 1], {extrapolateRight: 'clamp'});
  const numY = interpolate(f, [12, 24], [24, 0], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0, background: T.scrim}}>
      {spec.year ? (
        <div style={{position: 'absolute', top: 26, right: 28, background: T.accent, color: T.onAccent,
                     fontSize: 24, padding: '5px 18px', borderRadius: 20, ...heavy}}>{spec.year}</div>
      ) : null}
      <div style={{position: 'absolute', left: 36, top: 30, display: 'flex', alignItems: 'center', opacity: o}}>
        <span style={Tick} />
        <span style={{...heavy, fontSize: 28, color: T.accentSoft}}>{spec.label}</span>
      </div>
      <div style={{position: 'absolute', left: 38, top: 110, opacity: numO, ...heavy,
                   fontSize: 96, color: T.white, transform: `translateY(${numY}px)`}}>
        {spec.amount}
      </div>
      <div style={{position: 'absolute', left: 42, top: 236, fontSize: 26, color: T.mutedInk, opacity: numO}}>
        {spec.desc}
      </div>
    </div>
  );
};

const Branches: React.FC<{spec: any}> = ({spec}) => {
  const f = useCurrentFrame();
  const srcO = interpolate(f, [4, 12], [0, 1], {extrapolateRight: 'clamp'});
  const targets = spec.targets ?? [];
  return (
    <div style={{position: 'absolute', inset: 0, background: T.scrim}}>
      <div style={{position: 'absolute', left: 30, top: 30, display: 'flex', alignItems: 'center'}}>
        <span style={Tick} />
        <span style={{...heavy, fontSize: 28, color: T.accentSoft}}>{spec.label}</span>
      </div>
      <div style={{position: 'absolute', left: 30, top: 150, opacity: srcO}}>
        <div style={{...heavy, fontSize: 40, color: T.white, background: T.chipBg,
                     padding: '12px 26px', borderRadius: 10, display: 'inline-block'}}>
          {spec.source}
        </div>
      </div>
      {targets.map((_: unknown, i: number) => {
        const y1 = 196;
        const y2 = 210 + i * ((440 - 230) / Math.max(targets.length - 1, 1));
        const w = interpolate(f, [14 + i * 6, 26 + i * 6], [0, 260],
                              {extrapolateRight: 'clamp', extrapolateLeft: 'clamp'});
        return <div key={i} style={{position: 'absolute', left: 210, top: y1,
                                    width: w, height: 2, background: `${T.accent}88`,
                                    transform: `rotate(${(y2 - y1) * 0.05}deg)`, transformOrigin: 'left center'}} />;
      })}
      {targets.map((t: any, i: number) => {
        const o2 = interpolate(f, [20 + i * 6, 30 + i * 6], [0, 1], {extrapolateRight: 'clamp', extrapolateLeft: 'clamp'});
        const y2 = 210 + i * ((440 - 230) / Math.max(targets.length - 1, 1));
        return (
          <div key={i} style={{position: 'absolute', left: 430, top: y2 - 24, opacity: o2}}>
            <div style={{background: T.chipBg, color: T.white, ...heavy,
                         fontSize: 26, padding: '8px 20px', borderRadius: 8, display: 'inline-block'}}>
              {t.text ?? t}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const PersonCard: React.FC<{spec: any}> = ({spec}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [6, 18], [0, 1], {extrapolateRight: 'clamp'});
  const cardX = interpolate(f, [10, 22], [-60, 0], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <div style={{position: 'absolute', left: 36, top: 30, display: 'flex', alignItems: 'center'}}>
        <span style={Tick} />
        <span style={{...heavy, fontSize: 28, color: T.accentSoft}}>{spec.kicker}</span>
      </div>
      <div style={{position: 'absolute', left: 36, top: 90, opacity: o, ...heavy, fontSize: 56, color: T.white}}>
        {spec.title}
      </div>
      <div style={{position: 'absolute', right: 24, bottom: 20, width: 460, opacity: o,
                   transform: `translateX(${cardX * -0.4}px)`, background: T.cardWhite, borderRadius: T.cardRadius,
                   padding: '22px 28px'}}>
        <div style={{...heavy, fontSize: 30, color: T.cardInk}}>{spec.name}</div>
        <div style={{fontSize: 24, color: T.cardMuted, marginTop: 10, lineHeight: 1.45}}>{spec.caption}</div>
      </div>
    </div>
  );
};

const Timeline3: React.FC<{spec: any}> = ({spec}) => {
  const f = useCurrentFrame();
  const cols = spec.cols ?? [];
  return (
    <div style={{position: 'absolute', inset: 0, background: T.scrim}}>
      <div style={{position: 'absolute', left: 36, top: 30, ...heavy, fontSize: 48, color: T.white}}>
        {spec.title}
      </div>
      {spec.subtitle ? (
        <div style={{position: 'absolute', left: 38, top: 104, fontSize: 26, color: T.mutedInk}}>{spec.subtitle}</div>
      ) : null}
      <div style={{position: 'absolute', left: 30, right: 30, top: 180, display: 'flex', gap: 18}}>
        {cols.map((col: any, i: number) => {
          const o = interpolate(f, [16 + i * 10, 28 + i * 10], [0, 1], {extrapolateRight: 'clamp', extrapolateLeft: 'clamp'});
          return (
            <div key={i} style={{flex: 1, background: T.timelineBg, borderRadius: T.cardRadius,
                                 border: `2px solid ${T.accent}66`, opacity: o, padding: '16px 18px'}}>
              <div style={{display: 'inline-block', background: T.accent, color: T.onAccent, fontSize: 22,
                           padding: '3px 14px', borderRadius: 6, ...heavy}}>{col.year}</div>
              <div style={{fontSize: 24, color: T.white, marginTop: 12, lineHeight: 1.45}}>{col.text}</div>
            </div>
          );
        })}
      </div>
      {spec.badge ? <Badge text={spec.badge} delay={34} /> : null}
    </div>
  );
};
