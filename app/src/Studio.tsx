import { useEffect, useMemo, useRef, useState } from 'react';
import { planScript, renderVideo } from './lib/render';
import type { ThemeName, PlanBeat } from './lib/types';
import {
  createGen, deleteGen, getMe, listHistory, login, logout, redeem, register,
  uploadVideo, videoUrl, type GenItem, type Me,
} from './lib/account';
import { exportJianyingDraft } from './lib/jianying';

type Choice = ThemeName | 'auto';

const STYLES: { id: Choice; name: string; thumb?: string }[] = [
  { id: 'auto', name: '自动' },
  { id: 'poster', name: '大字报', thumb: 'style-thumbs/poster.jpg' },
  { id: 'magazine', name: '杂志', thumb: 'style-thumbs/magazine.jpg' },
  { id: 'dashboard', name: '数据', thumb: 'style-thumbs/dashboard.jpg' },
  { id: 'newsroom', name: '播报', thumb: 'style-thumbs/newsroom.jpg' },
  { id: 'ledger', name: '财报', thumb: 'style-thumbs/ledger.jpg' },
  { id: 'marker', name: '白板', thumb: 'style-thumbs/marker.jpg' },
  { id: 'swiss', name: '极简', thumb: 'style-thumbs/swiss.jpg' },
  { id: 'terminal', name: '终端', thumb: 'style-thumbs/terminal.jpg' },
  { id: 'broadsheet', name: '报纸', thumb: 'style-thumbs/broadsheet.jpg' },
  { id: 'cover', name: '封面', thumb: 'style-thumbs/cover.jpg' },
  { id: 'reel', name: '胶片', thumb: 'style-thumbs/reel.jpg' },
  { id: 'news', name: '新闻' },
  { id: 'night', name: '夜行' },
];

const VOICES = [
  { id: 'zh-CN-YunxiNeural', name: '云希 · 男声 · 年轻' },
  { id: 'zh-CN-YunyangNeural', name: '云扬 · 男声 · 播音' },
  { id: 'zh-CN-XiaoxiaoNeural', name: '晓晓 · 女声 · 温和' },
  { id: 'zh-CN-XiaoyiNeural', name: '晓伊 · 女声 · 活泼' },
  { id: 'zh-CN-YunjianNeural', name: '云健 · 男声 · 厚实' },
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
  if (/(考试|成绩|孩子|提分|上课|家长)/.test(text)) return 'newsroom';
  return 'poster';
}

/** 生成前用句子长度估一个时间轴，让底部轨道一直是"活的" */
function draftScenes(text: string) {
  const parts = text.split(/[。！？\n]/).map((s) => s.trim()).filter(Boolean).slice(0, 12);
  return parts.map((p) => ({ text: p, duration: Math.max(1.6, Math.round(p.length / 4.6)) }));
}

