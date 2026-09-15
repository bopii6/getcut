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

// ---------------- tokens (sampled from the reference video) ----------------

const FontFace: React.FC = () => {
  const [handle] = React.useState(() => delayRender('loading font'));
  React.useEffect(() => {
    document.fonts.load('900 100px SSH').then(() => continueRender(handle)).catch(() => continueRender(handle));
  }, []);
  return (
  <style
    dangerouslySetInnerHTML={{
      __html: `@font-face { font-family: 'SSH'; src: url('${staticFile(
        'fonts/SourceHanSansCN-Heavy.otf',
      )}') format('opentype'); font-weight: 900; }`,
    }}
  />
  );
};

export const T = {
  accent: '#a44231',
  accentSoft: '#c14f35',
  bgTop: '#1c1a18',
  bgBottom: '#171411',
  paper: '#e4e2e0',
  paperGrain: 'rgba(120,115,110,0.05)',
  ink: '#1c1a18',
  panel: '#1a1817',
  red: '#a44231',
  redBright: '#c14f35',
  teal: '#7fd4c9',
  white: '#f5f3f0',
  cardWhite: '#eee9e2',
  gray: '#999590',
  grayDim: '#76706a',
  font: "'SSH','Source Han Sans CN','Microsoft YaHei',sans-serif",
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
  template?: 'editorial' | 'portrait';
  shots: Shot[];
  clauses: Clause[];
};

export const estW = (text: string, size: number) => {
  let w = 0;
  for (const ch of text) w += ch.charCodeAt(0) > 0x2e80 ? size : size * 0.56;
  return w;
};
const fitSize = (text: string, maxSize: number, maxW: number) =>
  Math.min(maxSize, Math.max(20, (maxW / Math.max(estW(text, maxSize), 1)) * maxSize));

const msToF = (ms: number, fps: number) => Math.round((ms / 1000) * fps);

const heavy: React.CSSProperties = {fontFamily: T.font, fontWeight: 900};

