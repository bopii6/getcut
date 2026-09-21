// CDP 诊断 v3:绕缓存刷新,读版本标记 + 状态 + 错误
const list = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const page = list.find((t) => t.type === 'page' && t.url.includes('8633'));
if (!page) {
  console.log('no target');
  process.exit(1);
}
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const errors = [];
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
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.method === 'Runtime.exceptionThrown') {
    errors.push('[exception] ' + (m.params.exceptionDetails.exception?.description
      || m.params.exceptionDetails.text || '').slice(0, 300));
  }
});
ws.addEventListener('open', async () => {
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.reload', {ignoreCache: true});
  await new Promise((r) => setTimeout(r, 8000));
  const res = await send('Runtime.evaluate', {
    expression: `JSON.stringify({v: window.POC_VERSION, text: document.body.innerText.slice(0,120), btn: !!document.querySelector('button')})`,
    returnByValue: true,
  });
  console.log('STATE:', res.result.value);
  console.log('ERRORS(' + errors.length + '):');
  for (const e of errors.slice(0, 4)) console.log(' -', e);
  process.exit(0);
});
setTimeout(() => {
  console.log('timeout; errors:', errors.length);
  process.exit(1);
}, 20000);
