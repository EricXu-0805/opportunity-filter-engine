import { normalizeEmailContactContext } from './email-contact-context';
import { parseEmailContactDraftSnapshot, type EmailContactDraftSnapshot } from './email-contact-draft';
import { isOwnerTokenValid, isTokenOwnerStillCurrent, PRIVATE_STORAGE_LOCK, readUserScopedEntry,
  writeUserScopedRaw, type OwnerToken } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import type { EmailContactContext, EmailStyle } from './types';

/** UTF-16 units; failures preserve the old value, never truncate user text. */
export const COLD_EMAIL_DRAFT_LIMITS = {
  subject: 2000, body: 100000, manualRecipient: 2000, pendingEdit: 16000,
  targetVersion: 4096, opportunityId: 1000, total: 262144,
} as const;
export const COLD_EMAIL_DRAFT_LOCK_TIMEOUT_MS = 5000;
export interface ColdEmailDraftSources {
  profile_sig: string | null;
  target_version: string | null;
  contact_sig: string | null;
}
export interface ColdEmailDraftPayload {
  subject: string;
  body: string;
  /** User-entered text only. This field is never a verified address. */
  manualRecipient?: string;
  selectedStyle: EmailStyle;
  pendingEdit: string;
  context: EmailContactContext;
  pendingPanel?: EmailContactDraftSnapshot | null;
  sources: ColdEmailDraftSources;
}
export type ColdEmailDraftReadResult =
  | { status: 'present'; revision: string; draft: ColdEmailDraftPayload }
  | { status: 'missing'; revision: string | null };
export type ColdEmailDraftWriteResult =
  | { status: 'saved' | 'deleted'; revision: string }
  | { status: 'conflict'; current: ColdEmailDraftReadResult };
export type ColdEmailDraftErrorCode = 'owner_changed' | 'storage_unavailable' | 'invalid_draft'
  | 'too_large' | 'lock_timeout' | 'writer_closed';
