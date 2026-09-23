import React from 'react';
import {
  C, btn, btnLine, btnSm, btnSmLine, inp, api, lnk, lnkAcc, Sheet, TierChip, Field, Msg,
} from './ui';
import {BrandSheet} from './brand';

export interface Me {
  email: string; tier: string; tier_label: string; is_admin: boolean;
  nickname: string; avatar: string; created: string; avatars: string[];
  builds_today?: number; free_daily_builds?: number;
}
export interface AuthSt { smtp: boolean; dev_email: boolean; token_auth: boolean; locked: boolean;
  /** 服务端说了算：本机开放模式下不登录也能领单 */
  open: boolean }
export type SheetName = '' | 'auth' | 'pricing' | 'settings' | 'contact' | 'brand';


/* ───────────────────────── 登录 / 注册 / 重设密码 ───────────────────────── */

const AuthSheet: React.FC<{
  authst: AuthSt; mode0: 'login' | 'register'; note?: string; onClose: () => void;
  onSignedIn: () => void;
}> = ({authst, mode0, note, onClose, onSignedIn}) => {
  const [mode, setMode] = React.useState<'login' | 'register' | 'reset'>(mode0);
  const [msg, setMsg] = React.useState<{t: string; k: 'err' | 'ok'}>({t: '', k: 'err'});
  const [busy, setBusy] = React.useState(false);
  const [cooldown, setCooldown] = React.useState(0);
  const [f, setF] = React.useState({
    email: '', code: '', pass: '', pass2: '', liEmail: '', liPass: '', remember: true,
  });
  const canRegister = authst.smtp || authst.dev_email;
  const err = (t: string) => setMsg({t, k: 'err'});
  const ok = (t: string) => setMsg({t, k: 'ok'});
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setF({...f, [k]: v} as typeof f);
  };

  React.useEffect(() => {
    if (!cooldown) return;
    const t = setTimeout(() => setCooldown((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);
  React.useEffect(() => { setMsg({t: '', k: 'err'}); }, [mode]);
  // 面板已经开着时再点顶栏「登录/注册」，要切到对方那一档
  React.useEffect(() => { setMode(mode0); }, [mode0]);

  const sendCode = async (endpoint: string, field: 'email' | 'liEmail') => {
    const email = f[field].trim();
    if (!email) return err('请先输入邮箱');
    setBusy(true);
    try {
      const r = await api(endpoint, {method: 'POST', headers: {'content-type': 'application/json'},
        body: JSON.stringify({email})});
      ok(String(r.message || '验证码已发送'));
      setCooldown(60);
    } catch (e) {
      err(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const run = async (url: string, body: Record<string, unknown>) => {
    setBusy(true);
    try {
      await api(url, {method: 'POST', headers: {'content-type': 'application/json'},
        body: JSON.stringify(body)});
      onSignedIn();
    } catch (e) {
      err(String((e as Error).message));
      setBusy(false);
    }
  };

  const register = () => {
    const email = f.email.trim();
    if (!email) return err('请输入邮箱');
    if (!/^\d{6}$/.test(f.code.trim())) return err('请输入 6 位验证码');
    if (f.pass.length < 8) return err('密码至少 8 位');
    if (f.pass !== f.pass2) return err('两次输入的密码不一样');
    void run('/api/auth/register',
      {email, code: f.code.trim(), password: f.pass, remember: true});
  };
  const reset = () => {
    const email = f.email.trim();
    if (!email) return err('请输入注册时用的邮箱');
    if (!/^\d{6}$/.test(f.code.trim())) return err('请输入 6 位验证码');
    if (f.pass.length < 8) return err('密码至少 8 位');
    if (f.pass !== f.pass2) return err('两次输入的密码不一样');
    void run('/api/auth/reset',
      {email, code: f.code.trim(), password: f.pass, remember: true});
  };
  const login = () => {
    if (!f.liEmail.trim()) return err('请输入邮箱');
    if (!f.liPass) return err('请输入密码');
    void run('/api/auth/login',
      {email: f.liEmail.trim(), password: f.liPass, remember: f.remember});
  };

  const codeBtn = (endpoint: string, field: 'email' | 'liEmail') => (
    <button style={{...btnSmLine, whiteSpace: 'nowrap', opacity: busy || cooldown ? 0.6 : 1}}
            disabled={busy || cooldown > 0} onClick={() => void sendCode(endpoint, field)}>
      {cooldown > 0 ? `${cooldown} 秒后重发` : '获取验证码'}
    </button>
  );
  const tab = (m: 'register' | 'login', label: string) => (
    <button onClick={() => setMode(m)} style={{
      all: 'unset', cursor: 'pointer', textAlign: 'center', flex: 1, padding: '9px 0',
      borderRadius: 8, fontSize: 14.5, fontWeight: 700,
      background: mode === m ? C.accent : 'transparent', color: mode === m ? C.onAcc : C.soft,
    }}>{label}</button>
  );

  return (
    <Sheet title={mode === 'register' ? '注册 GetCut' : mode === 'reset' ? '重设密码' : '欢迎回来'}
           sub={mode === 'register' ? '把一篇文案变成能发的竖屏短片'
             : mode === 'reset' ? '邮箱验证码验证是你本人，然后设个新密码'
             : '登录后继续做你的片子'}
           onClose={onClose}>
      <Msg {...msg} />
      {note ? (
        <div style={{fontSize: 13, color: C.soft, background: C.paper, borderRadius: 8,
                     padding: '9px 11px', marginBottom: 12, lineHeight: 1.6}}>{note}</div>
      ) : null}
      {mode !== 'reset' ? (
        <div style={{display: 'flex', gap: 6, padding: 4, background: C.paper,
                     borderRadius: 10, marginBottom: 16}}>
          {tab('register', '注册')}
          {tab('login', '登录')}
        </div>
      ) : null}

      {mode === 'login' ? (
        <>
          <Field label="邮箱">
            <input style={inp} type="email" placeholder="you@example.com"
                   autoComplete="username" value={f.liEmail} onChange={set('liEmail')} />
          </Field>
          <Field label="密码">
            <input style={inp} type="password" placeholder="密码" autoComplete="current-password"
                   value={f.liPass} onChange={set('liPass')}
                   onKeyDown={(e) => { if (e.key === 'Enter') login(); }} />
          </Field>
          <label style={{display: 'flex', gap: 7, alignItems: 'center', fontSize: 13.5,
                         color: C.soft, marginBottom: 16, cursor: 'pointer'}}>
            <input type="checkbox" checked={f.remember} onChange={set('remember')} />
            记住我，30 天内免登录
          </label>
          <button style={{...btn, width: '100%', opacity: busy ? 0.7 : 1}} disabled={busy}
                  onClick={login}>{busy ? '登录中…' : '登录'}</button>
          <button style={{...lnk, display: 'block', marginTop: 12}}
                  onClick={() => setMode('reset')}>忘记密码？</button>
        </>
      ) : !canRegister ? (
        <>
          <div style={{fontSize: 13.5, color: C.soft, lineHeight: 1.8}}>
            {mode === 'register'
              ? '注册功能需要先在服务器配置发信邮箱（SMTP）。配置好之后，这里就是「输邮箱 → 收验证码 → 设密码」。'
              : '重设密码需要服务器配置发信邮箱（SMTP），否则收不到验证码。请联系管理员。'}
          </div>
          <button style={{...btnLine, width: '100%', marginTop: 14}}
                  onClick={() => setMode('login')}>我有账号，去登录</button>
        </>
      ) : (
        <>
          <Field label="邮箱">
            <div style={{display: 'grid', gridTemplateColumns: '1fr auto', gap: 8}}>
              <input style={inp} type="email" placeholder="you@example.com" autoComplete="username"
                     value={f.email} onChange={set('email')} />
              {codeBtn(mode === 'reset' ? '/api/auth/reset-code' : '/api/auth/send-code', 'email')}
            </div>
          </Field>
          <Field label="验证码">
            <input style={inp} type="text" placeholder="6 位数字" maxLength={6} inputMode="numeric"
                   value={f.code} onChange={set('code')} />
          </Field>
          <Field label={mode === 'reset' ? '新密码' : '设置密码'}>
            <input style={inp} type="password" placeholder="至少 8 位" autoComplete="new-password"
                   value={f.pass} onChange={set('pass')} />
          </Field>
          <Field label="确认密码">
            <input style={inp} type="password" autoComplete="new-password" value={f.pass2}
                   onChange={set('pass2')}
                   onKeyDown={(e) => { if (e.key === 'Enter') (mode === 'reset' ? reset : register)(); }} />
          </Field>
          <button style={{...btn, width: '100%', opacity: busy ? 0.7 : 1}} disabled={busy}
                  onClick={mode === 'reset' ? reset : register}>
            {busy ? '提交中…' : mode === 'reset' ? '重设密码并进入' : '注册并进入'}
          </button>
          {mode === 'reset' ? (
            <button style={{...lnk, display: 'block', marginTop: 12}}
                    onClick={() => setMode('login')}>返回登录</button>
          ) : null}
          {authst.dev_email ? (
            <div style={{fontSize: 12.5, color: C.soft, marginTop: 12}}>
              （本机开发模式：验证码会直接显示在提示里）
            </div>
          ) : null}
        </>
      )}
    </Sheet>
  );
};

/* ───────────────────────── 账号设置 ───────────────────────── */

const SettingsSheet: React.FC<{me: Me; onClose: () => void; onChanged: (m: Me) => void;
                               onSignedOut: () => void}> = ({me, onClose, onChanged, onSignedOut}) => {
  const avs = me.avatars;
  const [avatar, setAvatar] = React.useState(me.avatar || avs[0]);
  const [nick, setNick] = React.useState(me.nickname || '');
  const [msg, setMsg] = React.useState<{t: string; k: 'err' | 'ok'}>({t: '', k: 'err'});
  const [pw, setPw] = React.useState({old: '', neu: ''});
  const [pwMsg, setPwMsg] = React.useState<{t: string; k: 'err' | 'ok'}>({t: '', k: 'err'});
  const [busy, setBusy] = React.useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const r = await api('/api/me', {method: 'PUT', headers: {'content-type': 'application/json'},
        body: JSON.stringify({nickname: nick, avatar})});
      onChanged({...me, nickname: String(r.nickname), avatar: String(r.avatar)});
      setMsg({t: '资料已保存。', k: 'ok'});
    } catch (e) {
      setMsg({t: String((e as Error).message), k: 'err'});
    } finally {
      setBusy(false);
    }
  };
  const chgPw = async () => {
    setPwMsg({t: '', k: 'err'});
    try {
      await api('/api/auth/change-password', {method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({old_password: pw.old, new_password: pw.neu})});
      setPwMsg({t: '密码已更新，下次登录用新密码。', k: 'ok'});
      setPw({old: '', neu: ''});
    } catch (e) {
      setPwMsg({t: String((e as Error).message), k: 'err'});
    }
  };

  const row = (k: string, v: string) => (
    <div style={{display: 'flex', justifyContent: 'space-between', gap: 12,
                 padding: '8px 0', borderTop: `1px solid ${C.line}`, fontSize: 13.5}}>
      <span style={{color: C.soft}}>{k}</span>
      <b style={{color: C.ink, fontWeight: 600, textAlign: 'right', wordBreak: 'break-all'}}>{v}</b>
    </div>
  );

  return (
    <Sheet title="账号设置" sub="换个头像和名字，出片报告里认得出是你。" width={480} onClose={onClose}>
      <div style={{textAlign: 'center', fontSize: 40, marginBottom: 8}} aria-hidden>{avatar}</div>
      <div style={{display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center', marginBottom: 18}}>
        {avs.map((a) => (
          <button key={a} type="button" aria-pressed={a === avatar} title="选这个头像"
                  onClick={() => setAvatar(a)} style={{
            all: 'unset', cursor: 'pointer', fontSize: 19, width: 38, height: 38, borderRadius: 10,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: a === avatar ? C.accentSoft : C.paper,
            border: `1px solid ${a === avatar ? C.accent : C.line}`,
          }}>{a}</button>
        ))}
      </div>
      <Field label="昵称">
        <input style={inp} maxLength={16} value={nick} placeholder="最多 16 个字"
               onChange={(e) => setNick(e.target.value)} />
        <div style={{fontSize: 12, color: C.soft, textAlign: 'right', marginTop: 4}}>{nick.length}/16</div>
      </Field>
      <Msg {...msg} />
      <div style={{display: 'flex', gap: 8, justifyContent: 'flex-end', marginBottom: 22}}>
        <button style={{...btnLine, background: 'transparent'}} onClick={() => void save()}
                disabled={busy}>{busy ? '保存中…' : '保存资料'}</button>
      </div>

      <div style={{fontSize: 14, fontWeight: 700, marginBottom: 2}}>账号信息</div>
      {row('登录邮箱', me.email)}
      {row('当前档位', `${me.tier_label || '免费版'}${me.tier !== 'free' ? ' · 永久有效' : ''}`)}
      {me.created ? row('注册时间', me.created) : null}
      {typeof me.free_daily_builds === 'number'
        ? row('今日免费额度', `已用 ${me.builds_today || 0} / ${me.free_daily_builds} 条`) : null}

      <div style={{fontSize: 14, fontWeight: 700, margin: '22px 0 10px'}}>修改密码</div>
      <input style={{...inp, marginBottom: 8}} type="password" placeholder="当前密码"
             autoComplete="current-password" value={pw.old}
             onChange={(e) => setPw({...pw, old: e.target.value})} />
      <input style={inp} type="password" placeholder="新密码（至少 8 位）" autoComplete="new-password"
             value={pw.neu} onChange={(e) => setPw({...pw, neu: e.target.value})} />
      <Msg {...pwMsg} />
      <button style={btnSmLine} onClick={() => void chgPw()}>更新密码</button>

      <div style={{marginTop: 26, paddingTop: 16, borderTop: `1px solid ${C.line}`}}>
        <button style={{...btnLine, color: C.err, borderColor: C.err, background: 'transparent'}}
                onClick={onSignedOut}>退出登录</button>
      </div>
    </Sheet>
  );
};

/* ───────────────────────── 联系创始人 ───────────────────────── */

const ContactSheet: React.FC<{onClose: () => void; toast: (m: string) => void}> =
  ({onClose, toast}) => {
    const [wx, setWx] = React.useState('');
    React.useEffect(() => {
      api('/api/pricing')
        .then((d) => setWx(String((d as { wechat_id?: string }).wechat_id || '')))
        .catch(() => {});
    }, []);
    return (
      <Sheet title="联系创始人" sub="付款开通、卡密有问题、想提功能建议，直接加微信，都在。"
             width={400} onClose={onClose}>
        {wx ? (
          <div style={{display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px',
                       background: C.paper, borderRadius: 10}}>
            <span style={{fontSize: 12.5, color: C.soft}}>微信号</span>
            <b style={{flex: 1, fontSize: 15, fontWeight: 700}}>{wx}</b>
            <button style={btnSm} onClick={() => {
              navigator.clipboard.writeText(wx)
                .then(() => toast('已复制，去微信粘贴就行'), () => toast('复制失败，手动记一下微信号'));
            }}>复制</button>
          </div>
        ) : <div style={{fontSize: 13.5, color: C.soft}}>微信号马上放上来，先在「权益与定价」页留意。</div>}
      </Sheet>
    );
  };

/* ───────────────────────── 权益与定价 ───────────────────────── */

interface Price {
  prices: {premium: number}; wechat_id: string; free_daily_builds: number;
  tier: string; email: string; is_admin: boolean;
}
interface Lic { code: string; tier: string; redeemed_by?: string; note?: string }

const PricingSheet: React.FC<{me: Me | null; onClose: () => void; refresh: () => void;
                             needAuth: () => void; toast: (m: string) => void}> =
  ({me, onClose, refresh, needAuth, toast}) => {
    const [p, setP] = React.useState<Price | null>(null);
    const [loadErr, setLoadErr] = React.useState('');
    const [code, setCode] = React.useState('');
    const [rMsg, setRMsg] = React.useState<{t: string; k: 'err' | 'ok'}>({t: '', k: 'err'});
    const [busy, setBusy] = React.useState(false);
    const [admin, setAdmin] = React.useState(false);
    const [gen, setGen] = React.useState<{n: string; note: string}>({n: '10', note: ''});
    const [genCodes, setGenCodes] = React.useState<string[]>([]);
    const [lics, setLics] = React.useState<Lic[]>([]);

    const load = React.useCallback(() => {
      api('/api/pricing').then((d) => {
        setP(d as unknown as Price);
        if ((d as unknown as Price).is_admin) {
          setAdmin(true);
          api('/api/admin/licenses')
            .then((r) => setLics(((r as { codes?: Lic[] }).codes) || []))
            .catch(() => {});
        }
      }).catch((e) => setLoadErr(String((e as Error).message)));
    }, []);
    React.useEffect(() => { load(); }, [load]);

    const tier = me?.tier || 'free';
    const premium = tier === 'premium';
    const nowLine = premium ? '高级版 · 永久有效，全部权益已解锁'
      : tier === 'basic' ? '基础版 · 永久有效，出片不限量、无水印'
      : `免费版 · 每天 ${p?.free_daily_builds ?? 2} 条免费额度，成片带 GetCut 水印`;
    const copyWx = () => {
      if (!p?.wechat_id) return;
      navigator.clipboard.writeText(p.wechat_id)
        .then(() => toast('微信号已复制，去微信添加就行'), () => {});
    };
    const redeem = async () => {
      const c = code.trim();
      if (!c) return;
      setBusy(true);
      setRMsg({t: '', k: 'err'});
      try {
        const r = await api('/api/license/redeem', {method: 'POST',
          headers: {'content-type': 'application/json'}, body: JSON.stringify({code: c})});
        setRMsg({t: String(r.message || '已生效'), k: 'ok'});
        setCode('');
        refresh();
        load();
      } catch (e) {
        setRMsg({t: String((e as Error).message), k: 'err'});
      } finally {
        setBusy(false);
      }
    };
    const genCodesGo = async () => {
      setBusy(true);
      try {
        const r = await api('/api/admin/licenses/gen', {method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify({tier: 'premium', count: gen.n, note: gen.note})});
        setGenCodes(((r as { codes?: string[] }).codes) || []);
        api('/api/admin/licenses')
          .then((x) => setLics(((x as { codes?: Lic[] }).codes) || []))
          .catch(() => {});
      } catch (e) {
        toast(String((e as Error).message));
      } finally {
        setBusy(false);
      }
    };

    const h2: React.CSSProperties = {fontSize: 16, fontWeight: 800, margin: '26px 0 4px'};
    const feat: React.CSSProperties = {
      fontSize: 13.5, lineHeight: 1.9, color: C.ink, paddingLeft: 18, position: 'relative',
    };

    if (loadErr) {
      return <Sheet title="权益页暂时打不开" onClose={onClose}><Msg t={loadErr} k="err" /></Sheet>;
    }
    return (
      <Sheet title="权益与定价" width={620} onClose={onClose}>
        {!p ? <div style={{fontSize: 13.5, color: C.soft}}>加载中…</div> : (
          <>
            <span style={{
              display: 'inline-block', fontSize: 12, fontWeight: 700, color: C.accent,
              background: C.accentSoft, borderRadius: 20, padding: '4px 12px',
            }}>买断制 · 不订阅 · 不涨价</span>
            <div style={{fontSize: 26, fontWeight: 800, lineHeight: 1.45, marginTop: 12}}>
              一次付费，<span style={{color: C.accent}}>永久是你的。</span>
            </div>
            <div style={{fontSize: 13.5, color: C.soft, lineHeight: 1.8, marginTop: 8}}>
              没有月费，没有按条收费。今天买断，之后出的每一条片，都不再花一分钱。
            </div>
            <div style={{fontSize: 13.5, color: C.soft, marginTop: 12}}>
              你现在的档位：<b style={{color: C.ink, fontWeight: 700}}>{nowLine}</b>
            </div>

            {/* 唯一一档：高级版 */}
            <div style={{
              marginTop: 18, border: `1.5px solid ${C.accent}`, borderRadius: 14,
              background: C.card, padding: '20px 22px', position: 'relative', overflow: 'hidden',
            }}>
              <span style={{
                position: 'absolute', top: 0, right: 0, fontSize: 11.5, fontWeight: 700,
                background: C.accent, color: C.onAcc, padding: '5px 12px',
                borderRadius: '0 12px 0 12px',
              }}>永久有效</span>
              <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
                <div style={{fontSize: 16, fontWeight: 800}}>高级版 · 唯一一档</div>
                {premium ? <TierChip tier="premium" label="你在这档" /> : null}
              </div>
              <div style={{display: 'flex', alignItems: 'baseline', gap: 4, marginTop: 10}}>
                <span style={{fontSize: 16, fontWeight: 700}}>¥</span>
                <span style={{fontSize: 40, fontWeight: 800, lineHeight: 1}}>{p.prices.premium}</span>
                <span style={{fontSize: 13, color: C.soft, marginLeft: 8}}>一次付费 · 永久有效</span>
              </div>
              <div style={{fontSize: 13.5, color: C.soft, marginTop: 6}}>
                把片子做成「你的」，一次买断，不再花一分钱。
              </div>
              <ul style={{margin: '14px 0 0', padding: 0, listStyle: 'none'}}>
                {[
                  ['出片不限量', '：拖素材包 → 自动分镜 → 成片，随便出'],
                  ['无 GetCut 水印', '：可换成自己的 Logo / 文字水印，随便发'],
                  ['全部模板、全部音色', '任选'],
                  ['我的声音', '：录一分钟，以后每条片都用你自己的声音配音'],
                  ['品牌套件', '：自有 Logo + 文字水印，每条片自动带上'],
                  ['剪映草稿导出', '：成片接着精剪，导进去就是分好镜的'],
                  ['优先出片', '：高峰期排在免费任务前面生成，不跟人挤'],
                ].map(([b, rest]) => (
                  <li key={b} style={feat}>
                    <span style={{
                      position: 'absolute', left: 0, color: C.accent, fontWeight: 800}}>✓</span>
                    <b>{b}</b>{rest}
                  </li>
                ))}
              </ul>
              <button style={{...btn, width: '100%', marginTop: 18, opacity: premium ? 0.55 : 1}}
                      disabled={premium} onClick={copyWx}>
                {premium ? '已开通 · 当前档位' : '加微信，开通高级版'}
              </button>
              <div style={{fontSize: 12.5, color: C.soft, marginTop: 8, textAlign: 'center'}}>
                付款由<b>创始人一对一对接</b>，转账后 5 分钟内发卡密
              </div>
            </div>
            <div style={{fontSize: 13, color: C.soft, marginTop: 14, lineHeight: 1.8}}>
              还在犹豫？每天 {p.free_daily_builds} 条免费额度，成片带 GetCut 水印——先看效果，再决定。
            </div>

            <div style={h2}>怎么开通</div>
            <div style={{fontSize: 13, color: C.soft}}>三步，五分钟。付款走微信，由创始人亲自对接。</div>
            <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))',
                         gap: 12, marginTop: 12}}>
              {[
                ['01', '加创始人微信', '复制微信号，去微信搜索添加。'],
                ['02', '微信转账', '说明要哪一档。有拿不准的，直接问，他本人回。'],
                ['03', '回来输卡密', '付款截图发过去，马上拿卡密。在下面一贴，立即生效。'],
              ].map(([no, b, t]) => (
                <div key={no} style={{border: `1px solid ${C.line}`, borderRadius: 12, padding: 14,
                                      background: C.paper}}>
                  <div style={{fontSize: 12, fontWeight: 800, color: C.accent}}>{no}</div>
                  <div style={{fontSize: 14, fontWeight: 700, marginTop: 4}}>{b}</div>
                  <div style={{fontSize: 12.5, color: C.soft, lineHeight: 1.7, marginTop: 4}}>{t}</div>
                </div>
              ))}
            </div>
            <div style={{display: 'flex', alignItems: 'center', gap: 12, marginTop: 12,
                         padding: '11px 14px', background: C.paper, borderRadius: 10}}>
              <span style={{fontSize: 12.5, color: C.soft}}>微信号</span>
              <b style={{flex: 1, fontSize: 15}}>{p.wechat_id || '即将公布'}</b>
              {p.wechat_id ? <button style={btnSmLine} onClick={copyWx}>复制</button> : null}
            </div>
            <div style={{fontSize: 12.5, color: C.soft, lineHeight: 1.9, marginTop: 12,
                         padding: '11px 14px', border: `1px dashed ${C.line}`, borderRadius: 10}}>
              <b style={{color: C.ink}}>为什么是人工收款？</b>走自动支付要过支付通道、被抽手续费，
              这笔钱最后还是摊进定价。现在由创始人一对一收款发货——付款后有任何问题，你找得到人，
              不用跟机器人客服绕圈子。
            </div>

            <div style={h2}>卡密兑换</div>
            <div style={{fontSize: 13, color: C.soft, marginBottom: 10}}>
              拿到卡密后在这里输入，立即生效，不用等。
            </div>
            {me ? (
              <>
                <div style={{display: 'grid', gridTemplateColumns: '1fr auto', gap: 8}}>
                  <input style={inp} placeholder="GCP-XXXX-XXXX" autoComplete="off"
                         value={code} onChange={(e) => setCode(e.target.value)}
                         onKeyDown={(e) => { if (e.key === 'Enter') void redeem(); }} />
                  <button style={{...btn, opacity: busy ? 0.7 : 1}} disabled={busy}
                          onClick={() => void redeem()}>{busy ? '兑换中…' : '兑换'}</button>
                </div>
                <Msg {...rMsg} />
              </>
            ) : (
              <div style={{fontSize: 13.5, color: C.soft}}>
                先<button style={lnkAcc} onClick={needAuth}>登录/注册</button>，再回来输卡密。
              </div>
            )}

            {admin ? (
              <>
                <div style={h2}>站长面板（只有你能看到）</div>
                <div style={{display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center',
                             marginTop: 10}}>
                  <input style={{...inp, width: 90}} type="number" min={1} max={200} value={gen.n}
                         title="一次生成几张卡密"
                         onChange={(e) => setGen({...gen, n: e.target.value})} />
                  <input style={{...inp, flex: 1, minWidth: 150}} placeholder="备注（如 9.20 直播场）"
                         value={gen.note} onChange={(e) => setGen({...gen, note: e.target.value})} />
                  <button style={{...btnSm, opacity: busy ? 0.7 : 1}} disabled={busy}
                          onClick={() => void genCodesGo()}>生成卡密</button>
                </div>
                {genCodes.length ? (
                  <div style={{marginTop: 10}}>
                    <div style={{
                      fontFamily: 'ui-monospace, Consolas, monospace', fontSize: 13, lineHeight: 1.8,
                      background: C.paper, borderRadius: 10, padding: '10px 12px',
                      whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                    }}>{genCodes.join('\n')}</div>
                    <div style={{display: 'flex', gap: 10, alignItems: 'center', marginTop: 8}}>
                      <button style={btnSmLine} onClick={() => {
                        navigator.clipboard.writeText(genCodes.join('\n'))
                          .then(() => toast('已复制'), () => toast('复制失败，手动选中复制吧'));
                      }}>复制全部（{genCodes.length} 张）</button>
                      <span style={{fontSize: 12.5, color: C.soft}}>明文只显示这一次，复制走再关</span>
                    </div>
                  </div>
                ) : null}
                <div style={{marginTop: 12, maxHeight: 190, overflowY: 'auto',
                             border: `1px solid ${C.line}`, borderRadius: 10}}>
                  {lics.length ? lics.map((c) => (
                    <div key={c.code} style={{
                      display: 'flex', gap: 10, justifyContent: 'space-between', fontSize: 12.5,
                      padding: '7px 12px', borderTop: `1px solid ${C.line}`,
                    }}>
                      <span style={{fontFamily: 'ui-monospace, Consolas, monospace'}}>{c.code}</span>
                      <span style={{color: C.soft}}>
                        {c.tier === 'premium' ? '高级' : '基础'} ·{' '}
                        {c.redeemed_by ? `已兑换 ${c.redeemed_by}` : '未兑换'}
                        {c.note ? ` · ${c.note}` : ''}
                      </span>
                    </div>
                  )) : <div style={{padding: 12, fontSize: 13, color: C.soft}}>还没生成过卡密</div>}
                </div>
              </>
            ) : null}
          </>
        )}
      </Sheet>
    );
  };

/* ───────────────────────── 顶栏账号入口 ───────────────────────── */

export const Account: React.FC<{
  me: Me | null; authst: AuthSt; sheet: SheetName; setSheet: (s: SheetName) => void;
  refresh: () => Promise<unknown>; onMe: (m: Me | null) => void; onSignedIn: () => void;
  authNote?: string; onBrandChanged: () => void;
  toast: (m: string) => void;
}> = ({me, authst, sheet, setSheet, refresh, onMe, onSignedIn, authNote, onBrandChanged, toast}) => {
  const [menu, setMenu] = React.useState(false);
  // 顶栏两个按钮各自开各自的一档；被导入拦下来时按服务器状态给默认档
  const [authMode0, setAuthMode0] = React.useState<'login' | 'register'>(
    authst.locked ? 'login' : 'register');
  React.useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(false);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [menu]);
  const signOut = async () => {
    setMenu(false);
    try {
      await api('/api/auth/logout', {method: 'POST'});
    } catch (_) {}
    onMe(null);
    setSheet('');
    toast('已退出登录');
  };
  const item: React.CSSProperties = {
    all: 'unset', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 9, width: '100%',
    padding: '9px 12px', borderRadius: 8, fontSize: 13.5, color: C.ink, boxSizing: 'border-box',
  };
  // 菜单图标列：固定宽 + 同字号，字符再花文字也不歪（用户反馈：💬 大图标把文字顶歪了）
  const mi: React.CSSProperties = {
    fontStyle: 'normal', width: 20, textAlign: 'center', fontSize: 12.5,
    flex: 'none', lineHeight: 1,
  };
  const tier = me?.tier || 'free';
  // 本机开放模式（这台服务器一个账号都没建）：不摆账号入口，别给自用人添噪
  if (!me && !authst.locked && !authst.token_auth && !sheet) return null;

  return (
    <div style={{position: 'relative', display: 'flex', gap: 8, alignItems: 'center',
                 justifyContent: 'flex-end'}}>
      {me ? (
        <button onClick={(e) => { e.stopPropagation(); setMenu(!menu); }} aria-haspopup="menu"
                aria-expanded={menu} title="账号与权益" style={{
          all: 'unset', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 7,
          padding: '5px 10px 5px 6px', borderRadius: 22, background: menu ? C.accentSoft : C.paper,
          border: `1px solid ${menu ? C.accent : C.line}`,
        }}>
          <span style={{fontSize: 16}} aria-hidden>{me.avatar || '🦊'}</span>
          <span style={{fontSize: 13.5, fontWeight: 700, maxWidth: 96, overflow: 'hidden',
                        textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
            {me.nickname || '创作者'}
          </span>
          <TierChip tier={tier} label={me.tier_label || '免费版'} />
        </button>
      ) : (
        <>
          <button style={{...btnSmLine, background: 'transparent'}}
                  onClick={() => { setAuthMode0('login'); setSheet('auth'); }}>登录</button>
          <button style={{...btnSm, padding: '8px 16px'}}
                  onClick={() => { setAuthMode0('register'); setSheet('auth'); }}>注册</button>
        </>
      )}

      {menu && me ? (
        <div role="menu" onClick={(e) => e.stopPropagation()} style={{
          position: 'absolute', top: 'calc(100% + 8px)', right: 0, zIndex: 30, width: 302,
          background: C.card, border: `1px solid ${C.line}`, borderRadius: 14,
          boxShadow: 'var(--sh-pop)', padding: 8,
        }}>
          <div style={{display: 'flex', gap: 10, alignItems: 'center', padding: '8px 10px 12px'}}>
            <span style={{fontSize: 24}} aria-hidden>{me.avatar || '🦊'}</span>
            <span style={{minWidth: 0}}>
              <b style={{fontSize: 14.5, display: 'block'}}>{me.nickname || '创作者'}</b>
              <small title={me.email} style={{
                fontSize: 12, color: C.soft, display: 'block', overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 210,
              }}>{me.email}</small>
            </span>
          </div>
          <div style={{background: C.paper, borderRadius: 10, padding: '10px 12px', marginBottom: 6}}>
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                         fontSize: 13}}>
              <span style={{color: C.soft}}>当前档位</span>
              <TierChip tier={tier} label={`${me.tier_label || '免费版'}${tier !== 'free' ? ' · 永久' : ''}`} />
            </div>
            {tier === 'free' && typeof me.free_daily_builds === 'number' ? (
              <div style={{display: 'flex', justifyContent: 'space-between', fontSize: 13, marginTop: 7}}>
                <span style={{color: C.soft}}>今日免费额度</span>
                <b>已用 {me.builds_today || 0} / {me.free_daily_builds} 条</b>
              </div>
            ) : null}
          </div>
          <button style={item} onClick={() => { setMenu(false); setSheet(tier === 'premium' ? 'brand' : 'pricing'); }}>
            <i style={{...mi, color: tier === 'premium' ? C.accent : C.soft}}>
              {tier === 'premium' ? '◈' : '🔒'}
            </i>品牌套装
            <i style={{fontStyle: 'normal', marginLeft: 'auto', fontSize: 12, color: C.soft}}>
              {tier === 'premium' ? 'Logo · 声音 · 水印' : '高级版'}
            </i>
          </button>
          <button style={item} onClick={() => { setMenu(false); setSheet('settings'); }}>
            <i style={mi}>⚙</i>账号设置
            <i style={{fontStyle: 'normal', marginLeft: 'auto', fontSize: 12, color: C.soft}}>
              昵称 · 头像 · 密码
            </i>
          </button>
          <button style={item} onClick={() => { setMenu(false); setSheet('pricing'); }}>
            <i style={{...mi, color: C.accent}}>
              {tier === 'premium' ? '◆' : '⚡'}
            </i>{tier === 'premium' ? '我的权益' : '升级 / 兑换卡密'}
          </button>
          <button style={item} onClick={() => { setMenu(false); setSheet('contact'); }}>
            <i style={mi}>✉︎</i>联系创始人
          </button>
          <button style={{...item, color: C.err}} onClick={() => void signOut()}>
            <i style={mi}>⎋</i>退出登录
          </button>
        </div>
      ) : null}

      {sheet === 'auth' ? (
        <AuthSheet authst={authst} mode0={authMode0} note={authNote} onClose={() => setSheet('')}
                   onSignedIn={() => {
                     void refresh().then(() => {
                       setSheet('');
                       onSignedIn();
                     });
                   }} />
      ) : null}
      {sheet === 'pricing' ? (
        <PricingSheet me={me} onClose={() => setSheet('')} refresh={refresh}
                      needAuth={() => { setAuthMode0('login'); setSheet('auth'); }} toast={toast} />
      ) : null}
      {sheet === 'settings' && me ? (
        <SettingsSheet me={me} onClose={() => setSheet('')} onChanged={(m) => onMe(m)}
                       onSignedOut={() => void signOut()} />
      ) : null}
      {sheet === 'contact' ? (
        <ContactSheet onClose={() => setSheet('')} toast={toast} />
      ) : null}
      {sheet === 'brand' ? (
        <BrandSheet onClose={() => setSheet('')} toast={toast} onBrandChanged={onBrandChanged} />
      ) : null}
    </div>
  );
};
