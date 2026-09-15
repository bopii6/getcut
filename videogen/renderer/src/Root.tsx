import React from 'react';
import {Composition} from 'remotion';
import {NiwoVideo, type NiwoProps} from './NiwoVideo';

const fps = 30;

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="main"
      component={NiwoVideo as React.FC<Record<string, unknown>>}
      durationInFrames={30 * 5}
      fps={fps}
      width={1080}
      height={1920}
      defaultProps={
        {
          durationInFrames: 30 * 5,
          headline: {lines: [{text: '标题', highlight: '高亮'}]},
          sources: [],
          disclaimer: '',
          shots: [],
          clauses: [],
        } as unknown as NiwoProps
      }
      calculateMetadata={({props}) => ({
        durationInFrames: Math.max(props.durationInFrames, 30),
      })}
    />
  );
};
