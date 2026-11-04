import { useRef, useState } from 'react';
import { planScript, renderVideo } from './lib/render';
import type { ThemeName } from './lib/types';

const THEMES: { id: ThemeName; name: string; hint: string }[] = [
  { id: 'poster', name: '大字报', hint: '黑金 · 一屏一句' },
  { id: 'magazine', name: '杂志风', hint: '暖纸 · 印章红' },
  { id: 'dashboard', name: '数据面板', hint: '深蓝 · 数字图表' },
];

const DEMO = `想开一家小店，你最怕的是什么？
不是没客人，是钱投进去，三个月就撑不住。
今天讲三个数，你记下来再去谈加盟。
第一个数，前期总投入。加盟费、保证金、装修、设备、首批物料，加起来才是真数。
第二个数，回本周期。总部说八个月，你就按十二个月算，多出来的四个月是你的活路。
第三个数，日均流水。别问总部要，去他现有的店里蹲三天。
这三个数算完，你大概就知道这门生意能不能做。
如果你正在看某个项目，把品牌名发给我，我帮你把这三个数拆开算一遍。`;

export default function App() {
  const [text, setText] = useState('');
  const [theme, setTheme] = useState<ThemeName>('poster');
  const [status, setStatus] = useState('待机');
  const [pct, setPct] = useState(0);
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ms, setMs] = useState<number | null>(null);
  const busy = useRef(false);

  async function run() {
    if (busy.current) return;
    const src = text.trim();
    if (src.length < 20) { setErr('文案太短了，至少 20 个字'); return; }
    busy.current = true;
    setErr(null); setUrl(null); setPct(0); setMs(null);
    const t0 = performance.now();
    try {
      setStatus('AI 拆稿…');
      const plan = await planScript(src);
      const title = src.split(/[。！？\n]/)[0].slice(0, 14);
      const blob = await renderVideo(plan, theme, title, ({ stage, percent }) => {
        setStatus(stage);
        setPct(percent);
      });
      setMs(Math.round(performance.now() - t0));
      setUrl(URL.createObjectURL(blob));
      setStatus(`完成 · ${(blob.size / 1024 / 1024).toFixed(1)} MB`);
      setPct(100);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setStatus('失败');
    } finally {
      busy.current = false;
    }
  }

  return (
    <div className="page">
      <header>
        <div className="brand">Get<span>Cut</span></div>
        <div className="tag">纯浏览器出片 · 不装客户端 · 不上传素材</div>
      </header>

      <main>
        <section className="panel">
          <label className="label">01 · 粘贴文案</label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="把口播稿粘进来，200~1200 字。AI 会自己拆镜头、选卡片、配音。"
          />
          <div className="row">
            <span>{text.trim().length} 字</span>
            <button className="ghost" onClick={() => setText(DEMO)}>填一段示例</button>
          </div>

          <label className="label" style={{ marginTop: 22 }}>02 · 选长相</label>
          <div className="themes">
            {THEMES.map((t) => (
              <button
                key={t.id}
                className={`theme ${theme === t.id ? 'on' : ''}`}
                onClick={() => setTheme(t.id)}
              >
                <b>{t.name}</b><span>{t.hint}</span>
              </button>
            ))}
          </div>

          <div style={{ marginTop: 22 }}>
            <button className="go" onClick={run} disabled={busy.current}>生成视频</button>
            <div className="status">{status}{pct ? ` · ${pct}%` : ''}{ms ? ` · ${(ms / 1000).toFixed(1)} 秒` : ''}</div>
            {err ? <pre className="err">{err}</pre> : null}
          </div>
        </section>

        <section className="panel">
          <label className="label">03 · 成片</label>
          <div className="phone">
            {url ? <video src={url} controls playsInline /> : <span>竖屏 1080×1920<br />出片会出现在这里</span>}
          </div>
          <div className="bar"><i style={{ width: `${pct}%` }} /></div>
          {url ? <a className="dl" href={url} download="getcut.mp4">下载 MP4</a> : null}
        </section>
      </main>

      <style>{`
        * { box-sizing: border-box; }
        body { margin: 0; background: #0b0a09; color: #f3efe6;
          font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; }
        .page { max-width: 1200px; margin: 0 auto; padding: 26px; }
        header { display: flex; justify-content: space-between; align-items: center;
          padding-bottom: 18px; border-bottom: 1px solid rgba(243,239,230,0.12); }
        .brand { font-size: 28px; font-weight: 900; letter-spacing: 2px; }
        .brand span { color: #d8a94a; }
        .tag { font-size: 13px; color: rgba(243,239,230,0.5); }
        main { display: grid; grid-template-columns: 1fr 400px; gap: 24px; margin-top: 24px; }
        .panel { border: 1px solid rgba(243,239,230,0.12); border-radius: 16px; padding: 20px;
          background: linear-gradient(180deg, #171412, #121110); }
        .label { display: block; font-size: 13px; letter-spacing: 3px; color: rgba(243,239,230,0.5); margin-bottom: 12px; }
        textarea { width: 100%; min-height: 300px; resize: vertical; background: #0d0c0a; color: #f3efe6;
          border: 1px solid rgba(243,239,230,0.2); border-radius: 12px; padding: 16px; font-size: 15px;
          line-height: 1.9; font-family: inherit; outline: none; }
        textarea:focus { border-color: #d8a94a; }
        .row { display: flex; justify-content: space-between; align-items: center;
          font-size: 13px; color: rgba(243,239,230,0.5); margin-top: 8px; }
        .themes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .theme { text-align: left; background: #0d0c0a; color: #f3efe6; cursor: pointer;
          border: 1px solid rgba(243,239,230,0.14); border-radius: 12px; padding: 14px; }
        .theme.on { border-color: #d8a94a; }
        .theme b { display: block; font-size: 16px; margin-bottom: 6px; }
        .theme span { font-size: 12px; color: rgba(243,239,230,0.5); }
        .go { background: #d8a94a; color: #16120a; border: 0; border-radius: 12px;
          padding: 14px 26px; font-size: 16px; font-weight: 800; letter-spacing: 2px; cursor: pointer; }
        .go:disabled { opacity: .55; cursor: not-allowed; }
        .ghost { background: transparent; color: #f3efe6; border: 1px solid rgba(243,239,230,0.25);
          border-radius: 10px; padding: 8px 14px; cursor: pointer; font-size: 13px; }
        .status { margin-top: 12px; font-size: 13px; color: rgba(243,239,230,0.6); }
        .err { color: #ff8a7a; font-size: 13px; white-space: pre-wrap; }
        .phone { width: 100%; aspect-ratio: 9/16; border-radius: 16px; overflow: hidden;
          background: #080706; border: 1px solid rgba(243,239,230,0.12);
          display: flex; align-items: center; justify-content: center; font-size: 13px;
          color: rgba(243,239,230,0.4); text-align: center; line-height: 1.8; }
        .phone video { width: 100%; height: 100%; object-fit: cover; }
        .bar { height: 6px; background: rgba(243,239,230,0.08); border-radius: 999px; margin-top: 14px; overflow: hidden; }
        .bar i { display: block; height: 100%; background: linear-gradient(90deg,#b4432f,#d8a94a); transition: width .3s; }
        .dl { display: inline-block; margin-top: 14px; color: #d8a94a; font-size: 14px; }
        @media (max-width: 980px) { main { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}
