// 全流程实测：headless Chrome 打开成片台 → 拖 zip → 点开始渲染 → 等出片。
// 用法：node _tool_flow_test.mjs <zip绝对路径>
const ZIP = process.argv[2];
if (!ZIP) {
  console.log('用法: node _tool_flow_test.mjs <素材包.zip>');
  process.exit(1);
}
const list = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const page = list.find((t) => t.type === 'page' && t.url.includes('/poc/'));
if (!page) {
  console.log('NO-TARGET: 先起 chrome --headless=new --remote-debugging-port=9222 http://127.0.0.1:8622/poc/');
  process.exit(1);
}
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, {once: true}));
let id = 0;
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const mid = ++id;
    const onmsg = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id === mid) {
        ws.removeEventListener('message', onmsg);
        if (m.error) reject(new Error(JSON.stringify(m.error)));
        else resolve(m.result);
      }
    };
    ws.addEventListener('message', onmsg);
    ws.send(JSON.stringify({id: mid, method, params}));
  });
const evalJs = async (expr) => {
  const r = await send('Runtime.evaluate', {expression: expr, returnByValue: true, awaitPromise: true});
  return r?.result?.value;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const bodyText = () => evalJs('document.body.innerText');
const waitText = async (re, timeout, every = 4000) => {
  const t0 = Date.now();
  for (;;) {
    const txt = String(await bodyText());
    const m = txt.match(re);
    if (m) return m[0];
    if (/出错/.test(txt)) throw new Error(txt.match(/出错：[^\n]*/)?.[0] || 'page error');
    if (Date.now() - t0 > timeout) throw new Error(`timeout waiting ${re}`);
    await sleep(every);
  }
};

await send('Runtime.enable');
const t0 = Date.now();
const el = await send('DOM.getDocument', {depth: -1});
const input = await send('DOM.querySelector', {nodeId: el.root.nodeId, selector: 'input[type=file]'});
if (!input.nodeId) throw new Error('没找到文件选择框');
await send('DOM.setFileInputFiles', {files: [ZIP], nodeId: input.nodeId});
console.log('已拖入 zip:', ZIP.split(/[\\/]/).pop());
await waitText(/生成视频（约/, 180000);
console.log(`导入+解析 ${((Date.now() - t0) / 1000).toFixed(0)}s，点「生成视频」`);
await evalJs(`[...document.querySelectorAll('button')].find(b=>b.innerText.includes('生成视频（约')).click(); 1`);
const t1 = Date.now();
await waitText(/生成视频中/, 600000);
console.log(`云端备料+领单 ${((Date.now() - t1) / 1000).toFixed(0)}s，浏览器开渲`);
let last = -1;
for (;;) {
  const txt = String(await bodyText());
  if (/下载 MP4/.test(txt)) {
    console.log(`渲染+交回 ${((Date.now() - t1) / 1000).toFixed(0)}s  DONE`);
    process.exit(0);
  }
  const m = txt.match(/出错：[^\n]*/);
  if (m) {
    console.log('FAIL', m[0]);
    process.exit(2);
  }
  const p = txt.match(/(\d+)%/);
  if (p && +p[1] !== last) {
    last = +p[1];
    console.log(`  ${((Date.now() - t1) / 1000).toFixed(0)}s -> ${last}%`);
  }
  if (Date.now() - t1 > 25 * 60000) {
    console.log('TIMEOUT 25min');
    process.exit(4);
  }
  await sleep(5000);
}