export class ColdEmailDraftError extends Error {
  constructor(readonly code: ColdEmailDraftErrorCode) {
    super('The email draft could not be safely saved. Your current text is kept.');
    this.name = 'ColdEmailDraftError';
  }
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DIGEST = /^[0-9a-f]{64}$/;
function fail(code: ColdEmailDraftErrorCode): never { throw new ColdEmailDraftError(code); }
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function exact(value: Record<string, unknown>, required: string[], optional: string[] = []): boolean {
  return required.every(key => Object.hasOwn(value, key))
    && Object.keys(value).every(key => required.includes(key) || optional.includes(key));
}
function text(value: unknown, limit: number): value is string {
  if (typeof value !== 'string') return false;
  if (value.length > limit) fail('too_large');
  for (const ch of value) {
    const point = ch.codePointAt(0)!;
    if (point === 0 || (point >= 0xd800 && point <= 0xdfff)) return false;
  }
  return true;
}
/** Reject lossy JSON inputs (undefined, getters, symbols, custom toJSON, cycles). */
function snapshotJson(value: unknown): unknown {
  const seen = new Set<object>(); let units = 0;
  function walk(item: unknown, depth: number): unknown {
    if (depth > 12) fail('invalid_draft');
    if (typeof item === 'string') {
      if (!text(item, COLD_EMAIL_DRAFT_LIMITS.total)) fail('invalid_draft');
      units += item.length; if (units > COLD_EMAIL_DRAFT_LIMITS.total) fail('too_large');
      return item;
    }
    if (item === null || typeof item === 'boolean') return item;
    if (typeof item === 'number' && Number.isFinite(item)) return item;
    if (!record(item) || seen.has(item)) fail('invalid_draft');
    const proto = Object.getPrototypeOf(item);
    if (proto !== Object.prototype && proto !== null) fail('invalid_draft');
    seen.add(item); const out: Record<string, unknown> = {};
    for (const key of Reflect.ownKeys(item)) {
      if (typeof key !== 'string' || !text(key, COLD_EMAIL_DRAFT_LIMITS.total)) fail('invalid_draft');
      const descriptor = Object.getOwnPropertyDescriptor(item, key)!;
      if (!descriptor.enumerable || !Object.hasOwn(descriptor, 'value')) fail('invalid_draft');
      Object.defineProperty(out, key, { enumerable: true, configurable: true, writable: true, value: walk(descriptor.value, depth + 1) });
    }
    seen.delete(item); return out;
  }
  const result = walk(value, 0);
  if (JSON.stringify(result).length > COLD_EMAIL_DRAFT_LIMITS.total) fail('too_large');
  return result;
}
/** Takes an immutable-in-time copy before any lock/digest can yield. */
export function snapshotColdEmailDraft(value: unknown): ColdEmailDraftPayload {
  const item = snapshotJson(value);
  if (!record(item) || !exact(item, ['subject', 'body', 'selectedStyle', 'pendingEdit', 'context', 'sources'], ['manualRecipient', 'pendingPanel'])
    || !text(item.subject, COLD_EMAIL_DRAFT_LIMITS.subject) || !text(item.body, COLD_EMAIL_DRAFT_LIMITS.body)
    || !text(item.pendingEdit, COLD_EMAIL_DRAFT_LIMITS.pendingEdit)
    || !['professional', 'warm', 'friendly', 'lively'].includes(item.selectedStyle as string)
    || (Object.hasOwn(item, 'manualRecipient') && !text(item.manualRecipient, COLD_EMAIL_DRAFT_LIMITS.manualRecipient))
    || !record(item.sources) || !exact(item.sources, ['profile_sig', 'target_version', 'contact_sig'])) fail('invalid_draft');
  for (const key of ['profile_sig', 'contact_sig']) {
    if (item.sources[key] !== null && (typeof item.sources[key] !== 'string' || !DIGEST.test(item.sources[key]))) fail('invalid_draft');
  }
  if (item.sources.target_version !== null && (!text(item.sources.target_version, COLD_EMAIL_DRAFT_LIMITS.targetVersion)
    || !item.sources.target_version.trim())) fail('invalid_draft');
  if (!record(item.context)) fail('invalid_draft');
  // Validate the standard applied-context contract, but preserve its exact text.
  try { normalizeEmailContactContext(item.context); } catch { fail('invalid_draft'); }
  if (item.pendingPanel !== undefined && item.pendingPanel !== null && !parseEmailContactDraftSnapshot(item.pendingPanel)) fail('invalid_draft');
  return item as unknown as ColdEmailDraftPayload;
}
function scope(owner: OwnerToken, opportunityId: string): string {
  if (!text(opportunityId, COLD_EMAIL_DRAFT_LIMITS.opportunityId) || !opportunityId.trim()
    || (owner.uid !== null && (!text(owner.uid, 1000) || !owner.uid.trim()))
    || !Number.isSafeInteger(owner.epoch) || !Number.isSafeInteger(owner.generation)) fail('invalid_draft');
  // The uid is explicit even within the private generation. An authorized
  // anonymous-to-account claim may retain a generation; email drafts do not transfer.
  return STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX + encodeURIComponent(JSON.stringify([owner.uid, opportunityId]));
}
function current(owner: OwnerToken): void {
  if (!isTokenOwnerStillCurrent(owner)) fail('owner_changed');
}
function authorized(owner: OwnerToken): void {
  current(owner);
  if (!isOwnerTokenValid(owner, owner.uid)) fail('storage_unavailable');
}
export function readColdEmailDraft(owner: OwnerToken, opportunityId: string): ColdEmailDraftReadResult {
  const origin = { ...owner }; const key = scope(origin, opportunityId); current(origin);
  const entry = readUserScopedEntry(key);
  current(origin);
  if (entry.status === 'unavailable') fail(entry.reason === 'superseded' ? 'owner_changed' : 'storage_unavailable');
  authorized(origin);
  if (entry.status === 'absent') return { status: 'missing', revision: null };
  if (entry.value.length > COLD_EMAIL_DRAFT_LIMITS.total) fail('too_large');
  let item: unknown;
  try { item = snapshotJson(JSON.parse(entry.value)); } catch (error) {
    if (error instanceof ColdEmailDraftError) throw error;
    fail('invalid_draft');
  }
  if (!record(item) || !exact(item, ['version', 'ownerId', 'opportunityId', 'revision', 'draft']) || item.version !== 1
    || item.ownerId !== origin.uid || item.opportunityId !== opportunityId
    || typeof item.revision !== 'string' || !UUID.test(item.revision)) fail('invalid_draft');
  if (item.draft === null) return { status: 'missing', revision: item.revision };
  const draft = snapshotColdEmailDraft(item.draft);
  if (draft.pendingPanel && draft.pendingPanel.opportunityId !== opportunityId) fail('invalid_draft');
  return { status: 'present', revision: item.revision, draft };
}
async function locked<T>(owner: OwnerToken, fn: () => T): Promise<T> {
  authorized(owner);
  if (typeof navigator === 'undefined' || !navigator.locks?.request) fail('storage_unavailable');
  const controller = new AbortController(); let expired = false; let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => { expired = true; reject(new ColdEmailDraftError('lock_timeout')); controller.abort(); }, COLD_EMAIL_DRAFT_LOCK_TIMEOUT_MS);
  });
  try {
    const operation = navigator.locks.request(PRIVATE_STORAGE_LOCK, { mode: 'exclusive', signal: controller.signal }, () => {
      if (expired) fail('lock_timeout');
      authorized(owner); const result = fn(); authorized(owner); return result;
    });
    const value = await Promise.race([operation, deadline]); authorized(owner); return value;
  } catch (error) {
    current(owner);
    if (error instanceof ColdEmailDraftError) throw error;
    fail('storage_unavailable');
  } finally { clearTimeout(timer); }
}
async function mutate(owner: OwnerToken, opportunityId: string, expectedRevision: string | null,
  draft: ColdEmailDraftPayload | null): Promise<ColdEmailDraftWriteResult> {
  const origin = { ...owner }; const key = scope(origin, opportunityId);
  if (expectedRevision !== null && !UUID.test(expectedRevision)) fail('invalid_draft');
  const copy = draft === null ? null : snapshotColdEmailDraft(draft);
  if (copy?.pendingPanel && copy.pendingPanel.opportunityId !== opportunityId) fail('invalid_draft');
  return locked(origin, () => {
    const previous = readColdEmailDraft(origin, opportunityId);
    if (previous.revision !== expectedRevision) return { status: 'conflict', current: previous };
    let revision: string;
    try { revision = crypto.randomUUID(); } catch { fail('storage_unavailable'); }
    if (!UUID.test(revision) || revision === previous.revision) fail('storage_unavailable');
    const raw = JSON.stringify({ version: 1, ownerId: origin.uid, opportunityId, revision, draft: copy });
    if (raw.length > COLD_EMAIL_DRAFT_LIMITS.total) fail('too_large');
    if (!writeUserScopedRaw(key, raw, origin)) fail('storage_unavailable');
    // Identity gateway verifies exact durable readback. A delete is a retained
    // CAS tombstone: neither a stale save nor stale delete can resurrect/erase a newer draft.
    return { status: copy === null ? 'deleted' : 'saved', revision };
  });
}
export function saveColdEmailDraft(owner: OwnerToken, opportunityId: string, expectedRevision: string | null,
  draft: ColdEmailDraftPayload): Promise<ColdEmailDraftWriteResult> { return mutate(owner, opportunityId, expectedRevision, draft); }
