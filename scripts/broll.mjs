// 实拍 b-roll：用 Pexels 免费视频给每句配一个竖屏空镜。
// 关键词由分镜阶段生成（英文），这里只负责搜、挑竖屏、下载、去重。
import { createWriteStream } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { pipeline } from 'node:stream/promises';

const API = 'https://api.pexels.com/videos/search';

export function pexelsKey() {
  const k = process.env.PEXELS_API_KEY;
  if (k) return k;
  return undefined;
}

async function search(query, key) {
  const url = `${API}?query=${encodeURIComponent(query)}&orientation=portrait&per_page=6`;
  const res = await fetch(url, { headers: { Authorization: key }, signal: AbortSignal.timeout(20000) });
  if (!res.ok) throw new Error(`Pexels ${res.status}`);
  const data = await res.json();
  return Array.isArray(data.videos) ? data.videos : [];
}

function pickFile(video) {
  const files = (video.video_files || [])
    .filter((f) => f.width && f.height && f.height > f.width)
    .sort((a, b) => Math.abs(1024 - a.width) - Math.abs(1024 - b.width));
  return files[0] || video.video_files?.[0];
}

/**
 * 给每个镜头抓一段竖屏视频。抓不到就返回 null，渲染层自动退回纯排版。
 * @returns {Promise<Array<{broll?: string}>>}
 */
export async function fetchBroll(beats, outDir, { onProgress, concurrency = 3 } = {}) {
  const key = pexelsKey();
  if (!key) return beats.map(() => ({}));

  await mkdir(outDir, { recursive: true });
  const used = new Set();
  const out = new Array(beats.length).fill(null);
  let cursor = 0;

  async function worker() {
    while (cursor < beats.length) {
      const i = cursor++;
      const beat = beats[i];
      const query = (beat.broll || '').trim();
      if (!query) { out[i] = {}; continue; }
      try {
        const videos = await search(query, key);
        const video = videos.find((v) => !used.has(v.id)) || videos[0];
        const file = video && pickFile(video);
        if (!file) { out[i] = {}; continue; }
        used.add(video.id);
        const name = `broll-${video.id}.mp4`;
        const target = path.join(outDir, name);
        const dl = await fetch(file.link, { signal: AbortSignal.timeout(60000) });
        if (!dl.ok) { out[i] = {}; continue; }
        await pipeline(dl.body, createWriteStream(target));
        out[i] = { broll: path.posix.join('broll', path.basename(outDir), name) };
        onProgress?.({ index: i, query, id: video.id });
      } catch {
        out[i] = {};
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, beats.length) }, worker));
  return out.map((x) => x || {});
}
