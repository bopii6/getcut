#!/usr/bin/env node
/* GetCut 渲染台：让你自己的电脑给 GetCut 渲片子。
 *
 * 干的事：长轮询云端领任务 → 下载渲染包（props+素材）→ 用本机的
 * Edge/Chrome/Remotion 自带内核跑 Remotion 渲画面 → 把画面轨交回云端
 * （混音/封装/校验都在云端，都是秒级轻活）。
 *
 * 零依赖，Node ≥ 18（用全局 fetch）。Windows 优先，mac 走 Chrome 路径探测。
 *
 * 用法：
 *   node agent.js --server http://127.0.0.1:8600 \
 *                 [--email you@a.com --password xxx]   // 登录换 90 天设备令牌
 *                 [--token 主钥匙]                      // 调试用，二选一
 *                 [--renderer ../renderer 路径]         // Remotion 工程位置
 *                 [--device 我的笔记本]
 * 配置也可以走环境变量 GETCUT_SERVER / GETCUT_EMAIL / GETCUT_PASSWORD /
 * GETCUT_TOKEN / GETCUT_DEVICE / GETCUT_RENDERER。
 */
'use strict';
const {spawn} = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {pipeline} = require('stream/promises');

// ---------- 配置：命令行 > 环境变量 > 默认 ----------
function arg(name) {
  const argv = process.argv;
  const i = argv.indexOf('--' + name);
  if (i >= 0) {
    const v = argv[i + 1];
    return v && !v.startsWith('--') ? v : true;
  }
  const m = argv.find((a) => a.startsWith('--' + name + '='));
  return m ? m.slice(name.length + 3) : undefined;
}

const HOME = __dirname;
const CFG = {
  server: String(arg('server') || process.env.GETCUT_SERVER || 'http://127.0.0.1:8600').replace(/\/+$/, ''),
  email: String(arg('email') || process.env.GETCUT_EMAIL || ''),
  password: String(arg('password') || process.env.GETCUT_PASSWORD || ''),
  token: String(arg('token') || process.env.GETCUT_TOKEN || ''),
  device: String(arg('device') || process.env.GETCUT_DEVICE || os.hostname()).slice(0, 48),
  renderer: path.resolve(String(arg('renderer') || process.env.GETCUT_RENDERER || path.join(HOME, '..', 'renderer'))),
  workspace: path.resolve(String(arg('workspace') || process.env.GETCUT_WORKSPACE || path.join(HOME, 'workspace'))),
};

const REMOTION_CLI = path.join(CFG.renderer, 'node_modules', '@remotion', 'cli', 'remotion-cli.js');
const TOKEN_FILE = path.join(CFG.workspace, 'agent-token.json');
const PUBLIC = path.join(CFG.renderer, 'public');

