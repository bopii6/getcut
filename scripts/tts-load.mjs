// 并发压测：10 个客户端 × 每客户端 10 句，走 /api/tts/batch（5 句一批）
const BASE = process.env.BASE || 'https://getcut.cn';
const CLIENTS = Number(process.env.CLIENTS || 10);
const LINES = Number(process.env.LINES || 10);

const seed = ['开店三个数', '回本周期怎么算', '加盟合同要看哪几条', '律师费怎么收', '货款要不回来怎么办',
  '孩子成绩上不去', '选址决定生死', '现金流比利润重要', '复购率才是护城河', '加盟费只是入场券'];

async function client(idx) {
  const texts = Array.from({ length: LINES }, (_, i) => `${seed[(idx + i) % seed.length]}（第 ${idx + 1} 号客户第 ${i + 1} 句，测试用，请忽略）`);
  const t0 = Date.now();
  let ok = 0; let fail = 0;
  for (let s = 0; s < texts.length; s += 5) {
    const chunk = texts.slice(s, s + 5);
    try {
      const res = await fetch(`${BASE}/api/tts/batch`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ texts: chunk }),
        signal: AbortSignal.timeout(120000),
      });
      if (!res.ok) { fail += chunk.length; continue; }
      const data = await res.json();
      for (const it of data.items || []) (it.b64 ? ok++ : fail++);
    } catch {
      fail += chunk.length;
    }
  }
  return { idx, ok, fail, ms: Date.now() - t0 };
}

const t0 = Date.now();
const results = await Promise.all(Array.from({ length: CLIENTS }, (_, i) => client(i)));
const totalMs = Date.now() - t0;
const ok = results.reduce((n, r) => n + r.ok, 0);
const fail = results.reduce((n, r) => n + r.fail, 0);
const times = results.map((r) => r.ms).sort((a, b) => a - b);
const p95 = times[Math.min(times.length - 1, Math.floor(times.length * 0.95))];
console.log(JSON.stringify({
  clients: CLIENTS, lines: LINES, requests: (CLIENTS * Math.ceil(LINES / 5)),
  ok, fail, totalSec: +(totalMs / 1000).toFixed(1),
  clientMs: { min: times[0], p95, max: times[times.length - 1] },
}, null, 1));
