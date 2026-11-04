// 打包浏览器渲染 POC 页面(Remotion bundler 产物即静态网页)
import path from 'node:path';
import {bundle} from '@remotion/bundler';

const out = await bundle({
  entryPoint: 'src/poc/index.tsx',
  outDir: path.resolve('browserpoc-dist'),
  overwrite: true,
  ignoreRegisterRootWarning: true,
});
console.log('bundled ->', out);
