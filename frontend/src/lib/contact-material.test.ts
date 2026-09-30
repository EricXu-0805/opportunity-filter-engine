import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { captureOwnerToken, OwnerMismatchError, readUserScopedEntry, USER_SCOPED_PREFIXES, writeUserScopedRaw } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import { parseContactMaterialRecord, snapshotContactMaterialScope, type ContactMaterialScope } from './contact-material';
import { parseApplicationMaterialRecord } from './application-material';
import { beginContactMaterialDeletion, prepareContactMaterialAttempt, readPendingContactMaterialAttempts,
  readPendingContactMaterialDeletions, settleContactMaterialAttempt, settleContactMaterialDeletion } from './contact-material-storage';
import { beginApplicationMaterialDeletion, prepareApplicationMaterialAttempt, readPendingApplicationMaterialAttempts,
  readPendingApplicationMaterialDeletions } from './application-material-storage';
import { OWNER, OTHER, scope as applicationScope, input, file, wire, tombstone, staged, setupOwner, owner, deferred } from './application-material.test-utils';

const scope: ContactMaterialScope = { opportunityId: applicationScope.opportunityId, contactEventId: applicationScope.applicationEventId };
function contactWire(changes: Record<string, unknown> = {}, selected = input()) {
  const { application_event_id, ...rest } = wire(changes, selected);
  return { ...rest, contact_event_id: application_event_id };
}
const record = (changes: Record<string, unknown> = {}, selected = input()) => parseContactMaterialRecord(contactWire(changes, selected), OWNER, scope);
const key = STORAGE_KEYS.CONTACT_MATERIAL_ATTEMPT_PREFIX + encodeURIComponent(JSON.stringify([scope.opportunityId, scope.contactEventId]));
async function prepare(selected = file()) {
  const result = await prepareContactMaterialAttempt(captureOwnerToken(), scope, selected, true);
  if (result.status !== 'ready') throw new Error('unexpected conflict'); return result;
}
beforeEach(setupOwner);
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('keeps the original application key, JSON and lock contract while creating a separate contact attempt for identical IDs and bytes', async () => {
  const locks = vi.spyOn(navigator.locks, 'request');
  const token = captureOwnerToken();
  const app = await prepareApplicationMaterialAttempt(token, applicationScope, file(), true);
  const contact = await prepare();
  if (app.status !== 'ready') throw new Error('unexpected conflict');
  expect(contact.attempt.input.recordId).not.toBe(app.attempt.input.recordId);
  expect(contact.attempt.input.materialId).not.toBe(app.attempt.input.materialId);
  expect(readPendingApplicationMaterialAttempts(token, applicationScope)).toEqual([app.attempt]);
  expect(readPendingContactMaterialAttempts(token, scope)).toEqual([contact.attempt]);
  const legacyKey = 'ofe_application_material_attempt_v1_' + encodeURIComponent(JSON.stringify([applicationScope.opportunityId, applicationScope.applicationEventId]));
  expect(readUserScopedEntry(legacyKey)).toEqual({ status: 'present', value: JSON.stringify({ v: 1, ownerId: OWNER, attempt: app.attempt }) });
  expect(readUserScopedEntry(key)).toEqual({ status: 'present', value: JSON.stringify({ v: 1, ownerId: OWNER, attempt: contact.attempt }) });
  expect(locks.mock.calls.map(([name]) => JSON.parse(String(name)))).toEqual([
    ['ofe-application-material-v1', OWNER, token.generation, applicationScope],
    ['ofe-contact-material-v1', OWNER, token.generation, scope],
  ]);
});
it('registers contact metadata and deletion markers for account cleanup without storing file bytes', async () => {
  const { attempt } = await prepare();
  expect(USER_SCOPED_PREFIXES).toContain(STORAGE_KEYS.CONTACT_MATERIAL_ATTEMPT_PREFIX);
  expect(USER_SCOPED_PREFIXES).toContain(STORAGE_KEYS.CONTACT_MATERIAL_DELETE_PREFIX);
  const entry = readUserScopedEntry(key);
  expect(entry.status).toBe('present'); if (entry.status === 'present') expect(entry.value).not.toContain('%PDF');
  await beginContactMaterialDeletion(captureOwnerToken(), scope, attempt.input.recordId, attempt.input.materialId);
  const token = captureOwnerToken(); await owner(OTHER);
  expect(readPendingContactMaterialAttempts(captureOwnerToken(), scope)).toEqual([]);
  expect(readPendingContactMaterialDeletions(captureOwnerToken(), scope)).toEqual([]);
  await expect(settleContactMaterialAttempt(token, scope, record(tombstone, attempt.input))).rejects.toBeInstanceOf(OwnerMismatchError);
});
it('rejects application scope, both event fields, extra fields and missing scope without making a contact attempt', async () => {
  for (const invalid of [applicationScope, { ...scope, ...applicationScope }, { ...scope, extra: true }, { opportunityId: scope.opportunityId }]) {
    expect(() => snapshotContactMaterialScope(invalid)).toThrowError(expect.objectContaining({ code: 'invalid_input' }));
    await expect(prepareContactMaterialAttempt(captureOwnerToken(), invalid as ContactMaterialScope, file(), true)).rejects.toMatchObject({ code: 'invalid_input' });
  }
  expect(readPendingContactMaterialAttempts(captureOwnerToken(), scope)).toEqual([]);
});
it('rejects a receipt from the other source even when owner, target, event, material and record IDs match', () => {
  expect(() => parseContactMaterialRecord(wire(), OWNER, scope)).toThrowError(expect.objectContaining({ code: 'invalid_receipt' }));
  expect(() => parseApplicationMaterialRecord(contactWire(), OWNER, applicationScope)).toThrowError(expect.objectContaining({ code: 'invalid_receipt' }));
  expect(() => parseContactMaterialRecord({ ...contactWire(), application_event_id: scope.contactEventId }, OWNER, scope)).toThrow();
  for (const changes of [{ owner_id: OTHER }, { opportunity_id: 'other' }, { contact_event_id: OTHER }]) {
    expect(() => parseContactMaterialRecord({ ...contactWire(), ...changes }, OWNER, scope)).toThrow();
  }
});
it('does not accept an application pending JSON copied into the contact namespace', async () => {
  const result = await prepareApplicationMaterialAttempt(captureOwnerToken(), applicationScope, file(), true);
  if (result.status !== 'ready') throw new Error('unexpected conflict');
  writeUserScopedRaw(key, JSON.stringify({ v: 1, ownerId: OWNER, attempt: result.attempt }), captureOwnerToken());
  expect(() => readPendingContactMaterialAttempts(captureOwnerToken(), scope)).toThrowError(expect.objectContaining({ code: 'invalid_pending' }));
});
it('serializes same-contact tabs, preserves original filename, and gives different contacts independent records', async () => {
  const [first, replay] = await Promise.all([prepare(), prepare(file('renamed.pdf'))]);
  expect(replay.attempt).toEqual(first.attempt); expect(replay.reused).toBe(true);
  const other = await prepareContactMaterialAttempt(captureOwnerToken(), { ...scope, contactEventId: OTHER }, file(), true);
  expect(other.status).toBe('ready'); if (other.status === 'ready') expect(other.attempt.input.materialId).not.toBe(first.attempt.input.materialId);
});
it('only a matching terminal receipt retires contact upload and deletion; application intent is untouched', async () => {
  const token = captureOwnerToken(); const { attempt } = await prepare();
  const app = await prepareApplicationMaterialAttempt(token, applicationScope, file(), true);
  if (app.status !== 'ready') throw new Error('unexpected conflict');
  await beginApplicationMaterialDeletion(token, applicationScope, app.attempt.input.recordId, app.attempt.input.materialId);
  await beginContactMaterialDeletion(token, scope, attempt.input.recordId, attempt.input.materialId);
  await expect(settleContactMaterialAttempt(token, scope, record(staged, attempt.input))).rejects.toMatchObject({ code: 'invalid_receipt' });
  await expect(settleContactMaterialDeletion(token, scope, record({}, attempt.input))).rejects.toMatchObject({ code: 'invalid_receipt' });
  expect(await settleContactMaterialAttempt(token, scope, record(tombstone, attempt.input))).toBe(true);
  expect(await settleContactMaterialDeletion(token, scope, record(tombstone, attempt.input))).toBe(true);
  expect(readPendingContactMaterialAttempts(token, scope)).toEqual([]); expect(readPendingContactMaterialDeletions(token, scope)).toEqual([]);
  expect(readPendingApplicationMaterialAttempts(token, applicationScope)).toEqual([app.attempt]);
  expect(readPendingApplicationMaterialDeletions(token, applicationScope)).toHaveLength(1);
});
it('retains a different pending PDF and refuses a mismatched terminal receipt', async () => {
  const { attempt } = await prepare();
  expect(await prepareContactMaterialAttempt(captureOwnerToken(), scope, file('other.pdf', '%PDF-other'), true)).toEqual({ status: 'pending_exists', attempts: [attempt] });
  await expect(settleContactMaterialAttempt(captureOwnerToken(), scope, record({ material_id: OTHER }, attempt.input))).rejects.toMatchObject({ code: 'conflict' });
  expect(readPendingContactMaterialAttempts(captureOwnerToken(), scope)).toEqual([attempt]);
});
it('cannot persist a late file inspection after account change', async () => {
  const gate = deferred<ArrayBuffer>(); const selected = file(); const bytes = await selected.arrayBuffer();
  Object.defineProperty(selected, 'arrayBuffer', { value: () => gate.promise });
  const pending = prepareContactMaterialAttempt(captureOwnerToken(), scope, selected, true);
  const result = expect(pending).rejects.toBeInstanceOf(OwnerMismatchError);
  await owner(OTHER); gate.resolve(bytes); await result;
  expect(readPendingContactMaterialAttempts(captureOwnerToken(), scope)).toEqual([]);
});
