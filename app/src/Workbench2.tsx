import { useEffect, useRef, useState } from 'react';
import { planScript, renderVideo } from './lib/render';
import type { ThemeName, PlanBeat } from './lib/types';
import {
  createGen, deleteGen, getMe, listHistory, login, logout, redeem, register,
  uploadVideo, videoUrl, type GenItem, type Me,
} from './lib/account';
import { exportJianyingDraft } from './lib/jianying';

type Choice = ThemeName | 'auto';

const STYLES: { id: Choice; name: string }[] = [
  { id: 'auto', name: '自动' },
  { id: 'poster', name: '大字报' },
  { id: 'magazine', name: '杂志' },
  { id: 'dashboard', name: '数据' },
  { id: 'news', name: '新闻' },
  { id: 'newsroom', name: '播报' },
  { id: 'ledger', name: '财报' },
  { id: 'marker', name: '白板' },
  { id: 'swiss', name: '极简' },
  { id: 'terminal', name: '终端' },
  { id: 'broadsheet', name: '报纸' },
  { id: 'cover', name: '封面' },
  { id: 'reel', name: '胶片' },
  { id: 'night', name: '夜行' },
];

const SAMPLES = [
  { file: 'samples/poster.mp4', poster: 'samples/poster.jpg', name: '大字报', tag: '加盟 · 观点' },
  { file: 'samples/magazine.mp4', poster: 'samples/magazine.jpg', name: '杂志', tag: '律师 · 咨询' },
  { file: 'samples/dashboard.mp4', poster: 'samples/dashboard.jpg', name: '数据', tag: '教培 · 测评' },
];

const DEMO = `想开一家小店，你最怕的是什么？
不是没客人，是钱投进去，三个月就撑不住。
今天讲三个数，你记下来再去谈加盟。
第一个数，前期总投入。加盟费、保证金、装修、设备、首批物料，加起来才是真数。
第二个数，回本周期。总部说八个月，你就按十二个月算，多出来的四个月是你的活路。
第三个数，日均流水。别问总部要，去他现有的店里蹲三天。
这三个数算完，你大概就知道这门生意能不能做。
如果你正在看某个项目，把品牌名发给我，我帮你把这三个数拆开算一遍。`;

function pickTheme(text: string): ThemeName {
  if (/\d+\s*(万|元|%|倍)/.test(text) || /(回本|投入|成本|流水)/.test(text)) return 'dashboard';
  if (/(合同|条款|判决|律师|赔偿|仲裁)/.test(text)) return 'magazine';
  if (/(考试|成绩|孩子|提分|上课|家长)/.test(text)) return 'news';
  return 'poster';
}

