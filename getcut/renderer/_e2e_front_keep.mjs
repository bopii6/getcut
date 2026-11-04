// 持续把渲染标签页带到前台(每 20 秒一次),避免被遮挡冻结
const list = await (await fetch('http://127.0.0.1:9223/json/list')).json();
const page = list.find((t) => t.type === 'page' && t.url.includes('/poc/'));
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
  for (let i = 0; i < 40; i++) {
    await send('Page.bringToFront');
    await new Promise((r) => setTimeout(r, 20000));
  }
  process.exit(0);
});
