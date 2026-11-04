// 账号 / 作品库接口（同源 /api/*）
import { api } from './api';

export type Me = {
  device: string;
  email: string | null;
  loggedIn: boolean;
  freeLimit: number;
  used: number;
  remaining: number;
};

export type GenItem = {
  id: string;
  title: string;
  theme: string;
  duration: number;
  size: number;
  created: number;
  hasVideo: boolean;
};

async function jfetch(path: string, init?: RequestInit) {
  const res = await fetch(api(path), { credentials: 'same-origin', ...init });
  const text = await res.text();
  let body: unknown = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = { error: text }; }
  if (!res.ok) {
    const err = body as { error?: string } | null;
    const e = new Error(err?.error || `请求失败（${res.status}）`);
    (e as Error & { status?: number }).status = res.status;
    throw e;
  }
  return body as never;
}

export const getMe = () => jfetch('/api/me') as Promise<Me>;

export const register = (email: string, password: string) =>
  jfetch('/api/auth/register', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, password }),
  }) as Promise<{ email: string }>;

export const login = (email: string, password: string) =>
  jfetch('/api/auth/login', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, password }),
  }) as Promise<{ email: string }>;

export const logout = () => jfetch('/api/auth/logout', { method: 'POST' }) as Promise<{ ok: true }>;

export const listHistory = () => jfetch('/api/history') as Promise<{ items: GenItem[] }>;

export const createGen = (meta: { title: string; text: string; theme: string; duration: number }) =>
  jfetch('/api/gen', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(meta),
  }) as Promise<{ id: string; used: number; freeLimit: number; remaining: number }>;

export async function uploadVideo(id: string, blob: Blob) {
  const res = await fetch(api(`/api/gen/${id}/video`), {
    method: 'PUT', credentials: 'same-origin', headers: { 'content-type': 'video/mp4' }, body: blob,
  });
  if (!res.ok) throw new Error(`保存成片失败（${res.status}）`);
  return (await res.json()) as { id: string; size: number };
}

export const deleteGen = (id: string) =>
  jfetch(`/api/gen/${id}`, { method: 'DELETE' }) as Promise<{ ok: true }>;

export const videoUrl = (id: string) => api(`/api/video/${id}`);
