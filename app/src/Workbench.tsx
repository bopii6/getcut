import { useEffect, useMemo, useRef, useState } from 'react';
import { planScript, renderVideo } from './lib/render';
import type { ThemeName, PlanBeat } from './lib/types';
import {
  createGen, deleteGen, getMe, listHistory, login, logout, redeem, register,
  uploadVideo, videoUrl, type GenItem, type Me,
} from './lib/account';
import { exportJianyingDraft } from './lib/jianying';

type Choice = ThemeName | 'auto';

const STYLES: { id: Choice; name: string; use: string; thumb: string; preview?: string }[] = [
  { id: 'poster', name: '冲击大字', use: '开场抛痛点', thumb: 'style-thumbs/poster.jpg?v=2', preview: 'style-previews/poster.mp4' },
  { id: 'marker', name: '白板讲解', use: '讲方法步骤', thumb: 'style-thumbs/marker.jpg?v=2', preview: 'style-previews/marker.mp4' },
  { id: 'dashboard', name: '数据说服', use: '算账讲回报', thumb: 'style-thumbs/dashboard.jpg?v=2', preview: 'style-previews/dashboard.mp4' },
  { id: 'newsroom', name: '权威播报', use: '立信任讲案例', thumb: 'style-thumbs/newsroom.jpg?v=2', preview: 'style-previews/newsroom.mp4' },
  { id: 'magazine', name: '杂志访谈', use: '专业形象', thumb: 'style-thumbs/magazine.jpg?v=2', preview: 'style-previews/magazine.mp4' },
];

const VOICES = [
  { id: 'zh-CN-YunxiNeural', name: '云希 · 男声' },
  { id: 'zh-CN-YunyangNeural', name: '云扬 · 播音' },
  { id: 'zh-CN-XiaoxiaoNeural', name: '晓晓 · 女声' },
  { id: 'zh-CN-XiaoyiNeural', name: '晓伊 · 活泼' },
  { id: 'zh-CN-YunjianNeural', name: '云健 · 厚实' },
];

const STEPS = ['读稿', '配音', '画帧', '合成', '封装'];

const DEMO = `想开一家小店，你最怕的是什么？不是没客人，是钱投进去，三个月就撑不住。
今天讲三个数，你记下来再去谈加盟。
第一个数，前期总投入。加盟费、保证金、装修、设备、首批物料，加起来才是真数。
第二个数，回本周期。总部说八个月，你就按十二个月算。
第三个数，日均流水。别问总部要，去他现有的店里蹲三天。
把品牌名发给我，我帮你把这三个数拆开算一遍。`;

function pickTheme(text: string): ThemeName {
  if (/\d+\s*(万|元|%|倍)/.test(text) || /(回本|投入|成本|流水)/.test(text)) return 'dashboard';
  if (/(合同|条款|判决|律师|赔偿|仲裁)/.test(text)) return 'magazine';
  if (/(考试|成绩|孩子|提分|上课|家长)/.test(text)) return 'newsroom';
  return 'poster';
}

