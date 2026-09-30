import { createHash } from 'node:crypto';
import { StrictMode, type PropsWithChildren } from 'react';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
vi.mock('./supabase', () => ({ getAuthState: vi.fn() }));
import { getAuthState } from './supabase';
import actualApi from './__fixtures__/private-import-target-api.json';
import { createPrivateImportAdoptionController, derivePrivateImportTargetId } from './private-import-adoption';
import { usePrivateImportAdoption } from './use-private-import-adoption';
import { addCustomImport, removeCustomImport } from './custom-imports';
import { advanceOwnerEpoch, captureOwnerToken } from './identity-owner';
import { OWNER, OTHER, setupOwner, deferred } from './application-material.test-utils';
import { PRIVATE_TARGET_TIMEOUT_MS } from './private-import-target-api';
import type { ImportedOpportunity } from './api';
const auth = vi.mocked(getAuthState), fetchMock = vi.fn<typeof fetch>();
const authState = () => ({ user: { id: OWNER }, session: { user: { id: OWNER }, access_token: 'synthetic-only' }, isAnonymous: false, email: null }) as Awaited<ReturnType<typeof getAuthState>>;
const opp = (): ImportedOpportunity => ({ ...structuredClone(actualApi.create.target.opportunity) as ImportedOpportunity, description_raw: '完整原文🙂'.repeat(3000) + '\nLATE_SOURCE_MARKER' });
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const missing = () => json({ detail: { code: 'private_target_not_found' } }, 404);
function result(id: string, revision: number, opportunity: ImportedOpportunity | null = opp()) {
 const key = { id, owner_id: OWNER, revision };
 return { ...structuredClone(actualApi.create), target: { ...structuredClone(actualApi.create.target), ...key, opportunity,
  import_source: opportunity ? actualApi.create.target.import_source : null, deleted_at: opportunity ? null : actualApi.delete.target.deleted_at,
  target_version: 'pit1:' + createHash('sha256').update(JSON.stringify(key)).digest('hex') } };
}
let controller: ReturnType<typeof createPrivateImportAdoptionController>;
beforeEach(async () => { await setupOwner(); auth.mockReset().mockResolvedValue(authState()); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); controller = createPrivateImportAdoptionController(); });
afterEach(() => { controller.cancel(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
async function local() { const saved = await addCustomImport(opp(), captureOwnerToken()); if (!saved.ok) throw new Error(saved.reason); return saved.entry; }
function review() { const s = controller.getState(); if (s.status !== 'review') throw new Error(JSON.stringify(s)); return s.review; }
it('uses production SDK: GET review then one explicit PUT with complete original source/CAS and verified receipt', async () => {
 const entry = await local(), token = captureOwnerToken(); fetchMock.mockResolvedValueOnce(missing()); await controller.prepare(entry, token);
 expect(fetchMock).toHaveBeenCalledOnce(); expect(fetchMock.mock.calls[0][1]?.method ?? 'GET').toBe('GET'); const r = review();
 fetchMock.mockResolvedValueOnce(json(result(r.targetId, 1, entry.opportunity))); await controller.confirm();
 expect(controller.getState()).toMatchObject({ status: 'saved', receipt: result(r.targetId, 1, entry.opportunity) });
 const [url, init] = fetchMock.mock.calls[1]; expect(String(url)).toContain(encodeURIComponent(r.targetId)); expect(init).toMatchObject({ method: 'PUT', cache: 'no-store', redirect: 'error' });
 expect(JSON.parse(init!.body as string)).toEqual({ expected_owner_id: OWNER, expected_revision: 0, opportunity: entry.opportunity });
 expect((JSON.parse(init!.body as string).opportunity.description_raw as string).endsWith('LATE_SOURCE_MARKER')).toBe(true);
 expect(new Headers(init!.headers).get('Authorization')).toBe('Bearer synthetic-only');
});
it('uses fresh full cloud source and refuses stale revision without automatic PUT retry', async () => {
 const entry = await local(), id = await derivePrivateImportTargetId(OWNER, entry.id), cloud = { ...opp(), description_raw: 'Different full cloud original' };
 fetchMock.mockResolvedValueOnce(json(result(id, 6, cloud))); await controller.prepare(entry, captureOwnerToken()); expect(review().cloud?.target.opportunity).toEqual(cloud);
 fetchMock.mockResolvedValueOnce(json({ detail: { code: 'private_target_conflict' } }, 409)); await controller.confirm();
 expect(controller.getState()).toMatchObject({ status: 'error', code: 'conflict', review: { expectedRevision: 6, candidate: entry.opportunity } });
 await controller.confirm(); expect(fetchMock).toHaveBeenCalledTimes(2); expect(JSON.parse(fetchMock.mock.calls[1][1]!.body as string).expected_revision).toBe(6);
 fetchMock.mockResolvedValueOnce(json(result(id, 7, cloud))); await controller.prepare(entry, captureOwnerToken()); expect(review().expectedRevision).toBe(7); expect(fetchMock).toHaveBeenCalledTimes(3);
});
it('preserves an actual SDK tombstone and never attempts recreation', async () => {
 const entry = await local(), id = await derivePrivateImportTargetId(OWNER, entry.id); fetchMock.mockResolvedValueOnce(json(result(id, 3, null)));
 await controller.prepare(entry, captureOwnerToken()); expect(controller.getState()).toMatchObject({ status: 'error', code: 'deleted' }); await controller.confirm(); expect(fetchMock).toHaveBeenCalledOnce();
});
it.each(['owner', 'local', 'close'] as const)('cancels pending save authentication on %s change before any PUT', async mode => {
 const entry = await local(); fetchMock.mockResolvedValueOnce(missing()); await controller.prepare(entry, captureOwnerToken());
 const gate = deferred<Awaited<ReturnType<typeof getAuthState>>>(); auth.mockReturnValueOnce(gate.promise); const saving = controller.confirm();
 await vi.waitFor(() => expect(auth).toHaveBeenCalledTimes(2));
 if (mode === 'owner') advanceOwnerEpoch(OTHER); else if (mode === 'local') await removeCustomImport(entry.id, captureOwnerToken()); else controller.cancel();
 await saving; gate.resolve(authState()); await Promise.resolve(); expect(fetchMock).toHaveBeenCalledOnce();
 expect(controller.getState()).toMatchObject(mode === 'local' ? { status: 'error', code: 'local_missing' } : { status: 'idle' });
});
it('reports SDK timeout without a late auth-dispatched PUT and requires a new review', async () => {
 const entry = await local(); fetchMock.mockResolvedValueOnce(missing()); await controller.prepare(entry, captureOwnerToken());
 vi.useFakeTimers(); const gate = deferred<Awaited<ReturnType<typeof getAuthState>>>(); auth.mockReturnValueOnce(gate.promise); const saving = controller.confirm();
 await vi.advanceTimersByTimeAsync(PRIVATE_TARGET_TIMEOUT_MS); await saving; expect(controller.getState()).toMatchObject({ status: 'error', code: 'timeout' });
 gate.resolve(authState()); await Promise.resolve(); await controller.confirm(); expect(fetchMock).toHaveBeenCalledOnce();
});
it('does not present a fabricated authoritative receipt as saved', async () => {
 const entry = await local(); fetchMock.mockResolvedValueOnce(missing()); await controller.prepare(entry, captureOwnerToken()); const response = result(review().targetId, 1, entry.opportunity);
 fetchMock.mockResolvedValueOnce(json({ ...response, target: { ...response.target, verification: 'verified' } })); await controller.confirm();
 expect(controller.getState()).toMatchObject({ status: 'error', code: 'invalid_receipt', review: { candidate: entry.opportunity } });
});
it('two independent controllers derive the same private ID and CAS permits only one initial creation', async () => {
 const entry = await local(), other = createPrivateImportAdoptionController(); fetchMock.mockImplementation(async (_url, init) => init?.method === 'PUT' ? json({ detail: { code: 'private_target_conflict' } }, 409) : missing());
 await Promise.all([controller.prepare(entry, captureOwnerToken()), other.prepare(entry, captureOwnerToken())]); const second = other.getState();
 if (second.status !== 'review') throw new Error('review missing'); expect(second.review.targetId).toBe(review().targetId);
 fetchMock.mockResolvedValueOnce(json(result(review().targetId, 1, entry.opportunity))); await controller.confirm(); await other.confirm();
 expect(controller.getState().status).toBe('saved'); expect(other.getState()).toMatchObject({ status: 'error', code: 'conflict' }); other.cancel();
});
it('hook mount/StrictMode never uploads; unmount cancels a pending review and permits no late request', async () => {
 const entry = await local(); function Wrapper({ children }: PropsWithChildren) { return <StrictMode>{children}</StrictMode>; }
 const { result: hook, unmount } = renderHook(() => usePrivateImportAdoption(), { wrapper: Wrapper });
 expect(hook.current.state.status).toBe('idle'); expect(auth).not.toHaveBeenCalled(); expect(fetchMock).not.toHaveBeenCalled();
 const gate = deferred<Awaited<ReturnType<typeof getAuthState>>>(); auth.mockReturnValueOnce(gate.promise); let pending!: Promise<void>;
 act(() => { pending = hook.current.prepare(entry, captureOwnerToken()); }); await vi.waitFor(() => expect(auth).toHaveBeenCalledOnce());
 unmount(); await pending; gate.resolve(authState()); await Promise.resolve(); expect(fetchMock).not.toHaveBeenCalled();
});
