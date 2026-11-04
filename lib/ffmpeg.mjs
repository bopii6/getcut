// 本机渲染用到的两个外部命令：ffmpeg / ffprobe。
// 不写死安装位置：先看 PATH，再找 winget 装的位置（用户 PATH 没刷新也能跑）。
import { spawn } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const WINGET = path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'Microsoft', 'WinGet', 'Packages');

function findOnPath(name) {
  const exts = process.platform === 'win32' ? ['.exe', ''] : [''];
  for (const dir of (process.env.PATH || '').split(path.delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const full = path.join(dir, name + ext);
      if (existsSync(full)) return full;
    }
  }
  return null;
}

function findInWinget(name) {
  if (!existsSync(WINGET)) return null;
  const dirs = readdirSync(WINGET).filter((d) => /ffmpeg/i.test(d));
  for (const d of dirs) {
    const base = path.join(WINGET, d);
    const stack = [base];
    while (stack.length) {
      const cur = stack.pop();
      let entries = [];
      try { entries = readdirSync(cur, { withFileTypes: true }); } catch { continue; }
      for (const e of entries) {
        const full = path.join(cur, e.name);
        if (e.isDirectory()) stack.push(full);
        else if (e.name === `${name}.exe`) return full;
      }
    }
  }
  return null;
}

const cache = new Map();

export function binary(name) {
  if (cache.has(name)) return cache.get(name);
  const found = process.env[`GETCUT_${name.toUpperCase()}_PATH`]
    || findOnPath(name)
    || findInWinget(name)
    || name;
  cache.set(name, found);
  return found;
}

export function run(cmd, args, { cwd = process.cwd(), timeoutMs = 20 * 60 * 1000 } = {}) {
  const exe = binary(cmd);
  return new Promise((resolve, reject) => {
    const child = spawn(exe, args, { cwd, windowsHide: true });
    let out = '';
    let err = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`${cmd} 超时（${Math.round(timeoutMs / 1000)} 秒）：素材坏了或磁盘写满时会这样`));
    }, timeoutMs);
    child.stdout.on('data', (d) => { out += d; });
    child.stderr.on('data', (d) => { err += d; });
    child.on('error', (e) => { clearTimeout(timer); reject(new Error(`找不到 ${cmd}：${e.message}`)); });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0) resolve(out);
      else reject(new Error(`${cmd} 失败（退出码 ${code}）：\n${err.slice(-1500)}`));
    });
  });
}

export async function probeDuration(file) {
  const out = await run('ffprobe', [
    '-v', 'error', '-show_entries', 'format=duration',
    '-of', 'default=nw=1:nk=1', file,
  ]);
  const seconds = Number(String(out).trim());
  if (!Number.isFinite(seconds) || seconds <= 0) throw new Error(`量不出时长：${file}`);
  return seconds;
}
