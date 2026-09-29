import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
vi.mock('./private-import-target-api', () => ({ getPrivateImportTarget: vi.fn(), savePrivateImportTarget: vi.fn(), PRIVATE_TARGET_TIMEOUT_MS: 30_000, PrivateTargetError: class extends Error { constructor(readonly code: string) { super(code); } } }));
import { createPrivateImportAdoptionController, derivePrivateImportTargetId } from './private-import-adoption';
import { getPrivateImportTarget, savePrivateImportTarget, PrivateTargetError, type PrivateImportReceipt } from './private-import-target-api';
import { addCustomImport, removeCustomImport, type CustomImport } from './custom-imports';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { writeLocalStorageJSON } from './use-local-storage-json';
import { STORAGE_KEYS } from './storage-keys';
import { deferred } from './application-material.test-utils';
import type { ImportedOpportunity } from './api';
const OWNER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', OTHER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const get = vi.mocked(getPrivateImportTarget), save = vi.mocked(savePrivateImportTarget);
const opportunity = (): ImportedOpportunity => ({ source: 'text_parser', source_url: '', url: '', title: 'Own source', description_raw: 'Complete local source 中文🙂'.repeat(600), extra_fields: { description_source: 'pasted_text', suggested_skills: ['SQL'], retained: { note: 'Full metadata' } } });
let controller: ReturnType<typeof createPrivateImportAdoptionController>;
beforeEach(async () => { vi.stubGlobal('crypto', webcrypto); advanceOwnerEpoch(OWNER); await syncLocalIdentityOwner(OWNER); get.mockReset().mockResolvedValue(null); save.mockReset(); controller = createPrivateImportAdoptionController(); });
afterEach(() => { controller.cancel(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function local(title?: string) { const saved = await addCustomImport({ ...opportunity(), ...(title ? { title } : {}) }, captureOwnerToken()); if (!saved.ok) throw new Error(saved.reason); return saved.entry; }
function receipt(id: string, revision = 1, value: ImportedOpportunity | null = opportunity()): PrivateImportReceipt { return { version: 1, replayed: false, target: { id, owner_id: OWNER, revision, opportunity: value, import_source: value ? { version: 1, description_source: 'pasted_text', ai_input_scope: 'unknown', llm_enriched: false } : null, created_at: '2026-09-28T10:00:00Z', updated_at: '2026-09-28T10:00:00Z', deleted_at: value ? null : '2026-09-28T10:00:00Z', target_scope: 'private_import', verification: 'unverified', target_version: 'pit1:' + 'a'.repeat(64) } }; }
function review() { const s = controller.getState(); if (s.status !== 'review') throw new Error(JSON.stringify(s)); return s.review; }
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
it('derives a stable owner/local identity without reading or uploading', async () => {
 const id = await derivePrivateImportTargetId(OWNER, 'custom-stable'); expect(id).toBe('private-import:c900b940-665a-818f-b7b9-dfd7ad2ba2d7'); expect(id).toMatch(/^private-import:[a-f0-9]{8}-[a-f0-9]{4}-8[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
 expect(await derivePrivateImportTargetId(OWNER, 'custom-stable')).toBe(id); expect(await derivePrivateImportTargetId(OWNER, 'custom-new')).not.toBe(id); expect(await derivePrivateImportTargetId(OTHER, 'custom-stable')).not.toBe(id); expect(get).not.toHaveBeenCalled(); expect(save).not.toHaveBeenCalled(); expect(controller.getState()).toEqual({ status: 'idle' });
});
it.each(['', '\u0000', '\ud800', 'x'.repeat(1001)])('rejects unusable local identity', async id => { await expect(derivePrivateImportTargetId(OWNER, id)).rejects.toMatchObject({ code: 'invalid_input' }); expect(get).not.toHaveBeenCalled(); expect(save).not.toHaveBeenCalled(); });
it('prepares complete source/metadata without a write and freezes review snapshots', async () => {
 const entry = await local(); await controller.prepare(entry, captureOwnerToken()); expect(review().local).toEqual(entry); expect(review().candidate).toEqual(entry.opportunity); expect(review().cloud).toBeNull(); expect(review().expectedRevision).toBe(0); expect(Object.isFrozen(review().candidate.extra_fields.retained)).toBe(true); expect(get).toHaveBeenCalledOnce(); expect(save).not.toHaveBeenCalled();
});
it('freezes caller entry/token while GET waits and confirms only once', async () => {
 const entry = await local(), original = copy(entry), token = captureOwnerToken(), origin = { ...token }; const gate = deferred<PrivateImportReceipt | null>(); get.mockReturnValueOnce(gate.promise);
 const pending = controller.prepare(entry, token); await vi.waitFor(() => expect(get).toHaveBeenCalledOnce()); entry.opportunity.description_raw = 'mutated caller'; token.uid = OTHER; gate.resolve(null); await pending;
 const r = review(); expect(r.local).toEqual(original); const saving = deferred<PrivateImportReceipt>(); save.mockReturnValueOnce(saving.promise);
 const one = controller.confirm(), two = controller.confirm(); expect(save).toHaveBeenCalledOnce(); expect(save.mock.calls[0].slice(0, 3)).toEqual([r.targetId, original.opportunity, 0]); expect(save.mock.calls[0][3].owner).toEqual(origin);
 saving.resolve(receipt(r.targetId, 1, original.opportunity)); await Promise.all([one, two]); expect(controller.getState().status).toBe('saved'); await controller.confirm(); expect(save).toHaveBeenCalledOnce();
});
it('fetches the complete cloud original and exact revision anew for each review', async () => {
 const entry = await local(), id = await derivePrivateImportTargetId(OWNER, entry.id); const old = receipt(id, 7, { ...opportunity(), description_raw: 'Cloud original', extra_fields: { retained: 'cloud only' } }); get.mockResolvedValueOnce(old); await controller.prepare(entry, captureOwnerToken());
 expect(review()).toMatchObject({ targetId: id, expectedRevision: 7, cloud: old, candidate: entry.opportunity }); save.mockResolvedValueOnce(receipt(id, 8, entry.opportunity)); await controller.confirm(); expect(save.mock.calls[0][2]).toBe(7);
 get.mockResolvedValueOnce(receipt(id, 8)); await controller.prepare(entry, captureOwnerToken()); expect(review().expectedRevision).toBe(8); expect(get).toHaveBeenCalledTimes(2);
});
it('keeps deleted cloud ID tombstoned across cancellation/new controller', async () => {
 const entry = await local(), id = await derivePrivateImportTargetId(OWNER, entry.id); get.mockResolvedValue(receipt(id, 4, null)); await controller.prepare(entry, captureOwnerToken()); expect(controller.getState()).toMatchObject({ status: 'error', code: 'deleted', review: { targetId: id, expectedRevision: 4 } }); await controller.confirm(); controller.cancel(); controller = createPrivateImportAdoptionController(); await controller.prepare(entry, captureOwnerToken()); await controller.confirm(); expect(get.mock.calls.map(call => call[0])).toEqual([id, id]); expect(save).not.toHaveBeenCalled();
});
it.each(['missing', 'changed', 'damaged'] as const)('refuses %s local storage before GET', async mode => {
 const entry = await local(); if (mode === 'missing') await removeCustomImport(entry.id, captureOwnerToken()); if (mode === 'changed') writeLocalStorageJSON(STORAGE_KEYS.CUSTOM_IMPORTS, [{ ...entry, legacy_note: 'changed' }], captureOwnerToken()); if (mode === 'damaged') writeLocalStorageJSON(STORAGE_KEYS.CUSTOM_IMPORTS, { invalid: true }, captureOwnerToken());
 await controller.prepare(entry, captureOwnerToken()); expect(controller.getState()).toMatchObject({ status: 'error', code: mode === 'damaged' ? 'storage_damaged' : `local_${mode}` }); expect(get).not.toHaveBeenCalled();
});
it('detects nested metadata changes before confirmation without adopting newer candidate', async () => {
 const entry = await local(); await controller.prepare(entry, captureOwnerToken()); const changed = copy(entry); changed.opportunity.extra_fields.retained = { note: 'new fact' }; writeLocalStorageJSON(STORAGE_KEYS.CUSTOM_IMPORTS, [changed], captureOwnerToken()); await controller.confirm(); expect(controller.getState()).toMatchObject({ status: 'error', code: 'local_changed', review: { local: entry } }); expect(save).not.toHaveBeenCalled();
});
it.each(['get', 'save'] as const)('retires %s on local deletion and ignores late success', async phase => {
 const entry = await local(), id = await derivePrivateImportTargetId(OWNER, entry.id), gate = deferred<PrivateImportReceipt>(); let pending: Promise<void>;
 if (phase === 'get') { get.mockReturnValueOnce(gate.promise); pending = controller.prepare(entry, captureOwnerToken()); await vi.waitFor(() => expect(get).toHaveBeenCalledOnce()); } else { await controller.prepare(entry, captureOwnerToken()); save.mockReturnValueOnce(gate.promise); pending = controller.confirm(); }
 await removeCustomImport(entry.id, captureOwnerToken()); expect(controller.getState()).toMatchObject({ status: 'error', code: 'local_missing' }); gate.resolve(receipt(id)); await pending; expect(controller.getState()).toMatchObject({ status: 'error', code: 'local_missing' });
});
it.each(['get', 'save'] as const)('clears old-account display/results during %s', async phase => {
 const entry = await local(), gate = deferred<PrivateImportReceipt>(); let pending: Promise<void>;
 if (phase === 'get') { get.mockReturnValueOnce(gate.promise); pending = controller.prepare(entry, captureOwnerToken()); await vi.waitFor(() => expect(get).toHaveBeenCalledOnce()); } else { await controller.prepare(entry, captureOwnerToken()); save.mockReturnValueOnce(gate.promise); pending = controller.confirm(); }
 advanceOwnerEpoch(OTHER); expect(controller.getState()).toEqual({ status: 'idle' }); gate.resolve(receipt('unused')); await pending; expect(controller.getState()).toEqual({ status: 'idle' });
});
it('prevents an older prepare replacing a newer review', async () => {
 const first = await local('First'), next = await local('Next'), gate = deferred<PrivateImportReceipt | null>(); get.mockReturnValueOnce(gate.promise); const previous = controller.prepare(first, captureOwnerToken()); await vi.waitFor(() => expect(get).toHaveBeenCalledOnce()); await controller.prepare(next, captureOwnerToken()); const id = review().targetId; gate.resolve(null); await previous; expect(review()).toMatchObject({ targetId: id, local: next }); expect(get.mock.calls[0][1].signal?.aborted).toBe(true); expect(save).not.toHaveBeenCalled();
});
it('close cancels pending work and cannot dispatch late confirm', async () => {
 const entry = await local(), gate = deferred<PrivateImportReceipt | null>(); get.mockReturnValueOnce(gate.promise); const pending = controller.prepare(entry, captureOwnerToken()); await vi.waitFor(() => expect(get).toHaveBeenCalledOnce()); controller.cancel(); gate.resolve(null); await pending; await controller.confirm(); expect(controller.getState()).toEqual({ status: 'idle' }); expect(save).not.toHaveBeenCalled();
});
it.each(['conflict', 'timeout', 'invalid_receipt', 'unavailable', 'sign_in_required'] as const)('preserves %s review and requires fresh GET before retry', async code => {
 const entry = await local(); await controller.prepare(entry, captureOwnerToken()); const old = review(); save.mockRejectedValueOnce(new PrivateTargetError(code)); await controller.confirm(); expect(controller.getState()).toMatchObject({ status: 'error', code, local: entry, review: old }); await controller.confirm(); expect(save).toHaveBeenCalledOnce(); expect(get).toHaveBeenCalledOnce(); get.mockResolvedValueOnce(receipt(old.targetId, 9)); await controller.prepare(entry, captureOwnerToken()); expect(review().expectedRevision).toBe(9); expect(save).toHaveBeenCalledOnce();
});
it('shows dependency failure without transmitting source', async () => { const entry = await local(); vi.stubGlobal('crypto', {}); await controller.prepare(entry, captureOwnerToken()); expect(controller.getState()).toMatchObject({ status: 'error', code: 'unavailable', local: entry }); expect(get).not.toHaveBeenCalled(); expect(save).not.toHaveBeenCalled(); });
it('rejects malformed input and stale owner tokens before cloud GET', async () => { await controller.prepare(null as unknown as CustomImport, captureOwnerToken()); expect(controller.getState()).toMatchObject({ status: 'error', code: 'invalid_input' }); const entry = await local(), stale = captureOwnerToken(); advanceOwnerEpoch(OTHER); await controller.prepare(entry, stale); expect(controller.getState()).toEqual({ status: 'idle' }); expect(get).not.toHaveBeenCalled(); });

it.each(['owner', 'close', 'timeout'] as const)('retires a pending hash on %s without a late GET', async mode => {
 const entry = await local(), gate = deferred<ArrayBuffer>(); vi.useFakeTimers();
 vi.stubGlobal('crypto', { subtle: { digest: () => gate.promise } });
 const pending = controller.prepare(entry, captureOwnerToken());
 if (mode === 'owner') advanceOwnerEpoch(OTHER); else if (mode === 'close') controller.cancel(); else await vi.advanceTimersByTimeAsync(30_000);
 await pending; expect(controller.getState()).toMatchObject(mode === 'timeout' ? { status: 'error', code: 'timeout' } : { status: 'idle' });
 gate.resolve(new ArrayBuffer(32)); await Promise.resolve(); expect(get).not.toHaveBeenCalled(); expect(save).not.toHaveBeenCalled(); vi.useRealTimers();
});
