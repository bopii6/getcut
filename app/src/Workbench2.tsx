import { useRef, useState } from 'react';
import { planScript, renderVideo } from './lib/render';
import type { ThemeName } from './lib/types';

type Choice = ThemeName | 'auto';

const STYLES: { id: Choice; name: string }[] = [
  { id: 'auto', name: '自动' },
  { id: 'poster', name: '大字报' },
  { id: 'magazine', name: '杂志' },
  { id: 'dashboard', name: '数据' },
  { id: 'news', name: '新闻' },
  { id: 'newsroom', name: '播报' },
  { id: 'ledger', name: '财报' },
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

  const chars = text.trim().length;
  const est = Math.max(0, Math.round(chars / 4.6));

  async function run() {
    if (busy.current) return;
    const src = text.trim();
    if (src.length < 20) { setErr('再写几句，至少 20 个字'); return; }
    busy.current = true;
    setRunning(true);
    setErr(null); setUrl(null); setPct(0); setSecs(null);
    const t0 = performance.now();
    const theme = choice === 'auto' ? pickTheme(src) : choice;
    console.log('[getcut] theme =', theme);
    try {
      setStage('读文案，拆镜头');
      const plan = await planScript(src);
      const title = src.split(/[。！？\n]/)[0].slice(0, 14);
      const blob = await renderVideo(plan, theme, title, ({ stage: s, percent }) => {
        setStage(s);
        setPct(percent);
      }, broll, music);
      setSecs(Math.round((performance.now() - t0) / 1000));
      setUrl(URL.createObjectURL(blob));
      setPct(100);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      busy.current = false;
      setRunning(false);
    }
  }

  return (
    <div className="page">
      <header>
        <a className="brand" href="/">GetCut</a>
        <span className="note">免费试做 · 素材不上传</span>
      </header>

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
              <a className="primary" href={url} download="getcut.mp4">下载 MP4</a>
              <button className="ghost" onClick={() => { setUrl(null); setPct(0); setStage(''); }}>
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
            {running ? <div className="progress"><i style={{ width: `${pct}%` }} /></div> : null}
            {err ? <p className="err">{err}</p> : null}
          </>
        )}
      </section>

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

        .hero { padding: 56px 0 34px; }
        .hero h1 { margin: 0; font-size: 46px; line-height: 1.25; font-weight: 900; letter-spacing: -.5px; }
        .hero p { margin: 16px 0 0; color: var(--dim); font-size: 15px; line-height: 1.8; }

        .samples { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
        .samples figure { margin: 0; }
        .samples video { width: 100%; max-height: 330px; aspect-ratio: 9/16; object-fit: cover; border-radius: 14px;
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
        .checks { display: inline-flex; gap: 16px; }
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





