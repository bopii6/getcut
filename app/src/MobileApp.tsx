import { useEffect, useMemo, useRef, useState } from 'react';
import { planScript, renderVideo } from './lib/render';
import { pickAudioConfig } from './lib/audio';
import type { ThemeName, PlanBeat } from './lib/types';
import {
  createGen, deleteGen, getMe, listHistory, login, logout, redeem, register,
  uploadVideo, videoUrl, type GenItem, type Me,
} from './lib/account';
import { exportJianyingDraft } from './lib/jianying';

type Choice = ThemeName | 'auto';
type Step = 'write' | 'style' | 'run' | 'done';

const STYLES: { id: Choice; name: string; hint: string; thumb?: string }[] = [
  { id: 'poster', name: '大字报', hint: '黑金 · 一屏一句', thumb: 'style-thumbs/poster.jpg' },
  { id: 'magazine', name: '杂志', hint: '暖纸 · 印章红', thumb: 'style-thumbs/magazine.jpg' },
  { id: 'dashboard', name: '数据', hint: '深蓝 · 数字图表', thumb: 'style-thumbs/dashboard.jpg' },
  { id: 'newsroom', name: '新闻播报', hint: 'LIVE 条 · 信息板', thumb: 'style-thumbs/newsroom.jpg' },
  { id: 'ledger', name: '财报', hint: '巨数字 · 指标' },
  { id: 'marker', name: '白板', hint: '马克笔 · 手写', thumb: 'style-thumbs/marker.jpg' },
  { id: 'swiss', name: '极简', hint: '栅格 · 大留白', thumb: 'style-thumbs/swiss.jpg' },
  { id: 'terminal', name: '终端', hint: '黑底绿字', thumb: 'style-thumbs/terminal.jpg' },
  { id: 'broadsheet', name: '报纸', hint: '报头 · 双栏', thumb: 'style-thumbs/broadsheet.jpg' },
  { id: 'cover', name: '封面', hint: '刊名 · 条形码', thumb: 'style-thumbs/cover.jpg' },
  { id: 'reel', name: '胶片', hint: '齿孔 · 颗粒', thumb: 'style-thumbs/reel.jpg' },
  { id: 'news', name: '新闻', hint: '白底红条', thumb: 'style-thumbs/news.jpg' },
  { id: 'night', name: '夜行', hint: '深紫冷光', thumb: 'style-thumbs/night.jpg' },
];

const VOICES = [
  { id: 'zh-CN-YunxiNeural', name: '云希', desc: '男声 · 年轻' },
  { id: 'zh-CN-YunyangNeural', name: '云扬', desc: '男声 · 播音' },
  { id: 'zh-CN-XiaoxiaoNeural', name: '晓晓', desc: '女声 · 温和' },
  { id: 'zh-CN-XiaoyiNeural', name: '晓伊', desc: '女声 · 活泼' },
  { id: 'zh-CN-YunjianNeural', name: '云健', desc: '男声 · 厚实' },
];

const STEPS = ['读稿', '配音', '画帧', '合成', '封装'];

function pickTheme(text: string): ThemeName {
  if (/\d+\s*(万|元|%|倍)/.test(text) || /(回本|投入|成本|流水)/.test(text)) return 'dashboard';
  if (/(合同|条款|判决|律师|赔偿|仲裁)/.test(text)) return 'magazine';
  if (/(考试|成绩|孩子|提分|上课|家长)/.test(text)) return 'newsroom';
  return 'poster';
}

const DEMO = `想开一家小店，你最怕的是什么？不是没客人，是钱投进去，三个月就撑不住。
今天讲三个数，你记下来再去谈加盟。
第一个数，前期总投入。加盟费、保证金、装修、设备、首批物料，加起来才是真数。
第二个数，回本周期。总部说八个月，你就按十二个月算。
第三个数，日均流水。别问总部要，去他现有的店里蹲三天。
把品牌名发给我，我帮你把这三个数拆开算一遍。`;

