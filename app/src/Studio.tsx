import { useEffect, useMemo, useRef, useState } from 'react';
import { planScript, renderVideo } from './lib/render';
import type { ThemeName, PlanBeat } from './lib/types';
import {
  createGen, deleteGen, getMe, listHistory, login, logout, redeem, register,
  uploadVideo, videoUrl, type GenItem, type Me,
} from './lib/account';
import { exportJianyingDraft } from './lib/jianying';

type Choice = ThemeName | 'auto';

const STYLES: { id: Choice; name: string; thumb?: string; preview?: string }[] = [
  { id: 'auto', name: '自动' },
  { id: 'poster', name: '大字报', thumb: 'style-thumbs/poster.jpg', preview: 'style-previews/poster.mp4' },
  { id: 'magazine', name: '杂志', thumb: 'style-thumbs/magazine.jpg', preview: 'style-previews/magazine.mp4' },
  { id: 'dashboard', name: '数据', thumb: 'style-thumbs/dashboard.jpg' },
  { id: 'newsroom', name: '播报', thumb: 'style-thumbs/newsroom.jpg', preview: 'style-previews/newsroom.mp4' },
  { id: 'ledger', name: '财报' },
  { id: 'marker', name: '白板', thumb: 'style-thumbs/marker.jpg', preview: 'style-previews/marker.mp4' },
  { id: 'swiss', name: '极简', thumb: 'style-thumbs/swiss.jpg', preview: 'style-previews/swiss.mp4' },
  { id: 'terminal', name: '终端', thumb: 'style-thumbs/terminal.jpg', preview: 'style-previews/terminal.mp4' },
  { id: 'broadsheet', name: '报纸', thumb: 'style-thumbs/broadsheet.jpg', preview: 'style-previews/broadsheet.mp4' },
  { id: 'cover', name: '封面', thumb: 'style-thumbs/cover.jpg', preview: 'style-previews/cover.mp4' },
  { id: 'reel', name: '胶片', thumb: 'style-thumbs/reel.jpg', preview: 'style-previews/reel.mp4' },
  { id: 'news', name: '新闻', thumb: 'style-thumbs/news.jpg', preview: 'style-previews/news.mp4' },
  { id: 'night', name: '夜行', thumb: 'style-thumbs/night.jpg', preview: 'style-previews/night.mp4' },
];

const VOICES = [
  { id: 'zh-CN-YunxiNeural', name: '云希', desc: '男声 · 年轻' },
  { id: 'zh-CN-YunyangNeural', name: '云扬', desc: '男声 · 播音' },
  { id: 'zh-CN-XiaoxiaoNeural', name: '晓晓', desc: '女声 · 温和' },
  { id: 'zh-CN-XiaoyiNeural', name: '晓伊', desc: '女声 · 活泼' },
  { id: 'zh-CN-YunjianNeural', name: '云健', desc: '男声 · 厚实' },
];

const BGMS = [
  { id: '', name: '跟随风格', desc: '按模板自动配' },
  { id: 'music/corporate.mp3', name: '商务', desc: '稳 · 律师/教培' },
  { id: 'music/cinematic.mp3', name: '电影', desc: '推进 · 观点/加盟' },
  { id: 'music/news.mp3', name: '新闻', desc: '紧迫 · 资讯' },
  { id: 'music/electronic.mp3', name: '电子', desc: '轻快 · 通用' },
  { id: 'music/trap.mp3', name: '强拍', desc: '钩子 · 强节奏' },
  { id: 'music/funk.mp3', name: '律动', desc: '轻松 · 门店' },
  { id: 'music/orchestral.mp3', name: '管弦', desc: '压迫 · 重话题' },
  { id: 'music/upbeat.mp3', name: '明快', desc: '向上 · 通用' },
  { id: 'music/breakbeat.mp3', name: '碎拍', desc: '动感 · 大字报' },
  { id: 'music/chill.mp3', name: '舒缓', desc: '氛围 · 纪实' },
];

