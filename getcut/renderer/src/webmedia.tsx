import React from 'react';
import {Video} from '@remotion/media';

/**
 * 视频素材元件：@remotion/media 的 <Video>（WebCodecs 解码）。
 * 音频不由它发声——成片台在页面里按 audio 计划统一混音。
 * remotion 的 <OffthreadVideo> 是服务器端 CLI 渲染用的那副面孔，已随之下线。
 */
export const ShotVideo: React.FC<{
  src: string;
  style?: React.CSSProperties;
  muted?: boolean;
}> = ({src, style, muted = true}) => <Video src={src} muted={muted || undefined} style={style} />;
