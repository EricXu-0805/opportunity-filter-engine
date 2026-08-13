import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { PUBLIC_RELEASE_CACHE_VERSION } from './release-scope';
import {
  fetchOpportunityServer,
  fetchSimilarServer,
  fetchOpportunityIdsServer,
  fetchOpportunityDetail,
} from './api-server';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  vi.unstubAllEnvs();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function okJson<T>(body: T): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

function badResponse(status: number): Response {
  return new Response('', { status });
}

describe('server-side API base URL resolution', () => {
  it('uses BACKEND_URL when set (highest priority)', async () => {
    vi.stubEnv('BACKEND_URL', 'https://custom.example.com');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://wrong.example.com');
    fetchMock.mockResolvedValue(okJson({ id: 'x' }));

    await fetchOpportunityServer('x');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url.startsWith('https://custom.example.com/')).toBe(true);
  });

  it('falls back to NEXT_PUBLIC_API_URL when BACKEND_URL is unset', async () => {
    vi.stubEnv('BACKEND_URL', '');
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://public-api.example.com');
    fetchMock.mockResolvedValue(okJson({ id: 'x' }));

    await fetchOpportunityServer('x');

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url.startsWith('https://public-api.example.com/')).toBe(true);
  });

  it('falls back to the prod Render URL when VERCEL_ENV=production', async () => {
    vi.stubEnv('BACKEND_URL', '');
    vi.stubEnv('NEXT_PUBLIC_API_URL', '');
    vi.stubEnv('VERCEL_ENV', 'production');
    vi.stubEnv('NODE_ENV', 'development');
    fetchMock.mockResolvedValue(okJson({ id: 'x' }));

    await fetchOpportunityServer('x');

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url.startsWith('https://opportunity-filter-engine-api.onrender.com/')).toBe(true);
  });

  it('falls back to localhost:8000 when not in production', async () => {
    vi.stubEnv('BACKEND_URL', '');
    vi.stubEnv('NEXT_PUBLIC_API_URL', '');
    vi.stubEnv('VERCEL_ENV', '');
    vi.stubEnv('NODE_ENV', 'development');
    fetchMock.mockResolvedValue(okJson({ id: 'x' }));

    await fetchOpportunityServer('x');

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url.startsWith('http://127.0.0.1:8000/')).toBe(true);
  });

  it('strips a trailing slash from BACKEND_URL to avoid double slashes', async () => {
    vi.stubEnv('BACKEND_URL', 'https://backend.example.com/');
    fetchMock.mockResolvedValue(okJson({ id: 'x' }));

    await fetchOpportunityServer('x');

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe(
      `https://backend.example.com/api/opportunities/x?_release_scope=${encodeURIComponent(PUBLIC_RELEASE_CACHE_VERSION)}`,
    );
  });
});

describe('fetchOpportunityServer', () => {
  beforeEach(() => {
    vi.stubEnv('BACKEND_URL', 'https://api.test');
  });

  it('returns parsed JSON on 200', async () => {
    fetchMock.mockResolvedValue(okJson({ id: 'opp-1', title: 'Test' }));
    const result = await fetchOpportunityServer('opp-1');
    expect(result).toEqual({ id: 'opp-1', title: 'Test' });
  });

  it('URL-encodes the id (so a slashy id does not break the route)', async () => {
    fetchMock.mockResolvedValue(okJson({ id: 'x' }));
    await fetchOpportunityServer('uiuc/cs:101');
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe(
      `https://api.test/api/opportunities/uiuc%2Fcs%3A101?_release_scope=${encodeURIComponent(PUBLIC_RELEASE_CACHE_VERSION)}`,
    );
  });

  it('returns null on a non-2xx response', async () => {
    fetchMock.mockResolvedValue(badResponse(404));
    expect(await fetchOpportunityServer('missing')).toBeNull();
  });

  it('returns null when fetch throws (network error)', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
    expect(await fetchOpportunityServer('opp-1')).toBeNull();
  });
});

