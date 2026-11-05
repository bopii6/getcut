// 小程序用的 HTTP 接口层。
//
// 六个接口就够跑完整条产品链路：
//   GET  /health        探活
//   POST /plan          只拆稿，给用户先看分镜（不渲染，秒回）
//   POST /job           建出片任务 → 立刻返回 id，不等渲染
//   GET  /job/:id       轮询进度
//   GET  /jobs          最近任务
//   GET  /video/:id     取 MP4（支持 Range，微信 video 组件要它才能拖进度）
import http from 'node:http';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';

import { applyEnv, envOf } from '../lib/env.mjs';
import { planScript } from '../scripts/plan.mjs';
import { createJob, fileOf, getJob, listJobs, stats } from './jobs.mjs';

applyEnv(['DEEPSEEK_API_KEY']);

const PORT = Number(process.env.GETCUT_API_PORT || 8902);
const HOST = process.env.GETCUT_API_HOST || '127.0.0.1';
// 这台服务器上 Web 端的 proxy.mjs 已经占了 /api，所以新服务默认也认 /v1。
// 挂哪个前缀由反向代理决定，两套都认省得来回改配置。
const PREFIXES = (process.env.GETCUT_API_PREFIX || '/api,/v1')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean)
  .sort((a, b) => b.length - a.length);
const MAX_BODY = 256 * 1024;

/** 把 /v1/job/abc 归一成 /job/abc，路由表只写一套。 */
function stripPrefix(pathname) {
  for (const pre of PREFIXES) {
    if (pathname === pre) return '/';
    if (pathname.startsWith(pre + '/')) return pathname.slice(pre.length);
  }
  return pathname;
}

function cors(res) {
  res.setHeader('access-control-allow-origin', '*');
  res.setHeader('access-control-allow-methods', 'GET,POST,OPTIONS');
  res.setHeader('access-control-allow-headers', 'content-type,authorization');
  res.setHeader('access-control-expose-headers', 'content-length,content-range');
}

function json(res, code, body) {
  cors(res);
  const payload = JSON.stringify(body);
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      // 文案接口不该收大包；真收了要么是被扫，要么客户端有 bug
      if (size > MAX_BODY) {
        reject(new Error('请求体太大'));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(new Error('请求体不是合法 JSON'));
      }
    });
    req.on('error', reject);
  });
}

/** 微信 video 组件会先发 Range 探长度，不支持就得把整片下完才能播。 */
async function sendVideo(req, res, id) {
  const file = fileOf(id);
  if (!file) return json(res, 404, { error: '片子还没好，或者任务不存在' });

  const info = await stat(file).catch(() => null);
  if (!info) return json(res, 404, { error: '片子文件不在了，得重新生成' });

  const total = info.size;
  const range = req.headers.range;
  const common = {
    'content-type': 'video/mp4',
    'accept-ranges': 'bytes',
    'cache-control': 'public, max-age=86400',
  };

  if (!range) {
    cors(res);
    res.writeHead(200, { ...common, 'content-length': total });
    createReadStream(file).pipe(res);
    return;
  }

  const m = /^bytes=(\d*)-(\d*)$/.exec(range.trim());
  if (!m) {
    cors(res);
    res.writeHead(416, { ...common, 'content-range': `bytes */${total}` });
    return res.end();
  }

  const start = m[1] ? Number(m[1]) : 0;
  const end = m[2] ? Math.min(Number(m[2]), total - 1) : total - 1;
  if (Number.isNaN(start) || Number.isNaN(end) || start > end || start >= total) {
    cors(res);
    res.writeHead(416, { ...common, 'content-range': `bytes */${total}` });
    return res.end();
  }

  cors(res);
  res.writeHead(206, {
    ...common,
    'content-range': `bytes ${start}-${end}/${total}`,
    'content-length': end - start + 1,
  });
  createReadStream(file, { start, end }).pipe(res);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
  const p = stripPrefix(url.pathname);

  if (req.method === 'OPTIONS') {
    cors(res);
    res.writeHead(204);
    return res.end();
  }

  try {
    if (p === '/health') {
      return json(res, 200, {
        ok: true,
        plan: Boolean(envOf('DEEPSEEK_API_KEY')),
        ...stats(),
        uptimeSec: Math.round(process.uptime()),
      });
    }

    if (req.method === 'POST' && p === '/plan') {
      const { text, model } = await readBody(req);
      const src = String(text || '').trim();
      if (src.length < 8) throw new Error('文案太短，至少 8 个字');
      const plan = await planScript(src, { apiKey: envOf('DEEPSEEK_API_KEY'), ...(model ? { model } : {}) });
      return json(res, 200, plan);
    }

    if (req.method === 'POST' && p === '/job') {
      const body = await readBody(req);
      return json(res, 200, createJob(body));
    }

    if (req.method === 'GET' && p === '/jobs') {
      return json(res, 200, { items: listJobs(Number(url.searchParams.get('limit') || 20)) });
    }

    const jobMatch = /^\/job\/([a-f0-9]{4,32})$/.exec(p);
    if (req.method === 'GET' && jobMatch) {
      const job = getJob(jobMatch[1]);
      return job ? json(res, 200, job) : json(res, 404, { error: '任务不存在' });
    }

    const videoMatch = /^\/video\/([a-f0-9]{4,32})$/.exec(p);
    if (req.method === 'GET' && videoMatch) {
      return await sendVideo(req, res, videoMatch[1]);
    }

    json(res, 404, { error: `没有这个接口：${req.method} ${p}` });
  } catch (err) {
    json(res, 400, { error: err instanceof Error ? err.message : String(err) });
  }
});

server.listen(PORT, HOST, () => {
  const s = stats();
  console.log(`GetCut API  http://${HOST}:${PORT}`);
  console.log(`  拆稿：${envOf('DEEPSEEK_API_KEY') ? 'DeepSeek' : '规则版（没配 key）'}`);
  console.log(`  渲染并发：${s.concurrency} · 片子目录：${s.videoDir}`);
});
