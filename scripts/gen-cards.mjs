#!/usr/bin/env node
// 生成卡密：node scripts/gen-cards.mjs --count 20 --batch 2026-11
// 追加写入 data/cards.json，打印可直接发客户的码
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { makeCode, format } from '../lib/cards.mjs';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const DATA = join(ROOT, 'data');
const FILE = join(DATA, 'cards.json');

const args = process.argv.slice(2);
const get = (k, d) => {
  const i = args.indexOf(`--${k}`);
  return i >= 0 ? args[i + 1] : d;
};
const count = Number(get('count', 10));
const batch = get('batch', new Date().toISOString().slice(0, 7));

mkdirSync(DATA, { recursive: true });
const cards = existsSync(FILE) ? JSON.parse(readFileSync(FILE, 'utf8')) : [];
const seen = new Set(cards.map((c) => c.code));
const made = [];
while (made.length < count) {
  const code = makeCode();
  if (seen.has(code)) continue;
  seen.add(code);
  made.push({ code, batch, sku: 'getcut-599', used: false, usedBy: null, usedAt: null, createdAt: Date.now() });
}
cards.push(...made);
writeFileSync(FILE, JSON.stringify(cards, null, 1));
console.log(`已生成 ${made.length} 张（批次 ${batch}），文件：${FILE}\n`);
for (const c of made) console.log(format(c.code));
