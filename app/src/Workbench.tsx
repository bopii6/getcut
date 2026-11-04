import { useRef, useState } from 'react';
import { planScript, renderVideo } from './lib/render';
import type { ThemeName } from './lib/types';

const THEMES: { id: ThemeName; name: string; hint: string; swatch: string; ink: string }[] = [
  { id: 'poster', name: '大字报', hint: '黑金 · 一屏一句', swatch: 'linear-gradient(140deg,#0a0a09,#1d1708)', ink: '#ffd400' },
  { id: 'magazine', name: '杂志风', hint: '暖纸 · 印章红', swatch: 'linear-gradient(140deg,#f6f2e9,#e3d9c6)', ink: '#c0392b' },
  { id: 'dashboard', name: '数据面板', hint: '深蓝 · 数字', swatch: 'linear-gradient(140deg,#06101f,#0f2a44)', ink: '#40a9ff' },
  { id: 'news', name: '新闻播报', hint: '白底 · 正红', swatch: 'linear-gradient(140deg,#faf8f5,#ece6de)', ink: '#d62828' },
  { id: 'night', name: '夜行', hint: '深紫 · 冷光', swatch: 'linear-gradient(140deg,#0b0a16,#2a1f5c)', ink: '#a78bfa' },
];

const DEMO = `想开一家小店，你最怕的是什么？
不是没客人，是钱投进去，三个月就撑不住。
今天讲三个数，你记下来再去谈加盟。
第一个数，前期总投入。加盟费、保证金、装修、设备、首批物料，加起来才是真数。
第二个数，回本周期。总部说八个月，你就按十二个月算，多出来的四个月是你的活路。
第三个数，日均流水。别问总部要，去他现有的店里蹲三天。
这三个数算完，你大概就知道这门生意能不能做。
如果你正在看某个项目，把品牌名发给我，我帮你把这三个数拆开算一遍。`;

const STEPS = ['拆稿', '空镜', '配音', '画帧', '封片'];

