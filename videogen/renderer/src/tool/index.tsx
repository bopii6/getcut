import React from 'react';
import {createRoot} from 'react-dom/client';
import {Player, type PlayerRef} from '@remotion/player';
import {renderMediaOnWeb, renderStillOnWeb} from '@remotion/web-renderer';
import {NiwoVideo, probeSink, type NiwoProps} from '../NiwoVideo';
import {api, lnkAcc, Toggle, Sheet} from './ui';
import {Account, type AuthSt, type Me, type SheetName} from './account';
import './ui.css';

// GetCut 成片台（单页全流程）：拖素材包 → 内容与配音确认 → 浏览器渲染合成
// → 取走带声 mp4。云端只做写稿/配音/分镜等轻活；画面与混音全在本页完成，
// 无录屏授权弹窗（web-renderer 走 WebCodecs）。

const qs = new URLSearchParams(location.search);
const DEVICE = qs.get('device') || '网页成片台';

// 出片靠这台电脑的浏览器算：审一遍浏览器/硬件/网络，只给三档结论，技术细节收进小字
type EnvResult = {
  hasVE: boolean; hw: boolean; cores: number; mem: number; online: boolean; tier: 1 | 2 | 3;
};
async function probeEnv(): Promise<EnvResult> {
  const nav = navigator as Navigator & {hardwareConcurrency?: number; deviceMemory?: number};
  const hasVE = typeof (window as unknown as {VideoEncoder?: unknown}).VideoEncoder !== 'undefined';
  let hw = false;
  if (hasVE) {
    try {
      const VE = (window as unknown as {
        VideoEncoder: {isConfigSupported: (c: Record<string, unknown>) => Promise<{supported?: boolean}>};
      }).VideoEncoder;
      // 1080×1920 至少要 H.264 level 4.0——用 42001f（level 3.1，上限 720p）探测会在
      // 任何显卡上都得到 false 的假警报（2026-09-23 用户实测踩中）
      const base = {width: 1080, height: 1920, framerate: 30, bitrate: 8_000_000};
      for (const codec of ['avc1.42002a', 'avc1.4d002a', 'avc1.64002a']) {
        try {
          const r = await VE.isConfigSupported(
            {...base, codec, hardwareAcceleration: 'prefer-hardware'});
          if (r.supported === true) {
            hw = true;
            break;
          }
        } catch { /* 单个 profile 探测失败不致命 */ }
      }
    } catch { /* 老浏览器没有这个 API */ }
  }
  const cores = nav.hardwareConcurrency || 0;
  const mem = nav.deviceMemory || 0;
  const online = navigator.onLine;
  let tier: 1 | 2 | 3 = 3;
  if (!hasVE || !online) tier = 1;
  else if (!hw || (cores > 0 && cores < 4) || (mem > 0 && mem < 8)) tier = 2;
  return {hasVE, hw, cores, mem, online, tier};
}
// 开发自查用：?frames=240 只渲前 240 帧（不改变正式行为）
const FRAMES_LIMIT = Math.max(0, parseInt(qs.get('frames') || '0', 10) || 0);
const THEME_KEY = 'vg-theme';
// 刷新前这一单在飞什么：回来先把它认回来，别让人以为整条丢了
const RESUME_KEY = 'vg-resume';
const NL = /\r?\n/;   // 口播文案按段切开
// 配色主题：名字与工作台的 data-theme 同一套，两页之间切换互相认得
const THEMES = [
  {id: 'ziyu', name: '石墨金'}, {id: 'xuanqing', name: '玄青'}, {id: 'shimo', name: '石墨'},
  {id: 'zhimu', name: '纸墨'}, {id: 'daiqing', name: '黛青'},
];

// 画面样式（模板）：清单以 /api/templates 为准，一句话讲清长相由这里负责。
// 缩略图与样片是 tools/make_template_previews.py 产的，模板改了要重跑那条命令。
interface Tpl {id: string; name: string}
const TPL_HINT: Record<string, string> = {
  editorial: '纸卡 + 标题带 + 信息卡，信息量最足',
  news: '深蓝正红 + 底部信息条，适合时政、突发',
  data: '浅色仪表盘：左边数据右边素材',
  poster: '黑底荧光黄、一句一屏，冲击力优先',
  bleed: '素材铺满全屏，沉浸感强',
  zhigu: '三段式：顶带标题 / 中间舞台动作 / 底带字幕',
  macro: '深色章节式：大数字与图形块',
};
const TPL_IMG = (id: string) => `/templates/tpl-${id}.png`;
const TPL_SAMPLE = (id: string) => `/templates/sample-${id}.mp4`;

/** 品牌记号：与工作台同一个方印（右下角那一刀就是「Cut」），颜色跟主题走 */
const Mark: React.FC<{size?: number}> = ({size = 26}) => (
  <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
    <path d="M9 0H23A9 9 0 0 1 32 9v9.5L18.5 32H9A9 9 0 0 1 0 23V9a9 9 0 0 1 9-9Z" fill="var(--acc)" />
    <path d="M10.5 8.6 23.6 15.6 10.5 22.6Z" fill="var(--acc-ink)" />
  </svg>
);

/** 音色按气质分组，与工作台同一口径 */
/** 图层交回的失败原文带 HTTP 码，客户看不懂：翻成一句照着能做的事 */
const layerHint = (e: unknown) => {
  const m = String((e as Error).message || e);
  if (/404/.test(m)) return '这台服务器版本旧了，重启服务再出一条就全';
  if (/410/.test(m) || /没有等图层/.test(m)) return '这一单已过期，重试这一步再出';
  if (/401|403|未登录/.test(m)) return '登录掉了，重新登录后再出';
  return m.replace(/交回失败：/, '').slice(0, 46);
};

const groupVoices = (list: Voice[]) => {
  const g: Record<string, Voice[]> = {沉稳播报: [], 清爽男声: [], 女声: [], 特色口音: [], 其他: []};
  for (const v of list) {
    if (/口音/.test(v.label)) g.特色口音.push(v);
    else if (/女声/.test(v.label)) g.女声.push(v);
    else if (/新闻|浑厚|沉稳|解说|老年/.test(v.label)) g.沉稳播报.push(v);
    else if (/男声|少年/.test(v.label)) g.清爽男声.push(v);
    else g.其他.push(v);
  }
  return Object.entries(g).filter(([, v]) => v.length);
};

type Phase = 'drop' | 'importing' | 'config' | 'prepping' | 'ready'
  | 'rendering' | 'uploading' | 'done' | 'error';

const FPS = 30;
const COMP_W = 1080;
const COMP_H = 1920;

/**
 * 剪映分轨草稿要出几张卡片层：优先用云端随 props 下发的清单（与
 * draft_build.build_stills 同一份算法），老单子没这个字段时按同一公式兜底。
 */
const draftStillsOf = (props: NiwoProps) => {
  if (props.draftStills?.length) return props.draftStills;
  const total = props.durationInFrames;
  return props.shots.map((s, i) => {
    const end = Math.round((Number(s.endMs) / 1000) * FPS) - 2;
    const start = Math.round((Number(s.startMs) / 1000) * FPS) + 1;
    return {id: `shot_${String(i).padStart(3, '0')}`,
            frame: Math.max(0, Math.min(total - 1, Math.max(start, end)))};
  });
};

interface JobPack {
  job: string;
  props: NiwoProps;
  files: {path: string; size: number}[];
}
interface BundleInfo {
  name: string; title: string; script: string; estSeconds: number;
  hookLines?: {text: string; highlight?: string}[];
  sources?: string[];
  assets?: {kind: string}[];
}
interface Voice {id: string; label: string; provider?: string}
interface Project {project_id: string; title?: string; created?: string;
  assets_count?: number; renders_count?: number; renders?: {id: string; file?: string}[]}

const Step: React.FC<{n: number; title: string; state: 'todo' | 'active' | 'done';
                     children?: React.ReactNode; summary?: string; open?: boolean}> =
  ({n, title, state, children, summary, open}) => (
    <div className={`step${state === 'active' ? ' on' : ''}${state === 'done' ? ' ok' : ''}
      ${state === 'todo' ? ' dim' : ''}`}>
      <div className="no">{state === 'done' ? '✓' : n}</div>
      <div className="wrap">
        <div className="t">{title}</div>
        {(state === 'done' || state === 'active') && summary
          ? <div className="m">{summary}</div> : null}
        {(state === 'active' || open) && children ? <div className="c">{children}</div> : null}
      </div>
    </div>
  );

