import React from 'react';
import {createRoot} from 'react-dom/client';
import {Player, type PlayerRef} from '@remotion/player';
import {NiwoVideo, type NiwoProps} from '../NiwoVideo';

// 浏览器极速渲染页：一键完成（授权 → 领任务 → 预热素材 → 本浏览器渲染 → 交回）。
// 渲染与编码全部发生在本标签页；云端只做写稿/配音/混音等轻活。
// 进度显示在左侧面板（最终成片会裁剪到播放器区域，侧栏不会进入成片）；
// 兜底进度同时写进 document.title。

document.title = 'GetCutPOC';
const qs = new URLSearchParams(location.search);
const agentMode = qs.get('agent') === '1';
const DEVICE = qs.get('device') || '网页浏览器';

const App: React.FC = () => {
  const [props, setProps] = React.useState<NiwoProps | null>(null);
  const [pct, setPct] = React.useState(0);
  const [phase, setPhase] = React.useState('idle');
  const [msg, setMsg] = React.useState('点击下方按钮，开始渲染');
  const playerRef = React.useRef<PlayerRef>(null);
  const jobRef = React.useRef<string | null>(null);
  const propsRef = React.useRef<NiwoProps | null>(null);
  const boxRef = React.useRef<HTMLDivElement>(null);

  const report = async (p: number, detail: string, requeue = false) => {
    const job = jobRef.current;
    if (!job) return false;
    try {
      const r = await fetch(`/api/agent/job/${job}/progress?device=${encodeURIComponent(DEVICE)}`, {
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

  const render = async () => {
    setPhase('capture');
    setMsg('浏览器将请求共享当前标签页——请在弹窗中选择本页并允许');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const stream: MediaStream = await (navigator.mediaDevices as any).getDisplayMedia({
      video: {frameRate: 30},
      audio: false,
      preferCurrentTab: true,
    });
    const track = stream.getVideoTracks()[0];
    const st: any = (track.getSettings?.() || {}) as any;
    const capW = st.width || Math.round(window.innerWidth * (window.devicePixelRatio || 1));
    const capH = st.height || Math.round(window.innerHeight * (window.devicePixelRatio || 1));

    setPhase('claim');
    setMsg('正在领取任务…');
    for (;;) {
      const r = await fetch(`/api/agent/poll?wait=1&device=${encodeURIComponent(DEVICE)}`);
      if (!r.ok) throw new Error(`连接渲染队列失败 HTTP ${r.status}`);
      const data = await r.json();
      if (!data.job) continue;
      jobRef.current = data.job;
      (window as unknown as Record<string, unknown>).remotion_staticBase =
        `/agent-media/${data.job}`;
      // 预热素材：逐个校验必须 200 且进缓存，失败重试一次，再失败就大声报错
      const files: {path: string; size: number}[] = data.files || [];
      let done = 0;
      for (const f of files) {
        const url = `/agent-media/${data.job}/${f.path}`;
        let ok = false;
        for (let a = 0; a < 2 && !ok; a++) {
          try {
            const resp = await fetch(url, {cache: 'force-cache'});
            ok = resp.ok;
          } catch (_) {
            ok = false;
          }
          if (!ok) await new Promise((res) => setTimeout(res, 800));
        }
        if (!ok) throw new Error(`素材加载失败：${f.path}`);
        if (/\.(mp4|webm)$/i.test(f.path)) {
          await new Promise<void>((resolve) => {
            const v = document.createElement('video');
            v.preload = 'auto';
            v.muted = true;
            v.src = url;
            v.onloadeddata = () => resolve();
            v.onerror = () => resolve();
            setTimeout(resolve, 10000);
          });
        }
        done += 1;
        setMsg(`素材预热 ${done}/${files.length}`);
        setPct(Math.round((done / files.length) * 8));
      }

      setPhase('ready');
      setMsg('素材就绪，启动渲染引擎…');
      propsRef.current = data.props as NiwoProps;
      setProps(data.props as NiwoProps);
      await new Promise((res) => setTimeout(res, 1500));
      await document.fonts.ready;
      break;
    }

    setPhase('rec');
    if (!playerRef.current) throw new Error('播放器未就绪');
    playerRef.current.seekTo(0);
    const mime = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
      ? 'video/webm;codecs=vp9'
      : 'video/webm';
    const rec = new MediaRecorder(stream, {mimeType: mime, videoBitsPerSecond: 12_000_000});
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    const t0 = performance.now();
    rec.onstop = async () => {
      const blob = new Blob(chunks, {type: mime});
      const secs = ((performance.now() - t0) / 1000).toFixed(1);
      stream.getTracks().forEach((t) => t.stop());
      const job = jobRef.current;
      setMsg(`渲染完成（${(blob.size / 1048576).toFixed(1)}MB / ${secs}s），交回云端混音…`);
      const r = await fetch(`/api/agent/job/${job}/visual?device=${encodeURIComponent(DEVICE)}`, {
        method: 'POST',
        headers: {'content-type': 'application/octet-stream', 'content-length': String(blob.size)},
        body: blob,
      });
      if (!r.ok) {
        setPhase('idle');
        setMsg('交回失败：' + (await r.text()).slice(0, 120));
        return;
      }
      setPhase('done');
      setMsg('✅ 渲染完成！成片已在云端生成，回到任务页即可下载。本页可以关闭。');
      try {
        window.parent.postMessage({type: 'getcut-export-done', job}, '*');
      } catch (_) {}
    };

    playerRef.current.play();
    const total = (props as NiwoProps).durationInFrames;
    const tick = () => {
      const f = playerRef.current?.getCurrentFrame() ?? 0;
      const p = Math.min(99, Math.round((f / total) * 100));
      setPct(p);
      document.title = `${p}% · GetCut 极速渲染`;
      if (f % 150 === 0) report(p, `浏览器渲染中 ${f}/${total} 帧`);
      if (f >= total - 1) {
        setTimeout(() => {
          if (rec.state !== 'inactive') rec.stop();
        }, 500);
        return;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  const handleClick = () => {
    setMsg('启动中…');
    render().catch((e) => {
      setPhase('idle');
      setMsg('出错：' + String(e && e.message ? e.message : e).slice(0, 200));
    });
  };

  const phText: Record<string, string> = {
    idle: '就绪',
    capture: '等待授权…',
    claim: '正在领取任务…',
    ready: '素材预热中…',
    rec: '正在渲染（进度见百分比）',
    done: '完成',
  };

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        background: '#111',
        color: '#eee',
        fontFamily: 'system-ui, sans-serif',
      }}
    >
      <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: 'calc((100vw - 100vh*9/16)/2)', minWidth: 0, padding: 20, boxSizing: 'border-box', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 14, overflow: 'hidden'}}>
        <div style={{fontSize: 30, fontWeight: 800}}>GetCut 极速渲染</div>
        <div style={{opacity: 0.85, lineHeight: 1.8}}>
          用这台电脑的浏览器渲染你的视频，不排队、不限速。
          <br />
          渲染约需 <b>{props ? Math.round((props.durationInFrames / 30) * 10) / 10 : 60} 秒</b>，
          期间请保持本页在前台，不要切换标签页。
        </div>
        {phase === 'idle' && (
          <button
            onClick={handleClick}
            style={{
              all: 'unset', cursor: 'pointer', alignSelf: 'flex-start',
              background: 'linear-gradient(135deg,#7c3aed,#db2777)', color: '#fff',
              padding: '18px 34px', borderRadius: 16, fontSize: 22, fontWeight: 800,
              boxShadow: '0 10px 36px rgba(124,58,237,.5)',
            }}
          >
            ▶ 开始渲染
          </button>
        )}
        {phase === 'capture' && <div style={{fontSize: 17}}>请在浏览器弹窗中点击「允许 / 分享」</div>}
        <div style={{opacity: 0.8}}>{msg}</div>
        {(phase === 'rec' || phase === 'claim' || (phase === 'done')) && (
          <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
            <div style={{flex: 1, maxWidth: 420, height: 10, background: '#333', borderRadius: 6, overflow: 'hidden'}}>
              <div style={{width: `${pct}%`, height: '100%', background: 'linear-gradient(90deg,#7c3aed,#db2777)'}} />
            </div>
            <div style={{fontSize: 20, fontWeight: 700}}>{pct}%</div>
          </div>
        )}
        <div style={{fontSize: 13, opacity: 0.5}}>
          推荐使用 Chrome 浏览器 · 渲染期间请勿切换标签页 · 切走会自动暂停退单
        </div>
      </div>
      <div style={{height: '100vh', aspectRatio: '9 / 16', position: 'relative', background: '#000'}}>
        {props ? (
          <Player
            ref={playerRef as React.RefObject<PlayerRef>}
            component={NiwoVideo as React.FC<Record<string, unknown>>}
            inputProps={props as unknown as Record<string, unknown>}
            durationInFrames={props.durationInFrames}
            fps={30}
            compositionWidth={1080}
            compositionHeight={1920}
            style={{width: '100%', height: '100%'}}
          />
        ) : (
          <div style={{width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: 0.4}}>
            等待任务…
          </div>
        )}
      </div>
    </div>
  );
};

const el =
  document.getElementById('root') ??
  Object.assign(document.createElement('div'), {id: 'root'});
document.body.appendChild(el);
createRoot(el).render(<App />);