const Tick: React.CSSProperties = {
  display: 'inline-block',
  width: 8,
  height: 30,
  background: T.accent,
  marginRight: 14,
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
        color: '#f7f2ec',
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
          color: '#d2cdc6',
          letterSpacing: 2,
          fontFamily: 'Consolas, monospace',
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
          opacity: o * 0.38,
          ...heavy,
          fontSize: 96,
          color: '#c9c3bc',
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
        background: 'linear-gradient(to left, rgba(16,12,9,0.94) 55%, rgba(16,12,9,0.55) 80%, rgba(16,12,9,0))',
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
        <div style={{fontSize: 26, color: '#c9c3bc', opacity: capO, marginTop: 6}}>
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
    <div style={{position: 'absolute', inset: 0, background: 'rgba(18,14,11,0.55)'}}>
      <div style={{position: 'absolute', left: 36, top: 30, opacity: tO}}>
        <div style={{...heavy, fontSize: 72, color: T.white}}>{spec.title}</div>
        <div style={{fontSize: 30, color: '#b7b1aa', marginTop: 8}}>{spec.subtitle}</div>
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
          <span style={{...heavy, fontSize: 26, color: T.cardWhite, background: T.accent, padding: '6px 20px', borderRadius: 20}}>
            {spec.pillA}
          </span>
          <span style={{...heavy, fontSize: 26, color: '#6a655f', border: '2px solid #b7b1aa', padding: '4px 18px', borderRadius: 20}}>
            {spec.pillB}
          </span>
        </div>
        <div style={{marginTop: 22, height: 12, width: 420, background: '#d4d0ca', borderRadius: 6}} />
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
    <div style={{position: 'absolute', inset: 0, background: 'rgba(18,14,11,0.55)'}}>
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
            background: 'rgba(32,17,10,0.82)',
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
    <div style={{position: 'absolute', inset: 0, background: 'rgba(18,14,11,0.45)'}}>
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
        <div style={{...heavy, fontSize: 40, color: T.ink}}>{spec.card?.title}</div>
        <div style={{fontSize: 26, color: '#5a5651', marginTop: 14, lineHeight: 1.4}}>
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
    <div style={{position: 'absolute', inset: 0, background: 'rgba(18,14,11,0.55)'}}>
      <div style={{position: 'absolute', left: 36, top: 30, opacity: tO}}>
        <div style={{...heavy, fontSize: 64, color: T.white}}>{spec.title}</div>
        <div style={{fontSize: 28, color: '#b7b1aa', marginTop: 10}}>{spec.subtitle}</div>
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
              <span style={{fontSize: 24, color: T.accentSoft, fontFamily: 'Consolas, monospace'}}>{row.code}</span>
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
      {media ? (
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
  if (!shot.media) return null;
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
        left: 115,
        top: 596,
        width: 849,
        height: 844,
        borderRadius: 16,
        background: T.panel,
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
              left: 36,
              top: 71,
              width: 778,
              height: 440,
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
                  color: 'rgba(240,236,230,0.85)',
                  fontFamily: 'Consolas, monospace',
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
                  background: 'rgba(196,79,53,0.85)',
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
const Background: React.FC = () => (
  <AbsoluteFill
    style={{
      background: `radial-gradient(120% 90% at 50% 30%, ${T.bgTop} 0%, ${T.bgBottom} 78%, #100e0c 100%)`,
    }}
  >
    <AbsoluteFill
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.02' numOctaves='3'/><feColorMatrix type='matrix' values='0 0 0 0 0.5 0 0 0 0 0.48 0 0 0 0 0.45 0 0 0 0.05 0'/></filter><rect width='240' height='240' filter='url(%23n)'/></svg>\")",
      }}
    />
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
        return (
          <div key={i} style={{display: 'flex', alignItems: 'center', marginTop: 14, paddingLeft: 115}}>
            {before ? (
              <span style={{...heavy, fontSize: 88, color: T.ink, whiteSpace: 'pre'}}>{before}</span>
            ) : null}
            <div
              style={{
                flex: 1,
                marginLeft: 8,
                marginRight: 22,
                background: '#16110e',
                borderRadius: 10,
                padding: '2px 0 6px 0',
                position: 'relative',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: 104,
              }}
            >
              <div style={{position: 'absolute', left: 2, top: 0, bottom: 0, width: 10, background: T.red}} />
              <span style={{...heavy, fontSize: 88, color: T.white}}>{line.highlight}</span>
            </div>
            {after ? (
              <span style={{...heavy, fontSize: 88, color: T.ink}}>{after}</span>
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
  if (!active) return null;
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
  if (!shot.media) return null;
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
  if (!active) return null;
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
      opacity: o, background: 'rgba(14,11,9,0.74)', border: `2px solid ${T.red}`, borderRadius: 16,
      padding: '30px 34px', boxShadow: '0 18px 50px rgba(0,0,0,0.5)'}}>
      {spec.label ? (
        <div style={{...heavy, fontSize: 26, color: T.redBright, marginBottom: 12, letterSpacing: 1}}>{spec.label}</div>
      ) : null}
      {main ? <div style={{...heavy, fontSize: 54, color: T.white, lineHeight: 1.15}}>{main}</div> : null}
      {sub ? <div style={{fontSize: 30, color: '#d8d3cd', marginTop: 10}}>{sub}</div> : null}
      {showCompare ? (
        <div style={{display: 'flex', gap: 22, marginTop: 18}}>
          {[spec.left, spec.right].map((side, i) => side ? (
            <div key={i} style={{flex: 1, background: 'rgba(255,255,255,0.06)', borderRadius: 12, padding: '16px 18px'}}>
              <div style={{...heavy, fontSize: 28, color: i === 0 ? T.redBright : '#7fd4c9'}}>{side.head}</div>
              <div style={{fontSize: 28, color: '#eae5df', marginTop: 6}}>{side.body}</div>
            </div>
          ) : null)}
        </div>
      ) : null}
    </div>
  );
};

const PortraitBigText: React.FC<{label?: string; main?: string; sub?: string}> = ({label, main, sub}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [0, 12], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', opacity: o, padding: '0 110px'}}>
      {label ? <div style={{...heavy, fontSize: 30, color: T.redBright, marginBottom: 22, letterSpacing: 2}}>{label}</div> : null}
      {main ? <div style={{...heavy, fontSize: 108, color: T.white, textAlign: 'center', lineHeight: 1.1,
        textShadow: '0 4px 22px rgba(0,0,0,0.7)'}}>{main}</div> : null}
      {sub ? <div style={{fontSize: 34, color: '#e6e1db', marginTop: 22, textAlign: 'center'}}>{sub}</div> : null}
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
        <AbsoluteFill style={{background:
          'linear-gradient(180deg, rgba(0,0,0,0.68) 0%, rgba(0,0,0,0.12) 30%, rgba(0,0,0,0.18) 56%, rgba(0,0,0,0.82) 100%)'}} />
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
      <div style={{fontSize: fitSize('资料来源：' + sources.join(' ｜ '), 24, 980), color: 'rgba(230,225,219,0.72)',
        marginBottom: 10, whiteSpace: 'nowrap', textShadow: '0 2px 8px rgba(0,0,0,0.8)'}}>
        资料来源：{sources.join(' ｜ ')}
      </div>
    ) : null}
    {disclaimer ? (
      <div style={{fontSize: fitSize(disclaimer, 24, 980), color: 'rgba(230,225,219,0.6)',
        whiteSpace: 'nowrap', textShadow: '0 2px 8px rgba(0,0,0,0.8)'}}>{disclaimer}</div>
    ) : null}
  </div>
);

