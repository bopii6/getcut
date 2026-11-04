// 打包「浏览器成片台」工具页（web-renderer 逐帧渲染 + 浏览器内混音，产出带声 mp4）
import path from 'node:path';
import {bundle} from '@remotion/bundler';

const out = await bundle({
  entryPoint: 'src/tool/index.tsx',
  outDir: path.resolve('browsertool-dist'),
  overwrite: true,
  ignoreRegisterRootWarning: true,
});
console.log('bundled ->', out);
