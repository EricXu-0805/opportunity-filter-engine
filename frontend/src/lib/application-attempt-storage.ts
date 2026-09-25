import { contactRecord, validContactTarget } from './contact-ledger';
import { applicationEventMatches, parseApplicationEvent, snapshotApplicationEventInput,
  type ApplicationDraftInput, type ApplicationEvent, type ApplicationEventInput } from './application-ledger';
import { isOwnerTokenValid, OwnerMismatchError, readUserScopedEntry, removeUserScopedRaw, writeUserScopedRaw,
  type OwnerToken } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';

export interface ApplicationPendingAttempt { opportunityId: string; input: ApplicationEventInput }
export type PrepareApplicationAttemptResult =
  | { status: 'ready'; attempt: ApplicationPendingAttempt; reused: boolean }
  | { status: 'pending_exists'; attempts: ApplicationPendingAttempt[] };
export class ApplicationAttemptStorageError extends Error {
  constructor(readonly code: 'unavailable' | 'invalid_pending' | 'receipt_mismatch') {
    super('The pending application record could not be safely updated.'); this.name = 'ApplicationAttemptStorageError';
  }
}
function assertOwner(owner: OwnerToken): asserts owner is OwnerToken & { uid: string } {
  if (!owner.uid || !isOwnerTokenValid(owner, owner.uid)) throw new OwnerMismatchError();
}
function keyFor(opportunityId: string): string {
  if (!validContactTarget(opportunityId)) throw new ApplicationAttemptStorageError('invalid_pending');
  return STORAGE_KEYS.APPLICATION_ATTEMPT_PREFIX + encodeURIComponent(opportunityId);
}
function freezeAttempt(opportunityId: string, input: ApplicationEventInput): ApplicationPendingAttempt {
  return Object.freeze({ opportunityId, input: Object.freeze(input) });
}
/** Only a successful empty array proves that no attempt is pending. There is
 * one unresolved attempt per target, so a new confirmation cannot replace an
 * uncertain request. The storage namespace also isolates owner generations. */
export function readPendingApplicationAttempts(owner: OwnerToken, opportunityId: string): ApplicationPendingAttempt[] {
  assertOwner(owner);
  const entry = readUserScopedEntry(keyFor(opportunityId));
  assertOwner(owner);
  if (entry.status === 'unavailable') throw new ApplicationAttemptStorageError('unavailable');
  if (entry.status === 'absent') return [];
  try {
    const value: unknown = JSON.parse(entry.value);
    if (!contactRecord(value) || Object.keys(value).length !== 4 || value.v !== 1
      || value.ownerId !== owner.uid || value.opportunityId !== opportunityId) throw new Error('invalid');
    return [freezeAttempt(opportunityId, snapshotApplicationEventInput(value.input))];
  } catch { throw new ApplicationAttemptStorageError('invalid_pending'); }
}
async function withAttemptLock<T>(owner: OwnerToken, opportunityId: string, fn: () => T): Promise<T> {
  assertOwner(owner); keyFor(opportunityId);
  if (typeof navigator === 'undefined' || !navigator.locks?.request) throw new ApplicationAttemptStorageError('unavailable');
  try {
    const result = await navigator.locks.request(JSON.stringify(['ofe-application-attempt-v1', owner.uid, owner.generation, opportunityId]),
      { mode: 'exclusive' }, () => { assertOwner(owner); const value = fn(); assertOwner(owner); return value; });
    assertOwner(owner); return result;
  } catch (error) {
    assertOwner(owner);
    if (error instanceof ApplicationAttemptStorageError) throw error;
    throw new ApplicationAttemptStorageError('unavailable');
  }
}
/** Persist a random attempt ID before any RPC. This represents one explicit
 * submission, not a hash of its content: a real repeat with an unknown time
 * gets a new ID after the earlier attempt is settled. Identical outstanding
 * requests in this browser share an ID under Web Locks, including other tabs.
 * No cross-device content deduplication is implied. */
export async function prepareApplicationAttempt(owner: OwnerToken, opportunityId: string,
  draft: ApplicationDraftInput): Promise<PrepareApplicationAttemptResult> {
  const origin = { ...owner }; assertOwner(origin);
  const snapshot = snapshotApplicationEventInput({ ...draft, id: '00000000-0000-0000-0000-000000000000' });
  return withAttemptLock(origin, opportunityId, () => {
    const pending = readPendingApplicationAttempts(origin, opportunityId);
    if (pending.length) {
      return applicationEventMatches(pending[0].input, { ...snapshot, id: pending[0].input.id })
        ? { status: 'ready', attempt: pending[0], reused: true } : { status: 'pending_exists', attempts: pending };
    }
    const input = snapshotApplicationEventInput({ ...snapshot, id: crypto.randomUUID() });
    const value = JSON.stringify({ v: 1, ownerId: origin.uid, opportunityId, input });
    if (!writeUserScopedRaw(keyFor(opportunityId), value, origin)) throw new ApplicationAttemptStorageError('unavailable');
    return { status: 'ready', attempt: freezeAttempt(opportunityId, input), reused: false };
  });
}
/** Clear only an exact verified receipt. A delayed receipt for an older ID
 * cannot remove a newer attempt, and a changed payload cannot be settled. */
export async function settleApplicationAttempt(owner: OwnerToken, opportunityId: string, event: ApplicationEvent): Promise<boolean> {
  const origin = { ...owner }; assertOwner(origin);
  let receipt: ApplicationEvent;
  try { receipt = parseApplicationEvent({ event_id: event.id, device_id: event.deviceId, opportunity_id: event.opportunityId,
    channel: event.channel, destination: event.destination, actual_submitted_at: event.submittedAt, notes: event.notes,
    result_note: event.resultNote, next_step: event.nextStep, confirmed_at: event.confirmedAt,
    confirmation_source: event.confirmationSource }, origin.uid, opportunityId); }
  catch { throw new ApplicationAttemptStorageError('receipt_mismatch'); }
  return withAttemptLock(origin, opportunityId, () => {
    const pending = readPendingApplicationAttempts(origin, opportunityId)[0];
    if (!pending || pending.input.id !== receipt.id) return false;
    if (!applicationEventMatches(receipt, pending.input)) throw new ApplicationAttemptStorageError('receipt_mismatch');
    if (!removeUserScopedRaw(keyFor(opportunityId), origin)) throw new ApplicationAttemptStorageError('unavailable');
    return true;
  });
}
