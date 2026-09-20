// 全片实测：连 headless Chrome(9222) 的成片台页面，等预热→点渲染→盯到交回。
const BASE = 'http://127.0.0.1:9222';
const list = await (await fetch(`${BASE}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.url.includes('/poc/'));
if (!page) {
  console.log('NO-TARGET: 先起 chrome --headless=new --remote-debugging-port=9222 <url>');
  process.exit(1);
}
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, {once: true}));
let id = 0;
const send = (method, params = {}) =>
  new Promise((resolve) => {
    const mid = ++id;
    const onmsg = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id === mid) {
        ws.removeEventListener('message', onmsg);
        resolve(m.result);
      }
    };
    ws.addEventListener('message', onmsg);
    ws.send(JSON.stringify({id: mid, method, params}));
  });
const evalJs = async (expr) => {
  const r = await send('Runtime.evaluate', {expression: expr, returnByValue: true});
  return r?.result?.value;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const t0 = Date.now();
for (;;) {
  const txt = await evalJs('document.body.innerText');
  if (/出错/.test(txt)) {
    console.log('PAGE-ERROR:', (txt.match(/出错：[^\n]*/) || [''])[0]);
    process.exit(2);
  }
  if (/开始渲染/.test(txt)) break;
  if (Date.now() - t0 > 180000) {
    console.log('TIMEOUT waiting ready');
    process.exit(3);
  }
  await sleep(3000);
}
console.log('READY，预热完成，点击渲染', ((Date.now() - t0) / 1000).toFixed(0) + 's');
await evalJs(`[...document.querySelectorAll('button')].find(b=>b.innerText.includes('开始渲染')).click(); 1`);
const t1 = Date.now();
let lastPct = -1;
for (;;) {
  const txt = await evalJs('document.body.innerText');
  if (/下载 MP4/.test(txt)) {
    const secs = ((Date.now() - t1) / 1000).toFixed(0);
    const size = await evalJs(`(async()=>{const b=await(await fetch(document.querySelector('a[download]').href)).arrayBuffer();return (b.byteLength/1048576).toFixed(1)})()`);
    console.log(`DONE 渲染+交回 ${secs}s, blob=${await evalJs('String(0)')}`);
    console.log('BLOB_MB', await evalJs(`new Promise(r=>{const a=document.querySelector('a[download]');fetch(a.href).then(x=>x.blob()).then(b=>r((b.size/1048576).toFixed(1)))})`));
    process.exit(0);
  }
  if (/出错/.test(txt)) {
    console.log('RENDER-ERROR:', (txt.match(/出错：[^\n]*/) || [''])[0]);
    process.exit(2);
  }
  const m = txt.match(/(\d+)%/);
  if (m && +m[1] !== lastPct) {
    lastPct = +m[1];
    console.log(`${((Date.now() - t1) / 1000).toFixed(0)}s -> ${lastPct}%`);
  }
  if (Date.now() - t1 > 30 * 60000) {
    console.log('TIMEOUT render 30min');
    process.exit(4);
  }
  await sleep(5000);
}