function fmt(t: number) {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export default function Workbench() {
  const [text, setText] = useState('');
  const [choice, setChoice] = useState<Choice>('poster');
  const [voice, setVoice] = useState(VOICES[0].id);
  const [music, setMusic] = useState(true);
  const [stage, setStage] = useState('');
  const [pct, setPct] = useState(0);
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [secs, setSecs] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [plan, setPlan] = useState<PlanBeat[] | null>(null);
  const [hover, setHover] = useState('');
  const [started, setStarted] = useState(false);
  const busy = useRef(false);
  const startRef = useRef(0);
  const textRef = useRef<HTMLTextAreaElement | null>(null);
  const liveCanvas = useMemo(() => document.createElement('canvas'), []);
  const liveRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [now, setNow] = useState(0);
  const [dur, setDur] = useState(0);

  const [me, setMe] = useState<Me | null>(null);
  const [history, setHistory] = useState<GenItem[]>([]);
  const [panel, setPanel] = useState<'' | 'account' | 'works' | 'ai'>('');
  const [aiTopic, setAiTopic] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [authEmail, setAuthEmail] = useState('');
  const [authPass, setAuthPass] = useState('');
  const [authErr, setAuthErr] = useState('');
  const [buyCode, setBuyCode] = useState('');
  const [showBuy, setShowBuy] = useState(false);

  const refresh = async () => {
    try { setMe(await getMe()); } catch { /* 离线可用 */ }
    try { setHistory((await listHistory()).items); } catch { /* 同上 */ }
  };
  useEffect(() => { void refresh(); }, []);
  useEffect(() => {
    if (running && liveRef.current) liveRef.current.replaceChildren(liveCanvas);
  }, [running, liveCanvas]);

  const chars = text.trim().length;
  const est = Math.max(0, Math.round(chars / 4.6));
  const stepIndex = /拆稿|读稿/.test(stage) ? 0 : /配音/.test(stage) ? 1
    : /画帧|编码器/.test(stage) ? 2 : /音轨|合成/.test(stage) ? 3 : /完成|封装/.test(stage) ? 4 : 0;
  const elapsed = startRef.current ? (Date.now() - startRef.current) / 1000 : 0;
  const remain = pct > 3 ? Math.max(1, Math.round((elapsed / pct) * (100 - pct))) : 0;
  const eta = running ? (remain > 0 ? `约还剩 ${remain} 秒` : '正在启动…') : '';
  const empty = chars === 0 && !started;
  const scenes = useMemo(() => {
    if (plan?.length) return plan.map((b) => ({ text: b.text, duration: Math.max(1.4, Math.round(b.text.length / 4.6)) }));
    return text.split(/[。！？\n]/).map((s) => s.trim()).filter(Boolean).slice(0, 12)
      .map((p) => ({ text: p, duration: Math.max(1.6, Math.round(p.length / 4.6)) }));
  }, [plan, text]);
  const totalDur = scenes.reduce((n, s) => n + s.duration, 0) || 1;

  async function genScript() {
    if (aiTopic.trim().length < 2) return;
    setAiBusy(true);
    try {
      const res = await fetch('/api/script', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ topic: aiTopic.trim(), industry: '通用' }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '写稿失败');
      setText(data.text);
      setPanel('');
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setAiBusy(false); }
  }

  async function doAuth(mode: 'login' | 'register') {
    setAuthErr('');
    try {
      if (mode === 'register') await register(authEmail.trim(), authPass);
      else await login(authEmail.trim(), authPass);
      setAuthPass('');
      await refresh();
    } catch (e) { setAuthErr(e instanceof Error ? e.message : String(e)); }
  }

  async function run() {
    if (busy.current) return;
    const src = text.trim();
    if (src.length < 20) { setErr('再写几句，至少 20 个字'); textRef.current?.focus(); return; }
    busy.current = true;
    startRef.current = Date.now();
    setRunning(true); setErr(null); setUrl(null); setPct(0); setSecs(null);
    const t0 = performance.now();
    const theme = choice === 'auto' ? pickTheme(src) : choice;
    try {
      setStage('拆稿');
      const planned = await planScript(src);
      setPlan(planned);
      const title = src.split(/[。！？\n]/)[0].slice(0, 14);
      const blob = await renderVideo(planned, theme, title, ({ stage: s, percent }) => {
        setStage(s); setPct(percent);
      }, false, music, voice, '', liveCanvas, 'auto', (d) => {
        void fetch('/api/diag', {
          method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ ...d, ua: navigator.userAgent, src: 'desktop', style: theme }),
        });
      });
      setSecs(Math.round((performance.now() - t0) / 1000));
      setUrl(URL.createObjectURL(blob));
      setPct(100);
      try {
        const rec = await createGen({ title, text: src, theme, duration: Math.round(planned.length * 2.5) });
        await uploadVideo(rec.id, blob);
        await refresh();
      } catch { /* 额度用完也能下载 */ }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      busy.current = false;
      setRunning(false);
    }
  }

  async function exportDraft() {
    if (!plan) return;
    try {
      const r = await exportJianyingDraft({
        title: text.trim().split(/[。！？\n]/)[0].slice(0, 14) || 'getcut',
        width: 1080, height: 1920, fps: 30,
        beats: plan.map((b) => ({ text: b.text, duration: 2.5, card: b.card })),
      });
      if (!r.zipBlob) throw new Error('没有生成 zip');
      const u = URL.createObjectURL(r.zipBlob);
      const a = document.createElement('a');
      a.href = u; a.download = 'getcut-剪映草稿.zip';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(u), 5000);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }

  const free = me ? (me.pro ? '已买断' : `免费剩 ${me.remaining} 条`) : '免费 3 条';

  return (
    <div className="wb">
      <header className="top">
        <button
          className="brand"
          title="回到首页"
          onClick={() => {
            // 回到起手式：清空项目状态，但保留账号
            setText(''); setUrl(null); setPlan(null); setStarted(false);
            setPct(0); setStage(''); setSecs(null); setErr(null);
            setChoice('poster');
          }}
        >GetCut<span>studio</span></button>
        <div className="proj">
          <b>{text.trim().split(/[。！？\n]/)[0].slice(0, 20) || '未命名项目'}</b>
          <span>{running ? `${stage} ${pct}%` : url ? '已出片' : empty ? '新建' : '草稿'}</span>
        </div>
        <div className="topright">
          <span className="quota">{free}</span>
          <button className="av" onClick={() => setPanel(panel === 'account' ? '' : 'account')}>
            {me?.loggedIn ? (me.email || 'U').slice(0, 1).toUpperCase() : '登'}
          </button>
        </div>
      </header>

      <main className={empty ? 'main empty' : 'main'}>
        {/* 左：起手式 / 编辑区 */}
        <section className="pane">
          {empty ? (
            <div className="start">
              <h1>把一段文案<br />做成能发的片</h1>
              <p className="start-sub">粘稿子，或者让 AI 写一篇。竖屏 1080×1920，直接发抖音。</p>

              <div className="start-actions">
                <button className="big" onClick={() => { setStarted(true); setTimeout(() => textRef.current?.focus(), 30); }}>
                  <b>粘贴文案</b>
                  <span>把口播稿粘进来</span>
                </button>
                <button className="big" onClick={() => setText(DEMO)}>
                  <b>用示例试试</b>
                  <span>看看一条片长什么样</span>
                </button>
                <button className="big" onClick={() => setPanel('ai')}>
                  <b>AI 帮我写</b>
                  <span>给个主题，自动成稿</span>
                </button>
              </div>
            </div>
          ) : null}

          <div className={empty ? 'editor-hidden' : 'editor'}>
            <textarea
              ref={textRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="把口播稿粘在这里……"
            />
            <div className="meta">
              <span>{chars} 字 · 约 {est} 秒</span>
              <button className="link" onClick={() => setText('')}>清空</button>
            </div>
          </div>

          {/* 风格横排：永不裁切，可横向滑 */}
          <div className="strip">
            {STYLES.map((s) => (
              <button
                key={s.id}
                className={`card ${choice === s.id ? 'on' : ''}`}
                onClick={() => setChoice(s.id)}
                onMouseEnter={() => setHover(s.id)}
                onMouseLeave={() => setHover('')}
              >
                {s.preview && hover === s.id
                  ? <video className="card-video" src={s.preview} autoPlay muted loop playsInline />
                  : <img src={s.thumb} alt="" />}
                <b>{s.name}</b>
                <i>{s.use}</i>
              </button>
            ))}
          </div>

          {!running ? <div className="toolbar">
            <select value={voice} onChange={(e) => setVoice(e.target.value)} disabled={running}>
              {VOICES.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
            <label className="chk">
              <input type="checkbox" checked={music} onChange={(e) => setMusic(e.target.checked)} disabled={running} />配乐
            </label>
            <button className="go" onClick={run} disabled={running || empty}>
              '生成视频'
            </button>
          </div> : null}

          {running ? (
            <div className="prog">
              <div className="prog-head">
                <b>{pct}<i>%</i></b>
                <div className="prog-meta">
                  <span>{stage || '准备中'}</span>
                  <em>{eta}</em>
                </div>
              </div>
              <div className="prog-bar"><i style={{ width: `${Math.max(pct, 2)}%` }} /></div>
              <div className="prog-steps">
                {STEPS.map((s, i) => (
                  <span key={s} className={i < stepIndex ? 'done' : i === stepIndex ? 'now' : ''}>
                    <i>{i < stepIndex ? '✓' : i + 1}</i>{s}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
          {err ? <p className="err">{err}</p> : null}

          {url ? (
            <div className="out">
              <span className="fine">{secs ? `${secs} 秒渲染 · ` : ''}成片在右边，可直接下载</span>
            </div>
          ) : null}
        </section>

        {/* 右：预览 */}
        <aside className="preview">
          <div className="phone">
            <div className="island" />
            {running ? (<><div className="ph"><img src="style-thumbs/poster.jpg?v=2" alt="" /></div><div className="live" ref={liveRef} /></>) : url ? (
              <video
                ref={videoRef}
                src={url}
                playsInline
                onLoadedData={(e) => { e.currentTarget.currentTime = 0.4; }}
                onTimeUpdate={(e) => { setNow(e.currentTarget.currentTime); setDur(e.currentTarget.duration || 0); }}
              />
            ) : (
              <div className="ph"><img src="style-thumbs/poster.jpg?v=2" alt="" /></div>
            )}
          </div>
          {url ? (
            <>
              <div className="transport">
                <button className="play" onClick={() => {
                  const v = videoRef.current;
                  if (!v) return;
                  if (v.paused) void v.play(); else v.pause();
                }}>▶</button>
                <span>{fmt(now)} / {fmt(dur || totalDur)}</span>
              </div>
              <div className="out">
                <a className="go" href={url} download="getcut.mp4">下载 MP4</a>
                <button className="ghost" onClick={exportDraft}>剪映草稿</button>
              </div>
            </>
          ) : (
            <p className="hint">{empty ? '生成后成片出现在这里' : '点「生成视频」开始'}</p>
          )}
        </aside>
      </main>

      {/* 抽屉 */}
      {panel === 'ai' ? (
        <div className="mask" onClick={() => setPanel('')}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <h3>给个主题，我来写</h3>
            <input value={aiTopic} onChange={(e) => setAiTopic(e.target.value)} placeholder="例如：加盟回本周期怎么算" autoFocus />
            <button className="go" onClick={genScript} disabled={aiBusy}>{aiBusy ? '正在写…' : '写一篇'}</button>
            <button className="link" onClick={() => setPanel('')}>取消</button>
          </div>
        </div>
      ) : null}

      {panel === 'account' ? (
        <div className="mask" onClick={() => setPanel('')}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <h3>账号</h3>
            {me?.loggedIn ? (
              <>
                <p className="fine">{me.email}</p>
                <p className="fine">{me.pro ? '已买断 · 不限条数' : `免费剩 ${me.remaining} 条`}</p>
                {!me.pro ? <button className="go" onClick={() => { setShowBuy(true); setPanel(''); }}>输入卡密 · ¥599</button> : null}
                <button className="ghost" onClick={async () => { await logout(); await refresh(); }}>退出登录</button>
              </>
            ) : (
              <>
                <input value={authEmail} onChange={(e) => setAuthEmail(e.target.value)} placeholder="邮箱" />
                <input type="password" value={authPass} onChange={(e) => setAuthPass(e.target.value)} placeholder="密码，至少 6 位" />
                {authErr ? <p className="err">{authErr}</p> : null}
                <button className="go" onClick={() => doAuth('login')}>登录</button>
                <button className="link" onClick={() => doAuth('register')}>没有账号，直接注册</button>
              </>
            )}
            <button className="link" onClick={() => { setPanel('works'); }}>看我的作品</button>
          </div>
        </div>
      ) : null}

      {panel === 'works' ? (
        <div className="mask" onClick={() => setPanel('')}>
          <div className="sheet wide" onClick={(e) => e.stopPropagation()}>
            <h3>我的作品</h3>
            {history.length === 0 ? <p className="fine">还没有作品。</p> : null}
            {history.map((g) => (
              <div key={g.id} className="wrow">
                <div>
                  <b>{g.title || '未命名'}</b>
                  <span>{new Date(g.created).toLocaleString('zh-CN')} · {g.duration || 0} 秒</span>
                </div>
                <div className="wact">
                  {g.hasVideo ? <a href={videoUrl(g.id)} download={`${g.title || 'getcut'}.mp4`}>下载</a> : null}
                  <button onClick={async () => { await deleteGen(g.id); await refresh(); }}>删</button>
                </div>
              </div>
            ))}
            <button className="link" onClick={() => setPanel('')}>关闭</button>
          </div>
        </div>
      ) : null}

      {showBuy ? (
        <div className="mask" onClick={() => setShowBuy(false)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <h3>599 买断</h3>
            <input value={buyCode} onChange={(e) => setBuyCode(e.target.value)} placeholder="GC-XXXX-XXXX-XXXX" />
            <button className="go" onClick={async () => {
              try { await redeem(buyCode); await refresh(); setShowBuy(false); }
              catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
            }}>核销</button>
            <button className="link" onClick={() => setShowBuy(false)}>关闭</button>
          </div>
        </div>
      ) : null}

      <style>{`
        :root { --bg:#0B0B0C; --panel:#141417; --panel2:#1B1B20; --line:rgba(255,255,255,.1);
          --line2:rgba(255,255,255,.18); --ink:#F2F2F4; --dim:#9C9CA6; --gold:#F0B429; }
        * { box-sizing: border-box; }
        html, body, #root { height: 100%; }
        body { margin:0; background:var(--bg); color:var(--ink); font: 15px/1.6 "PingFang SC","Microsoft YaHei",system-ui,sans-serif; }

        .wb { height: 100vh; display: flex; flex-direction: column; }
        .top { height: 62px; flex: none; display: flex; align-items: center; gap: 18px; padding: 0 72px;
          max-width: 1320px; margin: 0 auto; width: 100%;
          border-bottom: 1px solid var(--line); }
        /* 隐藏所有滚动条：滚轮照常可用，只是不显示那条丑条 */
        .main, .preview, .strip, .sheet, .editor textarea, .tl { scrollbar-width: none; -ms-overflow-style: none; }
        .main::-webkit-scrollbar, .preview::-webkit-scrollbar, .strip::-webkit-scrollbar,
        .sheet::-webkit-scrollbar, .editor textarea::-webkit-scrollbar, .tl::-webkit-scrollbar { width: 0; height: 0; }        .brand { font-weight: 900; font-size: 17px; background: none; border: 0; color: var(--ink); cursor: pointer;
          padding: 6px 4px; border-radius: 8px; font-family: inherit; }
        .brand:hover { background: rgba(255,255,255,.06); }
        .brand span { color: var(--gold); font-size: 12px; margin-left: 5px; font-weight: 500; }
        .proj { flex: 1; display: flex; align-items: baseline; gap: 10px; min-width: 0; }
        .proj b { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .proj span { font-size: 12px; color: var(--dim); }
        .topright { display: flex; align-items: center; gap: 12px; font-size: 12px; color: var(--dim); }
        .av { width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--line2); background: var(--panel2);
          color: var(--ink); font-weight: 800; cursor: pointer; }

        .main { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0,1fr) 340px; gap: 44px;
          padding: 30px 72px 16px; overflow-y: auto; max-width: 1320px; margin: 0 auto; width: 100%; }
        .main.empty { grid-template-columns: 1fr; align-items: start; padding-top: 40px; }
        .main.empty .pane { max-width: 760px; }
        .main.empty .preview { display: none; }
        .pane { min-width: 0; display: flex; flex-direction: column; gap: 16px; }

        /* 起手式 */
        .start { max-width: 620px; }
        .start h1 { margin: 0; font-size: 46px; line-height: 1.2; letter-spacing: -.02em; }
        .start-sub { margin: 14px 0 30px; color: var(--dim); font-size: 15px; }
        .start-actions { display: grid; gap: 10px; }
        .big { display: grid; gap: 3px; text-align: left; padding: 18px 22px; border-radius: 14px;
          border: 1px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer;
          transition: border-color .15s, transform .12s; }
        .big b { font-size: 17px; }
        .big span { font-size: 13px; color: var(--dim); }
        .big:hover { border-color: var(--gold); transform: translateY(-1px); }
        .big:first-child { background: linear-gradient(180deg,#1E1A10,#141417); border-color: rgba(240,180,41,.4); }

        .editor-hidden { display: none; }
        .editor textarea { width: 100%; height: 220px; resize: none; background: var(--panel); color: var(--ink);
          border: 1px solid var(--line); border-radius: 14px; padding: 18px; font: inherit; font-size: 16px;
          line-height: 1.9; outline: none; }
        .editor textarea:focus { border-color: var(--gold); }
        .meta { display: flex; justify-content: space-between; margin-top: 8px; font-size: 12px; color: var(--dim); }

        /* 风格横排：不裁切 */
        .strip { display: flex; gap: 12px; overflow-x: auto; padding: 4px 2px 10px; scrollbar-width: thin; }
        .card { flex: 0 0 116px; display: grid; gap: 0; padding: 0 0 8px; border: 1px solid var(--line);
          border-radius: 12px; background: var(--panel); color: var(--ink); cursor: pointer; overflow: hidden; }
        .card img, .card .card-video { width: 100%; aspect-ratio: 3/4; object-fit: cover; display: block; }
        .card b { font-size: 13px; padding: 7px 9px 0; }
        .card i { font-style: normal; font-size: 11px; color: var(--gold); padding: 2px 9px 0; }
        .card.on { border-color: var(--gold); box-shadow: 0 0 0 2px rgba(240,180,41,.3); }

        .toolbar { display: flex; align-items: center; gap: 12px; }
        .toolbar select { background: var(--panel2); color: var(--ink); border: 1px solid var(--line);
          border-radius: 10px; padding: 10px 12px; font: inherit; font-size: 14px; }
        .chk { display: inline-flex; align-items: center; gap: 7px; font-size: 14px; color: var(--dim); }
        .chk input { width: 17px; height: 17px; accent-color: var(--gold); }
        .go { flex: 1; padding: 15px 20px; border: 0; border-radius: 12px; background: var(--gold);
          color: #171207; font: inherit; font-size: 16px; font-weight: 800; cursor: pointer; text-align: center;
          text-decoration: none; }
        .go:disabled { opacity: .45; cursor: not-allowed; }
        .ghost { padding: 12px 16px; border: 1px solid var(--line2); border-radius: 10px; background: none;
          color: var(--ink); font: inherit; font-size: 13px; cursor: pointer; }
        .link { background: none; border: 0; color: var(--gold); font: inherit; font-size: 13px; cursor: pointer; }
        .prog { border: 1px solid rgba(240,180,41,.35); border-radius: 14px; padding: 18px 20px; display: grid; gap: 14px;
          background: linear-gradient(180deg, rgba(240,180,41,.10), rgba(240,180,41,.02)); }
        .prog-head { display: flex; align-items: flex-end; gap: 16px; }
        .prog-head b { font-size: 58px; line-height: .95; letter-spacing: -.03em; color: var(--gold); font-weight: 900; }
        .prog-head b i { font-size: 22px; font-style: normal; margin-left: 2px; }
        .prog-meta { display: grid; gap: 4px; padding-bottom: 8px; }
        .prog-meta span { font-size: 15px; color: var(--ink); }
        .prog-meta em { font-style: normal; font-size: 12px; color: var(--dim); }
        .prog-bar { height: 10px; background: rgba(255,255,255,.1); border-radius: 6px; overflow: hidden; }
        .prog-bar i { display: block; height: 100%; border-radius: 6px; transition: width .4s ease;
          background: linear-gradient(90deg, #C98A12, #F0B429 60%, #FFD469);
          box-shadow: 0 0 14px rgba(240,180,41,.55); }
        .prog-steps { display: flex; gap: 8px; flex-wrap: wrap; }
        .prog-steps span { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--dim);
          padding: 5px 10px; border: 1px solid var(--line); border-radius: 99px; }
        .prog-steps i { width: 16px; height: 16px; border-radius: 50%; display: grid; place-items: center;
          font-size: 10px; font-style: normal; background: rgba(255,255,255,.08); }
        .prog-steps .now { color: var(--gold); border-color: rgba(240,180,41,.5); }
        .prog-steps .now i { background: var(--gold); color: #171207; }
        .prog-steps .done { color: #8FD6A5; border-color: rgba(143,214,165,.35); }        .bar { height: 3px; background: rgba(255,255,255,.1); border-radius: 2px; }
        .bar i { display: block; height: 100%; background: var(--gold); }
        .err { color: #ff9a86; font-size: 13px; margin: 0; }
        .fine { color: var(--dim); font-size: 12px; }
        .out { display: flex; align-items: center; gap: 10px; width: 100%; position: sticky; bottom: 0;
          background: linear-gradient(180deg, transparent, var(--bg) 45%); padding-top: 8px; }
        .out .go { flex: none; padding: 12px 18px; font-size: 14px; }

        /* 预览 */
        .preview { display: flex; flex-direction: column; align-items: center; gap: 10px; justify-content: flex-start;
          overflow-y: auto; padding-bottom: 10px; }
        .phone { flex: none; position: relative; width: min(34vh, 264px); aspect-ratio: 9/19.2; border-radius: 38px; padding: 9px;
          background: linear-gradient(160deg,#3C3C41,#16161A 60%,#2A2A2E);
          box-shadow: 0 30px 70px -30px #000, 0 0 0 1px #000, inset 0 0 0 1px rgba(255,255,255,.16); }
        .phone > * { border-radius: 30px; overflow: hidden; }
        .island { position: absolute; top: 16px; left: 50%; transform: translateX(-50%); width: 74px; height: 20px;
          border-radius: 12px; background: #000; z-index: 3; }
        .phone video, .phone .live, .phone .ph { width: 100%; height: 100%; display: block; background: #000; }
        .phone video { object-fit: contain; }
        .live canvas { width: 100%; height: 100%; object-fit: contain; }
        .ph img { width: 100%; height: 100%; object-fit: contain; opacity: .55; }
        .transport { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--dim); }
        .play { width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--line2); background: var(--panel2);
          color: var(--ink); cursor: pointer; }
        .hint { color: var(--dim); font-size: 12px; margin: 0; }

        /* 时间轴 */
        .tl { flex: none; height: 150px; border-top: 1px solid var(--line); padding: 10px 22px 12px;
          display: flex; flex-direction: column; gap: 8px; background: var(--panel); }
        .tl-head { display: flex; align-items: baseline; gap: 12px; font-size: 12px; color: var(--dim); }
        .tl-head b { color: var(--ink); font-size: 13px; }
        .tl-head .link { margin-left: auto; }
        .tl-body { flex: 1; display: grid; grid-template-columns: 44px 1fr; gap: 6px 10px; min-height: 0; }
        .lane-label { font-size: 11px; color: var(--dim); align-self: center; }
        .lane { display: flex; gap: 4px; min-width: 0; overflow: hidden; }
        .clip { flex: 1 1 0; min-width: 0; background: #2A2A31; border: 1px solid var(--line); border-radius: 6px;
          color: #D6D6DE; font-size: 11px; padding: 7px 8px; text-align: left; overflow: hidden; white-space: nowrap; }
        .sub { flex: 1 1 0; min-width: 0; background: rgba(240,180,41,.12); border: 1px solid rgba(240,180,41,.28);
          color: #E3CE9C; font-size: 11px; border-radius: 6px; padding: 7px 8px; text-align: left; overflow: hidden; white-space: nowrap; }

        /* 抽屉 */
        .mask { position: fixed; inset: 0; background: rgba(0,0,0,.62); display: grid; place-items: center; z-index: 40; }
        .sheet { width: min(420px, 92vw); background: var(--panel); border: 1px solid var(--line2); border-radius: 16px;
          padding: 22px; display: grid; gap: 10px; }
        .sheet.wide { width: min(560px, 92vw); max-height: 70vh; overflow-y: auto; }
        .sheet h3 { margin: 0; font-size: 18px; }
        .sheet input { background: var(--panel2); border: 1px solid var(--line); border-radius: 10px; color: var(--ink);
          padding: 12px 14px; font: inherit; font-size: 15px; outline: none; }
        .sheet input:focus { border-color: var(--gold); }
        .wrow { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 12px;
          border: 1px solid var(--line); border-radius: 10px; }
        .wrow b { display: block; font-size: 13px; }
        .wrow span { font-size: 11px; color: var(--dim); }
        @media (max-width: 1100px) {
          .main { display: flex; flex-direction: column; gap: 18px; padding: 16px 18px 10px; }
          .preview { order: -1; align-self: center; flex: none; }
          .phone { width: min(26vh, 190px); }
          .start { max-width: none; }
          .start h1 { font-size: 34px; }
          .strip { gap: 8px; }
          .card { flex: 0 0 96px; }
        }
        @media (max-height: 720px) {
          .main.empty { padding-top: 20px; }
          .start h1 { font-size: 34px; }
          .start-sub { margin-bottom: 18px; }
          .big { padding: 13px 18px; }
        }

        .wact { display: flex; gap: 12px; font-size: 12px; }
        .wact a, .wact button { color: var(--gold); background: none; border: 0; font: inherit; cursor: pointer; }
      `}</style>
    </div>
  );
}
















