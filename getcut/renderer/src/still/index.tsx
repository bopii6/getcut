/**
 * 模板缩略图专用的最小 Remotion 入口。
 *
 * 浏览器成片台是在页面里现场构造 composition 的（tool/index.tsx 的 compositionOf），
 * 全仓库没有 registerRoot，所以 @remotion/renderer 那种"打包一个 Root 再离线出帧"的
 * 路子没有入口可用。这里补一个：尺寸/帧率必须和 tool/index.tsx 的 COMP_W/COMP_H/FPS
 * 一致，否则缩略图和客户真看到的画面会对不上。
 *
 * 时长从 props.durationInFrames 现算，避免每套模板都要在这里改一个常量。
 */
import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {NiwoVideo, type NiwoProps} from '../NiwoVideo';

const W = 1080;
const H = 1920;
const FPS = 30;

export const StillRoot: React.FC = () => (
  <Composition
    id="main"
    component={NiwoVideo as unknown as React.ComponentType<Record<string, unknown>>}
    width={W}
    height={H}
    fps={FPS}
    durationInFrames={600}
    defaultProps={{}}
    calculateMetadata={({props}) => ({
      durationInFrames: Math.max(1, Number((props as Partial<NiwoProps>).durationInFrames) || 600),
      props: props as Record<string, unknown>,
    })}
  />
);

registerRoot(StillRoot);
