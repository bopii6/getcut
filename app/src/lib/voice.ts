// 声音克隆的接口位：前端只认这 4 个函数，服务端换供应商（百炼 CosyVoice / 火山 / MiniMax）
// 只改服务端实现，UI 与调用方不用动。服务端契约见 docs/声音克隆接入.md。
//
//   GET    /api/voice/clones      → { items: [{ id, name, preview? }] }
//   POST   /api/voice/clone       → multipart/form-data：sample(文件) + name → { id }
//   DELETE /api/voice/clones/:id  → 204（样本与音色一起删）
//   POST   /api/tts               → { text, voice } → 音频字节（默认 audio/mpeg）
//
// 克隆音色的 id 由我们自己的服务端签发（cl_xxx）；上游的 voice_id / target_model
// 只存在服务端，不下发浏览器，换供应商时前端零改动。
import { api } from './api';

export type VoiceOption = {
  id: string;
  name: string;
  kind: 'preset' | 'clone';
  preview?: string;
};

/** 内置预设：id 直接用 edge-tts 的发音人名，/api/tts 原样透传。 */
export const PRESET_VOICES: readonly VoiceOption[] = [
  { id: 'zh-CN-YunxiNeural', name: '云希 · 男声口播', kind: 'preset' },
  { id: 'zh-CN-XiaoxiaoNeural', name: '晓晓 · 女声亲和', kind: 'preset' },
  { id: 'zh-CN-YunyangNeural', name: '云扬 · 男声播报', kind: 'preset' },
  { id: 'zh-CN-XiaoyiNeural', name: '晓伊 · 女声清亮', kind: 'preset' },
  { id: 'zh-CN-YunjianNeural', name: '云健 · 男声解说', kind: 'preset' },
];

/** 克隆失败、服务没就绪时的兜底音色，和 audio.ts 的默认值保持一致。 */
export const DEFAULT_VOICE_ID = 'zh-CN-YunxiNeural';

/** 服务端路径；要改前缀只动这一处。 */
export const VOICE_ROUTES = {
  clones: '/api/voice/clones',
  clone: '/api/voice/clone',
  synth: '/api/tts',
} as const;

/** 样本上限 10 MB，对齐百炼声音复刻的音频要求。 */
const MAX_SAMPLE_BYTES = 10 * 1024 * 1024;
const MAX_NAME_CHARS = 20;

/** 带状态码的可读错误：UI 可以按 status / code 决定是提示重试还是降级到预设音色。 */
export class VoiceError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, init: { status?: number; code?: string; cause?: unknown } = {}) {
    super(message, { cause: init.cause });
    this.name = 'VoiceError';
    this.status = init.status ?? 0;
    this.code = init.code ?? '';
  }
}

const STATUS_HINT: Readonly<Record<number, string>> = {
  400: '参数不对',
  401: '服务端密钥无效',
  403: '没有权限，检查 key 是否开通了声音复刻',
  404: '接口不存在，服务端还没实现',
  413: '样本文件太大',
  415: '样本格式不支持',
  422: '样本不合格，建议重录',
  429: '请求太频繁，稍后再试',
  500: '服务端出错',
  501: '声音克隆服务还没接入',
  502: '上游声音服务暂时不可用',
  503: '声音服务暂时不可用',
  504: '上游声音服务超时',
};

function hintOf(status: number): string {
  return STATUS_HINT[status] ?? (status >= 500 ? '声音服务出错' : '请求失败');
}

function field(data: unknown, key: string): string | undefined {
  if (typeof data !== 'object' || data === null) return undefined;
  const value = (data as Record<string, unknown>)[key];
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

/** 服务端把原因放在 { error }，上游有时是 { message }，都不是就按纯文本截断。 */
type Detail = { message: string; code: string };

async function readDetail(res: Response): Promise<Detail> {
  let raw = '';
  try {
    raw = (await res.text()).trim();
  } catch {
    return { message: '', code: '' };
  }
  if (!raw) return { message: '', code: '' };
  try {
    const data: unknown = JSON.parse(raw);
    return {
      message: field(data, 'error') ?? field(data, 'message') ?? '',
      code: field(data, 'code') ?? '',
    };
  } catch {
    return { message: raw.slice(0, 160), code: '' };
  }
}

async function failure(res: Response, action: string): Promise<never> {
  const detail = await readDetail(res);
  const code = detail.code || `http_${res.status}`;
  const reason = detail.message || hintOf(res.status);
  throw new VoiceError(`${action}失败（HTTP ${res.status} ${code}）：${reason}`, {
    status: res.status,
    code,
  });
}

/** fetch 的薄封装：断网 / 代理没起时也给一句人话，而不是 "Failed to fetch"。 */
async function send(url: string, init: RequestInit, action: string): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      throw new VoiceError(`${action}已取消`, { code: 'aborted', cause });
    }
    throw new VoiceError(`${action}失败：连不上声音服务（本机代理可能没启动）`, {
      code: 'network',
      cause,
    });
  }
}

function toClone(data: unknown): VoiceOption | null {
  if (typeof data !== 'object' || data === null) return null;
  const row = data as Record<string, unknown>;
  const id = field(row, 'id');
  const name = field(row, 'name');
  if (!id || !name) return null;
  const option: VoiceOption = { id, name, kind: 'clone' };
  const preview = field(row, 'preview');
  if (preview) option.preview = preview;
  return option;
}

