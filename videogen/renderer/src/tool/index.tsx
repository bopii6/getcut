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
// 开发自查用：?frames=240 只渲前 240 帧（不改变正式行为）
const FRAMES_LIMIT = Math.max(0, parseInt(qs.get('frames') || '0', 10) || 0);
const THEME_KEY = 'vg-theme';
const NL = /\r?\n/;   // 口播文案按段切开
// 配色主题：名字与工作台的 data-theme 同一套，两页之间切换互相认得
const THEMES = [
  {id: 'ziyu', name: '紫玉描金'}, {id: 'xuanqing', name: '玄青'}, {id: 'shimo', name: '石墨'},
  {id: 'zhimu', name: '纸墨'}, {id: 'daiqing', name: '黛青'},
];

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
  const [authst, setAuthst] = React.useState<AuthSt>({smtp: false, dev_email: false, token_auth: false, locked: false});
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
  const [voices, setVoices] = React.useState<Voice[]>([]);
  const [music, setMusic] = React.useState<{file: string; name: string; mood?: string}[]>([]);
  const [cfg, setCfg] = React.useState({voice: '', bgm: '', subtitles: true, sfx: true, sources: true});
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
  const [lib, setLib] = React.useState<Project[] | null>(null);
  const [libMsg, setLibMsg] = React.useState('');
  const playerRef = React.useRef<PlayerRef>(null);
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
    api('/api/auth/status').then((d) => setAuthst(d as unknown as AuthSt)).catch(() => {});
    void loadVoices();
    api('/api/music').then((d) => {
      const list = (Array.isArray(d) ? d : (d.music as typeof music)) || [];
      setMusic(list);
    }).catch(() => {});
  }, []);

  // ---- 成片台轮询：领任务（本页提交的或别的页提交的都走这里） ----
  React.useEffect(() => {
    let alive = true;
    (async () => {
      for (;;) {
        if (!alive) return;
        try {
          const r = await fetch(`/api/agent/poll?wait=1&device=${encodeURIComponent(DEVICE)}`,
            {headers: {'x-agent-final': '1'}, credentials: 'same-origin'});
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const data = await r.json();
          if (!data.job) continue;
          (window as unknown as Record<string, unknown>).remotion_staticBase =
            `/agent-media/${data.job}`;
          const p: JobPack = {job: data.job, props: data.props, files: data.files || []};
          if (!alive) return;
          setPack(p);
          packRef.current = p;
          autoRef.current = !!jobIdRef.current && jobIdRef.current === data.job;
          setPhase(autoRef.current ? 'prepping' : 'ready');
          setPrewarmDone(0);
          let done = 0;
          for (const f of p.files) {
            const url = `/agent-media/${p.job}/${f.path}`;
            let ok = false;
            for (let a = 0; a < 2 && !ok; a++) {
              try {
                ok = (await fetch(url, {cache: 'force-cache'})).ok;
              } catch (_) {
                ok = false;
              }
              if (!ok) await new Promise((res) => setTimeout(res, 800));
            }
            if (!ok) throw new Error(`素材加载失败：${f.path}`);
            done += 1;
            setPrewarmDone(done);
          }
          await document.fonts.ready.catch(() => {});
          if (!alive) return;
          if (autoRef.current) startRender();
          else setPhase('ready');
          return;
        } catch (e) {
          if (!alive) return;
          console.error('GetCut 准备失败', e);
          if (packRef.current) {
            await report(0, '浏览器端准备失败，退回队列', true).catch(() => {});
            packRef.current = null;
            setPack(null);
          }
          await new Promise((res) => setTimeout(res, 3000));
        }
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- 导入：建项目 → 上传 zip → 挂载 → 读摘要 ----
  const importZip = async (file?: File) => {
    if (!file || phaseRef.current === 'importing') return;
    // 素材包是要花钱的活，账号先到位；本机开放模式（没建过账号）不拦
    if (!meRef.current && (authst.locked || authst.token_auth)) {
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
    setPrepMsg('已提交，云端正在写稿配音…');
    try {
      const r = await api('/api/build', {method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({project_id: projectId, bundle: bundle.name,
          voice: cfg.voice, bgm: cfg.bgm, sfx: cfg.sfx, sfxMode: cfg.sfx ? 'full' : 'off',
          subtitles: cfg.subtitles, sources: cfg.sources,
          // 免费档带 GetCut 水印（服务端也强制）；付费档设了品牌才出那一格
          watermark: !me || me.tier === 'free' || brandOn,
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
          setPrepPct(Number(j.progress ?? 0));
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

  const playPreview = (url: string) => {
    const a = new Audio(url);
    void a.play().catch(() => setErr('浏览器拦了自动播放，再点一次试试'));
  };

  // 导入剪映：装了小助手的机器一键直达；没装就回落成下载草稿包
  const jianying = async () => {
    if (!projectId || !jobId || jyBusy) return;
    setJyBusy(true);
    setJy('正在准备草稿…');
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
            location.href = `/api/projects/${projectId}/renders/${jobId}/jianying-draft`;
          }
        }, 2600);
      } else {
        setJy('草稿包已下载：解压后双击「一键导入剪映.bat」（只想快点剪的话，直接把这个 MP4 拖进剪映就行）');
        location.href = `/api/projects/${projectId}/renders/${jobId}/jianying-draft`;
      }
    } catch (e) {
      setJy('导入失败：' + String((e as Error).message));
    } finally {
      setTimeout(() => setJyBusy(false), 3000);
    }
  };

  const durS = pack ? pack.props.durationInFrames / 30
    : bundle ? bundle.estSeconds : 0;
  const nImg = bundle?.assets ? bundle.assets.filter((a) => a.kind === 'image').length : 0;
  const nVid = bundle?.assets ? bundle.assets.filter((a) => a.kind === 'video').length : 0;
  const title = bundle?.title || pack?.props.headline?.lines?.[0]?.text || '';
  const fileName = `${(title || 'getcut').replace(/[\\/:*?"<>|\[\]]/g, '')}-${(pack?.job || jobId).slice(-6)}.mp4`;
  const nChars = (bundle?.script || '').length;
  const estMin = Math.max(1, Math.round((durS || 60) / 60 * 2));
  const mmss = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;
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

  // 从「点生成」到「交回」一条进度条走到底：备料 2~15 → 缓存素材 15~20 → 本机 20~97 → 交回 97~100
  const bar = phase === 'prepping' && !pack ? Math.min(15, 2 + prepPct * 0.13)
    : pack && !finalUrl && phase !== 'rendering' && phase !== 'uploading' && phase !== 'done'
      ? 15 + (prewarmDone / Math.max(1, pack.files.length)) * 5
    : phase === 'rendering' ? 20 + pct * 0.75
    : phase === 'uploading' ? 97 : phase === 'done' ? 100 : 0;
  const line = phase === 'error' ? ''
    : phase === 'prepping' && !pack ? `云端准备 · ${prepMsg.replace(/渲染/g, '生成')}`
    : phase === 'uploading' ? '交回云端…'
    : phase === 'done' ? ''
    : pack && phase !== 'rendering' ? `缓存素材 ${prewarmDone}/${pack.files.length}`
    : `本机生成中 · 已出 ${Math.round(pct * durS / 100)} / ${Math.round(durS)} 秒 · 已用 ${mmss}`;

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
          {!me ? <a className="chip" href="/studio" title="这产品是什么、怎么做">怎么用</a> : null}
          {!me ? <button className="chip" onClick={() => setSheet('pricing')} title="免费版与高级版">定价</button> : null}
          {me ? <button className="chip" onClick={openLib} title="历史项目与成片">作品库</button> : null}
          <Account me={me} authst={authst} sheet={sheet} setSheet={setSheet}
                   refresh={refreshMe} toast={say}
                   onMe={(m) => { meRef.current = m; setMe(m); }}
                   authNote={authNote}
                   onBrandChanged={() => { void loadVoices(); void loadBrand(); }}
                   onSignedIn={() => {
                     setAuthNote('');
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
                  <div className="bar"><i style={{width: `${Math.max(4, upPct)}%`}} /></div>
                  <div className="pline"><span className="st">上传中</span>
                    <span className="pc">{upPct}%</span></div>
                </div>
              ) : bundle ? (
                <button className="btn ln sm" onClick={pick}>换一个素材包</button>
              ) : (
                <div className={`drop${hot ? ' hot' : ''}`} onClick={pick}
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

                <div className="field" style={{marginTop: 16}}>
                  <div className="lb">配音</div>
                  <div className="row">
                    <select className="sel" value={cfg.voice}
                            onChange={(e) => setCfg({...cfg, voice: e.target.value})}>
                      {groupVoices(voices).map(([g, vs]) => (
                        <optgroup key={g} label={g}>
                          {vs.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                        </optgroup>
                      ))}
                      {!voices.length ? <option value="">默认音色</option> : null}
                    </select>
                    <button className="btn ln sm"
                            onClick={() => cfg.voice && playPreview(`/api/voice-preview?voice=${encodeURIComponent(cfg.voice)}`)}>试听</button>
                  </div>
                </div>
                <div className="field">
                  <div className="lb">背景音乐</div>
                  <div className="row">
                    <select className="sel" value={cfg.bgm}
                            onChange={(e) => setCfg({...cfg, bgm: e.target.value})}>
                      <option value="">不用背景音乐</option>
                      {music.map((m) => <option key={m.file} value={m.file}>{m.name}{m.mood ? ` · ${m.mood}` : ''}</option>)}
                    </select>
                    <button className="btn ln sm"
                            onClick={() => cfg.bgm && playPreview(`/api/bgm/${encodeURIComponent(cfg.bgm.split('/').pop() as string)}`)}>试听</button>
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
                    <div className="bar"><i style={{width: `${bar}%`}} /></div>
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
                      : brandOn ? '右上角已带上你的品牌角标 · ' : '本条按你的档位干净出片（无水印）· '}
                    {!me || me.tier === 'free' ? (
                      <button style={lnkAcc} onClick={() => setSheet('pricing')}>看权益</button>
                    ) : (
                      <button style={lnkAcc} onClick={() => setSheet('brand')}>品牌套装</button>
                    )}
                  </div>
                  <div className="note" style={{color: cloudOk ? 'var(--ok)' : undefined}}>
                    {cloudOk ? '已同步云端作品库 · ' : '交回云端失败，不影响本机下载 · '}
                    {cloudOk && jobId ? <a href={`/studio#/project/${projectId}`} style={{color: 'var(--acc)'}}>去看历史</a> : null}
                  </div>
                  <button className="btn ln" style={{alignSelf: 'flex-start'}} onClick={reset}>再做一条</button>
                </div>
              </Step>
            ) : null}
          </div>

          {err ? <div className="err">出错：{err}</div> : null}
          {phase === 'drop' && !bundle ? (
            <div className="note">需要新版 Chrome 或 Edge（出片靠这台电脑自己算）。5 年以上的旧机器会慢一些。</div>
          ) : null}
        </div>

        {/* 右：预览台 */}
        <div className="pane right" onDrop={bundle ? undefined : onDrop}
             onDragOver={bundle ? undefined : onDragOver}
             onDragLeave={bundle ? undefined : () => setHot(false)}>
          {finalUrl || pack ? (
            <div className="stagewrap">
              <div className="stage">
                {finalUrl ? (
                  <video src={finalUrl} controls autoPlay />
                ) : phase === 'rendering' ? (
                  /* 生成期卸载 Player：同一时刻只保留 web-renderer 那一份合成 */
                  <div className="void">
                    <div className="bars3"><i /><i /><i /><i /><i /></div>
                    <div className="pct">{Math.round(bar)}%</div>
                    <div className="sm">
                      本机生成中 · 已用 {mmss}
                      <br />画面已出 {Math.round(pct * durS / 100)} / {Math.round(durS)} 秒，请保持本页打开
                    </div>
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
                {pack && !finalUrl && phase !== 'rendering' ? (
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
              {phase === 'prepping' ? (
                <div className="rd-strip"><span className="rd-dot" />{prepMsg} · 已用 {mmss}</div>
              ) : null}
              <div className="rd-body">
                {(bundle.script || '').split(NL).filter(Boolean).map((para, i) => <p key={i}>{para}</p>)}
              </div>
            </article>
          ) : (
            <div className={`stagedrop${hot ? ' hot' : ''}`} onClick={pick}
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
        <span>{DEVICE}</span>
        <span className="sep" />
        <span style={{color: codecOk ? undefined : 'var(--err)'}}>
          {codecOk ? '本机出片能力 正常' : '浏览器太旧，请换新版 Chrome / Edge'}
        </span>
        <div className="right">
          <span>画面与声音都在这台电脑上完成</span>
          <span className="sep" />
          <span>服务器零排队</span>
        </div>
      </footer>

      {lib !== null || libMsg ? (
        <Sheet title="作品库" sub="历史项目与成片；打开可继续精修" width={620}
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
                    {last ? <a className="btn ln sm" href={`/video/${last.id}`}
                               download>下成片</a> : null}
                    <a className="btn ln sm" href={`/studio#/project/${p.project_id}`}>打开</a>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="note" style={{marginTop: 14}}>
            需要逐条改字幕、动分轨，就在「打开」里进工作台；只出片的话，这一页就够了。
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
