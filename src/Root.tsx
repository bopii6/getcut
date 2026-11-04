import React from 'react';
import { Composition } from 'remotion';
import { Video, type VideoProps } from './Video';

const demo: VideoProps = {
  theme: 'magazine',
  title: '示例',
  fps: 30,
  beats: [
    { text: '这是一条占位文案', card: 'hook', title: '占位标题', audio: '', duration: 3 },
  ],
};

const size = (props: VideoProps) => ({
  durationInFrames: Math.max(90, Math.round(props.beats.reduce((n, b) => n + (b.duration || 2), 0) * 30)),
  fps: 30,
  width: 1080,
  height: 1920,
});

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="Magazine" component={Video} defaultProps={{ ...demo, theme: 'magazine' }}
      calculateMetadata={({ props }) => size(props as VideoProps)}
    />
    <Composition
      id="Poster" component={Video} defaultProps={{ ...demo, theme: 'poster' }}
      calculateMetadata={({ props }) => size(props as VideoProps)}
    />
    <Composition
      id="Dashboard" component={Video} defaultProps={{ ...demo, theme: 'dashboard' }}
      calculateMetadata={({ props }) => size(props as VideoProps)}
    />
  </>
);
