// 任务队列：小程序那边不可能等一个 HTTP 请求挂 3 分钟，必须"建任务 → 轮询 → 取片"。
//
// 为什么串行：一条 60 秒片在 2 核机器上要 3~5 分钟，几乎吃满一个核。
// 并发 2 条不会更快，只会让两条都变慢，还容易把内存顶爆（每帧 RGBA 8.3MB）。
import crypto from 'node:crypto';
import path from 'node:path';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

import { applyEnv, envOf } from '../lib/env.mjs';
import { planScript } from '../scripts/plan.mjs';
import { renderVideo } from './render.mjs';

applyEnv(['DEEPSEEK_API_KEY']);

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const VIDEO_DIR = process.env.GETCUT_VIDEO_DIR || path.join(ROOT, 'data', 'videos');

/** 一条片子吃满一个核，默认串行；机器够大再用 RENDER_CONCURRENCY 放。 */
const CONCURRENCY = Math.max(1, Number(process.env.RENDER_CONCURRENCY || 1));

/** 文案长度边界，和 README 里写的一致：太短拆不出结构，太长一条片渲到天亮。 */
export const TEXT_MIN = 8;
export const TEXT_MAX = 1200;

/** 内存里只留最近这么多条，超了把最老的丢掉（文件还在盘上，只是查不到状态）。 */
const KEEP = 200;

const jobs = new Map();
const queue = [];
let running = 0;

function nowIso() {
  return new Date().toISOString();
}

function publicView(job) {
  return {
    id: job.id,
    status: job.status,
    stage: job.stage,
    percent: job.percent,
    theme: job.theme,
    title: job.title,
    // 出片后给相对路径，让小程序拼自己的域名，不用把服务端地址写死
    videoPath: job.status === 'done' ? `/api/video/${job.id}` : null,
    seconds: job.seconds ?? null,
    frames: job.frames ?? null,
    elapsedSec: job.elapsedSec ?? null,
    error: job.error ?? null,
    createdAt: job.createdAt,
    startedAt: job.startedAt ?? null,
    finishedAt: job.finishedAt ?? null,
    // 排队时告诉用户前面还有几条，比一直转圈强
    queueAhead: job.status === 'queued' ? queue.filter((j) => j.id !== job.id).length + running : 0,
  };
}

export function getJob(id) {
  const job = jobs.get(id);
  return job ? publicView(job) : null;
}

export function listJobs(limit = 20) {
  return [...jobs.values()]
    .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))
    .slice(0, limit)
    .map(publicView);
}

/** 建任务。有 beats 就直接画（前端已经拆过稿），否则用 text 现拆。 */
export function createJob(input = {}) {
  const text = String(input.text || '').trim();
  const beats = Array.isArray(input.beats) && input.beats.length ? input.beats : null;

  if (!beats && !text) throw new Error('没有文案，也没有分镜');
  if (!beats && text.length < TEXT_MIN) throw new Error(`文案太短了，至少 ${TEXT_MIN} 个字`);
  if (!beats && text.length > TEXT_MAX) throw new Error(`文案太长，最多 ${TEXT_MAX} 个字（约 5 分钟口播）`);

  const id = crypto.randomBytes(4).toString('hex');
  const job = {
    id,
    status: 'queued',
    stage: '排队中',
    percent: 0,
    text,
    beats,
    theme: String(input.theme || 'poster'),
    title: String(input.title || '').slice(0, 40) || '获客片',
    voice: String(input.voice || 'zh-CN-YunxiNeural'),
    layoutMode: ['auto', 'big', 'data', 'content'].includes(input.layoutMode) ? input.layoutMode : 'auto',
    bgm: typeof input.bgm === 'string' ? input.bgm : undefined,
    outFile: path.join(VIDEO_DIR, `${id}.mp4`),
    createdAt: nowIso(),
  };

  jobs.set(id, job);
  queue.push(job);
  trim();
  pump();

  return publicView(job);
}

function trim() {
  if (jobs.size <= KEEP) return;
  const stale = [...jobs.values()]
    .filter((j) => j.status === 'done' || j.status === 'failed')
    .sort((a, b) => (a.createdAt < b.createdAt ? -1 : 1));
  while (jobs.size > KEEP && stale.length) jobs.delete(stale.shift().id);
}

async function pump() {
  if (running >= CONCURRENCY) return;
  const job = queue.shift();
  if (!job) return;

  running += 1;
  job.status = 'running';
  job.startedAt = nowIso();
  job.stage = '开始';
  job.percent = 1;

  try {
    await mkdir(VIDEO_DIR, { recursive: true });

    let beats = job.beats;
    if (!beats) {
      job.stage = '拆稿';
      job.percent = 2;
      // 没配 DEEPSEEK_API_KEY 会自动退回规则拆稿，不会因此失败
      const plan = await planScript(job.text, { apiKey: envOf('DEEPSEEK_API_KEY') });
      beats = plan.beats;
      if (!beats?.length) throw new Error('拆稿没拆出镜头');
    }

    const result = await renderVideo({
      beats,
      theme: job.theme,
      title: job.title,
      voice: job.voice,
      layoutMode: job.layoutMode,
      bgm: job.bgm,
      outFile: job.outFile,
      onProgress: (p) => {
        job.stage = p.stage;
        job.percent = p.percent;
      },
    });

    job.status = 'done';
    job.stage = '完成';
    job.percent = 100;
    job.seconds = result.seconds;
    job.frames = result.frames;
    job.elapsedSec = result.elapsedSec;
    job.finishedAt = nowIso();
    job.outFile = result.outFile;
  } catch (err) {
    job.status = 'failed';
    job.stage = '失败';
    job.error = err instanceof Error ? err.message : String(err);
    job.finishedAt = nowIso();
  } finally {
    running -= 1;
    pump();
  }
}

/** 服务端自己查一条任务对应的文件，路由层不直接碰磁盘布局。 */
export function fileOf(id) {
  const job = jobs.get(id);
  if (!job || job.status !== 'done') return null;
  return job.outFile;
}

export function stats() {
  return { total: jobs.size, queued: queue.length, running, concurrency: CONCURRENCY, videoDir: VIDEO_DIR };
}