const PortraitVideo: React.FC<NiwoProps> = (props) => (
  <AbsoluteFill style={{background: '#0e0c0b', fontFamily: T.font}}>
    <FontFace />
    {props.shots.map((shot, i) => (
      <PortraitShot key={i} shot={shot} index={i} />
    ))}
    <PortraitHeadline lines={props.headline.lines} />
    {props.showSubtitles !== false ? <PortraitSubtitles clauses={props.clauses} /> : null}
    <PortraitFooter sources={props.sources} disclaimer={props.disclaimer} />
  </AbsoluteFill>
);

// ---------------- root video ----------------
export const NiwoVideo: React.FC<NiwoProps> = (props) => {
  // 风格包：不同形态不同默认色系 + 动效强度
  const PACK_DEFAULTS: Record<string, [string, string]> = {
    data: ["#3a5a8c", "#5b82bb"],
    profile: ["#a44231", "#c96b5a"],
    investigation: ["#2e6f6a", "#4d9c96"],
    opinion: ["#a44231", "#d4623f"],
  };
  const pack = props.stylePack || "";
  if (!props.accent && PACK_DEFAULTS[pack]) {
    T.red = PACK_DEFAULTS[pack][0];
    T.redBright = PACK_DEFAULTS[pack][1];
  }
  if (props.accent) T.red = props.accent;
  if (props.accentSoft) T.redBright = props.accentSoft;
  // 动效强度：data/opinion 快节奏（入场 5 帧），profile/investigation 稳重（9 帧）
  (globalThis as any).__motionFrames = (pack === "data" || pack === "opinion") ? 5 : 9;
  if ((props.template || 'editorial') === 'portrait') {
    return <PortraitVideo {...props} />;
  }
  return (
    <AbsoluteFill style={{background: T.bgTop, fontFamily: T.font}}>
      <FontFace />
      <Background />
      {/* paper card */}
      <div
        style={{
          position: 'absolute',
          left: 91,
          top: 124,
          width: 892,
          height: 1432,
          borderRadius: 26,
          background: `linear-gradient(160deg, #e8e6e5 0%, ${T.paper} 55%, #dcd9d6 100%)`,
          boxShadow: '0 10px 30px rgba(0,0,0,0.55)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage:
              "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='p'><feTurbulence type='fractalNoise' baseFrequency='0.15' numOctaves='2'/><feColorMatrix type='matrix' values='0 0 0 0 0.45 0 0 0 0 0.44 0 0 0 0 0.42 0 0 0 0.045 0'/></filter><rect width='160' height='160' filter='url(%23p)'/></svg>\")",
          }}
        />
      </div>
      <HeadlineBand lines={props.headline.lines} />
      {/* dark inner panel */}
      <div
        style={{
          position: 'absolute',
          left: 115,
          top: 596,
          width: 849,
          height: 844,
          borderRadius: 16,
          background: T.panel,
        }}
      />
      {props.shots.map((shot, i) => (
        <ShotView key={i} shot={shot} index={i} />
      ))}
      {props.showSubtitles !== false ? <Subtitles clauses={props.clauses} /> : null}
      <Footer sources={props.sources} disclaimer={props.disclaimer} />
    </AbsoluteFill>
  );
};


