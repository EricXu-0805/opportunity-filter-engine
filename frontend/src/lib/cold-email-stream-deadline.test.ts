import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProfileData } from './types';
import { COLD_EMAIL_STREAM_TIMEOUT_MS, canFallbackColdEmailStream } from './cold-email-stream';
const auth = vi.hoisted(() => ({ token: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.token, refreshRevealAccessToken: vi.fn() }));
vi.mock('./analytics', () => ({ track: vi.fn() }));
import { generateColdEmailStream } from './api';
const profile = { name: 'Student', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore', is_international: false, research_interests: 'robotics', skills: [], coursework: [] } as unknown as ProfileData;
const fetchMock = vi.fn();
function pending<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
const frames = (value: unknown) => new TextEncoder().encode(`data: ${JSON.stringify(value)}\n\n`);
const done = { stage: 'done', subject: '主题', body: '手写经历', method: 'ai' };
beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); auth.token.mockReset().mockResolvedValue(null); });
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });
async function drain() { await vi.advanceTimersByTimeAsync(0); }

describe('Cold Email stream completion and no replay', () => {
  it('bounds auth wait and never sends after a late credential arrives', async () => {
    const token = pending<string>(); auth.token.mockReturnValue(token.promise);
    let error: unknown; void generateColdEmailStream(profile, 'A').catch(value => { error = value; });
    await vi.advanceTimersByTimeAsync(COLD_EMAIL_STREAM_TIMEOUT_MS);
    expect(error).toMatchObject({ code: 'timeout' }); expect(canFallbackColdEmailStream(error)).toBe(false);
    token.resolve('late-secret'); await drain(); expect(fetchMock).not.toHaveBeenCalled();
  });
  it('bounds a signal-ignoring fetch and cancels its late body', async () => {
    const header = pending<Response>(); fetchMock.mockReturnValue(header.promise);
    let error: unknown; void generateColdEmailStream(profile, 'A').catch(value => { error = value; });
    await vi.advanceTimersByTimeAsync(COLD_EMAIL_STREAM_TIMEOUT_MS);
    expect(error).toMatchObject({ code: 'timeout' });
    const cancel = vi.fn(); header.resolve({ body: { cancel }, ok: true } as unknown as Response);
    await drain(); expect(cancel).toHaveBeenCalledOnce(); expect(fetchMock).toHaveBeenCalledOnce();
  });
  it('bounds a reader ignoring abort, and ignores late stages and results', async () => {
    const read = pending<ReadableStreamReadResult<Uint8Array>>(); const cancel = vi.fn().mockResolvedValue(undefined);
    const reader = { read: vi.fn(() => read.promise), cancel };
    fetchMock.mockResolvedValue({ ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }), body: { getReader: () => reader } });
    const stage = vi.fn(); let error: unknown;
    void generateColdEmailStream(profile, 'A', {}, stage).catch(value => { error = value; });
    await vi.advanceTimersByTimeAsync(COLD_EMAIL_STREAM_TIMEOUT_MS);
    expect(error).toMatchObject({ code: 'timeout' }); expect(cancel).toHaveBeenCalledOnce();
    read.resolve({ done: false, value: frames({ stage: 'drafting' }) }); await drain();
    expect(stage).not.toHaveBeenCalled(); expect(reader.read).toHaveBeenCalledOnce();
  });
  it('returns on done without waiting for an open connection to close', async () => {
    const cancel = vi.fn(); let sent = false;
    fetchMock.mockResolvedValue(new Response(new ReadableStream({ pull(controller) { if (!sent) { sent = true; controller.enqueue(frames(done)); } }, cancel }), { headers: { 'content-type': 'text/event-stream' } }));
    let result: unknown; void generateColdEmailStream(profile, 'A').then(value => { result = value; }).catch(value => { result = value; });
    await drain(); expect(result).toMatchObject(done); expect(cancel).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it.each([404, 405, 409, 429, 500, 503])('does not read private or hanging HTTP %i bodies', async status => {
    const text = vi.fn(() => new Promise<string>(() => {})); const cancel = vi.fn().mockResolvedValue(undefined);
    fetchMock.mockResolvedValue({ ok: false, status, text, body: { cancel } });
    let error: unknown; void generateColdEmailStream(profile, 'A').catch(value => { error = value; }); await drain();
    expect(error).toMatchObject({ status }); expect(text).not.toHaveBeenCalled();
    expect(canFallbackColdEmailStream(error)).toBe(status === 404 || status === 405);
    expect(fetchMock).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
  it('never exposes raw network errors or permits a replay', async () => {
    fetchMock.mockRejectedValue(new Error('private URL and credentials'));
    const error = await generateColdEmailStream(profile, 'A').catch(error => error);
    expect(error).toMatchObject({ code: 'network_error' }); expect(error.message).not.toContain('private URL');
    expect(canFallbackColdEmailStream(error)).toBe(false);
  });
});
