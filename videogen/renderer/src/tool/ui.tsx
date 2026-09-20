import React from 'react';

/** 成片台一套记号：账号相关页面（登录/权益/设置）与主流程共用，避免两处各画一套 */
export const C = {
  ink: '#1a1817', soft: '#6f6a63', line: '#e5e2dc', paper: '#f7f6f3',
  card: '#ffffff', accent: '#5b21b6', accentSoft: '#ede9f7', ok: '#166534',
  okSoft: '#e8f2ea', err: '#a44231', errSoft: '#f7eae7', gold: '#8a6d1f',
};

export const btn: React.CSSProperties = {
  all: 'unset', cursor: 'pointer', display: 'block', textAlign: 'center',
  background: C.accent, color: '#fff', padding: '13px 26px', borderRadius: 10,
  fontSize: 16, fontWeight: 700,
  // 内联样式没有全局 reset：不设 border-box，width:100% + padding 会撑破容器
  boxSizing: 'border-box',
};
export const btnLine: React.CSSProperties = {
  ...btn, background: 'transparent', color: C.accent,
  border: `1px solid ${C.accent}`, padding: '9px 18px', fontSize: 14, fontWeight: 600,
};
export const btnSm: React.CSSProperties = {...btn, padding: '8px 14px', fontSize: 13.5};
export const btnSmLine: React.CSSProperties = {
  ...btnLine, padding: '8px 14px', fontSize: 13.5, background: '#fff',
};
export const sel: React.CSSProperties = {
  width: '100%', padding: '9px 10px', borderRadius: 8, border: `1px solid ${C.line}`,
  background: '#fff', color: C.ink, fontSize: 14, fontFamily: 'inherit',
  boxSizing: 'border-box',
};
export const inp: React.CSSProperties = {
  ...sel, lineHeight: 1.4,
};

export const api = async (u: string, o?: RequestInit) => {
  const r = await fetch(u, {credentials: 'same-origin', ...o});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((d && (d.error as string)) || `HTTP ${r.status}`);
  return d as Record<string, unknown>;
};

/** 一行一项的小开关 */
export const Toggle: React.FC<{label: string; on: boolean; set: (v: boolean) => void}> =
  ({label, on, set}) => (
    <button onClick={() => set(!on)} style={{
      all: 'unset', cursor: 'pointer', display: 'flex', alignItems: 'center',
      gap: 8, fontSize: 13.5, color: C.ink,
    }}>
      <span style={{
        width: 30, height: 17, borderRadius: 9, position: 'relative', flexShrink: 0,
        background: on ? C.accent : '#d8d4cd', transition: 'background .15s',
      }}>
        <span style={{
          position: 'absolute', top: 2, left: on ? 15 : 2, width: 13, height: 13,
          borderRadius: '50%', background: '#fff', transition: 'left .15s',
        }} />
      </span>
      {label}
    </button>
  );

/** 浮层：整页遮罩 + 居中卡片，Esc / 点背景都能关 */
export const Sheet: React.FC<{title: string; sub?: string; width?: number;
                              onClose: () => void; children: React.ReactNode;
                              footer?: React.ReactNode}> =
  ({title, sub, width = 460, onClose, children, footer}) => {
    React.useEffect(() => {
      const k = (e: KeyboardEvent) => {
        if (e.key === 'Escape') onClose();
      };
      document.addEventListener('keydown', k);
      return () => document.removeEventListener('keydown', k);
    }, [onClose]);
    return (
      <div onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
           style={{position: 'fixed', inset: 0, zIndex: 40, background: 'rgba(26,24,23,.42)',
                   display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20}}>
        <div role="dialog" aria-modal="true" aria-label={title} style={{
          width, maxWidth: '100%', maxHeight: '92vh', display: 'flex', flexDirection: 'column',
          background: C.card, borderRadius: 16, boxShadow: '0 24px 70px rgba(0,0,0,.28)',
        }}>
          <div style={{padding: '22px 26px 0', display: 'flex', gap: 14, alignItems: 'flex-start'}}>
            <div style={{flex: 1, minWidth: 0}}>
              <div style={{fontSize: 19, fontWeight: 800, color: C.ink}}>{title}</div>
              {sub ? <div style={{fontSize: 13.5, color: C.soft, marginTop: 5, lineHeight: 1.7}}>{sub}</div> : null}
            </div>
            <button onClick={onClose} aria-label="关闭" style={{
              all: 'unset', cursor: 'pointer', fontSize: 19, lineHeight: 1, color: C.soft,
              padding: 6, borderRadius: 8,
            }}>×</button>
          </div>
          <div style={{padding: '18px 26px 22px', overflowY: 'auto'}}>
            {children}
            {footer}
          </div>
        </div>
      </div>
    );
  };

/** 档位徽标：免费版灰、付费版金 */
export const TierChip: React.FC<{tier: string; label: string}> = ({tier, label}) => (
  <span style={{
    fontSize: 11.5, fontWeight: 700, padding: '2px 8px', borderRadius: 20, whiteSpace: 'nowrap',
    background: tier === 'free' ? C.paper : '#fbf3dd', color: tier === 'free' ? C.soft : C.gold,
    border: `1px solid ${tier === 'free' ? C.line : '#e6d3a3'}`,
  }}>{label}</span>
);

export const Field: React.FC<{label: string; children: React.ReactNode; hint?: string}> =
  ({label, children, hint}) => (
    <div style={{marginBottom: 13}}>
      <div style={{fontSize: 13, color: C.soft, marginBottom: 5}}>{label}</div>
      {children}
      {hint ? <div style={{fontSize: 12.5, color: C.soft, marginTop: 5}}>{hint}</div> : null}
    </div>
  );

/** 就地反馈条（登录/兑换/保存）：不弹窗，写在按钮上方 */
export const Msg: React.FC<{t: string; k: 'err' | 'ok' | 'info'}> = ({t, k}) =>
  t ? (
    <div style={{
      fontSize: 13, lineHeight: 1.6, marginBottom: 12, padding: '9px 11px', borderRadius: 8,
      color: k === 'err' ? C.err : k === 'ok' ? C.ok : C.ink,
      background: k === 'err' ? C.errSoft : k === 'ok' ? C.okSoft : C.paper,
    }}>{t}</div>
  ) : null;

/** 文字链：不用按钮壳 */
export const lnk: React.CSSProperties = {
  all: 'unset', cursor: 'pointer', color: C.soft, fontSize: 13.5,
};
export const lnkAcc: React.CSSProperties = {...lnk, color: C.accent, fontWeight: 650};
