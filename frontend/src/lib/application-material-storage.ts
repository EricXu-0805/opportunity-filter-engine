import { contactRecord } from './contact-ledger';
import { enumerateUserScopedKeys, readUserScopedEntry, removeUserScopedRaw, writeUserScopedRaw, type OwnerToken } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import { ApplicationMaterialError, assertApplicationMaterialOwner, inspectApplicationMaterialFile, applicationMaterialRecordMatchesInput, snapshotApplicationMaterialRecord,
  materialExactKeys, materialUuid, snapshotApplicationMaterialAttempt, snapshotApplicationMaterialInput, snapshotApplicationMaterialScope,
  type ApplicationMaterialAttempt, type ApplicationMaterialDeletion, type ApplicationMaterialScope, type ApplicationMaterialRecord } from './application-material';

export type PrepareApplicationMaterialResult =
  | { status: 'ready'; attempt: ApplicationMaterialAttempt; reused: boolean }
  | { status: 'pending_exists'; attempts: ApplicationMaterialAttempt[] };
function scopeSuffix(scope: ApplicationMaterialScope): string { return encodeURIComponent(JSON.stringify([scope.opportunityId, scope.applicationEventId])); }
function uploadKey(scope: ApplicationMaterialScope): string { return STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX + scopeSuffix(scope); }
function deletePrefix(scope: ApplicationMaterialScope): string { return STORAGE_KEYS.APPLICATION_MATERIAL_DELETE_PREFIX + scopeSuffix(scope) + '_'; }
async function locked<T>(owner: OwnerToken, scope: ApplicationMaterialScope, fn: () => T): Promise<T> {
  assertApplicationMaterialOwner(owner);
  if (typeof navigator === 'undefined' || !navigator.locks?.request) throw new ApplicationMaterialError('storage_unavailable');
  try {
    const value = await navigator.locks.request(JSON.stringify(['ofe-application-material-v1', owner.uid, owner.generation, scope]),
      { mode: 'exclusive' }, () => { assertApplicationMaterialOwner(owner); const result = fn(); assertApplicationMaterialOwner(owner); return result; });
    assertApplicationMaterialOwner(owner); return value;
  } catch (error) {
    assertApplicationMaterialOwner(owner);
    if (error instanceof ApplicationMaterialError) throw error;
    throw new ApplicationMaterialError('storage_unavailable');
  }
}
export function readPendingApplicationMaterialAttempts(owner: OwnerToken, value: ApplicationMaterialScope): ApplicationMaterialAttempt[] {
  assertApplicationMaterialOwner(owner); const scope = snapshotApplicationMaterialScope(value);
  const entry = readUserScopedEntry(uploadKey(scope)); assertApplicationMaterialOwner(owner);
  if (entry.status === 'unavailable') throw new ApplicationMaterialError('storage_unavailable');
  if (entry.status === 'absent') return [];
  try {
    const row: unknown = JSON.parse(entry.value);
    if (!contactRecord(row) || !materialExactKeys(row, ['v', 'ownerId', 'attempt']) || row.v !== 1 || row.ownerId !== owner.uid) throw new Error('invalid');
    const attempt = snapshotApplicationMaterialAttempt(row.attempt);
    if (attempt.scope.opportunityId !== scope.opportunityId || attempt.scope.applicationEventId !== scope.applicationEventId) throw new Error('invalid');
    return [attempt];
  } catch { throw new ApplicationMaterialError('invalid_pending'); }
}
/** Only metadata is durable. File bytes stay in the selected immutable File;
 * after a reload the user selects the same bytes again, preserving original metadata. */