export function deleteColdEmailDraft(owner: OwnerToken, opportunityId: string,
  expectedRevision: string | null): Promise<ColdEmailDraftWriteResult> { return mutate(owner, opportunityId, expectedRevision, null); }

/** One editor's ordered writes; a conflict or failure requires an explicit reread.
 * No debounce. Pending writes are NOT durable; callers guard unload and await
 * flush for normal close. An abrupt browser-process kill is not covered. */
export function createColdEmailDraftWriter(owner: OwnerToken, opportunityId: string, initialRevision: string | null) {
  const origin = { ...owner }; scope(origin, opportunityId);
  let revision = initialRevision; let pending = 0; let closing = false;
  let failure: unknown; let last: ColdEmailDraftWriteResult | null = null;
  let tail: Promise<void> = Promise.resolve();
  function queue(value: ColdEmailDraftPayload | null): Promise<ColdEmailDraftWriteResult> {
    if (closing) {
      const rejected = Promise.reject<ColdEmailDraftWriteResult>(new ColdEmailDraftError('writer_closed'));
      void rejected.catch(() => undefined); return rejected;
    }
    let copy: ColdEmailDraftPayload | null;
    try {
      copy = value === null ? null : snapshotColdEmailDraft(value);
    } catch (error) {
      failure = error; const rejected = Promise.reject<ColdEmailDraftWriteResult>(error); void rejected.catch(() => undefined); return rejected;
    }
    if (value === null) closing = true;
    pending += 1;
    const result = tail.then(async () => {
      if (failure) throw failure;
      if (last?.status === 'conflict') return last;
      const written = await mutate(origin, opportunityId, revision, copy);
      last = written; if (written.status !== 'conflict') revision = written.revision;
      return written;
    });
    tail = result.then(() => { pending -= 1; }, error => { pending -= 1; failure = error; });
    return result;
  }
  return {
    save: (draft: ColdEmailDraftPayload) => queue(draft),
    delete: () => queue(null),
    hasPending: () => pending > 0,
    flush: async (): Promise<ColdEmailDraftWriteResult | null> => {
      // Include writes appended while an earlier one was waiting for its lock.
      let observed: Promise<void>;
      do { observed = tail; await observed; } while (tail !== observed);
      if (failure) throw failure;
      return last;
    },
  };
}
