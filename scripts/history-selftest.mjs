// 账号/历史/额度接口自测：me → gen → 上传视频 → 历史 → 下载 → 删除
const BASE = process.env.BASE || 'https://getcut.cn';
let cookie = '';

async function call(path, opts = {}) {
  const res = await fetch(BASE + path, {
    ...opts,
    headers: { ...(opts.headers || {}), ...(cookie ? { cookie } : {}) },
  });
  const sc = res.headers.get('set-cookie');
  if (sc) cookie = sc.split(';')[0];
  return res;
}

const me1 = await (await call('/api/me')).json();
console.log('me:', me1);

const gen = await call('/api/gen', {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ title: '测试一条', text: '这是一条测试文案', theme: 'poster', duration: 30 }),
});
const rec = await gen.json();
console.log('gen:', gen.status, rec);
if (!rec.id) process.exit(1);

// 传 1KB 假视频
const fake = new Uint8Array(1024).fill(7);
const up = await call(`/api/gen/${rec.id}/video`, { method: 'PUT', headers: { 'content-type': 'video/mp4' }, body: fake });
console.log('upload:', up.status, await up.text());

const hist = await (await call('/api/history')).json();
console.log('history:', JSON.stringify(hist).slice(0, 300));

const vid = await call(`/api/video/${rec.id}`);
console.log('video:', vid.status, (await vid.arrayBuffer()).byteLength, 'bytes');

const me2 = await (await call('/api/me')).json();
console.log('me after:', me2);

const del = await call(`/api/gen/${rec.id}`, { method: 'DELETE' });
console.log('delete:', del.status);
const hist2 = await (await call('/api/history')).json();
console.log('history after delete:', hist2.items.length);