// ---------------- v11 new card templates (from demo research) ----------------

const StatCard: React.FC<{spec: any}> = ({spec}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [4, 14], [0, 1], {extrapolateRight: 'clamp'});
  const numO = interpolate(f, [12, 24], [0, 1], {extrapolateRight: 'clamp'});
  const numY = interpolate(f, [12, 24], [24, 0], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0, background: 'rgba(14,11,9,0.5)'}}>
      {spec.year ? (
        <div style={{position: 'absolute', top: 26, right: 28, background: T.accent, color: '#f7f2ec',
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
      <div style={{position: 'absolute', left: 42, top: 236, fontSize: 26, color: '#c9c3bc', opacity: numO}}>
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
    <div style={{position: 'absolute', inset: 0, background: 'rgba(16,12,9,0.55)'}}>
      <div style={{position: 'absolute', left: 30, top: 30, display: 'flex', alignItems: 'center'}}>
        <span style={Tick} />
        <span style={{...heavy, fontSize: 28, color: T.accentSoft}}>{spec.label}</span>
      </div>
      <div style={{position: 'absolute', left: 30, top: 150, opacity: srcO}}>
        <div style={{...heavy, fontSize: 40, color: T.white, background: 'rgba(120,40,20,0.75)',
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
            <div style={{background: 'rgba(120,40,20,0.85)', color: T.white, ...heavy,
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
                   transform: `translateX(${cardX * -0.4}px)`, background: '#eef4f8', borderRadius: 12,
                   padding: '22px 28px'}}>
        <div style={{...heavy, fontSize: 30, color: '#101820'}}>{spec.name}</div>
        <div style={{fontSize: 24, color: '#3c4650', marginTop: 10, lineHeight: 1.45}}>{spec.caption}</div>
      </div>
    </div>
  );
};

const Timeline3: React.FC<{spec: any}> = ({spec}) => {
  const f = useCurrentFrame();
  const cols = spec.cols ?? [];
  return (
    <div style={{position: 'absolute', inset: 0, background: 'rgba(16,12,9,0.55)'}}>
      <div style={{position: 'absolute', left: 36, top: 30, ...heavy, fontSize: 48, color: T.white}}>
        {spec.title}
      </div>
      {spec.subtitle ? (
        <div style={{position: 'absolute', left: 38, top: 104, fontSize: 26, color: '#b7b1aa'}}>{spec.subtitle}</div>
      ) : null}
      <div style={{position: 'absolute', left: 30, right: 30, top: 180, display: 'flex', gap: 18}}>
        {cols.map((col: any, i: number) => {
          const o = interpolate(f, [16 + i * 10, 28 + i * 10], [0, 1], {extrapolateRight: 'clamp', extrapolateLeft: 'clamp'});
          return (
            <div key={i} style={{flex: 1, background: 'rgba(40,30,14,0.85)', borderRadius: 10,
                                 border: `2px solid ${T.accent}66`, opacity: o, padding: '16px 18px'}}>
              <div style={{display: 'inline-block', background: T.accent, color: '#f7f2ec', fontSize: 22,
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