const PRESETS = [
  {
    title: '加盟：回本周期怎么算',
    industry: '餐饮加盟',
    text: `想开一家店，总部说八个月回本，你信吗？
先别信，自己算三个数。
第一个数，前期总投入。加盟费、保证金、装修、设备、首批物料，加起来才是真数，不是海报上那个数。
第二个数，每月固定支出。房租、人工、水电、物料，一分不能少。
第三个数，日均流水。别问总部，去他现有的店里蹲三天，看真实客流。
用前期投入除以每月净利，才是你的回本周期。
总部说八个月，你就按十二个月算，多出来的四个月是你的活路。
把品牌名发给我，我帮你把这三个数拆开算一遍。`,
  },
  {
    title: '律师：货款要不回来怎么办',
    industry: '律师',
    text: `货款要不回来，很多老板第一反应是打电话催。
催是没用的，对方早想好了怎么拖。
第一步，把所有凭证收齐：合同、送货单、对账单、聊天记录，缺一样都麻烦。
第二步，起诉的同时申请财产保全，先把他账户冻住，人一慌才肯谈。
第三步，只谈一件事——什么时候付、付多少，别在电话里讲道理。
拖过三年的，证据还在，钱可能就没了。
把合同发我，我帮你看还能不能走这一步。`,
  },
  {
    title: '教培：孩子成绩上不去',
    industry: '教培',
    text: `孩子成绩上不去，大部分家长第一件事就是报班。
报之前，先看三个地方。
第一，看他哪一科最差。瘸腿科目补十分，比优势科目多考五分容易得多。
第二，看他错在哪。是不会，还是粗心，还是根本没听懂。
第三，看他愿意学多久。坐不住四十分钟的孩子，先别报两小时的课。
三个都看清了再花钱，一节课的钱够你试错三次。
把孩子的卷子发我，我帮你看看问题出在哪。`,
  },
  {
    title: '门店：选址的五个坑',
    industry: '本地生活',
    text: `选址选错，后面再努力都是给房东打工。
第一个坑，只看人流不看客流。路过的人再多，不进店也没用。
第二个坑，贪便宜选背街。省下的房租，会从营业额里十倍还回去。
第三个坑，不算租金占比。房租超过营业额的两成，基本就很难赚了。
第四个坑，不看邻居。隔壁是五金店还是奶茶店，决定你客人停不停。
第五个坑，不蹲点数。白天、晚上、周末各蹲一天，数字最诚实。
看中哪个铺，把位置发我，我帮你一起算。`,
  },
  {
    title: '通用：为什么你的视频没人看',
    industry: '通用',
    text: `拍了三十条视频，播放还是三位数，问题多半不在画质。
第一条，前三秒没钩子。观众划走的决定，比你说话还快。
第二条，一屏放太多字。手机那么小，他只看得清一行。
第三条，句子里全是形容词。说"很划算"不如说"便宜了三十块"。
第四条，结尾没有动作。你不告诉他去哪，他就去哪了。
第五条，一条视频讲五件事，等于一件没讲。
挑一条你的片子，用这五条对一遍，你会发现问题一眼就能看出来。`,
  },
  {
    title: '财税：小规模纳税人别乱开票',
    industry: '通用',
    text: `小规模纳税人，最容易在开票上吃亏。
第一，别以为免税就不用管。免税有额度，超了就要交。
第二，专票和普票不是一回事。开了专票，那一部分通常不能免。
第三，季度末集中开票最容易踩线。平时不开，最后一周猛开，风险最高。
第四，进项票要留好。该抵的不抵，等于自己多交钱。
第五，别用个人卡收货款。流水对不上，解释起来很麻烦。
把你的开票情况发我，我帮你看看有没有踩线。`,
  },
];

