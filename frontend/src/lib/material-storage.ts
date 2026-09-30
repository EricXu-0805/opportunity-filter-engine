import { contactRecord } from './contact-ledger';
import { enumerateUserScopedKeys, readUserScopedEntry, removeUserScopedRaw, writeUserScopedRaw, type OwnerToken } from './identity-owner';
import { MaterialError, assertMaterialOwner, inspectMaterialFile, materialRecordMatchesInput,
  materialExactKeys, materialUuid, snapshotMaterialInput, type MaterialCodec, type MaterialEventField,
  type MaterialAttempt, type MaterialDeletion, type MaterialScope, type MaterialRecord } from './material-core';

export function createMaterialStorage<F extends MaterialEventField>(codec: MaterialCodec<F>,
  config: { uploadPrefix: string; deletePrefix: string; lockName: string }) {
  const { snapshotScope: snapshotMaterialScope, snapshotAttempt: snapshotMaterialAttempt, snapshotRecord: snapshotMaterialRecord } = codec;
  type PrepareResult =
    | { status: 'ready'; attempt: MaterialAttempt<F>; reused: boolean }
    | { status: 'pending_exists'; attempts: MaterialAttempt<F>[] };
  function scopeSuffix(scope: MaterialScope<F>): string { return encodeURIComponent(JSON.stringify([scope.opportunityId, scope[codec.field]])); }
  function uploadKey(scope: MaterialScope<F>): string { return config.uploadPrefix + scopeSuffix(scope); }
  function deletePrefix(scope: MaterialScope<F>): string { return config.deletePrefix + scopeSuffix(scope) + '_'; }
  async function locked<T>(owner: OwnerToken, scope: MaterialScope<F>, fn: () => T): Promise<T> {
    assertMaterialOwner(owner);
    if (typeof navigator === 'undefined' || !navigator.locks?.request) throw new MaterialError('storage_unavailable');
    try {
      const value = await navigator.locks.request(JSON.stringify([config.lockName, owner.uid, owner.generation, scope]),
        { mode: 'exclusive' }, () => { assertMaterialOwner(owner); const result = fn(); assertMaterialOwner(owner); return result; });
      assertMaterialOwner(owner); return value;
    } catch (error) {
      assertMaterialOwner(owner);
      if (error instanceof MaterialError) throw error;
      throw new MaterialError('storage_unavailable');
    }
  }
  function readPendingMaterialAttempts(owner: OwnerToken, value: MaterialScope<F>): MaterialAttempt<F>[] {
    assertMaterialOwner(owner); const scope = snapshotMaterialScope(value);
    const entry = readUserScopedEntry(uploadKey(scope)); assertMaterialOwner(owner);
    if (entry.status === 'unavailable') throw new MaterialError('storage_unavailable');
    if (entry.status === 'absent') return [];
    try {
      const row: unknown = JSON.parse(entry.value);
      if (!contactRecord(row) || !materialExactKeys(row, ['v', 'ownerId', 'attempt']) || row.v !== 1 || row.ownerId !== owner.uid) throw new Error('invalid');
      const attempt = snapshotMaterialAttempt(row.attempt);
      if (attempt.scope.opportunityId !== scope.opportunityId || attempt.scope[codec.field] !== scope[codec.field]) throw new Error('invalid');
      return [attempt];
    } catch { throw new MaterialError('invalid_pending'); }
  }
  /** Only metadata is durable. File bytes stay in the selected immutable File;
   * after a reload the user selects the same bytes again, preserving original metadata. */
  async function prepareMaterialAttempt(owner: OwnerToken, value: MaterialScope<F>,
    file: File, attested: true, signal?: AbortSignal): Promise<PrepareResult> {
    const origin = { ...owner }; assertMaterialOwner(origin); const scope = snapshotMaterialScope(value);
    if (attested !== true) throw new MaterialError('invalid_input');
    const fileInfo = await inspectMaterialFile(origin, file, signal); assertMaterialOwner(origin);
    return locked(origin, scope, () => {
      if (signal?.aborted) throw new MaterialError('aborted');
      const pending = readPendingMaterialAttempts(origin, scope);
      if (pending.length) {
        const original = pending[0].input;
        return original.byteLength === fileInfo.byteLength && original.bytesSha256 === fileInfo.bytesSha256
          ? { status: 'ready', attempt: pending[0], reused: true } : { status: 'pending_exists', attempts: pending };
      }
      const input = snapshotMaterialInput({ ...fileInfo, materialId: crypto.randomUUID(), recordId: crypto.randomUUID(), attested: true });
      const attempt = Object.freeze({ scope, input });
      if (!writeUserScopedRaw(uploadKey(scope), JSON.stringify({ v: 1, ownerId: origin.uid, attempt }), origin)) throw new MaterialError('storage_unavailable');
      return { status: 'ready', attempt, reused: false };
    });
  }
  function readPendingMaterialDeletions(owner: OwnerToken, value: MaterialScope<F>): MaterialDeletion<F>[] {
    assertMaterialOwner(owner); const scope = snapshotMaterialScope(value); const prefix = deletePrefix(scope);
    const keys = enumerateUserScopedKeys(prefix); assertMaterialOwner(owner);
    if (keys.status === 'unavailable') throw new MaterialError('storage_unavailable');
    return keys.keys.map(key => {
      const entry = readUserScopedEntry(key); assertMaterialOwner(owner);
      if (entry.status !== 'present') throw new MaterialError('storage_unavailable');
      try {
        const row: unknown = JSON.parse(entry.value);
        if (!contactRecord(row) || !materialExactKeys(row, ['v', 'ownerId', 'scope', 'recordId', 'materialId'])
          || row.v !== 1 || row.ownerId !== owner.uid || !materialUuid(row.recordId) || !materialUuid(row.materialId)
          || key !== prefix + row.recordId) throw new Error('invalid');
        const selected = snapshotMaterialScope(row.scope);
        if (selected.opportunityId !== scope.opportunityId || selected[codec.field] !== scope[codec.field]) throw new Error('invalid');
        return Object.freeze({ scope: selected, recordId: row.recordId, materialId: row.materialId });
      } catch { throw new MaterialError('invalid_pending'); }
    });
  }
  /** This marker intentionally excludes filenames, hashes and byte counts. A
   * successful read showing the file still exists does not cancel deletion intent. */
  async function beginMaterialDeletion(owner: OwnerToken, value: MaterialScope<F>,
    recordId: string, materialId: string): Promise<MaterialDeletion<F>> {
    const origin = { ...owner }; assertMaterialOwner(origin); const scope = snapshotMaterialScope(value);
    if (!materialUuid(recordId) || !materialUuid(materialId)) throw new MaterialError('invalid_input');
    return locked(origin, scope, () => {
      const existing = readPendingMaterialDeletions(origin, scope).find(item => item.recordId === recordId);
      if (existing) { if (existing.materialId !== materialId) throw new MaterialError('conflict'); return existing; }
      const deletion = Object.freeze({ scope, recordId, materialId });
      if (!writeUserScopedRaw(deletePrefix(scope) + recordId, JSON.stringify({ v: 1, ownerId: origin.uid, ...deletion }), origin)) throw new MaterialError('storage_unavailable');
      return deletion;
    });
  }
  
  /** Ready receipts match every frozen field. A tombstone intentionally lacks
   * private metadata, so it can retire only the same owner/scope/material/record IDs. */
  async function settleMaterialAttempt(owner: OwnerToken, value: MaterialScope<F>,
    valueRecord: MaterialRecord<F>): Promise<boolean> {
    const origin = { ...owner }; assertMaterialOwner(origin); const scope = snapshotMaterialScope(value);
    const record = snapshotMaterialRecord(valueRecord, origin.uid, scope);
    if (record.status === 'staged') throw new MaterialError('invalid_receipt');
    return locked(origin, scope, () => {
      const pending = readPendingMaterialAttempts(origin, scope)[0];
      if (!pending || pending.input.recordId !== record.recordId) return false;
      if (pending.input.materialId !== record.materialId
        || (record.status === 'ready' && !materialRecordMatchesInput(record, pending.input))) throw new MaterialError('conflict');
      if (!removeUserScopedRaw(uploadKey(scope), origin)) throw new MaterialError('storage_unavailable');
      return true;
    });
  }
  async function settleMaterialDeletion(owner: OwnerToken, value: MaterialScope<F>,
    valueRecord: MaterialRecord<F>): Promise<boolean> {
    const origin = { ...owner }; assertMaterialOwner(origin); const scope = snapshotMaterialScope(value);
    const record = snapshotMaterialRecord(valueRecord, origin.uid, scope);
    if (record.status !== 'deleted') throw new MaterialError('invalid_receipt');
    return locked(origin, scope, () => {
      const pending = readPendingMaterialDeletions(origin, scope).find(item => item.recordId === record.recordId);
      if (!pending) return false;
      if (pending.materialId !== record.materialId) throw new MaterialError('conflict');
      if (!removeUserScopedRaw(deletePrefix(scope) + record.recordId, origin)) throw new MaterialError('storage_unavailable');
      return true;
    });
  }
  return { readPendingMaterialAttempts, prepareMaterialAttempt, readPendingMaterialDeletions, beginMaterialDeletion, settleMaterialAttempt, settleMaterialDeletion };
}
export type MaterialStorage<F extends MaterialEventField> = ReturnType<typeof createMaterialStorage<F>>;
