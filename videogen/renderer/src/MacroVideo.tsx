import React from 'react';
import {AbsoluteFill, Img, Sequence, staticFile, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {FontFace, buildSubtitleChunks, hideMedia, isBase, isCard} from './NiwoVideo';
import type {NiwoProps} from './NiwoVideo';
import {T} from './skin';

/**
 * macro——「宏观棱镜」复刻模板（数据工作室风）。
 *
 * 三条铁律（按原片逐帧测量，_tools/_study/macro_breakdown.md）：
 * 1) 固定件全程钉死：暗背景图（近黑）+ 顶部一行金色选题标题 + 左上频道标
 *    + 中下波形口播件（白圆+跳动的金色波形条）+ 底部口播字幕。
 * 2) 舞台 = 章节状态机：kicker（小金字）→ 特粗金大标题 → 灰副标，
 *    正文是一个 block（list/bars/line/big/cards）逐元素弹出、先弹的不退场。
 * 3) 全片只有金 #e8a833、白、灰白三种颜色，不出现别的强调色。
 */

const W = 1080;
const GOLD = '#e8a833';
const INK_DIM = 'rgba(255,255,255,0.55)';
const LINE_DIM = 'rgba(255,255,255,0.30)';
const LEFT = 95;
const RIGHT = 985;

const heavy: React.CSSProperties = {fontFamily: T.font, fontWeight: 900};
const msToF = (ms: number, fps: number) => Math.round((ms / 1000) * fps);

/** 章节内的一个可弹元素：atMs 相对该章开头 */
type Beat = {atMs: number};
type ListRow = Beat & {text: string; gold?: boolean};
type BarRow = Beat & {name: string; value: number; display: string};
type CardRow = Beat & {text: string; gold?: boolean};
type LinePoint = {x: string; y: number; label?: string};
type Block =
  | {type: 'list'; rows: ListRow[]}
  | {type: 'bars'; rows: BarRow[]; axis?: boolean; zeroX?: number}
  | {type: 'line'; points: LinePoint[]; ticks?: number[]; spanMs: number; unit?: string}
  | {type: 'big'; number: string; label: string; atMs: number; deco?: 'dots'}
  | {type: 'cards'; rows: CardRow[]}
  | {type: 'grid'; items: Beat & {title: string; sub?: string}[]; cols?: number}
  | {type: 'vs'; left: {label: string; lines: string[]}; right: {label: string; lines: string[]}; atMs: number}
  | {type: 'arrow'; from: string; to: string; note?: string; atMs: number};
export type MacroStage = {
  mode: 'macro';
  kicker?: string;
  title: string;
  sub?: string;
  block?: Block;
  caption?: {text: string; atMs: number};
  rule?: boolean;
};

const Enter: React.FC<{children: React.ReactNode; at?: number; y?: number; pop?: boolean}> = ({children, at = 0, y = 22, pop = false}) => {
  const f = useCurrentFrame();
  const a = interpolate(f, [at, at + 9], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const ty = interpolate(f, [at, at + 11], [y, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const s = pop ? interpolate(f, [at, at + 10], [0.94, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 1;
  return <div style={{opacity: a, transform: `translateY(${ty}px) scale(${s})`}}>{children}</div>;
};

// ---------------- 固定件 ----------------

/** 暗背景：一张压到近黑的图，隐约可见纹理 */
const Backdrop: React.FC<{bg?: string}> = ({bg}) => (
  <AbsoluteFill style={{background: '#04080a'}}>
    {bg ? (
      <Img src={staticFile(`media/${bg}`)} style={{
        position: 'absolute', inset: 0, width: '100%', height: '100%',
        objectFit: 'cover', opacity: 0.9, filter: 'saturate(0.5) brightness(0.85)',
      }} />
    ) : null}
    <AbsoluteFill style={{background: 'rgba(2,7,8,0.88)'}} />
    <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(2,6,8,0.5), rgba(2,6,8,0) 30%, rgba(2,6,8,0) 62%, rgba(2,6,8,0.72))'}} />
  </AbsoluteFill>
);

/** 左上频道标：圆标 + @频道名 */
const ChannelMark: React.FC<{name: string}> = ({name}) => (
  <div style={{position: 'absolute', left: 52, top: 44, display: 'flex', alignItems: 'center', gap: 14}}>
    <span style={{width: 58, height: 58, borderRadius: '50%', background: 'rgba(255,255,255,0.14)',
      border: '1px solid rgba(255,255,255,0.25)', display: 'flex', alignItems: 'center', justifyContent: 'center',
      ...heavy, fontSize: 26, color: '#ffffff'}}>棱</span>
    <span style={{fontSize: 30, color: 'rgba(255,255,255,0.85)'}}>{name}</span>
  </div>
);

/** 顶部金色选题标题（全程钉死）：长标题自适应缩小 */
const SeriesTitle: React.FC<{text: string}> = ({text}) => {
  const size = text.length > 18 ? 42 : text.length > 14 ? 48 : 56;
  return (
    <div style={{position: 'absolute', top: 306, left: 50, right: 50, textAlign: 'center',
      ...heavy, fontSize: size, lineHeight: 1.15, color: GOLD, letterSpacing: 2}}>
      {text}
    </div>
  );
};

/** 波形口播件：白圆 + 金色波形条 + @频道名 */
const VoiceWave: React.FC<{name: string}> = ({name}) => {
  const f = useCurrentFrame();
  const bars = React.useMemo(() => {
    let s = 12345;
    const rnd = () => {
      s = (s * 1103515245 + 12345) % 2147483648;
      return s / 2147483648;
    };
    return Array.from({length: 46}, (_, i) => ({ph: rnd() * Math.PI * 2, sp: 0.5 + rnd(), base: 8 + rnd() * 30, key: i}));
  }, []);
  return (
    <div style={{position: 'absolute', top: 1330, left: 0, right: 0, display: 'flex', flexDirection: 'column', alignItems: 'center'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 20}}>
        <span style={{width: 86, height: 86, borderRadius: '50%', background: 'rgba(255,255,255,0.92)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          ...heavy, fontSize: 30, color: '#22262b'}}>棱</span>
        <span style={{display: 'flex', alignItems: 'center', gap: 3, height: 56}}>
          {bars.map((b) => {
            const h = Math.max(6, b.base + Math.sin(f * 0.11 * b.sp + b.ph) * 23);
            return <span key={b.key} style={{width: 4, height: h, borderRadius: 2, background: GOLD, opacity: 0.95}} />;
          })}
        </span>
      </div>
      <div style={{marginTop: 16, fontSize: 24, color: GOLD}}>{name}</div>
    </div>
  );
};

/** 底部口播字幕 */
const BottomSubtitle: React.FC<{clauses: {text: string; startMs: number; endMs: number}[]}> = ({clauses}) => {
  const frame = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const t = (frame / fps) * 1000;
  if (hideMedia()) return null;
  const active = buildSubtitleChunks(clauses).find((c) => t >= c.startMs && t < c.endMs);
  if (!active) return null;
  return (
    <div style={{position: 'absolute', left: 70, right: 70, top: 1602, textAlign: 'center',
      ...heavy, fontSize: 36, color: '#ffffff', lineHeight: 1.35, textShadow: '0 2px 12px rgba(0,0,0,0.8)'}}>
      {active.text}
    </div>
  );
};

// ---------------- 舞台 blocks ----------------

const BlockList: React.FC<{rows: ListRow[]; fps: number}> = ({rows, fps}) => (
  <div style={{position: 'absolute', left: LEFT, top: 722, display: 'flex', flexDirection: 'column', gap: 36}}>
    {rows.map((r, i) => (
      <Enter key={i} at={msToF(r.atMs, fps)} pop>
        <div style={{...heavy, fontSize: 56, color: r.gold ? GOLD : '#ffffff', letterSpacing: 2}}>{r.text}</div>
      </Enter>
    ))}
  </div>
);

/** 发散条形图：零轴居中偏左，正条向右 / 负条向左，值字统一右对齐 */
const BlockBars: React.FC<{rows: BarRow[]; fps: number; axis?: boolean; zeroX?: number}> = ({rows, fps, axis = true, zeroX = 530}) => {
  const f = useCurrentFrame();
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.value)), 0.001);
  const span = Math.max(zeroX - LEFT, RIGHT - zeroX) - 60;
  return (
    <div style={{position: 'absolute', left: 0, top: 700, width: W}}>
      {axis ? (
        <div style={{position: 'absolute', left: zeroX, top: 8, height: rows.length * 140 - 30, width: 2,
          background: LINE_DIM}}>
          <span style={{position: 'absolute', left: 10, bottom: -8, fontSize: 22, color: INK_DIM}}>0</span>
        </div>
      ) : null}
      {rows.map((r, i) => {
        const at = msToF(r.atMs, fps);
        const w = (Math.abs(r.value) / maxAbs) * span;
        const grow = interpolate(f, [at + 3, at + 14], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
        const barW = Math.max(w * grow, 0);
        return (
          <div key={i} style={{position: 'absolute', top: 20 + i * 140, left: 0, width: W}}>
            {i > 0 ? (
              <div style={{position: 'absolute', top: -22, left: LEFT, width: RIGHT - LEFT, height: 1,
                background: 'rgba(255,255,255,0.14)'}} />
            ) : null}
            <div style={{position: 'absolute', left: LEFT, top: 0, display: 'flex', justifyContent: 'space-between', width: RIGHT - LEFT}}>
              <span style={{fontSize: 32, color: 'rgba(255,255,255,0.92)'}}>{r.name}</span>
              <Enter at={at} y={10}>
                <span style={{...heavy, fontSize: 56, color: GOLD, letterSpacing: 1}}>{r.display.replace(/-/g, '−')}</span>
              </Enter>
            </div>
            <div style={{position: 'absolute', top: 66, left: r.value >= 0 ? zeroX : zeroX - barW,
              width: barW, height: 19, borderRadius: 4, background: GOLD}} />
          </div>
        );
      })}
      {axis ? (
        <div style={{position: 'absolute', top: rows.length * 140 - 10, left: LEFT, width: RIGHT - LEFT,
          display: 'flex', justifyContent: 'space-between', fontSize: 24, color: INK_DIM}}>
          <span>← 下降</span>
          <span>增长 →</span>
        </div>
      ) : null}
    </div>
  );
};

/** 时间序列折线：逐点展开 + 每点标值 */
const BlockLine: React.FC<{points: LinePoint[]; ticks?: number[]; spanMs: number; unit?: string; fps: number}> = ({points, ticks, spanMs, unit, fps}) => {
  const frame = useCurrentFrame();
  const boxL = 150;
  const boxR = RIGHT;
  const boxT = 716;
  const boxB = 1136;
  const ys = points.map((p) => p.y);
  const lo = Math.min(...(ticks ?? ys), ...ys);
  const hi = Math.max(...(ticks ?? ys), ...ys);
  const yOf = (v: number) => boxB - ((v - lo) / (hi - lo)) * (boxB - boxT);
  const xOf = (i: number) => boxL + (i / Math.max(points.length - 1, 1)) * (boxR - boxL);
  const spanF = Math.max(Math.round((spanMs / 1000) * fps), points.length * 3);
  const drawn = Math.min(points.length - 1, Math.floor((frame / spanF) * (points.length - 1) * 1.12));
  const path = points.slice(0, drawn + 2).map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(i)},${yOf(p.y)}`).join(' ');
  return (
    <div style={{position: 'absolute', left: 0, top: 0, width: W}}>
      {(ticks ?? []).map((tk, i) => (
        <div key={i} style={{position: 'absolute', left: 88, top: yOf(tk) - 14, fontSize: 22, color: INK_DIM, width: 50, textAlign: 'right'}}>
          {tk}
        </div>
      ))}
      {(ticks ?? []).map((tk, i) => (
        <div key={`g${i}`} style={{position: 'absolute', left: boxL, right: W - boxR, top: yOf(tk), height: 1,
          background: 'rgba(255,255,255,0.10)'}} />
      ))}
      <svg width={W} height={1920} style={{position: 'absolute', left: 0, top: 0}}>
        {/* L 形轴线 */}
        <line x1={boxL} y1={boxT - 6} x2={boxL} y2={boxB} stroke="rgba(255,255,255,0.45)" strokeWidth={2} />
        <line x1={boxL} y1={boxB} x2={boxR} y2={boxB} stroke="rgba(255,255,255,0.45)" strokeWidth={2} />
        <path d={path} fill="none" stroke={GOLD} strokeWidth={5} strokeLinejoin="round" strokeLinecap="round" />
        {points.slice(0, drawn + 1).map((p, i) => (
          <circle key={i} cx={xOf(i)} cy={yOf(p.y)} r={6} fill={GOLD} />
        ))}
      </svg>
      {points.slice(0, drawn + 1).map((p, i) => {
        // 原片的点值标签上下交替摆放，避免相邻标签互相压字
        const above = i % 2 === 0;
        return (
          <div key={`v${i}`} style={{position: 'absolute', left: xOf(i) - 34,
            top: yOf(p.y) + (above ? -54 : 22), width: 68,
            textAlign: 'center', fontSize: 22, fontWeight: 700, color: GOLD}}>
            {p.label ?? p.y}
          </div>
        );
      })}
      {points.map((p, i) => (
        <div key={`x${i}`} style={{position: 'absolute', left: xOf(i) - 16, top: boxB + 18, width: 90,
          textAlign: 'right', fontSize: 19, color: INK_DIM, opacity: i % 2 === 0 ? 1 : 0.6,
          transform: 'rotate(-38deg)', transformOrigin: 'right top'}}>
          {p.x}
        </div>
      ))}
      {/* 跨年分段标注（原片轴下方有 2025年 / 2026年） */}
      {(() => {
        const yi = points.findIndex((p) => p.x.startsWith('1-2月') || p.x === '2月');
        const split = yi > 0 ? xOf(yi) : boxL + (boxR - boxL) * 0.3;
        return (
          <>
            <div style={{position: 'absolute', left: boxL, top: boxB + 52, fontSize: 22, color: 'rgba(255,255,255,0.75)'}}>2025年</div>
            <div style={{position: 'absolute', left: split + 30, top: boxB + 52, fontSize: 22, color: 'rgba(255,255,255,0.75)'}}>2026年</div>
          </>
        );
      })()}
      {unit ? <div style={{position: 'absolute', left: boxR - 60, top: boxT - 44, fontSize: 22, color: INK_DIM}}>({unit})</div> : null}
    </div>
  );
};

/** 大数字：超大金字 + 标签（+可选金色方块饰带） */
const BlockBig: React.FC<{number: string; label: string; atMs: number; deco?: 'dots'; fps: number}> = ({number, label, atMs, deco, fps}) => (
  <div style={{position: 'absolute', left: LEFT, top: 760, width: RIGHT - LEFT}}>
    <Enter at={msToF(atMs, fps)} y={16}>
      <div style={{...heavy, fontSize: number.length > 7 ? 96 : 128, color: GOLD, letterSpacing: 2, lineHeight: 1.1}}>
        {number}
      </div>
      <div style={{marginTop: 14, fontSize: 32, color: 'rgba(255,255,255,0.85)'}}>{label}</div>
      {deco === 'dots' ? (
        <div style={{marginTop: 22, display: 'flex', gap: 6}}>
          {Array.from({length: 46}, (_, i) => (
            <span key={i} style={{width: 11, height: 11, background: i < 40 ? GOLD : 'rgba(232,168,51,0.22)'}} />
          ))}
        </div>
      ) : null}
    </Enter>
  </div>
);

/** 细框卡列表：白框深底逐张弹，gold 行金框金字 */
const BlockCards: React.FC<{rows: CardRow[]; fps: number}> = ({rows, fps}) => (
  <div style={{position: 'absolute', left: LEFT, top: 716, width: RIGHT - LEFT}}>
    {rows.map((r, i) => {
      const prev = rows.slice(0, i);
      const at = msToF(r.atMs, fps);
      return (
        <div key={i} style={{position: 'absolute', top: prev.length * 136, left: 0, width: '100%'}}>
          <Enter at={at} y={18} pop>
            <div style={{
              border: `2px solid ${r.gold ? GOLD : 'rgba(255,255,255,0.45)'}`,
              background: 'rgba(5,10,11,0.55)', borderRadius: 6, padding: '26px 30px'}}>
              <span style={{...heavy, fontSize: 36, color: r.gold ? GOLD : '#ffffff', letterSpacing: 1}}>{r.text}</span>
            </div>
          </Enter>
        </div>
      );
    })}
  </div>
);

/** 网格卡：2-3 列并列概念（修路/建园区/盖大楼…） */
const BlockGrid: React.FC<{items: {title: string; sub?: string; atMs: number}[]; cols?: number; fps: number}> = ({items, cols = 2, fps}) => {
  const gap = 24;
  const cw = (RIGHT - LEFT - gap * (cols - 1)) / cols;
  return (
    <div style={{position: 'absolute', left: LEFT, top: 726, width: RIGHT - LEFT}}>
      {items.map((it, i) => {
        const cx = (i % cols) * (cw + gap);
        const cy = Math.floor(i / cols) * 176;
        return (
          <div key={i} style={{position: 'absolute', left: cx, top: cy, width: cw}}>
            <Enter at={msToF(it.atMs, fps)} y={16} pop>
              <div style={{border: '2px solid rgba(255,255,255,0.45)', background: 'rgba(5,10,11,0.55)',
                borderRadius: 6, padding: '24px 26px', minHeight: 128}}>
                {it.sub ? <div style={{fontSize: 21, color: INK_DIM, letterSpacing: 3, marginBottom: 8}}>
                  {String(i + 1).padStart(2, '0')}</div> : null}
                <div style={{...heavy, fontSize: 32, color: '#ffffff', lineHeight: 1.3}}>{it.title}</div>
                {it.sub ? <div style={{fontSize: 24, color: 'rgba(255,255,255,0.6)', marginTop: 8}}>{it.sub}</div> : null}
              </div>
            </Enter>
          </div>
        );
      })}
    </div>
  );
};

/** 对比双栏：新旧/内外两个阵营并置 */
const BlockVs: React.FC<{left: {label: string; lines: string[]}; right: {label: string; lines: string[]}; atMs: number; fps: number}> = ({left, right, atMs, fps}) => {
  const at = msToF(atMs, fps);
  const col = (v: {label: string; lines: string[]}, gold: boolean, delay: number) => (
    <Enter at={at + delay} y={16} pop>
      <div style={{border: `2px solid ${gold ? GOLD : 'rgba(255,255,255,0.45)'}`,
        background: 'rgba(5,10,11,0.55)', borderRadius: 6, padding: '26px 28px', minHeight: 210}}>
        <div style={{fontSize: 21, color: gold ? GOLD : INK_DIM, letterSpacing: 3}}>{v.label}</div>
        <div style={{marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10}}>
          {v.lines.map((ln, i) => (
            <div key={i} style={{...heavy, fontSize: 30, color: gold ? GOLD : '#ffffff', lineHeight: 1.3}}>{ln}</div>
          ))}
        </div>
      </div>
    </Enter>
  );
  return (
    <div style={{position: 'absolute', left: LEFT, top: 726, width: RIGHT - LEFT, display: 'flex', gap: 24}}>
      <div style={{flex: 1}}>{col(left, false, 0)}</div>
      <div style={{flex: 1}}>{col(right, true, 8)}</div>
    </div>
  );
};

/** 时间箭头：现在投入 → 很多年以后 */
const BlockArrow: React.FC<{from: string; to: string; note?: string; atMs: number; fps: number}> = ({from, to, note, atMs, fps}) => {
  const at = msToF(atMs, fps);
  const f = useCurrentFrame();
  const grow = interpolate(f, [at + 6, at + 34], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', left: LEFT, top: 780, width: RIGHT - LEFT}}>
      <Enter at={at} y={12}>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}>
          <span style={{...heavy, fontSize: 30, color: '#ffffff'}}>{from}</span>
          <span style={{...heavy, fontSize: 30, color: GOLD}}>{to}</span>
        </div>
      </Enter>
      <div style={{marginTop: 22, height: 3, background: 'rgba(255,255,255,0.18)', position: 'relative'}}>
        <div style={{width: `${grow * 100}%`, height: 3, background: GOLD}} />
        <div style={{position: 'absolute', right: `${(1 - grow) * 100}%`, top: -7, width: 17, height: 17,
          borderTop: `3px solid ${GOLD}`, borderRight: `3px solid ${GOLD}`, transform: 'rotate(45deg)',
          opacity: grow > 0.02 ? 1 : 0}} />
      </div>
      {note ? (
        <Enter at={at + 30} y={12}>
          <div style={{marginTop: 34, border: '2px solid rgba(255,255,255,0.45)', borderRadius: 6,
            background: 'rgba(5,10,11,0.55)', padding: '22px 28px'}}>
            <span style={{...heavy, fontSize: 30, color: '#ffffff'}}>{note}</span>
          </div>
        </Enter>
      ) : null}
    </div>
  );
};

// ---------------- 章节舞台 ----------------

const ChapterStage: React.FC<{startMs: number; endMs: number; stage: MacroStage}> = ({startMs, endMs, stage: st}) => {
  const f = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const headIn = interpolate(f, [2, 12], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const relMs = (absMs: number) => Math.max(0, absMs - startMs);
  const block = st.block;
  return (
    <AbsoluteFill>
      {st.kicker ? (
        <div style={{position: 'absolute', left: LEFT, top: 466, fontSize: 25, fontWeight: 700, color: GOLD,
          letterSpacing: 5, opacity: headIn}}>{st.kicker}</div>
      ) : null}
      <div style={{position: 'absolute', left: LEFT, top: 516, right: 60,
        ...heavy, fontSize: 78, lineHeight: 1.14, color: GOLD, letterSpacing: 2,
        opacity: headIn, transform: `translateY(${(1 - headIn) * 18}px)`}}>
        {st.title}
      </div>
      {st.sub ? (
        <div style={{position: 'absolute', left: LEFT, top: 646, fontSize: 30, color: INK_DIM, opacity: headIn}}>
          {st.sub}
        </div>
      ) : null}

      {block?.type === 'list' ? <BlockList rows={block.rows} fps={fps} /> : null}
      {block?.type === 'bars' ? <BlockBars rows={block.rows} fps={fps} axis={block.axis} zeroX={block.zeroX} /> : null}
      {block?.type === 'line' ? (
        <BlockLine points={block.points} ticks={block.ticks} spanMs={block.spanMs} unit={block.unit} fps={fps} />
      ) : null}
      {block?.type === 'big' ? <BlockBig number={block.number} label={block.label} atMs={relMs(block.atMs)} deco={block.deco} fps={fps} /> : null}
      {block?.type === 'cards' ? <BlockCards rows={block.rows} fps={fps} /> : null}
      {block?.type === 'grid' ? <BlockGrid items={block.items} cols={block.cols} fps={fps} /> : null}
      {block?.type === 'vs' ? <BlockVs left={block.left} right={block.right} atMs={relMs(block.atMs)} fps={fps} /> : null}
      {block?.type === 'arrow' ? <BlockArrow from={block.from} to={block.to} note={block.note} atMs={relMs(block.atMs)} fps={fps} /> : null}

      {st.caption ? (
        <div style={{position: 'absolute', left: LEFT, top: 1216, width: RIGHT - LEFT}}>
          <Enter at={msToF(relMs(st.caption.atMs), fps)} y={12}>
            <span style={{...heavy, fontSize: 30, color: GOLD, letterSpacing: 1}}>{st.caption.text}</span>
          </Enter>
        </div>
      ) : null}
      {st.rule ? <GrowingRule at={msToF(relMs((st.caption?.atMs ?? endMs) + 600), fps)} /> : null}
    </AbsoluteFill>
  );
};

/** 章节尾金线：从左向右生长（原片是生长动画，不是瞬显） */
const GrowingRule: React.FC<{at: number}> = ({at}) => {
  const f = useCurrentFrame();
  const w = interpolate(f, [at, at + 22], [0, RIGHT - LEFT], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', left: LEFT, top: 1272, width: w, height: 3, background: GOLD, opacity: 0.9}} />
  );
};

// ---------------- 主入口 ----------------
export const MacroVideo: React.FC<NiwoProps> = (props) => {
  const fps = useVideoConfig().fps;
  const bg = props.bgImage;
  const channel = props.channelName ?? '@宏观棱镜';
  return (
    <AbsoluteFill style={{background: '#04080a', fontFamily: T.font}}>
      <FontFace />
      {isCard() ? null : <Backdrop bg={bg} />}
      {isCard() ? null : <ChannelMark name={channel} />}
      {isCard() ? null : <SeriesTitle text={props.headline.lines[0]?.text ?? ''} />}
      {isBase() ? null : props.shots.map((shot, i) => {
        const st = shot.macroStage;
        if (!st || st.mode !== 'macro') return null;
        return (
          <Sequence key={i} from={msToF(shot.startMs, fps)} durationInFrames={msToF(shot.endMs - shot.startMs, fps) + 1}>
            <ChapterStage startMs={shot.startMs} endMs={shot.endMs} stage={st as unknown as MacroStage} />
          </Sequence>
        );
      })}
      {isCard() ? null : <VoiceWave name={channel} />}
      {props.showSubtitles !== false ? <BottomSubtitle clauses={props.clauses} /> : null}
    </AbsoluteFill>
  );
};