function fmt(t: number) {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export default function Studio() {
  const [text, setText] = useState('');
  const [choice, setChoice] = useState<Choice>('auto');
  const [broll, setBroll] = useState(false);
  const [music, setMusic] = useState(true);
  const [voice, setVoice] = useState(VOICES[0].id);
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
  const [jianyingMsg, setJianyingMsg] = useState('');
  const [zipUrl, setZipUrl] = useState('');
  const [playId, setPlayId] = useState('');
  const [tab, setTab] = useState<'text' | 'style' | 'voice' | 'works'>('text');
  const [selectedScene, setSelectedScene] = useState(0);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [now, setNow] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);

  const refresh = async () => {
    try { setMe(await getMe()); } catch { /* 离线也能用 */ }
    try { setHistory((await listHistory()).items); } catch { /* 同上 */ }
  };
  useEffect(() => { void refresh(); }, []);

  const chars = text.trim().length;
  const est = Math.max(0, Math.round(chars / 4.6));
  const scenes = useMemo(() => {
    if (plan?.length) return plan.map((b) => ({ text: b.text, duration: Math.max(1.4, Math.round(b.text.length / 4.6)) }));
    return draftScenes(text);
  }, [plan, text]);
  const totalDur = scenes.reduce((n, s) => n + s.duration, 0) || 1;

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
    setErr(null); setUrl(null); setPct(0); setSecs(null); setSaveState('idle');
    const t0 = performance.now();
    const theme = choice === 'auto' ? pickTheme(src) : choice;
    try {
      setStage('拆稿');
      const plan = await planScript(src);
      setPlan(plan);
      const title = src.split(/[。！？\n]/)[0].slice(0, 14);
      const blob = await renderVideo(plan, theme, title, ({ stage: s, percent }) => {
        setStage(s); setPct(percent);
      }, broll, music, voice);
      setSecs(Math.round((performance.now() - t0) / 1000));
      setUrl(URL.createObjectURL(blob));
      setPct(100);
      setSaveState('saving');
      try {
        const rec = await createGen({ title, text: src, theme, duration: Math.round(plan.length * 2.5) });
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
      a.href = u; a.download = `${title}-剪映草稿.zip`; a.rel = 'noopener';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(u), 5000);
      setJianyingMsg(`草稿已生成 · ${(r.zipBlob.size / 1024).toFixed(0)} KB`);
    } catch (e) {
      setJianyingMsg(`导出失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) { void v.play(); } else { v.pause(); }
  };

  const seek = (ratio: number) => {
    const v = videoRef.current;
    if (!v || !v.duration) return;
    v.currentTime = Math.max(0, Math.min(1, ratio)) * v.duration;
  };

  return (
    <div className="studio">
      {/* 顶栏 */}
      <header className="top">
        <div className="brand">GetCut<span>studio</span></div>
        <div className="project">
          <b>{text.trim().split(/[。！？\n]/)[0].slice(0, 16) || '未命名项目'}</b>
          <span>{running ? `${stage} ${pct}%` : url ? '已出片' : '草稿'}</span>
        </div>
        <div className="top-act">
          <span className="quota">{me ? (me.pro ? '已买断' : `免费剩 ${me.remaining} 条`) : '免费 3 条'}</span>
          {me && !me.pro ? <button className="tlink" onClick={() => setShowBuy(true)}>买断 ¥599</button> : null}
          {me?.loggedIn
            ? <button className="tlink" onClick={async () => { await logout(); await refresh(); }}>{me.email} · 退出</button>
            : <button className="tlink" onClick={() => { setAuthMode('login'); setShowAuth(true); }}>登录</button>}
          <button className="primary" onClick={run} disabled={running}>
            {running ? `${pct}%` : '生成视频'}
          </button>
        </div>
      </header>

      <div className="body">
        {/* 左侧栏 */}
        <nav className="rail">
          {([
            ['text', '文案', 'M4 5h16M4 10h16M4 15h10'],
            ['style', '长相', 'M4 5h7v7H4zM13 5h7v7h-7zM4 14h7v6H4zM13 14h7v6h-7z'],
            ['voice', '声音', 'M4 12h3l3-6 3 12 3-6h4'],
            ['works', '作品', 'M4 6h16v12H4zM4 10h16'],
          ] as const).map(([id, label, d]) => (
            <button key={id} className={`rail-btn ${tab === id ? 'on' : ''}`} onClick={() => setTab(id)} title={label}>
              <svg viewBox="0 0 24 24" width="20" height="20"><path d={d} fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
              <span>{label}</span>
            </button>
          ))}
        </nav>

        {/* 画布 */}
        <main className="stage">
          <div className="canvas" onClick={togglePlay}>
            {url ? (
              <video
                ref={videoRef}
                src={url}
                playsInline
                onTimeUpdate={(e) => { const v = e.currentTarget; setNow(v.currentTime); setDur(v.duration || 0); }}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
              />
            ) : (
              <div className="placeholder">
                <img src="samples/poster.jpg" alt="" />
              </div>
            )}
            {!url && !running ? null : null}
            {running ? <div className="hud">{stage} · {pct}%</div> : null}
          </div>

          <div className="transport">
            <button className="play" onClick={togglePlay} disabled={!url} aria-label="播放">
              {playing ? (
                <svg viewBox="0 0 24 24" width="16" height="16"><path d="M7 5h3v14H7zM14 5h3v14h-3z" fill="currentColor" /></svg>
              ) : (
                <svg viewBox="0 0 24 24" width="16" height="16"><path d="M8 5l11 7-11 7z" fill="currentColor" /></svg>
              )}
            </button>
            <span className="tc">{fmt(now)} / {fmt(dur || totalDur)}</span>
            <div className="scrub" onClick={(e) => {
              const r = (e.currentTarget.getBoundingClientRect());
              seek((e.clientX - r.left) / r.width);
            }}>
              <i style={{ width: `${dur ? (now / dur) * 100 : 0}%` }} />
            </div>
            <span className="tc dim">1080×1920 · 30fps</span>
          </div>
        </main>

        {/* 右侧检查器 */}
        <aside className="inspector">
          <div className="ins-head">
            <b>{tab === 'text' ? '文案' : tab === 'style' ? '长相' : tab === 'voice' ? '声音' : '作品'}</b>
            {tab === 'text' ? <button className="tlink" onClick={() => setText(DEMO)}>插入示例</button> : null}
          </div>

          {tab === 'text' ? (
            <>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={'把口播稿粘在这里。\n\n想开一家小店，你最怕的是什么？……'}
              />
              <div className="meta-row">
                <span>{chars ? `${chars} 字 · 约 ${est} 秒` : '建议 200~600 字'}</span>
                <span>{scenes.length} 个镜头</span>
              </div>
            </>
          ) : null}

          {tab === 'style' ? (
            <div className="thumbs">
              {STYLES.map((s) => (
                <button key={s.id} className={`thumb ${choice === s.id ? 'on' : ''}`} onClick={() => setChoice(s.id)}>
                  {s.thumb ? <img src={s.thumb} alt="" /> : <span className="nothumb" />}
                  <i>{s.name}</i>
                </button>
              ))}
            </div>
          ) : null}

          {tab === 'voice' ? (
            <div className="voices">
              {VOICES.map((v) => (
                <button key={v.id} className={`voice-row ${voice === v.id ? 'on' : ''}`} onClick={() => setVoice(v.id)}>
                  <svg viewBox="0 0 24 24" width="16" height="16"><path d="M4 12h3l3-6 3 12 3-6h4" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
                  <span>{v.name}</span>
                </button>
              ))}
              <label className="check"><input type="checkbox" checked={music} onChange={(e) => setMusic(e.target.checked)} />自动配乐（人声出现时压低）</label>
              <label className="check"><input type="checkbox" checked={broll} onChange={(e) => setBroll(e.target.checked)} />插入实拍空镜（慢，慎用）</label>
            </div>
          ) : null}

          {tab === 'works' ? (
            <div className="works">
              {history.length === 0 ? <p className="dim">还没有作品。生成第一条后会出现在这里。</p> : null}
              {history.map((g) => (
                <div key={g.id} className="work">
                  <b>{g.title || '未命名'}</b>
                  <span className="dim">
                    {new Date(g.created).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    {g.duration ? ` · ${g.duration} 秒` : ''}
                  </span>
                  <div className="work-act">
                    {g.hasVideo ? (
                      <>
                        <button className="tlink" onClick={() => setPlayId(g.id)}>播放</button>
                        <a className="tlink" href={videoUrl(g.id)} download={`${g.title || 'getcut'}.mp4`}>下载</a>
                      </>
                    ) : <span className="dim">未存成片</span>}
                    <button className="tlink danger" onClick={async () => { await deleteGen(g.id); await refresh(); }}>删除</button>
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          {err ? <p className="err">{err}</p> : null}
          {url ? (
            <div className="out">
              <a className="primary wide" href={url} download="getcut.mp4">下载 MP4</a>
              <button className="ghost" onClick={exportDraft}>剪映草稿</button>
              <button className="ghost" onClick={() => { setUrl(null); setPct(0); setStage(''); setSaveState('idle'); setZipUrl(''); setJianyingMsg(''); }}>重做</button>
              {jianyingMsg ? <p className="dim">{jianyingMsg}{zipUrl ? <> · <a href={zipUrl} download="getcut-剪映草稿.zip">保存 zip</a></> : null}</p> : null}
              <p className="dim">
                {secs ? `${secs} 秒渲染 · ` : ''}
                {saveState === 'saved' ? '已存作品库' : saveState === 'saving' ? '存档中…' : saveState === 'limited' ? '额度用尽，仅可下载' : saveState === 'error' ? '存档失败' : ''}
              </p>
            </div>
          ) : null}
        </aside>
      </div>

      {/* 时间轴 */}
      <section className="timeline">
        <div className="tl-head">
          <b>时间轴</b>
          <span>{scenes.length} 个镜头 · 约 {Math.round(totalDur)} 秒</span>
          {running ? <span className="tl-run">{stage} {pct}%</span> : null}
        </div>
        <div className="tl-body">
          <div className="tl-lane-label">画面</div>
          <div className="tl-lane">
            {scenes.slice(0, 12).map((s, i) => (
              <button
                key={i}
                className={`clip ${selectedScene === i ? 'on' : ''}`}
                style={{ flexGrow: s.duration }}
                onClick={() => setSelectedScene(i)}
                title={s.text}
              >
                <span>{s.text.slice(0, 12)}</span>
              </button>
            ))}
            {!scenes.length ? <div className="clip empty">等待文案</div> : null}
          </div>
          <div className="tl-lane-label">字幕</div>
          <div className="tl-lane texts">
            {scenes.slice(0, 12).map((s, i) => (
              <button key={i} className="sub" style={{ flexGrow: s.duration }} onClick={() => setSelectedScene(i)}>
                {s.text.slice(0, 16)}
              </button>
            ))}
            {!scenes.length ? <div className="sub empty">—</div> : null}
          </div>
        </div>
      </section>

      {/* 弹窗 */}
      {showAuth ? (
        <div className="mask" onClick={() => setShowAuth(false)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <p className="kicker">{authMode === 'login' ? '登录' : '注册'}</p>
            <h3>用邮箱收好你的作品</h3>
            <input type="email" placeholder="you@example.com" value={authEmail} onChange={(e) => setAuthEmail(e.target.value)} />
            <input type="password" placeholder="密码，至少 6 位" value={authPass}
              onChange={(e) => setAuthPass(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void doAuth(); }} />
            {authErr ? <p className="err">{authErr}</p> : null}
            <button className="primary wide" onClick={doAuth}>{authMode === 'login' ? '登录' : '注册并登录'}</button>
            <button className="tlink" onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthErr(''); }}>
              {authMode === 'login' ? '没有账号，注册' : '已有账号，去登录'}
            </button>
          </div>
        </div>
      ) : null}

      {showBuy ? (
        <div className="mask" onClick={() => setShowBuy(false)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <p className="kicker">599 一次买断</p>
            <h3>输入卡密，永久解锁</h3>
            {me?.loggedIn ? null : <p className="err">先登录，卡密会绑到账号</p>}
            <input placeholder="GC-XXXX-XXXX-XXXX" value={buyCode} onChange={(e) => { setBuyCode(e.target.value); setBuyMsg(''); }} />
            {buyMsg ? <p className={buyMsg.startsWith('已') ? 'ok' : 'err'}>{buyMsg}</p> : null}
            <button className="primary wide" onClick={async () => {
              if (!me?.loggedIn) { setShowBuy(false); setShowAuth(true); return; }
              try {
                const r = await redeem(buyCode);
                setBuyMsg(r.already ? '这张已用过，权益已生效' : '已解锁');
                await refresh();
              } catch (e) { setBuyMsg(e instanceof Error ? e.message : String(e)); }
            }}>{me?.loggedIn ? '核销' : '先去登录'}</button>
            <p className="dim">还没买？转账后把邮箱发给客服，人工发码。</p>
          </div>
        </div>
      ) : null}

      {playId ? (
        <div className="mask" onClick={() => setPlayId('')}>
          <div className="player" onClick={(e) => e.stopPropagation()}>
            <video src={videoUrl(playId)} controls autoPlay playsInline />
          </div>
        </div>
      ) : null}

      <style>{`
        :root {
          --bg: #0B0B0C;
          --panel: #131316;
          --panel-2: #1A1A1E;
          --line: rgba(255,255,255,.08);
          --line-2: rgba(255,255,255,.16);
          --ink: #ECECEE;
          --dim: #8A8A93;
          --gold: #F0B429;
        }
        * { box-sizing: border-box; }
        html, body, #root { height: 100%; }
        body { margin: 0; background: var(--bg); color: var(--ink);
          font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif; overflow: hidden; }
        .studio { height: 100vh; display: flex; flex-direction: column; }

        .top { height: 56px; flex: none; display: flex; align-items: center; gap: 20px;
          padding: 0 16px; border-bottom: 1px solid var(--line); background: var(--panel); }
        .brand { font-weight: 900; font-size: 15px; letter-spacing: .02em; }
        .brand span { color: var(--gold); font-weight: 500; margin-left: 4px; font-size: 12px; }
        .project { flex: 1; display: flex; align-items: baseline; gap: 10px; min-width: 0; }
        .project b { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .project span { font-size: 11px; color: var(--dim); }
        .top-act { display: flex; align-items: center; gap: 14px; font-size: 12px; color: var(--dim); }
        .quota { letter-spacing: .04em; }
        .tlink { background: none; border: 0; padding: 0; font: inherit; color: var(--dim); cursor: pointer; }
        .tlink:hover { color: var(--ink); }
        .tlink.danger { color: #ff8f7a; }
        .primary { background: var(--gold); color: #171207; border: 0; border-radius: 6px;
          padding: 9px 16px; font-size: 13px; font-weight: 700; cursor: pointer; letter-spacing: .04em; }
        .primary:hover { filter: brightness(1.06); }
        .primary:disabled { opacity: .6; cursor: not-allowed; }
        .primary.wide { width: 100%; padding: 11px 16px; }
        .ghost { background: transparent; border: 1px solid var(--line-2); color: var(--ink);
          border-radius: 6px; padding: 9px 12px; font-size: 12px; cursor: pointer; }
        .ghost:hover { border-color: var(--gold); }

        .body { flex: 1; display: grid; grid-template-columns: 68px minmax(0,1fr) 320px; min-height: 0; }

        .rail { border-right: 1px solid var(--line); display: flex; flex-direction: column; align-items: center;
          padding-top: 12px; gap: 6px; background: var(--panel); }
        .rail-btn { width: 52px; height: 54px; display: grid; place-items: center; gap: 3px;
          background: none; border: 0; border-radius: 8px; color: var(--dim); cursor: pointer; font-size: 10px; }
        .rail-btn:hover { background: var(--panel-2); color: var(--ink); }
        .rail-btn.on { background: var(--panel-2); color: var(--gold); }

        .stage { min-width: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
          background:
            radial-gradient(1200px 600px at 50% 0%, rgba(255,255,255,.03), transparent 70%),
            var(--bg);
          padding: 18px 24px 8px; gap: 12px; }
        .canvas { position: relative; height: min(62vh, 560px); aspect-ratio: 9/16; background: #000;
          border-radius: 8px; overflow: hidden; box-shadow: 0 20px 60px -30px #000, 0 0 0 1px var(--line-2);
          cursor: pointer; display: grid; place-items: center; }
        .canvas video { width: 100%; height: 100%; object-fit: cover; display: block; }
        .placeholder { position: absolute; inset: 0; display: grid; place-items: center; }
        .placeholder img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .45; }
        .placeholder::after { content: ''; position: absolute; inset: 24px; border: 1px dashed rgba(255,255,255,.18); pointer-events: none; }
        .ph-meta { position: relative; display: grid; gap: 6px; justify-items: center; }
        .ph-meta span { font-size: 22px; letter-spacing: .18em; color: rgba(255,255,255,.7); }
        .ph-meta em { font-style: normal; font-size: 12px; color: rgba(255,255,255,.6); }
        .hud { position: absolute; left: 10px; bottom: 10px; background: rgba(0,0,0,.6); color: #fff;
          font-size: 11px; padding: 4px 8px; border-radius: 4px; }

        .transport { width: min(62vh * 9/16, 560px * 9/16, 100%); max-width: 340px; display: flex; align-items: center; gap: 10px; }
        .play { width: 30px; height: 30px; border-radius: 50%; border: 1px solid var(--line-2);
          background: var(--panel-2); color: var(--ink); display: grid; place-items: center; cursor: pointer; }
        .play:disabled { opacity: .4; cursor: default; }
        .tc { font-size: 11px; color: var(--dim); font-variant-numeric: tabular-nums; }
        .scrub { flex: 1; height: 4px; background: rgba(255,255,255,.1); border-radius: 2px; cursor: pointer; }
        .scrub i { display: block; height: 100%; width: 0; background: var(--gold); border-radius: 2px; }

        .inspector { border-left: 1px solid var(--line); background: var(--panel); padding: 14px;
          overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
        .ins-head { display: flex; align-items: center; justify-content: space-between; }
        .ins-head b { font-size: 13px; letter-spacing: .06em; }
        textarea { width: 100%; min-height: 220px; resize: vertical; background: var(--panel-2); color: var(--ink);
          border: 1px solid var(--line); border-radius: 8px; padding: 12px; font: inherit; font-size: 13px;
          line-height: 1.9; outline: none; }
        textarea:focus { border-color: var(--gold); }
        .meta-row { display: flex; justify-content: space-between; font-size: 11px; color: var(--dim); }

        .thumbs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
        .thumb { position: relative; padding: 0; border: 1px solid var(--line); border-radius: 6px; overflow: hidden;
          background: var(--panel-2); cursor: pointer; aspect-ratio: 9/16; }
        .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; opacity: .8; }
        .thumb .nothumb { display: block; width: 100%; height: 100%; background: linear-gradient(160deg, #2A2A31, #17171B); }
        .thumb i { position: absolute; left: 0; right: 0; bottom: 0; font-style: normal; font-size: 10px;
          padding: 3px 0; text-align: center; background: rgba(0,0,0,.55); color: #fff; }
        .thumb:hover { border-color: var(--line-2); }
        .thumb.on { border-color: var(--gold); box-shadow: 0 0 0 1px var(--gold); }
        .thumb.on img { opacity: 1; }

        .voices { display: grid; gap: 6px; }
        .voice-row { display: flex; align-items: center; gap: 10px; background: var(--panel-2);
          border: 1px solid var(--line); border-radius: 6px; padding: 9px 10px; color: var(--dim);
          font-size: 12px; cursor: pointer; text-align: left; }
        .voice-row:hover { color: var(--ink); }
        .voice-row.on { border-color: var(--gold); color: var(--ink); }
        .check { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--dim); margin-top: 4px; }
        .check input { accent-color: var(--gold); }

        .works { display: grid; gap: 10px; }
        .work { border: 1px solid var(--line); border-radius: 6px; padding: 10px; display: grid; gap: 4px; }
        .work b { font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .work-act { display: flex; gap: 12px; margin-top: 2px; font-size: 11px; }

        .out { display: grid; gap: 8px; border-top: 1px solid var(--line); padding-top: 12px; }
        .dim { font-size: 11px; color: var(--dim); line-height: 1.6; }
        .err { font-size: 12px; color: #ff8f7a; margin: 0; }
        .ok { font-size: 12px; color: #7ed69b; margin: 0; }

        .timeline { flex: none; height: 132px; border-top: 1px solid var(--line); background: var(--panel);
          padding: 8px 14px 10px; display: flex; flex-direction: column; gap: 6px; }
        .tl-head { display: flex; align-items: baseline; gap: 12px; font-size: 11px; color: var(--dim); }
        .tl-head b { color: var(--ink); font-size: 12px; letter-spacing: .06em; }
        .tl-run { color: var(--gold); margin-left: auto; }
        .tl-body { flex: 1; display: grid; grid-template-columns: 44px 1fr; gap: 4px 8px; min-height: 0; }
        .tl-lane-label { font-size: 10px; color: var(--dim); align-self: center; }
        .tl-lane { display: flex; gap: 3px; min-width: 0; overflow: hidden; }
        .clip { flex: 1 1 0; min-width: 0; background: linear-gradient(180deg, #2C2C34, #222229);
          border: 1px solid var(--line); border-radius: 4px; color: #C9C9D1; font-size: 10px;
          padding: 4px 6px; text-align: left; overflow: hidden; white-space: nowrap; cursor: pointer; }
        .clip.on { border-color: var(--gold); color: var(--ink); }
        .clip span { display: block; overflow: hidden; text-overflow: ellipsis; }
        .texts .sub { flex: 1 1 0; min-width: 0; background: rgba(240,180,41,.10); border: 1px solid rgba(240,180,41,.22);
          color: #D9C79B; font-size: 10px; border-radius: 4px; padding: 3px 6px; text-align: left;
          overflow: hidden; white-space: nowrap; cursor: pointer; }
        .clip.empty, .sub.empty { flex: 1; color: var(--dim); background: transparent; border-style: dashed; }

        .mask { position: fixed; inset: 0; background: rgba(0,0,0,.62); display: grid; place-items: center; z-index: 40; }
        .dialog { width: 100%; max-width: 380px; background: var(--panel); border: 1px solid var(--line-2);
          border-radius: 12px; padding: 22px; display: grid; gap: 10px; }
        .dialog h3 { margin: 0 0 4px; font-size: 18px; }
        .dialog input { background: var(--panel-2); border: 1px solid var(--line); border-radius: 6px;
          color: var(--ink); padding: 10px 12px; font: inherit; font-size: 13px; outline: none; }
        .dialog input:focus { border-color: var(--gold); }
        .kicker { margin: 0; font-size: 10px; letter-spacing: .18em; color: var(--gold); }
        .player { width: min(360px, 90vw); }
        .player video { width: 100%; border-radius: 8px; background: #000; }

        @media (max-width: 1080px) {
          .body { grid-template-columns: 56px minmax(0,1fr) 280px; }
          .canvas { height: min(52vh, 460px); }
        }
      `}</style>
    </div>
  );
}