function log(msg) {
  console.log(`[${new Date().toLocaleTimeString('zh-CN', {hour12: false})}] ${msg}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- 登录态 ----------
let agentToken = null;
try {
  agentToken = JSON.parse(fs.readFileSync(TOKEN_FILE, 'utf8')).token || null;
} catch (_) { /* 首次运行没有存档 */ }

function authHeaders() {
  if (agentToken) return {'x-agent-token': agentToken};
  if (CFG.token) return {'x-auth-token': CFG.token};
  return {};
}

async function ensureLogin() {
  if (agentToken || CFG.token || !CFG.email || !CFG.password) return;
  const r = await fetch(`${CFG.server}/api/agent/login`, {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({email: CFG.email, password: CFG.password}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok || !data.token) throw new Error(`登录失败: ${data.error || r.status}`);
  agentToken = data.token;
  fs.mkdirSync(CFG.workspace, {recursive: true});
  fs.writeFileSync(TOKEN_FILE, JSON.stringify({token: agentToken, email: CFG.email}));
  log(`已登录 ${CFG.email}，设备令牌存 ${TOKEN_FILE}（90 天有效）`);
}

// ---------- 渲染环境 ----------
function findBrowser() {
  const cands = process.platform === 'win32' ? [
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  ] : process.platform === 'darwin' ? [
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ] : [
    '/usr/bin/microsoft-edge', '/usr/bin/google-chrome', '/usr/bin/chromium',
  ];
  for (const c of cands) if (fs.existsSync(c)) return c;
  const shell = path.join(CFG.renderer, 'node_modules', '.remotion',
    'chrome-headless-shell', process.platform === 'darwin' ? 'mac-arm64' : 'win64',
    process.platform === 'darwin' ? 'chrome-headless-shell-mac-arm64' : 'chrome-headless-shell-win64',
    process.platform === 'darwin' ? 'chrome-headless-shell' : 'chrome-headless-shell.exe');
  return fs.existsSync(shell) ? shell : null;   // 都没有就让 Remotion 用自己会下载的内核
}

function checkRenderer() {
  if (!fs.existsSync(REMOTION_CLI)) {
    console.error(`渲染工程不完整：找不到 ${REMOTION_CLI}`);
    console.error('用 --renderer 指到装好依赖（npm i）的 renderer 目录');
    process.exit(1);
  }
  fs.mkdirSync(path.join(PUBLIC, 'media'), {recursive: true});
}

// ---------- 云端通信 ----------
async function pollOnce() {
  const u = `${CFG.server}/api/agent/poll?wait=1&device=${encodeURIComponent(CFG.device)}`;
  const r = await fetch(u, {headers: authHeaders()});
  if (r.status === 401) throw new Error('AUTH');
  if (!r.ok) throw new Error(`poll HTTP ${r.status}`);
  return r.json();
}

async function downloadFile(job, f) {
  if (!/^(media|brand)\//.test(f.path)) throw new Error(`拒绝的文件路径 ${f.path}`);
  const dst = path.join(PUBLIC, ...f.path.split('/'));
  const url = `${CFG.server}/api/agent/job/${job}/file?path=${encodeURIComponent(f.path)}`;
  const r = await fetch(url, {headers: authHeaders()});
  if (!r.ok || !r.body) throw new Error(`下载 ${f.path} 失败 HTTP ${r.status}`);
  fs.mkdirSync(path.dirname(dst), {recursive: true});
  await pipeline(r.body, fs.createWriteStream(dst));
  return dst;
}

async function report(job, pct, detail, failed = false) {
  try {
    const r = await fetch(
      `${CFG.server}/api/agent/job/${job}/progress?device=${encodeURIComponent(CFG.device)}`,
      {method: 'POST', headers: {...authHeaders(), 'content-type': 'application/json'},
       body: JSON.stringify({pct, detail, status: failed ? 'error' : 'ok'})});
    const data = await r.json().catch(() => ({}));
    return !!data.cancel;
  } catch (_) {
    return false;   // 一次上报失败不要紧，下一次再试
  }
}

async function uploadVisual(job, file) {
  const buf = fs.readFileSync(file);
  const r = await fetch(
    `${CFG.server}/api/agent/job/${job}/visual?device=${encodeURIComponent(CFG.device)}`,
    {method: 'POST', headers: {...authHeaders(), 'content-type': 'application/octet-stream',
     'content-length': buf.length}, body: buf});
  if (!r.ok) throw new Error(`交片失败 HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
}

// ---------- 渲染 ----------
function killTree(child) {
  if (process.platform === 'win32') {
    try { spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], {stdio: 'ignore'}); } catch (_) {}
  } else {
    try { child.kill('SIGKILL'); } catch (_) {}
  }
}

