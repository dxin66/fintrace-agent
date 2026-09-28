import { z } from 'zod';
let csrf = '';
export async function refreshCsrf(): Promise<void> {
  const response = await fetch('/api/auth/csrf');
  if (!response.ok) throw new Error('无法获取安全令牌');
  csrf = z.object({ token: z.string() }).parse(await response.json()).token;
}
export async function api<T>(
  path: string,
  schema: z.ZodType<T>,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET') {
    if (!csrf) await refreshCsrf();
    headers.set('X-CSRF-TOKEN', csrf);
  }
  const response = await fetch('/api' + path, { ...options, headers });
  const data: unknown = await response.json();
  if (!response.ok) {
    const error = z.object({ message: z.string() }).safeParse(data);
    throw new Error(error.success ? error.data.message : `请求失败 (${response.status})`);
  }
  return schema.parse(data);
}
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请重试';
}
