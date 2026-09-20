import {useCurrentFrame} from 'remotion';
import type {CSSProperties} from 'react';
import {T} from './skin';

/** 入场动效用的帧号：把模板的入场快慢折算成时间轴压缩。
 * 各卡片里的入场帧号是按 9 帧写死的；模板把 motionFrames 调小（节奏更快）时，
 * 这里整体加速，不用逐个改组件里的字面量。ANIM_BASE=9 时与历史行为完全一致。
 */
export const ANIM_BASE = 9;
export const animFactor = () => ANIM_BASE / Math.max(2, T.motionFrames || ANIM_BASE);
export const useAnimFrame = () => useCurrentFrame() * animFactor();

/** 重黑体字面（随皮肤取字体） */
export const heavy: CSSProperties = {
  get fontFamily() {
    return T.font;
  },
  get fontWeight() {
    return 900;
  },
};

/** 竖向色标（kicker 前的小方块） */
export const Tick: CSSProperties = {
  get display() {
    return 'inline-block';
  },
  get width() {
    return 8;
  },
  get height() {
    return 30;
  },
  get background() {
    return T.accent;
  },
  get marginRight() {
    return 14;
  },
};

// ---------------- 分轨导出（exportMode） ----------------
// full：正常成片；card：只出卡片/包装层（素材不出）；base：只出底板层（镜头内容不出）
// 状态放这里：编舞引擎（choreo）的媒体元素也要遵守；NiwoVideo 转发导出维持旧引用。
export type ExportMode = 'full' | 'card' | 'base';
let EXPORT_MODE: ExportMode = 'full';
export const setExportMode = (m: ExportMode) => {
  EXPORT_MODE = m;
};
/** 素材/字幕是否隐藏（分轨导出时） */
export const hideMedia = () => EXPORT_MODE !== 'full';
export const isCard = () => EXPORT_MODE === 'card';
export const isBase = () => EXPORT_MODE === 'base';
