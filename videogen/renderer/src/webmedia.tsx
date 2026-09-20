import React from 'react';
import {OffthreadVideo} from 'remotion';
import {Video as MediaVideo} from '@remotion/media';

// 视频素材元件的两副面孔：
// - 云端/渲染台（Remotion CLI 录制）：OffthreadVideo，与历史行为一致；
// - 浏览器成片台（@remotion/web-renderer）：不认 OffthreadVideo/Html5Video，
//   必须用 @remotion/media 的 <Video>（WebCodecs 解码，音频默认不接管）。
let webMediaMode = false;

export const setWebMediaMode = (v: boolean) => {
  webMediaMode = v;
};

export const ShotVideo: React.FC<{
  src: string;
  style?: React.CSSProperties;
  muted?: boolean;
}> = ({src, style, muted = true}) =>
  webMediaMode
    ? <MediaVideo src={src} muted style={style} />
    : <OffthreadVideo src={src} muted={muted || undefined} style={style} />;
