import React from 'react';
import {
  AbsoluteFill, Audio, OffthreadVideo, Sequence,
  interpolate, staticFile, useCurrentFrame, useVideoConfig,
} from 'remotion';
import { themeOf, type ThemeName } from './themes';
import { Card, Highlight } from './cards';
import { CartoonBeat } from './cartoon';
import { ensureChineseFont } from './font';

export type Beat = {
  text: string;
  card: 'hook' | 'plain' | 'stat' | 'list' | 'compare' | 'quote' | 'cta' | 'intro' | 'chapter';
  topic?: string;
  title?: string;
  value?: string;
  unit?: string;
  label?: string;
  items?: string[];
  left?: string;
  right?: string;
  cta?: string;
  broll?: string;
  screenshot?: string;
  audio: string;
  duration: number;
};

export type VideoProps = {
  theme: ThemeName;
  title: string;
  beats: Beat[];
  fps: number;
};

const TOP = 128;
const STAGE_TOP = 396;
const STAGE_BOTTOM = 560;

/** 背景：两团缓慢移动的光 + 细网格 + 上下压暗，短视频的"底子"就在这三层里。 */
const Background: React.FC<{ theme: ReturnType<typeof themeOf> }> = ({ theme }) => {
  const frame = useCurrentFrame();
  const x1 = 50 + Math.sin(frame / 90) * 14;
  const y1 = 22 + Math.cos(frame / 110) * 8;
  const x2 = 30 + Math.cos(frame / 130) * 12;
  const y2 = 78 + Math.sin(frame / 100) * 6;
  return (
    <AbsoluteFill style={{ background: theme.bg }}>
      <AbsoluteFill style={{
        background: `radial-gradient(760px 620px at ${x1}% ${y1}%, ${theme.blobA}, transparent 62%),
                     radial-gradient(680px 560px at ${x2}% ${y2}%, ${theme.blobB}, transparent 64%)`,
      }} />
      <AbsoluteFill style={{
        backgroundImage: theme.texture,
        backgroundSize: theme.texture.includes('linear-gradient') ? '84px 84px' : 'auto',
        opacity: 0.5,
      }} />
      <AbsoluteFill style={{
        background: 'linear-gradient(180deg, rgba(0,0,0,0.42) 0%, transparent 22%, transparent 74%, rgba(0,0,0,0.5) 100%)',
        opacity: theme.dark ? 0.85 : 0.28,
      }} />
    </AbsoluteFill>
  );
};

/** 顶部：章节 chip + 这一屏的标题，抖音那种"上标题"就在这一条。 */
const TopBar: React.FC<{ theme: ReturnType<typeof themeOf>; beat: Beat; index: number; total: number }> = ({ theme, beat, index, total }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: 'clamp' });
  const topic = beat.topic || '获客 · 一分钟说清';
  return (
    <div style={{ position: 'absolute', left: 64, right: 64, top: TOP, opacity: s }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
        <div style={{
          fontFamily: theme.light, fontSize: 24, letterSpacing: 4, color: theme.accentInk,
          background: theme.accent, padding: '8px 16px', borderRadius: 6,
        }}>{String(index + 1).padStart(2, '0')}</div>
        <div style={{ fontFamily: theme.heavy, fontSize: 42, color: theme.ink, letterSpacing: 1, flex: 1 }}>
          <Highlight text={topic} theme={theme} />
        </div>
        <div style={{ fontFamily: theme.light, fontSize: 24, color: theme.muted, letterSpacing: 2 }}>
          {index + 1}<span style={{ opacity: 0.45 }}>/{total}</span>
        </div>
      </div>
      <div style={{ height: 3, background: theme.hairline, marginTop: 22 }}>
        <div style={{
          height: '100%', background: theme.accent,
          width: `${interpolate(frame, [0, Math.max(1, fps * 0.5)], [((index) / total) * 100, ((index + 1) / total) * 100], { extrapolateRight: 'clamp' })}%`,
        }} />
      </div>
    </div>
  );
};