const DEMO = `想开一家小店，你最怕的是什么？不是没客人，是钱投进去，三个月就撑不住。
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

function draftScenes(text: string) {
  const parts = text.split(/[。！？\n]/).map((s) => s.trim()).filter(Boolean).slice(0, 12);
  return parts.map((p) => ({ text: p, duration: Math.max(1.6, Math.round(p.length / 4.6)) }));
}

function fmt(t: number) {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/** 大图标：给 40+ 用户看，笔画粗、形状实、一眼认得出 */
function Icon({ name }: { name: 'text' | 'style' | 'voice' | 'works' }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 2.2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  if (name === 'text') {
    return (
      <svg viewBox="0 0 32 32" width="30" height="30" {...common}>
        <path d="M8 5h12l5 5v17H8z" />
        <path d="M20 5v6h5" />
        <path d="M12 16h9M12 21h9M12 26h5" />
      </svg>
    );
  }
  if (name === 'style') {
    return (
      <svg viewBox="0 0 32 32" width="30" height="30" {...common}>
        <rect x="4" y="6" width="15" height="20" rx="2" />
        <rect x="15" y="12" width="13" height="14" rx="2" />
        <path d="M7 20l4-4 3 3" />
        <path d="M18 22l3-3 4 3" />
      </svg>
    );
  }
  if (name === 'voice') {
    return (
      <svg viewBox="0 0 32 32" width="30" height="30" {...common}>
        <path d="M5 13h5l6-5v16l-6-5H5z" />
        <path d="M21 12a6 6 0 010 8" />
        <path d="M25 9a10 10 0 010 14" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 32 32" width="30" height="30" {...common}>
      <rect x="4" y="8" width="24" height="16" rx="2" />
      <path d="M4 14h24M4 20h24" />
      <path d="M10 8v16M22 8v16" />
    </svg>
  );
}

export default function Studio() {
  const [text, setText] = useState('');
  const [choice, setChoice] = useState<Choice>('auto');
  const [broll, setBroll] = useState(false);
  const [music, setMusic] = useState(true);
  const [voice, setVoice] = useState(VOICES[0].id);
  const [bgm, setBgm] = useState('');
  const [srcMode, setSrcMode] = useState<'paste' | 'ai' | 'lib'>('paste');
  const [topic, setTopic] = useState('');
  const [industry, setIndustry] = useState('餐饮加盟');
  const [writing, setWriting] = useState(false);
  const [writeMsg, setWriteMsg] = useState('');
  const [menu, setMenu] = useState(false);
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
  const [hoverStyle, setHoverStyle] = useState<string>('');
  const [previewing, setPreviewing] = useState('');
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [now, setNow] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const dragging = useRef(false);

  const refresh = async () => {
    try { setMe(await getMe()); } catch { /* 离线也能用 */ }
    try { setHistory((await listHistory()).items); } catch { /* 同上 */ }
  };
  useEffect(() => { void refresh(); }, []);

  const chars = text.trim().length;
  const est = Math.max(0, Math.round(chars / 4.6));
  const [order, setOrder] = useState<number[]>([]);
  const dragFrom = useRef<number | null>(null);

  const scenes = useMemo(() => {
    if (plan?.length) return plan.map((b) => ({ text: b.text, duration: Math.max(1.4, Math.round(b.text.length / 4.6)) }));
    return draftScenes(text);
  }, [plan, text]);

  // 顺序：默认按稿子来；用户拖动剪辑块后按 order 排
  useEffect(() => {
    setOrder(scenes.map((_, i) => i));
  }, [scenes.length]);

  const ordered = order.length === scenes.length ? order.map((i) => scenes[i]) : scenes;
  const totalDur = ordered.reduce((n, s) => n + s.duration, 0) || 1;
  const playable = dur || totalDur;

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
      const planned = await planScript(src);
      setPlan(planned);
      // 用户拖过顺序：按当前 order 重排后再渲染
      const orderedPlan = order.length === planned.length ? order.map((i) => planned[i]) : planned;
      const title = src.split(/[。！？\n]/)[0].slice(0, 14);
      const blob = await renderVideo(orderedPlan, theme, title, ({ stage: s, percent }) => {
        setStage(s); setPct(percent);
      }, broll, music, voice, bgm);
      setSecs(Math.round((performance.now() - t0) / 1000));
      setUrl(URL.createObjectURL(blob));
      setPct(100);
      setSaveState('saving');
      try {
        const rec = await createGen({ title, text: src, theme, duration: Math.round(planned.length * 2.5) });
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

  /** 点一下就试听 3 秒，确认音色合不合适 */
  async function previewVoice(id: string) {
    if (previewing) return;
    setPreviewing(id);
    try {
      const res = await fetch('/api/tts', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: '开店三个数：先算投入，再算回本，最后看流水。', voice: id }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      const u = URL.createObjectURL(blob);
      audioRef.current?.pause();
      const audio = new Audio(u);
      audioRef.current = audio;
      audio.onended = () => { setPreviewing(''); URL.revokeObjectURL(u); };
      await audio.play();
    } catch {
      setPreviewing('');
      setErr('试听失败，稍后再试');
    }
  }

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) { void v.play(); } else { v.pause(); }
  };

  const seekRatio = (ratio: number) => {
    const v = videoRef.current;
    const r = Math.max(0, Math.min(1, ratio));
    setNow(r * playable);
    if (v && v.duration) v.currentTime = r * v.duration;
  };

  const seekFromEvent = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    seekRatio((clientX - rect.left) / rect.width);
  };

  async function genScript() {
    const t = topic.trim();
    if (t.length < 2) { setWriteMsg('先写个主题，比如「加盟回本周期怎么算」'); return; }
    setWriting(true);
    setWriteMsg('');
    try {
      const res = await fetch('/api/script', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ topic: t, industry }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '写稿失败');
      setText(data.text);
      setWriteMsg('写好了 · ' + data.words + ' 字，可以直接改');
      setSrcMode('paste');
    } catch (e) {
      setWriteMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setWriting(false);
    }
  }

  const sceneStart = (i: number) => ordered.slice(0, i).reduce((n, s) => n + s.duration, 0);

  return (
    <div className="studio">
      <header className="top">
        <div className="brand">GetCut<span>studio</span></div>
        <div className="project">
          <b>{text.trim().split(/[。！？\n]/)[0].slice(0, 18) || '未命名项目'}</b>
          <span>{running ? `${stage} ${pct}%` : url ? '已出片' : '草稿'}</span>
        </div>
        <div className="top-act">
          <button className="primary" onClick={run} disabled={running}>
            {running ? `${pct}%` : '生成视频'}
          </button>
          <button className="avatar" onClick={() => setMenu((v) => !v)} title="账号">
            {me?.loggedIn ? (me.email || 'U').slice(0, 1).toUpperCase() : '登'}
          </button>
          {menu ? (
            <>
              <div className="menu-mask" onClick={() => setMenu(false)} />
              <div className="menu">
                {me?.loggedIn ? (
                  <>
                    <div className="menu-head">
                      <b>{me.email}</b>
                      <span>{me.pro ? '已买断 · 不限条数' : `免费剩 ${me.remaining} 条`}</span>
                    </div>
                    <button className="menu-item" onClick={() => { setTab('works'); setMenu(false); }}>我的作品</button>
                    {!me.pro ? (
                      <button className="menu-item" onClick={() => { setShowBuy(true); setMenu(false); }}>买断 ¥599</button>
                    ) : null}
                    <button className="menu-item danger" onClick={async () => { await logout(); setMenu(false); await refresh(); }}>退出登录</button>
                  </>
                ) : (
                  <>
                    <div className="menu-head">
                      <b>未登录</b>
                      <span>{me ? `免费剩 ${me.remaining} 条` : '免费 3 条'}</span>
                    </div>
                    <button className="menu-item" onClick={() => { setAuthMode('login'); setShowAuth(true); setMenu(false); }}>登录 / 注册</button>
                    <button className="menu-item" onClick={() => { setShowBuy(true); setMenu(false); }}>买断 ¥599</button>
                  </>
                )}
              </div>
            </>
          ) : null}
        </div>
      </header>

      <div className="body">
        <nav className="rail">
          {([
            ['text', '文案'],
            ['style', '模板'],
            ['voice', '声音'],
            ['works', '作品'],
          ] as const).map(([id, label]) => (
            <button key={id} className={`rail-btn ${tab === id ? 'on' : ''}`} onClick={() => setTab(id)}>
              <Icon name={id} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <main className="stage">
          <div className="canvas" onClick={togglePlay}>
            {url ? (
              <video
                ref={videoRef}
                src={url}
                playsInline
                onLoadedData={(e) => { e.currentTarget.currentTime = 0.4; }}
                onTimeUpdate={(e) => { const v = e.currentTarget; setNow(v.currentTime); setDur(v.duration || 0); }}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
              />
            ) : (
              <div className="placeholder">
                <img src="samples/poster.jpg" alt="" />
              </div>
            )}
            {running ? <div className="hud">{stage} · {pct}%</div> : null}
          </div>

          <div className="transport">
            <button className="play" onClick={togglePlay} disabled={!url} aria-label="播放">
              {playing ? (
                <svg viewBox="0 0 24 24" width="18" height="18"><path d="M6 5h4v14H6zM14 5h4v14h-4z" fill="currentColor" /></svg>
              ) : (
                <svg viewBox="0 0 24 24" width="18" height="18"><path d="M8 5l12 7-12 7z" fill="currentColor" /></svg>
              )}
            </button>
            <span className="tc">{fmt(now)} / {fmt(playable)}</span>
            <div
              className="scrub"
              ref={trackRef}
              onPointerDown={(e) => { dragging.current = true; seekFromEvent(e.clientX); (e.target as HTMLElement).setPointerCapture?.(e.pointerId); }}
              onPointerMove={(e) => { if (dragging.current) seekFromEvent(e.clientX); }}
              onPointerUp={() => { dragging.current = false; }}
              onPointerCancel={() => { dragging.current = false; }}
            >
              <i style={{ width: `${(now / playable) * 100}%` }} />
              <b style={{ left: `${(now / playable) * 100}%` }} />
            </div>
            <span className="tc dim">1080×1920</span>
          </div>
        </main>

        <aside className="inspector">
          <div className="ins-head">
            <b>{tab === 'text' ? '文案' : tab === 'style' ? '剪辑模板' : tab === 'voice' ? '声音' : '作品'}</b>
            {tab === 'text' ? <button className="tlink" onClick={() => setText(DEMO)}>插入示例</button> : null}
          </div>

          {tab === 'text' ? (
            <>
              <div className="seg">
                <button className={`seg-b ${srcMode === 'paste' ? 'on' : ''}`} onClick={() => setSrcMode('paste')}>粘贴文案</button>
                <button className={`seg-b ${srcMode === 'ai' ? 'on' : ''}`} onClick={() => setSrcMode('ai')}>AI 帮我写</button>
                <button className={`seg-b ${srcMode === 'lib' ? 'on' : ''}`} onClick={() => setSrcMode('lib')}>现成模板</button>
              </div>

              {srcMode === 'ai' ? (
                <div className="ai-box">
                  <input
                    className="topic"
                    placeholder="想讲什么？例如：加盟回本周期怎么算"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') void genScript(); }}
                  />
                  <div className="ai-row">
                    <select className="select" value={industry} onChange={(e) => setIndustry(e.target.value)}>
                      <option value="餐饮加盟">餐饮加盟</option>
                      <option value="律师/法律服务">律师 / 法律服务</option>
                      <option value="教培/教育">教培 / 教育</option>
                      <option value="本地生活">本地生活</option>
                      <option value="美业/医美">美业 / 医美</option>
                      <option value="通用">通用</option>
                    </select>
                    <button className="primary" onClick={genScript} disabled={writing}>
                      {writing ? '正在写…' : '写一篇给我'}
                    </button>
                  </div>
                  {writeMsg ? <p className="dim">{writeMsg}</p> : null}
                </div>
              ) : null}

              {srcMode === 'lib' ? (
                <div className="lib">
                  {PRESETS.map((p) => (
                    <button key={p.title} className="lib-item" onClick={() => { setText(p.text); setSrcMode('paste'); }}>
                      <b>{p.title}</b>
                      <span>{p.industry} · {p.text.length} 字</span>
                    </button>
                  ))}
                </div>
              ) : null}

              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={'把口播稿粘在这里。\n\n不知道写什么？用上面「AI 帮我写」或「现成模板」。'}
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
                <button
                  key={s.id}
                  className={`thumb ${choice === s.id ? 'on' : ''}`}
                  onClick={() => setChoice(s.id)}
                  onMouseEnter={() => setHoverStyle(s.id)}
                  onMouseLeave={() => setHoverStyle('')}
                >
                  {s.thumb ? <img src={s.thumb} alt="" /> : <span className="nothumb" />}
                  {s.preview && hoverStyle === s.id ? (
                    <video className="hover-preview" src={s.preview} autoPlay muted loop playsInline />
                  ) : null}
                  <i>{s.name}</i>
                </button>
              ))}
            </div>
          ) : null}

          {tab === 'voice' ? (
            <div className="voices">
              {VOICES.map((v) => (
                <div key={v.id} className={`voice-row ${voice === v.id ? 'on' : ''}`}>
                  <button className="voice-main" onClick={() => setVoice(v.id)}>
                    <span className="vname">{v.name}</span>
                    <span className="vdesc">{v.desc}</span>
                  </button>
                  <button className="try" onClick={() => void previewVoice(v.id)} disabled={previewing === v.id}>
                    {previewing === v.id ? '播放中' : '试听'}
                  </button>
                </div>
              ))}
              <label className="check"><input type="checkbox" checked={music} onChange={(e) => setMusic(e.target.checked)} />自动配乐（说话时自动压低）</label>
              {music ? (
                <div className="bgm-list">
                  {BGMS.map((b) => (
                    <button
                      key={b.id || 'auto'}
                      className={`bgm-row ${bgm === b.id ? 'on' : ''}`}
                      onClick={() => setBgm(b.id)}
                    >
                      <span className="bname">{b.name}</span>
                      <span className="bdesc">{b.desc}</span>
                    </button>
                  ))}
                </div>
              ) : null}
              <label className="check"><input type="checkbox" checked={broll} onChange={(e) => setBroll(e.target.checked)} />插入实拍空镜（较慢）</label>
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

      <section className="timeline">
        <div className="tl-head">
          <b>时间轴</b>
          <span>{ordered.length} 个镜头 · 约 {Math.round(url ? playable : totalDur)} 秒</span>
          {running ? <span className="tl-run">{stage} {pct}%</span> : null}
          <span className="tl-tip">点片段跳到那一句 · 按住拖动可换顺序</span>
        </div>
        <div className="tl-body">
          <div className="tl-lane-label">主背景</div>
          <div className="tl-lane">
            <div className="lane-long bg">
              {broll ? '实拍空镜 · 按句子匹配' : `纯色底 · ${STYLES.find((s) => s.id === (choice === 'auto' ? 'poster' : choice))?.name || '自动'}`}
            </div>
          </div>

          <div className="tl-lane-label">画面</div>
          <div className="tl-lane">
            {ordered.slice(0, 12).map((s, i) => (
              <button
                key={i}
                draggable
                onDragStart={() => { dragFrom.current = i; }}
                onDragEnter={() => {
                  const from = dragFrom.current;
                  if (from === null || from === i) return;
                  setOrder((prev) => {
                    const a = [...prev];
                    const tmp = a[from];
                    a[from] = a[i];
                    a[i] = tmp;
                    return a;
                  });
                  dragFrom.current = i;
                }}
                onDragEnd={() => { dragFrom.current = null; }}
                className={`clip ${selectedScene === i ? 'on' : ''}`}
                style={{ flexGrow: s.duration }}
                onClick={() => { setSelectedScene(i); seekRatio(sceneStart(i) / totalDur); }}
                title={s.text}
              >
                <span>{s.text.slice(0, 12)}</span>
              </button>
            ))}
            {!ordered.length ? <div className="clip empty">等待文案</div> : null}
          </div>

          <div className="tl-lane-label">配音</div>
          <div className="tl-lane">
            {ordered.slice(0, 12).map((s, i) => (
              <button
                key={i}
                className="clip voice"
                style={{ flexGrow: s.duration }}
                onClick={() => { setSelectedScene(i); seekRatio(sceneStart(i) / totalDur); }}
                title={`${VOICES.find((v) => v.id === voice)?.name || ''} · ${s.text}`}
              >
                <span>{VOICES.find((v) => v.id === voice)?.name || '配音'}</span>
              </button>
            ))}
            {!ordered.length ? <div className="clip empty">—</div> : null}
          </div>

          <div className="tl-lane-label">字幕</div>
          <div className="tl-lane texts">
            {ordered.slice(0, 12).map((s, i) => (
              <button
                key={i}
                className="sub"
                style={{ flexGrow: s.duration }}
                onClick={() => { setSelectedScene(i); seekRatio(sceneStart(i) / totalDur); }}
              >
                {s.text.slice(0, 16)}
              </button>
            ))}
            {!ordered.length ? <div className="sub empty">—</div> : null}
          </div>

          <div className="tl-lane-label">音乐</div>
          <div className="tl-lane">
            <div className="lane-long music">
              {music ? (BGMS.find((b) => b.id === bgm)?.name || '跟随风格') + ' · 人声时自动压低' : '未启用'}
            </div>
          </div>

          <div className="playhead" style={{ left: `calc(52px + (100% - 60px) * ${now / playable})` }} />
        </div>
      </section>

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
          --panel-2: #1C1C21;
          --line: rgba(255,255,255,.10);
          --line-2: rgba(255,255,255,.20);
          --ink: #F2F2F4;
          --dim: #A6A6B0;
          --gold: #F0B429;
        }
        * { box-sizing: border-box; }
        html, body, #root { height: 100%; }
        body { margin: 0; background: var(--bg); color: var(--ink);
          font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif; overflow: hidden; font-size: 15px; }
        .studio { height: 100vh; display: flex; flex-direction: column; }

        .top { height: 64px; flex: none; display: flex; align-items: center; gap: 20px;
          padding: 0 18px; border-bottom: 1px solid var(--line); background: var(--panel); }
        .brand { font-weight: 900; font-size: 17px; letter-spacing: .02em; }
        .brand span { color: var(--gold); font-weight: 500; margin-left: 5px; font-size: 13px; }
        .project { flex: 1; display: flex; align-items: baseline; gap: 12px; min-width: 0; }
        .project b { font-size: 15px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .project span { font-size: 13px; color: var(--dim); }
        .avatar { width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--line-2);
          background: var(--panel-2); color: var(--ink); font-size: 15px; font-weight: 800; cursor: pointer; }
        .avatar:hover { border-color: var(--gold); }
        .menu-mask { position: fixed; inset: 0; z-index: 30; }
        .menu { position: absolute; right: 16px; top: 62px; z-index: 31; width: 260px;
          background: var(--panel); border: 1px solid var(--line-2); border-radius: 12px;
          padding: 8px; box-shadow: 0 24px 60px -20px #000; display: grid; gap: 2px; }
        .menu-head { display: grid; gap: 3px; padding: 10px 12px 12px; border-bottom: 1px solid var(--line); margin-bottom: 6px; }
        .menu-head b { font-size: 14px; overflow: hidden; text-overflow: ellipsis; }
        .menu-head span { font-size: 13px; color: var(--dim); }
        .menu-item { text-align: left; background: none; border: 0; color: var(--ink); font: inherit;
          font-size: 15px; padding: 11px 12px; border-radius: 8px; cursor: pointer; }
        .menu-item:hover { background: var(--panel-2); }
        .menu-item.danger { color: #ff8f7a; }
        .bgm-list { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 6px; }
        .bgm-row { display: grid; gap: 1px; text-align: left; background: var(--panel-2);
          border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; color: var(--ink);
          cursor: pointer; font: inherit; }
        .bgm-row.on { border-color: var(--gold); }
        .bname { font-size: 14px; font-weight: 700; }
        .bdesc { font-size: 12px; color: var(--dim); }
        .lane-long { flex: 1; display: flex; align-items: center; padding: 0 10px; font-size: 12px;
          border-radius: 6px; border: 1px solid var(--line); color: #C9C9D1; background: #24242B;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .lane-long.bg { background: rgba(120,140,200,.14); border-color: rgba(120,140,200,.3); color: #C6D2F2; }
        .lane-long.music { background: rgba(120,200,150,.12); border-color: rgba(120,200,150,.28); color: #BFE6CC; }
        .clip.voice { background: linear-gradient(180deg, #3A2F26, #2A221B); color: #E7CBA6; }        .top-act { position: relative; display: flex; align-items: center; gap: 14px; font-size: 14px; color: var(--dim); }
        .quota { letter-spacing: .03em; }
        .tlink { background: none; border: 0; padding: 0; font: inherit; color: var(--dim); cursor: pointer; font-size: 14px; }
        .tlink:hover { color: var(--ink); }
        .tlink.danger { color: #ff8f7a; }
        .primary { background: var(--gold); color: #171207; border: 0; border-radius: 8px;
          padding: 12px 22px; font-size: 15px; font-weight: 800; cursor: pointer; letter-spacing: .03em; }
        .primary:hover { filter: brightness(1.06); }
        .primary:disabled { opacity: .6; cursor: not-allowed; }
        .primary.wide { width: 100%; padding: 13px 16px; }
        .ghost { background: transparent; border: 1px solid var(--line-2); color: var(--ink);
          border-radius: 8px; padding: 11px 12px; font-size: 14px; cursor: pointer; }
        .ghost:hover { border-color: var(--gold); }

        .body { flex: 1; display: grid; grid-template-columns: 92px minmax(0,1fr) 372px; min-height: 0; }

        .rail { border-right: 1px solid var(--line); display: flex; flex-direction: column; align-items: center;
          padding-top: 14px; gap: 8px; background: var(--panel); }
        .rail-btn { width: 76px; padding: 12px 0 10px; display: grid; place-items: center; gap: 7px;
          background: none; border: 0; border-radius: 10px; color: var(--dim); cursor: pointer; font-size: 13px; }
        .rail-btn:hover { background: var(--panel-2); color: var(--ink); }
        .rail-btn.on { background: var(--panel-2); color: var(--gold); }

        .stage { min-width: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
          background: radial-gradient(1200px 600px at 50% 0%, rgba(255,255,255,.035), transparent 70%), var(--bg);
          padding: 18px 24px 10px; gap: 14px; }
        .canvas { position: relative; height: min(48vh, 430px); aspect-ratio: 9/16; background: #000;
          border-radius: 10px; overflow: hidden; box-shadow: 0 20px 60px -30px #000, 0 0 0 1px var(--line-2);
          cursor: pointer; display: grid; place-items: center; }
        .canvas video { width: 100%; height: 100%; object-fit: cover; display: block; }
        .placeholder { position: absolute; inset: 0; display: grid; place-items: center; }
        .placeholder img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .45; }
        .placeholder::after { content: ''; position: absolute; inset: 26px; border: 1px dashed rgba(255,255,255,.2); pointer-events: none; }
        .hud { position: absolute; left: 12px; bottom: 12px; background: rgba(0,0,0,.65); color: #fff;
          font-size: 13px; padding: 5px 10px; border-radius: 6px; }

        .transport { width: min(100%, 360px); display: flex; align-items: center; gap: 12px; }
        .play { width: 38px; height: 38px; border-radius: 50%; border: 1px solid var(--line-2);
          background: var(--panel-2); color: var(--ink); display: grid; place-items: center; cursor: pointer; }
        .play:disabled { opacity: .4; cursor: default; }
        .tc { font-size: 13px; color: var(--dim); font-variant-numeric: tabular-nums; }
        .scrub { position: relative; flex: 1; height: 8px; background: rgba(255,255,255,.12);
          border-radius: 4px; cursor: pointer; touch-action: none; }
        .scrub i { display: block; height: 100%; width: 0; background: var(--gold); border-radius: 4px; }
        .scrub b { position: absolute; top: 50%; width: 16px; height: 16px; border-radius: 50%;
          background: var(--gold); transform: translate(-50%, -50%); box-shadow: 0 0 0 3px rgba(240,180,41,.25); }

        .inspector { border-left: 1px solid var(--line); background: var(--panel); padding: 16px;
          overflow-y: auto; display: flex; flex-direction: column; gap: 14px; }
        .ins-head { display: flex; align-items: center; justify-content: space-between; }
        .ins-head b { font-size: 16px; letter-spacing: .04em; }
        textarea { width: 100%; min-height: 230px; resize: vertical; background: var(--panel-2); color: var(--ink);
          border: 1px solid var(--line); border-radius: 10px; padding: 14px; font: inherit; font-size: 15px;
          line-height: 1.95; outline: none; }
        textarea:focus { border-color: var(--gold); }
        .seg { display: flex; gap: 6px; background: var(--panel-2); padding: 4px; border-radius: 10px; }
        .seg-b { flex: 1; border: 0; background: none; color: var(--dim); font: inherit; font-size: 14px;
          padding: 9px 6px; border-radius: 8px; cursor: pointer; }
        .seg-b.on { background: var(--panel); color: var(--ink); box-shadow: inset 0 0 0 1px var(--line-2); }
        .ai-box { display: grid; gap: 8px; }
        .topic { width: 100%; background: var(--panel-2); border: 1px solid var(--line); border-radius: 10px;
          padding: 13px; color: var(--ink); font: inherit; font-size: 15px; outline: none; }
        .topic:focus { border-color: var(--gold); }
        .ai-row { display: flex; gap: 8px; }
        .ai-row .primary { flex: none; padding: 11px 14px; font-size: 14px; }
        .lib { display: grid; gap: 8px; max-height: 300px; overflow: auto; }
        .lib-item { text-align: left; background: var(--panel-2); border: 1px solid var(--line); border-radius: 10px;
          padding: 11px 12px; color: var(--ink); cursor: pointer; display: grid; gap: 3px; }
        .lib-item:hover { border-color: var(--gold); }
        .lib-item b { font-size: 14px; }
        .lib-item span { font-size: 12px; color: var(--dim); }        .meta-row { display: flex; justify-content: space-between; font-size: 13px; color: var(--dim); }

        .thumbs { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
        .thumb { position: relative; padding: 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden;
          background: var(--panel-2); cursor: pointer; aspect-ratio: 9/16; }
        .thumb img, .thumb .hover-preview { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; display: block; }
        .thumb img { opacity: .82; }
        .thumb .nothumb { display: block; width: 100%; height: 100%; background: linear-gradient(160deg, #2E2E37, #17171B); }
        .thumb i { position: absolute; left: 0; right: 0; bottom: 0; font-style: normal; font-size: 12px;
          padding: 4px 0; text-align: center; background: rgba(0,0,0,.6); color: #fff; }
        .thumb:hover { border-color: var(--line-2); }
        .thumb.on { border-color: var(--gold); box-shadow: 0 0 0 2px rgba(240,180,41,.4); }
        .thumb.on img { opacity: 1; }

        .voices { display: grid; gap: 8px; }
        .voice-row { display: flex; align-items: stretch; gap: 8px; background: var(--panel-2);
          border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
        .voice-row.on { border-color: var(--gold); }
        .voice-main { flex: 1; display: grid; gap: 2px; text-align: left; background: none; border: 0;
          padding: 11px 12px; color: var(--ink); cursor: pointer; font: inherit; }
        .vname { font-size: 15px; font-weight: 700; }
        .vdesc { font-size: 12px; color: var(--dim); }
        .try { border: 0; border-left: 1px solid var(--line); background: rgba(255,255,255,.03); color: var(--gold);
          font-size: 13px; padding: 0 14px; cursor: pointer; }
        .try:disabled { color: var(--dim); cursor: default; }
        .check { display: flex; align-items: center; gap: 9px; font-size: 14px; color: var(--dim); margin-top: 6px; }
        .check input { width: 18px; height: 18px; accent-color: var(--gold); }

        .works { display: grid; gap: 10px; }
        .work { border: 1px solid var(--line); border-radius: 10px; padding: 12px; display: grid; gap: 5px; }
        .work b { font-size: 14px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .work-act { display: flex; gap: 14px; margin-top: 3px; font-size: 13px; }

        .out { display: grid; gap: 9px; border-top: 1px solid var(--line); padding-top: 14px; }
        .dim { font-size: 13px; color: var(--dim); line-height: 1.65; }
        .err { font-size: 13px; color: #ff8f7a; margin: 0; }
        .ok { font-size: 13px; color: #7ed69b; margin: 0; }

        .timeline { position: relative; flex: none; height: 236px; border-top: 1px solid var(--line);
          background: var(--panel); padding: 10px 16px 12px; display: flex; flex-direction: column; gap: 8px; }
        .tl-head { display: flex; align-items: baseline; gap: 14px; font-size: 13px; color: var(--dim); }
        .tl-head b { color: var(--ink); font-size: 14px; letter-spacing: .05em; }
        .tl-tip { margin-left: auto; font-size: 12px; color: rgba(255,255,255,.35); }
        .tl-run { color: var(--gold); margin-left: auto; }
        .tl-body { position: relative; flex: 1; display: grid; grid-template-columns: 52px 1fr; gap: 6px 10px; min-height: 0; }
        .tl-lane-label { font-size: 12px; color: var(--dim); align-self: center; }
        .tl-lane { display: flex; gap: 4px; min-width: 0; overflow: hidden; }
        .clip { flex: 1 1 0; min-width: 0; background: linear-gradient(180deg, #34343E, #26262E);
          border: 1px solid var(--line); border-radius: 6px; color: #D6D6DE; font-size: 12px;
          padding: 8px 8px; text-align: left; overflow: hidden; white-space: nowrap; cursor: pointer; }
        .clip:hover { border-color: var(--line-2); }
        .clip.on { border-color: var(--gold); color: #fff; }
        .clip span { display: block; overflow: hidden; text-overflow: ellipsis; }
        .texts .sub { flex: 1 1 0; min-width: 0; background: rgba(240,180,41,.12); border: 1px solid rgba(240,180,41,.28);
          color: #E3CE9C; font-size: 12px; border-radius: 6px; padding: 7px 8px; text-align: left;
          overflow: hidden; white-space: nowrap; cursor: pointer; }
        .clip.empty, .sub.empty { flex: 1; color: var(--dim); background: transparent; border-style: dashed; }
        .playhead { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--gold); pointer-events: none;
          box-shadow: 0 0 8px rgba(240,180,41,.6); }

        .mask { position: fixed; inset: 0; background: rgba(0,0,0,.62); display: grid; place-items: center; z-index: 40; }
        .dialog { width: 100%; max-width: 400px; background: var(--panel); border: 1px solid var(--line-2);
          border-radius: 14px; padding: 24px; display: grid; gap: 12px; }
        .dialog h3 { margin: 0 0 4px; font-size: 20px; }
        .dialog input { background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px;
          color: var(--ink); padding: 12px; font: inherit; font-size: 15px; outline: none; }
        .dialog input:focus { border-color: var(--gold); }
        .kicker { margin: 0; font-size: 12px; letter-spacing: .16em; color: var(--gold); }
        .player { width: min(380px, 90vw); }
        .player video { width: 100%; border-radius: 10px; background: #000; }

        @media (max-width: 1180px) {
          .body { grid-template-columns: 84px minmax(0,1fr) 320px; }
          .canvas { height: min(50vh, 440px); }
        }
      `}</style>
    </div>
  );
}