export default function MobileApp() {
  const [step, setStep] = useState<Step>('write');
  const [text, setText] = useState('');
  const [choice, setChoice] = useState<Choice>('auto');
  const [voice, setVoice] = useState(VOICES[0].id);
  const [music, setMusic] = useState(true);
  const [srcMode, setSrcMode] = useState<'paste' | 'ai' | 'link'>('paste');
  const [topic, setTopic] = useState('');
  const [linkUrl, setLinkUrl] = useState('');
  const [industry, setIndustry] = useState('餐饮加盟');
  const [writing, setWriting] = useState(false);
  const [writeMsg, setWriteMsg] = useState('');

  const [stage, setStage] = useState('');
  const [pct, setPct] = useState(0);
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [secs, setSecs] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const busy = useRef(false);
  const liveRef = useRef<HTMLDivElement | null>(null);
  const liveCanvas = useMemo(() => document.createElement('canvas'), []);
  const [plan, setPlan] = useState<PlanBeat[] | null>(null);

  const [me, setMe] = useState<Me | null>(null);
  const [history, setHistory] = useState<GenItem[]>([]);
  const [sheet, setSheet] = useState<'' | 'account' | 'works'>('');
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authEmail, setAuthEmail] = useState('');
  const [authPass, setAuthPass] = useState('');
  const [authErr, setAuthErr] = useState('');
  const [buyCode, setBuyCode] = useState('');
  const [buyMsg, setBuyMsg] = useState('');
  const [showBuy, setShowBuy] = useState(false);

  const refresh = async () => {
    try { setMe(await getMe()); } catch { /* 离线可用 */ }
    try { setHistory((await listHistory()).items); } catch { /* 同上 */ }
  };
  useEffect(() => { void refresh(); }, []);

  // 进页面就自检：设备能不能编出声，不能的话提前讲清楚，别等出片才发现没声
  const [audioOk, setAudioOk] = useState<boolean | null>(null);
  const [audioDesc, setAudioDesc] = useState('检测中…');
  useEffect(() => {
    let alive = true;
    void pickAudioConfig().then((c) => {
      if (!alive) return;
      setAudioOk(Boolean(c));
      setAudioDesc(c ? `${(c.sampleRate / 1000).toFixed(1)}k · ${c.numberOfChannels === 2 ? '立体声' : '单声道'}` : '不可用');
    });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (running && liveRef.current) liveRef.current.replaceChildren(liveCanvas);
  }, [running, liveCanvas]);

  const chars = text.trim().length;
  const est = Math.max(0, Math.round(chars / 4.6));
  const stepIndex = /拆稿|准备|读稿/.test(stage) ? 0 : /配音/.test(stage) ? 1
    : /画帧|编码器/.test(stage) ? 2 : /音轨|合成/.test(stage) ? 3 : /完成/.test(stage) ? 4 : 0;

  async function genScript() {
    if (topic.trim().length < 2) { setWriteMsg('先写个主题，比如「加盟回本怎么算」'); return; }
    setWriting(true); setWriteMsg('');
    try {
      const res = await fetch('/api/script', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ topic: topic.trim(), industry }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '写稿失败');
      setText(data.text); setWriteMsg('写好了，可以直接改'); setSrcMode('paste');
    } catch (e) { setWriteMsg(e instanceof Error ? e.message : String(e)); }
    finally { setWriting(false); }
  }

  async function genLink() {
    if (!/^https?:\/\//i.test(linkUrl.trim())) { setWriteMsg('先粘一个链接'); return; }
    setWriting(true); setWriteMsg('');
    try {
      const res = await fetch('/api/link', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ url: linkUrl.trim(), industry }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '抓取失败');
      setText(data.text); setWriteMsg('改好了，可以直接改'); setSrcMode('paste');
    } catch (e) { setWriteMsg(e instanceof Error ? e.message : String(e)); }
    finally { setWriting(false); }
  }

  async function doAuth() {
    setAuthErr('');
    try {
      if (authMode === 'register') await register(authEmail.trim(), authPass);
      else await login(authEmail.trim(), authPass);
      setAuthPass('');
      await refresh();
    } catch (e) { setAuthErr(e instanceof Error ? e.message : String(e)); }
  }

  async function run() {
    if (busy.current) return;
    const src = text.trim();
    if (src.length < 20) { setErr('再写几句，至少 20 个字'); setStep('write'); return; }
    busy.current = true;
    setRunning(true); setStep('run'); setErr(null); setUrl(null); setPct(0); setSecs(null);
    const t0 = performance.now();
    const theme = choice === 'auto' ? pickTheme(src) : choice;
    try {
      setStage('拆稿');
      const planned = await planScript(src);
      setPlan(planned);
      const title = src.split(/[。！？\n]/)[0].slice(0, 14);
      const blob = await renderVideo(planned, theme, title, ({ stage: s, percent }) => {
        setStage(s); setPct(percent);
      }, false, music, voice, '', liveCanvas);
      setSecs(Math.round((performance.now() - t0) / 1000));
      setUrl(URL.createObjectURL(blob));
      setPct(100);
      setStep('done');
      try {
        const rec = await createGen({ title, text: src, theme, duration: Math.round(planned.length * 2.5) });
        await uploadVideo(rec.id, blob);
        await refresh();
      } catch { /* 额度用完也能下载 */ }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setStep('style');
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
    <div className="m">
      <header className="mbar">
        <div className="mbrand">GetCut</div>
        <div className="mright">
          <span className="mquota">{free}</span>
          <button className="mavatar" onClick={() => setSheet('account')}>
            {me?.loggedIn ? (me.email || 'U').slice(0, 1).toUpperCase() : '登'}
          </button>
        </div>
      </header>

      {audioOk === false ? (
        <div className="merr">这台浏览器不支持音频编码，出片会没有声音。请换 Chrome 电脑，或更新系统后重试。</div>
      ) : null}
      {err ? <div className="merr">{err}</div> : null}

      {step === 'write' ? (
        <div className="mpage hascta">
          <h1>把一段文案<br />做成能发的片</h1>
          <p className="msub">粘稿子，或让 AI 帮你写。竖屏 1080×1920，直接发抖音。</p>

          <div className="mseg">
            <button className={srcMode === 'paste' ? 'on' : ''} onClick={() => setSrcMode('paste')}>粘贴</button>
            <button className={srcMode === 'ai' ? 'on' : ''} onClick={() => setSrcMode('ai')}>AI 写</button>
            <button className={srcMode === 'link' ? 'on' : ''} onClick={() => setSrcMode('link')}>链接</button>
          </div>

          {srcMode === 'ai' ? (
            <div className="mbox">
              <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="想讲什么？如：加盟回本怎么算" />
              <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
                <option>餐饮加盟</option><option>律师/法律服务</option><option>教培/教育</option>
                <option>本地生活</option><option>美业/医美</option><option>通用</option>
              </select>
              <button className="mbtn ghost" onClick={genScript} disabled={writing}>
                {writing ? '正在写…' : '写一篇给我'}
              </button>
            </div>
          ) : null}

          {srcMode === 'link' ? (
            <div className="mbox">
              <input value={linkUrl} onChange={(e) => setLinkUrl(e.target.value)} placeholder="粘贴公众号 / 新闻链接" inputMode="url" />
              <button className="mbtn ghost" onClick={genLink} disabled={writing}>
                {writing ? '抓取中…' : '抓取并改写'}
              </button>
            </div>
          ) : null}

          {writeMsg ? <p className="mmsg">{writeMsg}</p> : null}

          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={'把口播稿粘在这里。\n\n不知道写什么？点上面的「AI 写」。'}
          />
          <div className="mmeta">
            <span>{chars ? `${chars} 字 · 约 ${est} 秒` : '建议 200~600 字'}</span>
            <button onClick={() => setText(DEMO)}>用示例</button>
          </div>

          <div className="mbottom">
            <button className="mbtn" onClick={() => setStep('style')} disabled={chars < 20}>
              {chars < 20 ? '先写点文案' : '下一步：选模板'}
            </button>
          </div>
        </div>
      ) : null}

      {step === 'style' ? (
        <div className="mpage hascta">
          <div className="mhead">
            <button className="mback" onClick={() => setStep('write')}>‹</button>
            <b>选一个长相</b>
            <span>{STYLES.length} 套</span>
          </div>
          <p className="msub">不同行业适合不同模板，选错了重来一次要几分钟。</p>

          <div className="mgrid">
            {STYLES.map((s) => (
              <button key={s.id} className={`mcard ${choice === s.id ? 'on' : ''}`} onClick={() => setChoice(s.id)}>
                {s.thumb ? <img src={s.thumb} alt="" /> : <span className="mnothumb" />}
                <b>{s.name}</b>
                <i>{s.hint}</i>
                {choice === s.id ? <em>✓</em> : null}
              </button>
            ))}
          </div>

          <div className="mrow">
            <label>声音</label>
            <select value={voice} onChange={(e) => setVoice(e.target.value)}>
              {VOICES.map((v) => <option key={v.id} value={v.id}>{v.name} · {v.desc}</option>)}
            </select>
          </div>
          <label className="mcheck">
            <input type="checkbox" checked={music} onChange={(e) => setMusic(e.target.checked)} />
            自动配背景音乐（说话时自动压低）
          </label>

          <div className="mbottom">
            <button className="mbtn" onClick={run} disabled={running}>
              {running ? '生成中…' : '开始生成'}
            </button>
          </div>
        </div>
      ) : null}

      {step === 'run' ? (
        <div className="mpage run">
          <div className="mphone">
            {pct < 34 ? <img className="mposter" src="samples/poster.jpg" alt="" /> : null}
            <div className="mlive" ref={liveRef} />
            <div className="misland" />
            {pct < 34 ? <div className="mwait">正在准备…</div> : null}
          </div>
          <div className="msteps">
            {STEPS.map((s, i) => (
              <div key={s} className={`mstep ${i < stepIndex ? 'done' : i === stepIndex ? 'now' : ''}`}>
                <i>{i < stepIndex ? '✓' : i + 1}</i>
                <span>{s}</span>
              </div>
            ))}
          </div>
          <div className="mprogress"><i style={{ width: `${pct}%` }} /></div>
          <p className="mhint">{pct}% · 别关掉页面，画帧时能看到画面</p>
        </div>
      ) : null}

      {step === 'done' && url ? (
        <div className="mpage">
          <div className="mhead">
            <b>做好了</b>
            <span>{secs ? `${secs} 秒` : ''}</span>
          </div>
          <div className="mvideobox">
            <video src={url} controls playsInline />
          </div>
          <div className="mactions">
            <a className="mbtn" href={url} download="getcut.mp4">下载到手机</a>
            <button className="mbtn ghost" onClick={exportDraft}>导出剪映草稿</button>
            <button className="mbtn ghost" onClick={() => { setUrl(null); setPct(0); setStep('write'); }}>
              再做一条
            </button>
          </div>
          <p className="mhint">已存进作品库（登录后换手机也能看到）</p>
        </div>
      ) : null}

      {step !== 'run' ? (
        <nav className="mnav">
          <button className={step === 'write' ? 'on' : ''} onClick={() => setStep('write')}>做片</button>
          <button onClick={() => setSheet('works')}>作品</button>
          <button onClick={() => setSheet('account')}>我的</button>
        </nav>
      ) : null}

      {sheet === 'works' ? (
        <div className="msheet" onClick={() => setSheet('')}>
          <div className="msheet-body" onClick={(e) => e.stopPropagation()}>
            <div className="msheet-head"><b>我的作品</b><button onClick={() => setSheet('')}>关闭</button></div>
            {history.length === 0 ? <p className="mmsg">还没有作品。</p> : null}
            {history.map((g) => (
              <div key={g.id} className="mwork">
                <div>
                  <b>{g.title || '未命名'}</b>
                  <span>{new Date(g.created).toLocaleDateString('zh-CN')} · {g.duration || 0} 秒</span>
                </div>
                <div className="mwork-act">
                  {g.hasVideo ? <a href={videoUrl(g.id)} download={`${g.title || 'getcut'}.mp4`}>下载</a> : null}
                  <button onClick={async () => { await deleteGen(g.id); await refresh(); }}>删</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {sheet === 'account' ? (
        <div className="msheet" onClick={() => setSheet('')}>
          <div className="msheet-body" onClick={(e) => e.stopPropagation()}>
            <div className="msheet-head"><b>我的</b><button onClick={() => setSheet('')}>关闭</button></div>
            {me?.loggedIn ? (
              <>
                <p className="memail">{me.email}</p>
                <p className="mmsg">{me.pro ? '已买断 · 不限条数' : `免费剩 ${me.remaining} 条`}</p>
                <p className="mmsg">音频编码：{audioDesc}</p>
                {!me.pro ? <button className="mbtn" onClick={() => setShowBuy(true)}>输入卡密解锁 · ¥599</button> : null}
                <button className="mbtn ghost" onClick={async () => { await logout(); await refresh(); }}>退出登录</button>
              </>
            ) : (
              <>
                <input type="email" value={authEmail} onChange={(e) => setAuthEmail(e.target.value)} placeholder="you@example.com" inputMode="email" />
                <input type="password" value={authPass} onChange={(e) => setAuthPass(e.target.value)} placeholder="密码，至少 6 位" />
                {authErr ? <p className="merr-inline">{authErr}</p> : null}
                <button className="mbtn" onClick={doAuth}>{authMode === 'login' ? '登录' : '注册并登录'}</button>
                <button className="mlink" onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthErr(''); }}>
                  {authMode === 'login' ? '没有账号，注册' : '已有账号，去登录'}
                </button>
              </>
            )}
          </div>
        </div>
      ) : null}

      {showBuy ? (
        <div className="msheet" onClick={() => setShowBuy(false)}>
          <div className="msheet-body" onClick={(e) => e.stopPropagation()}>
            <div className="msheet-head"><b>599 买断</b><button onClick={() => setShowBuy(false)}>关闭</button></div>
            <input value={buyCode} onChange={(e) => setBuyCode(e.target.value)} placeholder="GC-XXXX-XXXX-XXXX" />
            {buyMsg ? <p className="mmsg">{buyMsg}</p> : null}
            <button className="mbtn" onClick={async () => {
              try {
                const r = await redeem(buyCode);
                setBuyMsg(r.already ? '这张已用过' : '已解锁');
                await refresh();
              } catch (e) { setBuyMsg(e instanceof Error ? e.message : String(e)); }
            }}>核销</button>
            <p className="mhint">没买？转账后把邮箱发客服，人工发码。</p>
          </div>
        </div>
      ) : null}

      <style>{`
        :root { --bg:#0B0B0C; --panel:#15151A; --line:rgba(255,255,255,.12); --ink:#F2F2F4; --dim:#9C9CA6; --gold:#F0B429; }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        html, body, #root { height: 100%; }
        body { margin: 0; background: var(--bg); color: var(--ink); font-size: 16px;
          font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
          -webkit-text-size-adjust: 100%; }
        .m { min-height: 100vh; display: flex; flex-direction: column; padding-bottom: calc(72px + env(safe-area-inset-bottom)); }

        .mbar { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; justify-content: space-between;
          height: 54px; padding: 0 16px; background: rgba(11,11,12,.92); backdrop-filter: blur(10px);
          border-bottom: 1px solid var(--line); }
        .mbrand { font-weight: 900; font-size: 17px; letter-spacing: .02em; }
        .mright { display: flex; align-items: center; gap: 10px; }
        .mquota { font-size: 12px; color: var(--dim); }
        .mavatar { width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--line);
          background: var(--panel); color: var(--ink); font-size: 14px; font-weight: 800; }

        .mpage { flex: 1; padding: 18px 16px 8px; display: flex; flex-direction: column; gap: 14px; }
        .mpage.hascta { padding-bottom: 176px; }
        .mpage h1 { margin: 4px 0 0; font-size: 27px; line-height: 1.3; letter-spacing: -.02em; }
        .msub { margin: 0; font-size: 13px; color: var(--dim); line-height: 1.7; }
        .mmsg { margin: 0; font-size: 13px; color: var(--dim); }
        .merr { margin: 10px 16px 0; padding: 10px 12px; border-radius: 10px; background: rgba(255,90,70,.14);
          color: #ffb0a2; font-size: 13px; }
        .merr-inline { margin: 0; font-size: 13px; color: #ffb0a2; }

        .mseg { display: flex; gap: 6px; background: var(--panel); padding: 4px; border-radius: 12px; }
        .mseg button { flex: 1; border: 0; background: none; color: var(--dim); font: inherit; font-size: 15px;
          padding: 11px 0; border-radius: 9px; }
        .mseg button.on { background: #26262E; color: var(--ink); font-weight: 700; }

        .mbox { display: flex; flex-direction: column; gap: 8px; }
        input, select, textarea { width: 100%; background: var(--panel); color: var(--ink);
          border: 1px solid var(--line); border-radius: 12px; padding: 13px 14px; font: inherit; font-size: 16px;
          outline: none; }
        input:focus, textarea:focus { border-color: var(--gold); }
        textarea { min-height: 190px; line-height: 1.9; resize: vertical; }
        .mmeta { display: flex; justify-content: space-between; font-size: 12px; color: var(--dim); }
        .mmeta button { background: none; border: 0; color: var(--gold); font: inherit; font-size: 12px; }

        .mbtn { display: block; width: 100%; border: 0; border-radius: 14px; padding: 16px;
          background: var(--gold); color: #171207; font: inherit; font-size: 17px; font-weight: 800;
          letter-spacing: .02em; text-align: center; text-decoration: none; }
        .mbtn:disabled { opacity: .45; }
        .mbtn.ghost { background: transparent; color: var(--ink); border: 1px solid var(--line); font-weight: 600; font-size: 15px; }
        .mlink { background: none; border: 0; color: var(--gold); font: inherit; font-size: 14px; padding: 8px; }

        .mbottom { position: fixed; left: 0; right: 0; bottom: calc(58px + env(safe-area-inset-bottom));
          padding: 10px 16px; background: linear-gradient(180deg, transparent, var(--bg) 40%); }
        .mbottom .mbtn { box-shadow: 0 10px 30px -12px rgba(240,180,41,.6); }

        .mhead { display: flex; align-items: baseline; gap: 10px; }
        .mhead b { font-size: 19px; }
        .mhead span { font-size: 12px; color: var(--dim); margin-left: auto; }
        .mback { background: none; border: 1px solid var(--line); color: var(--ink); width: 34px; height: 34px;
          border-radius: 10px; font-size: 20px; line-height: 1; }

        .mgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .mcard { position: relative; padding: 0 0 8px; border: 1px solid var(--line); border-radius: 12px;
          background: var(--panel); overflow: hidden; text-align: left; color: var(--ink); }
        .mcard img, .mnothumb { display: block; width: 100%; aspect-ratio: 3/4; object-fit: cover; }
        .mnothumb { background: linear-gradient(160deg, #2C2C36, #17171C); }
        .mcard b { display: block; font-size: 15px; padding: 8px 10px 0; }
        .mcard i { display: block; font-style: normal; font-size: 12px; color: var(--dim); padding: 2px 10px 0; }
        .mcard.on { border-color: var(--gold); box-shadow: 0 0 0 2px rgba(240,180,41,.35); }
        .mcard em { position: absolute; top: 8px; right: 8px; width: 24px; height: 24px; border-radius: 50%;
          background: var(--gold); color: #171207; font-style: normal; font-size: 14px; font-weight: 900;
          display: grid; place-items: center; }

        .mrow { display: flex; align-items: center; gap: 10px; }
        .mrow label { font-size: 14px; color: var(--dim); white-space: nowrap; }
        .mrow select { flex: 1; }
        .mcheck { display: flex; align-items: center; gap: 10px; font-size: 14px; color: var(--dim); }
        .mcheck input { width: 20px; height: 20px; accent-color: var(--gold); }

        .mpage.run { align-items: center; justify-content: flex-start; gap: 16px; padding-top: 24px; }
        .mphone { position: relative; width: min(62vw, 248px); aspect-ratio: 9/19.2; border-radius: 34px;
          border: 8px solid #232329; background: #000; overflow: hidden; box-shadow: 0 20px 50px -20px #000; }
        .mlive { position: absolute; inset: 0; }
        .mlive canvas { width: 100%; height: 100%; object-fit: contain; display: block; background: #000; }
        .misland { position: absolute; top: 8px; left: 50%; transform: translateX(-50%);
          width: 70px; height: 20px; border-radius: 12px; background: #000; }
        .mposter { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .6; filter: saturate(.9); }
        .mphone::after { content: ''; position: absolute; inset: 0; pointer-events: none;
          background: linear-gradient(180deg, rgba(0,0,0,.25), rgba(0,0,0,.55)); }
        .mwait { position: absolute; inset: 0; display: grid; place-items: center; color: var(--dim); font-size: 14px; }
        .msteps { display: flex; gap: 5px; justify-content: center; width: 100%; }
        .mstep { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--dim);
          padding: 6px 8px; border: 1px solid var(--line); border-radius: 99px; white-space: nowrap; }
        .mstep i { width: 16px; height: 16px; border-radius: 50%; background: #26262E; display: grid;
          place-items: center; font-style: normal; font-size: 10px; }
        .mstep.now { color: var(--gold); border-color: rgba(240,180,41,.5); }
        .mstep.now i { background: var(--gold); color: #171207; }
        .mstep.done { color: #8FD6A5; border-color: rgba(143,214,165,.35); }
        .mprogress { width: 80%; height: 6px; background: rgba(255,255,255,.1); border-radius: 99px; overflow: hidden; }
        .mprogress i { display: block; height: 100%; background: var(--gold); transition: width .3s; }
        .mhint { font-size: 12px; color: var(--dim); text-align: center; margin: 0; }

        .mvideobox { border-radius: 14px; overflow: hidden; background: #000; }
        .mvideobox video { width: 100%; display: block; }
        .mactions { display: flex; flex-direction: column; gap: 8px; }

        .mnav { position: fixed; left: 0; right: 0; bottom: 0; height: calc(58px + env(safe-area-inset-bottom));
          padding-bottom: env(safe-area-inset-bottom); display: flex; background: rgba(15,15,18,.96);
          backdrop-filter: blur(10px); border-top: 1px solid var(--line); z-index: 30; }
        .mnav button { flex: 1; background: none; border: 0; color: var(--dim); font: inherit; font-size: 13px; }
        .mnav button.on { color: var(--gold); font-weight: 700; }

        .msheet { position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 40; display: flex; align-items: flex-end; }
        .msheet-body { width: 100%; max-height: 82vh; overflow-y: auto; background: #14141A;
          border-radius: 18px 18px 0 0; padding: 16px 16px calc(24px + env(safe-area-inset-bottom));
          display: flex; flex-direction: column; gap: 10px; }
        .msheet-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
        .msheet-head b { font-size: 17px; }
        .msheet-head button { background: none; border: 0; color: var(--dim); font: inherit; font-size: 14px; }
        .memail { margin: 0; font-size: 15px; word-break: break-all; }
        .mwork { display: flex; align-items: center; justify-content: space-between; gap: 10px;
          padding: 12px; border: 1px solid var(--line); border-radius: 12px; }
        .mwork b { display: block; font-size: 14px; }
        .mwork span { font-size: 12px; color: var(--dim); }
        .mwork-act { display: flex; gap: 12px; font-size: 13px; }
        .mwork-act a, .mwork-act button { color: var(--gold); background: none; border: 0; font: inherit; font-size: 13px; }
      `}</style>
    </div>
  );
}






