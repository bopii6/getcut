// 置前 + 点按钮开录
const list = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const page = list.find((t) => t.type === 'page' && t.url.includes('8633'));
const ws = new WebSocket(page.webSocketDebuggerUrl);
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
ws.addEventListener('open', async () => {
  await send('Page.enable');
  await send('Page.bringToFront');
  await new Promise((r) => setTimeout(r, 1500));
  await send('Runtime.evaluate', {
    expression: `document.querySelector('button').click()`,
  });
  await new Promise((r) => setTimeout(r, 4000));
  const res = await send('Runtime.evaluate', {
    expression: `document.body.innerText.slice(0, 80)`,
    returnByValue: true,
  });
  console.log('AFTER CLICK:', res.result.value);
  process.exit(0);
});
