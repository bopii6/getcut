import React from 'react';
import {
  AbsoluteFill,
  Img,
  Loop,
  Sequence,
  staticFile,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {ShotVideo} from './webmedia';
// 循环引用说明：本文件只在组件渲染期使用 NiwoVideo 的工具，ESM 活绑定安全。
import {FontFace, buildSubtitleChunks, hideMedia, isBase, isCard} from './NiwoVideo';
import type {NiwoProps, Shot} from './NiwoVideo';
import {T} from './skin';

/**
 * 智谷三段式 v2（zhigu）——按逐帧拆解重建的模板。
 *
 * 与智谷一致的三条铁律：
 * 1) 三段骨架全程钉死：顶带（粒子网+两行大标题+频道标）/ 底带（粒子网+口播字幕）。
 * 2) 中段舞台是【全出血】的：实拍/截图素材铺满整个舞台（裁切填满），
 *    图形动作（关系树/榜单/胶囊墙）则落在深色粒子底上——两种模式交替，
 *    绝不是"白底上摆小卡片"。
 * 3) 叠加层才是点睛：玻璃胶囊、黄色关键词芯片、弹出的说明卡，
 *    只在"句子点名了东西"的时候按顺序弹出来，一个拍子 1.5-4 秒。
 */

const BAND_TOP = 560;
const BAND_BOTTOM = 550;
const STAGE_TOP = BAND_TOP;
const STAGE_H = 1920 - BAND_TOP - BAND_BOTTOM;
const W = 1080;

const YELLOW = '#ffd93d';
const GREEN = '#34d399';
const DARK = '#0b0e13';
const STAGE_BG = '#f4f3ee';
const INK = '#14171d';
const MUTED = '#6a7280';

const heavy: React.CSSProperties = {fontFamily: T.font, fontWeight: 900};
const LINE = '#7a6cff';
const stageCard: React.CSSProperties = {
  background: '#ffffff', borderRadius: 22, border: '2px solid #e7e5dd',
  boxShadow: '0 22px 60px rgba(23,26,32,0.12)',
};
const Enter: React.FC<{children: React.ReactNode; delay?: number; y?: number}> = ({children, delay = 0, y = 34}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [delay, delay + 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const ty = interpolate(f, [delay, delay + 10], [y, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <div style={{opacity: o, transform: `translateY(${ty}px)`}}>{children}</div>;
};
const msToF = (ms: number, fps: number) => Math.round((ms / 1000) * fps);

const rng = (seed: number) => {
  let s = (seed * 2654435761) >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
};

// ---------------- 粒子网 ----------------
const ParticleField: React.FC<{height: number; seed: number}> = ({height, seed}) => {
  const frame = useCurrentFrame();
  const pts = React.useMemo(() => {
    const r = rng(seed);
    return Array.from({length: 54}, (_, i) => ({
      x: r() * W,
      y: r() * height,
      r: 1.4 + r() * 2.4,
      ph: r() * Math.PI * 2,
      sp: 0.5 + r(),
      amp: 8 + r() * 16,
      key: i,
    }));
  }, [seed, height]);
  const moved = pts.map((p) => ({
    ...p,
    dx: Math.sin(frame * 0.012 * p.sp + p.ph) * p.amp,
    dy: Math.cos(frame * 0.009 * p.sp + p.ph * 1.3) * p.amp * 0.55,
  }));
  const lines: React.ReactNode[] = [];
  for (let i = 0; i < moved.length; i++) {
    for (let j = i + 1; j < moved.length; j++) {
      const a = moved[i];
      const b = moved[j];
      const d = Math.hypot(a.x + a.dx - (b.x + b.dx), a.y + a.dy - (b.y + b.dy));
      if (d < 280) {
        lines.push(
          <line key={`${i}-${j}`} x1={a.x + a.dx} y1={a.y + a.dy} x2={b.x + b.dx} y2={b.y + b.dy}
            stroke="#4d5d7c" strokeWidth={1} opacity={Math.max(0, (1 - d / 280) * 0.55)} />,
        );
      }
    }
  }
  return (
    <svg width={W} height={height} viewBox={`0 0 ${W} ${height}`} style={{position: 'absolute', inset: 0}}>
      {lines}
      {moved.map((p) => (
        <circle key={p.key} cx={p.x + p.dx} cy={p.y + p.dy} r={p.r} fill="#93a7cd"
          opacity={0.4 + 0.32 * Math.abs(Math.sin(frame * 0.03 * p.sp + p.ph))} />
      ))}
    </svg>
  );
};

const DarkStage: React.FC<{seed?: number; children?: React.ReactNode}> = ({seed = 7, children}) => (
  <AbsoluteFill style={{background: DARK, overflow: 'hidden'}}>
    <ParticleField height={STAGE_H} seed={seed} />
    {children}
  </AbsoluteFill>
);

// ---------------- 顶带 ----------------
const ChannelMark: React.FC = () => (
  <div style={{position: 'absolute', left: 52, top: 44, display: 'flex', alignItems: 'center', gap: 12}}>
    <span style={{width: 16, height: 16, borderRadius: 5, background: YELLOW, display: 'inline-block'}} />
    <span style={{...heavy, fontSize: 34, color: '#ffffff', letterSpacing: 1}}>GetCut</span>
  </div>
);

const estWL = (text: string, size: number) => {
  let w = 0;
  for (const ch of text) w += ch.charCodeAt(0) > 0x2e80 ? size : size * 0.56;
  return w;
};

const Headline: React.FC<{lines: {text: string; highlight?: string}[]}> = ({lines}) => {
  const frame = useCurrentFrame();
  const r = rng(Math.floor(frame / 5) * 7 + 3);
  const dx = (r() - 0.5) * 3;
  const dy = (r() - 0.5) * 2;
  const shown = lines.slice(0, 2);
  return (
    <div style={{position: 'absolute', left: 40, right: 40, top: 148, textAlign: 'center', transform: `translate(${dx}px, ${dy}px)`}}>
      {shown.map((l, i) => {
        const size = Math.min(86, Math.max(56, (960 / Math.max(estWL(l.text, 84), 1)) * 84));
        const isTail = shown.length > 1 && i === shown.length - 1;
        const parts = l.highlight && l.text.includes(l.highlight) ? l.text.split(l.highlight) : null;
        return (
          <div key={i} style={{...heavy, fontSize: size, lineHeight: 1.22, color: isTail ? YELLOW : '#ffffff',
            marginTop: i === 0 ? 0 : 14, textShadow: '0 4px 18px rgba(0,0,0,0.6)'}}>
            {parts ? (
              <>
                {parts[0]}
                <span style={{background: YELLOW, color: INK, padding: '0 14px', borderRadius: 10}}>{l.highlight}</span>
                {parts[1]}
              </>
            ) : l.text}
          </div>
        );
      })}
    </div>
  );
};

// ---------------- 叠加层（可以叠在任何舞台上，按 at 顺序弹） ----------------
const pop = (f: number, at: number) => ({
  o: interpolate(f, [at, at + 5], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
  s: interpolate(f, [at, at + 9], [0.55, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: (x: number) => 1 + Math.sin(Math.min(Math.max(x, 0), 1) * Math.PI) * 0.12,
  }),
});

/** 玻璃胶囊：半透明浅色，叠在实拍素材上（开场钩子那一挂） */
const GlassPill: React.FC<{text: string; at: number; small?: boolean}> = ({text, at, small}) => {
  const f = useCurrentFrame();
  const {o, s} = pop(f, at);
  return (
    <div style={{opacity: o, transform: `scale(${s})`}}>
      <div style={{
        background: 'linear-gradient(180deg, rgba(190,214,255,0.88), rgba(150,178,235,0.82))',
        borderRadius: 999, padding: small ? '14px 40px' : '22px 58px',
        boxShadow: '0 12px 30px rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.5)',
        textAlign: 'center',
      }}>
        <span style={{...heavy, fontSize: small ? 40 : 56, color: '#ffffff', textShadow: '0 2px 8px rgba(20,40,90,0.4)'}}>
          {text}
        </span>
      </div>
    </div>
  );
};

/** 黄色关键词芯片：黑字黄底，一排（查资料/写报告/做PPT 那一挂） */
export const ChipRow: React.FC<{items: string[]; mode?: 'dark' | 'media'}> = ({items, mode = 'dark'}) => {
  const f = useCurrentFrame();
  const shown = items.filter(Boolean).slice(0, 3);
  return (
    <div style={{display: 'flex', gap: 24, justifyContent: 'center', flexWrap: 'nowrap'}}>
      {shown.map((it, i) => {
        const {o, s} = pop(f, 4 + i * 8);
        return (
          <div key={i} style={{opacity: o, transform: `scale(${s})`}}>
            <div style={{
              background: YELLOW, color: INK, ...heavy, fontSize: 46,
              padding: '18px 44px', borderRadius: 14,
              boxShadow: mode === 'dark' ? '0 10px 26px rgba(0,0,0,0.45)' : '0 12px 30px rgba(0,0,0,0.5)',
              border: mode === 'media' ? '3px solid rgba(255,255,255,0.85)' : 'none',
            }}>
              {it}
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ---------------- 舞台动作（图形类落在深色粒子底上） ----------------

/** 关系树：中间主卡 + 虚线连子项胶囊（公司/产品/版本 那一挂） */
const TreeStage: React.FC<{stage: any}> = ({stage}) => {
  const tree = stage.tree || {};
  const kids: any[] = (Array.isArray(tree.children) ? tree.children : []).slice(0, 4)
    .map((c: any) => (typeof c === 'string' ? {title: c} : c));
  const center = tree.center || {};
  const f = useCurrentFrame();
  const cIn = interpolate(f, [0, 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const kidAt = (i: number) => 14 + i * 8;
  const n = Math.max(1, kids.length);
  const slot = Math.min(250, 960 / n);
  return (
    <DarkStage seed={31}>
      <div style={{position: 'absolute', left: 0, right: 0, top: STAGE_H * 0.14,
        display: 'flex', justifyContent: 'center', opacity: cIn, transform: `translateY(${(1 - cIn) * 30}px)`}}>
        <div style={{...{background: '#ffffff', borderRadius: 20, boxShadow: '0 18px 44px rgba(0,0,0,0.5)'},
          display: 'inline-flex', flexDirection: 'column', alignItems: 'center', padding: '30px 56px', minWidth: 430}}>
          {center.logo ? <Img src={staticFile(`media/${center.logo}`)} style={{height: 92, objectFit: 'contain', marginBottom: 14}} /> : null}
          <div style={{...heavy, fontSize: 54, color: INK}}>{center.title}</div>
          {center.sub ? <div style={{fontFamily: T.fontMono, fontSize: 28, color: MUTED, marginTop: 10}}>{center.sub}</div> : null}
        </div>
      </div>
      <svg width={W} height={STAGE_H} style={{position: 'absolute', top: 0, left: 0, pointerEvents: 'none'}}>
        {kids.map((_, i) => {
          const cx = W / 2 + (i - (n - 1) / 2) * slot;
          const on = f >= kidAt(i);
          return (
            <line key={i} x1={W / 2} y1={STAGE_H * 0.14 + 148} x2={cx} y2={STAGE_H * 0.14 + 300}
              stroke={LINE} strokeWidth={3} strokeDasharray="10 8" opacity={on ? 0.85 : 0} />
          );
        })}
      </svg>
      <div style={{position: 'absolute', left: 0, right: 0, top: STAGE_H * 0.14 + 300, display: 'flex', justifyContent: 'center'}}>
        {kids.map((k, i) => {
          const on = f >= kidAt(i);
          const o2 = interpolate(f, [kidAt(i), kidAt(i) + 6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          const width = Math.min(226, slot - 18);
          return (
            <div key={i} style={{width: slot, display: 'flex', justifyContent: 'center'}}>
              {on ? (
                <div style={{width, opacity: o2}}>
                  <div style={{background: '#ffffff', borderRadius: 16, padding: '18px 8px', textAlign: 'center',
                    border: `2px solid ${LINE}`, boxShadow: '0 12px 30px rgba(0,0,0,0.4)'}}>
                    {k.logo ? <Img src={staticFile(`media/${k.logo}`)} style={{height: 42, objectFit: 'contain', marginBottom: 8}} /> : null}
                    <div style={{...heavy, fontSize: 30, color: INK}}>{k.title || k}</div>
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </DarkStage>
  );
};

/** 榜单卡：深底 + 白表卡 + 标题条 + 高亮行 + 弹出说明卡 */
const RankStage: React.FC<{stage: any}> = ({stage}) => {
  const table = stage.table || {};
  const rows: any[] = Array.isArray(table.rows) ? table.rows.slice(0, 5) : [];
  const f = useCurrentFrame();
  const hi = rows.findIndex((r) => r.highlight);
  const tooltip = typeof table.tooltip === 'string' ? table.tooltip : null;
  const tipAt = 26;
  return (
    <DarkStage seed={53}>
      <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 60px'}}>
        <Enter delay={2}>
          <div style={{width: 940, background: '#ffffff', borderRadius: 18, overflow: 'hidden',
            boxShadow: '0 30px 80px rgba(0,0,0,0.6)'}}>
            {table.title ? (
              <div style={{background: '#241a4d', padding: '20px 30px'}}>
                <div style={{...heavy, fontSize: 34, color: '#ffffff', letterSpacing: 1}}>{table.title}</div>
              </div>
            ) : null}
            {rows.map((r, i) => {
              const at = 8 + i * 6;
              const on = f >= at;
              const o2 = interpolate(f, [at, at + 5], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
              return (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: 16, padding: '15px 26px', opacity: o2,
                  background: r.highlight ? 'rgba(255,217,61,0.32)' : 'transparent',
                  borderLeft: r.highlight ? `8px solid ${YELLOW}` : '8px solid transparent',
                }}>
                  <span style={{fontFamily: T.fontMono, fontSize: 28, color: MUTED, width: 40}}>{i + 1}</span>
                  <span style={{flex: 1, minWidth: 0}}>
                    <span style={{...heavy, fontSize: 30, color: INK, display: 'block'}}>{r.name || ''}</span>
                    {r.sub ? <span style={{fontSize: 21, color: MUTED}}>{r.sub}</span> : null}
                  </span>
                  {r.value ? <span style={{fontFamily: T.fontMono, fontWeight: 700, fontSize: 32, color: INK}}>{r.value}</span> : null}
                  {r.delta ? (
                    <span style={{fontFamily: T.fontMono, fontSize: 24, fontWeight: 700, color: '#0e9f6e',
                      background: 'rgba(52,211,153,0.16)', padding: '4px 12px', borderRadius: 8}}>{r.delta}</span>
                  ) : null}
                </div>
              );
            })}
          </div>
        </Enter>
        {tooltip && f >= tipAt ? (
          <div style={{position: 'absolute', left: '50%', top: STAGE_H * 0.52,
            transform: `translate(-50%, 0) scale(${interpolate(f, [tipAt, tipAt + 7], [0.7, 1], {
              extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
              easing: (x: number) => 1 + Math.sin(Math.min(x, 1) * Math.PI) * 0.15,
            })})`, opacity: interpolate(f, [tipAt, tipAt + 5], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}>
            <div style={{background: '#ffffff', borderRadius: 14, padding: '16px 24px',
              boxShadow: '0 16px 44px rgba(0,0,0,0.55)', display: 'flex', gap: 16, alignItems: 'center'}}>
              {rows[hi]?.name ? <span style={{...heavy, fontSize: 28, color: INK}}>{rows[hi].name}</span> : null}
              {rows[hi]?.value ? <span style={{fontFamily: T.fontMono, fontWeight: 700, fontSize: 28, color: '#6a5acd'}}>{rows[hi].value}</span> : null}
              {rows[hi]?.delta ? <span style={{fontFamily: T.fontMono, fontSize: 24, fontWeight: 700, color: '#0e9f6e'}}>{rows[hi].delta}</span> : null}
            </div>
          </div>
        ) : null}
      </AbsoluteFill>
    </DarkStage>
  );
};

/** 高亮金句：深底 + 白卡 + 绿底高亮（可打字机） */
const QuoteStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const quote = o.quote || o.title || o.card?.title || '';
  const f = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const dur = msToF(shot.endMs - shot.startMs, fps);
  const chars = Math.round(interpolate(f, [4, Math.max(10, dur * 0.7)] as number[], [0, quote.length] as number[], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  }));
  const shown = quote.slice(0, chars);
  return (
    <DarkStage seed={77}>
      <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 80px'}}>
        <div style={{background: 'linear-gradient(135deg, #1d3557, #2a5a8c)', borderRadius: 20,
          padding: '36px 44px', maxWidth: 920, boxShadow: '0 24px 70px rgba(0,0,0,0.55)'}}>
          <div style={{...heavy, fontSize: 46, color: '#ffffff', lineHeight: 1.55}}>
            <span style={{background: 'rgba(255,255,255,0.16)', padding: '2px 12px', borderRadius: 10}}>{shown}</span>
            <span style={{opacity: Math.floor(f / 4) % 2 === 0 ? 1 : 0.2}}>|</span>
          </div>
        </div>
      </AbsoluteFill>
    </DarkStage>
  );
};

/** 数字卡：黄条压底大数字 */
const NumberStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  return (
    <DarkStage seed={13}>
      <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <Enter>
          <div style={{textAlign: 'center'}}>
            {o.label ? <div style={{fontSize: 30, color: '#aab2bd', letterSpacing: 4, marginBottom: 24}}>{o.label}</div> : null}
            <div style={{...heavy, fontSize: String(o.number || '').length > 8 ? 110 : 170, color: '#ffffff',
              display: 'inline-block', borderBottom: `16px solid ${YELLOW}`, paddingBottom: 8}}>{o.number || ''}</div>
            {o.caption ? <div style={{fontSize: 36, color: '#ffffff', marginTop: 30, ...heavy}}>{o.caption}</div> : null}
          </div>
        </Enter>
      </AbsoluteFill>
    </DarkStage>
  );
};

/** 对比卡 */
const CompareStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const sides = [o.left, o.right].filter(Boolean);
  return (
    <DarkStage seed={19}>
      <AbsoluteFill style={{display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '0 70px'}}>
        <Enter>
          <div style={{...heavy, fontSize: 42, color: '#ffffff', marginBottom: 30, textAlign: 'center'}}>{o.title || ''}</div>
          <div style={{display: 'flex', gap: 26}}>
            {sides.map((s: any, i: number) => (
              <div key={i} style={{flex: 1, background: 'rgba(255,255,255,0.96)', borderRadius: 18, padding: '30px 30px'}}>
                <div style={{...heavy, fontSize: 34, color: i === 0 ? '#6a5acd' : '#0e9f6e'}}>{s.head}</div>
                <div style={{fontSize: 30, color: INK, marginTop: 12, lineHeight: 1.5}}>{s.body}</div>
              </div>
            ))}
          </div>
        </Enter>
      </AbsoluteFill>
    </DarkStage>
  );
};

/** 勾选清单：显示器线框 */
const ChecklistStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const items: string[] = (Array.isArray(o.items) ? o.items : []).slice(0, 5);
  const f = useCurrentFrame();
  return (
    <DarkStage seed={29}>
      <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <Enter>
          <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center'}}>
            <div style={{background: '#171a20', borderRadius: 26, padding: 14, boxShadow: '0 24px 60px rgba(0,0,0,0.5)'}}>
              <div style={{background: '#ffffff', borderRadius: 14, width: 760, minHeight: 280 + items.length * 52, padding: '30px 40px'}}>
                {o.title ? (
                  <div style={{...heavy, fontSize: 34, color: INK, marginBottom: 20, display: 'flex', alignItems: 'center', gap: 12}}>
                    <span style={{width: 12, height: 12, borderRadius: 999, background: YELLOW, display: 'inline-block'}} />
                    {o.title}
                  </div>
                ) : null}
                {items.map((it, i) => {
                  const at = 8 + i * 9;
                  const done = f >= at;
                  const popv = interpolate(f, [at, at + 6], [0.4, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
                  return (
                    <div key={i} style={{display: 'flex', alignItems: 'center', gap: 18, padding: '10px 0'}}>
                      <span style={{width: 34, height: 34, borderRadius: 999, flex: 'none',
                        border: done ? `3px solid ${GREEN}` : '3px solid #d8d6cf', background: done ? GREEN : '#fff',
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#fff',
                        fontSize: 22, fontWeight: 900, transform: done ? `scale(${popv})` : 'scale(1)'}}>
                        {done ? '✓' : ''}
                      </span>
                      <span style={{fontSize: 30, color: INK}}>{it}</span>
                    </div>
                  );
                })}
              </div>
            </div>
            <div style={{width: 130, height: 46, background: '#171a20', clipPath: 'polygon(22% 0, 78% 0, 100% 100%, 0 100%)'}} />
            <div style={{width: 230, height: 14, background: '#171a20', borderRadius: 6}} />
          </div>
        </Enter>
      </AbsoluteFill>
    </DarkStage>
  );
};

/** 信息卡兜底 */
const CardStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const title = o.title || o.card?.title || o.card_title || '';
  const body = o.card?.body || o.card_body || o.subtitle || '';
  const badge = o.badge || o.label || '';
  return (
    <DarkStage seed={41}>
      <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 80px'}}>
        <Enter>
          <div style={{background: '#ffffff', borderRadius: 20, padding: '44px 52px', width: 900,
            borderLeft: `12px solid ${YELLOW}`, boxShadow: '0 24px 70px rgba(0,0,0,0.5)'}}>
            {badge ? <div style={{fontSize: 26, color: MUTED, letterSpacing: 3, marginBottom: 16}}>{badge}</div> : null}
            {title ? <div style={{...heavy, fontSize: 50, color: INK, lineHeight: 1.3}}>{title}</div> : null}
            {body ? <div style={{fontSize: 30, color: '#454b56', marginTop: 20, lineHeight: 1.7, whiteSpace: 'pre-wrap'}}>{body}</div> : null}
          </div>
        </Enter>
      </AbsoluteFill>
    </DarkStage>
  );
};

// ---------------- 舞台：全出血媒体 + 叠加层，或深色图形 ----------------
const MediaStage: React.FC<{shot: Shot; index: number}> = ({shot, index}) => {
  const fps = useVideoConfig().fps;
  const frame = useCurrentFrame();
  if (!shot.media) return null;
  const src = staticFile(`media/${shot.media}`);
  const dur = msToF(shot.endMs - shot.startMs, fps) + 1;
  if (shot.mediaKind === 'image') {
    const zoom = interpolate(frame, [0, dur], index % 2 === 0 ? [1.02, 1.1] : [1.1, 1.02], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    });
    return (
      <AbsoluteFill style={{overflow: 'hidden'}}>
        <Img src={src} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${zoom})`}} />
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <Loop durationInFrames={dur}>
        <ShotVideo src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      </Loop>
    </AbsoluteFill>
  );
};

const ChipsOverlay: React.FC<{chips: string[]}> = ({chips}) => (
  <div style={{position: 'absolute', left: 0, right: 0, bottom: 46, display: 'flex', justifyContent: 'center'}}>
    <ChipRow items={chips} mode="media" />
  </div>
);

// ---------------- 新增动作：递进卡 / 人物芯片墙 / 三联卡 / 结尾卡 ----------------

/** 概念递进卡：同一个框，先说 A 再换成 B（工具 → 智能体 那一挂） */
const SwapStage: React.FC<{swap: any}> = ({swap}) => {
  const f = useCurrentFrame();
  const total = useVideoConfig().durationInFrames;
  const half = Math.max(40, Math.floor(total * 0.45));
  const showB = f >= half;
  const cur = showB ? swap.b : swap.a;
  const o = interpolate(f, showB ? [half, half + 8] : [0, 8], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  return (
    <DarkStage seed={23}>
      <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 90px'}}>
        <div style={{opacity: o, width: '100%', border: '2px solid rgba(255,255,255,0.55)', borderRadius: 18,
          padding: '40px 40px', textAlign: 'center', background: 'rgba(10,12,18,0.55)'}}>
          <div style={{display: 'inline-block', background: YELLOW, color: INK, ...heavy,
            fontSize: 52, padding: '10px 40px', borderRadius: 12}}>{cur.label}</div>
          <div style={{...heavy, fontSize: 46, color: '#ffffff', marginTop: 26, lineHeight: 1.4}}>
            “{cur.text}”
          </div>
        </div>
      </AbsoluteFill>
    </DarkStage>
  );
};

/** 人物芯片墙：人物卡 + 他用搭子干的事（普通人例子那一挂） */
const PersonChipsStage: React.FC<{person: any}> = ({person}) => {
  const f = useCurrentFrame();
  const chips: string[] = (person.chips || []).slice(0, 4);
  return (
    <DarkStage seed={37}>
      <AbsoluteFill style={{display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 44, padding: '0 70px'}}>
        <Enter>
          <div style={{background: '#ffffff', borderRadius: 20, padding: '30px 46px', textAlign: 'center',
            boxShadow: '0 20px 50px rgba(0,0,0,0.45)'}}>
            <div style={{...heavy, fontSize: 52, color: INK}}>{person.name}</div>
            {person.caption ? <div style={{fontSize: 28, color: MUTED, marginTop: 8}}>{person.caption}</div> : null}
          </div>
        </Enter>
        <div style={{display: 'grid', gridTemplateColumns: chips.length > 3 ? '1fr 1fr' : '1fr', gap: 18, width: 620}}>
          {chips.map((c, i) => {
            const at = 12 + i * 8;
            const o2 = interpolate(f, [at, at + 6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
            return (
              <div key={i} style={{opacity: o2, background: YELLOW, borderRadius: 12, padding: '16px 10px',
                textAlign: 'center', ...heavy, fontSize: 34, color: INK}}>{c}</div>
            );
          })}
        </div>
      </AbsoluteFill>
    </DarkStage>
  );
};

/** 三联卡：渐变色卡滑入（功能一/二/三 那一挂） */
const ThreeCardsStage: React.FC<{cards: any[]}> = ({cards}) => {
  const f = useCurrentFrame();
  const list = (cards || []).slice(0, 3);
  const tints = [['#ffe3ec', '#ffd3a8'], ['#dff3ff', '#cfe0ff'], ['#e2ffdf', '#c9f0d8']];
  return (
    <DarkStage seed={43}>
      <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 26, padding: '0 46px'}}>
        {list.map((c: any, i: number) => {
          const at = 4 + i * 8;
          const o = interpolate(f, [at, at + 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          const y = interpolate(f, [at, at + 10], [40, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          return (
            <div key={i} style={{flex: 1, opacity: o, transform: `translateY(${y}px)`,
              background: `linear-gradient(160deg, ${tints[i][0]}, ${tints[i][1]})`,
              borderRadius: 20, padding: '26px 22px', minHeight: 300,
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14}}>
              <div style={{width: 64, height: 64, borderRadius: 16, background: 'rgba(255,255,255,0.75)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 34}}>🤖</div>
              <div style={{...heavy, fontSize: 32, color: INK, textAlign: 'center'}}>{c.title}</div>
              {c.sub ? <div style={{fontSize: 22, color: '#4a4f58', textAlign: 'center'}}>{c.sub}</div> : null}
            </div>
          );
        })}
      </AbsoluteFill>
    </DarkStage>
  );
};

/** 结尾卡：黑底 slogan + 三个互动图标 */
const EndStage: React.FC<{end: any}> = ({end}) => {
  const f = useCurrentFrame();
  const slogan = end.slogan || '有大事看 GetCut';
  const hi = end.highlight || 'GetCut';
  const parts = slogan.includes(hi) ? slogan.split(hi) : [slogan];
  return (
    <AbsoluteFill style={{background: '#000000', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: 90}}>
      <div style={{...heavy, fontSize: 92, color: '#ffffff', textAlign: 'center'}}>
        {parts.length > 1 ? (
          <>{parts[0]}<span style={{color: YELLOW}}>{hi}</span>{parts[1]}</>
        ) : slogan}
      </div>
      <div style={{display: 'flex', gap: 120}}>
        {['👍', '↗', '❤'].map((ic, i) => {
          const at = 20 + i * 12;
          const on = f >= at;
          const o = interpolate(f, [at, at + 8], [0.15, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          return (
            <span key={i} style={{fontSize: 64, opacity: o, filter: on ? 'none' : 'grayscale(1)'}}>{ic}</span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** 品牌揭幕：柔和渐变底 + 品牌名（发布会揭幕那一挂） */
const BrandStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const main = o.keyword || o.title || o.number || 'GetCut';
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center',
      background: 'linear-gradient(120deg, #dfe7ff 0%, #f3e6ff 45%, #ffe9f3 100%)'}}>
      <Enter>
        <div style={{textAlign: 'center'}}>
          <div style={{...heavy, fontSize: 128, color: '#3d4470', textShadow: '0 12px 34px rgba(61,68,112,0.28)'}}>
            {main}
          </div>
          {o.subtitle ? <div style={{fontSize: 38, color: '#5c6470', marginTop: 26, fontWeight: 700}}>{o.subtitle}</div> : null}
        </div>
      </Enter>
    </AbsoluteFill>
  );
};

// ---------------- 舞台调度：优先认 stage.mode，没有则按 kind 兜底 ----------------
const Stage: React.FC<{shot: Shot; index: number}> = ({shot, index}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const st = (shot as any).stage || {};
  const mode = st.mode;
  const chips: string[] = Array.isArray(st.chips) ? st.chips : (Array.isArray(o.chips) ? o.chips : []);
  let node: React.ReactNode;

  if (mode === 'hook') {
    node = (
      <>
        {shot.media ? <MediaStage shot={shot} index={index} /> : <DarkStage seed={7} />}
        <AbsoluteFill style={{background: 'rgba(6,8,12,0.30)'}} />
        <AbsoluteFill style={{display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 36, padding: '0 60px'}}>
          {(st.pills || []).map((t: string, i: number) => (
            <GlassPill key={i} text={t} at={6 + i * 12} small={i > 0} />
          ))}
        </AbsoluteFill>
      </>
    );
  } else if (mode === 'media' || mode === 'chips-media') {
    node = (
      <>
        <MediaStage shot={shot} index={index} />
        {mode === 'chips-media' ? (
          <>
            <AbsoluteFill style={{background: 'rgba(6,8,12,0.22)'}} />
            <div style={{position: 'absolute', left: 0, right: 0, bottom: 44}}>
              <ChipRow items={chips} mode="media" />
            </div>
          </>
        ) : null}
      </>
    );
  } else if (mode === 'chips-dark') {
    node = (
      <DarkStage seed={61}>
        <AbsoluteFill style={{display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 42, padding: '0 60px'}}>
          {st.title ? (
            <Enter>
              <div style={{...heavy, fontSize: 44, color: '#ffffff', textAlign: 'center'}}>
                <span style={{borderBottom: `6px solid ${YELLOW}`, paddingBottom: 6}}>{st.title}</span>
              </div>
            </Enter>
          ) : null}
          <ChipRow items={chips} />
        </AbsoluteFill>
      </DarkStage>
    );
  } else if (mode === 'tree') {
    node = <TreeStage stage={st} />;
  } else if (mode === 'table') {
    node = <RankStage stage={st} />;
  } else if (mode === 'swap') {
    node = <SwapStage swap={st.swap} />;
  } else if (mode === 'quote') {
    node = <QuoteStage shot={{...shot, overlay: {quote: st.quote || o.quote || '', label: st.label || o.label}} as any} />;
  } else if (mode === 'number') {
    node = <NumberStage shot={{...shot, overlay: {label: st.label ?? o.label, number: st.number ?? o.number, caption: st.caption ?? o.caption}}} />;
  } else if (mode === 'checklist') {
    node = <ChecklistStage shot={{...shot, overlay: {title: st.title ?? o.title, items: st.items ?? o.items ?? []}}} />;
  } else if (mode === 'person') {
    node = <PersonChipsStage person={st.person || {}} />;
  } else if (mode === 'cards3') {
    node = <ThreeCardsStage cards={st.cards || []} />;
  } else if (mode === 'brand') {
    node = <BrandStage shot={{...shot, overlay: {keyword: st.name || o.keyword || 'GetCut', subtitle: st.sub || o.subtitle}}} />;
  } else if (mode === 'end') {
    node = <EndStage end={st.end || {slogan: '有大事看 GetCut', highlight: 'GetCut'}} />;
  } else if (shot.media) {
    node = (
      <>
        <MediaStage shot={shot} index={index} />
        {chips.length ? (
          <>
            <AbsoluteFill style={{background: 'rgba(6,8,12,0.22)'}} />
            <div style={{position: 'absolute', left: 0, right: 0, bottom: 44}}>
              <ChipRow items={chips} mode="media" />
            </div>
          </>
        ) : null}
      </>
    );
  } else if (shot.kind === 'title_card') {
    node = (
      <DarkStage seed={7}>
        <AbsoluteFill style={{display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 30}}>
          <GlassPill text={o.keyword || o.title || 'GetCut'} at={4} />
          {o.subtitle ? <GlassPill text={o.subtitle} at={14} small /> : null}
        </AbsoluteFill>
      </DarkStage>
    );
  } else if (shot.kind === 'quote_card') {
    node = <QuoteStage shot={shot} />;
  } else if (shot.kind === 'callout') {
    node = <NumberStage shot={shot} />;
  } else if (o.variant === 'compare' && (o.left || o.right)) {
    node = <CompareStage shot={shot} />;
  } else if (o.variant === 'fact' && o.items) {
    node = <ChecklistStage shot={shot} />;
  } else {
    node = <CardStage shot={shot} />;
  }

  return <AbsoluteFill style={{position: 'absolute', top: STAGE_TOP, height: STAGE_H, overflow: 'hidden'}}>{node}</AbsoluteFill>;
};

// ---------------- 主入口：三段式骨架 ----------------
export const ZhiguVideo: React.FC<NiwoProps> = (props) => {
  const fps = useVideoConfig().fps;
  return (
    <AbsoluteFill style={{background: DARK, fontFamily: T.font}}>
      <FontFace />
      {isCard() ? null : (
        <div style={{position: 'absolute', top: 0, width: '100%', height: BAND_TOP, background: DARK, overflow: 'hidden'}}>
          <ParticleField height={BAND_TOP} seed={7} />
          <ChannelMark />
          <Headline lines={props.headline.lines} />
        </div>
      )}
      <div style={{position: 'absolute', top: STAGE_TOP, width: '100%', height: STAGE_H, background: isCard() ? 'transparent' : DARK}} />
      {isBase() ? null : props.shots.map((shot, i) => (
        <Sequence key={i} from={msToF(shot.startMs, fps)} durationInFrames={msToF(shot.endMs - shot.startMs, fps) + 1}>
          <Stage shot={shot} index={i} />
        </Sequence>
      ))}
      {isCard() ? null : (
        <div style={{position: 'absolute', top: 1920 - BAND_BOTTOM, width: '100%', height: BAND_BOTTOM, background: DARK, overflow: 'hidden'}}>
          <ParticleField height={BAND_BOTTOM} seed={99} />
          {props.showSubtitles !== false ? <BottomSubtitle clauses={props.clauses} /> : null}
        </div>
      )}
    </AbsoluteFill>
  );
};

const BottomSubtitle: React.FC<{clauses: {text: string; startMs: number; endMs: number}[]}> = ({clauses}) => {
  const frame = useCurrentFrame();
  const fps = useVideoConfig().fps;
  const t = (frame / fps) * 1000;
  if (hideMedia()) return null;
  const active = buildSubtitleChunks(clauses).find((c) => t >= c.startMs && t < c.endMs);
  if (!active) return null;
  return (
    <div style={{position: 'absolute', left: 56, right: 56, top: BAND_BOTTOM / 2 - 90, textAlign: 'center',
      ...heavy, fontSize: 62, color: '#ffffff', lineHeight: 1.3, textShadow: '0 3px 16px rgba(0,0,0,0.7)'}}>
      {active.text}
    </div>
  );
};
