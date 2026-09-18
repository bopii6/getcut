import React from 'react';
import {
  AbsoluteFill,
  Img,
  Loop,
  Sequence,
  staticFile,
  Video,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
// 循环引用说明：本文件只在组件渲染期使用 NiwoVideo 的工具（FontFace/字幕分块），
// ESM 活绑定在渲染时已初始化，加载顺序安全。
import {FontFace, buildSubtitleChunks, hideMedia, isBase, isCard} from './NiwoVideo';
import type {NiwoProps, Shot} from './NiwoVideo';
import {T} from './skin';

/**
 * 智谷三段式（zhigu）：复刻智谷趋势的成片版式逻辑。
 * 骨架全程钉死：顶带（深色粒子网 + 两行大标题 + 频道标）/ 中段近白舞台 / 底带（粒子网 + 口播字幕）。
 * 舞台按分镜换"动作"：视频素材、截图卡（缓推）、关系树、榜单卡、勾选清单、高亮金句、数字卡。
 * 抽象出来的模板逻辑：文案驱动舞台动作，画面元素在舞台里累积，版式永远不换。
 */

const BAND_TOP = 560; // 顶带高（约 29%）
const BAND_BOTTOM = 550; // 底带高（约 29%）
const STAGE_TOP = BAND_TOP;
const STAGE_H = 1920 - BAND_TOP - BAND_BOTTOM;
const W = 1080;

const YELLOW = '#ffd93d';
const GREEN = '#34d399';
const LINE = '#7a6cff';
const DARK = '#0c0f14';
const STAGE_BG = '#f5f4ef';
const INK = '#171a20';
const MUTED = '#6a7280';

const heavy: React.CSSProperties = {fontFamily: T.font, fontWeight: 900};
const msToF = (ms: number, fps: number) => Math.round((ms / 1000) * fps);

// 确定性伪随机：同一种子每次渲染的点阵/抖动一致（Remotion 逐帧渲染要求确定性）
const rng = (seed: number) => {
  let s = (seed * 2654435761) >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
};

// ---------------- 粒子网（顶/底带的深色底） ----------------
const ParticleField: React.FC<{height: number; seed: number}> = ({height, seed}) => {
  const frame = useCurrentFrame();
  const pts = React.useMemo(() => {
    const r = rng(seed);
    return Array.from({length: 52}, (_, i) => ({
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
          <line
            key={`${i}-${j}`}
            x1={a.x + a.dx}
            y1={a.y + a.dy}
            x2={b.x + b.dx}
            y2={b.y + b.dy}
            stroke="#4d5d7c"
            strokeWidth={1}
            opacity={Math.max(0, (1 - d / 280) * 0.55)}
          />,
        );
      }
    }
  }
  return (
    <svg width={W} height={height} viewBox={`0 0 ${W} ${height}`} style={{position: 'absolute', inset: 0}}>
      {lines}
      {moved.map((p) => (
        <circle
          key={p.key}
          cx={p.x + p.dx}
          cy={p.y + p.dy}
          r={p.r}
          fill="#93a7cd"
          opacity={0.4 + 0.32 * Math.abs(Math.sin(frame * 0.03 * p.sp + p.ph))}
        />
      ))}
    </svg>
  );
};

// ---------------- 顶带：频道标 + 两行大标题 ----------------
const ChannelMark: React.FC = () => (
  <div style={{position: 'absolute', left: 52, top: 44, display: 'flex', alignItems: 'center', gap: 12}}>
    <span style={{width: 16, height: 16, borderRadius: 5, background: YELLOW, display: 'inline-block'}} />
    <span style={{...heavy, fontSize: 34, color: '#ffffff', letterSpacing: 1}}>GetCut</span>
  </div>
);

// 本地字宽估算（与 NiwoVideo.estW 同一公式，避免跨文件循环依赖加导出面）
const estWL = (text: string, size: number) => {
  let w = 0;
  for (const ch of text) w += ch.charCodeAt(0) > 0x2e80 ? size : size * 0.56;
  return w;
};

const Headline: React.FC<{lines: {text: string; highlight?: string}[]}> = ({lines}) => {
  const frame = useCurrentFrame();
  // 智谷标题带的那点"活劲"：每 5 帧一个 1–2px 的微抖，肉眼几乎不可见但画面不僵
  const r = rng(Math.floor(frame / 5) * 7 + 3);
  const dx = (r() - 0.5) * 3;
  const dy = (r() - 0.5) * 2;
  const shown = lines.slice(0, 2);
  return (
    <div
      style={{
        position: 'absolute',
        left: 40,
        right: 40,
        top: 148,
        textAlign: 'center',
        transform: `translate(${dx}px, ${dy}px)`,
      }}
    >
      {shown.map((l, i) => {
        const size = Math.min(86, Math.max(56, (960 / Math.max(estWL(l.text, 84), 1)) * 84));
        const isTail = shown.length > 1 && i === shown.length - 1;
        const parts = l.highlight && l.text.includes(l.highlight) ? l.text.split(l.highlight) : null;
        return (
          <div
            key={i}
            style={{
              ...heavy,
              fontSize: size,
              lineHeight: 1.22,
              color: isTail ? YELLOW : '#ffffff',
              marginTop: i === 0 ? 0 : 14,
              textShadow: '0 4px 18px rgba(0,0,0,0.6)',
            }}
          >
            {parts ? (
              <>
                {parts[0]}
                <span style={{background: YELLOW, color: INK, padding: '0 14px', borderRadius: 10}}>{l.highlight}</span>
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

// ---------------- 舞台动作的公共件 ----------------
const Enter: React.FC<{children: React.ReactNode; delay?: number; y?: number}> = ({children, delay = 0, y = 34}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [delay, delay + 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const ty = interpolate(f, [delay, delay + 10], [y, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <div style={{opacity: o, transform: `translateY(${ty}px)`}}>{children}</div>;
};

const stageCard: React.CSSProperties = {
  background: '#ffffff',
  borderRadius: 22,
  border: '2px solid #e7e5dd',
  boxShadow: '0 22px 60px rgba(23,26,32,0.12)',
};

const TickDot: React.FC<{at: number}> = ({at}) => {
  const f = useCurrentFrame();
  const done = f >= at;
  const pop = interpolate(f, [at, at + 6], [0.4, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <span
      style={{
        width: 34,
        height: 34,
        borderRadius: 999,
        flex: 'none',
        border: done ? `3px solid ${GREEN}` : '3px solid #d8d6cf',
        background: done ? GREEN : '#ffffff',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#ffffff',
        fontSize: 22,
        fontWeight: 900,
        transform: done ? `scale(${pop})` : 'scale(1)',
      }}
    >
      {done ? '✓' : ''}
    </span>
  );
};

// ---------------- 舞台动作 ----------------

/** 视频素材 / 截图卡：铺满舞台，图给缓推（Ken Burns），视频循环播放 */
const MediaStage: React.FC<{shot: Shot; index: number}> = ({shot, index}) => {
  const fps = useVideoConfig().fps;
  const frame = useCurrentFrame();
  if (!shot.media) return null;
  const src = staticFile(`media/${shot.media}`);
  const dur = msToF(shot.endMs - shot.startMs, fps) + 1;
  if (shot.mediaKind === 'image') {
    const zoom = interpolate(frame, [0, dur], index % 2 === 0 ? [1.03, 1.13] : [1.13, 1.03], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    return (
      <AbsoluteFill style={{overflow: 'hidden'}}>
        <Img
          src={src}
          style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${zoom})`}}
        />
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <Loop durationInFrames={dur}>
        <Video src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      </Loop>
    </AbsoluteFill>
  );
};

/** 关键词胶囊：一个个"弹"出来（查资料 / 写报告 / 做PPT 那一挂） */
const PillsStage: React.FC<{items: string[]; title?: string}> = ({items, title}) => {
  const f = useCurrentFrame();
  const shown = items.filter(Boolean).slice(0, 4);
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', padding: '0 70px'}}>
      {title ? (
        <Enter>
          <div style={{...heavy, fontSize: 40, color: INK, marginBottom: 44, textAlign: 'center'}}>{title}</div>
        </Enter>
      ) : null}
      <div style={{display: 'flex', gap: 26, flexWrap: 'wrap', justifyContent: 'center'}}>
        {shown.map((it, i) => {
          const at = 6 + i * 9;
          const s = interpolate(f, [at, at + 9], [0.55, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
            easing: (x: number) => 1 + Math.sin(Math.min(x, 1) * Math.PI) * 0.12,
          });
          const o = interpolate(f, [at, at + 5], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          return (
            <div
              key={i}
              style={{
                ...heavy,
                fontSize: 52,
                color: INK,
                background: YELLOW,
                padding: '24px 56px',
                borderRadius: 999,
                boxShadow: '0 14px 34px rgba(255,217,61,0.35)',
                opacity: o,
                transform: `scale(${s})`,
              }}
            >
              {it}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** 关系树：中间主卡（logo/产品）+ 虚线连到子项胶囊（个人版/企业版/行业套件那一挂） */
const TreeStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const children: any[] = Array.isArray(o.children) ? o.children : [];
  const kids = children.slice(0, 4).map((c: any) => (typeof c === 'string' ? {title: c} : c));
  const centerTitle = o.center?.title || o.title || '';
  const centerSub = o.center?.sub || o.center?.subtitle || '';
  const f = useCurrentFrame();
  const cIn = interpolate(f, [0, 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const kidAt = (i: number) => 14 + i * 8;
  const n = Math.max(1, kids.length);
  const slot = Math.min(250, 940 / n);
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: STAGE_H * 0.18,
          display: 'flex',
          justifyContent: 'center',
          opacity: cIn,
          transform: `translateY(${(1 - cIn) * 30}px)`,
        }}
      >
        <div style={{...stageCard, display: 'inline-flex', flexDirection: 'column', alignItems: 'center', padding: '34px 60px', minWidth: 420}}>
          {o.center?.logo ? (
            <Img src={staticFile(`media/${o.center.logo}`)} style={{height: 96, objectFit: 'contain', marginBottom: 16}} />
          ) : null}
          <div style={{...heavy, fontSize: 56, color: INK}}>{centerTitle}</div>
          {centerSub ? <div style={{fontFamily: T.fontMono, fontSize: 30, color: MUTED, marginTop: 10}}>{centerSub}</div> : null}
        </div>
      </div>
      <svg width={W} height={STAGE_H} style={{position: 'absolute', top: 0, left: 0, pointerEvents: 'none'}}>
        {kids.map((_, i) => {
          const cx = W / 2 + (i - (n - 1) / 2) * slot;
          const on = f >= kidAt(i);
          return (
            <line
              key={i}
              x1={W / 2}
              y1={STAGE_H * 0.18 + 150}
              x2={cx}
              y2={STAGE_H * 0.18 + 320}
              stroke={LINE}
              strokeWidth={3}
              strokeDasharray="10 8"
              opacity={on ? 0.8 : 0}
            />
          );
        })}
      </svg>
      <div style={{position: 'absolute', left: 0, right: 0, top: STAGE_H * 0.18 + 320, display: 'flex', justifyContent: 'center'}}>
        {kids.map((k, i) => {
          const on = f >= kidAt(i);
          const o2 = interpolate(f, [kidAt(i), kidAt(i) + 6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          const width = Math.min(230, slot - 20);
          return (
            <div key={i} style={{width: slot, display: 'flex', justifyContent: 'center'}}>
              {on ? (
                <div style={{width, opacity: o2}}>
                  <div style={{...stageCard, padding: '20px 10px', textAlign: 'center', background: '#fbfaf6', border: `2px solid ${LINE}`}}>
                    {k.logo ? (
                      <Img src={staticFile(`media/${k.logo}`)} style={{height: 44, objectFit: 'contain', marginBottom: 8}} />
                    ) : null}
                    <div style={{...heavy, fontSize: 32, color: INK}}>{k.title || k}</div>
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** 榜单卡：标题条 + 行，高亮一行（AI 产品榜那一挂） */
const RankStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const rows: any[] = Array.isArray(o.rows) ? o.rows.slice(0, 6) : [];
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 60px'}}>
      <Enter>
        <div style={{width: 920, ...stageCard, overflow: 'hidden'}}>
          {o.title ? (
            <div style={{background: '#241a4d', padding: '22px 30px'}}>
              <div style={{...heavy, fontSize: 36, color: '#ffffff', letterSpacing: 1}}>{o.title}</div>
            </div>
          ) : null}
          <div style={{padding: '8px 0 14px'}}>
            {rows.map((r, i) => {
              const at = 10 + i * 7;
              const on = f >= at;
              const o2 = interpolate(f, [at, at + 6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
              const hi = r.highlight || r.hi;
              return (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 18,
                    padding: '16px 28px',
                    opacity: o2,
                    background: hi ? 'rgba(255,217,61,0.30)' : 'transparent',
                    borderLeft: hi ? `8px solid ${YELLOW}` : '8px solid transparent',
                    transform: `scale(${hi && on ? 1.02 : 1})`,
                  }}
                >
                  <span style={{fontFamily: T.fontMono, fontSize: 30, color: MUTED, width: 44}}>{i + 1}</span>
                  <span style={{flex: 1, minWidth: 0}}>
                    <span style={{...heavy, fontSize: 32, color: INK, display: 'block'}}>{r.name || r.title || ''}</span>
                    {r.sub ? <span style={{fontSize: 22, color: MUTED}}>{r.sub}</span> : null}
                  </span>
                  {r.value ? <span style={{fontFamily: T.fontMono, fontWeight: 700, fontSize: 34, color: INK}}>{r.value}</span> : null}
                  {r.delta ? (
                    <span
                      style={{
                        fontFamily: T.fontMono,
                        fontSize: 26,
                        fontWeight: 700,
                        color: '#0e9f6e',
                        background: 'rgba(52,211,153,0.16)',
                        padding: '4px 12px',
                        borderRadius: 8,
                      }}
                    >
                      {r.delta}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      </Enter>
    </AbsoluteFill>
  );
};

/** 勾选清单：显示器线框 + 逐条打勾（AI 入职干活那一挂） */
const ChecklistStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const items: string[] = (Array.isArray(o.items) ? o.items : []).slice(0, 5);
  return (
    <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
      <Enter>
        <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center'}}>
          <div style={{background: '#171a20', borderRadius: 26, padding: 14, boxShadow: '0 24px 60px rgba(23,26,32,0.28)'}}>
            <div style={{background: '#ffffff', borderRadius: 14, width: 760, minHeight: 280 + items.length * 52, padding: '30px 40px'}}>
              {o.title ? (
                <div style={{...heavy, fontSize: 34, color: INK, marginBottom: 20, display: 'flex', alignItems: 'center', gap: 12}}>
                  <span style={{width: 12, height: 12, borderRadius: 999, background: YELLOW, display: 'inline-block'}} />
                  {o.title}
                </div>
              ) : null}
              {items.map((it, i) => (
                <div key={i} style={{display: 'flex', alignItems: 'center', gap: 18, padding: '10px 0'}}>
                  <TickDot at={8 + i * 9} />
                  <span style={{fontSize: 30, color: INK}}>{it}</span>
                </div>
              ))}
            </div>
          </div>
          <div style={{width: 130, height: 46, background: '#171a20', clipPath: 'polygon(22% 0, 78% 0, 100% 100%, 0 100%)'}} />
          <div style={{width: 230, height: 14, background: '#171a20', borderRadius: 6}} />
        </div>
      </Enter>
    </AbsoluteFill>
  );
};

/** 高亮金句：白卡 + 绿底高亮（新闻截图划重点那一挂） */
const QuoteStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const quote = o.quote || o.title || o.card?.title || '';
  const label = o.label || '';
  return (
    <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 80px'}}>
      <Enter>
        <div style={{...stageCard, padding: '44px 50px', maxWidth: 900}}>
          {label ? <div style={{fontSize: 26, color: MUTED, letterSpacing: 3, marginBottom: 20}}>{label}</div> : null}
          <div style={{...heavy, fontSize: 48, color: INK, lineHeight: 1.5}}>
            <span style={{background: 'rgba(52,211,153,0.35)', padding: '2px 12px', borderRadius: 10}}>{quote}</span>
          </div>
          {o.card?.body ? <div style={{fontSize: 30, color: MUTED, marginTop: 22, lineHeight: 1.6}}>{o.card.body}</div> : null}
        </div>
      </Enter>
    </AbsoluteFill>
  );
};

/** 数字卡：关键数据大号突出（黄条压底） */
const NumberStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  return (
    <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
      <Enter>
        <div style={{textAlign: 'center'}}>
          {o.label ? <div style={{fontSize: 30, color: MUTED, letterSpacing: 4, marginBottom: 24}}>{o.label}</div> : null}
          <div
            style={{
              ...heavy,
              fontSize: o.number && String(o.number).length > 8 ? 110 : 170,
              color: INK,
              lineHeight: 1.1,
              display: 'inline-block',
              borderBottom: `16px solid ${YELLOW}`,
              paddingBottom: 8,
            }}
          >
            {o.number || ''}
          </div>
          {o.caption ? <div style={{fontSize: 36, color: INK, marginTop: 30, ...heavy}}>{o.caption}</div> : null}
        </div>
      </Enter>
    </AbsoluteFill>
  );
};

/** 对比卡：左右两栏各一句 */
const CompareStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const sides = [o.left, o.right].filter(Boolean);
  return (
    <AbsoluteFill style={{display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '0 70px'}}>
      <Enter>
        <div style={{...heavy, fontSize: 42, color: INK, marginBottom: 30, textAlign: 'center'}}>{o.title || ''}</div>
        <div style={{display: 'flex', gap: 26}}>
          {sides.map((s: any, i: number) => (
            <div key={i} style={{flex: 1, ...stageCard, padding: '30px 30px'}}>
              <div style={{...heavy, fontSize: 34, color: i === 0 ? '#6a5acd' : '#0e9f6e'}}>{s.head}</div>
              <div style={{fontSize: 30, color: INK, marginTop: 12, lineHeight: 1.5}}>{s.body}</div>
            </div>
          ))}
        </div>
      </Enter>
    </AbsoluteFill>
  );
};

/** 品牌揭幕：柔和渐变 + 卡片 logo + 名字（产品发布那一挂） */
const BrandStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const main = o.keyword || o.title || o.number || 'GetCut';
  return (
    <AbsoluteFill
      style={{
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(120deg, #dfe7ff 0%, #f3e6ff 45%, #ffe9f3 100%)',
      }}
    >
      <Enter>
        <div style={{textAlign: 'center'}}>
          <div style={{...heavy, fontSize: 120, color: '#3d4470', textShadow: '0 10px 30px rgba(61,68,112,0.25)'}}>{main}</div>
          {o.subtitle || o.caption ? <div style={{fontSize: 36, color: '#5c6470', marginTop: 24}}>{o.subtitle || o.caption}</div> : null}
        </div>
      </Enter>
    </AbsoluteFill>
  );
};

/** 信息卡：面板类的兜底（标题 + 正文 + 角标） */
const CardStage: React.FC<{shot: Shot}> = ({shot}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const title = o.title || o.card?.title || o.card_title || '';
  const body = o.card?.body || o.card_body || o.subtitle || '';
  const badge = o.badge || o.label || '';
  return (
    <AbsoluteFill style={{display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 80px'}}>
      <Enter>
        <div style={{...stageCard, padding: '44px 52px', width: 880, borderLeft: `12px solid ${YELLOW}`}}>
          {badge ? <div style={{fontSize: 26, color: MUTED, letterSpacing: 3, marginBottom: 16}}>{badge}</div> : null}
          {title ? <div style={{...heavy, fontSize: 50, color: INK, lineHeight: 1.3}}>{title}</div> : null}
          {body ? (
            <div style={{fontSize: 30, color: '#454b56', marginTop: 20, lineHeight: 1.7, whiteSpace: 'pre-wrap'}}>{body}</div>
          ) : null}
        </div>
      </Enter>
    </AbsoluteFill>
  );
};

// ---------------- 舞台调度：按 shot 决定用哪个动作 ----------------
const Stage: React.FC<{shot: Shot; index: number}> = ({shot, index}) => {
  const o = (shot.overlay ?? {}) as Record<string, any>;
  const items: string[] = Array.isArray(o.items) ? o.items.map((x: any) => (typeof x === 'string' ? x : x.text || '')) : [];
  const children = Array.isArray(o.children) ? o.children : [];
  const rows = Array.isArray(o.rows) ? o.rows : [];
  const center = o.center;
  let node: React.ReactNode;
  if (shot.media) node = <MediaStage shot={shot} index={index} />;
  else if (center && children.length) node = <TreeStage shot={shot} />;
  else if (rows.length) node = <RankStage shot={shot} />;
  else if (items.length && o.monitor) node = <ChecklistStage shot={shot} />;
  else if (items.length) node = <PillsStage items={items} title={o.title} />;
  else if (shot.kind === 'title_card') node = <PillsStage items={[o.keyword || o.title || ''].filter(Boolean)} title={o.subtitle} />;
  else if (shot.kind === 'quote_card') node = <QuoteStage shot={shot} />;
  else if (shot.kind === 'callout') node = <NumberStage shot={shot} />;
  else if (o.variant === 'compare' && (o.left || o.right)) node = <CompareStage shot={shot} />;
  else node = <CardStage shot={shot} />;
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        top: STAGE_TOP,
        width: '100%',
        height: STAGE_H,
        background: isCard() ? 'transparent' : STAGE_BG,
        overflow: 'hidden',
        backgroundImage: isCard() ? undefined : 'radial-gradient(#e6e3da 2.2px, transparent 2.8px)',
        backgroundSize: isCard() ? undefined : '52px 52px',
      }}
    >
      {node}
    </div>
  );
};

// ---------------- 主入口：三段式骨架 ----------------
export const ZhiguVideo: React.FC<NiwoProps> = (props) => {
  const fps = useVideoConfig().fps;
  return (
    <AbsoluteFill style={{background: DARK, fontFamily: T.font}}>
      <FontFace />
      {/* 顶带：粒子网 + 频道标 + 大标题（card 分轨层不出） */}
      {isCard() ? null : (
        <div style={{position: 'absolute', top: 0, width: '100%', height: BAND_TOP, background: DARK, overflow: 'hidden'}}>
          <ParticleField height={BAND_TOP} seed={7} />
          <ChannelMark />
          <Headline lines={props.headline.lines} />
        </div>
      )}
      {/* 中段舞台底：base 层只出白底，成片/卡片层在此之上出动作 */}
      <div
        style={{
          position: 'absolute',
          top: STAGE_TOP,
          width: '100%',
          height: STAGE_H,
          background: isCard() ? 'transparent' : STAGE_BG,
          backgroundImage: isCard() || isBase() ? undefined : 'radial-gradient(#e6e3da 2.2px, transparent 2.8px)',
          backgroundSize: isCard() || isBase() ? undefined : '52px 52px',
        }}
      />
      {isBase() ? null : props.shots.map((shot, i) => (
        <Sequence key={i} from={msToF(shot.startMs, fps)} durationInFrames={msToF(shot.endMs - shot.startMs, fps) + 1}>
          <Stage shot={shot} index={i} />
        </Sequence>
      ))}
      {/* 底带：粒子网 + 字幕 */}
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
    <div
      style={{
        position: 'absolute',
        left: 56,
        right: 56,
        top: BAND_BOTTOM / 2 - 90,
        textAlign: 'center',
        ...heavy,
        fontSize: 62,
        color: '#ffffff',
        lineHeight: 1.3,
        textShadow: '0 3px 16px rgba(0,0,0,0.7)',
      }}
    >
      {active.text}
    </div>
  );
};
