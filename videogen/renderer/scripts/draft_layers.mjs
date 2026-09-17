// 剪映分轨草稿：一次打包，渲染「底板层」+ 逐镜「卡片层」，并采出卡片文字几何。
//
//   node scripts/draft_layers.mjs <props.json> <baseOut.png> <cardOutDir> <frames.json> <textsOut.json>
//
// frames.json: [{"id": "shot_000", "frame": 123}, ...]
// textsOut.json: {"shot_000": [{text,x,y,w,h,size,weight,color,align}, ...], ...}
// 文字几何由页面内的 TextProbe 通过本地 HTTP 回传（no-cors POST），避免依赖浏览器日志通道。
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition, getCompositions} from '@remotion/renderer';

const [, , propsPath, baseOut, cardOutDir, framesPath, textsOut] = process.argv;
if (!propsPath || !baseOut || !cardOutDir || !framesPath || !textsOut) {
  process.stderr.write(
    'usage: node scripts/draft_layers.mjs <props.json> <baseOut> <cardDir> <frames.json> <textsOut>\n',
  );
  process.exit(2);
}

const props = JSON.parse(fs.readFileSync(propsPath, 'utf8'));
const frames = JSON.parse(fs.readFileSync(framesPath, 'utf8'));

// 收集页面回传的文字几何
const collected = {};
const absorb = (payload) => {
  try {
    const tag = String(payload.tag || '');
    if (tag) collected[tag] = payload.items || [];
    return true;
  } catch (err) {
    return false;
  }
};
const server = http.createServer({maxHeaderSize: 1 << 20}, (req, res) => {
  if (req.method === 'GET') {
    // 图片信标：?chunk=<base64(payload)>
    const q = new URL(req.url, 'http://127.0.0.1').searchParams.get('chunk');
    let ok = false;
    if (q) {
      try {
        const json = Buffer.from(decodeURIComponent(q), 'base64').toString('utf8');
        ok = absorb(JSON.parse(json));
      } catch (err) {
        ok = false;
      }
    }
    process.stdout.write(`beacon ${ok ? 'ok' : 'bad'} len=${(q || '').length}\n`);
    res.writeHead(200, {'Content-Type': 'image/gif', 'Access-Control-Allow-Origin': '*'});
    res.end(Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7', 'base64'));
    return;
  }
  let body = '';
  req.on('data', (chunk) => {
    body += chunk;
    if (body.length > 8_000_000) req.destroy();
  });
  req.on('end', () => {
    try {
      absorb(JSON.parse(body));
    } catch (err) {
      process.stdout.write(`probe bad payload: ${String(body).slice(0, 120)}\n`);
    }
    res.writeHead(200, {'Access-Control-Allow-Origin': '*'});
    res.end('ok');
  });
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;
const probeUrl = `http://127.0.0.1:${port}/vgtext`;
process.stdout.write(`probe http on ${port}\n`);

const entryPoint = path.resolve('src/index.ts');
process.stdout.write('bundling...\n');
const serveUrl = await bundle({entryPoint, onProgress: (p) => {
  if (p % 25 === 0) process.stdout.write(`bundle ${p}%\n`);
}});

// 注意：renderStill 必须和 selectComposition 用同一份 props，否则页面拿到的是旧 props
const pickComposition = async (inputProps) => {
  let comp;
  if (typeof selectComposition === 'function') {
    comp = await selectComposition({serveUrl, id: 'main', inputProps});
  } else {
    const comps = await getCompositions(serveUrl, {inputProps});
    comp = comps.find((c) => c.id === 'main');
  }
  if (!comp) throw new Error('composition "main" not found');
  return comp;
};
const baseComposition = await pickComposition(props);
const lastFrame = baseComposition.durationInFrames - 1;

fs.mkdirSync(cardOutDir, {recursive: true});

// 1) 底板层（一张，铺满全片）
const baseProps = {...props, exportMode: 'base'};
await renderStill({
  composition: await pickComposition(baseProps),
  serveUrl,
  output: baseOut,
  frame: Math.max(0, Math.min(lastFrame, Math.round(frames[0]?.frame ?? 0))),
  inputProps: baseProps,
  imageFormat: 'png',
  overwrite: true,
});
process.stdout.write('ok base\n');

// 2) 卡片层（每镜一张）+ 文字几何
for (const item of frames) {
  const frame = Math.max(0, Math.min(lastFrame, Math.round(item.frame)));
  delete collected[item.id];
  const out = path.join(cardOutDir, `${item.id}.png`);
  const cardProps = {...props, exportMode: 'card', probeUrl, probeTag: item.id};
  await renderStill({
    composition: await pickComposition(cardProps),
    serveUrl,
    output: out,
    frame,
    inputProps: cardProps,
    imageFormat: 'png',
    overwrite: true,
  });
  process.stdout.write(`ok ${item.id} f=${frame} texts=${(collected[item.id] || []).length}\n`);
}

fs.writeFileSync(textsOut, JSON.stringify(collected, null, 1), 'utf8');
server.close();
process.stdout.write('done\n');
