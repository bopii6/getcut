// =============================================================================
// 导出到剪映（剪映专业版 / JianyingPro）草稿
// -----------------------------------------------------------------------------
// 把 GetCut 的 beats 变成一份剪映能打开的草稿：视频轨按 beats 顺序切片，字幕轨
// 一句一个 text 素材，画布 1080×1920、30fps。只依赖浏览器自带的 Blob /
// CompressionStream，没有第三方 zip 库。
//
// 一、哪些字段是必须的（按剪映专业版 5.9 的 draft_content.json 核对）
//   - 顶层必须有：canvas_config{width,height,ratio}、fps、duration（微秒）、
//     materials、tracks、version=360000、new_version="110.0.0"、platform。
//     version/new_version/platform 不对，剪映会直接拒绝解析这份草稿。
//   - 每个片段（segment）必须有：id、material_id、target_timerange{start,duration}
//     （单位为微秒）；同一条轨道内片段按时间升序、首尾相接、不能重叠。
//   - 视频/音频片段必须有 source_timerange（截取素材的哪一段）；
//     文本片段必须是 source_timerange=null。
//   - 每个片段都要在 extra_material_refs 里挂一个 speed 素材（materials.speeds），
//     这是剪映自己保存草稿时的固定写法，缺了容易触发解析异常。
//   - 字幕素材放在 materials.texts，type="text"；正文在 content 字段里，而且是
//     「JSON 字符串里的 JSON」（{styles:[...], text:"..."}），不是普通字符串。
//   - 草稿目录里还必须有 draft_meta_info.json：剪映靠它识别草稿名/时长；
//     只给 draft_content.json 时草稿列表里可能看不到。
//
// 二、我们简化掉的东西
//   - 没有卡片视觉：配色、排版、动效是 render.ts 画进视频的，剪映草稿里没有
//     「卡片」这个概念。视频轨只有一个占位素材，按 beat 时间切片引用它。
//   - 没有 BGM、转场、入场/出场动画、关键帧、蒙版、滤镜、花字、封面缩略图。
//   - 字幕样式只保留字号/粗细/斜体/对齐/位置；不含描边、背景、阴影、自定义字体
//     （字体一律用系统默认，避免「字体缺失」）。
//   - 不强制帧对齐：剪映内部用微秒，这里按秒四舍五入到微秒，相邻片段首尾相接。
//   - 没有自动识别字幕、没有变速（speed 固定 1.0）。
//
// 三、用户导入后能看到什么 / 看不到什么
//   能看到：
//     - 草稿列表里出现同名草稿，画布 1080×1920、30fps；
//     - 视频轨按 beats 切成 N 段，时间点和时长都对（素材默认指向
//       materials/final.mp4，文件不存在时显示「素材丢失」的占位片段）；
//     - 字幕轨按 beat 时间出字，字号/对齐按卡片类型做了近似（hook 大字、list 左对齐等）；
//     - beat 带 audio 时多一条配音轨（audio 必须是本机真实路径才会出声）。
//   看不到：
//     - 卡片本身的版式、颜色、动画；BGM；转场；封面；
//     - 成片画面：需要把 render.ts 导出的 MP4 放到草稿的 materials/final.mp4，
//       或导出时通过 options.videoPath 传一个绝对路径（剪映 5.9 一般写绝对路径）。
//
// 四、怎么用
//     const { files, zipBlob } = await exportJianyingDraft({
//       title: '加盟避坑', beats, width: 1080, height: 1920, fps: 30,
//     });
//     // files 的 key 是「草稿目录内的相对路径」，直接写盘；
//     // zipBlob 里已经套好 <草稿名>/ 这一层，解压到剪映草稿目录即可。
//     剪映草稿目录：剪映「全局设置 → 草稿位置」（Windows 常见为
//     %LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft）。
//
// 五、兼容性
//     结构按 5.9 写（version=360000 / new_version=110.0.0），更高版本通常能读；
//     4.x 及更早版本可能不认这个 version。剪映草稿字段随版本演进，这里只承诺
//     「最小可导入 + 时间轴正确」，不承诺还原 GetCut 的视觉。
// =============================================================================

/** 一个 beat 进入剪映时需要的最小信息（和 GetCut 的 PlanBeat 对齐）。 */
export type JianyingBeat = {
  /** 这一句的字幕文本；空白字符串表示只占时间轴、不出字幕 */
  text: string;
  /** 时长，单位是秒（和 render.ts 里的 duration 一致） */
  duration: number;
  /** GetCut 的卡片类型：hook / stat / list / quote / cta ...，只用来微调字幕排版 */
  card: string;
  /** 可选：这一句配音的本地文件路径；给了才会生成音频轨 */
  audio?: string;
};

/**
 * 导出输入。画布/帧率按 GetCut 的成片规格固定成字面量类型：
 * 传错（比如 720/1280/25）在编译期就会被拦下。
 */
export type JianyingInput = {
  title: string;
  beats: JianyingBeat[];
  width: 1080;
  height: 1920;
  fps: 30;
};

/** 导出结果。files 的 key 是草稿目录内的相对路径。 */
export type JianyingExport = {
  files: Record<string, string>;
  /** 浏览器支持 zip 时（默认）附带；options.zip=false 时不产出 */
  zipBlob?: Blob;
};

