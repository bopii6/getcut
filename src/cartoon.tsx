import React from 'react';
import {
  AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig,
} from 'remotion';
import type { Beat } from './Video';
import type { Theme } from './themes';
import { Highlight } from './cards';

/**
 * cartoon —— "卡通主播 + 截图 + 大字幕" 三段式模板。
 *
 * 一个镜头 = 一句话，但画面内部再切两刀（phase 0 / 1），
 * 所以 4 秒的镜头看起来也有 3 个变化，不会呆。
 */

type Layout = 'stage' | 'fullbleed' | 'split' | 'duo' | 'punch';

const ROTA: Record<string, Layout[]> = {
  hook: ['fullbleed', 'punch'],
  intro: ['punch'],
  chapter: ['punch'],
  stat: ['split', 'stage'],
  list: ['stage', 'split'],
  compare: ['duo'],
  quote: ['punch'],
  cta: ['punch'],
  plain: ['stage', 'fullbleed'],
};

const layoutOf = (beat: Beat, i: number): Layout => {
  const arr = ROTA[beat.card] || ['stage'];
  return arr[i % arr.length];
};

const pop = (frame: number, fps: number, delay = 0, stiffness = 190) =>
  spring({ frame: frame - delay, fps, config: { damping: 16, mass: 0.55, stiffness } });

