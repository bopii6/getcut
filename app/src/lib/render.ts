// 一条片子：拆稿 → 配音 → 画帧 → 编视频 → 编音频 → 封 MP4
import { ArrayBufferTarget, Muxer } from 'mp4-muxer';
import type { Beat, PlanBeat, ThemeName } from './types';
import { drawFrame, FPS, H, W } from './draw';
import { buildTimeline, encodeAudio, loadMusic, voiceAll } from './audio';
import { fetchBroll } from './broll';

import { api } from './api';

/** 每套风格配一首 BGM（都在 public/music 下，可随时替换）。 */
const BGM: Record<ThemeName, string> = {
  poster: 'music/breakbeat.mp3',
  magazine: 'music/cinematic.mp3',
  dashboard: 'music/chill.mp3',
  news: 'music/breakbeat.mp3',
  night: 'music/cinematic.mp3',
  newsroom: 'music/news.mp3',
  ledger: 'music/corporate.mp3',
  marker: 'music/funk.mp3',
  swiss: 'music/corporate.mp3',
  terminal: 'music/electronic.mp3',
  broadsheet: 'music/cinematic.mp3',
  cover: 'music/trap.mp3',
  reel: 'music/chill.mp3',
};

export async function planScript(text: string): Promise<PlanBeat[]> {
  const res = await fetch(api('/api/plan'), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => '');
    throw new Error(`拆稿失败（${res.status}）：${msg.slice(0, 160)}`);
  }
  const data = await res.json();
  return data.beats as PlanBeat[];
}

/** 片头 + 章节页插进去，变成真正的时间轴。 */
function withChapterCards(beats: Beat[], title: string): Beat[] {
  const out: Beat[] = [{ card: 'intro', text: '', title, duration: 2 }];
  let lastTopic: string | undefined;
  let chapter = 0;
  for (const b of beats) {
    if (b.topic && b.topic !== lastTopic) {
      chapter += 1;
      out.push({ card: 'chapter', text: '', topic: b.topic, value: String(chapter), duration: 1.4 });
      lastTopic = b.topic;
    }
    out.push(b);
  }
  return out;
}

export type Progress = { stage: string; percent: number };

export async function renderVideo(
  plan: PlanBeat[],
  theme: ThemeName,
  title: string,
  onProgress: (p: Progress) => void,
  useBroll = false,
  useMusic = true,
): Promise<Blob> {
  // 1. 实拍空镜（默认关：抓素材慢且不稳，需要时在界面上打开）
  onProgress({ stage: useBroll ? '找实拍空镜' : '准备', percent: 1 });
  const frames: Map<string, HTMLCanvasElement> = useBroll
    ? await fetchBroll(plan, (d, t) => {
        onProgress({ stage: `空镜 ${d}/${t}`, percent: 1 + Math.round((d / t) * 8) });
      })
    : new Map();

  // 2. 配音
  onProgress({ stage: '配音', percent: 10 });
  const spoken = plan.filter((b) => b.text && !['intro', 'chapter'].includes(b.card));
  const voiced = await voiceAll(spoken.map((b) => b.text), (d, t) => {
    onProgress({ stage: `配音 ${d}/${t}`, percent: 10 + Math.round((d / t) * 22) });
  });
  const voicedBeats: Beat[] = plan.map((b, i) => {
    if (b.card === 'intro' || b.card === 'chapter') return { ...b, duration: b.card === 'intro' ? 2 : 1.4 };
    const v = voiced.find((x) => x.text === b.text);
    return {
      ...b,
      bg: frames.get(String(i)) || null,
      duration: v ? Math.max(1.4, v.duration) : 2,
    };
  });

  const timeline = withChapterCards(voicedBeats, title);

  // 2. 编码器
  onProgress({ stage: '初始化编码器', percent: 32 });
  const candidates = ['avc1.640028', 'avc1.4d0028', 'avc1.42001f'];
  let codec = '';
  for (const c of candidates) {
    const r = await VideoEncoder.isConfigSupported({ codec: c, width: W, height: H, bitrate: 4_000_000, framerate: FPS });
    if (r.supported) { codec = c; break; }
  }
  if (!codec) throw new Error('这个浏览器没有 H.264 编码器，换 Edge/Chrome 最新版试试');

  const muxer = new Muxer({
    target: new ArrayBufferTarget(),
    video: { codec: 'avc', width: W, height: H },
    audio: { codec: 'aac', sampleRate: 48000, numberOfChannels: 2 },
    fastStart: 'in-memory',
  });

  let encoderError: Error | null = null;
  const video = new VideoEncoder({
    output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
    error: (e) => {
      encoderError = new Error(`浏览器编码器出错（${String(e).slice(0, 80)}）：关掉其它 Chrome 标签/窗口再试`);
    },
  });
  video.configure({ codec, width: W, height: H, bitrate: 4_000_000, framerate: FPS });

  // 3. 画帧
  const canvas = new OffscreenCanvas(W, H);
  const ctx = canvas.getContext('2d')!;
  ctx.textBaseline = 'alphabetic';
  let globalFrame = 0;
  for (let bi = 0; bi < timeline.length; bi++) {
    const beat = timeline[bi];
    const frames = Math.max(1, Math.round(beat.duration * FPS));
    for (let f = 0; f < frames; f++) {
      if (encoderError) throw encoderError;
      drawFrame(ctx, beat, f / FPS, theme, bi, timeline.length);
      const frame = new VideoFrame(canvas, {
        timestamp: Math.round((globalFrame * 1_000_000) / FPS),
        duration: Math.round(1_000_000 / FPS),
      });
      video.encode(frame, { keyFrame: globalFrame % (FPS * 2) === 0 });
      frame.close();
      globalFrame++;
      if (video.encodeQueueSize > 6) await new Promise((r) => setTimeout(r, 0));
    }
    onProgress({ stage: `画帧 ${bi + 1}/${timeline.length}`, percent: 34 + Math.round(((bi + 1) / timeline.length) * 50) });
  }
  await video.flush();
  video.close();

  // 4. 音轨（配音 + BGM，人声出现时自动压低音乐）
  onProgress({ stage: '合成音轨', percent: 86 });
  const bgm = useMusic ? await loadMusic(BGM[theme] || BGM.poster) : null;
  const audioBuf = buildTimeline(voiced, { sampleRate: 48000, channels: 2, bgm });
  await encodeAudio(audioBuf, (chunk, meta) => muxer.addAudioChunk(chunk, meta), (p) => {
    onProgress({ stage: '音轨编码', percent: 86 + Math.round(p * 12) });
  });

  muxer.finalize();
  const { buffer } = muxer.target;
  onProgress({ stage: '完成', percent: 100 });
  return new Blob([buffer], { type: 'video/mp4' });
}