/**
 * 剪映分轨草稿的图层：一张底板 + 每镜一张透明卡片 + 卡片文字几何。
 * 成片与图层共用这一个 composition 描述，尺寸/帧率一旦对不上，卡片在剪映里就会错位。
 */
const compositionOf = (durationInFrames: number) => ({
  id: 'main',
  component: NiwoVideo as React.ComponentType<Record<string, unknown>>,
  width: COMP_W,
  height: COMP_H,
  fps: FPS,
  durationInFrames,
});

const App: React.FC = () => {
  const [phase, setPhase] = React.useState<Phase>('drop');
  const [me, setMe] = React.useState<Me | null>(null);
  const [authst, setAuthst] = React.useState<AuthSt>({smtp: false, dev_email: false, token_auth: false, locked: false, open: false});
  // /api/auth/status 回来之前谁都不算"查过"：拿默认值当结论会把访客当成开放模式，
  // 于是落地页第一帧就去领单、第一帧就 401。
  const [authReady, setAuthReady] = React.useState(false);
  const [sheet, setSheet] = React.useState<SheetName>('');
  const [authNote, setAuthNote] = React.useState('');
  const [brandOn, setBrandOn] = React.useState(false);
  const [toast, setToast] = React.useState('');
  const [err, setErr] = React.useState('');
  const [upPct, setUpPct] = React.useState(0);
  const [bundle, setBundle] = React.useState<BundleInfo | null>(null);
  const [projectId, setProjectId] = React.useState('');
  const [jobId, setJobId] = React.useState('');
  const [prepMsg, setPrepMsg] = React.useState('');
  const [prepPct, setPrepPct] = React.useState(0);
  const [jy, setJy] = React.useState('');
  const [jyBusy, setJyBusy] = React.useState(false);
  const [libJyKey, setLibJyKey] = React.useState('');   // 作品库里正在打包剪映草稿的项目
  // 本机环境体检：用户点一下，我们把浏览器/硬件/网络审一遍，只给三档结论，技术细节收进小字
  const [env, setEnv] = React.useState<EnvResult | null>(null);
  const [envBusy, setEnvBusy] = React.useState(false);
  const runEnvCheck = React.useCallback(async () => {
    if (envBusy) return;
    setEnvBusy(true);
    const [r] = await Promise.all([probeEnv(), new Promise((res) => setTimeout(res, 700))]);
    setEnv(r);
    setEnvBusy(false);
  }, [envBusy]);
  const [voices, setVoices] = React.useState<Voice[]>([]);
  const [music, setMusic] = React.useState<{file: string; name: string; mood?: string}[]>([]);
  const [tpls, setTpls] = React.useState<Tpl[]>([]);
  const [tplSample, setTplSample] = React.useState('');
  const [cfg, setCfg] = React.useState({voice: '', bgm: '', template: '',
                                        subtitles: true, sfx: true, sources: true});
  const [pack, setPack] = React.useState<JobPack | null>(null);
  const [prewarmDone, setPrewarmDone] = React.useState(0);
  const [pct, setPct] = React.useState(0);
  const [msg, setMsg] = React.useState('');
  const [finalUrl, setFinalUrl] = React.useState<string | null>(null);
  const [cloudOk, setCloudOk] = React.useState<boolean | null>(null);
  const [layerMsg, setLayerMsg] = React.useState('');
  const [layersOk, setLayersOk] = React.useState<boolean | null>(null);
  const [layerErr, setLayerErr] = React.useState('');
  const [layerNote, setLayerNote] = React.useState('');
  const [theme, setTheme] = React.useState(() => localStorage.getItem(THEME_KEY) || 'ziyu');
  const [hot, setHot] = React.useState(false);
  const [elapsed, setElapsed] = React.useState(0);
  const [prepStage, setPrepStage] = React.useState('');
  const [prevKey, setPrevKey] = React.useState('');
  const [resumeJob, setResumeJob] = React.useState('');
  const [showScript, setShowScript] = React.useState(false);
  const [stalled, setStalled] = React.useState(false);
  const [lib, setLib] = React.useState<Project[] | null>(null);
  const [libMsg, setLibMsg] = React.useState('');
  const playerRef = React.useRef<PlayerRef>(null);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);
  const packRef = React.useRef<JobPack | null>(null);
  const jobIdRef = React.useRef('');
  const autoRef = React.useRef(false);
  const pendingZip = React.useRef<File | null>(null);
  const meRef = React.useRef<Me | null>(null);
  const phaseRef = React.useRef<Phase>('drop');
  const t0Ref = React.useRef(0);
  phaseRef.current = phase;
  jobIdRef.current = jobId;

  React.useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  // 一条进度条要配一个「已经过了多久」，否则 2 分钟像 20 分钟
  React.useEffect(() => {
    const busy = phase === 'prepping' || phase === 'ready' || phase === 'rendering'
      || phase === 'uploading';
    if (!busy) return;
    if (!t0Ref.current) t0Ref.current = Date.now();
    const iv = setInterval(() => setElapsed(Math.round((Date.now() - t0Ref.current) / 1000)), 1000);
    return () => clearInterval(iv);
  }, [phase]);

  // 试听是「点一下听一段」，不是「挂在那儿等我关」：进入下一步就该自己停
  const stopPreview = React.useCallback(() => {
    const a = audioRef.current;
    audioRef.current = null;
    setPrevKey('');
    if (a) {
      a.pause();
      a.src = '';
    }
  }, []);

  React.useEffect(() => {
    if (phase !== 'config') stopPreview();
  }, [phase, stopPreview]);

  // 刷新/关页时把在飞的单主动交还给队列：不等云端 10 分钟失联判定，
  // 回来这一页就能立刻重新领上（素材已在 HTTP 缓存里，几乎秒进下一步）
  React.useEffect(() => {
    const inFlight = () => {
      const cur = packRef.current;
      const p = phaseRef.current;
      if (!cur || p === 'done' || p === 'error') return null;
      return cur.job;
    };
    const leave = () => {
      const job = inFlight();
      if (!job) return;
      fetch(`/api/agent/job/${job}/progress?device=${encodeURIComponent(DEVICE)}`, {
        method: 'POST',
        keepalive: true,
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({pct: 0, detail: '页面刷新，先交还任务',
                              requeue: true, voluntary: true}),
      }).catch(() => {});
    };
    addEventListener('pagehide', leave);
    return () => removeEventListener('pagehide', leave);
  }, []);

  // 这一单是我上一条留下的：写进 sessionStorage，回来才有话可说
  React.useEffect(() => {
    const job = pack?.job || jobId;
    const live = job && (phase === 'prepping' || phase === 'ready' || phase === 'rendering');
    if (live) sessionStorage.setItem(RESUME_KEY, String(job));
    else if (phase === 'done' || phase === 'drop') sessionStorage.removeItem(RESUME_KEY);
  }, [phase, jobId, pack]);

  // 刷新回来：上一条已交还队列，正在重新领（素材在 HTTP 缓存里，几乎秒过缓存段）
  React.useEffect(() => {
    const job = sessionStorage.getItem(RESUME_KEY);
    if (job) setResumeJob(job);
  }, []);

  const say = (m: string) => {
    setToast(m);
    setTimeout(() => setToast((t) => (t === m ? '' : t)), 3200);
  };

  // 付费档：右上角那一格摆的是他自己的 Logo/文字（设了才出），没设就干净出片
  const loadBrand = React.useCallback(() => api('/api/brand').then((d) => {
    const b = d as {has_logo?: boolean; brand?: {watermark_text?: string}};
    setBrandOn(!!(b.has_logo || b.brand?.watermark_text));
  }).catch(() => setBrandOn(false)), []);

  // 登录成功后要立刻能拿到档位（水印、续传导入都读它），所以 ref 与 state 一起写
  const refreshMe = React.useCallback(() => api('/api/me')
    .then((d) => {
      meRef.current = d as unknown as Me;
      setMe(meRef.current);
      if (meRef.current.tier !== 'free') void loadBrand();
      else setBrandOn(false);
    })
    .catch(() => {
      meRef.current = null;
      setMe(null);
    }), [loadBrand]);

  const report = async (p: number, detail: string, requeue = false) => {
    const cur = packRef.current;
    if (!cur) return false;
    try {
      const r = await fetch(`/api/agent/job/${cur.job}/progress?device=${encodeURIComponent(DEVICE)}`, {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({pct: p, detail, requeue}),
      });
      const d = await r.json().catch(() => ({}));
      return !!d.cancel;
    } catch (_) {
      return false;
    }
  };

  // 克隆完「我的声音」要重新拉一次音色目录
  const loadVoices = React.useCallback(() => api('/api/voices').then((d) => {
    const list = (d.voices as Voice[]) || [];
    if (list.length) {
      setVoices(list);
      setCfg((c) => ({...c, voice: c.voice || String(d.default || list[0].id)}));
    }
  }).catch(() => {}), []);

  // ---- 目录：音色 + 曲库（进页面拉一次） ----
  React.useEffect(() => {
    refreshMe();
    api('/api/auth/status').then((d) => {
      setAuthst(d as unknown as AuthSt);
      setAuthReady(true);
    }).catch(() => setAuthReady(true));
    void loadVoices();
    api('/api/music').then((d) => {
      const list = (Array.isArray(d) ? d : (d.music as typeof music)) || [];
      setMusic(list);
    }).catch(() => {});
    api('/api/templates').then((d) => {
      const list = (d.templates as Tpl[]) || [];
      if (!list.length) return;
      setTpls(list);
      // 服务端没给默认就取第一套：选中的那套必须真的能出片，别留一个空 format
      const def = String(d.default || '');
      setCfg((c) => (c.template ? c
        : {...c, template: list.some((t) => t.id === def) ? def : list[0].id}));
    }).catch(() => {});
  }, []);

  // ---- 成片台轮询：领任务（本页提交的或别的页提交的都走这里） ----
  // 访客（未登录）不开这条轮询：poll 一定 401，落地页会凭空糊一屏红字，
  // 说的还是"这一单已作废"——可他连单都还没有。开放模式例外，问服务端要结论别自己猜。
  const mayPoll = authReady && (!!me || authst.open);

  React.useEffect(() => {
    if (!mayPoll) return;
    let alive = true;
    let fails = 0;
    // 重试要有上限、要分性质。以前这里是无限循环：签名密钥轮换或登录过期之后，
    // 页面每 3 秒撞一次 401，客户看到的是"已重试 447 次，还在试"，
    // 而正确动作只有一个 —— 重新登录。401/403/410 属于"再试也没用"，直接停。
    const DEAD_STATUSES = [401, 403, 410];
    const MAX_FAILS = 8;
    let stage = '领单';
    (async () => {
      for (;;) {
        if (!alive) return;
        try {
          stage = '领单';
          const r = await fetch(`/api/agent/poll?wait=1&device=${encodeURIComponent(DEVICE)}`,
            {headers: {'x-agent-final': '1'}, credentials: 'same-origin'});
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const data = await r.json();
          if (!data.job) continue;
          (window as unknown as Record<string, unknown>).remotion_staticBase =
            `/agent-media/${data.job}`;
          const p: JobPack = {job: data.job, props: data.props, files: data.files || []};
          if (!alive) return;
          // 刷新前那条是这一页自己交还的：领回来就直接接着跑，不再要用户点一次
          const resuming = sessionStorage.getItem(RESUME_KEY) === data.job;
          if (resuming) {
            sessionStorage.removeItem(RESUME_KEY);
            setResumeJob('');
            t0Ref.current = Date.now();
            say('已接回刚才那一条，接着生成');
          }
          setPack(p);
          packRef.current = p;
          setStalled(false);
          autoRef.current = resuming
            || (!!jobIdRef.current && jobIdRef.current === data.job);
          setPhase(autoRef.current ? 'prepping' : 'ready');
          setPrewarmDone(0);
          stage = '素材';        // 下面这段失败才是"素材拉不下来"
          let done = 0;
          // 预取期也要报心跳：云端靠「多久没说话」判断成片台还活着。
          // 不报的话，一条 3Mbps 的慢线拉几十兆素材就能被误判成失联。
          const beat = setInterval(() => {
            void report(0, `缓存素材 ${done}/${p.files.length}`);
          }, 5000);
          try {
            for (const f of p.files) {
              const url = `/agent-media/${p.job}/${f.path}`;
              let why = '未取';
              for (let a = 0; a < 2 && why; a++) {
                try {
                  const res = await fetch(url, {cache: 'force-cache'});
                  const ct = res.headers.get('content-type') || '';
                  // 拿回 JSON 说明服务端给的是错误页（401 登录掉了 / 404 这一单已作废）。
                  // 它照样进浏览器缓存，下次 force-cache 直接回放给解码器，
                  // 报出来就是一句莫名其妙的 "Unknown container format"
                  if (!res.ok) why = `HTTP ${res.status}`;
                  else if (ct.includes('json')) why = '云端回的是错误信息，不是素材';
                  else why = '';
                } catch (_) {
                  why = '网络中断';
                }
                if (why) await new Promise((r) => setTimeout(r, 800));
              }
              if (why) {
                throw new Error(`素材没取回来：${f.path}（${why}）——刷新这一页重新领单`);
              }
              done += 1;
              setPrewarmDone(done);
            }
            await document.fonts.ready.catch(() => {});
          } finally {
            clearInterval(beat);
          }
          if (!alive) return;
          fails = 0;            // 这一单备料成功，之前的失败计数作废
          setErr('');
          if (autoRef.current) startRender();
          else setPhase('ready');
          return;
        } catch (e) {
          if (!alive) return;
          const msg = String((e as Error).message || e);
          const dead = DEAD_STATUSES.some((c) => msg.includes(`HTTP ${c}`));
          const whichStep = stage === '领单' ? '联系不上云端' : '素材反复拉不下来';
          console.error('GetCut 准备失败', e);
          if (packRef.current) {
            await report(0, '浏览器端准备失败，退回队列', true).catch(() => {});
            packRef.current = null;
            setPack(null);
          }
          // 停下来给人看，而不是每 3 秒撞一次墙：再试也没用的（登录掉了 / 这一单不是你的），
          // 或者已经试够 8 次的，都直接说下一步该干什么。
          if (dead || ++fails > MAX_FAILS) {
            if (msg.includes('HTTP 401')) {
              // 会话真的没了：把顶栏换回「登录」，别让人对着付费档的界面空等
              meRef.current = null;
              setMe(null);
            }
            setErr(msg.includes('HTTP 401')
              ? '登录状态已失效（或还没登录）：点右上角「登录」重新登录一次，再刷新这一页领单'
              : msg.includes('HTTP 403')
                ? '这一单不属于当前账号：刷新这一页重新领单；若反复如此，确认这一单是用哪个账号提交的'
                : msg.includes('HTTP 410')
                  ? '这一单已被云端收回（服务器重启或超时）：刷新这一页就会重新领单'
                  : `${whichStep}（已试 ${MAX_FAILS} 次）：${msg.slice(0, 60)} —— 刷新这一页重新领单`);
            return;
          }
          if (fails >= 2) {
            setErr(`${whichStep}：${msg.slice(0, 60)} · 已重试 ${fails} 次，还在试`);
          }
          await new Promise((res) => setTimeout(res, Math.min(1000 * 2 ** fails, 15000)));
        }
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mayPoll]);

  // ---- 导入：建项目 → 上传 zip → 挂载 → 读摘要 ----
  const importZip = async (file?: File) => {
    if (!file || phaseRef.current === 'importing') return;
    // 素材包是要花钱的活，账号先到位；本机开放模式（服务端说 open 才算）不拦。
    // authReady 之前不拦：那一瞬间的判断不可信，真被服务端 401 了下面的 catch 会补上登录面板。
    if (!meRef.current && authReady && !authst.open) {
      pendingZip.current = file;
      setAuthNote(`登录后接着导入「${file.name}」，不用重拖一次。`);
      setSheet('auth');
      return;
    }
    setErr('');
    setPhase('importing');
    setUpPct(0);
    try {
      const r = await api('/api/projects/create', {method: 'POST',
        headers: {'content-type': 'application/json'}, body: '{}'});
      const pid = String(r.project_id || '');
      if (!pid) throw new Error('创建项目失败');
      const up = await new Promise<{name: string}>((resolve, reject) => {
        const fd = new FormData();
        fd.append('file', file);
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/upload');
        xhr.upload.onprogress = (ev) => {
          if (ev.lengthComputable) setUpPct(Math.round(ev.loaded / ev.total * 100));
        };
        xhr.onload = () => {
          let d: Record<string, unknown> = {};
          try { d = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
          if (xhr.status >= 200 && xhr.status < 300 && d.name) resolve(d as {name: string});
          else reject(new Error(String(d.error || `HTTP ${xhr.status}`)));
        };
        xhr.onerror = () => reject(new Error('网络中断，上传失败'));
        xhr.send(fd);
      });
      await api(`/api/projects/${pid}/mount`, {method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({bundle: up.name, title: up.name})});
      const b = await api(`/api/bundle/${encodeURIComponent(up.name)}`) as unknown as BundleInfo;
      setProjectId(pid);
      setBundle(b);
      setPhase('config');
    } catch (e) {
      const m = String((e as Error).message || e);
      setErr(m);
      setPhase('drop');
      if (/未登录/.test(m)) {          // 会话过期：把包留在手里，登录完接着导
        pendingZip.current = file;
        setAuthNote(`登录后接着导入「${file.name}」，不用重拖一次。`);
        setSheet('auth');
      }
    }
  };

  // ---- 提交：/api/build → 盯云端备料（配音/分镜），成片台领单后自动开渲 ----
  const submit = async () => {
    if (!bundle) return;
    setErr('');
    setPhase('prepping');
    t0Ref.current = Date.now();
    setElapsed(0);
    setStalled(false);
    setPrepPct(0);
    setPrepStage('queued');
    setPrepMsg('云端备料中…');
    try {
      const r = await api('/api/build', {method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({project_id: projectId, bundle: bundle.name,
          format: cfg.template,
          voice: cfg.voice, bgm: cfg.bgm, sfx: cfg.sfx, sfxMode: cfg.sfx ? 'full' : 'off',
          subtitles: cfg.subtitles, sources: cfg.sources,
          watermark: true,   // 右上角水印常开：留空显示「Powered by GetCut」，设了品牌则出品牌水印
          useLlm: true})});
      const jid = String(r.job || '');
      if (!jid) throw new Error(String(r.error || '启动失败'));
      setJobId(jid);
      jobIdRef.current = jid;
      const tick = async () => {
        for (;;) {
          await new Promise((res) => setTimeout(res, 2000));
          if (jobIdRef.current !== jid) return;
          let j: Record<string, unknown>;
          try {
            j = await api(`/api/job/${jid}`) as Record<string, unknown>;
          } catch (_) {
            continue;
          }
          const stage = String(j.stage || '');
          if (stage === 'error') {
            setErr(String(j.detail || '云端备料失败'));
            jobIdRef.current = '';
            setPhase('config');
            return;
          }
          if (stage === 'done' || stage === 'cancelled') return;
          setPrepMsg(String(j.detail || stage));
          setPrepStage(stage);
          setPrepPct(Number(j.progress ?? 0));
          // 这一单被别的页面（含自己另开的标签页）领走了：本页领不到，
          // 只能等云端「多久没心跳」判定收回 —— 不告诉人就是一直转圈
          setStalled(!packRef.current && stage === 'render'
            && /已领取/.test(String(j.detail || ''))
            && Date.now() - t0Ref.current > 60_000);
          if (packRef.current && packRef.current.job === jid) return;  // 已领单，交给渲染线
        }
      };
      void tick();
    } catch (e) {
      const m = String((e as Error).message || e);
      setErr(m);
      setPhase('config');
      if (/额度|升级|水印/.test(m)) setSheet('pricing');   // 付费墙：当场给出权益页
    }
  };

  // ---- 剪映分轨图层：成片交回后接着在本页出（服务器已无 Chrome） ----
  const exportDraftLayers = async (cur: JobPack) => {
    const props = cur.props;
    const stills = draftStillsOf(props);
    const last = Math.max(0, props.durationInFrames - 1);
    const post = async (name: string, body: Blob | string, type: string) => {
      const r = await fetch(`/api/agent/job/${cur.job}/layer?name=${encodeURIComponent(name)}&device=${encodeURIComponent(DEVICE)}`,
        {method: 'POST', headers: {'content-type': type}, body});
      if (!r.ok) {
        const d = await r.json().catch(() => ({}) as Record<string, unknown>);
        throw new Error(`${name} 交回失败：${String(d.error || `HTTP ${r.status}`)}`);
      }
    };
    const still = async (extra: Record<string, unknown>, frame: number) => {
      // 探针在 commit 时同步量字，字体没落地就会量到回退字体的宽度
      await document.fonts.ready.catch(() => {});
      const res = await renderStillOnWeb({
        composition: compositionOf(props.durationInFrames),
        inputProps: {...(props as unknown as Record<string, unknown>), ...extra},
        frame: Math.max(0, Math.min(last, frame)),
        delayRenderTimeoutInMilliseconds: 180_000,
        signal: abortRef.current?.signal ?? null,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any);
      return res.blob({format: 'png'});
    };
    const sink = probeSink();
    setLayerMsg('正在出剪映底板…');
    await post('base.png', await still({exportMode: 'base'}, stills[0]?.frame ?? 0),
               'application/octet-stream');
    for (let i = 0; i < stills.length; i++) {
      setLayerMsg(`正在出剪映卡片层 ${i + 1}/${stills.length}`);
      delete sink[stills[i].id];
      const png = await still({exportMode: 'card', probeTag: stills[i].id}, stills[i].frame);
      await post(`cards/${stills[i].id}.png`, png, 'application/octet-stream');
    }
    const texts: Record<string, unknown[]> = {};
    for (const s of stills) if (sink[s.id]?.length) texts[s.id] = sink[s.id];
    const nTexts = Object.keys(texts).length;
    setLayerNote(`底板 1 张 + 卡片 ${stills.length} 张 + ${nTexts} 镜可改文字`);
    await post('texts.json', JSON.stringify(texts), 'application/json');
  };

  // ---- 渲染 + 交回 ----
  const startRender = async () => {
    const cur = packRef.current;
    if (!cur) return;
    playerRef.current?.pause();
    setPhase('rendering');
    setMsg('');
    const ac = new AbortController();
    abortRef.current = ac;
    const total = cur.props.durationInFrames;
    let lastReport = 0;
    try {
      const {getBlob} = await renderMediaOnWeb({
        composition: compositionOf(total),
        inputProps: cur.props as unknown as Record<string, unknown>,
        muted: false,
        videoCodec: 'h264',
        container: 'mp4',
        // 渲染期让位频率调低：预览已卸载，页面只需响应进度条；换回更高吞吐
        pageResponsiveness: 'low',
        delayRenderTimeoutInMilliseconds: 180_000,
        // 解码缓存上限写死：Remotion 不传就按「客户机可用内存的一半」放大（上限 20GB），
        // 等于让它自己去猜这台电脑还能吃多少——2026-09-21 线上就是这么顶到
        // Chrome "Aw, Snap! Out of Memory" 的。1GB 是 Remotion 自己的兜底默认值。
        mediaCacheSizeInBytes: 1024 * 1024 * 1024,
        signal: ac.signal,
        frameRange: FRAMES_LIMIT > 0 && FRAMES_LIMIT < total ? [0, FRAMES_LIMIT] : null,
        onProgress: (p) => {
          const q = Math.min(97, Math.round(p.progress * 97));
          setPct(q);
          document.title = `${q}% · GetCut 成片台`;
          const now = Date.now();
          if (now - lastReport > 2500) {
            lastReport = now;
            report(q, `浏览器渲染中 ${Math.round(p.progress * 100)}%`).then((cancel) => {
              if (cancel) ac.abort();
            });
          }
        },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any);
      const blob = await getBlob();
      setFinalUrl(URL.createObjectURL(blob));
      setPhase('uploading');
      setMsg('正在交回云端…');
      const r = await fetch(`/api/agent/job/${cur.job}/visual?final=1&device=${encodeURIComponent(DEVICE)}`, {
        method: 'POST',
        headers: {'content-type': 'application/octet-stream'},
        body: blob,
      });
      const ok = r.ok;
      setCloudOk(ok);
      if (ok) {
        await report(100, '浏览器成片已交回');
        try {
          window.parent.postMessage({type: 'getcut-export-done', job: cur.job}, '*');
        } catch (_) {}
      }
      setPhase('done');
      setPct(100);
      // 图层出图排在成片之后：慢一点、失败都不要紧，大不了草稿退回整条切片
      if (ok) {
        setLayersOk(null);
        setLayerErr('');
        setLayerNote('');
        try {
          await exportDraftLayers(cur);
          setLayersOk(true);
        } catch (e) {
          setLayersOk(false);
          setLayerErr(layerHint(e));
          console.warn('GetCut 剪映图层出图失败', (e as Error).stack || String(e));
        } finally {
          setLayerMsg('');
        }
      }
    } catch (e) {
      setPhase('error');
      setErr(String((e as Error).message || e).slice(0, 200));
    }
  };

  const reset = () => {
    jobIdRef.current = '';
    packRef.current = null;
    autoRef.current = false;
    setPack(null);
    setBundle(null);
    setProjectId('');
    setJobId('');
    setFinalUrl(null);
    setCloudOk(null);
    setLayerMsg('');
    setLayerErr('');
    setLayerNote('');
    setLayersOk(null);
    setPct(0);
    setErr('');
    t0Ref.current = 0;
    setElapsed(0);
    setPrepPct(0);
    setPrepStage('');
    setShowScript(false);
    setResumeJob('');
    stopPreview();
    setPhase('drop');
  };

  const openLib = () => {
    setLibMsg('正在取项目列表…');
    setLib([]);
    api('/api/projects').then((d) => {
      const ps = ((d.projects || d) as Project[]) || [];
      setLib(ps.slice().sort((a, b) => String(b.created || '').localeCompare(String(a.created || ''))));
      setLibMsg('');
    }).catch((e) => { setLib(null); setLibMsg(String((e as Error).message || e)); });
  };

  const playPreview = (key: string, url: string) => {
    if (prevKey === key) { stopPreview(); return; }   // 再点一次就是停
    stopPreview();                                    // 换一条：先把上一条掐了，别叠着放
    const a = new Audio(url);
    audioRef.current = a;
    setPrevKey(key);
    a.onended = () => { if (audioRef.current === a) stopPreview(); };
    void a.play().catch(() => {
      stopPreview();
      setErr('浏览器拦了自动播放，再点一次试试');
    });
  };

  // 直接跳下载时，浏览器在服务端打包完成前只能显示 0%。先把等待阶段说清楚，
  // 收到响应后再读取流，这样用户能看到真实的网络下载进度。
  const downloadDraftPackage = async (url: string, notify: (message: string) => void,
                                      fallbackName: string) => {
    notify('正在打包剪映草稿…首次导出会整理分镜素材，页面没有卡住');
    const r = await fetch(url);
    if (!r.ok) {
      const d = await r.json().catch(() => ({} as Record<string, unknown>));
      throw new Error(String(d.error || `HTTP ${r.status}`));
    }
    const total = Number(r.headers.get('content-length') || 0);
    if (!r.body) {
      const blob = await r.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = fallbackName;
      a.click();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
      notify('草稿包已下载：解压后双击「一键导入剪映.bat」');
      return;
    }
    const reader = r.body.getReader();
    const chunks: BlobPart[] = [];
    let received = 0;
    let lastPct = -1;
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      if (part.value) {
        chunks.push(part.value as BlobPart);
        received += part.value.byteLength;
        const pct = total > 0 ? Math.min(99, Math.round(received / total * 100)) : -1;
        if (pct !== lastPct) {
          lastPct = pct;
          notify(pct >= 0 ? `正在下载剪映草稿… ${pct}%` :
            `正在下载剪映草稿… ${(received / 1024 / 1024).toFixed(1)} MB`);
        }
      }
    }
    const blob = new Blob(chunks, {type: r.headers.get('content-type') || 'application/zip'});
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = fallbackName;
    a.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
    notify('草稿包已下载：解压后双击「一键导入剪映.bat」');
  };

  // 导入剪映：装了小助手的机器一键直达；没装就回落成下载草稿包
  const jianying = async () => {
    if (!projectId || !jobId || jyBusy) return;
    setJyBusy(true);
    setJy('正在准备剪映草稿…首次会整理分镜素材，页面没有卡住');
    try {
      const res = await api(`/api/projects/${projectId}/renders/${jobId}/jianying-import`,
        {method: 'POST'});
      if (res.installed) {
        setJy('已导入剪映，打开剪映就能看到');
      } else if (res.protocol && res.pull) {
        setJy('正在唤起导入小助手…（浏览器问「打开」时点允许）');
        let woke = false;
        const off = () => { woke = true; };
        window.addEventListener('blur', off);
        document.addEventListener('visibilitychange', off);
        location.href = `getcut://import?src=${encodeURIComponent(location.origin + String(res.pull))}`;
        setTimeout(() => {
          window.removeEventListener('blur', off);
          document.removeEventListener('visibilitychange', off);
          if (!woke) {
            setJy('这台电脑没装导入小助手：草稿包已改为下载，解压后双击「一键导入剪映.bat」；不装也能用——剪映里直接导入那个 MP4。');
            void downloadDraftPackage(
              `/api/projects/${projectId}/renders/${jobId}/jianying-draft`, setJy,
              `GetCut-剪映草稿-${jobId.slice(-6)}.zip`,
            ).catch((e) => setJy('下载失败：' + String((e as Error).message || e)));
          }
        }, 2600);
      } else {
        await downloadDraftPackage(
          `/api/projects/${projectId}/renders/${jobId}/jianying-draft`, setJy,
          `GetCut-剪映草稿-${jobId.slice(-6)}.zip`,
        );
      }
    } catch (e) {
      setJy('导入失败：' + String((e as Error).message));
    } finally {
      setTimeout(() => setJyBusy(false), 3000);
    }
  };

  // 作品库里补一刀：当时没进剪映的成片，随时可以再导入——同一套三路逻辑
  const libJy = async (pid: string, rid: string) => {
    if (libJyKey) return;
    setLibJyKey(pid);
    try {
      const res = await api(`/api/projects/${pid}/renders/${rid}/jianying-import`,
        {method: 'POST'});
      if (res.installed) {
        say('已导入剪映，打开剪映就能看到');
      } else if (res.protocol && res.pull) {
        say('正在唤起导入小助手…（浏览器问「打开」时点允许）');
        let woke = false;
        const off = () => { woke = true; };
        window.addEventListener('blur', off);
        document.addEventListener('visibilitychange', off);
        location.href = `getcut://import?src=${encodeURIComponent(location.origin + String(res.pull))}`;
        setTimeout(() => {
          window.removeEventListener('blur', off);
          document.removeEventListener('visibilitychange', off);
          if (!woke) {
            say('没装导入小助手：草稿包已改为下载，解压后双击「一键导入剪映.bat」');
            void downloadDraftPackage(
              `/api/projects/${pid}/renders/${rid}/jianying-draft`, say,
              `GetCut-剪映草稿-${rid.slice(-6)}.zip`,
            ).catch((e) => say('下载失败：' + String((e as Error).message || e)));
          }
        }, 2600);
      } else {
        await downloadDraftPackage(
          `/api/projects/${pid}/renders/${rid}/jianying-draft`, say,
          `GetCut-剪映草稿-${rid.slice(-6)}.zip`,
        );
      }
    } catch (e) {
      say('导入失败：' + String((e as Error).message));
    } finally {
      setTimeout(() => setLibJyKey(''), 3000);
    }
  };

  const durS = pack ? pack.props.durationInFrames / 30
    : bundle ? bundle.estSeconds : 0;
  const nImg = bundle?.assets ? bundle.assets.filter((a) => a.kind === 'image').length : 0;
  const nVid = bundle?.assets ? bundle.assets.filter((a) => a.kind === 'video').length : 0;
  const title = bundle?.title || pack?.props.headline?.lines?.[0]?.text || '';
  const fileName = `${(title || 'getcut').replace(/[\\/:*?"<>|\[\]]/g, '')}-${(pack?.job || jobId).slice(-6)}.mp4`;
  const nChars = (bundle?.script || '').length;
  const tplName = tpls.find((t) => t.id === cfg.template)?.name || cfg.template;
  const mm = (s: number) => `${Math.floor(Math.max(0, s) / 60)}:${String(Math.round(Math.max(0, s)) % 60).padStart(2, '0')}`;
  const mmss = mm(elapsed);
  const codecOk = typeof (window as unknown as {VideoEncoder?: unknown}).VideoEncoder !== 'undefined';

  // 每一步对应流程线上的位置：号小于当前=已完成，等于=进行中
  const SEQ: Record<Phase, number> = {
    drop: 1, importing: 1, config: 2, prepping: 3, ready: 3, rendering: 3,
    uploading: 3, done: 4, error: 3,
  };
  const st = (n: number): 'todo' | 'active' | 'done' => {
    if (phase === 'done') return n <= 4 ? 'done' : 'todo';
    const cur = SEQ[phase];
    return n < cur ? 'done' : n === cur ? 'active' : 'todo';
  };

  // 一条进度条走到底，按各段真实墙钟分格子：备料是最慢的一段，不能再只给它 5 个点
  // （旧算法把服务器 3~42 的备料进度压成 2~7.4%，四分钟只挪 1 格，看着就像骗人）
  const SEG = {prep: 38, cache: 8, render: 49, hand: 5};
  const PREP_TOP = 42;      // 云端备料在服务器 8 段进度里走到 ~42 就交单
  const gen = phase === 'prepping' || phase === 'ready' || phase === 'rendering'
    || phase === 'uploading';
  const bar = phase === 'done' ? 100
    : phase === 'uploading' ? 100 - SEG.hand
    : phase === 'rendering' ? SEG.prep + SEG.cache + (pct / 100) * SEG.render
    : pack ? SEG.prep + (prewarmDone / Math.max(1, pack.files.length)) * SEG.cache
    : phase === 'prepping' ? Math.min(SEG.prep, (prepPct / PREP_TOP) * SEG.prep)
    : 0;

  // 一个动作一个词：这一屏最大的字只说「此刻在干什么」
  const ACT: Record<string, string> = {
    queued: '排队等号', tts: '合成配音', plan: '排分镜', props: '设计画面',
    prepped: '打包交给你', render: '等你这台电脑开工',
  };
  const act = phase === 'done' ? '已完成'
    : phase === 'rendering' ? '本机生成画面'
    : phase === 'uploading' ? '交回云端'
    : phase === 'ready' ? '等你这台电脑开工'
    : pack ? '缓存素材'
    : ACT[prepStage] || '云端备料';

  // 四段轨道：每段走完打一个勾，等的过程要看得见在推进
  const RAIL = ['云端备料', '缓存素材', '本机生成', '交回云端'];
  const genIdx = phase === 'done' ? 4 : phase === 'uploading' ? 3
    : phase === 'rendering' ? 2 : pack ? 1 : 0;
  // 副行不重复大标题：大标题说「此刻」，副行说「接下来」
  const rest = RAIL.slice(genIdx + 1);
  const gdetail = phase === 'rendering'
    ? `画面已出 ${Math.round(pct * durS / 100)} / ${Math.round(durS)} 秒`
    : rest.length ? `接下来：${rest.join(' → ')}` : '最后一步，交完就能取片';

  const cacheMB = pack ? pack.files.reduce((s, f) => s + f.size, 0) / 1048576 : 0;
  // 整条流程的预估：备料约 2 分半 + 缓存按 ~500KB/s + 本机约两倍片长
  const estSec = 150 + Math.max(6, cacheMB * 2) + Math.max(45, (durS || 60) * 2);
  const estMin = Math.max(3, Math.round(estSec / 60));
  // 跑起来之后以实测为准：已用时间按当前比例外推，越跑越准
  const leftSec = bar >= 6 && bar < 100 ? (elapsed * (100 - bar)) / bar : 0;

  const line = phase === 'error' ? ''
    : phase === 'uploading' ? '交回云端…'
    : phase === 'done' ? ''
    : pack && phase !== 'rendering' ? `缓存素材 ${prewarmDone}/${pack.files.length}`
    : phase === 'prepping' ? prepMsg.replace(/渲染/g, '生成')
    : `已出 ${Math.round(pct * durS / 100)} / ${Math.round(durS)} 秒 · 已用 ${mmss}`;

  const fileInput = React.useRef<HTMLInputElement>(null);
  const pick = () => fileInput.current?.click();
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setHot(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) void importZip(f);
  };
  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setHot(true);
  };

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <Mark />
          <span className="wm">GetCut</span>
          <span className="sub">成片台</span>
        </div>
        <div className="top-right">
          <span className="selw">
            <select className="chip sel-theme" value={theme} aria-label="配色主题"
                    onChange={(e) => setTheme(e.target.value)}>
              {THEMES.map((t) => <option key={t.id} value={t.id}>配色 · {t.name}</option>)}
            </select>
            <span className="car">▾</span>
          </span>
          {!me ? <button className="chip" onClick={() => setSheet('pricing')} title="免费版与高级版">定价</button> : null}
          {me ? <button className="chip" onClick={openLib} title="历史项目与成片">作品库</button> : null}
          <Account me={me} authst={authst} sheet={sheet} setSheet={setSheet}
                   refresh={refreshMe} toast={say}
                   onMe={(m) => { meRef.current = m; setMe(m); }}
                   authNote={authNote}
                   onBrandChanged={() => { void loadVoices(); void loadBrand(); }}
                   onSignedIn={() => {
                     setAuthNote('');
                     setErr('');       // 那句"登录已失效"到此为止
                     const f = pendingZip.current;
                     pendingZip.current = null;
                     if (f) void importZip(f);
                   }} />
        </div>
      </header>

      <div className="body">
        {/* 左：动作 */}
        <div className="pane left">
          <div className="lede">拖入素材包，一条好片子在你这台电脑上完成——不排队、不限速。</div>

          <input ref={fileInput} type="file" accept=".zip" style={{display: 'none'}}
                 onChange={(e) => void importZip(e.target.files?.[0])} />

          <div className="steps">
            {/* 1 导入 */}
            <Step n={1} title="导入素材包" state={st(1)}
                  summary={bundle ? `${bundle.name} 已导入` : undefined}>
              {phase === 'importing' ? (
                <div>
                  <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100}
                       aria-valuenow={Math.round(upPct)} aria-label="素材包上传进度"><i style={{width: `${Math.max(4, upPct)}%`}} aria-hidden="true" /></div>
                  <div className="pline"><span className="st">上传中</span>
                    <span className="pc">{upPct}%</span></div>
                </div>
              ) : bundle ? (
                <button className="btn ln sm" onClick={pick}>换一个素材包</button>
              ) : (
                <div className={`drop${hot ? ' hot' : ''}`} role="button" tabIndex={0}
                     aria-label="点这里选素材包 zip" onClick={pick}
                     onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' '){ e.preventDefault(); pick(); } }}
                     onDrop={onDrop} onDragOver={onDragOver} onDragLeave={() => setHot(false)}>
                  <b>点这里选素材包 zip</b>
                  <span>不解压，文案与素材一起读入 · 也可以直接拖到右边那块</span>
                </div>
              )}
            </Step>

            {/* 2 内容与配音 */}
            {bundle ? (
              <Step n={2} title="内容与配音" state={st(2)}>
                <div className="meta">
                  <span>{nChars} 字口播</span><span>约 {bundle.estSeconds} 秒</span>
                  <span>{nImg} 图 / {nVid} 视频</span>
                </div>
                <div className="togo">口播文案在右边整屏核对，看完直接点生成</div>

                {/* 画面样式：这套片子最贵的差别，不该藏在二级浮层里 —— 缩略图直接摊开，点哪个用哪个 */}
                {tpls.length ? (
                  <div className="field" style={{marginTop: 16}}>
                    <div className="lb tpl-lb">
                      <span>画面样式</span>
                      <button className="btn ln sm" onClick={() => setTplSample(cfg.template)}>看样片</button>
                    </div>
                    <div className="tplrow" role="radiogroup" aria-label="画面样式">
                      {tpls.map((t) => (
                        <button key={t.id} type="button" role="radio"
                                aria-checked={cfg.template === t.id} aria-label={t.name}
                                className={`tplth${cfg.template === t.id ? ' on' : ''}`}
                                onClick={() => setCfg({...cfg, template: t.id})}>
                          <img src={TPL_IMG(t.id)} alt="" loading="lazy"
                               onError={(e) => { e.currentTarget.style.visibility = 'hidden'; }} />
                        </button>
                      ))}
                    </div>
                    <div className="tplcap">
                      <b>{tplName}</b><span>{TPL_HINT[cfg.template] || '这套就是推荐样式'}</span>
                    </div>
                  </div>
                ) : null}

                <div className="field" style={{marginTop: 16}}>
                  <div className="lb">配音</div>
                  <div className="row">
                    <select className="sel" value={cfg.voice}
                            onChange={(e) => { stopPreview(); setCfg({...cfg, voice: e.target.value}); }}>
                      {groupVoices(voices).map(([g, vs]) => (
                        <optgroup key={g} label={g}>
                          {vs.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                        </optgroup>
                      ))}
                      {!voices.length ? <option value="">默认音色</option> : null}
                    </select>
                    <button className={`btn ln sm${prevKey === 'voice' ? ' busy' : ''}`}
                            onClick={() => cfg.voice && playPreview('voice',
                              `/api/voice-preview?voice=${encodeURIComponent(cfg.voice)}`)}>
                      {prevKey === 'voice' ? '停止试听' : '试听'}
                    </button>
                  </div>
                </div>
                <div className="field">
                  <div className="lb">背景音乐</div>
                  <div className="row">
                    <select className="sel" value={cfg.bgm}
                            onChange={(e) => { stopPreview(); setCfg({...cfg, bgm: e.target.value}); }}>
                      <option value="">不用背景音乐</option>
                      {music.map((m) => <option key={m.file} value={m.file}>{m.name}{m.mood ? ` · ${m.mood}` : ''}</option>)}
                    </select>
                    <button className={`btn ln sm${prevKey === 'bgm' ? ' busy' : ''}`}
                            onClick={() => cfg.bgm && playPreview('bgm',
                              `/api/bgm/${encodeURIComponent(cfg.bgm.split('/').pop() as string)}`)}>
                      {prevKey === 'bgm' ? '停止试听' : '试听'}
                    </button>
                  </div>
                </div>
                <div className="toggles">
                  <Toggle label="字幕" on={cfg.subtitles} set={(v) => setCfg({...cfg, subtitles: v})} />
                  <Toggle label="音效" on={cfg.sfx} set={(v) => setCfg({...cfg, sfx: v})} />
                  <Toggle label="资料来源" on={cfg.sources} set={(v) => setCfg({...cfg, sources: v})} />
                </div>
                <div style={{marginTop: 18}}>
                  <button className="btn" onClick={() => void submit()}>
                    生成视频{durS ? `（约 ${estMin} 分钟）` : ''}
                  </button>
                </div>
              </Step>
            ) : null}

            {/* 3 正在生成视频：备料→缓存→本机→交回，一条进度条走到底 */}
            {pack || jobId || phase === 'prepping' ? (
              <Step n={3} title={phase === 'done' ? '视频已生成' : '正在生成视频'} state={st(3)}>
                {phase !== 'error' && phase !== 'done' ? (
                  <div>
                    <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100}
                         aria-valuenow={Math.round(bar)} aria-label="生成进度"><i style={{width: `${bar}%`}} aria-hidden="true" /></div>
                    <div className="pline">
                      <span className="st">{line}</span>
                      <span className="pc">{Math.round(bar)}%</span>
                    </div>
                  </div>
                ) : null}
                {phase === 'ready' ? (
                  <button className="btn" style={{marginTop: 12}} onClick={() => void startRender()}>
                    生成视频（约 {estMin} 分钟）
                  </button>
                ) : null}
                {phase === 'error' ? (
                  <button className="btn" style={{marginTop: 12}} onClick={() => void startRender()}>
                    重试这一步
                  </button>
                ) : null}
              </Step>
            ) : null}

            {/* 4 取走成片 */}
            {finalUrl ? (
              <Step n={4} title="取走成片" state="done" open>
                <div style={{display: 'flex', flexDirection: 'column', gap: 10}}>
                  <a className="btn" href={finalUrl} download={fileName}>下载 MP4 成片</a>
                  <div className="note">拿到 MP4 就能直接用：发抖音/视频号，或剪映里「导入」这个文件开剪，什么都不用装。</div>
                  <button className="btn ln" style={{alignSelf: 'flex-start',
                          opacity: (jyBusy || layerMsg) ? .6 : 1}}
                          disabled={jyBusy || !!layerMsg} onClick={() => void jianying()}>
                    导入剪映（分轨草稿 · 可逐条改字幕）
                  </button>
                  {layerMsg ? <div className="note">{layerMsg}</div> : null}
                  {layersOk !== null && !layerMsg ? (
                    <div className="note" style={{color: layersOk ? 'var(--ok)' : undefined}}>
                      {layersOk ? `剪映分轨图层已备好：${layerNote || '底板、卡片、可改文字各一条轨'}`
                                : '分轨图层没出全' + (layerErr ? `（${layerErr}）` : '')
                                  + '。片子照样能导入剪映，只是卡片只能整条挪'}
                    </div>
                  ) : null}
                  {jy ? <div className="note">{jy}</div> : null}
                  <div className="note">
                    {!me || me.tier === 'free' ? '免费版成片带 GetCut 水印 · '
                      : brandOn ? '右上角已带上你的品牌角标 · '
                      : '右上角带 Powered by GetCut 水印 · '}
                    {!me || me.tier === 'free' ? (
                      <button style={lnkAcc} onClick={() => setSheet('pricing')}>看权益</button>
                    ) : (
                      <button style={lnkAcc} onClick={() => setSheet('brand')}>品牌套装</button>
                    )}
                  </div>
                  <div className="note" style={{color: cloudOk ? 'var(--ok)' : undefined}}>
                    {cloudOk ? '已同步云端作品库 · ' : '交回云端失败，不影响本机下载 · '}
                    {cloudOk && jobId ? <button style={lnkAcc} onClick={openLib}>去看历史</button> : null}
                  </div>
                  <button className="btn ln" style={{alignSelf: 'flex-start'}} onClick={reset}>再做一条</button>
                </div>
              </Step>
            ) : null}
          </div>

          {err ? <div className="err">出错：{err}</div> : null}
          {resumeJob && !pack && phase === 'drop' ? (
            <div className="note" style={{color: 'var(--acc)'}}>
              刚才那一条（{resumeJob.slice(-6)}）已交还队列，正在重新领回来——不用重拖素材包。
            </div>
          ) : null}

          {/* 本机环境体检：不在主流程上，压到左栏最底部；一个按钮，审完只给三档结论 */}
          <div className="envcheck">
            {envBusy ? (
              <span className="envres">正在检查这台电脑…</span>
            ) : env === null ? (
              <button className="envbtn" onClick={() => void runEnvCheck()}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z"/>
                  <path d="M8.5 12.5l2.5 2.5 4.5-5"/>
                </svg>
                检查这台电脑能不能出片
              </button>
            ) : env.tier === 3 ? (
              <>
                <span className="envres ok">✓ 这台电脑可以正常出片</span>
                <button className="envre" onClick={() => void runEnvCheck()}>重新检查</button>
                <span className="envsub">已检查：浏览器兼容 · 硬件加速（开）· 处理器 {env.cores || '?'} 核{env.mem ? ` · 内存 ${env.mem} GB` : ''} · 网络（在线）</span>
              </>
            ) : env.tier === 2 ? (
              <>
                <span className="envres slow">⚠ 能出片，但速度会比较慢</span>
                <button className="envre" onClick={() => void runEnvCheck()}>重新检查</button>
                <span className="envsub">想要更快：换台配置好点的电脑，或在浏览器设置里打开硬件加速。已检查：浏览器兼容 · 硬件加速（{env.hw ? '开' : '未开'}）· 处理器 {env.cores || '?'} 核{env.mem ? ` · 内存 ${env.mem} GB` : ''} · 网络（{env.online ? '在线' : '离线'}）</span>
              </>
            ) : (
              <>
                <span className="envres bad">✗ 这台电脑暂时导不了片</span>
                <button className="envre" onClick={() => void runEnvCheck()}>重新检查</button>
                <span className="envsub">{!env.hasVE ? '浏览器版本太旧：请换新版 Chrome 或 Edge，再回来导入素材包。' : '网络已断开：恢复网络后再导入素材包。'}已检查：浏览器兼容 · 处理器 {env.cores || '?'} 核 · 网络（{env.online ? '在线' : '离线'}）</span>
              </>
            )}
          </div>
        </div>

        {/* 右：预览台 */}
        <div className="pane right" onDrop={bundle ? undefined : onDrop}
             onDragOver={bundle ? undefined : onDragOver}
             onDragLeave={bundle ? undefined : () => setHot(false)}>
          {gen && !finalUrl ? (
            /* 生成期这一屏就是「正在做什么」：动作词最大，进度不断档，口播文案折起来仍可细看 */
            <div className="genwrap">
              <article className="gen">
                <div className="g-top">
                  <span className="g-kicker">第 3 步 · 共 4 步</span>
                  <span className="g-pct">{Math.round(bar)}%</span>
                </div>
                <div className="g-act">{act}</div>
                <div className="g-detail">{gdetail}</div>
                <div className="g-bar"><i style={{width: `${bar}%`}} /></div>
                <div className="rail">
                  {RAIL.map((t, i) => (
                    <span key={t} className={`rl${i < genIdx ? ' ok' : i === genIdx ? ' on' : ''}`}>
                      <b>{i < genIdx ? '✓' : i + 1}</b>{t}
                    </span>
                  ))}
                </div>
                <div className="g-meta">
                  <span>已用 {mmss}</span>
                  {!stalled && leftSec >= 20 ? <span>还需约 {mm(leftSec)}</span> : null}
                  {!stalled ? <span>整条预计 {estMin} 分钟</span> : null}
                </div>
                {stalled ? (
                  <div className="g-warn">
                    这一单被另一个成片台页面占着 —— 你可能开了两个标签页，或旧标签页刚被关掉。
                    关掉另一个页面；不然等约 4 分钟云端会自己收回，收回后这一页立刻接着跑。
                    <div>
                      <button className="btn ln sm" style={{marginTop: 10}}
                              onClick={() => { setStalled(false); void submit(); }}>
                        不等了，重开一条
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="g-keep">
                    可以刷新这一页：任务会自动接回来重跑。关掉浏览器或断网，云端要等约 4 分钟才回收这一单。
                  </div>
                )}
              </article>
              {pack ? (
                <div className="stage mini">
                  {phase === 'rendering' ? (
                    /* 生成期卸载 Player：同一时刻只保留 web-renderer 那一份合成 */
                    <div className="void">
                      <div className="bars3"><i /><i /><i /><i /><i /></div>
                      <div className="sm">画面已出 {Math.round(pct * durS / 100)} / {Math.round(durS)} 秒</div>
                    </div>
                  ) : (
                    <Player
                      ref={playerRef}
                      component={NiwoVideo as React.FC<Record<string, unknown>>}
                      inputProps={(pack as JobPack).props as unknown as Record<string, unknown>}
                      durationInFrames={(pack as JobPack).props.durationInFrames}
                      fps={30}
                      compositionWidth={1080}
                      compositionHeight={1920}
                      style={{width: '100%', height: '100%'}}
                      autoplay
                      loop
                      muted
                      showControls={false}
                      acknowledgeRemotionLicense
                    />
                  )}
                  {phase !== 'rendering' ? (
                    <div className="cap">实时预览（静音） · 成片带配音与音乐</div>
                  ) : null}
                </div>
              ) : null}
              {bundle ? (
                <div className="foldbox">
                  <button className="foldb" onClick={() => setShowScript(!showScript)}>
                    {showScript ? '收起口播文案'
                      : `口播文案 ${nChars} 字 · 约 ${bundle.estSeconds} 秒 —— 展开核对`}
                  </button>
                  {showScript ? (
                    <div className="rd-body">
                      {(bundle.script || '').split(NL).filter(Boolean).map((para, i) => <p key={i}>{para}</p>)}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : finalUrl || pack ? (
            <div className="stagewrap">
              <div className="stage">
                {finalUrl ? (
                  <video src={finalUrl} controls autoPlay />
                ) : (
                  <Player
                    ref={playerRef}
                    component={NiwoVideo as React.FC<Record<string, unknown>>}
                    inputProps={(pack as JobPack).props as unknown as Record<string, unknown>}
                    durationInFrames={(pack as JobPack).props.durationInFrames}
                    fps={30}
                    compositionWidth={1080}
                    compositionHeight={1920}
                    style={{width: '100%', height: '100%'}}
                    autoplay
                    loop
                    muted
                    showControls={false}
                    acknowledgeRemotionLicense
                  />
                )}
                {pack && !finalUrl ? (
                  <div className="cap">实时预览（静音） · 成片带配音与音乐</div>
                ) : null}
              </div>
              <div className="stagecap">
                <b>{title}</b>
                <span>{Math.round(durS)} 秒 · 1080×1920 竖屏 · {phase === 'done' ? '已完成' : phase === 'rendering' ? '生成中' : '预览中'}</span>
              </div>
            </div>
          ) : bundle ? (
            <article className="reader">
              <div className="rd-top">
                <span className="rd-kicker">口播文案 · 核对</span>
                <span className="rd-meta">{nChars} 字 · 约 {bundle.estSeconds} 秒 · 图 {nImg} 视频 {nVid}</span>
              </div>
              <h2 className="rd-title">{title}</h2>
              {(bundle.hookLines?.[0]?.text) ? <div className="rd-hook">{bundle.hookLines?.[0]?.text}</div> : null}
              <div className="rd-body">
                {(bundle.script || '').split(NL).filter(Boolean).map((para, i) => <p key={i}>{para}</p>)}
              </div>
            </article>
          ) : (
            <div className={`stagedrop${hot ? ' hot' : ''}`} role="button" tabIndex={0}
                 aria-label="把素材包拖到这里，或按回车选文件" onClick={pick}
                 onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' '){ e.preventDefault(); pick(); } }}
                 onDrop={onDrop} onDragOver={onDragOver} onDragLeave={() => setHot(false)}>
              <Mark size={44} />
              <div className="t">素材包拖到这里</div>
              <div className="s">文案、图片、视频一起读入，成片在这里出现</div>
              <div className="s dim">也可以点左边第 1 步选文件 · zip 不解压</div>
            </div>
          )}
        </div>
      </div>

      <footer className="footbar">
        <span style={{color: codecOk ? undefined : 'var(--err)'}}>
          {codecOk ? '本机出片能力 正常' : '浏览器太旧，请换新版 Chrome / Edge'}
        </span>
        <div className="right">
          <a href="/privacy" target="_blank" rel="noopener">隐私政策</a>
          <a href="/terms" target="_blank" rel="noopener">用户协议</a>
          <a href="/refund" target="_blank" rel="noopener">退款说明</a>
        </div>
      </footer>

      {tplSample ? (
        <Sheet title={`「${tplName}」样片`} width={400} onClose={() => setTplSample('')}>
          <video className="tplvid" controls autoPlay playsInline
                 poster={TPL_IMG(tplSample)} src={TPL_SAMPLE(tplSample)}
                 onError={(e) => { e.currentTarget.style.display = 'none'; }} />
          <div className="note" style={{marginTop: 12}}>
            同一段演示内容在这套样式下出的真片，约 17 秒。样片播不出来？说明这套的样片还没生成。
          </div>
        </Sheet>
      ) : null}

      {lib !== null || libMsg ? (
        <Sheet title="作品库" sub="历史项目与成片，直接下载带走" width={620}
               onClose={() => { setLib(null); setLibMsg(''); }}>
          {libMsg ? <div className="note">{libMsg}</div> : null}
          {lib && !lib.length ? <div className="note">还没有项目，拖一个素材包进来就是第一条。</div> : null}
          <div className="liblist">
            {(lib || []).map((p) => {
              const last = (p.renders || []).filter((r) => r.file).slice(-1)[0];
              return (
                <div className="librow" key={p.project_id}>
                  <div className="li-t">
                    <b>{p.title || '未命名'}</b>
                    <span>{p.created || ''} · {p.assets_count ?? 0} 素材 · {p.renders_count ?? 0} 成片</span>
                  </div>
                  <div className="li-a">
                    {last ? (
                      <button className="btn ln sm" style={{minWidth: 84}}
                              disabled={libJyKey === p.project_id}
                              onClick={() => void libJy(p.project_id, last.id)}>
                        {libJyKey === p.project_id ? '打包草稿…' : '导入剪映'}
                      </button>
                    ) : null}
                    {last ? <a className="btn ln sm" href={`/video/${last.id}`}
                               download>下成片</a> : null}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="note" style={{marginTop: 14}}>
            当时没导剪映？在条目上点「导入剪映」随时补；导入后要逐条改字幕、动分轨，去剪映里接着剪。
          </div>
        </Sheet>
      ) : null}

      {toast ? <div className="toast">{toast}</div> : null}
    </div>
  );
};

const el =
  document.getElementById('root') ??
  Object.assign(document.createElement('div'), {id: 'root'});
document.body.appendChild(el);
createRoot(el).render(<App />);
