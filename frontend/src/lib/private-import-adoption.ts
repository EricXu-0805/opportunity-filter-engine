/** Explicit adoption of one saved browser import. No background upload. */
import type { ImportedOpportunity } from './api';
import { readCustomImportStorageState, startNewAccountCopy, type CustomImport, type CustomImportWriteFailureReason } from './custom-imports';
import { isOwnerTokenValid, onLocalOwnerStateChange, OwnerMismatchError, type OwnerToken } from './identity-owner';
import { getPrivateImportTarget, savePrivateImportTarget, PrivateTargetError, PRIVATE_TARGET_TIMEOUT_MS,
  type PrivateTargetErrorCode, type PrivateImportReceipt } from './private-import-target-api';

export type PrivateImportAdoptionError = PrivateTargetErrorCode | 'owner_changed' | 'local_changed' | 'local_missing'
  | 'storage_damaged' | 'storage_unavailable';
export interface PrivateImportAdoptionReview {
  local: CustomImport;
  candidate: ImportedOpportunity;
  targetId: string;
  expectedRevision: number;
  cloud: PrivateImportReceipt | null;
}
export type PrivateImportAdoptionState =
  | { status: 'idle' }
  | { status: 'loading'; local: CustomImport }
  | { status: 'review'; review: PrivateImportAdoptionReview }
  | { status: 'saving'; review: PrivateImportAdoptionReview }
  | { status: 'saved'; review: PrivateImportAdoptionReview; receipt: PrivateImportReceipt }
  | { status: 'error'; code: PrivateImportAdoptionError; local: CustomImport | null; review: PrivateImportAdoptionReview | null };
const IDLE: PrivateImportAdoptionState = Object.freeze({ status: 'idle' });
const OWNER_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function freeze<T>(value: T): T {
  if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}
function snapshot<T>(value: T): T { return freeze(JSON.parse(JSON.stringify(value)) as T); }
function same(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  if (Array.isArray(left) || Array.isArray(right)) return Array.isArray(left) && Array.isArray(right)
    && left.length === right.length && left.every((value, index) => same(value, right[index]));
  const a = left as Record<string, unknown>; const b = right as Record<string, unknown>;
  return Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(key => Object.hasOwn(b, key) && same(a[key], b[key]));
}

/** Name-derived UUIDv8, not a content hash or deduplication guarantee. A local
 * recreation or another device's import has a different local entry ID. */
