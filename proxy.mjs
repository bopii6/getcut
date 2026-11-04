// 本机代理：浏览器不直接拿 key。
//   POST /api/plan  {text}          → DeepSeek 拆稿（返回 beats）
//   POST /api/tts   {text, voice}   → 配音，返回 audio/mpeg
// 部署时这一层换成 Cloudflare Worker，接口不变。
import http from 'node:http';
import crypto from 'node:crypto';
import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { planScript } from './scripts/plan.mjs';
import { applyEnv, envOf } from './lib/env.mjs';

applyEnv(['DEEPSEEK_API_KEY', 'PEXELS_API_KEY']);

const PORT = Number(process.env.GETCUT_PROXY_PORT || 8790);
const brollCache = new Map();

function cors(res) {
  res.setHeader('access-control-allow-origin', '*');
  res.setHeader('access-control-allow-headers', 'content-type');
  res.setHeader('access-control-allow-methods', 'POST, OPTIONS');
}

function json(res, code, body) {
  cors(res);
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

async function readBody(req) {
  let body = '';
  for await (const chunk of req) body += chunk;
  return JSON.parse(body || '{}');
}

function edgeTts(text, outFile, voice, rate) {
  return new Promise((resolve, reject) => {
    // Windows 上是 python，Linux 服务器通常只有 python3
    const py = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    execFile(py, ['-m', 'edge_tts', '--text', text, '--voice', voice, '--rate', rate,
      '--write-media', outFile, '--no-progress'], { timeout: 60000 }, (err, _out, stderr) => {
      if (err) reject(new Error(String(stderr || err.message).slice(-300)));
      else resolve();
    });
  });
}

// ── 并发闸门：每句一个 python 进程（约 70MB），不限并发，10 个客户 × 20 句就把 2C4G 撑爆
const TTS_CONCURRENCY = Number(process.env.TTS_CONCURRENCY || 4);
let running = 0;
const waiters = [];

function acquire() {
  if (running < TTS_CONCURRENCY) { running++; return Promise.resolve(); }
  return new Promise((resolve) => waiters.push(resolve));
}

function release() {
  const next = waiters.shift();
  if (next) next();
  else running--;
}

// ── 句级缓存：改一句只重配那一句，同行业套话也常命中
const TTS_CACHE_MAX = 400;
const ttsCache = new Map();

function cacheKey(text, voice, rate) {
  return crypto.createHash('sha1').update(`${voice}|${rate}|${text}`).digest('hex');
}

function cacheGet(k) {
  const hit = ttsCache.get(k);
  if (!hit) return null;
  ttsCache.delete(k);
  ttsCache.set(k, hit);            // LRU：命中挪到队尾
  return hit;
}

function cacheSet(k, buf) {
  ttsCache.set(k, buf);
  if (ttsCache.size > TTS_CACHE_MAX) ttsCache.delete(ttsCache.keys().next().value);
}

/** 单句合成（带闸门 + 缓存），返回 mp3 Buffer。 */
async function synth(text, voice, rate) {
  const key = cacheKey(text, voice, rate);
  const hit = cacheGet(key);
  if (hit) return hit;

  await acquire();
  const dir = await mkdtemp(path.join(os.tmpdir(), 'gc-tts-'));
  const file = path.join(dir, 'a.mp3');
  try {
    await edgeTts(text, file, voice, rate);
    const buf = await readFile(file);
    cacheSet(key, buf);
    return buf;
  } finally {
    release();
    await rm(dir, { recursive: true, force: true }).catch(() => {});
  }
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') { cors(res); res.writeHead(204); res.end(); return; }
  try {
    if (req.method === 'GET' && req.url === '/api/health') {
      return json(res, 200, {
        ok: Boolean(envOf('DEEPSEEK_API_KEY')),
        plan: Boolean(envOf('DEEPSEEK_API_KEY')),
        tts: true,
        ttsConcurrency: TTS_CONCURRENCY,
        ttsCached: ttsCache.size,
        runtime: process.version,
      });
    }
    if (req.method === 'POST' && req.url === '/api/plan') {
      const { text } = await readBody(req);
      const src = String(text || '').trim();
      if (src.length < 20) return json(res, 400, { error: '文案太短了，至少 20 个字' });
      const plan = await planScript(src, { apiKey: envOf('DEEPSEEK_API_KEY') });
      return json(res, 200, plan);
    }
    if (req.method === 'GET' && req.url.startsWith('/api/broll')) {
      // 实拍空镜：按关键词去 Pexels 找竖屏视频，直接把字节流回浏览器（避免跨域污染 canvas）
      const q = new URL(req.url, 'http://localhost').searchParams.get('q') || '';
      const key = envOf('PEXELS_API_KEY');
      if (!key) return json(res, 501, { error: '服务端没配 PEXELS_API_KEY' });
      if (!q.trim()) return json(res, 400, { error: '缺少关键词' });
      const sr = await fetch(
        `https://api.pexels.com/videos/search?query=${encodeURIComponent(q)}&orientation=portrait&per_page=8`,
        { headers: { Authorization: key }, signal: AbortSignal.timeout(15000) },
      );
      if (!sr.ok) return json(res, 502, { error: `Pexels ${sr.status}` });
      const data = await sr.json();
      const videos = Array.isArray(data.videos) ? data.videos : [];
      // 挑竖屏、尽量轻的（540 宽够当背景），别动辄下 20MB
      const pick = (v) => (v.video_files || [])
        .filter((f) => f.height > f.width && f.link)
        .sort((a, b) => Math.abs(540 - a.width) - Math.abs(540 - b.width))[0];
      let file = null;
      for (const v of videos) { file = pick(v); if (file) break; }
      if (!file) return json(res, 404, { error: '没找到合适的竖屏素材' });
      const cacheKey = q.toLowerCase();
      if (brollCache.has(cacheKey)) {
        const hit = brollCache.get(cacheKey);
        cors(res);
        res.writeHead(200, { 'content-type': 'video/mp4', 'content-length': String(hit.length), 'cache-control': 'public, max-age=86400' });
        res.end(hit);
        return;
      }
      const vr = await fetch(file.link, { signal: AbortSignal.timeout(30000) });
      if (!vr.ok) return json(res, 502, { error: `下载素材失败 ${vr.status}` });
      const buf = Buffer.from(await vr.arrayBuffer());
      if (brollCache.size > 24) brollCache.clear();
      brollCache.set(cacheKey, buf);
      cors(res);
      res.writeHead(200, { 'content-type': 'video/mp4', 'content-length': String(buf.length), 'cache-control': 'public, max-age=86400' });
      res.end(buf);
      return;
    }
    if (req.method === 'POST' && req.url === '/api/tts') {
      const { text, voice, rate } = await readBody(req);
      const src = String(text || '').trim();
      if (!src) return json(res, 400, { error: '没有文本' });
      const buf = await synth(src, voice || 'zh-CN-YunxiNeural', rate || '+16%');
      cors(res);
      res.writeHead(200, { 'content-type': 'audio/mpeg', 'content-length': String(buf.length) });
      res.end(buf);
      return;
    }
    if (req.method === 'POST' && req.url === '/api/tts/batch') {
      // 一次 5 句：少 4 次往返，失败也只重来这一批
      const { texts, voice, rate } = await readBody(req);
      const list = Array.isArray(texts) ? texts.map((t) => String(t || '').trim()).filter(Boolean) : [];
      if (!list.length) return json(res, 400, { error: '没有文本' });
      if (list.length > 8) return json(res, 400, { error: '一批最多 8 句' });
      const items = [];
      for (let i = 0; i < list.length; i++) {
        try {
          const buf = await synth(list[i], voice || 'zh-CN-YunxiNeural', rate || '+16%');
          items.push({ i, b64: buf.toString('base64') });
        } catch (e) {
          items.push({ i, error: e instanceof Error ? e.message.slice(0, 120) : 'fail' });
        }
      }
      return json(res, 200, { items });
    }
    json(res, 404, { error: 'not found' });
  } catch (e) {
    json(res, 500, { error: e instanceof Error ? e.message : String(e) });
  }
});

server.listen(PORT, '127.0.0.1', () => console.log(`代理已起：http://127.0.0.1:${PORT}`));