function renderLocally(job, propsObj) {
  return new Promise((resolve, reject) => {
    const propsRel = `props_agent_${job}.json`;
    const outRel = `visual_agent_${job}.mp4`;
    fs.writeFileSync(path.join(CFG.renderer, propsRel), JSON.stringify(propsObj));
    const browser = findBrowser();
    const conc = Math.min(8, Math.max(2, (os.cpus().length || 4) - 2));
    const args = [REMOTION_CLI, 'render', 'main', outRel,
      `--props=${propsRel}`, '--image-format=jpeg', '--jpeg-quality=95',
      '--crf=23', '--x264-preset=veryfast', `--concurrency=${conc}`, '--muted'];
    if (browser) args.push(`--browser-executable=${browser}`);
    log(`本机渲染启动（并发 ${conc}，内核 ${browser ? path.basename(browser) : 'Remotion 默认'}）`);
    const child = spawn(process.execPath, args, {cwd: CFG.renderer, stdio: ['ignore', 'pipe', 'pipe']});
    let buf = '';
    let lastPct = -1;
    let lastPost = 0;
    let cancelled = false;
    const onLine = async (line) => {
      buf += line;
      let idx;
      while ((idx = buf.indexOf('\n')) >= 0) {
        const text = buf.slice(0, idx);
        buf = buf.slice(idx + 1);
        const m = text.match(/Rendered\s+([\d,]+)\s*\/\s*([\d,]+)/);
        if (m) {
          const done = Number(m[1].replace(/,/g, ''));
          const total = Number(m[2].replace(/,/g, ''));
          if (total > 0) {
            const pct = Math.min(99, Math.round((done / total) * 100));
            const now = Date.now();
            if (pct !== lastPct && now - lastPost > 2000) {
              lastPct = pct; lastPost = now;
              if (await report(job, pct, `本机渲染中 ${done}/${total} 帧`)) cancelled = true;
            }
          }
        }
      }
    };
    child.stdout.on('data', (d) => onLine(d.toString()));
    child.stderr.on('data', (d) => onLine(d.toString()));
    const cancelPoll = setInterval(async () => {
      if (await report(job, Math.max(lastPct, 0), '本机渲染中')) cancelled = true;
    }, 15000);
    child.on('exit', async (code) => {
      clearInterval(cancelPoll);
      const out = path.join(CFG.renderer, outRel);
      if (cancelled) {
        try { fs.unlinkSync(out); fs.unlinkSync(path.join(CFG.renderer, propsRel)); } catch (_) {}
        return reject(new Error('CANCELLED'));
      }
      if (code !== 0 || !fs.existsSync(out)) {
        const tail = buf.trim().split('\n').slice(-5).join(' | ').slice(0, 500);
        await report(job, 0, `Remotion 退出码 ${code}: ${tail}`, true);
        return reject(new Error(`渲染失败（退出码 ${code}）`));
      }
      resolve({out, propsFile: path.join(CFG.renderer, propsRel)});
    });
  });
}

function cleanup(job, files, extra) {
  for (const f of files) {
    try { fs.unlinkSync(path.join(PUBLIC, ...f.path.split('/'))); } catch (_) {}
  }
  for (const f of extra) {
    try { fs.unlinkSync(f); } catch (_) {}
  }
}

// ---------- 主循环 ----------
async function handleJob(job, props, files) {
  log(`领到任务 ${job}（素材 ${files.length} 个），开始下载渲染包`);
  const downloaded = [];
  let total = 0;
  for (const f of files) {
    await downloadFile(job, f);
    total += f.size || 0;
    downloaded.push(f);
  }
  log(`渲染包就绪：${files.length} 个文件，共 ${(total / 1048576).toFixed(1)} MB`);
  await report(job, 0, '渲染包已就位，启动本机渲染');
  // 偶发环境抖动（端口被占/代理拦了本地回环）会这么挂：自动重试一次
  let result;
  for (let attempt = 1; ; attempt++) {
    try {
      result = await renderLocally(job, props);
      break;
    } catch (err) {
      if (err.message === 'CANCELLED' || attempt >= 2) throw err;
      log(`第 ${attempt} 次渲染没起来（${err.message}），重试一次`);
      await report(job, 0, '本机渲染异常，自动重试');
      await sleep(3000);
    }
  }
  const {out, propsFile} = result;
  log('本机渲染完成，交回云端合成音轨…');
  await report(job, 99, '渲染完成，上传画面轨');
  await uploadVisual(job, out);
  log(`任务 ${job} 已交片 ✓`);
  cleanup(job, downloaded, [out, propsFile]);
}

async function main() {
  checkRenderer();
  log(`GetCut 渲染台启动 → ${CFG.server}（设备：${CFG.device}）`);
  log('保持这个窗口开着就行；关掉 = 你的电脑不再帮忙渲染（任务会等它回来）');
  let backoff = 1000;
  for (;;) {
    try {
      await ensureLogin();
      const data = await pollOnce();
      backoff = 1000;
      if (data.job) {
        await handleJob(data.job, data.props, data.files || []);
      }
    } catch (err) {
      if (err.message === 'AUTH') {
        agentToken = null;
        try { fs.unlinkSync(TOKEN_FILE); } catch (_) {}
        log('设备令牌过期，需要重新登录');
      } else if (err.message !== 'CANCELLED') {
        log(`等待重试：${err.message}`);
        await sleep(backoff);
        backoff = Math.min(backoff * 2, 30000);
      }
    }
  }
}

main().catch((e) => {
  console.error('渲染台起不来了：', e);
  process.exit(1);
});
