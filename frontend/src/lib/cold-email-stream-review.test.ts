import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProfileData } from './types';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from './identity-owner';
import { COLD_EMAIL_STREAM_TIMEOUT_MS, canFallbackColdEmailStream } from './cold-email-stream';
const auth = vi.hoisted(() => ({ token: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.token, refreshRevealAccessToken: vi.fn() }));
vi.mock('./analytics', () => ({ track: vi.fn() }));
import { generateColdEmailStream } from './api';
const profile: ProfileData = { name: 'Synthetic Student A', institution: 'UIUC', college: 'Engineering', major: 'CS', grade: 'Junior',
  is_international: false, research_interests: 'sensors', skills: [], coursework: [] };
const payload = { stage: 'done', subject: 'Safe synthetic subject', body: 'Safe synthetic body', method: 'ai' };
const bytes = (...events: unknown[]) => new TextEncoder().encode(events.map(value => `data: ${JSON.stringify(value)}\n\n`).join(''));
const fetchMock = vi.fn<typeof fetch>();
function deferred<T>() { let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function observe(promise: Promise<unknown>) { const result: { state: 'pending' | 'resolved' | 'rejected'; value?: unknown } = { state: 'pending' };
  void promise.then(value => { result.state = 'resolved'; result.value = value; }, error => { result.state = 'rejected'; result.value = error; }); return result; }
function streamResponse(chunk: Uint8Array) {
  const cancel = vi.fn(); let sent = false;
  const response = new Response(new ReadableStream<Uint8Array>({ pull(controller) { if (!sent) { sent = true; controller.enqueue(chunk); } }, cancel }),
    { headers: { 'content-type': 'text/event-stream' } });
  return { response, cancel };
}
beforeEach(async () => {
  localStorage.clear(); advanceOwnerEpoch(null); advanceOwnerEpoch('stream-owner-a'); await syncLocalIdentityOwner('stream-owner-a');
  vi.useFakeTimers(); vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); auth.token.mockReset().mockResolvedValue(null);
});
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const drain = () => vi.advanceTimersByTimeAsync(0);

describe('independent cold email stream boundaries', () => {
  it('does not send an old profile under a new account when auth changes during the credential wait', async () => {
    const credential = deferred<string>(); auth.token.mockReturnValue(credential.promise);
    fetchMock.mockResolvedValue(streamResponse(bytes(payload)).response);
    const result = observe(generateColdEmailStream(profile, 'target-a')); await drain();
    advanceOwnerEpoch('stream-owner-b'); await syncLocalIdentityOwner('stream-owner-b');
    credential.resolve('SYNTHETIC_NEW_OWNER_TOKEN'); await drain();
    expect(fetchMock).not.toHaveBeenCalled(); expect(result.state).toBe('rejected');
    expect(canFallbackColdEmailStream(result.value)).toBe(false); expect(vi.getTimerCount()).toBe(0);
  });
  it('a caller abort inside a progress callback suppresses later events in the same received chunk', async () => {
    const caller = new AbortController(); const stages: string[] = [];
    const response = streamResponse(bytes({ stage: 'drafting' }, { stage: 'revising' }, payload)); fetchMock.mockResolvedValue(response.response);
    const result = observe(generateColdEmailStream(profile, 'target-a', { signal: caller.signal }, stage => { stages.push(stage); caller.abort('PRIVATE abort reason'); }));
    await drain();
    expect(stages).toEqual(['drafting']); expect(result.state).toBe('rejected'); expect(result.value).toMatchObject({ code: 'cancelled' });
    expect(canFallbackColdEmailStream(result.value)).toBe(false); expect(response.cancel).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it('ignores unknown progress frames while retaining supported stages and the first complete done event', async () => {
    const onStage = vi.fn(); const result = streamResponse(bytes({ stage: 'new-stage', message: 'PRIVATE upstream diagnostic' }, { stage: 'judging' }, payload, { stage: 'done', subject: 'wrong later', body: 'wrong later' }));
    fetchMock.mockResolvedValue(result.response);
    await expect(generateColdEmailStream(profile, 'target-a', {}, onStage)).resolves.toMatchObject(payload);
    expect(onStage).toHaveBeenCalledExactlyOnceWith('judging'); expect(result.cancel).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it('pre-cancellation prevents auth and network and never grants compatibility fallback', async () => {
    const caller = new AbortController(); caller.abort(new Error('PRIVATE caller data'));
    const result = observe(generateColdEmailStream(profile, 'target-a', { signal: caller.signal })); await drain();
    expect(result.value).toMatchObject({ code: 'cancelled' }); expect(String(result.value)).not.toContain('PRIVATE');
    expect(auth.token).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled(); expect(canFallbackColdEmailStream(result.value)).toBe(false); expect(vi.getTimerCount()).toBe(0);
  });
  it('removes the caller listener on done so aborting a completed operation cannot alter it', async () => {
    const caller = new AbortController(); const added = vi.spyOn(caller.signal, 'addEventListener'); const removed = vi.spyOn(caller.signal, 'removeEventListener');
    const response = streamResponse(bytes(payload)); fetchMock.mockResolvedValue(response.response);
    const result = await generateColdEmailStream(profile, 'target-a', { signal: caller.signal });
    expect(removed).toHaveBeenCalledWith('abort', added.mock.calls.find(([event]) => event === 'abort')?.[1]);
    const networkSignal = fetchMock.mock.calls[0][1]?.signal; caller.abort(); await vi.advanceTimersByTimeAsync(COLD_EMAIL_STREAM_TIMEOUT_MS);
    expect(result).toMatchObject(payload); expect(networkSignal?.aborted).toBe(false); expect(response.cancel).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it('cancels while error headers are pending without turning a late 404 into permission to replay', async () => {
    const pending = deferred<Response>(); fetchMock.mockReturnValue(pending.promise); const caller = new AbortController();
    const result = observe(generateColdEmailStream(profile, 'target-a', { signal: caller.signal })); await drain();
    caller.abort(); await drain(); const cancel = vi.fn(async () => {});
    pending.resolve({ status: 404, ok: false, body: { cancel } } as unknown as Response); await drain();
    expect(result.value).toMatchObject({ code: 'cancelled' }); expect(canFallbackColdEmailStream(result.value)).toBe(false);
    expect(cancel).toHaveBeenCalledOnce(); expect(fetchMock).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
});