export default function Workbench() {
  const [text, setText] = useState('');
  const [theme, setTheme] = useState<ThemeName>('poster');
  const [useBroll, setUseBroll] = useState(false);
  const [status, setStatus] = useState('待机');
  const [pct, setPct] = useState(0);
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ms, setMs] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const busy = useRef(false);

  const chars = text.trim().length;
  const seconds = Math.max(0, Math.round(chars / 4.6));
  const active = running ? Math.min(4, Math.floor(pct / 22)) : -1;

  async function run() {
    if (busy.current) return;
    const src = text.trim();
    if (src.length < 20) { setErr('文案太短了，至少 20 个字'); return; }
    busy.current = true;
    setRunning(true);
    setErr(null); setUrl(null); setPct(0); setMs(null);
    const t0 = performance.now();
    try {
      setStatus('AI 拆稿');
      const plan = await planScript(src);
      const title = src.split(/[。！？\n]/)[0].slice(0, 14);
      const blob = await renderVideo(plan, theme, title, ({ stage, percent }) => {
        setStatus(stage);
        setPct(percent);
      }, useBroll);
      setMs(Math.round(performance.now() - t0));
      setUrl(URL.createObjectURL(blob));
      setStatus('完成');
      setPct(100);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setStatus('失败');
    } finally {
      busy.current = false;
      setRunning(false);
    }
  }

  return (
    <div className="app">
      <div className="grain" />

      <header className="top">
        <div className="wordmark">Get<span>Cut</span></div>
        <div className="top-meta">
          <span>纯浏览器渲染</span>
          <i />
          <span>素材不上传</span>
          <i />
          <span>1080×1920</span>
        </div>
      </header>

      <section className="hero">
        <p className="eyebrow">获客短视频 · 本机产出</p>
        <h1>把一段文案，<br /><em>做成一条能发的片。</em></h1>
        <p className="sub">AI 拆镜 · 逐句配音 · 实拍空镜 · 浏览器里编码成 MP4。不装软件，不等排队。</p>
      </section>

      <main className="grid">
        <section className="card">
          <div className="block">
            <div className="step"><b>01</b><span>文案</span></div>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={'把口播稿粘进来。\n\n比如：想开一家小店，你最怕的是什么？不是没客人，是钱投进去三个月就撑不住……'}
            />
            <div className="row">
              <span className="dim">{chars} 字 · 约 {seconds} 秒</span>
              <button className="link" onClick={() => setText(DEMO)}>填一段示例</button>
            </div>
          </div>

          <div className="block">
            <div className="step"><b>02</b><span>视觉</span></div>
            <div className="swatches">
              {THEMES.map((t) => (
                <button
                  key={t.id}
                  className={`swatch ${theme === t.id ? 'on' : ''}`}
                  onClick={() => setTheme(t.id)}
                >
                  <span className="chip" style={{ background: t.swatch }}>
                    <i style={{ background: t.ink }} />
                  </span>
                  <b>{t.name}</b>
                  <em>{t.hint}</em>
                </button>
              ))}
            </div>
          </div>

          <div className="block row between">
            <label className="toggle">
              <input type="checkbox" checked={useBroll} onChange={(e) => setUseBroll(e.target.checked)} />
              <span className="dot" />
              配实拍空镜<em>慢 1~2 分钟</em>
            </label>
            <span className="dim">Pexels 免费素材</span>
          </div>

          <button className="cta" onClick={run} disabled={running}>
            {running ? '正在生成…' : '生成视频'}
            <span className="arrow">→</span>
          </button>

          <div className="steps">
            {STEPS.map((s, i) => (
              <div key={s} className={`pipe ${i <= active ? 'on' : ''}`}>
                <i />
                {s}
              </div>
            ))}
          </div>

          <div className="statusbar">
            <span>{status}{pct ? ` · ${pct}%` : ''}{ms ? ` · ${(ms / 1000).toFixed(1)} 秒` : ''}</span>
            {err ? <span className="err">{err}</span> : null}
          </div>

          <div className="progress"><i style={{ width: `${pct}%` }} /></div>
        </section>

        <aside className="preview">
          <div className="phone">
            {url ? <video src={url} controls playsInline /> : (
              <div className="empty">
                <span>成片在这里</span>
                <em>1080 × 1920 · 30fps · H.264</em>
              </div>
            )}
          </div>
          <div className="preview-foot">
            <span className="dim">{url ? '已生成 · 可直接下载' : '生成后可直接下载'}</span>
            {url ? <a className="dl" href={url} download="getcut.mp4">下载 MP4</a> : <span className="dim">—</span>}
          </div>
        </aside>
      </main>

      <footer>
        <span>GetCut · 本机出片</span>
        <span>文案 20~1200 字</span>
      </footer>

      <style>{`
        :root {
          --bg: #0a0908;
          --panel: #131110;
          --panel-2: #191614;
          --line: rgba(244,239,228,0.10);
          --line-2: rgba(244,239,228,0.18);
          --ink: #f4efe4;
          --dim: rgba(244,239,228,0.46);
          --gold: #d8a94a;
          --gold-ink: #171207;
        }
        * { box-sizing: border-box; }
        html, body, #root { min-height: 100%; }
        body { margin: 0; background: var(--bg); color: var(--ink);
          font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
          -webkit-font-smoothing: antialiased; }
        .app { position: relative; max-width: 1180px; margin: 0 auto; padding: 28px 28px 48px; }
        .grain { pointer-events: none; position: fixed; inset: 0; opacity: .35;
          background-image: radial-gradient(rgba(244,239,228,0.055) 1px, transparent 1px);
          background-size: 3px 3px; }

        .top { display: flex; align-items: center; justify-content: space-between;
          padding-bottom: 20px; border-bottom: 1px solid var(--line); position: relative; z-index: 1; }
        .wordmark { font-size: 24px; font-weight: 900; letter-spacing: .5px; }
        .wordmark span { color: var(--gold); }
        .top-meta { display: flex; align-items: center; gap: 14px; font-size: 12px; color: var(--dim); letter-spacing: 1px; }
        .top-meta i { width: 3px; height: 3px; border-radius: 50%; background: var(--line-2); }

        .hero { padding: 54px 0 40px; position: relative; z-index: 1; }
        .eyebrow { margin: 0 0 18px; font-size: 12px; letter-spacing: 4px; color: var(--gold); }
        .hero h1 { margin: 0; font-size: 54px; line-height: 1.18; letter-spacing: -1px; font-weight: 900; }
        .hero h1 em { font-style: normal; color: var(--gold); }
        .sub { margin: 18px 0 0; color: var(--dim); font-size: 14px; letter-spacing: .5px; }

        .grid { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 22px; align-items: start; position: relative; z-index: 1; }
        .card { background: linear-gradient(180deg, var(--panel-2), var(--panel));
          border: 1px solid var(--line); border-radius: 18px; padding: 22px;
          box-shadow: 0 1px 0 rgba(255,255,255,0.04) inset, 0 24px 60px -30px rgba(0,0,0,.9); }
        .block { margin-bottom: 22px; }
        .step { display: flex; align-items: center; gap: 10px; margin-bottom: 12px;
          font-size: 12px; letter-spacing: 3px; color: var(--dim); }
        .step b { display: inline-flex; align-items: center; justify-content: center;
          width: 26px; height: 26px; border-radius: 50%; border: 1px solid var(--line-2);
          font-size: 11px; color: var(--ink); letter-spacing: 0; }
        textarea { width: 100%; min-height: 260px; resize: vertical; background: #0c0b09; color: var(--ink);
          border: 1px solid var(--line); border-radius: 14px; padding: 16px 18px; font-size: 15px;
          line-height: 1.95; font-family: inherit; outline: none; transition: border-color .2s, box-shadow .2s; }
        textarea::placeholder { color: rgba(244,239,228,0.28); }
        textarea:focus { border-color: rgba(216,169,74,.65); box-shadow: 0 0 0 3px rgba(216,169,74,.12); }
        .row { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; }
        .row.between { justify-content: space-between; }
        .dim { font-size: 12px; color: var(--dim); }
        .link { background: none; border: 0; color: var(--gold); font-size: 12px; cursor: pointer; letter-spacing: .5px; }
        .link:hover { text-decoration: underline; }

        .swatches { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
        .swatch { background: transparent; border: 1px solid var(--line); border-radius: 12px; padding: 8px;
          text-align: left; cursor: pointer; color: var(--ink); transition: border-color .2s, transform .2s; }
        .swatch:hover { transform: translateY(-1px); border-color: var(--line-2); }
        .swatch.on { border-color: var(--gold); box-shadow: 0 0 0 1px rgba(216,169,74,.35); }
        .swatch .chip { display: block; height: 46px; border-radius: 8px; margin-bottom: 8px; position: relative; overflow: hidden; }
        .swatch .chip i { position: absolute; right: 8px; bottom: 8px; width: 10px; height: 10px; border-radius: 3px; }
        .swatch b { display: block; font-size: 13px; font-weight: 700; }
        .swatch em { display: block; font-style: normal; font-size: 11px; color: var(--dim); margin-top: 2px; }

        .toggle { display: inline-flex; align-items: center; gap: 10px; font-size: 13px; color: var(--ink); cursor: pointer; }
        .toggle input { display: none; }
        .toggle .dot { width: 34px; height: 20px; border-radius: 999px; background: rgba(244,239,228,.14); position: relative; transition: background .2s; }
        .toggle .dot::after { content: ''; position: absolute; top: 3px; left: 3px; width: 14px; height: 14px;
          border-radius: 50%; background: var(--ink); transition: transform .2s; }
        .toggle input:checked + .dot { background: rgba(216,169,74,.85); }
        .toggle input:checked + .dot::after { transform: translateX(14px); background: var(--gold-ink); }
        .toggle em { font-style: normal; color: var(--dim); font-size: 11px; margin-left: 6px; }

        .cta { width: 100%; margin-top: 6px; border: 0; border-radius: 14px; cursor: pointer;
          background: linear-gradient(180deg, #e6b95c, var(--gold)); color: var(--gold-ink);
          font-size: 16px; font-weight: 900; letter-spacing: 2px; padding: 16px 20px;
          display: flex; align-items: center; justify-content: space-between;
          transition: transform .15s, box-shadow .2s; box-shadow: 0 10px 30px -12px rgba(216,169,74,.6); }
        .cta:hover:not(:disabled) { transform: translateY(-1px); }
        .cta:disabled { opacity: .55; cursor: not-allowed; box-shadow: none; }
        .cta .arrow { font-size: 20px; }

        .steps { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin-top: 18px; }
        .pipe { font-size: 11px; color: var(--dim); display: flex; align-items: center; gap: 6px; }
        .pipe i { width: 100%; max-width: 18px; height: 2px; background: var(--line-2); display: block; }
        .pipe.on { color: var(--gold); }
        .pipe.on i { background: var(--gold); }

        .statusbar { display: flex; justify-content: space-between; gap: 12px; margin-top: 12px; font-size: 12px; color: var(--dim); }
        .err { color: #ff9a86; }
        .progress { height: 3px; background: rgba(244,239,228,.08); border-radius: 999px; margin-top: 10px; overflow: hidden; }
        .progress i { display: block; height: 100%; width: 0; background: linear-gradient(90deg, #b4432f, var(--gold)); transition: width .35s; }

        .preview { position: sticky; top: 24px; }
        .phone { aspect-ratio: 9 / 16; border-radius: 26px; overflow: hidden; background: #070605;
          border: 8px solid #171412; box-shadow: 0 30px 80px -40px rgba(0,0,0,.95), 0 0 0 1px rgba(244,239,228,.06); }
        .phone video { width: 100%; height: 100%; object-fit: cover; display: block; }
        .empty { height: 100%; display: flex; flex-direction: column; gap: 8px; align-items: center; justify-content: center;
          color: rgba(244,239,228,.3); font-size: 13px; }
        .empty em { font-style: normal; font-size: 11px; color: rgba(244,239,228,.2); letter-spacing: 1px; }
        .preview-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 12px; }
        .dl { color: var(--gold); font-size: 13px; text-decoration: none; border-bottom: 1px solid rgba(216,169,74,.35); padding-bottom: 1px; }

        footer { display: flex; justify-content: space-between; margin-top: 40px; padding-top: 18px;
          border-top: 1px solid var(--line); color: var(--dim); font-size: 12px; letter-spacing: 1px; position: relative; z-index: 1; }

        @media (max-width: 980px) {
          .grid { grid-template-columns: 1fr; }
          .hero h1 { font-size: 38px; }
          .swatches { grid-template-columns: repeat(3, 1fr); }
          .preview { position: static; }
        }
      `}</style>
    </div>
  );
}
