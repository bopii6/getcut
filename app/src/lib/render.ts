// 一条片子：拆稿 → 配音 → 画帧 → 编视频 → 编音频 → 封 MP4
import { ArrayBufferTarget, Muxer } from 'mp4-muxer';
import type { Beat, LayoutMode, PlanBeat, ThemeName } from './types';
import { drawFrame, FPS, H, W } from './draw';
import { buildTimeline, encodeAudio, loadMusic, pickAudioConfig, voiceAll } from './audio';
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
  voice = 'zh-CN-YunxiNeural',
  bgmFile = '',
  surface?: HTMLCanvasElement,
  layoutMode: LayoutMode = 'auto',
  onDiag?: (d: Record<string, unknown>) => void,
): Promise<Blob> {
  // 字体没加载完就开始画，measureText 会用回退字体量宽度，导致中文溢出版面
  if (typeof document !== 'undefined' && document.fonts?.ready) {
    try { await document.fonts.ready; } catch { /* 忽略 */ }
  }

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
  }, voice);
  const voicedBeats: Beat[] = plan.map((b, i) => {
    if (b.card === 'intro' || b.card === 'chapter') return { ...b, duration: b.card === 'intro' ? 2 : 1.4 };
    const v = voiced.find((x) => x.text === b.text);
    return {
      ...b,
      bg: frames.get(String(i)) || null,
      audio: v?.buffer,
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

  // 音频能力必须在建封装器之前定下来：轨道声明的采样率/声道必须和真实编码一致，
  // 否则部分手机播放器会认为音轨损坏（表现为喇叭按钮是灰的、点了没反应）
  const audioCfg = await pickAudioConfig();
  if (!audioCfg) {
    throw new Error('这台设备不支持网页内音频编码（AAC），出不了带声音的片子。请换 Chrome/Edge 电脑，或换一部手机再试。');
  }

  const muxer = new Muxer({
    target: new ArrayBufferTarget(),
    video: { codec: 'avc', width: W, height: H },
    audio: { codec: 'aac', sampleRate: audioCfg.sampleRate, numberOfChannels: audioCfg.numberOfChannels },
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

  // 3. 画帧：始终画在离屏 canvas 上（快），只把缩小版刷到可见画布做预览
  const canvas = new OffscreenCanvas(W, H);
  const ctx = canvas.getContext('2d') as OffscreenCanvasRenderingContext2D;
  ctx.textBaseline = 'alphabetic';

  const preview = surface ?? null;
  const pctx = preview ? preview.getContext('2d') : null;
  if (preview) {
    preview.width = 270;
    preview.height = 480;
  }

  let globalFrame = 0;
  let lastLayout: LayoutMode = 'content';
  const layoutOf = (b: Beat): LayoutMode => {
    if (layoutMode !== 'auto') return layoutMode;
    const base: LayoutMode =
      b.card === 'stat' && b.value ? 'data'
        : (b.card === 'hook' || b.card === 'quote') ? 'big'
          : 'content';
    // 同一个版式绝不连着出现两屏：上一屏是什么就换另一个
    const prev: LayoutMode = lastLayout;
    if (base === prev) return prev === 'big' ? 'content' : 'big';
    return base;
  };
  for (let bi = 0; bi < timeline.length; bi++) {
    const beat = timeline[bi];
    const frames = Math.max(1, Math.round(beat.duration * FPS));
    for (let f = 0; f < frames; f++) {
      if (encoderError) throw encoderError;
      const layout = layoutOf(beat);
      drawFrame(ctx, beat, f / FPS, theme, bi, timeline.length, layout);
      const frame = new VideoFrame(canvas, {
        timestamp: Math.round((globalFrame * 1_000_000) / FPS),
        duration: Math.round(1_000_000 / FPS),
      });
      video.encode(frame, { keyFrame: globalFrame % (FPS * 2) === 0 });
      frame.close();
      // 预览每 6 帧刷一次，缩到 270×480，开销可以忽略
      if (pctx && globalFrame % 6 === 0) {
        pctx.drawImage(canvas, 0, 0, preview!.width, preview!.height);
      }
      globalFrame++;
      if (video.encodeQueueSize > 6) await new Promise((r) => setTimeout(r, 0));
    }
    lastLayout = layoutOf(beat);
    onProgress({ stage: `画帧 ${bi + 1}/${timeline.length}`, percent: 34 + Math.round(((bi + 1) / timeline.length) * 50) });
  }
  await video.flush();
  video.close();

  // 4. 音轨：按最终时间轴逐段铺，卡片段补静音，保证和画面等长、不跑偏
  onProgress({ stage: '合成音轨', percent: 86 });
  const bgm = useMusic ? await loadMusic(bgmFile || BGM[theme] || BGM.poster) : null;

  const audioBuf = buildTimeline(
    timeline.map((b) => ({ duration: b.duration, buffer: b.audio ?? null })),
    { sampleRate: audioCfg.sampleRate, channels: audioCfg.numberOfChannels, bgm },
  );
  // iOS 的 AAC 编码器常常不给 AudioSpecificConfig；缺了它，Apple 播放器会认为音轨损坏
  // （表现：画面正常、喇叭变灰）。这里按 MPEG-4 标准自己拼一份塞给封装器。
  const asc = (() => {
    const table: Record<number, number> = {
      96000: 0, 88200: 1, 64000: 2, 48000: 3, 44100: 4, 32000: 5,
      24000: 6, 22050: 7, 16000: 8, 12000: 9, 11025: 10, 8000: 11,
    };
    const idx = table[audioCfg.sampleRate] ?? 4;
    const ch = Math.min(7, audioCfg.numberOfChannels);
    return new Uint8Array([(2 << 3) | (idx >> 1), ((idx & 1) << 7) | (ch << 3)]);
  })();

  let audioChunks = 0;
  let sawDesc = false;
  await encodeAudio(audioBuf, (chunk, meta) => {
    audioChunks += 1;
    const desc = meta?.decoderConfig?.description;
    if (desc && (desc.byteLength ?? 0) >= 2) sawDesc = true;
    let m = meta;
    if (meta && (!desc || (desc.byteLength ?? 0) < 2)) {
      m = {
        ...meta,
        decoderConfig: {
          ...(meta.decoderConfig || {}),
          codec: 'mp4a.40.2',
          sampleRate: audioCfg.sampleRate,
          numberOfChannels: audioCfg.numberOfChannels,
          description: asc,
        },
      };
    }
    muxer.addAudioChunk(chunk, m);
  }, (p) => {
    onProgress({ stage: '音轨编码', percent: 86 + Math.round(p * 12) });
  }, audioCfg);
  if (audioChunks === 0) {
    throw new Error('音频编码没有产出任何数据（设备编码器异常），这条片子会是无声的，已中止。请换电脑或换浏览器重试。');
  }

  onDiag?.({
    ok: true,
    audioCodec: audioCfg.codec,
    sampleRate: audioCfg.sampleRate,
    channels: audioCfg.numberOfChannels,
    audioChunks,
    sawDesc,
    audioSec: Number(audioBuf.duration.toFixed(2)),
    videoSec: Number(timeline.reduce((n, b) => n + b.duration, 0).toFixed(2)),
  });

  muxer.finalize();
  const { buffer } = muxer.target;
  onProgress({ stage: '完成', percent: 100 });
  return new Blob([buffer], { type: 'video/mp4' });
}





















