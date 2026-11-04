import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Beat } from './Video';
import type { Theme } from './themes';

/** 一句话里把数字/金额/比例挑出来上色。 */
const KEYWORD = /(\d+(?:\.\d+)?\s*(?:万|亿|%|元|块|天|年|个月|倍|件|人|分)?|[一二三四五六七八九十百]+(?:万|亿|%|元|天|年|个月|倍|件|人|分)?)/g;

export const Highlight: React.FC<{ text: string; theme: Theme; base?: string }> = ({ text, theme, base }) => {
  const parts = String(text).split(KEYWORD);
  return (
    <>
      {parts.map((p, i) => (
        i % 2 === 1
          ? <span key={i} style={{ color: theme.accent, fontWeight: 900 }}>{p}</span>
          : <span key={i} style={{ color: base || 'inherit' }}>{p}</span>
      ))}
    </>
  );
};

const enter = (frame: number, fps: number, delay = 0, lift = 34) => {
  const s = spring({ frame: frame - delay, fps, config: { damping: 20, mass: 0.8, stiffness: 110 } });
  return { opacity: Math.min(1, s * 1.2), transform: `translateY(${(1 - s) * lift}px)` };
};

const stage: React.CSSProperties = {
  position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center',
};

/** 舞台底纹：入场时一条竖线从中间长出来，给画面一个"开演"的动作。 */
const OpenLine: React.FC<{ theme: Theme }> = ({ theme }) => {
  const frame = useCurrentFrame();
  const h = interpolate(frame, [0, 14], [0, 100], { extrapolateRight: 'clamp' });
  return (
    <div style={{
      position: 'absolute', left: 0, top: `${(100 - h) / 2}%`, height: `${h}%`,
      width: 6, background: theme.accent, opacity: 0.9,
    }} />
  );
};

const Hook: React.FC<{ beat: Beat; theme: Theme }> = ({ beat, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const lines = String(beat.title || beat.text).split(/[，,]/).filter(Boolean);
  return (
    <div style={stage}>
      <OpenLine theme={theme} />
      <div style={{ paddingLeft: 28 }}>
        {lines.map((line, i) => {
          const s = spring({ frame: frame - i * 6, fps, config: { damping: 22, mass: 0.9 } });
          return (
            <div key={i} style={{
              fontFamily: theme.heavy, fontSize: 116, lineHeight: 1.16, color: theme.ink,
              letterSpacing: -1, opacity: Math.min(1, s * 1.2),
              transform: `translateY(${(1 - s) * 40}px)`,
            }}>
              <Highlight text={line} theme={theme} />
            </div>
          );
        })}
        <div style={{ width: 260, height: 8, background: theme.accent, marginTop: 40 }} />
      </div>
    </div>
  );
};

const Stat: React.FC<{ beat: Beat; theme: Theme }> = ({ beat, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame, fps, config: { damping: 16, stiffness: 130 } });
  const numeric = Number(String(beat.value ?? '').replace(/[^\d.]/g, ''));
  const shown = Number.isFinite(numeric)
    ? Math.round(numeric * interpolate(frame, [0, 22], [0, 1], { extrapolateRight: 'clamp' }))
    : beat.value;
  const bars = [0.42, 0.68, 1].map((h, i) => Math.min(1, Math.max(0, (frame - 8 - i * 4) / 12)) * h);
  return (
    <div style={{ ...stage, paddingLeft: 28 }}>
      <div style={{ display: 'flex', alignItems: 'flex-end' }}>
        <div style={{
          fontFamily: theme.heavy, fontSize: 300, lineHeight: 0.9, color: theme.accent,
          letterSpacing: -10, fontVariantNumeric: 'tabular-nums',
          transform: `scale(${0.9 + s * 0.1})`, transformOrigin: 'left bottom',
        }}>{shown}</div>
        <div style={{ fontFamily: theme.heavy, fontSize: 92, color: theme.ink, marginLeft: 16, marginBottom: 26 }}>
          {beat.unit || ''}
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 14, height: 130, marginTop: 8 }}>
        {bars.map((h, i) => (
          <div key={i} style={{ width: 74, height: `${h * 100}%`, background: i === 2 ? theme.accent : theme.hairline }} />
        ))}
        <div style={{ marginLeft: 12, fontFamily: theme.light, fontSize: 32, color: theme.muted, marginBottom: 6 }}>
          {beat.label || ''}
        </div>
      </div>
    </div>
  );
};