/** 底部手绘主播：呼吸 + 嘴动 + 可选镜像 */
const Host: React.FC<{
  theme: Theme; src?: string; height?: number; bottom?: number;
  left?: number; flip?: boolean; talk?: boolean; delay?: number;
}> = ({ theme, src = 'cartoon/host.png', height = 560, bottom = -46, left = 0.5, flip, talk = true, delay = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = pop(frame, fps, delay, 150);
  const bob = Math.sin((frame / fps) * 2.6) * 7;
  const mouth = talk ? (Math.sin((frame / fps) * 17) * 0.5 + 0.5) : 0;
  const w = height * 0.92;
  return (
    <div style={{
      position: 'absolute', left: `${left * 100}%`, bottom: bottom + bob,
      width: w, height, transform: `translateX(-50%) scale(${0.94 + s * 0.06})${flip ? ' scaleX(-1)' : ''}`,
      opacity: Math.min(1, s * 1.4),
    }}>
      <Img src={staticFile(src)} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
      {mouth > 0.35 ? (
        <div style={{
          position: 'absolute', left: '50%', top: '45.5%',
          width: 18, height: 6 + 10 * mouth, marginLeft: -9, borderRadius: 99,
          background: theme.ink,
        }} />
      ) : null}
    </div>
  );
};

/** 字幕：上小标 + 下大字，数字自动高亮 */
const Caption: React.FC<{ theme: Theme; kicker?: string; text: string; big?: boolean; onDark?: boolean; delay?: number }> =
  ({ theme, kicker, text, big, onDark, delay = 0 }) => {
    const frame = useCurrentFrame();
    const { fps } = useVideoConfig();
    const s1 = pop(frame, fps, delay, 210);
    const s2 = pop(frame, fps, delay + 3, 210);
    const size = big ? 118 : text.length > 12 ? 84 : 96;
    return (
      <div style={{ position: 'absolute', left: 62, right: 62, top: 132 }}>
        {kicker ? (
          <div style={{
            fontFamily: theme.heavy, fontSize: 34, letterSpacing: 3,
            color: onDark ? 'rgba(255,255,255,0.62)' : theme.muted,
            opacity: Math.min(1, s1 * 1.5), transform: `translateY(${(1 - s1) * 18}px)`,
          }}>{kicker}</div>
        ) : null}
        <div style={{
          fontFamily: theme.heavy, fontSize: size, lineHeight: 1.12, letterSpacing: -1,
          color: theme.accent, marginTop: 14,
          opacity: Math.min(1, s2 * 1.5), transform: `translateY(${(1 - s2) * 26}px)`,
        }}>
          <Highlight text={text} theme={theme} base={theme.accent} />
        </div>
      </div>
    );
  };

/** 那张"截图"：带窗口 chrome 的白卡，内容按 card 类型变 */
const Panel: React.FC<{ theme: Theme; beat: Beat; phase: number; bare?: boolean }> = ({ theme, beat, phase, bare }) => {
  const items = (beat.items?.length ? beat.items : beat.text.split(/[、，,；;]/)).filter(Boolean).slice(0, 4);
  const rows = beat.card === 'stat'
    ? [[beat.label || '当期', String(beat.value || '—') + (beat.unit || '')], ['上期', '—'], ['变化', '↑']]
    : items.map((t, i) => [t, i === 0 ? '进行中' : '—']);

  return (
    <div style={{
      width: '100%', height: '100%', borderRadius: bare ? 14 : 26,
      background: '#fffdf7', border: `3px solid ${theme.ink}`,
      boxShadow: '0 18px 0 rgba(24,34,58,0.10)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
    }}>
      <div style={{
        height: 64, display: 'flex', alignItems: 'center', gap: 12, padding: '0 22px',
        borderBottom: `2px solid rgba(24,34,58,0.14)`,
      }}>
        {['#e2604a', '#eeb048', '#78b482'].map((c) => (
          <div key={c} style={{ width: 16, height: 16, borderRadius: 99, background: c }} />
        ))}
        <div style={{
          flex: 1, textAlign: 'center', fontFamily: theme.heavy, fontSize: 24, color: 'rgba(24,34,58,0.45)',
        }}>{beat.topic || '截图'}</div>
      </div>
      <div style={{ padding: '26px 30px', display: 'flex', flexDirection: 'column', gap: 18 }}>
        {rows.map(([a, b], i) => (
          <div key={i} style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            borderBottom: `1px solid rgba(24,34,58,0.10)`, paddingBottom: 14,
            opacity: i <= phase * 2 ? 1 : 0.25,
            transform: `translateX(${i <= phase * 2 ? 0 : 8}px)`,
          }}>
            <div style={{ fontFamily: theme.heavy, fontSize: 34, color: theme.ink }}>{a}</div>
            <div style={{
              fontFamily: theme.heavy, fontSize: 34,
              color: i === 0 ? theme.accent : theme.muted,
            }}>{b}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

const Stage: React.FC<{ theme: Theme; beat: Beat; phase: number; index: number }> = ({ theme, beat, phase, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = pop(frame, fps, 2, 170);
  return (
    <AbsoluteFill>
      <Caption theme={theme} kicker={beat.topic} text={beat.title || beat.text} delay={0} />
      <div style={{
        position: 'absolute', left: 70, right: 70, top: 470, height: 620,
        transform: `translateY(${(1 - s) * 60}px) scale(${0.97 + phase * 0.03})`, opacity: Math.min(1, s * 1.3),
      }}>
        <Panel theme={theme} beat={beat} phase={phase} />
      </div>
      <Host theme={theme} height={560} bottom={-40} talk delay={3} />
      <div style={{ position: 'absolute', right: 62, top: 1180, fontFamily: theme.heavy, fontSize: 120, color: 'rgba(24,34,58,0.10)' }}>
        {String(index + 1).padStart(2, '0')}
      </div>
    </AbsoluteFill>
  );
};

const FullBleed: React.FC<{ theme: Theme; beat: Beat; phase: number }> = ({ theme, beat, phase }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const zoom = interpolate(frame, [0, 90], [1.0, 1.03], { extrapolateRight: 'clamp' });
  const s = pop(frame, fps, 0, 200);
  return (
    <AbsoluteFill>
      <div style={{ position: 'absolute', inset: 26, transform: `scale(${zoom})` }}>
        <Panel theme={theme} beat={beat} phase={phase} bare />
      </div>
      <AbsoluteFill style={{ background: 'linear-gradient(180deg, rgba(10,12,16,0.82) 0%, rgba(10,12,16,0.35) 34%, transparent 62%)' }} />
      <div style={{ position: 'absolute', left: 62, right: 62, top: 120, opacity: Math.min(1, s * 1.5), transform: `translateY(${(1 - s) * 30}px)` }}>
        {beat.topic ? (
          <div style={{ fontFamily: theme.heavy, fontSize: 30, letterSpacing: 3, color: 'rgba(255,255,255,0.6)' }}>{beat.topic}</div>
        ) : null}
        <div style={{
          fontFamily: theme.heavy, fontSize: beat.text.length > 12 ? 78 : 96, lineHeight: 1.14,
          color: '#fff', marginTop: 10,
          textShadow: '0 4px 0 rgba(0,0,0,0.35)',
        }}>
          <Highlight text={beat.title || beat.text} theme={theme} base="#fff" />
        </div>
      </div>
      <Host theme={theme} height={430} bottom={-30} left={0.78} talk={false} delay={4} />
    </AbsoluteFill>
  );
};

const Split: React.FC<{ theme: Theme; beat: Beat; phase: number }> = ({ theme, beat, phase }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = pop(frame, fps, 1, 200);
  const v = beat.value || (beat.text.match(/\d+(?:\.\d+)?/) || [''])[0];
  return (
    <AbsoluteFill>
      <div style={{ position: 'absolute', left: 62, right: 62, top: 130, fontFamily: theme.heavy, fontSize: 60, lineHeight: 1.16, color: theme.ink }}>
        <Highlight text={beat.title || beat.text} theme={theme} />
      </div>
      <div style={{ position: 'absolute', left: 56, top: 430, width: 520, height: 560, transform: `rotate(-1.2deg) scale(${0.96 + s * 0.04})` }}>
        <Panel theme={theme} beat={beat} phase={phase} />
      </div>
      <div style={{ position: 'absolute', right: 56, top: 470, textAlign: 'right' }}>
        <div style={{
          fontFamily: theme.heavy, fontSize: 190, lineHeight: 0.95, color: theme.accent,
          transform: `scale(${0.9 + s * 0.1})`, transformOrigin: 'right top',
        }}>{v}</div>
        <div style={{ fontFamily: theme.heavy, fontSize: 54, color: theme.ink }}>{beat.unit || ''}</div>
        <div style={{ width: 240, height: 10, background: theme.accent, marginTop: 18, marginLeft: 'auto' }} />
      </div>
      <Host theme={theme} height={470} bottom={-34} left={0.5} talk delay={5} />
    </AbsoluteFill>
  );
};

const Duo: React.FC<{ theme: Theme; beat: Beat; phase: number }> = ({ theme, beat, phase }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = pop(frame, fps, 4, 160);
  return (
    <AbsoluteFill>
      <Caption theme={theme} kicker={beat.topic} text={beat.title || ''} />
      <div style={{
        position: 'absolute', left: 90, right: 90, top: 620,
        background: '#fffdf7', border: `3px solid ${theme.ink}`, borderRadius: 24,
        padding: '38px 34px', opacity: Math.min(1, s * 1.4), transform: `translateY(${(1 - s) * 24}px)`,
      }}>
        <div style={{ fontFamily: theme.heavy, fontSize: 30, letterSpacing: 3, color: theme.muted }}>
          {beat.left || '他说'}
        </div>
        <div style={{ fontFamily: theme.heavy, fontSize: 60, lineHeight: 1.22, color: theme.ink, marginTop: 12 }}>
          <Highlight text={beat.text} theme={theme} />
        </div>
        {phase >= 1 ? (
          <div style={{
            fontFamily: theme.heavy, fontSize: 46, color: theme.accent, marginTop: 18,
            borderTop: `2px dashed rgba(24,34,58,0.18)`, paddingTop: 16,
          }}>{beat.right || '但是——'}</div>
        ) : null}
      </div>
      <Host theme={theme} src="cartoon/host2.png" height={520} bottom={-36} left={0.24} talk delay={2} />
      <Host theme={theme} height={520} bottom={-36} left={0.76} flip talk delay={7} />
    </AbsoluteFill>
  );
};

const Punch: React.FC<{ theme: Theme; beat: Beat; phase: number }> = ({ theme, beat, phase }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const big = String(beat.title || beat.value || beat.text).slice(0, 6);
  const s = pop(frame, fps, 0, 230);
  const sub = beat.text && beat.text !== big ? beat.text : '';
  return (
    <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center' }}>
      <div style={{
        fontFamily: theme.heavy, fontSize: big.length > 3 ? 200 : 300, lineHeight: 1,
        color: theme.accent, transform: `scale(${1.22 - s * 0.22}) rotate(-2deg)`,
        opacity: Math.min(1, s * 1.6), letterSpacing: -6,
      }}>{big}</div>
      {sub ? (
        <div style={{
          position: 'absolute', bottom: 300, left: 80, right: 80, textAlign: 'center',
          fontFamily: theme.heavy, fontSize: 52, color: theme.ink, opacity: phase >= 1 ? 1 : 0.35,
        }}>{sub}</div>
      ) : null}
      <Host theme={theme} height={380} bottom={-40} left={0.82} talk={false} delay={6} />
    </AbsoluteFill>
  );
};

export const CartoonBeat: React.FC<{ beat: Beat; theme: Theme; seconds: number; index: number; total: number }> =
  ({ beat, theme, seconds, index }) => {
    const frame = useCurrentFrame();
    const { fps } = useVideoConfig();
    const frames = Math.max(2, Math.round(seconds * fps));
    const phase = frame >= frames * 0.46 ? 1 : 0;
    const fade = interpolate(frame, [frames - 4, frames], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
    const punchIn = interpolate(frame, [0, 3], [1.035, 1], { extrapolateRight: 'clamp' });
    const layout = layoutOf(beat, index);

    return (
      <AbsoluteFill style={{ opacity: fade, transform: `scale(${punchIn})` }}>
        {layout === 'stage' && <Stage theme={theme} beat={beat} phase={phase} index={index} />}
        {layout === 'fullbleed' && <FullBleed theme={theme} beat={beat} phase={phase} />}
        {layout === 'split' && <Split theme={theme} beat={beat} phase={phase} />}
        {layout === 'duo' && <Duo theme={theme} beat={beat} phase={phase} />}
        {layout === 'punch' && <Punch theme={theme} beat={beat} phase={phase} />}

        <div style={{
          position: 'absolute', left: 0, bottom: 0, height: 8, width: `${((index + 1) / 6) * 100}%`,
          background: theme.accent, opacity: 0.9,
        }} />
        <div style={{
          position: 'absolute', left: 62, bottom: 56, fontFamily: theme.heavy, fontSize: 26,
          letterSpacing: 3, color: theme.muted,
        }}>@你的账号</div>
        <div style={{
          position: 'absolute', right: 62, bottom: 56, fontFamily: theme.heavy, fontSize: 26,
          letterSpacing: 2, color: theme.muted,
        }}>卡通主播模板 · {String(index + 1).padStart(2, '0')}</div>
      </AbsoluteFill>
    );
  };