export async function derivePrivateImportTargetId(ownerId: string, localId: string): Promise<string> {
  if (typeof ownerId !== 'string' || !OWNER_ID.test(ownerId) || typeof localId !== 'string' || !localId.trim()
    || Array.from(localId).length > 1000 || /[\u0000\ud800-\udfff]/u.test(localId)) throw new PrivateTargetError('invalid_input');
  try {
    const bytes = new TextEncoder().encode(JSON.stringify(['ofe-private-import-adoption-v1', ownerId, localId]));
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    const uuid = digest.slice(0, 16);
    uuid[6] = (uuid[6] & 0x0f) | 0x80;
    uuid[8] = (uuid[8] & 0x3f) | 0x80;
    const hex = Array.from(uuid, byte => byte.toString(16).padStart(2, '0')).join('');
    return `private-import:${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  } catch { throw new PrivateTargetError('unavailable'); }
}

/** Hashing is local and small, but its async wait must still retire on close,
 * account transition, or deadline. An abandoned digest cannot start a GET. */
function waitForIdentity(promise: Promise<string>, signal: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer: ReturnType<typeof setTimeout>;
    const finish = (value?: string, error?: PrivateTargetError) => {
      if (settled) return;
      settled = true; clearTimeout(timer); signal.removeEventListener('abort', aborted);
      if (error) reject(error); else resolve(value!);
    };
    const aborted = () => finish(undefined, new PrivateTargetError('aborted'));
    timer = setTimeout(() => finish(undefined, new PrivateTargetError('timeout')), PRIVATE_TARGET_TIMEOUT_MS);
    signal.addEventListener('abort', aborted, { once: true });
    if (signal.aborted) aborted();
    promise.then(value => finish(value), error => finish(undefined,
      error instanceof PrivateTargetError ? error : new PrivateTargetError('unavailable')));
  });
}

interface Session {
  owner: OwnerToken;
  local: CustomImport;
  controller: AbortController;
  phase: 'loading' | 'review' | 'saving' | 'saved' | 'error' | 'rekeying';
  review: PrivateImportAdoptionReview | null;
}
function localProblem(session: Session): PrivateImportAdoptionError | null {
  const current = readCustomImportStorageState(session.owner);
  if (current.status === 'unavailable') return current.reason === 'owner_changed' ? 'owner_changed' : 'storage_unavailable';
  if (current.status === 'damaged') return 'storage_damaged';
  const found = current.entries.filter(entry => entry.id === session.local.id);
  if (!found.length) return 'local_missing';
  return found.length === 1 && same(found[0], session.local) ? null : 'local_changed';
}
function rekeyFailure(reason: CustomImportWriteFailureReason): PrivateImportAdoptionError {
  if (reason === 'owner_changed') return 'owner_changed';
  if (reason === 'missing') return 'local_missing';
  if (reason === 'changed' || reason === 'identity_mismatch') return 'local_changed';
  return reason === 'storage_damaged' ? 'storage_damaged' : 'storage_unavailable';
}
function errorCode(error: unknown): PrivateImportAdoptionError {
  if (error instanceof OwnerMismatchError) return 'owner_changed';
  if (error instanceof PrivateTargetError) return error.code;
  return 'unavailable';
}

export function createPrivateImportAdoptionController() {
  let state: PrivateImportAdoptionState = IDLE;
  let active: Session | null = null;
  let stopOwner: (() => void) | null = null;
  const listeners = new Set<() => void>();
  const publish = (next: PrivateImportAdoptionState) => { state = freeze(next); listeners.forEach(listener => listener()); };
  const stopListening = () => {
    stopOwner?.(); stopOwner = null;
    if (typeof window !== 'undefined') window.removeEventListener('storage', changed);
  };
  const cancel = () => {
    const previous = active; active = null; previous?.controller.abort();
    stopListening(); publish(IDLE);
  };
  const fail = (session: Session, code: PrivateImportAdoptionError) => {
    if (active !== session) return;
    if (code === 'owner_changed' || !isOwnerTokenValid(session.owner, session.owner.uid)) { cancel(); return; }
    session.phase = 'error'; session.controller.abort();
    publish({ status: 'error', code, local: session.local, review: session.review });
  };
  function changed() {
    const session = active;
    if (!session) return;
    if (!isOwnerTokenValid(session.owner, session.owner.uid)) { cancel(); return; }
    // The re-key write notifies this tab; its own result is checked below.
    if (session.phase === 'error' || session.phase === 'rekeying') return;
    const problem = localProblem(session);
    if (problem) fail(session, problem);
  }
  const current = (session: Session, phase: Session['phase']) => {
    if (active !== session || session.phase !== phase || session.controller.signal.aborted) return false;
    if (!isOwnerTokenValid(session.owner, session.owner.uid)) { cancel(); return false; }
    const problem = localProblem(session);
    if (problem) { fail(session, problem); return false; }
    return true;
  };

  const prepare = async (entry: CustomImport, owner: OwnerToken): Promise<void> => {
    cancel();
    const origin = { ...owner };
    if (!isOwnerTokenValid(origin, origin.uid)) return;
    let local: CustomImport;
    try { local = snapshot(entry); } catch { publish({ status: 'error', code: 'invalid_input', local: null, review: null }); return; }
    if (!local || typeof local !== 'object' || typeof local.id !== 'string' || !local.id.trim()) {
      publish({ status: 'error', code: 'invalid_input', local: null, review: null }); return;
    }
    const session: Session = { owner: origin, local, controller: new AbortController(), phase: 'loading', review: null };
    active = session;
    stopOwner = onLocalOwnerStateChange(changed);
    if (typeof window !== 'undefined') window.addEventListener('storage', changed);
    if (!origin.uid || !OWNER_ID.test(origin.uid)) { fail(session, 'sign_in_required'); return; }
    if (!current(session, 'loading')) return;
    publish({ status: 'loading', local });
    try {
      const targetId = await waitForIdentity(derivePrivateImportTargetId(origin.uid, local.account_copy_key ?? local.id), session.controller.signal);
      if (!current(session, 'loading')) return;
      const cloud = await getPrivateImportTarget(targetId, { owner: origin, signal: session.controller.signal });
      if (!current(session, 'loading')) return;
      session.review = snapshot({ local, candidate: local.opportunity, targetId, expectedRevision: cloud?.target.revision ?? 0, cloud });
      if (cloud && cloud.target.deleted_at !== null) { fail(session, 'deleted'); return; }
      session.phase = 'review'; publish({ status: 'review', review: session.review });
    } catch (error) {
      if (active === session && session.phase === 'loading') fail(session, errorCode(error));
    }
  };
  const confirm = async (): Promise<void> => {
    const session = active;
    if (!session || !session.review || !current(session, 'review')) return;
    // Phase changes synchronously, before the SDK can wait for authentication.
    // A double click cannot dispatch the same reviewed request twice.
    const review = session.review;
    session.phase = 'saving'; publish({ status: 'saving', review });
    try {
      const receipt = await savePrivateImportTarget(review.targetId, review.candidate, review.expectedRevision,
        { owner: session.owner, signal: session.controller.signal });
      if (!current(session, 'saving')) return;
      session.phase = 'saved'; publish({ status: 'saved', review, receipt: snapshot(receipt) });
    } catch (error) {
      if (active === session && session.phase === 'saving') fail(session, errorCode(error));
    }
  };
  /** A deleted account copy is never restored. Only this explicit action,
   * by the account that saw the deletion, re-keys the browser entry; the new
   * copy still needs its own review and confirmation before any upload. */
  const startNewCopy = async (owner: OwnerToken): Promise<void> => {
    const session = active;
    if (!session || session.phase !== 'error' || state.status !== 'error' || state.code !== 'deleted') return;
    const origin = { ...owner };
    if (origin.uid !== session.owner.uid || !isOwnerTokenValid(origin, origin.uid)) { cancel(); return; }
    session.phase = 'rekeying'; publish({ status: 'loading', local: session.local });
    const result = await startNewAccountCopy(session.local, origin);
    if (active !== session || session.phase !== 'rekeying') return;
    if (!result.ok) { fail(session, rekeyFailure(result.reason)); return; }
    await prepare(result.entry, origin);
  };
  return {
    prepare, confirm, cancel, startNewCopy,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    getState(): PrivateImportAdoptionState {
      // Read-time masking also covers a missed cross-tab notification.
      return active && !isOwnerTokenValid(active.owner, active.owner.uid) ? IDLE : state;
    },
  };
}
