#!/usr/bin/env python3
"""v11: theme system + 4 new card templates in NiwoVideo.tsx"""
p = r'E:/短视频生成/videogen/renderer/src/NiwoVideo.tsx'
s = open(p, encoding='utf-8').read()

# 1. theme on props
a1 = '''export type NiwoProps = {
  durationInFrames: number;'''
s = s.replace(a1, '''export type NiwoProps = {
  durationInFrames: number;
  accent?: string;
  accentSoft?: string;''')

# 2. mutable accent tokens + apply from props
a2 = '''export const T = {
  bgTop: '#1c1a18','''
s = s.replace(a2, '''export const T = {
  accent: '#a44231',
  accentSoft: '#c14f35',
  bgTop: '#1c1a18',''')

a3 = '''export const NiwoVideo: React.FC<NiwoProps> = (props) => {
  return (
    <AbsoluteFill style={{background: T.bgTop, fontFamily: T.font}}>'''
s = s.replace(a3, '''export const NiwoVideo: React.FC<NiwoProps> = (props) => {
  if (props.accent) T.red = props.accent;
  if (props.accentSoft) T.redBright = props.accentSoft;
  return (
    <AbsoluteFill style={{background: T.bgTop, fontFamily: T.font}}>''')

# 3. theme the existing card accents (T.red/T.redBright used inside overlays)
s = s.replace("background: T.red,", "background: T.accent,")
s = s.replace("background: T.redB,", "background: T.accentSoft,")
s = s.replace("color: T.redBright", "color: T.accentSoft")
s = s.replace("background: RED,", "background: T.accent,")
s = s.replace("border: `2px solid ${T.red}`", "border: `2px solid ${T.accentSoft}`")

# 4. new overlay components (from demo research: statcard/branches/person/timeline)
s += '''

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
'''
open(p, 'w', encoding='utf-8').write(s)
print("templates added")
