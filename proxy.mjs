// 本机代理：浏览器不直接拿 key。
//   POST /api/plan  {text}          → DeepSeek 拆稿（返回 beats）
//   POST /api/tts   {text, voice}   → 配音，返回 audio/mpeg
// 部署时这一层换成 Cloudflare Worker，接口不变。
import http from 'node:http';
import crypto from 'node:crypto';
import { execFile } from 'node:child_process';
import { createReadStream, createWriteStream, existsSync, mkdirSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { planScript } from './scripts/plan.mjs';
import { applyEnv, envOf } from './lib/env.mjs';
import { format as fmtCard, normalize as normCard, validate as validCard } from './lib/cards.mjs';

applyEnv(['DEEPSEEK_API_KEY', 'PEXELS_API_KEY']);

const PORT = Number(process.env.GETCUT_PROXY_PORT || 8790);
const brollCache = new Map();

// ── 极简数据层：一个 JSON 索引 + 视频文件，单机低并发足够；以后换 SQLite 不动接口
const ROOT = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.GETCUT_DATA_DIR || path.join(ROOT, 'data');
const VIDEO_DIR = path.join(DATA_DIR, 'videos');
const STORE = path.join(DATA_DIR, 'store.json');
const CARDS = path.join(DATA_DIR, 'cards.json');
const FREE_LIMIT = Number(process.env.GETCUT_FREE_LIMIT || 3);

function loadCards() {
  try { return JSON.parse(readFileSync(CARDS, 'utf8')); } catch { return []; }
}

function saveCards(cards) {
  mkdirSync(DATA_DIR, { recursive: true });
  const tmp = `${CARDS}.tmp`;
  writeFileSync(tmp, JSON.stringify(cards, null, 1));
  renameSync(tmp, CARDS);
}
mkdirSync(VIDEO_DIR, { recursive: true });

function loadStore() {
  try {
    const raw = JSON.parse(readFileSync(STORE, 'utf8'));
    return { devices: raw.devices || {}, gens: raw.gens || [], users: raw.users || [], sessions: raw.sessions || {} };
  } catch {
    return { devices: {}, gens: [], users: [], sessions: {} };
  }
}

function saveStore(s) {
  const tmp = `${STORE}.tmp`;
  writeFileSync(tmp, JSON.stringify(s));
  renameSync(tmp, STORE);           // 原子替换，坏不了
}

function hashPassword(pw, salt) {
  return crypto.scryptSync(String(pw), salt, 32).toString('hex');
}

function sessionIdOf(req) {
  const m = (req.headers.cookie || '').match(/(?:^|;\s*)gc_sid=([A-Za-z0-9_-]+)/);
  return m ? m[1] : null;
}

function sessionEmail(req) {
  const sid = sessionIdOf(req);
  if (!sid) return null;
  const s = loadStore().sessions[sid];
  if (!s || s.exp < Date.now()) return null;
  return s.email;
}

function newSession(store, email) {
  const sid = crypto.randomBytes(24).toString('base64url');
  store.sessions[sid] = { email, created: Date.now(), exp: Date.now() + 30 * 86400 * 1000 };
  return sid;
}

/** 已登录用账号额度，未登录用设备额度；两者互不影响。 */
function ownerOf(req, res) {
  const device = deviceOf(req, res);
  const email = sessionEmail(req);
  return { owner: email ? 'u:' + email : 'd:' + device, email, device };
}

function deviceOf(req, res) {
  const cookie = req.headers.cookie || '';
  const m = cookie.match(/(?:^|;\s*)gc_did=([A-Za-z0-9_-]+)/);
  let id = m ? m[1] : null;
  if (!id) {
    id = 'dev_' + crypto.randomBytes(9).toString('base64url');
    res.setHeader('set-cookie', `gc_did=${id}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax`);
  }
  return id;
}


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
    // ── 账号：邮箱 + 密码（不依赖 SMTP，注册即登录） ────────
    if (req.method === 'POST' && req.url === '/api/auth/register') {
      const body = await readBody(req);
      const email = String(body.email || '').trim().toLowerCase();
      const password = String(body.password || '');
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return json(res, 400, { error: '邮箱格式不对' });
      if (password.length < 6) return json(res, 400, { error: '密码至少 6 位' });
      const store = loadStore();
      if (store.users.some((u) => u.email === email)) return json(res, 409, { error: '这个邮箱已经注册过，直接登录' });
      const salt = crypto.randomBytes(8).toString('hex');
      store.users.push({ email, salt, hash: hashPassword(password, salt), created: Date.now() });
      const sid = newSession(store, email);
      saveStore(store);
      res.setHeader('set-cookie', `gc_sid=${sid}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax`);
      return json(res, 200, { email });
    }
    if (req.method === 'POST' && req.url === '/api/auth/login') {
      const body = await readBody(req);
      const email = String(body.email || '').trim().toLowerCase();
      const password = String(body.password || '');
      const store = loadStore();
      const user = store.users.find((u) => u.email === email);
      if (!user || user.hash !== hashPassword(password, user.salt)) return json(res, 401, { error: '邮箱或密码不对' });
      const sid = newSession(store, email);
      saveStore(store);
      res.setHeader('set-cookie', `gc_sid=${sid}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax`);
      return json(res, 200, { email });
    }
    if (req.method === 'POST' && req.url === '/api/auth/logout') {
      const store = loadStore();
      const sid = sessionIdOf(req);
      if (sid && store.sessions[sid]) { delete store.sessions[sid]; saveStore(store); }
      res.setHeader('set-cookie', 'gc_sid=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax');
      return json(res, 200, { ok: true });
    }
    if (req.method === 'POST' && req.url === '/api/redeem') {
      // 599 买断：卡密核销。先算校验位（不查库），再在单写事务里带条件更新
      const { email } = ownerOf(req, res);
      if (!email) return json(res, 401, { error: '先登录，卡密会绑到你的账号' });
      const body = await readBody(req);
      const v = validCard(body.code);
      if (!v.ok) return json(res, 400, { error: v.reason });
      const code = normCard(body.code);
      const cards = loadCards();
      const card = cards.find((c) => c.code === code);
      if (!card) return json(res, 404, { error: '没有这张卡密' });
      const store = loadStore();
      const user = store.users.find((u) => u.email === email);
      if (!user) return json(res, 401, { error: '账号不存在，重新登录' });

      if (card.used) {
        if (card.usedBy === email) {
          if (!user.pro) { user.pro = true; saveStore(store); }
          return json(res, 200, { ok: true, pro: true, already: true });
        }
        return json(res, 409, { error: '这张卡密已经被用过了' });
      }
      card.used = true;
      card.usedBy = email;
      card.usedAt = Date.now();
      saveCards(cards);
      user.pro = true;
      user.proSince = Date.now();
      saveStore(store);
      return json(res, 200, { ok: true, pro: true, plan: 'getcut-599', card: fmtCard(code) });
    }

    // ── 账号 / 历史 / 额度 ────────────────────────────────
    if (req.method === 'GET' && req.url === '/api/me') {
      const { owner, email, device } = ownerOf(req, res);
      const store = loadStore();
      const user = email ? store.users.find((u) => u.email === email) : null;
      const pro = Boolean(user && user.pro);
      // 登录后把同一台设备的试用记录也算进来，避免换个账号白拿 3 条
      const owners = email ? [`u:${email}`, `d:${device}`] : [`d:${device}`];
      const used = store.gens.filter((g) => owners.includes(g.owner)).length;
      cors(res);
      return json(res, 200, {
        device,
        email: email || null,
        loggedIn: Boolean(email),
        pro,
        freeLimit: FREE_LIMIT,
        used,
        remaining: pro ? -1 : Math.max(0, FREE_LIMIT - used),
      });
    }
    if (req.method === 'POST' && req.url === '/api/gen') {
      const { owner, email, device } = ownerOf(req, res);
      const body = await readBody(req);
      const store = loadStore();
      const user = email ? store.users.find((u) => u.email === email) : null;
      const pro = Boolean(user && user.pro);
      const owners = email ? [`u:${email}`, `d:${device}`] : [`d:${device}`];
      const used = store.gens.filter((g) => owners.includes(g.owner)).length;
      if (!pro && used >= FREE_LIMIT) {
        return json(res, 402, { error: `免费额度已经用完（${FREE_LIMIT} 条）`, limited: true, used, freeLimit: FREE_LIMIT });
      }
      const id = crypto.randomBytes(6).toString('hex');
      const rec = {
        id, owner, device: owner.startsWith('d:') ? owner.slice(2) : null,
        email: email || null,
        title: String(body.title || '未命名').slice(0, 40),
        text: String(body.text || '').slice(0, 4000),
        theme: String(body.theme || ''),
        duration: Number(body.duration) || 0,
        size: 0,
        created: Date.now(),
      };
      store.gens.unshift(rec);
      saveStore(store);
      return json(res, 200, { id, used: used + 1, freeLimit: FREE_LIMIT, pro, remaining: pro ? -1 : Math.max(0, FREE_LIMIT - used - 1) });
    }
    if (req.method === 'PUT' && /^\/api\/gen\/[a-f0-9]+\/video$/.test(req.url)) {
      const { owner } = ownerOf(req, res);
      const id = req.url.split('/')[3];
      const store = loadStore();
      const rec = store.gens.find((g) => g.id === id && g.owner === owner);
      if (!rec) return json(res, 404, { error: '没有这条记录' });
      const tmp = path.join(VIDEO_DIR, `${id}.tmp`);
      const out = path.join(VIDEO_DIR, `${id}.mp4`);
      await new Promise((resolve, reject) => {
        const ws = createWriteStream(tmp);
        req.pipe(ws);
        ws.on('finish', resolve);
        ws.on('error', reject);
      });
      const size = statSync(tmp).size;
      renameSync(tmp, out);
      rec.size = size;
      saveStore(store);
      return json(res, 200, { id, size });
    }
    if (req.method === 'GET' && req.url === '/api/history') {
      const { owner } = ownerOf(req, res);
      const store = loadStore();
      const items = store.gens
        .filter((g) => g.owner === owner)
        .map((g) => ({ id: g.id, title: g.title, theme: g.theme, duration: g.duration, size: g.size, created: g.created, hasVideo: g.size > 0 }));
      return json(res, 200, { items });
    }
    if (req.method === 'GET' && /^\/api\/video\/[a-f0-9]+$/.test(req.url)) {
      const { owner } = ownerOf(req, res);
      const id = req.url.split('/')[3];
      const store = loadStore();
      const rec = store.gens.find((g) => g.id === id && g.owner === owner && g.size > 0);
      const file = path.join(VIDEO_DIR, `${id}.mp4`);
      if (!rec || !existsSync(file)) { res.writeHead(404); return res.end('not found'); }
      cors(res);
      res.writeHead(200, { 'content-type': 'video/mp4', 'content-length': String(statSync(file).size) });
      return createReadStream(file).pipe(res);
    }
    if (req.method === 'DELETE' && /^\/api\/gen\/[a-f0-9]+$/.test(req.url)) {
      const { owner } = ownerOf(req, res);
      const id = req.url.split('/')[3];
      const store = loadStore();
      const idx = store.gens.findIndex((g) => g.id === id && g.owner === owner);
      if (idx < 0) return json(res, 404, { error: '没有这条记录' });
      store.gens.splice(idx, 1);
      saveStore(store);
      const file = path.join(VIDEO_DIR, `${id}.mp4`);
      if (existsSync(file)) unlinkSync(file);
      return json(res, 200, { ok: true });
    }

    json(res, 404, { error: 'not found' });
  } catch (e) {
    json(res, 500, { error: e instanceof Error ? e.message : String(e) });
  }
});

server.listen(PORT, '127.0.0.1', () => console.log(`代理已起：http://127.0.0.1:${PORT}`));





