import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getTailorStatus } from './api';

const auth = vi.hoisted(() => ({ get: vi.fn(() => new Promise<string>(() => {})), refresh: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.get, refreshRevealAccessToken: auth.refresh }));
const fetchMock = vi.fn<typeof fetch>();
const DEADLINE = 15_000;
const valid = { ai_available: true, pipeline_version: 'w13.2' };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const deferred = <T,>() => { let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; }); return { promise, resolve }; };
function observe(promise: Promise<unknown>) {
  const outcome: { state: 'pending' | 'resolved' | 'rejected'; value?: unknown } = { state: 'pending' };
  void promise.then(value => { outcome.state = 'resolved'; outcome.value = value; }, error => { outcome.state = 'rejected'; outcome.value = error; });
  return outcome;
}
function heldBody(status: number, body: Promise<string>) {
  return { status, ok: status < 400, headers: new Headers(), text: () => body, json: async () => JSON.parse(await body) } as Response;
}
beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); auth.get.mockClear(); auth.refresh.mockClear(); });
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('Tailor status bounded anonymous source check', () => {
  it('performs exactly one anonymous GET with no cache or credential reuse', async () => {
    fetchMock.mockResolvedValue(json(valid));
    await expect(getTailorStatus()).resolves.toEqual(valid);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0]; expect(String(url)).toMatch(/\/tailor\/status$/);
    expect(options).toMatchObject({ method: 'GET', cache: 'no-store', credentials: 'omit', signal: expect.any(AbortSignal) });
    expect(new Headers(options?.headers).has('Authorization')).toBe(false);
    expect(auth.get).not.toHaveBeenCalled(); expect(auth.refresh).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
  });

  it.each([null, [], { ai_available: 'true', pipeline_version: 'w13.2' }, { ai_available: false },
    { ai_available: false, pipeline_version: '' }, { ai_available: true, pipeline_version: 'w13 中文' },
    { ai_available: true, pipeline_version: 'a'.repeat(81) }, { ai_available: true, pipeline_version: ['w13.2'] },
    { ai_available: true, pipeline_version: ' version' }, { ai_available: true, pipeline_version: 'v\n1' },
  ])('rejects malformed success without reflecting the input (%j)', async value => {
    fetchMock.mockResolvedValue(json(value)); const error = await getTailorStatus().catch(error => error);
    expect(error).toBeInstanceOf(ApiError); expect(error).toMatchObject({ code: 'INVALID_TAILOR_STATUS', detail: undefined });
    expect(error.message).not.toContain('中文'); expect(fetchMock).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(0);
  });

  it.each(['a', 'a'.repeat(80), 'w13.2-preview_1'])('accepts supported ASCII version boundary %s', async pipeline_version => {
    fetchMock.mockResolvedValue(json({ ai_available: false, pipeline_version }));
    await expect(getTailorStatus()).resolves.toEqual({ ai_available: false, pipeline_version });
  });

  it('rejects a signal-ignoring fetch at 15 seconds and cannot become successful later', async () => {
    const pending = deferred<Response>(); fetchMock.mockReturnValue(pending.promise); const result = observe(getTailorStatus());
    await vi.advanceTimersByTimeAsync(DEADLINE - 1); expect(result.state).toBe('pending');
    await vi.advanceTimersByTimeAsync(1); expect(result.state).toBe('rejected');
    expect(result.value).toMatchObject({ status: 408, code: 'TAILOR_STATUS_TIMEOUT', detail: undefined });
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
    pending.resolve(json(valid)); await vi.advanceTimersByTimeAsync(0); expect(result.state).toBe('rejected');
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(0);
  });

  it.each([200, 404, 503])('bounds a signal-ignoring HTTP %i body and ignores its late result', async status => {
    const body = deferred<string>(); fetchMock.mockResolvedValue(heldBody(status, body.promise));
    const result = observe(getTailorStatus()); await vi.advanceTimersByTimeAsync(DEADLINE - 1); expect(result.state).toBe('pending');
    await vi.advanceTimersByTimeAsync(1); expect(result.state).toBe('rejected');
    expect(result.value).toMatchObject({ status: 408, code: 'TAILOR_STATUS_TIMEOUT', detail: undefined });
    body.resolve(JSON.stringify(valid)); await vi.advanceTimersByTimeAsync(0); expect(result.state).toBe('rejected');
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(0);
  });

  it('shares one deadline across fetch headers and response body instead of restarting it', async () => {
    const headers = deferred<Response>(), body = deferred<string>(); fetchMock.mockReturnValue(headers.promise);
    const result = observe(getTailorStatus()); await vi.advanceTimersByTimeAsync(DEADLINE - 100);
    headers.resolve(heldBody(200, body.promise)); await vi.advanceTimersByTimeAsync(99); expect(result.state).toBe('pending');
    await vi.advanceTimersByTimeAsync(1); expect(result.state).toBe('rejected');
    expect(result.value).toMatchObject({ code: 'TAILOR_STATUS_TIMEOUT' });
    body.resolve(JSON.stringify(valid)); await vi.advanceTimersByTimeAsync(0); expect(result.state).toBe('rejected');
  });

  it.each([401, 409, 429, 503])('reports safe HTTP %i without echoing server text or retrying', async status => {
    fetchMock.mockResolvedValue(json({ detail: { message: 'PRIVATE_RESUME_CONTENT', code: 'PRIVATE_CODE', retryable: true } }, status));
    const error = await getTailorStatus().catch(error => error);
    expect(error).toBeInstanceOf(ApiError); expect(error).toMatchObject({ status, code: `HTTP_${status}`, detail: undefined });
    expect(error.message).not.toContain('PRIVATE'); await vi.advanceTimersByTimeAsync(DEADLINE * 2); expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('wraps a network exception without exposing private text and does not retry', async () => {
    fetchMock.mockRejectedValue(new Error('PRIVATE_RESUME_CONTENT https://secret.example/token'));
    const error = await getTailorStatus().catch(error => error); expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 0, detail: undefined }); expect(error.message).not.toMatch(/PRIVATE|secret/);
    await vi.advanceTimersByTimeAsync(DEADLINE * 2); expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('safely rejects invalid JSON rather than exposing body text', async () => {
    fetchMock.mockResolvedValue(new Response('PRIVATE_RESUME_CONTENT'));
    const error = await getTailorStatus().catch(error => error);
    expect(error).toBeInstanceOf(ApiError); expect(error).toMatchObject({ code: 'INVALID_TAILOR_STATUS', detail: undefined });
    expect(error.message).not.toContain('PRIVATE'); expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('bounds a rejected error-body read without echoing its exception', async () => {
    fetchMock.mockResolvedValue({ status: 503, ok: false, headers: new Headers(), text: async () => { throw new Error('PRIVATE_RESUME_CONTENT'); } } as unknown as Response);
    const error = await getTailorStatus().catch(error => error); expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 503, code: 'HTTP_503', detail: undefined }); expect(error.message).not.toContain('PRIVATE');
  });
});
