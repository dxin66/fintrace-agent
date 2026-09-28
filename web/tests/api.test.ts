import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest';
import { z } from 'zod';
const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => {
  vi.resetModules();
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
});
const response = (data: unknown, status = 200): Response =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
describe('HTTP contracts', () => {
  it('fetches CSRF and attaches it to mutations', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ token: 'csrf' }))
      .mockResolvedValueOnce(response({ ok: true }));
    const { api } = await import('../src/api');
    await expect(
      api('/test', z.object({ ok: z.boolean() }), { method: 'POST', body: '{}' })
    ).resolves.toEqual({ ok: true });
    const headers = fetchMock.mock.calls[1]?.[1]?.headers;
    expect(new Headers(headers).get('X-CSRF-TOKEN')).toBe('csrf');
    expect(new Headers(headers).get('Content-Type')).toBe('application/json');
  });
  it('does not set multipart content type and reuses token', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ token: 'csrf' }))
      .mockResolvedValue(response({ ok: true }));
    const { api, refreshCsrf } = await import('../src/api');
    await refreshCsrf();
    await api('/test', z.object({ ok: z.boolean() }), { method: 'POST', body: new FormData() });
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).has('Content-Type')).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it('validates response schemas and GET requires no csrf', async () => {
    fetchMock.mockResolvedValue(response({ id: 'wrong' }));
    const { api } = await import('../src/api');
    await expect(api('/test', z.object({ id: z.number() }), { method: 'GET' })).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it('surfaces backend errors', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ message: '无权限' }, 403))
      .mockResolvedValueOnce(response({}, 500));
    const { api } = await import('../src/api');
    await expect(api('/test', z.unknown())).rejects.toThrow('无权限');
    await expect(api('/test', z.unknown())).rejects.toThrow('500');
  });
  it('surfaces CSRF and network errors', async () => {
    fetchMock.mockResolvedValue(response({}, 503));
    const { refreshCsrf, errorMessage } = await import('../src/api');
    await expect(refreshCsrf()).rejects.toThrow('安全令牌');
    expect(errorMessage(new Error('network'))).toBe('network');
    expect(errorMessage(null)).toContain('操作失败');
  });
});