describe('fetchSimilarServer', () => {
  beforeEach(() => {
    vi.stubEnv('BACKEND_URL', 'https://api.test');
  });

  it('returns body.opportunities on success', async () => {
    fetchMock.mockResolvedValue(
      okJson({ opportunities: [{ id: 'a', _similarity: 0.9 }, { id: 'b', _similarity: 0.8 }] }),
    );
    const result = await fetchSimilarServer('seed');
    expect(result).toEqual([
      { id: 'a', _similarity: 0.9 },
      { id: 'b', _similarity: 0.8 },
    ]);
  });

  it('returns [] when body has no opportunities key', async () => {
    fetchMock.mockResolvedValue(okJson({ other: 'shape' }));
    expect(await fetchSimilarServer('seed')).toEqual([]);
  });

  it('returns [] on non-2xx', async () => {
    fetchMock.mockResolvedValue(badResponse(500));
    expect(await fetchSimilarServer('seed')).toEqual([]);
  });

  it('returns [] when fetch throws', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));
    expect(await fetchSimilarServer('seed')).toEqual([]);
  });

  it('honours the limit query parameter (default 5)', async () => {
    fetchMock.mockResolvedValue(okJson({ opportunities: [] }));
    await fetchSimilarServer('seed');
    expect(fetchMock.mock.calls[0][0]).toContain('limit=5');
  });

  it('honours a custom limit', async () => {
    fetchMock.mockResolvedValue(okJson({ opportunities: [] }));
    await fetchSimilarServer('seed', 12);
    expect(fetchMock.mock.calls[0][0]).toContain('limit=12');
  });

  it('uses the release-scope cache version after the limit query', async () => {
    fetchMock.mockResolvedValue(okJson({ opportunities: [] }));
    await fetchSimilarServer('seed');
    expect(fetchMock.mock.calls[0][0]).toContain(
      `limit=5&_release_scope=${encodeURIComponent(PUBLIC_RELEASE_CACHE_VERSION)}`,
    );
  });

  it('degrades to [] on a finite timeout instead of hanging the caller (fail-open)', async () => {
    vi.useFakeTimers();
    try {
      fetchMock.mockImplementation((_url: string, options: { signal: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          options.signal.addEventListener('abort', () => {
            reject(new DOMException('The operation was aborted', 'AbortError'));
          });
        }),
      );
      const pending = fetchSimilarServer('seed');
      await vi.advanceTimersByTimeAsync(8000);
      expect(await pending).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('fetchOpportunityIdsServer', () => {
  beforeEach(() => {
    vi.stubEnv('BACKEND_URL', 'https://api.test');
  });

  it('returns the id list extracted from body.opportunities', async () => {
    fetchMock.mockResolvedValue(
      okJson({ opportunities: [{ id: 'a' }, { id: 'b' }, { id: 'c' }] }),
    );
    expect(await fetchOpportunityIdsServer()).toEqual(['a', 'b', 'c']);
  });

  it('filters out falsy / empty ids', async () => {
    fetchMock.mockResolvedValue(
      okJson({ opportunities: [{ id: 'a' }, { id: '' }, { id: 'c' }] }),
    );
    expect(await fetchOpportunityIdsServer()).toEqual(['a', 'c']);
  });

  it('returns [] when body has no opportunities key', async () => {
    fetchMock.mockResolvedValue(okJson({}));
    expect(await fetchOpportunityIdsServer()).toEqual([]);
  });

  it('returns [] on non-2xx', async () => {
    fetchMock.mockResolvedValue(badResponse(502));
    expect(await fetchOpportunityIdsServer()).toEqual([]);
  });

  it('returns [] when fetch throws', async () => {
    fetchMock.mockRejectedValue(new Error('boom'));
    expect(await fetchOpportunityIdsServer()).toEqual([]);
  });

  it('passes limit=200 to keep the SSR fetch bounded', async () => {
    fetchMock.mockResolvedValue(okJson({ opportunities: [] }));
    await fetchOpportunityIdsServer();
    expect(fetchMock.mock.calls[0][0]).toContain('limit=200');
  });

  it('does not reuse a pre-release-scope server data-cache key', async () => {
    fetchMock.mockResolvedValue(okJson({ opportunities: [] }));
    await fetchOpportunityIdsServer();
    expect(fetchMock.mock.calls[0][0]).toContain(
      `limit=200&_release_scope=${encodeURIComponent(PUBLIC_RELEASE_CACHE_VERSION)}`,
    );
  });
});

describe('fetchOpportunityDetail (detail-page classification)', () => {
  beforeEach(() => {
    vi.stubEnv('BACKEND_URL', 'https://api.test');
  });

  it('returns ok with the opportunity when the body id matches the requested id', async () => {
    fetchMock.mockResolvedValue(okJson({ id: 'opp-1', title: 'Test' }));
    const result = await fetchOpportunityDetail('opp-1');
    expect(result).toEqual({ status: 'ok', opportunity: { id: 'opp-1', title: 'Test' } });
  });

  it('classifies an explicit 404 as not-found', async () => {
    fetchMock.mockResolvedValue(badResponse(404));
    expect(await fetchOpportunityDetail('missing')).toEqual({ status: 'not-found' });
  });

  it('classifies an explicit 400 as not-found', async () => {
    fetchMock.mockResolvedValue(badResponse(400));
    expect(await fetchOpportunityDetail('bad-id')).toEqual({ status: 'not-found' });
  });

  it('classifies a 429 as unavailable, never not-found', async () => {
    fetchMock.mockResolvedValue(badResponse(429));
    expect(await fetchOpportunityDetail('opp-1')).toEqual({ status: 'unavailable' });
  });

  it('classifies a 5xx as unavailable, never not-found', async () => {
    fetchMock.mockResolvedValue(badResponse(502));
    expect(await fetchOpportunityDetail('opp-1')).toEqual({ status: 'unavailable' });
  });

  it('classifies a network error as unavailable', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));
    expect(await fetchOpportunityDetail('opp-1')).toEqual({ status: 'unavailable' });
  });

  it('classifies an unparseable (non-JSON) 200 body as unavailable', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.reject(new SyntaxError('Unexpected token')),
    } as unknown as Response);
    expect(await fetchOpportunityDetail('opp-1')).toEqual({ status: 'unavailable' });
  });

  it('classifies a body missing id as unavailable', async () => {
    fetchMock.mockResolvedValue(okJson({ title: 'no id here' }));
    expect(await fetchOpportunityDetail('opp-1')).toEqual({ status: 'unavailable' });
  });

  it('classifies a body with an empty-string id as unavailable', async () => {
    fetchMock.mockResolvedValue(okJson({ id: '', title: 'empty id' }));
    expect(await fetchOpportunityDetail('opp-1')).toEqual({ status: 'unavailable' });
  });

  it('classifies a returned id mismatch as unavailable, never renders the wrong opportunity', async () => {
    fetchMock.mockResolvedValue(okJson({ id: 'some-other-id', title: 'wrong record' }));
    expect(await fetchOpportunityDetail('opp-1')).toEqual({ status: 'unavailable' });
  });

  it('classifies a timeout (finite abort) as unavailable', async () => {
    vi.useFakeTimers();
    try {
      fetchMock.mockImplementation((_url: string, options: { signal: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          options.signal.addEventListener('abort', () => {
            reject(new DOMException('The operation was aborted', 'AbortError'));
          });
        }),
      );
      const pending = fetchOpportunityDetail('opp-1');
      await vi.advanceTimersByTimeAsync(8000);
      expect(await pending).toEqual({ status: 'unavailable' });
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not change the legacy fetchOpportunityServer contract', async () => {
    fetchMock.mockResolvedValue(okJson({ id: 'opp-1', title: 'Test' }));
    expect(await fetchOpportunityServer('opp-1')).toEqual({ id: 'opp-1', title: 'Test' });
    fetchMock.mockResolvedValue(badResponse(404));
    expect(await fetchOpportunityServer('missing')).toBeNull();
  });
});
