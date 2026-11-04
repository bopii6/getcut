// 本机代理：浏览器不直接拿 key。
//   POST /api/plan  {text}          → DeepSeek 拆稿（返回 beats）
//   POST /api/tts   {text, voice}   → 配音，返回 audio/mpeg
// 部署时这一层换成 Cloudflare Worker，接口不变。
import http from 'node:http';
import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { planScript } from './scripts/plan.mjs';
import { applyEnv, envOf } from './lib/env.mjs';

applyEnv(['DEEPSEEK_API_KEY', 'PEXELS_API_KEY']);

const PORT = Number(process.env.GETCUT_PROXY_PORT || 8790);

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

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') { cors(res); res.writeHead(204); res.end(); return; }
  try {
    if (req.method === 'GET' && req.url === '/api/health') {
      return json(res, 200, {
        ok: Boolean(envOf('DEEPSEEK_API_KEY')),
        plan: Boolean(envOf('DEEPSEEK_API_KEY')),
        tts: true,
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
    if (req.method === 'POST' && req.url === '/api/tts') {
      const { text, voice, rate } = await readBody(req);
      const src = String(text || '').trim();
      if (!src) return json(res, 400, { error: '没有文本' });
      const dir = await mkdtemp(path.join(os.tmpdir(), 'gc-tts-'));
      const file = path.join(dir, 'a.mp3');
      try {
        await edgeTts(src, file, voice || 'zh-CN-YunxiNeural', rate || '+16%');
        const buf = await readFile(file);
        cors(res);
        res.writeHead(200, { 'content-type': 'audio/mpeg', 'content-length': String(buf.length) });
        res.end(buf);
      } finally {
        await rm(dir, { recursive: true, force: true }).catch(() => {});
      }
      return;
    }
    json(res, 404, { error: 'not found' });
  } catch (e) {
    json(res, 500, { error: e instanceof Error ? e.message : String(e) });
  }
});

server.listen(PORT, '127.0.0.1', () => console.log(`代理已起：http://127.0.0.1:${PORT}`));
