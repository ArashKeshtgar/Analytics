import { afterEach, describe, expect, it, type Mock, vi } from 'vitest';
import { ApiError, apiGet, buildUrl, type Session } from './client';

function session(token: string | null = 'tok'): Session & { expired: Mock } {
  return { accessToken: async () => token, expired: vi.fn() } as Session & { expired: Mock };
}

function respond(status: number, body: unknown): void {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

afterEach(() => vi.unstubAllGlobals());

describe('buildUrl', () => {
  it('leaves out empty parameters and encodes the rest', () => {
    expect(buildUrl('/api/x', { a: '1', b: undefined, c: '', d: 'x y&z' })).toBe('http://localhost:5600/api/x?a=1&d=x+y%26z');
    expect(buildUrl('/api/x')).toBe('http://localhost:5600/api/x');
  });
});

describe('apiGet', () => {
  it('sends the access token and returns the JSON', async () => {
    respond(200, [{ a: 1 }]);
    const result = await apiGet<unknown[]>(session('abc'), '/api/finance/range', { business: 'HV' });
    expect(result).toEqual([{ a: 1 }]);
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:5600/api/finance/range?business=HV');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer abc');
  });

  it('starts sign-in again when there is no usable token, without calling the API', async () => {
    respond(200, []);
    const s = session(null);
    await expect(apiGet(s, '/api/x')).rejects.toMatchObject({ status: 401 });
    expect(s.expired).toHaveBeenCalledOnce();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('starts sign-in again when the API says 401', async () => {
    respond(401, { detail: 'x' });
    const s = session();
    await expect(apiGet(s, '/api/x')).rejects.toBeInstanceOf(ApiError);
    expect(s.expired).toHaveBeenCalledOnce();
  });

  it('says plainly what a 403 and a 503 mean, and uses the API’s own text for 503', async () => {
    respond(403, { detail: 'No permission to view finance data.' });
    await expect(apiGet(session(), '/api/x')).rejects.toMatchObject({ status: 403, message: 'You do not have permission to see this.' });
    respond(503, { detail: 'The warehouse is not built yet. Run `analytics build`.' });
    await expect(apiGet(session(), '/api/x')).rejects.toMatchObject({ status: 503, message: 'The warehouse is not built yet. Run `analytics build`.' });
  });

  it('copes with an error that is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>bad gateway</html>', { status: 502 })));
    await expect(apiGet(session(), '/api/x')).rejects.toMatchObject({ status: 502, message: 'The request failed (502).' });
  });
});