const List: React.FC<{ beat: Beat; theme: Theme }> = ({ beat, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const items = (beat.items?.length ? beat.items : String(beat.text).split(/[、，,；;]/)).filter(Boolean).slice(0, 4);
  return (
    <div style={{ ...stage, justifyContent: 'center' }}>
      {beat.title ? (
        <div style={{ fontFamily: theme.heavy, fontSize: 54, color: theme.ink, marginBottom: 26, ...enter(frame, fps) }}>
          <Highlight text={beat.title} theme={theme} />
        </div>
      ) : null}
      {items.map((item, i) => (
        <div key={i} style={{
          display: 'flex', alignItems: 'flex-start', gap: 24, marginBottom: 26,
          ...enter(frame, fps, 4 + i * 5, 28),
        }}>
          <div style={{
            minWidth: 56, height: 56, borderRadius: 8, background: i === 0 ? theme.accent : 'transparent',
            border: `2px solid ${i === 0 ? theme.accent : theme.hairline}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: theme.heavy, fontSize: 28, color: i === 0 ? theme.accentInk : theme.muted,
          }}>{String(i + 1).padStart(2, '0')}</div>
          <div style={{ fontFamily: theme.heavy, fontSize: 58, lineHeight: 1.26, color: theme.ink, flex: 1 }}>
            <Highlight text={item} theme={theme} />
          </div>
        </div>
      ))}
    </div>
  );
};

const Compare: React.FC<{ beat: Beat; theme: Theme }> = ({ beat, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const vs = spring({ frame: frame - 6, fps, config: { damping: 14, stiffness: 160 } });
  const cols = [
    { head: '别人', body: beat.left || '', hot: false },
    { head: '我们', body: beat.right || '', hot: true },
  ];
  return (
    <div style={{ ...stage, justifyContent: 'center' }}>
      <div style={{ display: 'flex', gap: 20, alignItems: 'stretch' }}>
        {cols.map((c, i) => (
          <div key={i} style={{
            flex: 1, padding: '40px 30px', minHeight: 560, borderRadius: 12,
            background: c.hot ? theme.panel : 'transparent',
            border: `3px solid ${c.hot ? theme.accent : theme.hairline}`,
            display: 'flex', flexDirection: 'column', gap: 22,
            ...enter(frame, fps, i * 5, 24),
          }}>
            <div style={{ fontFamily: theme.light, fontSize: 24, letterSpacing: 6, color: c.hot ? theme.accent : theme.muted }}>{c.head}</div>
            <div style={{ fontFamily: theme.heavy, fontSize: 62, lineHeight: 1.26, color: theme.ink }}>{c.body}</div>
          </div>
        ))}
      </div>
      <div style={{
        position: 'absolute', left: '50%', top: '48%', transform: `translate(-50%,-50%) scale(${vs})`,
        width: 108, height: 108, borderRadius: '50%', background: theme.accent, color: theme.accentInk,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: theme.heavy, fontSize: 40, letterSpacing: 1,
      }}>VS</div>
    </div>
  );
};

const Quote: React.FC<{ beat: Beat; theme: Theme }> = ({ beat, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame, fps, config: { damping: 20 } });
  return (
    <div style={{ ...stage, paddingLeft: 28 }}>
      <div style={{ fontFamily: theme.heavy, fontSize: 280, lineHeight: 0.55, color: theme.accent, opacity: 0.25 }}>“</div>
      <div style={{
        fontFamily: theme.heavy, fontSize: 92, lineHeight: 1.26, color: theme.ink, marginTop: 10,
        transform: `translateX(${(1 - s) * -30}px)`, opacity: Math.min(1, s * 1.2),
      }}>
        <Highlight text={beat.title || beat.text} theme={theme} />
      </div>
    </div>
  );
};

const Cta: React.FC<{ beat: Beat; theme: Theme }> = ({ beat, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div style={{ ...stage, justifyContent: 'center' }}>
      <div style={{ background: theme.accent, padding: '54px 40px', borderRadius: 14, ...enter(frame, fps) }}>
        <div style={{ fontFamily: theme.heavy, fontSize: 76, lineHeight: 1.24, color: theme.accentInk, textAlign: 'center' }}>
          {beat.cta || beat.title || beat.text}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 14, marginTop: 26, justifyContent: 'center', opacity: spring({ frame: frame - 10, fps, config: { damping: 200 } }) }}>
        {['私信', '评论', '到店咨询'].map((t) => (
          <div key={t} style={{
            border: `2px solid ${theme.hairline}`, borderRadius: 999, padding: '12px 26px',
            fontFamily: theme.light, fontSize: 32, color: theme.ink,
          }}>{t}</div>
        ))}
      </div>
    </div>
  );
};

const Plain: React.FC<{ beat: Beat; theme: Theme }> = ({ beat, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const words = String(beat.text).split(/[，。！？；、,.;!?]/).map((s) => s.trim()).filter((s) => s.length >= 2).slice(0, 3);
  return (
    <div style={{ ...stage, paddingLeft: 28, gap: 22 }}>
      {words.map((w, i) => {
        const s = spring({ frame: frame - i * 7, fps, config: { damping: 18, stiffness: 120 } });
        return (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 20,
            opacity: Math.min(1, s * 1.2), transform: `translateX(${(1 - s) * -26}px)`,
          }}>
            <div style={{ width: 12, height: 12, borderRadius: 3, background: theme.accent }} />
            <div style={{ fontFamily: theme.heavy, fontSize: 72, lineHeight: 1.2, color: theme.ink }}>
              <Highlight text={w} theme={theme} />
            </div>
          </div>
        );
      })}
    </div>
  );
};

const Chapter: React.FC<{ beat: Beat; theme: Theme }> = ({ beat, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame, fps, config: { damping: 16, stiffness: 120 } });
  const n = String(beat.value || '1').padStart(2, '0');
  return (
    <div style={{ textAlign: 'center', transform: `scale(${0.94 + s * 0.06})`, opacity: Math.min(1, s * 1.3) }}>
      <div style={{
        fontFamily: theme.heavy, fontSize: 300, lineHeight: 1, color: 'transparent',
        WebkitTextStroke: `3px ${theme.accent}`, opacity: 0.7,
      }}>{n}</div>
      <div style={{ fontFamily: theme.light, fontSize: 30, letterSpacing: 12, color: theme.muted, marginTop: 10 }}>
        第 {n} 部分
      </div>
      <div style={{ fontFamily: theme.heavy, fontSize: 96, lineHeight: 1.2, color: theme.ink, marginTop: 22 }}>
        {beat.title}
      </div>
      <div style={{ width: 220, height: 8, background: theme.accent, margin: '34px auto 0' }} />
    </div>
  );
};

const Intro: React.FC<{ beat: Beat; theme: Theme }> = ({ beat, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame, fps, config: { damping: 18, stiffness: 110 } });
  return (
    <div style={{ textAlign: 'center', opacity: Math.min(1, s * 1.2), transform: `translateY(${(1 - s) * 26}px)` }}>
      <div style={{ fontFamily: theme.heavy, fontSize: 44, letterSpacing: 16, color: theme.accent }}>GETCUT</div>
      <div style={{ fontFamily: theme.light, fontSize: 28, letterSpacing: 8, color: theme.muted, marginTop: 12 }}>
        本机出片 · 一分钟说清
      </div>
      <div style={{ fontFamily: theme.heavy, fontSize: 88, lineHeight: 1.24, color: theme.ink, marginTop: 34, maxWidth: 860 }}>
        {beat.title}
      </div>
      <div style={{ width: 180, height: 6, background: theme.accent, margin: '30px auto 0' }} />
    </div>
  );
};

export const Card: React.FC<{ beat: Beat; theme: Theme }> = ({ beat, theme }) => {
  switch (beat.card) {
    case 'hook': return <Hook beat={beat} theme={theme} />;
    case 'stat': return <Stat beat={beat} theme={theme} />;
    case 'list': return <List beat={beat} theme={theme} />;
    case 'compare': return <Compare beat={beat} theme={theme} />;
    case 'quote': return <Quote beat={beat} theme={theme} />;
    case 'cta': return <Cta beat={beat} theme={theme} />;
    case 'chapter': return <Chapter beat={beat} theme={theme} />;
    case 'intro': return <Intro beat={beat} theme={theme} />;
    default: return <Plain beat={beat} theme={theme} />;
  }
};
