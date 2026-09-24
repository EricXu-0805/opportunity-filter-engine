import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import golden from '../../../tests/fixtures/target-resume-ai-golden.json';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { FULL_TARGET_AI_MAX_BODY_BYTES, type TargetResumeAiRequest } from './target-resume-ai-protocol';
const auth = vi.hoisted(() => ({ token: vi.fn() }));
vi.mock('./supabase', () => ({ getRevealAccessToken: auth.token, refreshRevealAccessToken: vi.fn() }));
vi.mock('./analytics', () => ({ track: vi.fn() }));
import { generateTargetResumeSuggestions } from './api';
const fetchMock = vi.fn();
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((yes) => { resolve = yes; }); return { promise, resolve }; };
const request = () => ({ version: 1, request_id: 'request-one', locale: 'en', draft: structuredClone(golden.draft),
  document_signature: golden.document_signature, selected_unit_ids: golden.manifest.unit_ids } as TargetResumeAiRequest);
beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto); localStorage.clear(); advanceOwnerEpoch('full-ai-owner'); await syncLocalIdentityOwner('full-ai-owner');
  auth.token.mockReset().mockResolvedValue('synthetic-test-token'); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe('full target résumé transport', () => {
  it('sends the complete frozen request once, without private-content truncation or caching', async () => {
    const payload = request(); payload.draft.base_snapshot.resume_text = '完整材料 😀 '.repeat(12000) + 'TAIL-END';
    const expected = structuredClone(payload); const pending = deferred<string>(); auth.token.mockReturnValueOnce(pending.promise);
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ receipt: 'sent' }), { status: 200 }));
    const promise = generateTargetResumeSuggestions(payload, { owner: captureOwnerToken()! });
    payload.draft.base_snapshot.resume_text = 'changed while auth is pending'; pending.resolve('synthetic-test-token'); await promise;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]; expect(url).toBe('/api/tailor/full-target/suggestions');
    expect(JSON.parse(init.body)).toEqual(expected); expect(init).toMatchObject({ method: 'POST', cache: 'no-store', headers: { Authorization: 'Bearer synthetic-test-token' } });
  });
  it('does not send a private draft if the owner switches while auth is pending', async () => {
    const pending = deferred<string>(); auth.token.mockReturnValueOnce(pending.promise);
    const promise = generateTargetResumeSuggestions(request(), { owner: captureOwnerToken()! });
    const assertion = expect(promise).rejects.toMatchObject({ code: 'FULL_TARGET_OWNER_CHANGED' });
    advanceOwnerEpoch('another-owner'); pending.resolve('synthetic-other-token'); await assertion;
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it.each(['before', 'during'] as const)('does not dispatch when cancelled %s auth lookup', async (when) => {
    const controller = new AbortController(); const pending = deferred<string>(); auth.token.mockReturnValueOnce(pending.promise);
    if (when === 'before') controller.abort();
    const promise = generateTargetResumeSuggestions(request(), { owner: captureOwnerToken()!, signal: controller.signal });
    const assertion = expect(promise).rejects.toMatchObject({ code: 'FULL_TARGET_OWNER_CHANGED' });
    controller.abort(); pending.resolve('synthetic-test-token'); await assertion; expect(fetchMock).not.toHaveBeenCalled();
    expect(auth.token).toHaveBeenCalledTimes(when === 'before' ? 0 : 1);
  });
  it('refuses an oversized UTF-8 body before auth or network and preserves the input', async () => {
    const payload = request(); payload.draft.base_snapshot.resume_text = '界'.repeat(Math.ceil(FULL_TARGET_AI_MAX_BODY_BYTES / 3));
    const original = payload.draft.base_snapshot.resume_text;
    await expect(generateTargetResumeSuggestions(payload, { owner: captureOwnerToken()! })).rejects.toMatchObject({ status: 413 });
    expect(auth.token).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled(); expect(payload.draft.base_snapshot.resume_text).toBe(original);
  });
  it('does not replay a retryable provider failure or expose an unstructured body', async () => {
    fetchMock.mockResolvedValue(new Response('PRIVATE PROVIDER BODY', { status: 503, headers: { 'retry-after': '0' } }));
    await expect(generateTargetResumeSuggestions(request(), { owner: captureOwnerToken()! })).rejects.toMatchObject({ status: 503, message: 'The service is busy. Please try again shortly.' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
