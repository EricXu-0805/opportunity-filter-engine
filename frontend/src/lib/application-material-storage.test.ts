import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { beginApplicationMaterialDeletion, prepareApplicationMaterialAttempt, readPendingApplicationMaterialAttempts,
  readPendingApplicationMaterialDeletions, settleApplicationMaterialAttempt, settleApplicationMaterialDeletion } from './application-material-storage';
import { captureOwnerToken, OwnerMismatchError, readUserScopedEntry, syncLocalIdentityOwner, USER_SCOPED_PREFIXES, writeUserScopedRaw } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import { OTHER, scope, file, record, tombstone, staged, setupOwner, owner, deferred } from './application-material.test-utils';
const key = STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX + encodeURIComponent(JSON.stringify([scope.opportunityId, scope.applicationEventId]));
beforeEach(setupOwner);
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function prepare(selected = file()) { const result = await prepareApplicationMaterialAttempt(captureOwnerToken(), scope, selected, true);
  expect(result.status).toBe('ready'); if (result.status !== 'ready') throw new Error('unexpected conflict'); return result; }
it('registers both private namespaces and persists metadata only before returning', async () => {
  const { attempt } = await prepare();
  expect(USER_SCOPED_PREFIXES).toContain(STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX);
  expect(USER_SCOPED_PREFIXES).toContain(STORAGE_KEYS.APPLICATION_MATERIAL_DELETE_PREFIX);
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([attempt]);
  const entry = readUserScopedEntry(key); expect(entry.status).toBe('present');
  if (entry.status === 'present') { expect(entry.value).not.toContain('%PDF'); expect(entry.value.length).toBeLessThan(1500); }
  expect(Object.isFrozen(attempt.input)).toBe(true);
});
it.each(['natural', 'second-first'] as const)('serializes competing tabs (%s), reusing exact IDs and the winning filename', async order => {
  const files = [file(), file('renamed.pdf')];
  const bytes = await files[0].arrayBuffer(); const gate = deferred<ArrayBuffer>();
  if (order === 'second-first') Object.defineProperty(files[0], 'arrayBuffer', { value: () => gate.promise });
  const writes = vi.spyOn(localStorage, 'setItem');
  const pending = files.map(selected => prepare(selected));
  // Reading and hashing happen before the lock. Invocation order does not
  // determine which tab first establishes the immutable attempt metadata.
  if (order === 'second-first') { try { await pending[1]; } finally { gate.resolve(bytes); } }
  const [a, b] = await Promise.all(pending);
  expect(a.attempt.input).toEqual(b.attempt.input);
  expect([a.reused, b.reused].sort()).toEqual([false, true]);
  const winner = a.reused ? 1 : 0;
  if (order === 'second-first') expect(winner).toBe(1);
  expect(a.attempt.input.filename).toBe(files[winner].name);
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([a.attempt]);
  expect(writes.mock.calls.filter(([name]) => name.includes(STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX))).toHaveLength(1);
});
it('keeps a different unresolved file and scope separate', async () => {
  const a = await prepare();
  expect(await prepareApplicationMaterialAttempt(captureOwnerToken(), scope, file('x.pdf', '%PDF-different'), true))
    .toEqual({ status: 'pending_exists', attempts: [a.attempt] });
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), { ...scope, opportunityId: 'other' })).toEqual([]);
});
it('settles only a matching receipt, and a stale receipt cannot delete the next upload', async () => {
  const { attempt } = await prepare(); const ready = record({}, attempt.input);
  await expect(settleApplicationMaterialAttempt(captureOwnerToken(), scope, record({ filename: 'other.pdf' }, attempt.input))).rejects.toMatchObject({ code: 'conflict' });
  await expect(settleApplicationMaterialAttempt(captureOwnerToken(), scope, record(staged, attempt.input))).rejects.toMatchObject({ code: 'invalid_receipt' });
  expect(await settleApplicationMaterialAttempt(captureOwnerToken(), scope, ready)).toBe(true);
  const next = await prepare(); expect(next.attempt.input.materialId).not.toBe(attempt.input.materialId);
  expect(await settleApplicationMaterialAttempt(captureOwnerToken(), scope, ready)).toBe(false);
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([next.attempt]);
});
it('opaque deletion intent survives a ready read and tombstone retires both pending kinds', async () => {
  const { attempt } = await prepare(); const { recordId, materialId } = attempt.input;
  const deletion = await beginApplicationMaterialDeletion(captureOwnerToken(), scope, recordId, materialId);
  expect(await beginApplicationMaterialDeletion(captureOwnerToken(), scope, recordId, materialId)).toEqual(deletion);
  const raw = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i)!).filter(k => k.includes(STORAGE_KEYS.APPLICATION_MATERIAL_DELETE_PREFIX)).map(k => localStorage.getItem(k));
  expect(raw).toHaveLength(1); expect(raw[0]).not.toMatch(/filename|byteLength|bytesSha256|résumé/);
  await expect(settleApplicationMaterialDeletion(captureOwnerToken(), scope, record({}, attempt.input))).rejects.toMatchObject({ code: 'invalid_receipt' });
  expect(readPendingApplicationMaterialDeletions(captureOwnerToken(), scope)).toEqual([deletion]);
  const removed = record(tombstone, attempt.input);
  expect(await settleApplicationMaterialAttempt(captureOwnerToken(), scope, removed)).toBe(true);
  expect(await settleApplicationMaterialDeletion(captureOwnerToken(), scope, removed)).toBe(true);
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([]);
});
it('does not hide corrupt or unreadable pending data as an empty list', async () => {
  writeUserScopedRaw(key, '{}', captureOwnerToken());
  expect(() => readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toThrowError(expect.objectContaining({ code: 'invalid_pending' }));
  const realGet = localStorage.getItem.bind(localStorage);
  vi.spyOn(localStorage, 'getItem').mockImplementation(name => { if (name.includes(STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX)) throw new Error('private'); return realGet(name); });
  expect(() => readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toThrow();
});
it('write/no-op/remove failures never claim durable preparation or settlement', async () => {
  const set = localStorage.setItem.bind(localStorage);
  const spy = vi.spyOn(localStorage, 'setItem').mockImplementation((name, value) => { if (!name.includes(STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX)) set(name, value); });
  await expect(prepare()).rejects.toMatchObject({ code: 'storage_unavailable' }); spy.mockRestore();
  const { attempt } = await prepare(); vi.spyOn(localStorage, 'removeItem').mockImplementation(() => {});
  await expect(settleApplicationMaterialAttempt(captureOwnerToken(), scope, record({}, attempt.input))).rejects.toMatchObject({ code: 'storage_unavailable' });
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([attempt]);
});
it('owner transitions clear metadata and opaque deletion markers and reject stale cleanup', async () => {
  const { attempt } = await prepare(); const token = captureOwnerToken();
  await beginApplicationMaterialDeletion(token, scope, attempt.input.recordId, attempt.input.materialId);
  await owner(OTHER);
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([]);
  expect(readPendingApplicationMaterialDeletions(captureOwnerToken(), scope)).toEqual([]);
  await expect(settleApplicationMaterialAttempt(token, scope, record(tombstone, attempt.input))).rejects.toBeInstanceOf(OwnerMismatchError);
});
it('copies the scope before a file read and cannot persist after explicit cancellation', async () => {
  const pending = deferred<ArrayBuffer>(); const chosen = file(); const bytes = await chosen.arrayBuffer();
  Object.defineProperty(chosen, 'arrayBuffer', { value: () => pending.promise });
  const mutable = { ...scope }; const signal = new AbortController();
  const result = prepareApplicationMaterialAttempt(captureOwnerToken(), mutable, chosen, true, signal.signal);
  const check = expect(result).rejects.toMatchObject({ code: 'aborted' }); mutable.opportunityId = 'changed'; signal.abort(); await check; pending.resolve(bytes);
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([]);
});

it('also retires material metadata for a replaced same-account local generation', async () => {
  const { attempt } = await prepare(); const old = captureOwnerToken();
  await beginApplicationMaterialDeletion(old, scope, attempt.input.recordId, attempt.input.materialId);
  const marker = JSON.parse(localStorage.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER)!);
  localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, JSON.stringify({ ...marker, generation: marker.generation + 1, phase: 'switching' }));
  await syncLocalIdentityOwner(old.uid!);
  expect(() => readPendingApplicationMaterialAttempts(old, scope)).toThrow(OwnerMismatchError);
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([]);
  expect(readPendingApplicationMaterialDeletions(captureOwnerToken(), scope)).toEqual([]);
});
