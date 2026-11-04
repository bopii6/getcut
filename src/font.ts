import { loadFont } from '@remotion/fonts';
import { staticFile } from 'remotion';

/**
 * 两套字重：超粗标题 + 细体说明，是"有设计感"和"PPT"最直接的区别。
 * 官方 loadFont 会挡住渲染，直到字体就绪，不会掉回系统字体。
 */
let started = false;

export function ensureChineseFont() {
  if (started) return;
  started = true;
  const jobs = [
    loadFont({ family: 'GC Heavy', url: staticFile('fonts/SourceHanSansCN-Heavy.otf'), weight: '900' }),
    loadFont({ family: 'GC Light', url: staticFile('fonts/NotoSansSC-Light.otf'), weight: '300' }),
  ];
  Promise.all(jobs).catch(() => { started = false; });
}
