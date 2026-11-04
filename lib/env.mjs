// 极小 .env 读取：不引依赖，只看项目根目录这一份。
// 目标：这个项目自己带钥匙，不依赖外面任何目录。
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let cached = null;

export function loadEnv() {
  if (cached) return cached;
  cached = {};
  const file = process.env.GETCUT_ENV || path.join(ROOT, '.env');
  if (!existsSync(file)) return cached;
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const s = line.trim();
    if (!s || s.startsWith('#')) continue;
    const i = s.indexOf('=');
    if (i < 0) continue;
    const key = s.slice(0, i).trim();
    const value = s.slice(i + 1).trim().replace(/^["']|["']$/g, '');
    if (key) cached[key] = value;
  }
  return cached;
}

/** 环境变量优先，其次项目里的 .env。 */
export function envOf(key) {
  return process.env[key] || loadEnv()[key];
}

export function applyEnv(keys) {
  const env = loadEnv();
  for (const k of keys) {
    if (!process.env[k] && env[k]) process.env[k] = env[k];
  }
}
