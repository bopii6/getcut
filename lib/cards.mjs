// 卡密：GC-XXXX-XXXX-XXXX（16 位 Crockford Base32，最后一位是校验位）
// 生成脚本和 proxy.mjs 共用这一份，避免两边算法漂移。
import { randomBytes } from 'node:crypto';

const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'; // 去掉 I L O U

export function normalize(code) {
  let s = String(code || '').toUpperCase().replace(/[^0-9A-Z]/g, '');
  if (s.length === 18 && s.startsWith('GC')) s = s.slice(2);   // 带前缀的 GC-XXXX-... 形式
  return s;
}

function value(ch) {
  return ALPHABET.indexOf(ch);
}

/** 15 位随机体 → 第 16 位校验位 */
export function checksum(body) {
  let sum = 0;
  for (let i = 0; i < body.length; i++) sum += value(body[i]) * (i + 1);
  return ALPHABET[sum % 32];
}

export function makeCode() {
  const bytes = randomBytes(15);
  let body = '';
  for (const b of bytes) body += ALPHABET[b % 32];
  return body + checksum(body);
}

/** 返回 { ok, reason } —— 校验位先算，不查库，挡爆破 */
export function validate(code) {
  const c = normalize(code);
  if (c.length !== 16) return { ok: false, reason: '卡密应该是 16 位' };
  for (const ch of c) if (value(ch) < 0) return { ok: false, reason: '卡密里有不认识的字符' };
  if (checksum(c.slice(0, 15)) !== c[15]) return { ok: false, reason: '卡密有错字，检查一下' };
  return { ok: true, reason: '' };
}

export function format(code) {
  const c = normalize(code);
  return `GC-${c.slice(0, 4)}-${c.slice(4, 8)}-${c.slice(8, 12)}-${c.slice(12, 16)}`;
}