export default function Workbench() {
  const [text, setText] = useState('');
  const [choice, setChoice] = useState<Choice>('auto');
  const [broll, setBroll] = useState(false);
  const [music, setMusic] = useState(true);
  const [stage, setStage] = useState('');
  const [pct, setPct] = useState(0);
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [secs, setSecs] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const busy = useRef(false);

  const [me, setMe] = useState<Me | null>(null);
  const [history, setHistory] = useState<GenItem[]>([]);
  const [showAuth, setShowAuth] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authEmail, setAuthEmail] = useState('');
  const [authPass, setAuthPass] = useState('');
  const [authErr, setAuthErr] = useState('');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'limited' | 'error'>('idle');
  const [showBuy, setShowBuy] = useState(false);
  const [buyCode, setBuyCode] = useState('');
  const [buyMsg, setBuyMsg] = useState('');
  const [plan, setPlan] = useState<PlanBeat[] | null>(null);
  const [voice, setVoice] = useState('zh-CN-YunxiNeural');
  const [jianyingMsg, setJianyingMsg] = useState('');
  const [zipUrl, setZipUrl] = useState('');
  const [playId, setPlayId] = useState('');

  const refresh = async () => {
    try { setMe(await getMe()); } catch { /* 离线也能用 */ }
    try { setHistory((await listHistory()).items); } catch { /* 同上 */ }
  };
  useEffect(() => { void refresh(); }, []);

  const chars = text.trim().length;
  const est = Math.max(0, Math.round(chars / 4.6));

  async function doAuth() {
    setAuthErr('');
    try {
      if (authMode === 'register') await register(authEmail.trim(), authPass);
      else await login(authEmail.trim(), authPass);
      setShowAuth(false);
      setAuthPass('');
      await refresh();
    } catch (e) {
      setAuthErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function run() {
    if (busy.current) return;
    const src = text.trim();
    if (src.length < 20) { setErr('再写几句，至少 20 个字'); return; }
    busy.current = true;
    setRunning(true);
    setErr(null); setUrl(null); setPct(0); setSecs(null);
    setSaveState('idle');
    const t0 = performance.now();
    const theme = choice === 'auto' ? pickTheme(src) : choice;
    try {
      setStage('读文案，拆镜头');
      const plan = await planScript(src);
      setPlan(plan);
      const title = src.split(/[。！？\n]/)[0].slice(0, 14);
      const blob = await renderVideo(plan, theme, title, ({ stage: s, percent }) => {
        setStage(s);
        setPct(percent);
      }, broll, music, voice);
      const secs = Math.round((performance.now() - t0) / 1000);
      setSecs(secs);
      setUrl(URL.createObjectURL(blob));
      setPct(100);

      // 存进作品库（额度在这里扣）
      setSaveState('saving');
      try {
        const rec = await createGen({
          title, text: src, theme,
          duration: Math.round(plan.length * 2.5),
        });
        await uploadVideo(rec.id, blob);
        setSaveState('saved');
        await refresh();
      } catch (e) {
        const status = (e as Error & { status?: number }).status;
        setSaveState(status === 402 ? 'limited' : 'error');
        if (status === 402) setShowBuy(true);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      busy.current = false;
      setRunning(false);
    }
  }

  async function exportDraft() {
    if (!plan) return;
    const title = text.trim().split(/[。！？\n]/)[0].slice(0, 14) || 'getcut';
    try {
      const r = await exportJianyingDraft({
        title, width: 1080, height: 1920, fps: 30,
        beats: plan.map((b) => ({ text: b.text, duration: 2.5, card: b.card })),
      });
      if (!r.zipBlob) throw new Error('没有生成 zip');
      const u = URL.createObjectURL(r.zipBlob);
      setZipUrl(u);
      const a = document.createElement('a');
      a.href = u;
      a.download = `${title}-剪映草稿.zip`;
      a.rel = 'noopener';
      document.body.appendChild(a);   // 游离节点有的浏览器不认 download
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(u), 5000);
      setJianyingMsg(`已生成草稿（${(r.zipBlob.size / 1024).toFixed(0)} KB）`);
    } catch (e) {
      setJianyingMsg(`导出失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  return (
    <div className="page">
      <header>
        <a className="brand" href="/">GetCut</a>
        <div className="topright">
          {me?.pro ? <span className="quota pro">已买断 · 不限条数</span>
            : me ? <span className="quota">免费剩 {me.remaining} 条</span> : null}
          {me && !me.pro ? <button className="link" onClick={() => setShowBuy(true)}>599 买断</button> : null}
          {me?.loggedIn ? (
            <span className="who" title={me.email || ''}>
              {me.email}
              <button className="link" onClick={async () => { await logout(); await refresh(); }}>退出</button>
            </span>
          ) : (
            <button className="link" onClick={() => { setAuthMode('login'); setShowAuth(true); }}>登录</button>
          )}
        </div>
      </header>

      {showAuth ? (
        <div className="mask" onClick={() => setShowAuth(false)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>{authMode === 'login' ? '登录' : '注册'}</h3>
            <p>用邮箱登录，作品会存在你的账号下</p>
            <input
              type="email" placeholder="you@example.com" value={authEmail}
              onChange={(e) => setAuthEmail(e.target.value)}
            />
            <input
              type="password" placeholder="密码（至少 6 位）" value={authPass}
              onChange={(e) => setAuthPass(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void doAuth(); }}
            />
            {authErr ? <p className="err">{authErr}</p> : null}
            <button className="primary" onClick={doAuth}>
              {authMode === 'login' ? '登录' : '注册并登录'}
            </button>
            <button
              className="link"
              onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthErr(''); }}
            >
              {authMode === 'login' ? '没有账号？注册一个' : '已有账号，去登录'}
            </button>
          </div>
        </div>
      ) : null}

      {showBuy ? (
        <div className="mask" onClick={() => setShowBuy(false)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <h3>599 元买断</h3>
            <p>不限条数 · 作品存 90 天 · 含全部 13 种风格。付款后给你一串卡密，在这里核销。</p>
            {me?.loggedIn ? null : <p className="err">先登录，卡密会绑到你的账号</p>}
            <input
              placeholder="GC-XXXX-XXXX-XXXX" value={buyCode}
              onChange={(e) => { setBuyCode(e.target.value); setBuyMsg(''); }}
            />
            {buyMsg ? <p className={buyMsg.startsWith('已') ? 'ok' : 'err'}>{buyMsg}</p> : null}
            <button
              className="primary"
              onClick={async () => {
                if (!me?.loggedIn) { setShowBuy(false); setShowAuth(true); return; }
                try {
                  const r = await redeem(buyCode);
                  setBuyMsg(r.already ? '这张卡已经用过，权益已生效' : '已解锁，随便用');
                  await refresh();
                } catch (e) { setBuyMsg(e instanceof Error ? e.message : String(e)); }
              }}
            >{me?.loggedIn ? '核销卡密' : '先去登录'}</button>
            <p className="dim">还没买？微信 / 支付宝转账后把邮箱发给客服，人工发码。</p>
          </div>
        </div>
      ) : null}

      <section className="hero">
        <h1>一条能发出去的获客片，<br />只需要一段文案。</h1>
        <p>粘贴口播稿，AI 拆镜头、配音、排版，几分钟后拿到竖屏成片。</p>
      </section>

      <section className="samples" aria-label="样例">
        {SAMPLES.map((s) => (
          <figure key={s.file}>
            <video src={s.file} poster={s.poster} muted loop autoPlay playsInline preload="auto" />
            <figcaption><b>{s.name}</b><span>{s.tag}</span></figcaption>
          </figure>
        ))}
        <p className="samples-note">上面是样例，你写的内容会按选中的长相生成</p>
      </section>

      <section className="composer">
        {url ? (
          <div className="result">
            <video src={url} controls playsInline />
            <div className="result-side">
              <h3>做好了</h3>
              <p>{secs ? `用时 ${secs} 秒` : ''} · 1080×1920 · 可直接发抖音/视频号</p>
              {saveState === 'saving' ? <p className="dim">正在存进作品库…</p> : null}
              {saveState === 'saved' ? <p className="ok">已存进作品库</p> : null}
              {saveState === 'limited' ? <p className="err">免费 3 条用完了 · 这条可以先下载，解锁后自动存</p> : null}
              {saveState === 'error' ? <p className="err">存作品库失败，但下载不受影响</p> : null}
              <a className="primary" href={url} download="getcut.mp4">下载 MP4</a>
              <button className="ghost" onClick={exportDraft}>导出剪映草稿</button>`n              {jianyingMsg ? <p className="dim">{jianyingMsg}</p> : null}`n              {zipUrl ? <a className="dl" href={zipUrl} download="getcut-剪映草稿.zip">保存剪映草稿.zip</a> : null}
              <button className="ghost" onClick={() => { setUrl(null); setPct(0); setStage(''); setSaveState('idle'); }}>
                再做一条
              </button>
            </div>
          </div>
        ) : (
          <>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={'把口播稿粘在这里。\n\n想开一家小店，你最怕的是什么？不是没客人，是钱投进去三个月就撑不住……'}
            />
            <div className="bar">
              <div className="styles" role="tablist">
                {STYLES.map((s) => (
                  <button
                    key={s.id}
                    role="tab"
                    aria-selected={choice === s.id}
                    className={choice === s.id ? 'on' : ''}
                    onClick={() => setChoice(s.id)}
                  >{s.name}</button>
                ))}
              </div>
              <span className="checks">
                <select
                  className="voice"
                  value={voice}
                  onChange={(e) => setVoice(e.target.value)}
                  title="配音音色"
                >
                  <option value="zh-CN-YunxiNeural">云希 · 男声</option>
                  <option value="zh-CN-YunyangNeural">云扬 · 播音</option>
                  <option value="zh-CN-XiaoxiaoNeural">晓晓 · 女声</option>
                  <option value="zh-CN-XiaoyiNeural">晓伊 · 活泼</option>
                  <option value="zh-CN-YunjianNeural">云健 · 厚实</option>
                </select>
                <label className="check">
                  <input type="checkbox" checked={music} onChange={(e) => setMusic(e.target.checked)} />
                  背景音乐
                </label>
                <label className="check">
                  <input type="checkbox" checked={broll} onChange={(e) => setBroll(e.target.checked)} />
                  实拍画面
                </label>
              </span>
            </div>
            <button className="primary" onClick={run} disabled={running}>
              {running ? (stage || '生成中') : '生成视频'}
            </button>
            <div className="meta">
              <span>{chars} 字{chars ? ` · 约 ${est} 秒` : ''}</span>
              <button className="link" onClick={() => setText(DEMO)}>用示例文案试试</button>
            </div>
            <p className="price">
              {me?.pro ? '已买断 · 不限条数' : `免费 3 条 · 之后 599 元买断，不限条数`}
              {me && !me.pro ? <button className="link" onClick={() => setShowBuy(true)}>用卡密解锁</button> : null}
            </p>
            {running ? <div className="progress"><i style={{ width: `${pct}%` }} /></div> : null}
            {err ? <p className="err">{err}</p> : null}
          </>
        )}
      </section>

      {history.length ? (
        <section className="works">
          <div className="works-head">
            <h2>我的作品</h2>
            <span>{me?.loggedIn ? '换设备登录也能看到' : '登录后换设备也能看到'}</span>
          </div>
          <div className="works-grid">
            {history.map((g) => (
              <article key={g.id} className="work">
                <h3>{g.title || '未命名'}</h3>
                <p className="dim">
                  {new Date(g.created).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  {g.duration ? ` · ${g.duration} 秒` : ''}
                  {g.size ? ` · ${(g.size / 1024 / 1024).toFixed(1)} MB` : ''}
                </p>
                <div className="work-actions">
                  {g.hasVideo ? (
                    <>
                      <button className="link" onClick={() => setPlayId(g.id)}>播放</button>
                      <a className="link" href={videoUrl(g.id)} download={`${g.title || 'getcut'}.mp4`}>下载</a>
                    </>
                  ) : <span className="dim">成片未保存</span>}
                  <button
                    className="link danger"
                    onClick={async () => { await deleteGen(g.id); await refresh(); }}
                  >删除</button>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {playId ? (
        <div className="mask" onClick={() => setPlayId('')}>
          <div className="player" onClick={(e) => e.stopPropagation()}>
            <video src={videoUrl(playId)} controls autoPlay playsInline />
          </div>
        </div>
      ) : null}

      <footer>
        <span>GetCut · 获客短视频</span>
        <span>文案 20~1200 字 · 竖屏 1080×1920</span>
      </footer>

      <style>{`
        :root {
          --bg: #0a0908;
          --ink: #f4efe4;
          --dim: rgba(244,239,228,0.5);
          --line: rgba(244,239,228,0.12);
          --gold: #d8a94a;
          --gold-ink: #151006;
        }
        * { box-sizing: border-box; }
        html, body, #root { min-height: 100%; }
        body { margin: 0; background: var(--bg); color: var(--ink);
          font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
          -webkit-font-smoothing: antialiased; }
        .page { max-width: 860px; margin: 0 auto; padding: 30px 24px 56px; }

        header { display: flex; align-items: center; justify-content: space-between; }
        .brand { color: var(--ink); text-decoration: none; font-size: 20px; font-weight: 900; letter-spacing: .5px; }
        .brand::after { content: ''; }
        .note { font-size: 12px; color: var(--dim); letter-spacing: 1px; }
        .topright { display: flex; align-items: center; gap: 14px; font-size: 13px; color: var(--dim); }
        .quota { padding: 4px 10px; border: 1px solid var(--line); border-radius: 999px; font-size: 12px; }
        .quota.pro { border-color: rgba(216,169,74,.55); color: var(--gold); }
        .who { display: inline-flex; align-items: center; gap: 10px; font-size: 12px; max-width: 260px;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .mask { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: grid; place-items: center; z-index: 20; padding: 20px; }
        .dialog { width: 100%; max-width: 380px; background: #131110; border: 1px solid var(--line);
          border-radius: 16px; padding: 22px; display: grid; gap: 10px; }
        .dialog h3 { margin: 0; font-size: 20px; }
        .dialog p { margin: 0; color: var(--dim); font-size: 13px; }
        .dialog input { background: #0d0c0a; border: 1px solid var(--line); border-radius: 10px;
          color: var(--ink); padding: 12px 14px; font-size: 14px; outline: none; }
        .dialog input:focus { border-color: rgba(216,169,74,.6); }
        .ok { color: #8bd18b !important; font-size: 13px; margin: 0 0 12px; }
        .works { margin-top: 42px; }
        .works-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 14px; }
        .works-head h2 { margin: 0; font-size: 18px; font-weight: 800; }
        .works-head span { font-size: 12px; color: var(--dim); }
        .works-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
        .work { border: 1px solid var(--line); border-radius: 12px; padding: 14px; background: #0d0c0a; }
        .work h3 { margin: 0 0 6px; font-size: 14px; font-weight: 700; overflow: hidden;
          text-overflow: ellipsis; white-space: nowrap; }
        .work-actions { display: flex; gap: 14px; margin-top: 10px; }
        .danger { color: #ff9a86; }
        .player { max-width: 380px; width: 100%; }
        .player video { width: 100%; border-radius: 14px; background: #000; }

        .hero { padding: 56px 0 34px; }
        .hero h1 { margin: 0; font-size: 46px; line-height: 1.25; font-weight: 900; letter-spacing: -.5px; }
        .hero p { margin: 16px 0 0; color: var(--dim); font-size: 15px; line-height: 1.8; }

        .samples { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
        .samples figure { margin: 0; }
        .samples video { width: 100%; max-height: 220px; aspect-ratio: 9/16; object-fit: cover; border-radius: 14px;
          background: #111; display: block; border: 1px solid var(--line); }
        .samples figcaption { display: flex; justify-content: space-between; align-items: baseline;
          margin-top: 8px; font-size: 12px; color: var(--dim); }
        .samples figcaption b { color: var(--ink); font-size: 13px; font-weight: 600; }
        .samples-note { grid-column: 1 / -1; margin: 6px 0 0; font-size: 12px; color: rgba(244,239,228,.36); }

        .composer { margin-top: 34px; }
        textarea { width: 100%; min-height: 240px; resize: vertical; background: #0d0c0a; color: var(--ink);
          border: 1px solid var(--line); border-radius: 14px; padding: 18px; font-size: 15px;
          line-height: 1.95; font-family: inherit; outline: none; transition: border-color .2s, box-shadow .2s; }
        textarea::placeholder { color: rgba(244,239,228,.28); }
        textarea:focus { border-color: rgba(216,169,74,.6); box-shadow: 0 0 0 3px rgba(216,169,74,.1); }

        .bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 12px 0 16px; flex-wrap: wrap; }
        .styles { display: flex; gap: 6px; flex-wrap: wrap; }
        .styles button { background: transparent; border: 1px solid var(--line); color: var(--dim);
          padding: 7px 14px; border-radius: 999px; font-size: 13px; cursor: pointer; transition: all .18s; }
        .styles button:hover { color: var(--ink); border-color: rgba(244,239,228,.25); }
        .styles button.on { color: var(--gold-ink); background: var(--gold); border-color: var(--gold); }
        .checks { display: inline-flex; align-items: center; gap: 14px; }
        .voice { background: #0d0c0a; color: var(--ink); border: 1px solid var(--line);
          border-radius: 8px; padding: 6px 10px; font-size: 12px; outline: none; }
        .page { display: flex; flex-direction: column; }
        .hero { order: 1; } .composer { order: 2; } .samples { order: 3; } .works { order: 4; } footer { order: 5; }
        .check { display: inline-flex; align-items: center; gap: 7px; font-size: 13px; color: var(--dim); cursor: pointer; }
        .check input { width: 15px; height: 15px; accent-color: var(--gold); }

        .primary { display: inline-block; width: 100%; text-align: center; text-decoration: none;
          background: var(--gold); color: var(--gold-ink); border: 0; border-radius: 12px;
          padding: 15px 20px; font-size: 16px; font-weight: 800; letter-spacing: 1px; cursor: pointer; }
        .primary:disabled { opacity: .5; cursor: not-allowed; }
        .ghost { margin-top: 10px; width: 100%; background: transparent; color: var(--ink);
          border: 1px solid var(--line); border-radius: 12px; padding: 12px; font-size: 14px; cursor: pointer; }

        .meta { display: flex; justify-content: space-between; align-items: center; margin-top: 10px;
          font-size: 12px; color: var(--dim); }
        .link { background: none; border: 0; color: var(--gold); font-size: 12px; cursor: pointer; }
        .price { display: flex; align-items: center; gap: 12px; margin: 12px 0 0; font-size: 12px; color: var(--dim); }
        .progress { height: 3px; background: rgba(244,239,228,.08); border-radius: 3px; overflow: hidden; margin-top: 12px; }
        .progress i { display: block; height: 100%; background: var(--gold); transition: width .3s; }
        .err { color: #ff9a86; font-size: 13px; margin-top: 10px; }

        .result { display: grid; grid-template-columns: 260px 1fr; gap: 22px; align-items: start; }
        .result video { width: 100%; aspect-ratio: 9/16; object-fit: cover; border-radius: 14px; background: #000; }
        .result-side h3 { margin: 4px 0 6px; font-size: 20px; }
        .result-side p { margin: 0 0 16px; color: var(--dim); font-size: 13px; }

        footer { display: flex; justify-content: space-between; margin-top: 48px; padding-top: 18px;
          border-top: 1px solid var(--line); color: rgba(244,239,228,.32); font-size: 12px; }

        @media (max-width: 720px) {
          .hero h1 { font-size: 32px; }
          .samples { grid-template-columns: repeat(3, 1fr); gap: 8px; }
          .result { grid-template-columns: 1fr; }
          .result video { max-width: 260px; }
        }
      `}</style>
    </div>
  );
}

