/** 兼容 [{...}] 和 { items: [...] } 两种返回，脏数据直接跳过。 */
function toCloneList(data: unknown): VoiceOption[] {
  const raw = Array.isArray(data)
    ? data
    : typeof data === 'object' && data !== null
      ? (data as Record<string, unknown>).items
      : null;
  if (!Array.isArray(raw)) return [];
  const out: VoiceOption[] = [];
  for (const row of raw) {
    const option = toClone(row);
    if (option) out.push(option);
  }
  return out;
}

/** 预设在前、克隆在后；拉不到列表也返回预设，列表接口不该让页面白屏。 */
export async function listVoices(): Promise<VoiceOption[]> {
  const out: VoiceOption[] = PRESET_VOICES.map((voice) => ({ ...voice }));
  const seen = new Set(out.map((voice) => voice.id));

  try {
    const res = await send(
      api(VOICE_ROUTES.clones),
      { method: 'GET', headers: { accept: 'application/json' } },
      '读取克隆音色',
    );
    if (!res.ok) throw await failure(res, '读取克隆音色');
    for (const clone of toCloneList(await res.json())) {
      if (seen.has(clone.id)) continue;
      seen.add(clone.id);
      out.push(clone);
    }
  } catch (err) {
    // 服务没就绪属于正常状态：这里只降级，不打断页面。
    console.warn(`[voice] 克隆音色暂不可用，先给预设：${err instanceof Error ? err.message : String(err)}`);
  }

  return out;
}

function cleanName(name: string): string {
  const clean = name.trim().replace(/\s+/g, ' ');
  const length = Array.from(clean).length;
  if (!length) throw new VoiceError('给这个音色起个名字', { code: 'bad_name' });
  if (length > MAX_NAME_CHARS) {
    throw new VoiceError(`音色名称最多 ${MAX_NAME_CHARS} 个字（现在 ${length} 个字）`, {
      code: 'bad_name',
    });
  }
  return clean;
}

/** 只挡一眼假的类型；录屏/录音产物的 MIME 各家浏览器不一致，其余交给服务端判。 */
function looksLikeAudio(file: Blob): boolean {
  const type = file.type.toLowerCase();
  if (!type) return true;
  if (type.startsWith('audio/')) return true;
  if (type === 'application/octet-stream') return true;
  // MediaRecorder 只开音轨时，个别版本会报 video/webm
  return type.startsWith('video/webm');
}

function sampleFileName(file: Blob): string {
  if (file instanceof File && file.name) return file.name;
  const type = file.type.toLowerCase();
  const ext = type.includes('wav')
    ? 'wav'
    : type.includes('m4a') || type.includes('mp4')
      ? 'm4a'
      : type.includes('mpeg')
        ? 'mp3'
        : type.includes('ogg')
          ? 'ogg'
          : 'webm';
  return `sample.${ext}`;
}

/** 上传一段样本做克隆（10~30 秒最佳，上限 10 MB）；返回服务端签发的克隆音色 id。 */
export async function uploadCloneSample(file: Blob, name: string): Promise<{ id: string }> {
  const clean = cleanName(name);
  if (file.size === 0) throw new VoiceError('样本是空的，重新录一段', { code: 'empty_sample' });
  if (file.size > MAX_SAMPLE_BYTES) {
    const mb = (file.size / 1024 / 1024).toFixed(1);
    throw new VoiceError(`样本不能超过 10 MB（现在是 ${mb} MB）`, { code: 'sample_too_large' });
  }
  if (!looksLikeAudio(file)) {
    throw new VoiceError(`样本得是音频（现在是 ${file.type || '未知类型'}）`, {
      code: 'bad_sample_type',
    });
  }

  const form = new FormData();
  form.append('name', clean);
  form.append('sample', file, sampleFileName(file));

  // 不要手写 content-type，浏览器要自己带 multipart 的 boundary。
  const res = await send(api(VOICE_ROUTES.clone), { method: 'POST', body: form }, '克隆音色');
  if (!res.ok) await failure(res, '克隆音色');

  const data: unknown = await res.json().catch(() => null);
  const id = field(data, 'id');
  if (!id) throw new VoiceError('服务端没有返回音色 id', { status: 502, code: 'bad_response' });
  return { id };
}

/** 删除克隆音色（样本、上游音色一起清）；已经删掉的再删一次也算成功。 */
export async function deleteClone(id: string): Promise<void> {
  const clean = id.trim();
  if (!clean) throw new VoiceError('没有指定要删除的音色', { code: 'bad_id' });
  if (PRESET_VOICES.some((voice) => voice.id === clean)) {
    throw new VoiceError('预设音色不能删除', { code: 'preset' });
  }

  const res = await send(
    api(`${VOICE_ROUTES.clones}/${encodeURIComponent(clean)}`),
    { method: 'DELETE' },
    '删除克隆音色',
  );
  if (res.status === 404) return;
  if (!res.ok) await failure(res, '删除克隆音色');
}

/** 合成一段配音；voiceId 传预设 id 或克隆 id 都行，由服务端判断走哪家。 */
export async function synthesize(text: string, voiceId: string): Promise<ArrayBuffer> {
  const src = text.trim();
  if (!src) throw new VoiceError('没有文本，合成不出来', { code: 'empty_text' });
  const voice = voiceId.trim();
  if (!voice) throw new VoiceError('没有指定音色', { code: 'bad_voice' });

  const res = await send(
    api(VOICE_ROUTES.synth),
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: src, voice }),
    },
    '配音',
  );
  if (!res.ok) await failure(res, '配音');

  const buffer = await res.arrayBuffer();
  if (buffer.byteLength === 0) {
    throw new VoiceError('配音返回了空音频', { status: 502, code: 'empty_audio' });
  }
  return buffer;
}