/** 可选参数，都有默认值，不传也能跑。 */
export type JianyingOptions = {
  /** 草稿名（也是 zip 里的顶层目录名），默认由 title 生成 */
  draftName?: string;
  /**
   * 视频轨素材路径。剪映 5.9 一般写绝对路径（如 C:/Users/me/Videos/final.mp4），
   * 默认 "materials/final.mp4"（相对草稿目录）。
   */
  videoPath?: string;
  /** 是否生成 zipBlob，默认 true */
  zip?: boolean;
  /** zip 条目的时间戳，测试时传固定值可得到确定结果；默认 new Date() */
  now?: Date;
};

// ---------------------------------------------------------------------------
// 草稿 JSON 的类型定义
// 这些接口是「剪映认得的字段」的完整形状；注释里标了哪些是必须的。
// ---------------------------------------------------------------------------

/** 微秒 */
type Micros = number;

/** 剪映的时间区间，单位微秒 */
interface TimerangeJson {
  start: Micros;
  duration: Micros;
}

/** 画面变换：translation 的单位是「半个画布」 */
interface ClipJson {
  alpha: number;
  flip: { horizontal: boolean; vertical: boolean };
  rotation: number;
  scale: { x: number; y: number };
  transform: { x: number; y: number };
}

/** materials.speeds 里的变速素材（每个片段挂一个，speed=1 表示原速） */
interface SpeedJson {
  curve_speed: null;
  id: string;
  mode: number;
  speed: number;
  type: 'speed';
}

/** materials.videos 里的本地视频素材 */
interface VideoMaterialJson {
  audio_fade: null;
  category_id: string;
  category_name: string;
  check_flag: number;
  crop: {
    upper_left_x: number;
    upper_left_y: number;
    upper_right_x: number;
    upper_right_y: number;
    lower_left_x: number;
    lower_left_y: number;
    lower_right_x: number;
    lower_right_y: number;
  };
  crop_ratio: string;
  crop_scale: number;
  duration: Micros;
  height: number;
  id: string;
  local_material_id: string;
  material_id: string;
  material_name: string;
  media_path: string;
  path: string;
  type: 'video';
  width: number;
}

/** materials.audios 里的本地音频素材（剪映把导入的音频标成 extract_music） */
interface AudioMaterialJson {
  app_id: number;
  category_id: string;
  category_name: string;
  check_flag: number;
  copyright_limit_type: string;
  duration: Micros;
  effect_id: string;
  formula_id: string;
  id: string;
  local_material_id: string;
  music_id: string;
  name: string;
  path: string;
  source_platform: number;
  type: 'extract_music';
  wave_points: never[];
}

/**
 * materials.texts 里的文本素材。
 * 注意 content：剪映要求它是「JSON 字符串」，形如
 * '{"styles":[{"fill":...}],"text":"..."}'，这里先构造对象再 stringify。
 */
interface TextMaterialJson {
  id: string;
  content: string;
  typesetting: number;
  alignment: 0 | 1 | 2;
  letter_spacing: number;
  line_spacing: number;
  line_feed: number;
  line_max_width: number;
  force_apply_line_max_width: boolean;
  check_flag: number;
  type: 'text';
  global_alpha: number;
}

type MaterialJson = VideoMaterialJson | AudioMaterialJson | TextMaterialJson | SpeedJson;

/**
 * materials 是个「素材类型 → 素材数组」的字典。
 * 剪映保存草稿时会把所有类型都列出来（大部分是空数组）；我们同样把空列表补齐，
 * 只往 videos / audios / texts / speeds 里填东西，降低版本差异带来的解析风险。
 */
type MaterialsJson = Record<string, MaterialJson[]>;

/** 所有片段共有的字段（剪映每个 segment 都带这一套） */
interface SegmentBaseJson {
  enable_adjust: boolean;
  enable_color_correct_adjust: boolean;
  enable_color_curves: boolean;
  enable_color_match_adjust: boolean;
  enable_color_wheels: boolean;
  enable_lut: boolean;
  enable_smart_color_adjust: boolean;
  last_nonzero_volume: number;
  reverse: boolean;
  track_attribute: number;
  track_render_index: number;
  visible: boolean;
  id: string;
  material_id: string;
  target_timerange: TimerangeJson;
  common_keyframes: never[];
  keyframe_refs: never[];
  render_index: number;
}

/** 带素材的片段（视频/音频/文本都继承它） */
interface MediaSegmentJson extends SegmentBaseJson {
  source_timerange: TimerangeJson | null;
  speed: number;
  volume: number;
  extra_material_refs: string[];
  is_tone_modify: boolean;
}

interface VideoSegmentJson extends MediaSegmentJson {
  source_timerange: TimerangeJson;
  clip: ClipJson;
  uniform_scale: { on: boolean; value: number };
  hdr_settings: { intensity: number; mode: number; nits: number };
}

interface TextSegmentJson extends MediaSegmentJson {
  source_timerange: null;
  clip: ClipJson;
  uniform_scale: { on: boolean; value: number };
}

interface AudioSegmentJson extends MediaSegmentJson {
  source_timerange: TimerangeJson;
  clip: null;
  hdr_settings: null;
}

type SegmentJson = VideoSegmentJson | TextSegmentJson | AudioSegmentJson;

