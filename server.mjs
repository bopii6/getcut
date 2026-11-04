// 本机工作台：一个页面 + 一个 POST，后台跑 render.mjs，前端轮询进度。
// 没有数据库、没有队列、没有账号——就是本机的一条流水线。
import http from 'node:http';
import { createReadStream, existsSync, statSync } from 'node:fs';
import { readFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { applyEnv } from './lib/env.mjs';
import { binary } from './lib/ffmpeg.mjs';

// 钥匙从本项目的 .env 读，子进程（render.mjs）直接继承
applyEnv(['DEEPSEEK_API_KEY', 'PEXELS_API_KEY']);

/** 环境自检：页面顶部那条横幅用的，缺什么直接说怎么补。 */
function health() {
  const checks = [];
  const ff = binary('ffmpeg');
  checks.push({ name: 'ffmpeg', ok: ff !== 'ffmpeg', hint: '没装 ffmpeg：双击 安装.bat 自动装' });
  let edgeOk = false;
  try {
    execFileSync('python', ['-c', 'import edge_tts'], { stdio: 'ignore', timeout: 15000 });
    edgeOk = true;
  } catch { edgeOk = false; }
  checks.push({ name: 'edge-tts', ok: edgeOk, hint: '缺 Python 配音组件：在命令行跑 pip install edge-tts' });
  checks.push({ name: 'DeepSeek 钥匙', ok: Boolean(process.env.DEEPSEEK_API_KEY), hint: '没有 DEEPSEEK_API_KEY：拆稿会退回规则版，画面会比较呆' });
  checks.push({ name: 'Pexels 钥匙', ok: Boolean(process.env.PEXELS_API_KEY), hint: '没有 PEXELS_API_KEY：不会抓实拍空镜，只剩排版' });
  return { ok: checks.every((c) => c.ok), checks };
}

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.GETCUT_UI_PORT || 8901);
const OUT_DIR = path.join(ROOT, 'out');
await mkdir(OUT_DIR, { recursive: true });

const STYLES = {
  magazine: { name: '杂志风', hint: '暖纸底 · 印章红' },
  poster: { name: '大字报', hint: '黑金 · 一屏一句' },
  dashboard: { name: '数据面板', hint: '深蓝 · 数字图表' },
};

const jobs = new Map();

function json(res, code, body) {
  const data = JSON.stringify(body);
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' });
  res.end(data);
}

function staticFile(res, file) {
  const ext = path.extname(file).toLowerCase();
  const type = {
    '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8', '.otf': 'font/otf', '.mp4': 'video/mp4',
    '.png': 'image/png', '.jpg': 'image/jpeg',
  }[ext] || 'application/octet-stream';
  if (!existsSync(file)) { res.writeHead(404); res.end('not found'); return; }
  res.writeHead(200, { 'content-type': type, 'cache-control': 'no-cache' });
  createReadStream(file).pipe(res);
}

function startJob(text, theme) {
  const id = randomUUID().slice(0, 8);
  const job = { id, status: 'running', percent: 2, log: [], video: null, createdAt: Date.now() };
  jobs.set(id, job);
  const output = path.join(OUT_DIR, `${id}.mp4`);
  const child = spawn(process.execPath, ['scripts/render.mjs', '--text', text, '--theme', theme, '-o', output], {
    cwd: ROOT, windowsHide: true,
  });
  const push = (line) => {
    const s = line.replace(/\r/g, '').trim();
    if (!s) return;
    job.log.push(s);
    if (job.log.length > 200) job.log.shift();
    if (s.includes('[1/5]')) job.percent = 8;
    else if (s.includes('[2/5]')) job.percent = 26;
    else if (s.includes('[3/5]')) job.percent = 46;
    else if (s.startsWith('[4/5]')) job.percent = 60;
    else if (s.includes('[5/5]')) { job.percent = 100; job.status = 'done'; job.video = `/api/file/${id}.mp4`; }
    else if (s.startsWith('切出')) job.percent = 12;
    else if (s.includes('约') && s.includes('秒')) job.percent = 34;
    else if (s.includes('配到了实拍')) job.percent = 52;
    const m = s.match(/Rendered (\d+)\/(\d+)|(\d+)%/);
    if (m && job.percent < 99) {
      const pct = m[3] ? Number(m[3]) : Math.round((Number(m[1]) / Number(m[2])) * 100);
      job.percent = Math.max(job.percent, 60 + Math.round(pct * 0.38));
    }
  };
  const onData = (buf) => String(buf).split('\n').forEach(push);
  child.stdout.on('data', onData);
  child.stderr.on('data', onData);
  child.on('error', (e) => { job.status = 'failed'; job.error = e.message; });
  child.on('close', (code) => {
    if (code === 0 && job.status === 'running') { job.status = 'done'; job.percent = 100; job.video = `/api/file/${id}.mp4`; }
    if (code !== 0) { job.status = 'failed'; job.error = `渲染退出码 ${code}`; }
  });
  setTimeout(() => { if (jobs.get(id)?.status === 'running') { child.kill(); job.status = 'failed'; job.error = '超过 20 分钟，已终止'; } }, 20 * 60 * 1000);
  return job;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (req.method === 'GET' && (url.pathname === '/' || url.pathname === '/index.html')) {
    return staticFile(res, path.join(ROOT, 'web', 'index.html'));
  }
  if (req.method === 'GET' && url.pathname.startsWith('/fonts/')) {
    return staticFile(res, path.join(ROOT, 'public', url.pathname));
  }
  if (req.method === 'GET' && url.pathname.startsWith('/api/file/')) {
    return staticFile(res, path.join(OUT_DIR, path.basename(url.pathname)));
  }
  if (req.method === 'GET' && url.pathname === '/api/styles') {
    return json(res, 200, STYLES);
  }
  if (req.method === 'GET' && url.pathname === '/api/health') {
    return json(res, 200, health());
  }
  if (req.method === 'POST' && url.pathname === '/api/render') {
    let body = '';
    for await (const chunk of req) body += chunk;
    let payload;
    try { payload = JSON.parse(body); } catch { return json(res, 400, { error: '请求不是 JSON' }); }
    const text = String(payload.text || '').trim();
    const theme = STYLES[payload.theme] ? payload.theme : 'magazine';
    if (text.length < 20) return json(res, 400, { error: '文案太短了，至少 20 个字' });
    if (text.length > 1600) return json(res, 400, { error: '文案太长了，5 分钟上限约 1200 字' });
    const job = startJob(text, theme);
    return json(res, 200, { id: job.id });
  }
  if (req.method === 'GET' && url.pathname.startsWith('/api/job/')) {
    const job = jobs.get(url.pathname.split('/').pop());
    if (!job) return json(res, 404, { error: '没有这个任务' });
    return json(res, 200, job);
  }
  res.writeHead(404);
  res.end('not found');
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    const next = PORT + 1;
    console.log(`端口 ${PORT} 被占用，换 ${next}`);
    server.listen(next, '127.0.0.1');
    return;
  }
  throw err;
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`GetCut 工作台：http://127.0.0.1:${PORT}`);
});
void statSync;


