import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CONTACT_REVEAL_TIMEOUT_MS, getOpportunityById } from './api';

const auth = vi.hoisted(() => ({ token: vi.fn(), refresh: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.token, refreshRevealAccessToken: auth.refresh }));
const fetchMock = vi.fn();
const locked = { id: 'one', contact_email_status: 'sign_in_required' };
const revealed = { id: 'one', contact_email_status: 'revealed', contact_email: 'fixture@example.edu' };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}
function observe(promise: Promise<unknown>) {
  const result: { state: string; value?: unknown } = { state: 'pending' };
  void promise.then(value => { result.state = 'resolved'; result.value = value; }, value => { result.state = 'rejected'; result.value = value; });
  return result;
}
beforeEach(() => {
  vi.useFakeTimers(); auth.token.mockReset().mockResolvedValue('first');
  auth.refresh.mockReset().mockResolvedValue('fresh'); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('contact reveal complete-operation deadline and cancellation', () => {
  it('requires strict token lookup and never falls back to an anonymous GET after an auth read error', async () => {
    auth.token.mockRejectedValue(new Error('Session read failed'));
    await expect(getOpportunityById('one')).rejects.toThrow('Session read failed');
    expect(auth.token).toHaveBeenCalledWith({ throwOnError: true });
    expect(fetchMock).not.toHaveBeenCalled(); expect(auth.refresh).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
  });
  it('requires strict refresh and keeps its failure visible without returning a misleading locked response', async () => {
    fetchMock.mockResolvedValue(json(locked)); auth.refresh.mockRejectedValue(new Error('Session refresh failed'));
    await expect(getOpportunityById('one')).rejects.toThrow('Session refresh failed');
    expect(auth.refresh).toHaveBeenCalledWith({ throwOnError: true });
    expect(fetchMock).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });

  it.each(['token', 'headers', 'body', 'refresh'] as const)('bounds a stalled %s and retires late completion', async phase => {
    const held = deferred<unknown>(); const cancel = vi.fn(async () => {});
    auth.token.mockImplementation(() => phase === 'token' ? held.promise : Promise.resolve('first'));
    if (phase === 'headers') fetchMock.mockReturnValue(held.promise);
    else if (phase === 'body') fetchMock.mockResolvedValue({ ok: true, status: 200, body: { cancel }, json: () => held.promise });
    else fetchMock.mockResolvedValue(json(locked));
    if (phase === 'refresh') auth.refresh.mockReturnValue(held.promise);
    const result = observe(getOpportunityById('one'));
    await vi.advanceTimersByTimeAsync(CONTACT_REVEAL_TIMEOUT_MS - 1);
    expect(result.state).toBe('pending');
    await vi.advanceTimersByTimeAsync(1);
    expect(result).toMatchObject({ state: 'rejected', value: { status: 408, code: 'CONTACT_REVEAL_TIMEOUT' } });
    const calls = fetchMock.mock.calls.length;
    held.resolve(phase === 'headers' ? json(revealed) : phase === 'body' ? revealed : 'late-token');
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(calls);
    expect(result.state).toBe('rejected');
    expect(vi.getTimerCount()).toBe(0);
    if (phase === 'body') expect(cancel).toHaveBeenCalled();
  });
  it('shares the deadline across initial token, locked response, and refresh', async () => {
    const token = deferred<string>(); const fresh = deferred<string>();
    auth.token.mockReturnValue(token.promise); auth.refresh.mockReturnValue(fresh.promise); fetchMock.mockResolvedValue(json(locked));
    const result = observe(getOpportunityById('one'));
    await vi.advanceTimersByTimeAsync(20_000); token.resolve('first'); await vi.advanceTimersByTimeAsync(0);
    expect(auth.refresh).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(result).toMatchObject({ state: 'rejected', value: { code: 'CONTACT_REVEAL_TIMEOUT' } });
    fresh.resolve('late-fresh'); await vi.advanceTimersByTimeAsync(0); expect(fetchMock).toHaveBeenCalledOnce();
  });
  it('does not perform auth or fetch for an already-aborted caller', async () => {
    const caller = new AbortController(); caller.abort();
    await expect(getOpportunityById('one', { signal: caller.signal })).rejects.toMatchObject({ name: 'AbortError' });
    expect(auth.token).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
  });
  it.each(['token', 'refresh'] as const)('cancels while waiting for %s without sending a late request', async phase => {
    const held = deferred<string>(); const caller = new AbortController();
    if (phase === 'token') auth.token.mockReturnValue(held.promise);
    else { auth.refresh.mockReturnValue(held.promise); fetchMock.mockResolvedValue(json(locked)); }
    const result = observe(getOpportunityById('one', { signal: caller.signal }));
    await vi.advanceTimersByTimeAsync(0); caller.abort(); await vi.advanceTimersByTimeAsync(0);
    expect(result).toMatchObject({ state: 'rejected', value: { name: 'AbortError' } });
    const calls = fetchMock.mock.calls.length; held.resolve('late'); await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(calls); expect(vi.getTimerCount()).toBe(0);
  });
  it('cancels an outstanding body and does not publish its later email', async () => {
    const caller = new AbortController(); const held = deferred<unknown>(); const cancel = vi.fn(async () => {});
    fetchMock.mockResolvedValue({ ok: true, status: 200, body: { cancel }, json: () => held.promise });
    const result = observe(getOpportunityById('one', { signal: caller.signal }));
    await vi.advanceTimersByTimeAsync(0); const signal = fetchMock.mock.calls[0][1].signal;
    caller.abort(); await vi.advanceTimersByTimeAsync(0);
    expect(signal.aborted).toBe(true); expect(cancel).toHaveBeenCalled();
    held.resolve(revealed); await vi.advanceTimersByTimeAsync(0);
    expect(result).toMatchObject({ state: 'rejected', value: { name: 'AbortError' } }); expect(vi.getTimerCount()).toBe(0);
  });
  it.each(['http', 'network'] as const)('keeps %s errors visible without automatic transport retry', async mode => {
    if (mode === 'http') fetchMock.mockResolvedValue(new Response('Internal Server Error', { status: 500 }));
    else fetchMock.mockRejectedValue(new Error('private proxy text'));
    await expect(getOpportunityById('one')).rejects.toMatchObject({ code: mode === 'http' ? 'HTTP_500' : 'NETWORK_ERROR' });
    expect(fetchMock).toHaveBeenCalledOnce(); expect(auth.refresh).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
  });
  it('cleans listeners on success so later caller cancellation does not abort a completed response', async () => {
    const caller = new AbortController(); const removed = vi.spyOn(caller.signal, 'removeEventListener');
    fetchMock.mockResolvedValue(json(revealed));
    await expect(getOpportunityById('one', { signal: caller.signal })).resolves.toEqual(revealed);
    const signal = fetchMock.mock.calls[0][1].signal;
    expect(removed).toHaveBeenCalledWith('abort', expect.any(Function)); expect(vi.getTimerCount()).toBe(0);
    caller.abort(); expect(signal.aborted).toBe(false);
  });
});
