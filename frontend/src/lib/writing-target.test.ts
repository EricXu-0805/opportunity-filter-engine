import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './api';
import { PUBLIC_RELEASE_CACHE_VERSION } from './release-scope';
import { targetPosture } from './target-truth';
import type { Opportunity } from './types';
import { readWritingTarget, writingTargetKey, WRITING_TARGET_TIMEOUT_MS } from './writing-target';

const auth = vi.hoisted(() => ({ get: vi.fn(() => new Promise<string>(() => {})), refresh: vi.fn() }));
// Import the real ApiError class without creating an SDK or auth network. If
// the transport starts waiting for either token function, these tests fail.
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.get, refreshRevealAccessToken: auth.refresh }));

const full = (id = 'target-1') => ({
  id, title: '材料研究 🧪', organization: 'Example University', department: 'Chemistry',
  opportunity_type: 'research', paid: 'unknown', location: 'Campus', on_campus: true,
  description_clean: 'Full public description\r\nwith exact whitespace.  ', description_raw: 'Original public text',
  source_type: 'campus_program', record_kind: 'listing', source_url: 'https://example.edu/research',
  keywords: ['materials', 'research'],
  eligibility: { international_friendly: 'unknown', preferred_year: [], majors: ['Chemistry'], skills_required: ['Python'], citizenship_required: null },
  application: { application_effort: 'medium', requires_resume: 'yes', contact_method: 'form', application_url: 'https://example.edu/apply' },
  metadata: { confidence_score: 0.9, recent_works: [{ title: 'Paper 🧪', year: 2026 }] },
  target_truth: { actionable: true, listing_state: 'open', accepting_state: 'accepting', reference_only: false, reason_code: null, verified_at: null, expires_at: null },
  contact_email_status: 'sign_in_required',
});
const fetchMock = vi.fn<typeof fetch>();
const pending = <T,>() => { let resolve!: (value: T) => void; let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const bodyResponse = (status: number, text: () => Promise<string>) => ({ status, ok: status >= 200 && status < 300, text } as Response);

beforeEach(() => { vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); auth.get.mockClear(); auth.refresh.mockClear(); vi.stubEnv('NEXT_PUBLIC_API_URL', ''); });
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe('readWritingTarget anonymous full-detail transport', () => {
  it('uses the anonymous no-store detail contract and preserves the complete public JSON', async () => {
    const target = { ...full(), optional_future_field: { z: ['last', 'first'], a: 'not projected out' } };
    fetchMock.mockResolvedValue(json(target));
    const received = await readWritingTarget(target.id);
    expect(received).toEqual(target);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(`/api/opportunities/target-1?_release_scope=${encodeURIComponent(PUBLIC_RELEASE_CACHE_VERSION)}`, {
      method: 'GET', cache: 'no-store', credentials: 'omit', signal: expect.any(AbortSignal), headers: { Accept: 'application/json' },
    });
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.has('Authorization')).toBe(false);
    expect(auth.get).not.toHaveBeenCalled(); expect(auth.refresh).not.toHaveBeenCalled();
  });

  it('keeps the exact server writing version with the complete target', async () => {
    const target = { ...full(), writing_target_version: 'wt1:' + 'a'.repeat(64) };
    fetchMock.mockResolvedValue(json(target));
    expect(await readWritingTarget(target.id)).toEqual(target);
  });

  it('encodes the whole id as one path segment and honors the configured API base', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'https://api.example.test/api/');
    const id = '学校/target ?#%'; fetchMock.mockResolvedValue(json(full(id)));
    await expect(readWritingTarget(id)).resolves.toMatchObject({ id });
    expect(fetchMock.mock.calls[0][0]).toBe(`https://api.example.test/api/opportunities/${encodeURIComponent(id)}?_release_scope=${encodeURIComponent(PUBLIC_RELEASE_CACHE_VERSION)}`);
  });

  it('preserves long Unicode, CRLF, array order and whitespace without truncation', async () => {
    const target = { ...full(), description_clean: `  ${'完整🧪'.repeat(30_000)}\r\n\n ` };
    fetchMock.mockResolvedValue(json(target));
    expect(await readWritingTarget(target.id)).toEqual(target);
  });

  it('accepts public metadata without internal is_active and does not impose an opportunity_type enum', async () => {
    const target = { ...full(), opportunity_type: 'future-program-kind' };
    fetchMock.mockResolvedValue(json(target));
    expect(await readWritingTarget(target.id)).toEqual(target);
  });

  it('returns historical detail unchanged for the hook to block', async () => {
    const target = { ...full(), target_truth: { ...full().target_truth, actionable: false, listing_state: 'closed', accepting_state: 'not_accepting', reason_code: 'listing_closed' },
      application: { ...full().application, application_url: null }, contact_email_status: 'unavailable' };
    fetchMock.mockResolvedValue(json(target));
    const value = await readWritingTarget(target.id);
    expect(value).toEqual(target); expect(targetPosture(value)).toBe('historical');
  });

  it('accepts the real neutralized unknown-kind detail without restoring stripped offer fields', async () => {
    const { opportunity_type: _type, paid: _paid, location: _location, on_campus: _campus,
      description_clean: _clean, description_raw: _raw, ...identity } = full();
    const target = { ...identity, source_type: 'unreviewed', record_kind: 'unknown', eligibility: {}, application: {},
      target_truth: { ...full().target_truth, actionable: false, listing_state: 'unknown', accepting_state: 'unknown', reason_code: 'record_kind_unverified' } };
    fetchMock.mockResolvedValue(json(target));
    const value = await readWritingTarget(target.id);
    expect(value).toEqual(target); expect(targetPosture(value)).not.toBe('actionable');
    expect(value).not.toHaveProperty('opportunity_type');
  });

  it.each([undefined, null, { actionable: true }, { ...full().target_truth, reason_code: 'future_reason' }])(
    'never upgrades absent, partial or unfamiliar target truth (%j)', async truth => {
      const target = { ...full(), target_truth: truth }; fetchMock.mockResolvedValue(json(target));
      const value = await readWritingTarget(target.id);
      expect(targetPosture(value)).toBe('unknown');
      expect(value).toEqual(JSON.parse(JSON.stringify(target)));
    },
  );

  it.each([
    ['different id', (target: Record<string, unknown>) => { target.id = 'other'; }],
    ['missing identity', (target: Record<string, unknown>) => { delete target.title; }],
    ['wrong organization', (target: Record<string, unknown>) => { target.organization = {}; }],
    ['list card', (target: Record<string, unknown>) => { delete target.metadata; }],
    ['coercible record kind', (target: Record<string, unknown>) => { target.record_kind = ['listing']; }],
    ['malformed metadata', (target: Record<string, unknown>) => { target.metadata = []; }],
    ['malformed keywords', (target: Record<string, unknown>) => { target.keywords = [1]; }],
    ['malformed writing version', (target: Record<string, unknown>) => { target.writing_target_version = 'wt1:' + 'a'.repeat(64) + '\n'; }],
    ['partial eligibility', (target: Record<string, unknown>) => { target.eligibility = { skills_required: [] }; }],
    ['malformed application', (target: Record<string, unknown>) => { target.application = 'apply'; }],
    ['revealed contact', (target: Record<string, unknown>) => { target.contact_email = 'private@example.test'; }],
    ['revealed status', (target: Record<string, unknown>) => { target.contact_email_status = 'revealed'; }],
  ])('rejects %s without reflecting content in the error', async (_name, change) => {
    const target = full() as Record<string, unknown>; change(target); fetchMock.mockResolvedValue(json(target));
    const error = await readWritingTarget('target-1').catch(error => error);
    expect(error).toBeInstanceOf(ApiError); expect(error).toMatchObject({ status: 200, code: 'INVALID_TARGET_RESPONSE', retryable: false });
    expect(error.detail).toBeUndefined(); expect(error.message).not.toContain('private@example.test');
  });

  it.each([null, [], 3, 'target'])('rejects non-object bodies (%j)', async value => {
    fetchMock.mockResolvedValue(json(value));
    await expect(readWritingTarget('target-1')).rejects.toMatchObject({ code: 'INVALID_TARGET_RESPONSE' });
  });

  it('rejects invalid JSON safely', async () => {
    fetchMock.mockResolvedValue(new Response('<html>private error body</html>'));
    await expect(readWritingTarget('target-1')).rejects.toMatchObject({ code: 'INVALID_TARGET_RESPONSE', detail: undefined });
  });

  it.each([404, 409, 429, 500, 503])('keeps HTTP %i and ignores untrusted server codes/details without retry', async status => {
    fetchMock.mockResolvedValue(json({ detail: { code: 'secret@example.test', message: 'private body', retryable: true } }, status));
    const error = await readWritingTarget('target-1').catch(error => error);
    expect(error).toBeInstanceOf(ApiError); expect(error.status).toBe(status); expect(error.code).toBe(`HTTP_${status}`);
    expect(error.message).not.toMatch(/private|secret/); expect(error.detail).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('wraps network failures safely without replay', async () => {
    fetchMock.mockRejectedValue(new Error('secret URL credentials'));
    await expect(readWritingTarget('target-1')).rejects.toMatchObject({ status: 0, code: 'TARGET_READ_FAILED', detail: undefined });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('settles a signal-ignoring fetch at the default deadline, removes listeners, and ignores late delivery', async () => {
    vi.useFakeTimers(); const caller = new AbortController();
    const add = vi.spyOn(caller.signal, 'addEventListener'); const remove = vi.spyOn(caller.signal, 'removeEventListener');
    const fetchResult = pending<Response>(); fetchMock.mockReturnValue(fetchResult.promise);
    const result = readWritingTarget('target-1', { signal: caller.signal });
    const failure = expect(result).rejects.toMatchObject({ status: 408, code: 'TARGET_READ_TIMEOUT' });
    await vi.advanceTimersByTimeAsync(WRITING_TARGET_TIMEOUT_MS - 1);
    expect((fetchMock.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1); await failure;
    expect((fetchMock.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
    expect(remove).toHaveBeenCalledWith('abort', add.mock.calls[0][1]); expect(vi.getTimerCount()).toBe(0);
    const text = vi.fn(async () => JSON.stringify(full())); const cancel = vi.fn(async () => {});
    fetchResult.resolve({ ...bodyResponse(200, text), body: { cancel } } as unknown as Response);
    await Promise.resolve(); expect(cancel).toHaveBeenCalledTimes(1); expect(text).not.toHaveBeenCalled(); expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([200, 404, 503])('bounds a hung HTTP %i body within the same request deadline', async status => {
    vi.useFakeTimers(); const body = pending<string>(); const text = vi.fn(() => body.promise);
    fetchMock.mockResolvedValue(bodyResponse(status, text));
    const result = readWritingTarget('target-1', { timeoutMs: 100 });
    const failure = expect(result).rejects.toMatchObject({ code: 'TARGET_READ_TIMEOUT' });
    await vi.advanceTimersByTimeAsync(99); expect(text).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1); await failure;
    body.resolve(JSON.stringify(full())); await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(0);
  });

  it('does not restart the deadline when headers arrive', async () => {
    vi.useFakeTimers(); const fetchResult = pending<Response>(); fetchMock.mockReturnValue(fetchResult.promise);
    const result = readWritingTarget('target-1', { timeoutMs: 100 });
    const failure = expect(result).rejects.toMatchObject({ code: 'TARGET_READ_TIMEOUT' });
    await vi.advanceTimersByTimeAsync(90);
    fetchResult.resolve(bodyResponse(200, () => new Promise(() => {})));
    await vi.advanceTimersByTimeAsync(10); await failure;
  });

  it.each(['fetch', 'body'] as const)('caller abort promptly settles an ignoring %s without exposing its reason', async phase => {
    vi.useFakeTimers(); const caller = new AbortController(); const add = vi.spyOn(caller.signal, 'addEventListener'); const remove = vi.spyOn(caller.signal, 'removeEventListener');
    fetchMock.mockImplementation(() => phase === 'fetch' ? new Promise(() => {}) : Promise.resolve(bodyResponse(200, () => new Promise(() => {}))));
    const result = readWritingTarget('target-1', { signal: caller.signal });
    const failure = expect(result).rejects.toMatchObject({ name: 'AbortError', message: 'The opportunity check was cancelled.' });
    await Promise.resolve(); caller.abort(new Error('sensitive caller reason')); await failure;
    expect(remove).toHaveBeenCalledWith('abort', add.mock.calls[0][1]); expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(60_000); expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not fetch for an already-aborted caller', async () => {
    const caller = new AbortController(); caller.abort();
    await expect(readWritingTarget('target-1', { signal: caller.signal })).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('cleans caller listeners and deadline on success and non-timeout failure', async () => {
    vi.useFakeTimers(); const caller = new AbortController(); const add = vi.spyOn(caller.signal, 'addEventListener'); const remove = vi.spyOn(caller.signal, 'removeEventListener');
    fetchMock.mockResolvedValueOnce(json(full())).mockResolvedValueOnce(json({}, 404));
    await readWritingTarget('target-1', { signal: caller.signal });
    await expect(readWritingTarget('target-1', { signal: caller.signal })).rejects.toMatchObject({ status: 404 });
    expect(remove.mock.calls.map(call => call[1])).toEqual(add.mock.calls.map(call => call[1]));
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(['', 'x'.repeat(101), 'line\nbreak', '\ud800'])('rejects invalid id before fetch', async id => {
    await expect(readWritingTarget(id)).rejects.toMatchObject({ status: 400, code: 'INVALID_TARGET_ID' });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('writingTargetKey', () => {
  const opportunity = () => full() as unknown as Opportunity;
  it('ignores all object key ordering but preserves full nested content', () => {
    const target = opportunity();
    const reordered = JSON.parse(JSON.stringify(target, (_key, value) => value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).reverse()) : value));
    expect(writingTargetKey(reordered)).toBe(writingTargetKey(target));
    expect(JSON.parse(writingTargetKey(target)!)).toEqual(target);
  });
  it('detects arrays, whitespace, future fields and same-id target changes', () => {
    const target = opportunity(); const key = writingTargetKey(target);
    expect(writingTargetKey({ ...target, keywords: [...target.keywords].reverse() })).not.toBe(key);
    expect(writingTargetKey({ ...target, description_clean: target.description_clean.trim() })).not.toBe(key);
    expect(writingTargetKey({ ...target, organization: 'Changed University' })).not.toBe(key);
    expect(writingTargetKey({ ...target, future: true } as Opportunity)).not.toBe(key);
    expect(target.description_clean).toBe(full().description_clean);
  });
  it('handles absent targets and refuses cyclic non-wire input', () => {
    expect(writingTargetKey(null)).toBeNull();
    const target = opportunity() as Opportunity & { cyclic?: unknown }; target.cyclic = target;
    expect(writingTargetKey(target)).toBeNull();
  });
});
