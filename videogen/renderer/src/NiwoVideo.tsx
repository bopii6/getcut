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
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {Audio as MediaAudio} from '@remotion/media';
import {ShotVideo} from './webmedia';
import {T, resolveSkin, applySkin, type Skin} from './skin';
import {ChoreoCard, sanitizeChoreo} from './choreo';
import {ZhiguVideo} from './ZhiguVideo';
import {MacroVideo} from './MacroVideo';

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

export const FontFace: React.FC = () => {
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
  /** 编舞谱（开场/金句现场编排）：结构由 choreo.tsx 的词汇表约束，非法谱回落死编排 */
  choreo?: unknown;
};
export type ZhiguTable = {
  title?: string;
  rows?: {name?: string; sub?: string; value?: string; delta?: string; highlight?: boolean}[];
  tooltip?: string;
};
export type ZhiguStage = {
  /** 关键词芯片：黄底黑字，一排弹出 */
  chips?: string[];
  /** 关系树：中间主卡 + 虚线连子项胶囊 */
  tree?: {center?: {title?: string; sub?: string; logo?: string};
          children?: ({title?: string; logo?: string} | string)[]};
  /** 榜单卡：标题条 + 行，高亮一行 + 弹出说明 */
  table?: ZhiguTable;
};
/** macro 章节的宽松形状（精确类型在 MacroVideo.tsx，这里只做字段透传） */
export type MacroStageLike = {
  mode: 'macro';
  kicker?: string;
  title: string;
  sub?: string;
  block?: Record<string, unknown>;
  caption?: {text: string; atMs: number};
  rule?: boolean;
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
  /** 智谷三段式：舞台动作字段（chips/tree/table） */
  stage?: ZhiguStage;
  /** macro（宏观棱镜复刻）：整拍就是一个章节（kicker/标题/块） */
  macroStage?: MacroStageLike;
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
  /** 编舞镜头（开场/金句/数字卡）时间窗 [startMs, endMs]：窗内字幕不出，画面自带大字 */
  subtitleHoles?: [number, number][];
  /** 模板 id：editorial / finance / minimal / bleed / news / retro / portrait */
  template?: string;
  /** 右上角品牌水印「Powered by GetCut」；false = 不出 */
  watermark?: boolean;
  /** 栏目化（高级档）：第 X 期角标（左上角，全程显示） */
  series?: {
    badge?: string;
  };
  /** 品牌套装（高级档）：用户的 Logo + 文字水印（右上角胶囊；片尾卡/品牌色已下线） */
  brand?: {
    /** renderer/public 下的相对路径（brand/<key>.png） */
    logo?: string;
    /** 右上角水印文字，如 @阿伟说财经；留空回落 Powered by GetCut */
    watermarkText?: string;
  };
  /** macro 模板：全程钉死的暗背景图（renderer/public/media 下的文件名） */
  bgImage?: string;
  /** macro 模板：频道名（左上标 + 波形件下方签名） */
  channelName?: string;
  shots: Shot[];
  clauses: Clause[];
  /**
   * 分轨草稿导出模式：card=只出卡片/包装层（文字转剪映文本轨），base=只出底板层。
   * 供剪映草稿分层合成。
   */
  exportMode?: ExportMode;
  /** @deprecated 旧字段，等价于 exportMode="card" */
  chromeOnly?: boolean;
  /** 分轨导出：测量结果的分组标签（通常是镜头 id） */
  probeTag?: string;
  /** 分轨导出：云端算好的卡片层取帧清单，成片台照着逐张出图 */
  draftStills?: {id: string; frame: number}[];
  /**
   * 浏览器内合成（web-renderer）专用混音计划：voice/bgm/sfx 都是渲染包里
   * audio/ 下的相对路径，随 props 一起下发。云端渲染链路不带这个字段，
   * 画面轨照旧无声、由 ffmpeg 混音——两种产物互不干扰。
   */
  audio?: {
    voice: string;
    bgm?: string | null;
    sfx?: {t: number; file: string; vol: number}[];
    durationMs?: number;
  };
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
// full：正常成片 / card：只出卡片包装层 / base：只出底板层
// 剪映草稿的轨道顺序（下→上）：底板 → 画面 → 卡片 → 字幕 → 叠加文字
// 状态实现在 ./anim（编舞引擎的媒体元素也要遵守），这里转发导出维持旧引用。
export {setExportMode, hideMedia, isCard, isBase} from './anim';
export type {ExportMode} from './anim';
import {hideMedia, isCard, isBase, setExportMode} from './anim';
import type {ExportMode} from './anim';
/**
 * 版式几何一律走皮肤（renderer/src/layouts.json）：一次渲染 = 一个模板，
 * T.geo 在渲染入口由 applySkin 赋值，所以这里只做取值不存常量。
 */
const paperRect = () => T.geo.paper!;
const panelRect = () => T.geo.panel!;
const mediaWindow = () => T.geo.mediaWin!;
/** 媒体窗在整帧里的 rect（= 面板 rect + 窗口相对偏移）：素材轨的落点 */
const mediaRect = () => T.geo.mediaRect!;

type Rect = {left: number; top: number; width: number; height: number};

/**
 * 全帧坐标 -> 挖掉 hole 矩形的 clip-path。
 * 刻意不写 polygon(evenodd, …)：成片台用的 @remotion/web-renderer 那套软件合成器
 * 按「每个点 x y」解析 polygon()，evenodd 前缀会被当成第一个点，整张底板直接渲崩
 * （视频那条路是 full 模式，从不走这里，所以一直没暴露）。
 * 改写成「零宽缝隙 + 反向绕行」：nonzero 填充下外框与洞方向相反即互相抵消，
 * 洞照样是洞，真浏览器里像素一致。
 */
const holeClip = (frameW: number, frameH: number, hole: Rect) => {
  const l = hole.left;
  const t = hole.top;
  const r = hole.left + hole.width;
  const b = hole.top + hole.height;
  return 'polygon(' + [
    `0 0`, `${frameW}px 0`, `${frameW}px ${frameH}px`, `0 ${frameH}px`, `0 0`,
    `${l}px ${t}px`, `${l}px ${b}px`, `${r}px ${b}px`, `${r}px ${t}px`, `${l}px ${t}px`,
  ].join(', ') + ')';
};

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
// heavy / Tick / useAnimFrame 抽到 ./anim：编舞引擎（choreo）与卡片共用同一套字面与入场节奏。
import {heavy, Tick, useAnimFrame} from './anim';
export {useAnimFrame};

const Label: React.FC<{text: string; delay?: number}> = ({text, delay = 0}) => {
  const frame = useAnimFrame();
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
  const f = useAnimFrame();
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
  const f = useAnimFrame();
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
  const f = useAnimFrame();
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
  const f = useAnimFrame();
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
  const f = useAnimFrame();
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
  const f = useAnimFrame();
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
  const f = useAnimFrame();
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
  const f = useAnimFrame();
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
        <ShotVideo src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
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
  // 编舞谱：片头/片尾/数字卡的 overlay 带合法谱就走引擎，谱废了回落死编排
  const choreoCues = sanitizeChoreo(shot.overlay?.choreo);
  const shotInner = (
    <div
      style={{
        position: 'absolute',
        left: panelRect().left,
        top: panelRect().top,
        width: panelRect().width,
        height: panelRect().height,
        borderRadius: T.panelRadius,
        background: hideMedia() ? 'transparent' : T.panel,
        overflow: 'hidden',
      }}
    >
      {shot.kind === 'title_card' ? (
        choreoCues ? (
          <ChoreoCard cues={choreoCues} fps={fps} media={mediaSrc}
                      mediaKind={shot.mediaKind} dur={dur} />
        ) : (
          <TitleCard spec={shot.overlay ?? {}} fps={fps} />
        )
      ) : shot.kind === 'quote_card' ? (
        choreoCues ? (
          <ChoreoCard cues={choreoCues} fps={fps} media={mediaSrc}
                      mediaKind={shot.mediaKind} dur={dur} />
        ) : (
          <QuoteCard spec={shot.overlay ?? {}} />
        )
      ) : shot.kind === 'statement' && shot.overlay?.variant === 'statement_media' ? (
        <StatementMedia spec={{...shot.overlay, appearMs: (shot.overlay as any).appearMs} as any} media={mediaSrc} />
      ) : shot.kind === 'callout' && choreoCues ? (
        <ChoreoCard cues={choreoCues} fps={fps} media={mediaSrc}
                    mediaKind={shot.mediaKind} dur={dur} />
      ) : shot.kind === 'panel' && choreoCues && (shot.overlay?.variant === 'fact' || shot.overlay?.variant === 'statement') ? (
        // fact/statement 卡谱：字段当主角现场摆（谱内元素只从词汇表出）
        <ChoreoCard cues={choreoCues} fps={fps} media={mediaSrc}
                    mediaKind={shot.mediaKind} dur={dur} />
      ) : (
        <div style={{position: 'absolute', inset: 0}}>
          {/* media window: 778x440 at panel-relative (36,71) */}
          <div
            style={{
              position: 'absolute',
              left: mediaWindow().left,
              top: mediaWindow().top,
              width: mediaWindow().width,
              height: mediaWindow().height,
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
            {shot.kind === 'footage' && !choreoCues ? (
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
          {shot.kind === 'footage' ? (
            choreoCues ? (
              // 信息层编舞谱：挂在面板坐标系（媒体窗外层），media-* 锚位经 mediaOrigin
              // 换算进媒体窗；只画谱里的元素，媒体窗本身照常走 MediaWindow
              <ChoreoCard cues={choreoCues} fps={fps} dur={dur} bare
                          mediaOrigin={{left: mediaWindow().left, top: mediaWindow().top,
                                        width: mediaWindow().width, height: mediaWindow().height}} />
            ) : (
              <ChapterLabel text={shot.chapterLabel ?? ''} />
            )
          ) : null}
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
  const H = T.geo.headline;
  return (
    <div style={{position: 'absolute', left: 0, top: 0, width: '100%'}}>
      {lines.map((line, i) => {
        if (i === 0 || !line.highlight) {
          return (
            <div
              key={i}
              style={{
                ...heavy,
                fontSize: H.size,
                color: T.ink,
                textAlign: 'center',
                marginTop: i === 0 ? H.top : H.lineGap ?? 14,
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
        const budget = H.budget ?? 840;
        const totalW = estW(before, H.size) + estW(line.highlight, H.size) + estW(after, H.size) + (stretch ? 0 : 48);
        const fs = stretch ? H.size : Math.min(H.size, Math.max(46, (budget / Math.max(totalW, 1)) * H.size));
        return (
          <div
            key={i}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: stretch ? 'flex-start' : 'center',
              marginTop: H.lineGap ?? 14,
              paddingLeft: stretch ? panelRect().left : 40,
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
                height: H.highlightHeight ?? 104,
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

const Footer: React.FC<{sources: string[]; disclaimer: string}> = ({sources, disclaimer}) => {
  const F = T.geo.footer;
  return (
  <div style={{position: 'absolute', left: 0, top: F.top, width: '100%', textAlign: 'center'}}>
    {sources.length ? (
      <div style={{fontSize: fitSize('资料来源：' + sources.join(' ｜ '), F.size, F.width), color: T.gray, marginBottom: 12, whiteSpace: 'nowrap'}}>
        资料来源：{sources.join(' ｜ ')}
      </div>
    ) : null}
    {disclaimer ? <div style={{fontSize: fitSize(disclaimer, F.size, F.width), color: T.gray, whiteSpace: 'nowrap'}}>{disclaimer}</div> : null}
  </div>
  );
};

export const buildSubtitleChunks = (clauses: Clause[]) => {
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

const Subtitles: React.FC<{clauses: Clause[]; holes?: [number, number][]}> = ({clauses, holes}) => {
  const frame = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const t = (frame / fps) * 1000;
  const chunks = buildSubtitleChunks(clauses);
  const active = chunks.find((c) => t >= c.startMs && t < c.endMs);
  if (!active || hideMedia()) return null;
  // 编舞时刻（内容驱动开场/金句卡/数字卡）画面自带大字：字幕再压上来会撞成两层白字，让路
  if (holes?.some(([a, b]) => active.startMs >= a - 200 && active.endMs <= b + 200)) return null;
  return (
    <div
      style={{
        position: 'absolute',
        left: T.geo.subtitle.side ?? 60,
        right: T.geo.subtitle.side ?? 60,
        top: T.geo.subtitle.top,
        textAlign: 'center',
        ...heavy,
        fontSize: T.geo.subtitle.size,
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
        <ShotVideo src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      </Loop>
    </AbsoluteFill>
  );
};

const PortraitSectionLabel: React.FC<{text: string}> = ({text}) => {
  const S = T.geo.sectionLabel ?? {left: 64, top: 84, size: 28};
  if (!text) return null;
  return (
    <div style={{position: 'absolute', left: S.left, top: S.top, display: 'flex', alignItems: 'center',
      textShadow: '0 2px 10px rgba(0,0,0,0.7)'}}>
      <span style={{...Tick, height: 28}} />
      <span style={{...heavy, fontSize: S.size, color: T.white, letterSpacing: 1}}>{text}</span>
    </div>
  );
};

const PortraitHeadline: React.FC<{lines: {text: string; highlight?: string}[]}> = ({lines}) => {
  const H = T.geo.headline;
  return (
  <div style={{position: 'absolute', left: 0, top: H.top, width: '100%'}}>
    {lines.map((l, i) => {
      const parts = l.highlight && l.text.includes(l.highlight) ? l.text.split(l.highlight) : null;
      return (
        <div key={i} style={{...heavy, fontSize: H.size, color: T.white, textAlign: 'center',
          marginTop: i === 0 ? 0 : H.lineGap ?? 12, textShadow: '0 3px 18px rgba(0,0,0,0.65)'}}>
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
};

const PortraitSubtitles: React.FC<{clauses: Clause[]}> = ({clauses}) => {
  const frame = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const t = (frame / fps) * 1000;
  const active = buildSubtitleChunks(clauses).find((c) => t >= c.startMs && t < c.endMs);
  if (!active || hideMedia()) return null;
  return (
    <div style={{position: 'absolute', left: T.geo.subtitle.side ?? 80, right: T.geo.subtitle.side ?? 80,
      bottom: T.geo.subtitle.bottom, textAlign: 'center',
      ...heavy, fontSize: T.geo.subtitle.size, color: T.white, textShadow: '0 3px 16px rgba(0,0,0,0.75)'}}>
      {active.text}
    </div>
  );
};

const PortraitCard: React.FC<{spec: Record<string, any>}> = ({spec}) => {
  const f = useAnimFrame();
  const C = T.geo.card ?? {side: 110, topPct: 40, size: 54, titleSize: 26, subSize: 30};
  const o = interpolate(f, [0, 10], [0, 1], {extrapolateRight: 'clamp'});
  const y = interpolate(f, [0, 14], [24, 0], {extrapolateRight: 'clamp'});
  const main = spec.amount || spec.title || spec.card?.title || spec.number || spec.card_title || spec.name || '';
  const sub = spec.desc || spec.subtitle || spec.card?.body || spec.card_body || spec.caption || '';
  const showCompare = spec.left || spec.right;
  return (
    <div style={{position: 'absolute', left: C.side, right: C.side, top: `${C.topPct}%`, transform: `translateY(${y}px)`,
      opacity: o, background: T.cardWhite, border: `2px solid ${T.red}`, borderRadius: T.cardRadius,
      padding: '30px 34px', boxShadow: '0 18px 50px rgba(0,0,0,0.5)'}}>
      {spec.label ? (
        <div style={{...heavy, fontSize: C.titleSize, color: T.redBright, marginBottom: 12, letterSpacing: 1}}>{spec.label}</div>
      ) : null}
      {main ? <div style={{...heavy, fontSize: C.size, color: T.white, lineHeight: 1.15}}>{main}</div> : null}
      {sub ? <div style={{fontSize: C.subSize, color: T.cardMuted, marginTop: 10}}>{sub}</div> : null}
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
  const f = useAnimFrame();
  const B = T.geo.bigText ?? {size: 108, subSize: 34, side: 110};
  const o = interpolate(f, [0, 12], [0, 1], {extrapolateRight: 'clamp'});
  // centerY：在带底部信息条的骨架里，大标题要居中到上半区，避免压住信息条
  const box: React.CSSProperties =
    centerY === undefined
      ? {position: 'absolute', inset: 0}
      : {position: 'absolute', left: 0, right: 0, top: centerY - 420, height: 840};
  return (
    <AbsoluteFill style={{...box, justifyContent: 'center', alignItems: 'center', opacity: o, padding: `0 ${B.side}px`}}>
      {label ? <div style={{...heavy, fontSize: 30, color: T.redBright, marginBottom: 22, letterSpacing: 2}}>{label}</div> : null}
      {main ? <div style={{...heavy, fontSize: B.size, color: T.white, textAlign: 'center', lineHeight: 1.1,
        textShadow: '0 4px 22px rgba(0,0,0,0.7)'}}>{main}</div> : null}
      {sub ? <div style={{fontSize: B.subSize, color: T.onMedia, marginTop: 22, textAlign: 'center'}}>{sub}</div> : null}
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

const PortraitFooter: React.FC<{sources: string[]; disclaimer: string}> = ({sources, disclaimer}) => {
  const F = T.geo.footer;
  return (
  <div style={{position: 'absolute', left: 0, top: F.top, width: '100%', textAlign: 'center'}}>
    {sources.length ? (
      <div style={{fontSize: fitSize('资料来源：' + sources.join(' ｜ '), F.size, F.width), color: T.gray,
        marginBottom: 10, whiteSpace: 'nowrap', textShadow: '0 2px 8px rgba(0,0,0,0.8)'}}>
        资料来源：{sources.join(' ｜ ')}
      </div>
    ) : null}
    {disclaimer ? (
      <div style={{fontSize: fitSize(disclaimer, F.size, F.width), color: T.grayDim,
        whiteSpace: 'nowrap', textShadow: '0 2px 8px rgba(0,0,0,0.8)'}}>{disclaimer}</div>
    ) : null}
  </div>
  );
};

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
/**
 * 量出来的文字几何暂存在此：成片台页面渲完一张 card 层就直接读它，
 * 随图层一起交回云端（服务器不再有 Chrome，量不到第二手）。
 * 必须走 globalThis 取：webpack 分包会把本模块装进多个 chunk，
 * 模块级常量会变成两份，页面那份永远读不到渲染那份写的东西。
 */
export const probeSink = (): Record<string, Record<string, unknown>[]> =>
  ((globalThis as {__vgProbe?: Record<string, Record<string, unknown>[]>}).__vgProbe
    ??= {});

/** 量画面里每个文字元素的几何与样式：剪映文本轨按这个摆字（可改字的那一层）。 */
const measureTextGeometry = (anchor: HTMLElement | null): Record<string, unknown>[] => {
  const items: Record<string, unknown>[] = [];
  const seen = new Set<string>();
  // 画面原点：Remotion 把画面整体放在缩放容器里，rect 是屏幕坐标，需要换算。
  // 必须从探针自己往上找——页面里同时存在过好几个 [data-vg-frame]（播放器那一个、
  // 每张 still 各自的脚手架），全局 querySelector 会抓到残留的那个。
  const frame = anchor?.closest('[data-vg-frame]') as HTMLElement | null;
  if (!frame) return items;
  const fr = frame.getBoundingClientRect();
  // still 的脚手架挂在 visibility:hidden 下：隐藏里的文字不生成绘制盒，Range 量出来
  // 全是 0×0。量之前把祖先的 visibility 临时抬起来，量完还原；外层那个
  // filter:opacity(0) 不动，它照样透明，不会在页面上闪一下。
  const lifted: Array<[HTMLElement, string]> = [];
  for (let q: HTMLElement | null = frame; q; q = q.parentElement) {
    if (getComputedStyle(q).visibility === 'hidden') {
      lifted.push([q, q.style.visibility]);
      q.style.visibility = 'visible';
    }
  }
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
  // 只量画面内部：成片台页面自身还有一整栏 UI，从 body 起走会把按钮文案当成片文字
  walk(frame);
  if (hideStyle) hideStyle.disabled = false;
  for (const [el, v] of lifted) el.style.visibility = v;
  return items;
};

const TextProbe: React.FC<{tag?: string}> = ({tag}) => {
  const anchorRef = React.useRef<HTMLSpanElement>(null);
  // 必须用 layout effect 同步量：web-renderer 不吃 delayRender——它渲完就取像素，
  // 普通 effect 排在那之后，探针连同脚手架一起被卸载，一条文字都量不到（实测）。
  React.useLayoutEffect(() => {
    if (tag) probeSink()[tag] = measureTextGeometry(anchorRef.current);
  }, [tag]);
  // 零尺寸占位：只为让探针知道自己挂在哪个画面里
  return <span ref={anchorRef} style={{display: 'none'}} />;
};

/**
 * 品牌水印：六套模板共用，画在最上层，位置固定在右上角。
 * 为什么是右上角：竖屏平台自己的按钮在下边，而六套模板的底部都被字幕/信息条/页脚占着，
 * 右上角是唯一六套都空着的地方。用深色半透明底 + 白字，浅色模板（数据面板）上也看得清。
 * 分轨导出时只压进底板层（card 层不画），否则每张卡片上都会叠一个。
 */
const Watermark: React.FC<{logo?: string; text?: string}> = ({logo, text}) => (
  <div
    style={{
      position: 'absolute', top: 34, right: 38, display: 'flex', alignItems: 'center', gap: 9,
      padding: logo ? '6px 10px' : '7px 13px', borderRadius: 9, background: 'rgba(10,10,14,0.46)',
      color: '#ffffff', fontFamily: T.font, lineHeight: 1,
    }}
  >
    {logo ? (
      // 品牌套装：右上角摆用户自己的 Logo（等比缩进 34px 高的胶囊里）
      <Img src={staticFile(logo)} alt="" style={{height: 30, maxWidth: 150, objectFit: 'contain', display: 'block'}} />
    ) : null}
    {text ? (
      <span style={{fontSize: 21, fontWeight: 700, letterSpacing: 0.4, whiteSpace: 'nowrap'}}>{text}</span>
    ) : null}
    {!logo && !text ? (
      <>
        <span style={{width: 15, height: 15, borderRadius: 5, background: '#B7AAFF', display: 'inline-block'}} />
        <span style={{fontSize: 21, fontWeight: 700, letterSpacing: 0.4, whiteSpace: 'nowrap'}}>
          Powered by <span style={{color: '#C9BEFF'}}>GetCut</span>
        </span>
      </>
    ) : null}
  </div>
);

/**
 * 栏目角标（高级档）：左上角"第 X 期"，和水印（右上）对称，全程常驻。
 * 让一个账号的十条片子看起来是同一个栏目——这是 IP 感的来源。
 */
const SeriesBadge: React.FC<{text: string}> = ({text}) => (
  <div style={{
    position: 'absolute', top: 34, left: 38, padding: '9px 16px', borderRadius: 9,
    background: 'rgba(10,10,14,0.46)', color: '#ffffff', fontFamily: T.font,
    fontSize: 21, fontWeight: 700, letterSpacing: 0.5, lineHeight: 1, whiteSpace: 'nowrap',
  }}>
    {text}
  </div>
);

// ---------------- root video ----------------
// ---------------- 浏览器内合成：音轨层 ----------------
// 复刻云端 ffmpeg 混音规格：配音全程、BGM 音量 0.2 循环铺底、片尾 3 秒淡出、
// 音效按事件时刻挂。BGM 的 highpass/压缩两处小差异可闻度极低，暂不复刻。
const AudioLayer: React.FC<{audio: NonNullable<NiwoProps['audio']>}> = ({audio}) => {
  const {fps, durationInFrames} = useVideoConfig();
  const totalMs = (audio.durationMs || 0) > 0
    ? audio.durationMs!
    : (durationInFrames / fps) * 1000;
  const fadeStart = totalMs - 3000;
  return (
    <>
      <MediaAudio src={staticFile(audio.voice)} />
      {audio.bgm ? (
        <MediaAudio
          src={staticFile(audio.bgm)}
          loop
          volume={(f) => {
            const t = (f / fps) * 1000;
            const fade = t <= fadeStart ? 1 : Math.max(0, (totalMs - t) / 3000);
            return 0.2 * fade;
          }}
        />
      ) : null}
      {(audio.sfx || []).map((e, i) => (
        <Sequence key={i} from={Math.round(e.t * fps)}>
          <MediaAudio src={staticFile(e.file)} volume={e.vol} />
        </Sequence>
      ))}
    </>
  );
};

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
        {/* 只留形状与位置：字形交给剪映文本轨。范围必须锁在画面内部——
            成片台页面与合成同处一个 document，写全局 * 会把页面自己的字也弄透明 */}
        <style
          id="vg-hide-text"
          dangerouslySetInnerHTML={{
            __html: '.vg-frame,.vg-frame *{color:transparent !important;text-shadow:none !important;}',
          }}
        />
        <TextProbe tag={props.probeTag} />
      </>
    ) : null;
  let body: React.ReactNode;
  if (skin.layout === 'bleed') body = <PortraitVideo {...props} />;
  else if (skin.layout === 'zhigu') body = <ZhiguVideo {...props} />;
  else if (skin.layout === 'macro') body = <MacroVideo {...props} />;
  else if (skin.layout === 'lower') body = <LowerVideo {...props} />;
  else if (skin.layout === 'poster') body = <PosterVideo {...props} />;
  else if (skin.layout === 'data') body = <DataVideo {...props} />;
  else body = <EditorialVideo props={props} />;
  return (
    // 画面根节点统一在这里给：七个版式各有自己的 AbsoluteFill，靠它们各自挂
    // 标记会漏（宏观/智谷两版就没挂），文字几何也就量不到正确的原点。
    <AbsoluteFill data-vg-frame="1" className="vg-frame">
      {probe}
      {body}
      {props.series?.badge && !isCard() ? <SeriesBadge text={props.series.badge} /> : null}
      {props.watermark !== false && !isCard() ? <Watermark logo={props.brand?.logo} text={props.brand?.watermarkText} /> : null}
      {props.audio && mode === 'full' ? <AudioLayer audio={props.audio} /> : null}
    </AbsoluteFill>
  );
};

// ---------------- editorial layout（纸卡 + 顶标题带 + 内嵌媒体窗） ----------------
const EditorialVideo: React.FC<{props: NiwoProps}> = ({props}) => (
  <AbsoluteFill data-vg-frame="1"
    style={{background: hideMedia() ? 'transparent' : T.bgTop, fontFamily: T.font}}>
    <FontFace />
    {/* 页面底：card 模式不出（卡片层要能叠在素材上） */}
    {isCard() ? null : isBase() ? (
      <ChromeClip hole={mediaRect()}>
        <Background />
      </ChromeClip>
    ) : (
      <Background />
    )}
    {/* paper card：card 模式不出；base 模式留出媒体窗的洞 */}
    {isCard() ? null : isBase() ? (
      <RectWithHole
        rect={paperRect()}
        hole={mediaRect()}
        radius={paperRect().radius}
        fill={{background: `linear-gradient(160deg, ${T.paperTop} 0%, ${T.paper} 55%, ${T.paperBottom} 100%)`}}
        style={{boxShadow: T.paperShadow}}
      />
    ) : (
      <div
        style={{
          position: 'absolute',
          left: paperRect().left,
          top: paperRect().top,
          width: paperRect().width,
          height: paperRect().height,
          borderRadius: paperRect().radius,
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
      <RectWithHole rect={panelRect()} hole={mediaRect()} radius={T.panelRadius} fill={{background: T.panel}} />
    ) : (
      <div
        style={{
          position: 'absolute',
          left: panelRect().left,
          top: panelRect().top,
          width: panelRect().width,
          height: panelRect().height,
          borderRadius: T.panelRadius,
          background: T.panel,
        }}
      />
    )}
    {/* base 层只出底板：镜头内容（卡片/角标/章节标签）交给卡片层 */}
    {isBase() ? null : props.shots.map((shot, i) => (
      <ShotView key={i} shot={shot} index={i} />
    ))}
    {props.showSubtitles !== false ? <Subtitles clauses={props.clauses} holes={props.subtitleHoles} /> : null}
    {isCard() ? null : <Footer sources={props.sources} disclaimer={props.disclaimer} />}
  </AbsoluteFill>
);

// ---------------- lower layout（满屏素材 + 底部实色信息条） ----------------
const LowerVideo: React.FC<{props: NiwoProps}> = (props) => (
  <AbsoluteFill data-vg-frame="1"
    style={{background: hideMedia() ? 'transparent' : T.pageBg ?? '#000', fontFamily: T.font}}>
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
            centerY={T.geo.contentCenterY ?? 560}
            label={shot.overlay?.label}
            main={shot.overlay?.number || shot.overlay?.keyword || shot.overlay?.title}
          />
        ) : null}
        {shot.kind === 'quote_card' ? (
          <PortraitBigText
            centerY={T.geo.contentCenterY ?? 560}
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
const LowerBar: React.FC<{lines: {text: string; highlight?: string}[]}> = ({lines}) => {
  const B = T.geo.headline;
  return (
  <div
    style={{
      position: 'absolute',
      left: 0,
      top: B.top,
      width: '100%',
      background: T.barBg ?? 'rgba(3,8,16,0.94)',
      borderTop: `${B.borderTop ?? 6}px solid ${T.accent}`,
      padding: `${B.padTop ?? 26}px 0 ${B.padBottom ?? 30}px 0`,
    }}
  >
    {lines.map((l, i) => {
      const parts = l.highlight && l.text.includes(l.highlight) ? l.text.split(l.highlight) : null;
      return (
        <div
          key={i}
          style={{
            ...heavy,
            fontSize: i === 0 ? B.size : B.size2 ?? B.size - 8,
            color: i === 0 ? T.white : T.highlightInk,
            textAlign: 'left',
            paddingLeft: B.padLeft ?? 64,
            paddingRight: B.padLeft ?? 64,
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
};

const LowerSubtitles: React.FC<{clauses: Clause[]}> = ({clauses}) => {
  const frame = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const t = (frame / fps) * 1000;
  const active = buildSubtitleChunks(clauses).find((c) => t >= c.startMs && t < c.endMs);
  if (!active || hideMedia()) return null;
  return (
    <div style={{position: 'absolute', left: T.geo.subtitle.side ?? 70, right: T.geo.subtitle.side ?? 70,
      bottom: T.geo.subtitle.bottom, textAlign: 'center'}}>
      <span
        style={{
          ...heavy,
          fontSize: T.geo.subtitle.size,
          color: T.white,
          background: T.barSubBg ?? 'rgba(3,8,16,0.74)',
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


// ---------------- poster：大字报（一句一屏） ----------------
// 跟 bleed 的区别：左对齐、字更大（geo.bigText.size）、关键字压高亮色块、
// 底部实色字幕带、顶部一行小引题。片头卡是整屏纯色块，是最"炸"的一套。

/** 从镜头 overlay 里取「小标 / 主字 / 副字」——各版式的卡字段名不同，统一兜一遍 */
const overlayText = (spec: Record<string, any> = {}) => ({
  label: spec.label || '',
  main: spec.amount || spec.number || spec.quote || spec.title || spec.keyword
        || spec.card_title || spec.name || '',
  sub: spec.desc || spec.subtitle || spec.caption || spec.card_body || '',
});

const PosterKicker: React.FC<{text: string}> = ({text}) => {
  const f = useAnimFrame();
  const o = interpolate(f, [0, 8], [0, 1], {extrapolateRight: 'clamp'});
  if (!text) return null;
  return (
    <div style={{position: 'absolute', left: 90, bottom: 320, opacity: o}}>
      <span style={{...heavy, fontSize: 30, color: T.onAccent, background: T.accent,
        padding: '4px 16px 8px 16px', letterSpacing: 2}}>{text}</span>
    </div>
  );
};

const PosterBig: React.FC<{label?: string; main?: string; sub?: string; onBlock?: boolean}> = ({
  label, main, sub, onBlock,
}) => {
  const f = useAnimFrame();
  const B = T.geo.bigText ?? {size: 168, subSize: 40, side: 90};
  const o = interpolate(f, [0, 9], [0, 1], {extrapolateRight: 'clamp'});
  const y = interpolate(f, [0, 13], [44, 0], {extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'flex-start',
      padding: `0 ${B.side}px`, opacity: o, transform: `translateY(${y}px)`}}>
      {label ? (
        <div style={{...heavy, fontSize: 34, color: T.onAccent, background: T.accentSoft,
          padding: '2px 14px 6px 14px', marginBottom: 30, letterSpacing: 3}}>{label}</div>
      ) : null}
      {main ? (
        <div style={{...heavy, fontSize: B.size, color: onBlock ? T.onAccent : T.white, lineHeight: 1.1,
          textShadow: onBlock ? 'none' : '0 6px 30px rgba(0,0,0,0.85)'}}>
          <span style={{background: onBlock ? 'transparent' : T.accent, padding: '0 18px 10px 18px',
            boxDecorationBreak: 'clone', WebkitBoxDecorationBreak: 'clone'}}>{main}</span>
        </div>
      ) : null}
      {sub ? (
        <div style={{fontSize: B.subSize, color: T.onMedia, marginTop: 32, lineHeight: 1.45,
          textShadow: '0 3px 16px rgba(0,0,0,0.85)'}}>{sub}</div>
      ) : null}
    </AbsoluteFill>
  );
};

const PosterCard: React.FC<{spec: Record<string, any>}> = ({spec}) => {
  const f = useAnimFrame();
  const C = T.geo.card ?? {side: 80, topPct: 34, size: 72, subSize: 36};
  const o = interpolate(f, [0, 8], [0, 1], {extrapolateRight: 'clamp'});
  const y = interpolate(f, [0, 12], [30, 0], {extrapolateRight: 'clamp'});
  const t = overlayText(spec);
  const compare = spec.left || spec.right;
  return (
    <div style={{position: 'absolute', left: C.side, right: C.side, top: `${C.topPct}%`,
      opacity: o, transform: `translateY(${y}px)`}}>
      <div style={{background: T.accent, padding: '34px 38px 38px 38px'}}>
        {t.label ? (
          <div style={{...heavy, fontSize: 30, color: T.onAccent, opacity: 0.8, letterSpacing: 3}}>{t.label}</div>
        ) : null}
        {t.main ? (
          <div style={{...heavy, fontSize: C.size, color: T.onAccent, lineHeight: 1.1, marginTop: 4}}>{t.main}</div>
        ) : null}
        {t.sub ? (
          <div style={{fontSize: C.subSize ?? 36, color: T.onAccent, opacity: 0.92, marginTop: 14}}>{t.sub}</div>
        ) : null}
      </div>
      {compare ? (
        <div style={{display: 'flex', gap: 0, marginTop: 6}}>
          {[spec.left, spec.right].map((side, i) => side ? (
            <div key={i} style={{flex: 1, background: i === 0 ? T.cardWhite : T.accent, padding: '22px 24px 26px 24px'}}>
              <div style={{...heavy, fontSize: 30, color: i === 0 ? T.redBright : T.onAccent}}>{side.head}</div>
              <div style={{fontSize: 32, color: i === 0 ? T.cardInk : T.onAccent, marginTop: 8}}>{side.body}</div>
            </div>
          ) : null)}
        </div>
      ) : null}
    </div>
  );
};

const PosterShot: React.FC<{shot: Shot; index: number}> = ({shot, index}) => {
  const fps = useVideoConfig().fps;
  const from = msToF(shot.startMs, fps);
  const dur = msToF(shot.endMs - shot.startMs, fps) + 1;
  const solid = shot.kind === 'title_card';         // 片头卡：整屏纯色 + 超大标题
  const isDesign = shot.kind === 'panel' || shot.kind === 'callout';
  const t = overlayText((shot.overlay ?? {}) as Record<string, any>);
  return (
    <Sequence from={from} durationInFrames={dur}>
      <AbsoluteFill style={{overflow: 'hidden'}}>
        {solid ? (
          <AbsoluteFill style={{background: `linear-gradient(150deg, ${T.accent} 0%, ${T.accentSoft} 100%)`}} />
        ) : (
          <>
            <PortraitMedia shot={shot} index={index} />
            <AbsoluteFill style={{background: 'rgba(10,10,12,0.60)'}} />
          </>
        )}
        {solid || shot.kind === 'quote_card' ? (
          <PosterBig label={t.label} main={t.main} sub={t.sub} onBlock={solid} />
        ) : null}
        {isDesign ? <PosterCard spec={(shot.overlay ?? {}) as Record<string, any>} /> : null}
        {shot.kind === 'footage' && shot.chapterLabel ? <PosterKicker text={shot.chapterLabel} /> : null}
      </AbsoluteFill>
    </Sequence>
  );
};

const PosterHeadline: React.FC<{lines: {text: string; highlight?: string}[]}> = ({lines}) => {
  const H = T.geo.headline;
  if (!lines.length) return null;
  const [first, ...rest] = lines;
  return (
    <div style={{position: 'absolute', left: 0, top: H.top, width: '100%', padding: '0 90px', boxSizing: 'border-box'}}>
      <div style={{...heavy, fontSize: H.size, color: T.white, lineHeight: 1.12,
        textShadow: '0 4px 20px rgba(0,0,0,0.85)'}}>{first.text}</div>
      {rest.map((l, i) => (
        <div key={i} style={{...heavy, fontSize: Math.round(H.size * 0.6), color: T.accentSoft,
          marginTop: H.lineGap ?? 14, textShadow: '0 4px 20px rgba(0,0,0,0.85)'}}>{l.text}</div>
      ))}
    </div>
  );
};

const PosterSubtitles: React.FC<{clauses: Clause[]}> = ({clauses}) => {
  const frame = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const t = (frame / fps) * 1000;
  const active = buildSubtitleChunks(clauses).find((c) => t >= c.startMs && t < c.endMs);
  if (!active || hideMedia()) return null;
  const S = T.geo.subtitle;
  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom: S.bottom, background: T.barBg ?? 'rgba(10,10,12,0.86)',
      borderTop: `5px solid ${T.accent}`, padding: '22px 90px 26px 90px'}}>
      <span style={{...heavy, fontSize: S.size, color: T.white, lineHeight: 1.25}}>{active.text}</span>
    </div>
  );
};

const PosterFooter: React.FC<{sources: string[]; disclaimer: string}> = ({sources, disclaimer}) => {
  const F = T.geo.footer;
  return (
    <div style={{position: 'absolute', left: 0, top: F.top, width: '100%', textAlign: 'center'}}>
      {sources.length ? (
        <div style={{fontSize: fitSize('资料来源：' + sources.join(' ｜ '), F.size, F.width), color: T.gray,
          whiteSpace: 'nowrap', textShadow: '0 2px 8px rgba(0,0,0,0.9)'}}>
          资料来源：{sources.join(' ｜ ')}
        </div>
      ) : null}
      {disclaimer ? (
        <div style={{fontSize: fitSize(disclaimer, F.size, F.width), color: T.grayDim,
          marginTop: 8, whiteSpace: 'nowrap', textShadow: '0 2px 8px rgba(0,0,0,0.9)'}}>{disclaimer}</div>
      ) : null}
    </div>
  );
};

/**
 * 字幕底衬（只出在底板层）：分轨草稿里字幕是剪映文本轨，只有字没有底。
 * 这条带子的高度是恒定的——字幕切分不超过 12 字，74px 字号下一行放得下——
 * 所以可以精确地烘进底板，草稿看起来才和成片一致。
 */
const PosterSubtitlePlate: React.FC = () => {
  const S = T.geo.subtitle;
  const plateH = 22 + 26 + Math.round(S.size * 1.25);
  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom: S.bottom,
      height: plateH, background: T.barBg ?? 'rgba(10,10,12,0.86)',
      borderTop: `5px solid ${T.accent}`}} />
  );
};

const PosterVideo: React.FC<NiwoProps> = (props) => (
  <AbsoluteFill data-vg-frame="1"
    style={{background: hideMedia() ? 'transparent' : T.pageBg ?? T.bgTop, fontFamily: T.font}}>
    <FontFace />
    {isCard() ? null : isBase() ? <PosterSubtitlePlate /> : null}
    {isBase() ? null : props.shots.map((shot, i) => (
      <PosterShot key={i} shot={shot} index={i} />
    ))}
    {isCard() ? null : <PosterHeadline lines={props.headline.lines} />}
    {props.showSubtitles !== false ? <PosterSubtitles clauses={props.clauses} /> : null}
    {isCard() ? null : <PosterFooter sources={props.sources} disclaimer={props.disclaimer} />}
  </AbsoluteFill>
);

// ---------------- data：数据面板（左数据 / 右素材的双栏板） ----------------
// 跟别的骨架最不一样的地方：素材不是铺满，而是嵌在面板右半边的窗口里，
// 左边留给数据卡/榜单/金句。整条片子的"界面感"最强。

const DataHeader: React.FC<{lines: {text: string; highlight?: string}[]}> = ({lines}) => {
  const H = T.geo.headline;
  if (!lines.length) return null;
  return (
    <div style={{position: 'absolute', left: 0, top: H.top, width: '100%', padding: '0 70px', boxSizing: 'border-box'}}>
      {lines.map((l, i) => {
        const parts = l.highlight && l.text.includes(l.highlight) ? l.text.split(l.highlight) : null;
        return (
          <div key={i} style={{...heavy, fontSize: i === 0 ? H.size : Math.round(H.size * 0.78),
            color: i === 0 ? T.ink : T.mutedInk, lineHeight: 1.15,
            marginTop: i === 0 ? 0 : H.lineGap ?? 12}}>
            {parts ? (
              <>
                {parts[0]}
                <span style={{background: T.highlightBg, color: T.highlightInk, padding: '0 10px 4px', marginLeft: 6}}>
                  {l.highlight}</span>
                {parts[1]}
              </>
            ) : l.text}
          </div>
        );
      })}
    </div>
  );
};

/** 素材镜头左栏：把这一拍正在念的话摊在面板上，像仪表盘的当前读数 */
const DataRunningText: React.FC<{text: string; chapterLabel?: string}> = ({text, chapterLabel}) => {
  const f = useAnimFrame();
  const P = T.geo.panel!;
  const W = T.geo.mediaWin ?? {left: 40};
  const o = interpolate(f, [0, 8], [0, 1], {extrapolateRight: 'clamp'});
  const y = interpolate(f, [0, 12], [18, 0], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', left: P.left + 46, top: P.top + 56,
      width: Math.max(200, W.left - 92), opacity: o, transform: `translateY(${y}px)`}}>
      {chapterLabel ? (
        <div style={{...heavy, fontSize: 24, color: T.onAccent, background: T.accent,
          display: 'inline-block', padding: '3px 12px 7px 12px', letterSpacing: 2, marginBottom: 20}}>
          {chapterLabel}</div>
      ) : null}
      <div style={{...heavy, fontSize: 56, color: T.ink, lineHeight: 1.32}}>{text}</div>
      <div style={{width: 120, height: 8, background: T.accent, marginTop: 26}} />
    </div>
  );
};

const DataCard: React.FC<{spec: Record<string, any>; kind: string; chapterLabel?: string}> = ({
  spec, kind, chapterLabel,
}) => {
  const f = useAnimFrame();
  const C = T.geo.card ?? {size: 62, subSize: 32};
  const P = T.geo.panel!;
  const W = T.geo.mediaWin ?? {left: 40};
  const o = interpolate(f, [0, 8], [0, 1], {extrapolateRight: 'clamp'});
  const y = interpolate(f, [0, 12], [22, 0], {extrapolateRight: 'clamp'});
  const t = overlayText(spec);
  const rows: {name?: string; value?: string; delta?: string; text?: string; highlight?: boolean}[] =
    spec.rows || spec.table?.rows || [];
  const big = kind === 'title_card' || kind === 'quote_card';
  return (
    <div style={{position: 'absolute', left: P.left + 46, top: P.top + 56,
      width: Math.max(200, W.left - 92), opacity: o, transform: `translateY(${y}px)`}}>
      {chapterLabel ? (
        <div style={{...heavy, fontSize: 24, color: T.accentSoft, letterSpacing: 3, marginBottom: 14}}>{chapterLabel}</div>
      ) : null}
      {t.label ? (
        <div style={{...heavy, fontSize: 28, color: T.onAccent, background: T.accent,
          display: 'inline-block', padding: '2px 12px 6px 12px', marginBottom: 16}}>{t.label}</div>
      ) : null}
      {t.main ? (
        <div style={{...heavy, fontSize: big ? C.size : C.size + 16, color: T.ink, lineHeight: 1.12}}>{t.main}</div>
      ) : null}
      {t.sub ? (
        <div style={{fontSize: C.subSize ?? 32, color: T.mutedInk, marginTop: 12, lineHeight: 1.4}}>{t.sub}</div>
      ) : null}
      {rows.length ? (
        <div style={{marginTop: 20, borderTop: `2px solid ${T.cardLine}`}}>
          {rows.slice(0, 5).map((r, i) => (
            <div key={i} style={{display: 'flex', alignItems: 'baseline', gap: 10, padding: '10px 0',
              borderBottom: `1px solid ${T.cardLine}`, background: r.highlight ? hexA(T.accent, 0.16) : 'transparent'}}>
              <span style={{...heavy, fontSize: 30, color: T.ink, flex: 1}}>{r.name || r.text}</span>
              {r.value ? <span style={{...heavy, fontSize: 32, color: r.highlight ? T.accent : T.ink}}>{r.value}</span> : null}
              {r.delta ? <span style={{fontSize: 26, color: T.teal, width: 96, textAlign: 'right'}}>{r.delta}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
      {spec.left || spec.right ? (
        <div style={{marginTop: 20, display: 'flex', flexDirection: 'column', gap: 12}}>
          {[spec.left, spec.right].map((side, i) => side ? (
            <div key={i} style={{background: hexA(i === 0 ? T.cardInk : T.accent, 0.10),
              borderLeft: `5px solid ${i === 0 ? T.teal : T.accent}`, padding: '14px 16px'}}>
              <div style={{...heavy, fontSize: 28, color: i === 0 ? T.ink : T.accent}}>{side.head}</div>
              <div style={{fontSize: 28, color: T.mutedInk, marginTop: 4}}>{side.body}</div>
            </div>
          ) : null)}
        </div>
      ) : null}
    </div>
  );
};

const DataShot: React.FC<{shot: Shot; index: number; runningText: string}> = ({shot, index, runningText}) => {
  const fps = useVideoConfig().fps;
  const from = msToF(shot.startMs, fps);
  const dur = msToF(shot.endMs - shot.startMs, fps) + 1;
  const P = T.geo.panel!;
  const W = T.geo.mediaWin!;
  const showCard = shot.kind !== 'footage';
  return (
    <Sequence from={from} durationInFrames={dur}>
      <AbsoluteFill style={{overflow: 'hidden'}}>
        {/* 媒体窗：素材轨的落点。card 层不放底衬——卡片层在素材之上，一层灰底会把画面糊掉 */}
        <div style={{position: 'absolute', left: P.left + W.left, top: P.top + W.top,
          width: W.width, height: W.height, overflow: 'hidden', borderRadius: 12,
          background: isCard() ? 'transparent' : hexA(T.cardInk, 0.06)}}>
          <PortraitMedia shot={shot} index={index} />
        </div>
        {showCard ? (
          <DataCard spec={(shot.overlay ?? {}) as Record<string, any>}
                    kind={shot.kind} chapterLabel={shot.chapterLabel} />
        ) : (
          <DataRunningText text={runningText} chapterLabel={shot.chapterLabel} />
        )}
      </AbsoluteFill>
    </Sequence>
  );
};

/** 面板底部的进度轨：当前拍到第几拍，像仪表盘的位置读数 */
const DataProgress: React.FC<{shots: Shot[]}> = ({shots}) => {
  const frame = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const t = (frame / fps) * 1000;
  const P = T.geo.panel!;
  const idx = shots.findIndex((s) => t >= s.startMs && t < s.endMs);
  if (!shots.length) return null;
  const cur = Math.max(0, idx);
  return (
    <div style={{position: 'absolute', left: P.left + 46, top: P.top + P.height - 96,
      width: P.width - 92, display: 'flex', alignItems: 'center', gap: 16}}>
      <span style={{...heavy, fontSize: 26, color: T.mutedInk, letterSpacing: 1}}>
        {String(cur + 1).padStart(2, '0')}<span style={{opacity: 0.5}}> / {String(shots.length).padStart(2, '0')}</span>
      </span>
      <div style={{display: 'flex', gap: 4, flex: 1}}>
        {shots.map((_, i) => (
          <span key={i} style={{flex: 1, height: 10, background: i <= cur ? T.accent : T.cardLine}} />
        ))}
      </div>
    </div>
  );
};

const DataVideo: React.FC<NiwoProps> = (props) => {
  const runningOf = (s: Shot) => props.clauses
    .filter((c) => c.endMs > s.startMs && c.startMs < s.endMs)
    .map((c) => c.text).join('');
  const P = T.geo.panel!;
  const hole = mediaRect();
  return (
    <AbsoluteFill data-vg-frame="1"
      style={{background: hideMedia() ? 'transparent' : T.pageBg ?? T.bgTop, fontFamily: T.font}}>
      <FontFace />
      {/* 页面底：分轨导出时底板压在素材之上，必须挖掉媒体窗，否则素材整块被盖住 */}
      {isCard() ? null : isBase() ? (
        <ChromeClip hole={hole}>
          <AbsoluteFill style={{background: T.pageBg ?? T.bgTop}} />
        </ChromeClip>
      ) : null}
      {/* 面板：card 层不出——它是整片不变的包装层，出在卡片层会把素材和底板一起盖住 */}
      {isCard() ? null : isBase() ? (
        <RectWithHole rect={P} hole={hole} radius={P.radius ?? 20} fill={{background: T.panel}} />
      ) : (
        <div style={{position: 'absolute', left: P.left, top: P.top,
          width: P.width, height: P.height,
          borderRadius: P.radius ?? 20, background: T.panel,
          border: `1px solid ${T.cardLine}`, boxShadow: T.paperShadow}} />
      )}
      {isBase() ? null : props.shots.map((shot, i) => (
        <DataShot key={i} shot={shot} index={i} runningText={runningOf(shot)} />
      ))}
      {/* 进度轨每镜一个状态，要跟着卡片层走（base 只有一张静止帧，放进去会定格） */}
      {isBase() ? null : <DataProgress shots={props.shots} />}
      {isCard() ? null : <DataHeader lines={props.headline.lines} />}
      {props.showSubtitles !== false ? <DataSubtitles clauses={props.clauses} /> : null}
      {isCard() ? null : <Footer sources={props.sources} disclaimer={props.disclaimer} />}
    </AbsoluteFill>
  );
};

const DataSubtitles: React.FC<{clauses: Clause[]}> = ({clauses}) => {
  const frame = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const t = (frame / fps) * 1000;
  const active = buildSubtitleChunks(clauses).find((c) => t >= c.startMs && t < c.endMs);
  if (!active || hideMedia()) return null;
  const S = T.geo.subtitle;
  return (
    <div style={{position: 'absolute', left: S.side ?? 80, right: S.side ?? 80, bottom: S.bottom, textAlign: 'center'}}>
      <span style={{...heavy, fontSize: S.size, color: T.white, background: T.barSubBg ?? 'rgba(6,12,20,0.80)',
        borderLeft: `6px solid ${T.accent}`, padding: '10px 26px 14px 26px', lineHeight: 1.3}}>
        {active.text}
      </span>
    </div>
  );
};

// ---------------- v11 new card templates (from demo research) ----------------

const StatCard: React.FC<{spec: any}> = ({spec}) => {
  const f = useAnimFrame();
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
  const f = useAnimFrame();
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
  const f = useAnimFrame();
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
  const f = useAnimFrame();
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
