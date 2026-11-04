// 把 POC 标签页带到前台(解除 rAF 节流)
const list = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const page = list.find((t) => t.type === 'page' && t.url.includes('8633'));
const ws = new WebSocket(page.webSocketDebuggerUrl);
ws.addEventListener('open', () => {
  ws.send(JSON.stringify({id: 1, method: 'Page.bringToFront', params: {}}));
  setTimeout(() => {
    console.log('brought to front');
    process.exit(0);
  }, 800);
});