const Subtitle: React.FC<{ text: string; theme: ReturnType<typeof themeOf> }> = ({ text, theme }) => (
  <div style={{ position: 'absolute', left: 70, right: 70, bottom: 196, display: 'flex', justifyContent: 'center' }}>
    <div style={{
      maxWidth: 920, fontFamily: theme.heavy, fontSize: 52, lineHeight: 1.34, textAlign: 'center',
      color: '#fff', letterSpacing: 0.5,
      textShadow: '0 0 3px rgba(0,0,0,0.9), 2px 2px 0 #000, -2px 2px 0 #000, 2px -2px 0 #000, -2px -2px 0 #000',
    }}>
      <Highlight text={text} theme={theme} base="#fff" />
    </div>
  </div>
);

const BottomBar: React.FC<{ theme: ReturnType<typeof themeOf> }> = ({ theme }) => (
  <div style={{
    position: 'absolute', left: 64, right: 64, bottom: 84, display: 'flex',
    justifyContent: 'space-between', alignItems: 'center',
    fontFamily: theme.light, fontSize: 22, letterSpacing: 4, color: theme.muted,
  }}>
    <div>GETCUT<span style={{ color: theme.accent }}>·</span>获客片</div>
    <div>#获客 #本地生意</div>
  </div>
);

const BeatScene: React.FC<{ beat: Beat; theme: ReturnType<typeof themeOf>; seconds: number; index: number; total: number }> = ({ beat, theme, seconds, index, total }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const frames = Math.max(2, Math.round(seconds * fps));
  const fadeOut = interpolate(frame, [frames - 6, frames], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const push = interpolate(frame, [0, frames], [1.0, 1.03], { extrapolateRight: 'clamp' });
  const cardSpeaksIt = ['hook', 'quote', 'cta', 'plain', 'chapter', 'intro'].includes(beat.card);

  if (beat.card === 'chapter' || beat.card === 'intro') {
    return (
      <AbsoluteFill style={{ opacity: fadeOut, justifyContent: 'center', alignItems: 'center' }}>
        <Card beat={beat} theme={theme} />
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ opacity: fadeOut }}>
      {beat.broll ? (
        <AbsoluteFill style={{ overflow: 'hidden' }}>
          <OffthreadVideo
            src={staticFile(beat.broll)}
            muted
            style={{ width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${1.06 + push * 0.02})` }}
          />
          <AbsoluteFill style={{ background: theme.dark ? 'rgba(0,0,0,0.58)' : 'rgba(255,255,255,0.55)' }} />
        </AbsoluteFill>
      ) : null}
      <TopBar theme={theme} beat={beat} index={index} total={total} />
      <div style={{
        position: 'absolute', left: 64, right: 64, top: STAGE_TOP, bottom: STAGE_BOTTOM,
        transform: `scale(${push})`,
      }}>
        <Card beat={beat} theme={theme} />
      </div>
      {cardSpeaksIt ? null : <Subtitle text={beat.text} theme={theme} />}
      <BottomBar theme={theme} />
    </AbsoluteFill>
  );
};

export const Video: React.FC<VideoProps> = ({ theme: name, beats }) => {
  ensureChineseFont();
  const theme = themeOf(name);
  let from = 0;
  return (
    <AbsoluteFill style={{ background: theme.bg, fontFamily: theme.heavy }}>
      <Background theme={theme} />
      <Audio src={staticFile(theme.music)} loop volume={0.08} />
      {beats.map((beat, i) => {
        const frames = Math.max(1, Math.round(beat.duration * 30));
        const seq = (
          <Sequence key={i} from={from} durationInFrames={frames} name={`${i + 1}. ${beat.card}`}>
            {name === 'cartoon'
              ? <CartoonBeat beat={beat} theme={theme} seconds={beat.duration} index={i} total={beats.length} />
              : <BeatScene beat={beat} theme={theme} seconds={beat.duration} index={i} total={beats.length} />}            {beat.audio ? <Audio src={staticFile(beat.audio)} /> : null}
            <Audio src={staticFile('sfx/whoosh.mp3')} volume={0.10} />
            {beat.card === 'stat' ? <Audio src={staticFile('sfx/tick.mp3')} volume={0.3} /> : null}
            {beat.card === 'cta' ? <Audio src={staticFile('sfx/hit.mp3')} volume={0.26} /> : null}
          </Sequence>
        );
        from += frames;
        return seq;
      })}
    </AbsoluteFill>
  );
};