type TrackType = 'video' | 'audio' | 'text';

/** tracks[]：同类片段放在一条轨道里，同轨片段首尾相接 */
interface TrackJson {
  attribute: number;
  flag: number;
  id: string;
  is_default_name: boolean;
  name: string;
  segments: SegmentJson[];
  type: TrackType;
}

/** config 里的编辑器状态；剪映会读 maintrack_adsorb 等少数字段，其余原样带回 */
interface DraftConfigJson {
  adjust_max_index: number;
  attachment_info: never[];
  combination_max_index: number;
  export_range: null;
  extract_audio_last_index: number;
  lyrics_recognition_id: string;
  lyrics_sync: boolean;
  lyrics_taskinfo: never[];
  maintrack_adsorb: boolean;
  material_save_mode: number;
  multi_language_current: string;
  multi_language_list: never[];
  multi_language_main: string;
  multi_language_mode: string;
  original_sound_last_index: number;
  record_audio_last_index: number;
  sticker_max_index: number;
  subtitle_keywords_config: null;
  subtitle_recognition_id: string;
  subtitle_sync: boolean;
  subtitle_taskinfo: never[];
  system_font_list: never[];
  video_mute: boolean;
  zoom_info_params: null;
}

interface KeyframesJson {
  adjusts: never[];
  audios: never[];
  effects: never[];
  filters: never[];
  handwrites: never[];
  stickers: never[];
  texts: never[];
  videos: never[];
}

interface PlatformJson {
  app_id: number;
  app_source: string;
  app_version: string;
  os: string;
}

/** draft_content.json 的整体形状 */
interface DraftContentJson {
  canvas_config: { height: number; ratio: string; width: number };
  color_space: number;
  config: DraftConfigJson;
  cover: string | null;
  create_time: number;
  duration: Micros;
  extra_info: string | null;
  fps: number;
  free_render_index_mode_on: boolean;
  group_container: null;
  id: string;
  keyframe_graph_list: never[];
  keyframes: KeyframesJson;
  last_modified_platform: PlatformJson;
  materials: MaterialsJson;
  mutable_config: null;
  name: string;
  new_version: string;
  platform: PlatformJson;
  relationships: never[];
  render_index_track_mode_on: boolean;
  retouch_cover: null;
  source: string;
  static_cover_image_path: string;
  time_marks: null;
  tracks: TrackJson[];
  update_time: number;
  version: number;
}

/** draft_meta_info.json 里的「素材桶」，保持空数组即可 */
interface DraftMaterialBucketJson {
  type: number;
  value: never[];
}

/** draft_meta_info.json：剪映草稿列表用的元信息 */
interface DraftMetaInfoJson {
  cloud_package_completed_time: string;
  draft_cloud_capcut_purchase_info: string;
  draft_cloud_last_action_download: boolean;
  draft_cloud_materials: never[];
  draft_cloud_purchase_info: string;
  draft_cloud_template_id: string;
  draft_cloud_tutorial_info: string;
  draft_cloud_videocut_purchase_info: string;
  draft_cover: string;
  draft_deeplink_url: string;
  draft_enterprise_info: {
    draft_enterprise_extra: string;
    draft_enterprise_id: string;
    draft_enterprise_name: string;
    enterprise_material: never[];
  };
  draft_fold_path: string;
  draft_id: string;
  draft_is_ai_packaging_used: boolean;
  draft_is_ai_shorts: boolean;
  draft_is_ai_translate: boolean;
  draft_is_article_video_draft: boolean;
  draft_is_from_deeplink: string;
  draft_is_invisible: boolean;
  draft_materials: DraftMaterialBucketJson[];
  draft_materials_copied_info: never[];
  draft_name: string;
  draft_new_version: string;
  draft_removable_storage_device: string;
  draft_root_path: string;
  draft_segment_extra_info: never[];
  draft_type: string;
  tm_draft_cloud_completed: string;
  tm_draft_cloud_modified: number;
  tm_draft_removed: number;
  tm_duration: number;
}

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

const MICROS_PER_SECOND = 1_000_000;

/** 剪映 5.9 的草稿版本号；4.x 不认这个值 */
const DRAFT_VERSION = 360000;
const DRAFT_NEW_VERSION = '110.0.0';
const APP_ID = 3704;
const APP_VERSION = '5.9.0';

/** 视频轨占位素材的默认路径（相对草稿目录） */
const DEFAULT_VIDEO_PATH = 'materials/final.mp4';

/**
 * 剪映草稿里出现过的全部素材列表名。
 * 我们不生产这些素材，但保留空数组可以让不同小版本的解析器都能取到 key。
 */
const MATERIAL_LIST_KEYS = [
  'ai_translates',
  'audio_balances',
  'audio_effects',
  'audio_fades',
  'audio_track_indexes',
  'audios',
  'beats',
  'canvases',
  'chromas',
  'color_curves',
  'digital_humans',
  'drafts',
  'effects',
  'flowers',
  'green_screens',
  'handwrites',
  'hsl',
  'images',
  'log_color_wheels',
  'loudnesses',
  'manual_deformations',
  'masks',
  'material_animations',
  'material_colors',
  'multi_language_refs',
  'placeholders',
  'plugin_effects',
  'primary_color_wheels',
  'realtime_denoises',
  'shapes',
  'smart_crops',
  'smart_relights',
  'sound_channel_mappings',
  'speeds',
  'stickers',
  'tail_leaders',
  'text_templates',
  'texts',
  'time_marks',
  'transitions',
  'video_effects',
  'video_trackings',
  'videos',
  'vocal_beautifys',
  'vocal_separations',
] as const;

