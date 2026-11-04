// 离线出「模板缩略图」的一帧：node _still.mjs <jobs.json>
//
// jobs.json = [{props: "work/…/props.json", frame: 123, out: "server_static/templates/tpl-xxx.png"}]
//
// 为什么要有这个脚本：画面渲染早在 2026-09-20 就从命令行搬进客户的浏览器成片台了
// （cli.py 里没有 visual_fn 会直接报错），于是 tools/make_template_previews.py 里
// 那个 render_still_frame 成了空气——改完模板根本出不了新封面，选择器只能一直挂着旧图。
// 这里只出单帧、不出片，所以不需要那条已退役的整片渲染链路。
//
// bundle 只做一次，七个模板共用，免得每套都重新打一遍包。
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';

const [jobsPath] = process.argv.slice(2);
if (!jobsPath) {
  console.error('usage: node _still.mjs <jobs.json>');
  process.exit(2);
}
const jobs = JSON.parse(await readFile(path.resolve(jobsPath), 'utf8'));
if (!Array.isArray(jobs) || !jobs.length) {
  console.error('jobs.json 要是一个非空数组');
  process.exit(2);
}

const serveUrl = await bundle({
  entryPoint: 'src/still/index.tsx',
  outDir: path.resolve('.still-dist'),
  overwrite: true,
  ignoreRegisterRootWarning: true,
});

let failed = 0;
for (const j of jobs) {
  const inputProps = JSON.parse(await readFile(path.resolve(j.props), 'utf8'));
  const frame = Math.max(0, Math.min(Number(j.frame) || 0, Number(inputProps.durationInFrames) - 1));
  const output = path.resolve(j.out);
  try {
    // 尺寸/时长由 src/still 的 calculateMetadata 从 props 现算，这里取回来
    const composition = await selectComposition({serveUrl, id: 'main', inputProps});
    await renderStill({
      serveUrl,
      composition,
      inputProps,
      frame,
      output,
      imageFormat: 'png',
      // 字体是 staticFile 进来的，等字体落地再截，否则缩略图会量到回退字体的宽度
      delayRenderTimeoutInMilliseconds: 120_000,
      chromiumOptions: {headless: true},
    });
    console.log(`ok ${path.basename(output)} frame=${frame}`);
  } catch (e) {
    failed += 1;
    console.log(`FAIL ${path.basename(output)}: ${String(e.message || e).slice(0, 200)}`);
  }
}
process.exit(failed ? 1 : 0);