export async function prepareApplicationMaterialAttempt(owner: OwnerToken, value: ApplicationMaterialScope,
  file: File, attested: true, signal?: AbortSignal): Promise<PrepareApplicationMaterialResult> {
  const origin = { ...owner }; assertApplicationMaterialOwner(origin); const scope = snapshotApplicationMaterialScope(value);
  if (attested !== true) throw new ApplicationMaterialError('invalid_input');
  const fileInfo = await inspectApplicationMaterialFile(origin, file, signal); assertApplicationMaterialOwner(origin);
  return locked(origin, scope, () => {
    if (signal?.aborted) throw new ApplicationMaterialError('aborted');
    const pending = readPendingApplicationMaterialAttempts(origin, scope);
    if (pending.length) {
      const original = pending[0].input;
      return original.byteLength === fileInfo.byteLength && original.bytesSha256 === fileInfo.bytesSha256
        ? { status: 'ready', attempt: pending[0], reused: true } : { status: 'pending_exists', attempts: pending };
    }
    const input = snapshotApplicationMaterialInput({ ...fileInfo, materialId: crypto.randomUUID(), recordId: crypto.randomUUID(), attested: true });
    const attempt = Object.freeze({ scope, input });
    if (!writeUserScopedRaw(uploadKey(scope), JSON.stringify({ v: 1, ownerId: origin.uid, attempt }), origin)) throw new ApplicationMaterialError('storage_unavailable');
    return { status: 'ready', attempt, reused: false };
  });
}
export function readPendingApplicationMaterialDeletions(owner: OwnerToken, value: ApplicationMaterialScope): ApplicationMaterialDeletion[] {
  assertApplicationMaterialOwner(owner); const scope = snapshotApplicationMaterialScope(value); const prefix = deletePrefix(scope);
  const keys = enumerateUserScopedKeys(prefix); assertApplicationMaterialOwner(owner);
  if (keys.status === 'unavailable') throw new ApplicationMaterialError('storage_unavailable');
  return keys.keys.map(key => {
    const entry = readUserScopedEntry(key); assertApplicationMaterialOwner(owner);
    if (entry.status !== 'present') throw new ApplicationMaterialError('storage_unavailable');
    try {
      const row: unknown = JSON.parse(entry.value);
      if (!contactRecord(row) || !materialExactKeys(row, ['v', 'ownerId', 'scope', 'recordId', 'materialId'])
        || row.v !== 1 || row.ownerId !== owner.uid || !materialUuid(row.recordId) || !materialUuid(row.materialId)
        || key !== prefix + row.recordId) throw new Error('invalid');
      const selected = snapshotApplicationMaterialScope(row.scope);
      if (selected.opportunityId !== scope.opportunityId || selected.applicationEventId !== scope.applicationEventId) throw new Error('invalid');
      return Object.freeze({ scope: selected, recordId: row.recordId, materialId: row.materialId });
    } catch { throw new ApplicationMaterialError('invalid_pending'); }
  });
}
/** This marker intentionally excludes filenames, hashes and byte counts. A
 * successful read showing the file still exists does not cancel deletion intent. */
export async function beginApplicationMaterialDeletion(owner: OwnerToken, value: ApplicationMaterialScope,
  recordId: string, materialId: string): Promise<ApplicationMaterialDeletion> {
  const origin = { ...owner }; assertApplicationMaterialOwner(origin); const scope = snapshotApplicationMaterialScope(value);
  if (!materialUuid(recordId) || !materialUuid(materialId)) throw new ApplicationMaterialError('invalid_input');
  return locked(origin, scope, () => {
    const existing = readPendingApplicationMaterialDeletions(origin, scope).find(item => item.recordId === recordId);
    if (existing) { if (existing.materialId !== materialId) throw new ApplicationMaterialError('conflict'); return existing; }
    const deletion = Object.freeze({ scope, recordId, materialId });
    if (!writeUserScopedRaw(deletePrefix(scope) + recordId, JSON.stringify({ v: 1, ownerId: origin.uid, ...deletion }), origin)) throw new ApplicationMaterialError('storage_unavailable');
    return deletion;
  });
}

/** Ready receipts match every frozen field. A tombstone intentionally lacks
 * private metadata, so it can retire only the same owner/scope/material/record IDs. */
export async function settleApplicationMaterialAttempt(owner: OwnerToken, value: ApplicationMaterialScope,
  valueRecord: ApplicationMaterialRecord): Promise<boolean> {
  const origin = { ...owner }; assertApplicationMaterialOwner(origin); const scope = snapshotApplicationMaterialScope(value);
  const record = snapshotApplicationMaterialRecord(valueRecord, origin.uid, scope);
  if (record.status === 'staged') throw new ApplicationMaterialError('invalid_receipt');
  return locked(origin, scope, () => {
    const pending = readPendingApplicationMaterialAttempts(origin, scope)[0];
    if (!pending || pending.input.recordId !== record.recordId) return false;
    if (pending.input.materialId !== record.materialId
      || (record.status === 'ready' && !applicationMaterialRecordMatchesInput(record, pending.input))) throw new ApplicationMaterialError('conflict');
    if (!removeUserScopedRaw(uploadKey(scope), origin)) throw new ApplicationMaterialError('storage_unavailable');
    return true;
  });
}
export async function settleApplicationMaterialDeletion(owner: OwnerToken, value: ApplicationMaterialScope,
  valueRecord: ApplicationMaterialRecord): Promise<boolean> {
  const origin = { ...owner }; assertApplicationMaterialOwner(origin); const scope = snapshotApplicationMaterialScope(value);
  const record = snapshotApplicationMaterialRecord(valueRecord, origin.uid, scope);
  if (record.status !== 'deleted') throw new ApplicationMaterialError('invalid_receipt');
  return locked(origin, scope, () => {
    const pending = readPendingApplicationMaterialDeletions(origin, scope).find(item => item.recordId === record.recordId);
    if (!pending) return false;
    if (pending.materialId !== record.materialId) throw new ApplicationMaterialError('conflict');
    if (!removeUserScopedRaw(deletePrefix(scope) + record.recordId, origin)) throw new ApplicationMaterialError('storage_unavailable');
    return true;
  });
}