// ---------------------------------------------------------------------------
// 小工具：随机 id、时间、文件名
// ---------------------------------------------------------------------------

/** 32 位小写 hex，剪映的素材/片段/轨道 id 就是这个形态 */
function freshHexId(): string {
  return randomHex(16);
}

/** 带连字符的大写 UUID，草稿自身 id 的形态 */
function freshDraftId(): string {
  return [
    randomHex(4),
    randomHex(2),
    randomHex(2),
    randomHex(2),
    randomHex(6),
  ].join('-').toUpperCase();
}

function randomHex(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  const cryptoApi = globalThis.crypto;
  if (cryptoApi && typeof cryptoApi.getRandomValues === 'function') {
    cryptoApi.getRandomValues(bytes);
  } else {
    // 极老的浏览器/测试环境兜底；草稿 id 不需要密码学强度
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  let hex = '';
  for (const byte of bytes) hex += byte.toString(16).padStart(2, '0');
  return hex;
}

/** 秒 → 微秒；非法/负数按 0 处理，调用方再决定要不要抬到一帧 */
function toMicros(seconds: number): Micros {
  if (!Number.isFinite(seconds) || seconds <= 0) return 0;
  return Math.round(seconds * MICROS_PER_SECOND);
}

/**
 * 把任意标题变成安全的文件夹/草稿名：
 * 去掉 Windows 非法字符与结尾的点/空格，按字符数截断。
 */
function safeFileSegment(raw: string, fallback: string, maxLength = 40): string {
  const cleaned = raw
    .replace(/[\\/:*?"<>|]/g, ' ')
    .replace(/[\u0000-\u001f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[. ]+$/g, '');
  const cut = Array.from(cleaned).slice(0, maxLength).join('');
  return cut || fallback;
}

/** 从路径里取文件名（剪映素材的 material_name） */
function baseNameOf(path: string): string {
  const normalized = path.replace(/\\/g, '/');
  const parts = normalized.split('/');
  return parts[parts.length - 1] || 'final.mp4';
}

/** 统一成正斜杠，剪映的 path 都是这种写法 */
function normalizePath(path: string): string {
  return path.replace(/\\/g, '/');
}

// ---------------------------------------------------------------------------
// 字幕排版
// ---------------------------------------------------------------------------

/** 字幕的近似排版：剪映草稿里只有文本样式，没有「卡片」 */
type SubtitleTone = {
  /** 剪映的字号单位（默认 8 左右，和画布高度成比例） */
  size: number;
  align: 0 | 1 | 2;
  bold: boolean;
  italic: boolean;
  /** 水平位移，单位是半个画布宽 */
  x: number;
  /** 垂直位移，单位是半个画布高；负数往下 */
  y: number;
};

const DEFAULT_TONE: SubtitleTone = {
  size: 8.5,
  align: 1,
  bold: true,
  italic: false,
  x: 0,
  y: -0.8,
};

/**
 * 按卡片类型给字幕一点排版倾向：大字报/封面字幕更大，清单左对齐，引用句斜体。
 * 这只是「近似」——剪映里仍然是普通文本，用户可以整体改。
 */
const CARD_TONES: Readonly<Record<string, SubtitleTone>> = {
  hook: { size: 10, align: 1, bold: true, italic: false, x: 0, y: -0.62 },
  cover: { size: 10, align: 1, bold: true, italic: false, x: 0, y: -0.62 },
  intro: { size: 10, align: 1, bold: true, italic: false, x: 0, y: -0.62 },
  cta: { size: 9.5, align: 1, bold: true, italic: false, x: 0, y: -0.74 },
  stat: { size: 10, align: 1, bold: true, italic: false, x: 0, y: -0.8 },
  chapter: { size: 9, align: 1, bold: true, italic: false, x: 0, y: -0.8 },
  list: { size: 8.5, align: 0, bold: false, italic: false, x: -0.28, y: -0.82 },
  quote: { size: 9, align: 1, bold: false, italic: true, x: 0, y: -0.82 },
};

function toneFor(card: string): SubtitleTone {
  const tone: SubtitleTone | undefined = CARD_TONES[card];
  return tone ?? DEFAULT_TONE;
}

// ---------------------------------------------------------------------------
// beats → 时间轴
// ---------------------------------------------------------------------------

/** 一个 beat 在时间轴上的落点 */
interface BeatSlice {
  index: number;
  beat: JianyingBeat;
  start: Micros;
  duration: Micros;
}

/**
 * 把 beats 累加成时间轴。
 * - 每个片段至少一帧，避免 0 时长片段让剪映解析失败；
 * - start 用「已四舍五入的时长」累加，保证相邻片段严格首尾相接、不重叠。
 */
function sliceBeats(beats: readonly JianyingBeat[], fps: number): BeatSlice[] {
  const minDuration = Math.max(1, Math.round(MICROS_PER_SECOND / fps));
  const slices: BeatSlice[] = [];
  let cursor = 0;
  for (let i = 0; i < beats.length; i += 1) {
    const beat = beats[i];
    const duration = Math.max(minDuration, toMicros(beat.duration));
    slices.push({ index: i, beat, start: cursor, duration });
    cursor += duration;
  }
  return slices;
}

function totalMicros(slices: readonly BeatSlice[]): Micros {
  const last = slices.at(-1);
  return last ? last.start + last.duration : 0;
}

// ---------------------------------------------------------------------------
// 素材 / 片段构造
// ---------------------------------------------------------------------------

function buildSpeedMaterial(): SpeedJson {
  // 每个媒体片段都挂一个原速 speed 素材，和剪映自己保存的草稿一致
  return { curve_speed: null, id: freshHexId(), mode: 0, speed: 1, type: 'speed' };
}

function buildVideoMaterial(input: JianyingInput, videoPath: string, duration: Micros): VideoMaterialJson {
  const id = freshHexId();
  return {
    audio_fade: null,
    category_id: '',
    category_name: 'local',
    check_flag: 63487,
    crop: {
      upper_left_x: 0,
      upper_left_y: 0,
      upper_right_x: 1,
      upper_right_y: 0,
      lower_left_x: 0,
      lower_left_y: 1,
      lower_right_x: 1,
      lower_right_y: 1,
    },
    crop_ratio: 'free',
    crop_scale: 1,
    duration,
    height: input.height,
    id,
    local_material_id: '',
    material_id: id,
    material_name: baseNameOf(videoPath),
    media_path: '',
    path: videoPath,
    type: 'video',
    width: input.width,
  };
}

function buildTextMaterial(text: string, tone: SubtitleTone): TextMaterialJson {
  // content 是「JSON 字符串」：剪映读的是里面那层 {styles, text}
  const content = {
    styles: [
      {
        fill: {
          alpha: 1,
          content: {
            render_type: 'solid',
            solid: { alpha: 1, color: [1, 1, 1] },
          },
        },
        // 字符区间，剪映用码点计数
        range: [0, Array.from(text).length],
        size: tone.size,
        bold: tone.bold,
        italic: tone.italic,
        underline: false,
        strokes: [],
      },
    ],
    text,
  };
  return {
    id: freshHexId(),
    content: JSON.stringify(content),
    typesetting: 0,
    alignment: tone.align,
    letter_spacing: 0,
    line_spacing: 0.02,
    line_feed: 1,
    line_max_width: 0.82,
    force_apply_line_max_width: false,
    // 1(基础) | 2 | 4；没有描边/背景/阴影，所以停在 7
    check_flag: 7,
    type: 'text',
    global_alpha: 1,
  };
}

function buildAudioMaterial(audioPath: string, duration: Micros): AudioMaterialJson {
  const id = freshHexId();
  return {
    app_id: 0,
    category_id: '',
    category_name: 'local',
    check_flag: 3,
    copyright_limit_type: 'none',
    duration,
    effect_id: '',
    formula_id: '',
    id,
    local_material_id: id,
    music_id: id,
    name: baseNameOf(audioPath),
    path: normalizePath(audioPath),
    source_platform: 0,
    type: 'extract_music',
    wave_points: [],
  };
}

function buildClipJson(x: number, y: number): ClipJson {
  return {
    alpha: 1,
    flip: { horizontal: false, vertical: false },
    rotation: 0,
    scale: { x: 1, y: 1 },
    transform: { x, y },
  };
}

/** 片段公共字段；id/material_id/target_timerange 是剪映必读的三件套 */
function buildSegmentBase(materialId: string, target: TimerangeJson): SegmentBaseJson {
  return {
    enable_adjust: true,
    enable_color_correct_adjust: false,
    enable_color_curves: true,
    enable_color_match_adjust: false,
    enable_color_wheels: true,
    enable_lut: true,
    enable_smart_color_adjust: false,
    last_nonzero_volume: 1,
    reverse: false,
    track_attribute: 0,
    track_render_index: 0,
    visible: true,
    id: freshHexId(),
    material_id: materialId,
    target_timerange: { start: target.start, duration: target.duration },
    common_keyframes: [],
    keyframe_refs: [],
    render_index: 0,
  };
}

function buildVideoSegment(
  materialId: string,
  source: TimerangeJson,
  target: TimerangeJson,
  speedId: string,
): VideoSegmentJson {
  return {
    ...buildSegmentBase(materialId, target),
    source_timerange: { start: source.start, duration: source.duration },
    speed: 1,
    volume: 1,
    extra_material_refs: [speedId],
    is_tone_modify: false,
    clip: buildClipJson(0, 0),
    uniform_scale: { on: true, value: 1 },
    hdr_settings: { intensity: 1, mode: 1, nits: 1000 },
  };
}

function buildTextSegment(
  materialId: string,
  target: TimerangeJson,
  speedId: string,
  tone: SubtitleTone,
): TextSegmentJson {
  return {
    ...buildSegmentBase(materialId, target),
    // 文本没有源素材，剪映要求显式 null
    source_timerange: null,
    speed: 1,
    volume: 1,
    extra_material_refs: [speedId],
    is_tone_modify: false,
    clip: buildClipJson(tone.x, tone.y),
    uniform_scale: { on: true, value: 1 },
  };
}

function buildAudioSegment(
  materialId: string,
  source: TimerangeJson,
  target: TimerangeJson,
  speedId: string,
): AudioSegmentJson {
  return {
    ...buildSegmentBase(materialId, target),
    source_timerange: { start: source.start, duration: source.duration },
    speed: 1,
    volume: 1,
    extra_material_refs: [speedId],
    is_tone_modify: false,
    clip: null,
    hdr_settings: null,
  };
}

function buildTrack(type: TrackType, name: string, segments: SegmentJson[]): TrackJson {
  return {
    attribute: 0,
    flag: 0,
    id: freshHexId(),
    is_default_name: false,
    name,
    segments,
    type,
  };
}

function emptyMaterials(): MaterialsJson {
  const materials: MaterialsJson = {};
  for (const key of MATERIAL_LIST_KEYS) materials[key] = [];
  return materials;
}

// ---------------------------------------------------------------------------
// draft_content.json
// ---------------------------------------------------------------------------

function buildDraftConfig(): DraftConfigJson {
  return {
    adjust_max_index: 1,
    attachment_info: [],
    combination_max_index: 1,
    export_range: null,
    extract_audio_last_index: 1,
    lyrics_recognition_id: '',
    lyrics_sync: true,
    lyrics_taskinfo: [],
    maintrack_adsorb: true,
    material_save_mode: 0,
    multi_language_current: 'none',
    multi_language_list: [],
    multi_language_main: 'none',
    multi_language_mode: 'none',
    original_sound_last_index: 1,
    record_audio_last_index: 1,
    sticker_max_index: 1,
    subtitle_keywords_config: null,
    subtitle_recognition_id: '',
    subtitle_sync: true,
    subtitle_taskinfo: [],
    system_font_list: [],
    video_mute: false,
    zoom_info_params: null,
  };
}

function buildPlatform(): PlatformJson {
  return {
    app_id: APP_ID,
    app_source: 'lv',
    app_version: APP_VERSION,
    os: 'windows',
  };
}

type BuiltDraft = {
  draftId: string;
  draftName: string;
  content: DraftContentJson;
};

function buildDraft(input: JianyingInput, options: JianyingOptions): BuiltDraft {
  const draftName = safeFileSegment(
    options.draftName && options.draftName.trim() ? options.draftName : input.title,
    'GetCut 草稿',
  );
  const draftId = freshDraftId();
  const videoPath = normalizePath(options.videoPath?.trim() || DEFAULT_VIDEO_PATH);
  const slices = sliceBeats(input.beats, input.fps);
  const duration = totalMicros(slices);

  const speeds: SpeedJson[] = [];

  // --- 视频轨：一个占位素材，按 beat 时间切片引用 ---------------------------
  const videoMaterials: VideoMaterialJson[] =
    slices.length > 0 ? [buildVideoMaterial(input, videoPath, duration)] : [];
  const videoMaterial = videoMaterials.at(0);
  const videoSegments: VideoSegmentJson[] = [];
  if (videoMaterial) {
    for (const slice of slices) {
      const speed = buildSpeedMaterial();
      speeds.push(speed);
      // source 与 target 相同：占位素材（final.mp4）本身就是整条时间轴
      const range = { start: slice.start, duration: slice.duration };
      videoSegments.push(buildVideoSegment(videoMaterial.id, range, range, speed.id));
    }
  }

  // --- 字幕轨：一句一个 text 素材，跳过空文本（片头/章节卡不需要字幕） ------
  const textMaterials: TextMaterialJson[] = [];
  const textSegments: TextSegmentJson[] = [];
  for (const slice of slices) {
    if (slice.beat.text.trim() === '') continue;
    const tone = toneFor(slice.beat.card);
    const material = buildTextMaterial(slice.beat.text, tone);
    const speed = buildSpeedMaterial();
    speeds.push(speed);
    textMaterials.push(material);
    textSegments.push(
      buildTextSegment(
        material.id,
        { start: slice.start, duration: slice.duration },
        speed.id,
        tone,
      ),
    );
  }

  // --- 音频轨（可选）：只有 beat.audio 给了真实路径才建 ---------------------
  const audioMaterials: AudioMaterialJson[] = [];
  const audioSegments: AudioSegmentJson[] = [];
  for (const slice of slices) {
    const audioPath = slice.beat.audio?.trim();
    if (!audioPath) continue;
    const material = buildAudioMaterial(audioPath, slice.duration);
    const speed = buildSpeedMaterial();
    speeds.push(speed);
    audioMaterials.push(material);
    audioSegments.push(
      buildAudioSegment(
        material.id,
        { start: 0, duration: slice.duration },
        { start: slice.start, duration: slice.duration },
        speed.id,
      ),
    );
  }

  // --- 轨道顺序 = 图层顺序：视频在下、字幕在上 ------------------------------
  const tracks: TrackJson[] = [];
  if (videoSegments.length > 0) tracks.push(buildTrack('video', '主视频', videoSegments));
  if (audioSegments.length > 0) tracks.push(buildTrack('audio', '配音', audioSegments));
  if (textSegments.length > 0) tracks.push(buildTrack('text', '字幕', textSegments));
  // render_index 越大越靠上层；剪映保存草稿时就是按轨道顺序写的
  for (let trackIndex = 0; trackIndex < tracks.length; trackIndex += 1) {
    for (const segment of tracks[trackIndex].segments) segment.render_index = trackIndex;
  }

  const materials = emptyMaterials();
  materials.videos = videoMaterials;
  materials.audios = audioMaterials;
  materials.texts = textMaterials;
  materials.speeds = speeds;

  const content: DraftContentJson = {
    canvas_config: { width: input.width, height: input.height, ratio: 'original' },
    color_space: 0,
    config: buildDraftConfig(),
    cover: null,
    // 时间基准：剪映内部一律微秒
    create_time: 0,
    duration,
    extra_info: null,
    fps: input.fps,
    free_render_index_mode_on: false,
    group_container: null,
    id: draftId,
    keyframe_graph_list: [],
    keyframes: {
      adjusts: [],
      audios: [],
      effects: [],
      filters: [],
      handwrites: [],
      stickers: [],
      texts: [],
      videos: [],
    },
    last_modified_platform: buildPlatform(),
    materials,
    mutable_config: null,
    name: '',
    new_version: DRAFT_NEW_VERSION,
    platform: buildPlatform(),
    relationships: [],
    render_index_track_mode_on: false,
    retouch_cover: null,
    source: 'default',
    static_cover_image_path: '',
    time_marks: null,
    tracks,
    update_time: 0,
    version: DRAFT_VERSION,
  };

  return { draftId, draftName, content };
}

// ---------------------------------------------------------------------------
// draft_meta_info.json
// ---------------------------------------------------------------------------

function buildMetaInfo(draftName: string, draftId: string, duration: Micros): DraftMetaInfoJson {
  return {
    cloud_package_completed_time: '',
    draft_cloud_capcut_purchase_info: '',
    draft_cloud_last_action_download: false,
    draft_cloud_materials: [],
    draft_cloud_purchase_info: '',
    draft_cloud_template_id: '',
    draft_cloud_tutorial_info: '',
    draft_cloud_videocut_purchase_info: '',
    draft_cover: '',
    draft_deeplink_url: '',
    draft_enterprise_info: {
      draft_enterprise_extra: '',
      draft_enterprise_id: '',
      draft_enterprise_name: '',
      enterprise_material: [],
    },
    draft_fold_path: '',
    draft_id: draftId,
    draft_is_ai_packaging_used: false,
    draft_is_ai_shorts: false,
    draft_is_ai_translate: false,
    draft_is_article_video_draft: false,
    draft_is_from_deeplink: 'false',
    draft_is_invisible: false,
    draft_materials: [
      { type: 0, value: [] },
      { type: 1, value: [] },
      { type: 2, value: [] },
      { type: 3, value: [] },
      { type: 6, value: [] },
      { type: 7, value: [] },
      { type: 8, value: [] },
    ],
    draft_materials_copied_info: [],
    draft_name: draftName,
    draft_new_version: DRAFT_NEW_VERSION,
    draft_removable_storage_device: '',
    draft_root_path: '',
    draft_segment_extra_info: [],
    draft_type: '',
    tm_draft_cloud_completed: '',
    tm_draft_cloud_modified: 0,
    tm_draft_removed: 0,
    // 草稿列表里显示的时长，单位微秒
    tm_duration: duration,
  };
}

// ---------------------------------------------------------------------------
// 手写 ZIP（ZIP64 不需要：草稿文件远小于 4GB）
// 结构：每个文件 = 本地文件头 + 数据；最后 = 中央目录 + EOCD。
// 文件名的 UTF-8 靠通用标志位 bit 11 (0x0800) 标记，中文草稿名不会乱码。
// 压缩优先用浏览器自带的 CompressionStream('deflate-raw')；
// 环境不支持（或压缩后反而变大）时退回 store（method=0）。
// ---------------------------------------------------------------------------

/** 一个待打包的文件 */
export type ZipEntry = {
  /** zip 内的路径，用正斜杠，目录以 "/" 结尾 */
  name: string;
  // 显式写成 Uint8Array<ArrayBuffer>（而不是默认的 ArrayBufferLike），
  // 否则 TS 5.7+ 会认为它可能是 SharedArrayBuffer，不能直接当 BlobPart 用
  data: Uint8Array<ArrayBuffer>;
};

function encodeUtf8(text: string): Uint8Array<ArrayBuffer> {
  return new TextEncoder().encode(text);
}

/** CRC-32 查表（zip 本地头/中央目录都要写） */
const CRC32_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let value = i;
    for (let bit = 0; bit < 8; bit += 1) {
      value = (value & 1) !== 0 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[i] = value >>> 0;
  }
  return table;
})();

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i += 1) {
    crc = CRC32_TABLE[(crc ^ data[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/** deflate-raw 压缩；不支持或失败时返回 null，调用方退回 store */
async function deflateRaw(data: Uint8Array<ArrayBuffer>): Promise<Uint8Array<ArrayBuffer> | null> {
  if (typeof CompressionStream === 'undefined') return null;
  try {
    const stream = new Blob([data]).stream().pipeThrough(new CompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  } catch {
    return null;
  }
}

/** JS Date → ZIP 的 DOS 时间/日期（1980 年起） */
function toDosDateTime(date: Date): { time: number; date: number } {
  const year = Math.max(1980, date.getFullYear());
  const time =
    (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const day = ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { time, date: day };
}

/**
 * 用本地文件头 + 中央目录手写一个 store/deflate 的 zip。
 * 返回值是 Blob，调用方可以直接下载。
 */
export async function createZipBlob(
  entries: readonly ZipEntry[],
  now: Date = new Date(),
): Promise<Blob> {
  const { time, date } = toDosDateTime(now);
  const parts: BlobPart[] = [];
  const centralParts: Uint8Array<ArrayBuffer>[] = [];
  let offset = 0;

  for (const entry of entries) {
    const nameBytes = encodeUtf8(entry.name);
    const checksum = crc32(entry.data);
    const deflated = await deflateRaw(entry.data);
    // 压不小就用 store，避免为了 deflate 反而变大
    const useDeflate = deflated !== null && deflated.length < entry.data.length;
    const body = useDeflate && deflated !== null ? deflated : entry.data;
    const method = useDeflate ? 8 : 0;

    // 本地文件头：30 字节固定 + 文件名
    const localHeader = new Uint8Array(30 + nameBytes.length);
    const lv = new DataView(localHeader.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(4, 20, true); // 解压所需版本
    lv.setUint16(6, 0x0800, true); // bit 11：文件名为 UTF-8
    lv.setUint16(8, method, true);
    lv.setUint16(10, time, true);
    lv.setUint16(12, date, true);
    lv.setUint32(14, checksum, true);
    lv.setUint32(18, body.length, true);
    lv.setUint32(22, entry.data.length, true);
    lv.setUint16(26, nameBytes.length, true);
    lv.setUint16(28, 0, true); // extra field 长度
    localHeader.set(nameBytes, 30);

    const localOffset = offset;
    parts.push(localHeader, body);
    offset += localHeader.length + body.length;

    // 中央目录项：46 字节固定 + 文件名
    const centralHeader = new Uint8Array(46 + nameBytes.length);
    const cv = new DataView(centralHeader.buffer);
    cv.setUint32(0, 0x02014b50, true);
    cv.setUint16(4, 20, true); // version made by
    cv.setUint16(6, 20, true); // version needed
    cv.setUint16(8, 0x0800, true);
    cv.setUint16(10, method, true);
    cv.setUint16(12, time, true);
    cv.setUint16(14, date, true);
    cv.setUint32(16, checksum, true);
    cv.setUint32(20, body.length, true);
    cv.setUint32(24, entry.data.length, true);
    cv.setUint16(28, nameBytes.length, true);
    cv.setUint16(30, 0, true); // extra
    cv.setUint16(32, 0, true); // comment
    cv.setUint16(34, 0, true); // 起始磁盘号
    cv.setUint16(36, 0, true); // 内部属性
    cv.setUint32(38, 0, true); // 外部属性
    cv.setUint32(42, localOffset, true); // 本地头偏移
    centralHeader.set(nameBytes, 46);
    centralParts.push(centralHeader);
  }

  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);

  // 中央目录结束记录（EOCD）
  const endRecord = new Uint8Array(22);
  const ev = new DataView(endRecord.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(4, 0, true);
  ev.setUint16(6, 0, true);
  ev.setUint16(8, entries.length, true);
  ev.setUint16(10, entries.length, true);
  ev.setUint32(12, centralSize, true);
  ev.setUint32(16, offset, true);
  ev.setUint16(20, 0, true); // 注释长度

  return new Blob([...parts, ...centralParts, endRecord], { type: 'application/zip' });
}

// ---------------------------------------------------------------------------
// 对外入口
// ---------------------------------------------------------------------------

/**
 * 把 beats 导出成剪映草稿。
 *
 * @param input 标题 + beats + 画布/帧率（1080×1920 / 30fps）
 * @param options 草稿名、视频素材路径、是否出 zip 等可选参数
 * @returns files（草稿目录内的相对路径 → 文本内容）和 zipBlob（顶层目录为草稿名）
 *
 * @example
 * const { files, zipBlob } = await exportJianyingDraft({
 *   title: '加盟避坑',
 *   beats: [{ text: '加盟前先算三个数', duration: 2.4, card: 'hook' }],
 *   width: 1080,
 *   height: 1920,
 *   fps: 30,
 * });
 */
export async function exportJianyingDraft(
  input: JianyingInput,
  options: JianyingOptions = {},
): Promise<JianyingExport> {
  const draft = buildDraft(input, options);

  // 两个文件都是 UTF-8 文本；files 的 key 是草稿目录内的相对路径
  const files: Record<string, string> = {
    'draft_content.json': JSON.stringify(draft.content, null, 2),
    'draft_meta_info.json': JSON.stringify(
      buildMetaInfo(draft.draftName, draft.draftId, draft.content.duration),
      null,
      2,
    ),
  };

  if (options.zip === false) return { files };

  // zip 里套一层 <草稿名>/，解压到剪映草稿目录就能直接被识别
  const entries: ZipEntry[] = [];
  for (const [name, text] of Object.entries(files)) {
    entries.push({ name: `${draft.draftName}/${name}`, data: encodeUtf8(text) });
  }
  // 预留 materials/ 目录：把成片放进去（默认路径 materials/final.mp4）就能显示画面
  entries.push({ name: `${draft.draftName}/materials/`, data: new Uint8Array(0) });

  const zipBlob = await createZipBlob(entries, options.now ?? new Date());
  return { files, zipBlob };
}
