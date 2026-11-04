// 卡密 + 额度端到端（带 cookie jar）
const B = process.env.BASE || 'https://getcut.cn';
const jar = new Map();

function cookieHeader() {
  return [...jar.entries()].map(([k, v]) => `${k}=${v}`).join('; ');
}

async function call(path, opts = {}) {
  const res = await fetch(B + path, {
    ...opts,
    headers: { ...(opts.headers || {}), ...(jar.size ? { cookie: cookieHeader() } : {}) },
  });
  for (const sc of res.headers.getSetCookie?.() ?? (res.headers.get('set-cookie') ? [res.headers.get('set-cookie')] : [])) {
    const [pair] = sc.split(';');
    const i = pair.indexOf('=');
    jar.set(pair.slice(0, i), pair.slice(i + 1));
  }
  return res;
}

const email = `buy${Date.now()}@test.local`;
let r = await call('/api/auth/register', {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ email, password: '123456' }),
});
console.log('register', r.status);

let me = await (await call('/api/me')).json();
console.log('me:', me.loggedIn, me.email, 'pro=', me.pro, 'remaining=', me.remaining);

const code = process.env.CARD;
r = await call('/api/redeem', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ code }) });
console.log('redeem', r.status, (await r.text()).slice(0, 120));

me = await (await call('/api/me')).json();
console.log('after redeem: pro=', me.pro, 'remaining=', me.remaining);

for (let i = 0; i < 4; i++) {
  const g = await call('/api/gen', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ title: 't' + i, theme: 'poster', duration: 10 }) });
  console.log('gen' + i, g.status);
}

r = await call('/api/redeem', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ code }) });
console.log('same card again:', r.status, (await r.text()).slice(0, 80));

r = await call('/api/redeem', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ code: 'GC-AAAA-AAAA-AAAA-AAAA' }) });
console.log('bad code:', r.status, (await r.text()).slice(0, 80));
