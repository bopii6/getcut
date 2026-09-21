// CDP:从主页面进同源 iframe,点「开始渲染」(最多等 90 秒)
const list = await (await fetch('http://127.0.0.1:9223/json/list')).json();
const page = list.find((t) => t.type === 'page');
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
  await send('Runtime.enable');
  for (let i = 0; i < 36; i++) {
    const res = await send('Runtime.evaluate', {
      expression: `(function(){
        var f = document.querySelector('#gc-bx-frame');
        if (!f) return 'no-iframe';
        var b = f.contentWindow.document.querySelector('button');
        if (b && /开始渲染/.test(b.textContent)) { b.click(); return 'clicked'; }
        return 'wait: ' + (f.contentWindow.document.body.innerText || '').slice(0, 70);
      })()`,
      returnByValue: true,
    });
    const v = res?.result?.value || '';
    console.log(`[${i}] ${v}`);
    if (v === 'clicked') process.exit(0);
    await new Promise((r) => setTimeout(r, 2500));
  }
  process.exit(1);
});
