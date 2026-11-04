// CDP:刷新页面→置前→等按钮→点击开跑
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
  await send('Runtime.enable');
  await send('Page.bringToFront');
  await send('Page.reload', {ignoreCache: true});
  await new Promise((r) => setTimeout(r, 4000));
  for (let i = 0; i < 20; i++) {
    const res = await send('Runtime.evaluate', {
      expression: `(function(){
        var b = document.querySelector('button');
        if (b && /开始渲染/.test(b.textContent)) { b.click(); return 'clicked'; }
        return 'wait: ' + (document.body.innerText || '').slice(0, 60);
      })()`,
      returnByValue: true,
    });
    const v = res?.result?.value || '';
    console.log(`[${i}] ${v}`);
    if (v === 'clicked') process.exit(0);
    await new Promise((r) => setTimeout(r, 3000));
  }
  process.exit(1);
});
