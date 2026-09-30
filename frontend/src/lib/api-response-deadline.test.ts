import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getMatches, getOpportunities, tailorResume } from './api';
import type { ProfileData } from './types';

vi.mock('./analytics', () => ({ track: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: vi.fn(), refreshRevealAccessToken: vi.fn() }));
const fetchMock = vi.fn<typeof fetch>();
const DEADLINE = 60_000;
const MATCH_DEADLINE = 70_000;
const profile: ProfileData = { institution: 'UIUC', college: 'Engineering', major: 'CS', grade: 'Junior',
  is_international: false, research_interests: 'sensors', skills: [], coursework: [] };
const matches = { total: 0, results: [], opportunities: [] };
const valid = { total: 0, opportunities: [] };
const json = (value: unknown, status = 200, headers?: HeadersInit) => new Response(JSON.stringify(value), { status, headers });
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function observe(promise: Promise<unknown>) {
  const result: { state: 'pending' | 'resolved' | 'rejected'; value?: unknown } = { state: 'pending' };
  void promise.then(value => { result.state = 'resolved'; result.value = value; }, error => { result.state = 'rejected'; result.value = error; });
  return result;
}
function heldBody(status: number, text: Promise<string>) {
  const cancel = vi.fn(async () => {});
  const readJson = vi.fn(async () => JSON.parse(await text));
  const readText = vi.fn(() => text);
  const response = { status, ok: status < 400, headers: new Headers(), body: { cancel }, json: readJson, text: readText } as unknown as Response;
  return { response, cancel, readJson, readText };
}
function expectTimeout(result: ReturnType<typeof observe>) {
  expect(result.state).toBe('rejected');
  expect(result.value).toMatchObject({ name: 'ApiError', status: 408, code: 'REQUEST_TIMEOUT', retryable: true, detail: undefined });
}
function expectCancelled(result: ReturnType<typeof observe>) {
  expect(result.state).toBe('rejected');
  expect(result.value).toMatchObject({ name: 'AbortError', message: 'The request was cancelled.' });
}
beforeEach(() => { vi.useFakeTimers(); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); });
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('generic JSON request complete-response deadline', () => {
  it('rejects an AbortSignal-ignoring fetch on the deadline and cancels late headers without reading them', async () => {
    const headers = deferred<Response>(); fetchMock.mockReturnValue(headers.promise);
    const result = observe(getOpportunities());
    await vi.advanceTimersByTimeAsync(DEADLINE - 1); expect(result.state).toBe('pending');
    await vi.advanceTimersByTimeAsync(1); expectTimeout(result);
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
    const late = heldBody(200, Promise.resolve(JSON.stringify(valid))); headers.resolve(late.response);
    await vi.advanceTimersByTimeAsync(0); expectTimeout(result);
    expect(late.cancel).toHaveBeenCalledOnce(); expect(late.readJson).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it.each([200, 422, 503])('bounds a signal-ignoring HTTP %i body and cannot become successful on late body completion', async status => {
    const body = deferred<string>(); const held = heldBody(status, body.promise); fetchMock.mockResolvedValue(held.response);
    const result = observe(getOpportunities());
    await vi.advanceTimersByTimeAsync(DEADLINE - 1); expect(result.state).toBe('pending');
    await vi.advanceTimersByTimeAsync(1); expectTimeout(result);
    expect(held.cancel).toHaveBeenCalledOnce();
    body.resolve(JSON.stringify(valid)); await vi.advanceTimersByTimeAsync(0); expectTimeout(result);
    expect(fetchMock).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it('uses one deadline across the headers and body instead of restarting after headers', async () => {
    const headers = deferred<Response>(), body = deferred<string>(); fetchMock.mockReturnValue(headers.promise);
    const result = observe(getOpportunities()); await vi.advanceTimersByTimeAsync(DEADLINE - 100);
    headers.resolve(heldBody(200, body.promise).response);
    await vi.advanceTimersByTimeAsync(99); expect(result.state).toBe('pending');
    await vi.advanceTimersByTimeAsync(1); expectTimeout(result);
    body.resolve(JSON.stringify(valid)); await vi.advanceTimersByTimeAsync(0); expectTimeout(result);
  });
  it('does not dispatch any request when the caller is already cancelled, even if fetch would ignore its signal', async () => {
    const caller = new AbortController(); caller.abort(new Error('PRIVATE caller reason'));
    fetchMock.mockResolvedValue(json(matches)); const result = observe(getMatches(profile, { signal: caller.signal }));
    await vi.advanceTimersByTimeAsync(0); expectCancelled(result); expect(fetchMock).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
  });
  it('caller cancellation settles a signal-ignoring fetch immediately and prevents late acceptance', async () => {
    const headers = deferred<Response>(); fetchMock.mockReturnValue(headers.promise);
    const caller = new AbortController(); const result = observe(getMatches(profile, { signal: caller.signal }));
    await vi.advanceTimersByTimeAsync(0); caller.abort(new Error('PRIVATE caller reason')); await vi.advanceTimersByTimeAsync(0);
    expectCancelled(result); expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
    const late = heldBody(200, Promise.resolve(JSON.stringify(matches))); headers.resolve(late.response);
    await vi.advanceTimersByTimeAsync(MATCH_DEADLINE * 2); expectCancelled(result);
    expect(late.cancel).toHaveBeenCalledOnce(); expect(late.readJson).not.toHaveBeenCalled(); expect(fetchMock).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it.each([200, 422, 503])('keeps caller cancellation attached until the entire HTTP %i body settles', async status => {
    const body = deferred<string>(); const held = heldBody(status, body.promise); fetchMock.mockResolvedValue(held.response);
    const caller = new AbortController(); const remove = vi.spyOn(caller.signal, 'removeEventListener');
    const result = observe(getMatches(profile, { signal: caller.signal })); await vi.advanceTimersByTimeAsync(0);
    expect(remove).not.toHaveBeenCalledWith('abort', expect.any(Function));
    caller.abort('PRIVATE abort text'); await vi.advanceTimersByTimeAsync(0); expectCancelled(result);
    expect(held.cancel).toHaveBeenCalledOnce(); body.resolve(JSON.stringify(matches)); await vi.advanceTimersByTimeAsync(MATCH_DEADLINE * 2);
    expectCancelled(result); expect(fetchMock).toHaveBeenCalledOnce(); expect(remove).toHaveBeenCalledWith('abort', expect.any(Function)); expect(vi.getTimerCount()).toBe(0);
  });
  it('cleans listeners and timers after success without later caller abort cancelling the completed request', async () => {
    const caller = new AbortController(); const added = vi.spyOn(caller.signal, 'addEventListener'); const removed = vi.spyOn(caller.signal, 'removeEventListener');
    fetchMock.mockResolvedValue(json(matches)); await expect(getMatches(profile, { signal: caller.signal })).resolves.toEqual(matches);
    const listener = added.mock.calls.find(([event]) => event === 'abort')?.[1]; expect(listener).toBeTypeOf('function');
    expect(removed).toHaveBeenCalledWith('abort', listener); expect(vi.getTimerCount()).toBe(0);
    const fetchSignal = fetchMock.mock.calls[0][1]?.signal; caller.abort(); expect(fetchSignal?.aborted).toBe(false);
  });
  it('cleans listeners and timers after a structured non-retryable HTTP error and keeps its contract', async () => {
    const caller = new AbortController(); const remove = vi.spyOn(caller.signal, 'removeEventListener');
    fetchMock.mockResolvedValue(json({ detail: { code: 'MATCH_INVALID', message: 'Choose a school.', retryable: false } }, 422, { 'x-request-id': 'synthetic-receipt' }));
    await expect(getMatches(profile, { signal: caller.signal })).rejects.toMatchObject({ status: 422, code: 'MATCH_INVALID', message: 'Choose a school.', requestId: 'synthetic-receipt', retryable: false });
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function)); expect(vi.getTimerCount()).toBe(0); expect(fetchMock).toHaveBeenCalledOnce();
  });
  it('never automatically repeats a non-opted-in POST after a body deadline', async () => {
    const body = deferred<string>(); fetchMock.mockResolvedValue(heldBody(200, body.promise).response);
    const result = observe(tailorResume(profile, 'target-one', ['A complete human bullet']));
    await vi.advanceTimersByTimeAsync(DEADLINE); expectTimeout(result);
    await vi.advanceTimersByTimeAsync(DEADLINE * 2); expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][1]?.method).toBe('POST');
    body.resolve(JSON.stringify({ tailored_bullets: [] })); await vi.advanceTimersByTimeAsync(0); expectTimeout(result);
  });
  it('preserves explicit retry attempts while an earlier timed-out body remains retired', async () => {
    const firstBody = deferred<string>(); fetchMock.mockResolvedValueOnce(heldBody(200, firstBody.promise).response).mockResolvedValueOnce(json(matches));
    const result = observe(getMatches(profile)); await vi.advanceTimersByTimeAsync(MATCH_DEADLINE);
    expect(result.state).toBe('pending'); expect(fetchMock).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1499); expect(fetchMock).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1); expect(result).toEqual({ state: 'resolved', value: matches }); expect(fetchMock).toHaveBeenCalledTimes(2);
    firstBody.resolve(JSON.stringify({ total: 999, results: ['LATE OLD RESPONSE'] })); await vi.advanceTimersByTimeAsync(0);
    expect(result.value).toEqual(matches); expect(vi.getTimerCount()).toBe(0);
  });
  it('keeps the existing Retry-After and explicit retry-count contract for matching', async () => {
    const busy = () => json({ detail: { code: 'MATCH_BUSY', message: 'Busy', retryable: true } }, 503, { 'retry-after': '2' });
    fetchMock.mockResolvedValueOnce(busy()).mockResolvedValueOnce(json(matches)); const result = observe(getMatches(profile));
    await vi.advanceTimersByTimeAsync(1999); expect(result.state).toBe('pending'); expect(fetchMock).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1); expect(result.value).toEqual(matches); expect(fetchMock).toHaveBeenCalledTimes(2); expect(vi.getTimerCount()).toBe(0);
  });
  it('sanitizes raw network failure and does not add new retry eligibility', async () => {
    fetchMock.mockRejectedValue(new Error('PRIVATE source text https://secret.example/token'));
    const error = await getMatches(profile).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ApiError); expect(error).toMatchObject({ status: 0, code: 'NETWORK_ERROR', retryable: false, detail: undefined });
    expect((error as Error).message).not.toMatch(/PRIVATE|secret/); expect(error).not.toHaveProperty('cause');
    expect(fetchMock).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it.each(['rejected-body', 'malformed-json'] as const)('sanitizes a successful response with %s without a new automatic retry', async kind => {
    fetchMock.mockResolvedValue(kind === 'malformed-json' ? new Response('PRIVATE malformed body')
      : heldBody(200, Promise.reject(new Error('PRIVATE body failure'))).response);
    const error = await getMatches(profile).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ApiError); expect(error).toMatchObject({ code: 'INVALID_RESPONSE', retryable: false, detail: undefined });
    expect((error as Error).message).not.toContain('PRIVATE'); expect(error).not.toHaveProperty('cause'); expect(fetchMock).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it('also sanitizes an error-body reader which throws before returning a promise', async () => {
    fetchMock.mockResolvedValue({ status: 503, ok: false, headers: new Headers(), text: () => { throw new Error('PRIVATE synchronous body error'); } } as unknown as Response);
    const error = await getOpportunities().catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 503, code: 'HTTP_503', message: 'The service is busy. Please try again shortly.' });
    expect((error as Error).message).not.toContain('PRIVATE'); expect(error).not.toHaveProperty('cause');
    expect(fetchMock).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it('settles the deadline while a real streamed JSON body is locked, and ignores its later complete document', async () => {
    let stream!: ReadableStreamDefaultController<Uint8Array>;
    fetchMock.mockResolvedValue(new Response(new ReadableStream<Uint8Array>({ start(controller) { stream = controller; } })));
    const result = observe(getOpportunities()); await vi.advanceTimersByTimeAsync(DEADLINE); expectTimeout(result);
    stream.enqueue(new TextEncoder().encode(JSON.stringify(valid))); stream.close();
    await vi.advanceTimersByTimeAsync(0); expectTimeout(result); expect(fetchMock).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it('retains a safe HTTP fallback when its error body rejects, without leaking the read error', async () => {
    fetchMock.mockResolvedValue(heldBody(503, Promise.reject(new Error('PRIVATE read error'))).response);
    const error = await getOpportunities().catch((value: unknown) => value);
    expect(error).toMatchObject({ status: 503, code: 'HTTP_503', message: 'The service is busy. Please try again shortly.' });
    expect((error as Error).message).not.toContain('PRIVATE'); expect(fetchMock).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
});
