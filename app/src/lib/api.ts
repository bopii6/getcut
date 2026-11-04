// 接口地址：同源 /api/*。
// - 线上：Caddy 把 getcut.cn/api/* 反代到本机 8790
// - 本机开发：vite.config.ts 里把 /api 代理到 127.0.0.1:8790
export const API_BASE = '';

export const api = (path: string) => `${API_BASE}${path}`;
