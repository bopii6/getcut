// CDP:点主页面悬浮按钮 #gc-bx-go
const list = await (await fetch('http://127.0.0.1:9223/json/list')).json();
const page = list.find((t) => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
ws.addEventListener('open', () => {
  ws.send(JSON.stringify({id: 1, method: 'Runtime.evaluate', params: {
    expression: `(function(){var b=document.querySelector('#gc-bx-go');if(b){b.click();return 'clicked';}return 'no-button';})()`,
    returnByValue: true,
  }}));
});
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id === 1) {
    console.log('WIDGET:', m.result?.result?.value);
    process.exit(0);
  }
});
setTimeout(() => {
  console.log('timeout');
  process.exit(1);
}, 12000);
