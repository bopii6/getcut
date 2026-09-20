import React from 'react';
import {createRoot} from 'react-dom/client';
import {Player, type PlayerRef} from '@remotion/player';
import {renderMediaOnWeb, renderStillOnWeb} from '@remotion/web-renderer';
import {NiwoVideo, probeSink, type NiwoProps} from '../NiwoVideo';
import {C, btn, btnLine, sel, api, lnkAcc, Toggle} from './ui';
import {Account, type AuthSt, type Me, type SheetName} from './account';

// GetCut 成片台（单页全流程）：拖素材包 → 内容与配音确认 → 浏览器渲染合成
// → 取走带声 mp4。云端只做写稿/配音/分镜等轻活；画面与混音全在本页完成，
// 无录屏授权弹窗（web-renderer 走 WebCodecs）。

const qs = new URLSearchParams(location.search);
const DEVICE = qs.get('device') || '网页成片台';
// 开发自查用：?frames=240 只渲前 240 帧（不改变正式行为）
const FRAMES_LIMIT = Math.max(0, parseInt(qs.get('frames') || '0', 10) || 0);

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

const Step: React.FC<{n: number; title: string; state: 'todo' | 'active' | 'done';
                     children?: React.ReactNode; summary?: string; open?: boolean}> =
  ({n, title, state, children, summary, open}) => (
    <div style={{display: 'flex', gap: 14, opacity: state === 'todo' ? 0.45 : 1}}>
      <div style={{
        width: 26, height: 26, flexShrink: 0, borderRadius: '50%', marginTop: 1,
        border: `1.5px solid ${state === 'done' ? C.ok : state === 'active' ? C.accent : C.line}`,
        background: state === 'done' ? C.ok : state === 'active' ? C.accentSoft : 'transparent',
        color: state === 'done' ? '#fff' : state === 'active' ? C.accent : C.soft,
        fontSize: 13, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>{state === 'done' ? '✓' : n}</div>
      <div style={{minWidth: 0, flex: 1}}>
        <div style={{fontSize: 15, fontWeight: 700}}>{title}</div>
        {(state === 'done' || state === 'active') && summary
          ? <div style={{fontSize: 13, color: C.soft, marginTop: 3}}>{summary}</div> : null}
        {(state === 'active' || open) && children ? <div style={{marginTop: 10}}>{children}</div> : null}
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
  const playerRef = React.useRef<PlayerRef>(null);
  const abortRef = React.useRef<AbortController | null>(null);
  const packRef = React.useRef<JobPack | null>(null);
  const jobIdRef = React.useRef('');
  const autoRef = React.useRef(false);
  const pendingZip = React.useRef<File | null>(null);
  const meRef = React.useRef<Me | null>(null);
  const phaseRef = React.useRef<Phase>('drop');
  phaseRef.current = phase;
  jobIdRef.current = jobId;

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
          setLayerErr(String((e as Error).message || e).slice(0, 90));
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
    setPhase('drop');
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
        setJy('已导入剪映，打开剪映就能看到 ✓');
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
            setJy('小助手还没装：已改为下载草稿包，解压后双击「一键导入剪映.bat」');
            location.href = `/api/projects/${projectId}/renders/${jobId}/jianying-draft`;
          }
        }, 2600);
      } else {
        setJy('草稿包已下载：解压后双击「一键导入剪映.bat」');
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

  return (
    <div style={{display: 'grid', gridTemplateColumns: 'minmax(340px, 420px) 1fr', height: '100vh',
                 background: C.paper, color: C.ink, fontFamily: 'system-ui, "Microsoft YaHei", sans-serif'}}>
      {/* 左：动作 */}
      <div style={{padding: '36px 32px', borderRight: `1px solid ${C.line}`, background: C.card,
                   display: 'flex', flexDirection: 'column', gap: 24, overflowY: 'auto'}}>
        <div style={{display: 'flex', gap: 14, alignItems: 'flex-start'}}>
          <div style={{flex: 1, minWidth: 0}}>
            <div style={{fontSize: 22, fontWeight: 800, letterSpacing: 0.5}}>GetCut 成片台</div>
            <div style={{fontSize: 14, color: C.soft, marginTop: 6, lineHeight: 1.7}}>
              拖入素材包，一条好片子在你这台电脑上完成。
            </div>
          </div>
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

        <div style={{display: 'flex', flexDirection: 'column', gap: 20}}>
          {/* 1 导入 */}
          <Step n={1} title="导入素材包" state={st(1)}
                summary={bundle ? `${bundle.name} 已导入` : undefined}>
            {phase === 'importing' ? (
              <div>
                <div style={{height: 6, background: C.line, borderRadius: 3, overflow: 'hidden'}}>
                  <div style={{width: `${Math.max(4, upPct)}%`, height: '100%', background: C.accent, transition: 'width .3s'}} />
                </div>
                <div style={{fontSize: 13, color: C.soft, marginTop: 6}}>上传中 {upPct}%</div>
              </div>
            ) : (
              <label style={{
                display: 'block', border: `1.5px dashed ${C.line}`, borderRadius: 10,
                padding: '18px 14px', textAlign: 'center', cursor: 'pointer',
                fontSize: 13.5, color: C.soft, lineHeight: 1.7, background: C.paper,
              }}>
                把素材包 zip 拖进来，或点这里选文件
                <input type="file" accept=".zip" style={{display: 'none'}}
                       onChange={(e) => void importZip(e.target.files?.[0])} />
              </label>
            )}
          </Step>

          {/* 2 内容与配音 */}
          {bundle ? (
            <Step n={2} title="内容与配音" state={st(2)}
                  summary={`${(bundle.script || '').length} 字 · 约 ${bundle.estSeconds} 秒 · 图${nImg} 视频${nVid}`}>
              <div style={{fontSize: 15, fontWeight: 700, lineHeight: 1.6, marginBottom: 12}}>
                {(bundle.hookLines?.[0]?.text) || bundle.title}
              </div>
              <div style={{display: 'grid', gridTemplateColumns: '1fr auto', gap: '10px 8px', alignItems: 'center'}}>
                <select style={sel} value={cfg.voice}
                        onChange={(e) => setCfg({...cfg, voice: e.target.value})}>
                  {voices.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                  {!voices.length ? <option value="">默认音色</option> : null}
                </select>
                <button style={{...btnLine, padding: '9px 12px'}}
                        onClick={() => cfg.voice && playPreview(`/api/voice-preview?voice=${encodeURIComponent(cfg.voice)}`)}>试听</button>
                <select style={sel} value={cfg.bgm} onChange={(e) => setCfg({...cfg, bgm: e.target.value})}>
                  <option value="">不用背景音乐</option>
                  {music.map((m) => <option key={m.file} value={m.file}>{m.name}{m.mood ? ` · ${m.mood}` : ''}</option>)}
                </select>
                <button style={{...btnLine, padding: '9px 12px'}}
                        onClick={() => cfg.bgm && playPreview(`/api/bgm/${encodeURIComponent(cfg.bgm.split('/').pop() as string)}`)}>试听</button>
              </div>
              <div style={{display: 'flex', gap: 18, marginTop: 14, flexWrap: 'wrap'}}>
                <Toggle label="字幕" on={cfg.subtitles} set={(v) => setCfg({...cfg, subtitles: v})} />
                <Toggle label="音效" on={cfg.sfx} set={(v) => setCfg({...cfg, sfx: v})} />
                <Toggle label="资料来源" on={cfg.sources} set={(v) => setCfg({...cfg, sources: v})} />
              </div>
              <div style={{marginTop: 14}}>
                <button style={btn} onClick={() => void submit()}>
                  ▶ 生成视频{durS ? `（约 ${Math.max(1, Math.round(durS / 60 * 2))} 分钟）` : ''}
                </button>
              </div>
            </Step>
          ) : null}

          {/* 3 正在生成视频：备料→预热→渲染→交回，一条进度条走到底 */}
          {pack || jobId || phase === 'prepping' ? (
            <Step n={3} title="正在生成视频" state={st(3)}
                  summary={phase === 'done' ? '视频已生成' : undefined}>
              {(() => {
                const bar = phase === 'prepping' && !pack ? Math.min(15, 2 + prepPct * 0.13)
                  : pack && !finalUrl && phase !== 'rendering' && phase !== 'uploading' && phase !== 'done'
                    ? 15 + (prewarmDone / Math.max(1, pack.files.length)) * 5
                  : phase === 'rendering' ? 20 + pct * 0.75
                  : phase === 'uploading' ? 97 : phase === 'done' ? 100 : 0;
                const line = phase === 'error' ? ''
                  : phase === 'prepping' && !pack ? `云端备料 · ${prepMsg}`
                  : phase === 'uploading' ? '交回云端…'
                  : phase === 'done' ? ''
                  : pack && phase !== 'rendering' ? `缓存素材 ${prewarmDone}/${pack.files.length}`
                  : `本机生成中 ${pct}%`;
                return (
                  <div>
                    {phase !== 'error' && phase !== 'done' ? (
                      <>
                        <div style={{height: 6, background: C.line, borderRadius: 3, overflow: 'hidden'}}>
                          <div style={{width: `${bar}%`, height: '100%', background: C.accent, transition: 'width .4s'}} />
                        </div>
                        <div style={{fontSize: 13, color: C.soft, marginTop: 6}}>{line}</div>
                      </>
                    ) : null}
                    {phase === 'ready' ? (
                      <button style={{...btn, marginTop: 10}} onClick={() => void startRender()}>
                        ▶ 生成视频（约 {Math.max(1, Math.round(durS / 60 * 2))} 分钟）
                      </button>
                    ) : null}
                    {phase === 'error' ? (
                      <button style={{...btn, marginTop: 10}} onClick={() => void startRender()}>
                        ↻ 重试
                      </button>
                    ) : null}
                  </div>
                );
              })()}
            </Step>
          ) : null}

          {/* 4 取走成片 */}
          {finalUrl ? (
            <Step n={4} title="取走成片" state="done" open>
              <div style={{display: 'flex', flexDirection: 'column', gap: 10}}>
                <a style={btn} href={finalUrl} download={fileName}>下载 MP4 成片</a>
                <button style={{...btnLine, alignSelf: 'flex-start', opacity: (jyBusy || layerMsg) ? 0.6 : 1}}
                        disabled={jyBusy || !!layerMsg} onClick={() => void jianying()}>
                  导入剪映
                </button>
                {layerMsg ? (
                  <div style={{fontSize: 12.5, color: C.soft, lineHeight: 1.7}}>{layerMsg}</div>
                ) : null}
                {layersOk !== null && !layerMsg ? (
                  <div style={{fontSize: 12.5, color: layersOk ? C.ok : C.soft, lineHeight: 1.7}}>
                    {layersOk ? `剪映分轨图层已备好：${layerNote || '底板、卡片、可改文字各一条轨'}`
                              : '分轨图层没出全' + (layerErr ? `（${layerErr}）` : '')
                                + '：仍可导入剪映，但卡片只能整条挪'}
                  </div>
                ) : null}
                {jy ? <div style={{fontSize: 12.5, color: C.soft, lineHeight: 1.7}}>{jy}</div> : null}
                <div style={{fontSize: 12.5, color: C.soft}}>
                  {!me || me.tier === 'free' ? '免费版成片带 GetCut 水印 · '
                    : brandOn ? '右上角已带上你的品牌角标 · ' : '本条按你的档位干净出片（无水印）· '}
                  {!me || me.tier === 'free' ? (
                    <button style={lnkAcc} onClick={() => setSheet('pricing')}>看权益</button>
                  ) : (
                    <button style={lnkAcc} onClick={() => setSheet('brand')}>品牌套装</button>
                  )}
                </div>
                <div style={{fontSize: 12.5, color: cloudOk ? C.ok : C.soft}}>
                  {cloudOk ? '已同步云端工作台 · ' : '云端交回失败，不影响本机下载 · '}
                  {cloudOk && jobId ? <a href={`/#/project/${projectId}`} style={{color: C.accent}}>去工作台看历史</a> : null}
                </div>
                <button style={{...btnLine, alignSelf: 'flex-start'}} onClick={reset}>再做一条</button>
              </div>
            </Step>
          ) : null}
        </div>

        {err ? <div style={{fontSize: 13, color: C.err, lineHeight: 1.6}}>出错：{err}</div> : null}

        <div style={{marginTop: 'auto', fontSize: 12, color: C.soft, lineHeight: 1.8}}>
          生成期间请保持本页打开。画面与声音都在这台电脑上完成，服务器零渲染。
        </div>
      </div>

      {/* 右：结果 */}
      <div style={{display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, minWidth: 0}}>
        <div style={{height: 'min(92vh, 1200px)', aspectRatio: '9 / 16', position: 'relative',
                     background: '#0d0c0b', borderRadius: 14, overflow: 'hidden'}}>
          {finalUrl ? (
            <video src={finalUrl} controls autoPlay style={{width: '100%', height: '100%', objectFit: 'contain'}} />
          ) : pack && phase === 'rendering' ? (
            /* 渲染期卸载 Player：同一时刻只保留 web-renderer 那一份合成 */
            <div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                         alignItems: 'center', justifyContent: 'center', gap: 10, color: '#b5afa6'}}>
              <div style={{fontSize: 40, fontWeight: 800, color: '#fff'}}>{pct}%</div>
              <div style={{fontSize: 14}}>生成视频中…</div>
            </div>
          ) : pack ? (
            <Player
              ref={playerRef}
              component={NiwoVideo as React.FC<Record<string, unknown>>}
              inputProps={pack.props as unknown as Record<string, unknown>}
              durationInFrames={pack.props.durationInFrames}
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
          ) : (
            <div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                         alignItems: 'center', justifyContent: 'center', gap: 16, color: '#8a857d', padding: 30, textAlign: 'center'}}>
              {title ? (
                <>
                  <div style={{fontSize: 24, fontWeight: 800, color: '#efece7', lineHeight: 1.6}}>{title}</div>
                  <div style={{fontSize: 13}}>{phase === 'prepping' ? '云端配音分镜中，稍候自动开渲' : '已导入，检查左侧配置'}</div>
                </>
              ) : (
                <div style={{fontSize: 15, lineHeight: 2}}>素材包进来后<br />成片会在这里出现</div>
              )}
            </div>
          )}
          {pack && !finalUrl && phase !== 'rendering' ? (
            <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, padding: '28px 16px 10px',
                         textAlign: 'center', fontSize: 12, color: '#b5afa6',
                         background: 'linear-gradient(transparent, rgba(0,0,0,.55))'}}>
              实时预览（静音） · 成片带配音与音乐
            </div>
          ) : null}
        </div>
      </div>

      {toast ? (
        <div style={{
          position: 'fixed', left: '50%', bottom: 28, transform: 'translateX(-50%)', zIndex: 60,
          background: C.ink, color: '#fff', fontSize: 13.5, padding: '10px 18px', borderRadius: 24,
          boxShadow: '0 10px 30px rgba(0,0,0,.25)',
        }}>{toast}</div>
      ) : null}
    </div>
  );
};

const el =
  document.getElementById('root') ??
  Object.assign(document.createElement('div'), {id: 'root'});
document.body.appendChild(el);
createRoot(el).render(<App />);
