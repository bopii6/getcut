import type { PlanBeat } from './types';
import { api } from './api';
import { H, W } from './draw';

/** 从一段视频里抓一帧当背景（静态空镜 + 慢推，够用且稳定）。 */
async function grabFrame(url: string): Promise<HTMLCanvasElement> {
  const video = document.createElement('video');
  video.src = url;
  video.muted = true;
  video.playsInline = true;
  video.preload = 'auto';

  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('视频加载超时')), 15000);
    video.onloadeddata = () => { clearTimeout(timer); resolve(); };
    video.onerror = () => { clearTimeout(timer); reject(new Error('视频加载失败')); };
  });

  // 有的源不触发 seeked：等到时间就算
  await new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, 2000);
    const done = () => { clearTimeout(timer); resolve(); };
    video.onseeked = done;
    try {
      video.currentTime = Math.min(0.8, Math.max(0.1, (video.duration || 2) * 0.25));
    } catch {
      done();
    }
  });

  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d')!;
  const vw = video.videoWidth || W;
  const vh = video.videoHeight || H;
  const scale = Math.max(W / vw, H / vh);
  const dw = vw * scale;
  const dh = vh * scale;
  ctx.drawImage(video, (W - dw) / 2, (H - dh) / 2, dw, dh);
  return canvas;
}

/**
 * 按句子抓实拍空镜：
 * - 最多抓 5 段（每段几 MB，抓多了太慢），抓不到的句子用别的空镜顶着
 * - 整个阶段最多花 45 秒，超时就退回纯排版
 */
export async function fetchBroll(
  beats: PlanBeat[],
  onProgress?: (done: number, total: number) => void,
): Promise<Map<string, HTMLCanvasElement>> {
  const out = new Map<string, HTMLCanvasElement>();
  const MAX_CLIPS = 5;
  const deadline = Date.now() + 45_000;

  const indexed = beats
    .map((b, i) => ({ b, i }))
    .filter(({ b }) => b.broll && b.card !== 'intro' && b.card !== 'chapter');
  if (!indexed.length) return out;

  const unique = Array.from(new Set(indexed.map(({ b }) => String(b.broll)))).slice(0, MAX_CLIPS);
  const clips: HTMLCanvasElement[] = [];
  let done = 0;

  async function one(q: string): Promise<HTMLCanvasElement | null> {
    try {
      const res = await fetch(api(`/api/broll?q=${encodeURIComponent(q)}`));
      if (!res.ok) return null;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      try {
        return await grabFrame(url);
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch {
      return null;
    }
  }

  let cursor = 0;
  async function worker() {
    while (cursor < unique.length && Date.now() < deadline) {
      const q = unique[cursor++];
      const canvas = await one(q);
      if (canvas) clips.push(canvas);
      onProgress?.(++done, unique.length);
    }
  }
  await Promise.all(Array.from({ length: Math.min(3, unique.length) }, worker));

  if (!clips.length) return out;
  indexed.forEach(({ i }, k) => {
    out.set(String(i), clips[k % clips.length]);
  });
  return out;
}

