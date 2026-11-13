import { createHash, webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import golden from '../../../tests/fixtures/private-resume-context-v5-golden.json';
import { getPrivateResumeContext } from './private-resume';
import { PRIVATE_TARGET_TIMEOUT_MS } from './private-import-target-api';
import type { PrivateResumeContext } from './private-resume-context';
import { targetResumeContextSignature } from './target-resume';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
vi.mock('./supabase', () => ({ getAuthState: vi.fn() }));
import { getAuthState } from './supabase';

const auth = vi.mocked(getAuthState), fetchMock = vi.fn<typeof fetch>();
const clone = <T,>(value: T): T => structuredClone(value);
const uid = golden.receipt.context.private_source.owner_id, id = golden.receipt.context.opportunity_id;
const other = 'b1000000-0000-4000-8000-000000000001';
const context = () => clone(golden.receipt.context) as PrivateResumeContext;
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
const read = () => getPrivateResumeContext(id, { owner: captureOwnerToken() });
const pit1 = (target: PrivateResumeContext) => 'pit1:' + createHash('sha256').update(JSON.stringify({ id: target.opportunity_id,
  owner_id: target.private_source.owner_id, revision: target.private_source.revision })).digest('hex');
beforeEach(async () => {
  vi.stubGlobal('crypto', webcrypto); localStorage.clear(); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  auth.mockReset().mockResolvedValue({ user: { id: uid }, session: { user: { id: uid }, access_token: 'synthetic-token' }, isAnonymous: false, email: null } as Awaited<ReturnType<typeof getAuthState>>);
  fetchMock.mockReset().mockRejectedValue(new Error('Unexpected transport')); vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('private résumé source receipt', () => {
  it('consumes the actual route receipt with the owner and version in the query', async () => {
    fetchMock.mockResolvedValueOnce(json(golden.receipt));
    const result = await getPrivateResumeContext(id, { owner: captureOwnerToken(), expectedVersion: context().private_source.source_version });
    expect(result).toEqual(context());
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/private-import-targets/${encodeURIComponent(id)}/resume-context?expected_owner_id=${uid}&expected_target_version=pit1%3A`);
    expect(options).toMatchObject({ cache: 'no-store', redirect: 'error' }); expect(options?.body).toBeUndefined();
    expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer synthetic-token'); expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('refuses a self-consistent receipt for another account', async () => {
    const value = clone(golden.receipt), target = value.context as PrivateResumeContext;
    target.private_source.owner_id = other; target.private_source.source_version = pit1(target);
    value.target_signature = await targetResumeContextSignature(target);
    fetchMock.mockResolvedValueOnce(json(value));
    await expect(read()).rejects.toMatchObject({ code: 'invalid_receipt' });
  });

  it('refuses a self-consistent receipt for another import', async () => {
    const value = clone(golden.receipt), target = value.context as PrivateResumeContext;
    target.opportunity_id = 'private-import:b2000000-0000-4000-8000-000000000001'; target.private_source.source_version = pit1(target);
    value.target_signature = await targetResumeContextSignature(target);
    fetchMock.mockResolvedValueOnce(json(value));
    await expect(read()).rejects.toMatchObject({ code: 'invalid_receipt' });
  });

  it('refuses a self-consistent receipt for a revision other than the expected one', async () => {
    const expected = context().private_source.source_version;
    const value = clone(golden.receipt), target = value.context as PrivateResumeContext;
    target.private_source.revision = 2; target.private_source.source_version = pit1(target);
    value.target_signature = await targetResumeContextSignature(target);
    fetchMock.mockResolvedValueOnce(json(value));
    await expect(getPrivateResumeContext(id, { owner: captureOwnerToken(), expectedVersion: expected })).rejects.toMatchObject({ code: 'invalid_receipt' });
  });

  it.each(['version', 'authority', 'scope', 'extra', 'missing', 'requirements', 'criteria', 'hash', 'binding'])('refuses a mismatched or promoted receipt (%s)', async fault => {
    const value: Record<string, unknown> = clone(golden.receipt), source = value.context as Record<string, unknown>;
    const binding = source.private_source as Record<string, unknown>;
    if (fault === 'version') value.version = 2;
    if (fault === 'authority') value.verification = 'verified';
    if (fault === 'scope') value.target_scope = 'public';
    if (fault === 'extra') value.extra = true;
    if (fault === 'missing') delete value.target_signature;
    if (fault === 'requirements') source.requirements = ['Guessed skill'];
    if (fault === 'criteria') source.criteria = {};
    if (fault === 'hash') value.target_signature = 'v1:sha256:' + '0'.repeat(64);
    if (fault === 'binding') binding.source_version = 'pit1:' + '0'.repeat(64);
    fetchMock.mockResolvedValueOnce(json(value));
    await expect(read()).rejects.toMatchObject({ code: 'invalid_receipt' }); expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('refuses an invalid expected version before any request', async () => {
    await expect(getPrivateResumeContext(id, { owner: captureOwnerToken(), expectedVersion: 'pit1:abc' })).rejects.toMatchObject({ code: 'invalid_input' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('reports a source over the draft limit as too_large, not as a corrupt receipt', async () => {
    const value = clone(golden.receipt); value.context.description = 'x'.repeat(2 * 1024 * 1024);
    fetchMock.mockResolvedValueOnce(json(value));
    await expect(read()).rejects.toMatchObject({ code: 'too_large' });
  });

  it('retires an in-flight read when the account changes', async () => {
    let resolve!: (value: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>(r => { resolve = r; }));
    const pending = read(); const refused = expect(pending).rejects.toThrow();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    advanceOwnerEpoch(other); await syncLocalIdentityOwner(other); resolve(json(golden.receipt)); await refused;
  });

  it('keeps the read deadline active through source verification', async () => {
    vi.useFakeTimers();
    vi.spyOn(crypto.subtle, 'digest').mockReturnValue(new Promise(() => {}));
    fetchMock.mockResolvedValueOnce(json(golden.receipt));
    const pending = read(); const refused = expect(pending).rejects.toMatchObject({ code: 'timeout' });
    await vi.advanceTimersByTimeAsync(PRIVATE_TARGET_TIMEOUT_MS + 1); await refused;
  });
});
