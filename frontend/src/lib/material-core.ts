import { APPLICATION_EVENT_UUID } from './application-ledger';
import { contactRecord, contactTimestamp, validContactTarget } from './contact-ledger';
import { isOwnerTokenValid, onLocalOwnerStateChange, OwnerMismatchError, type OwnerToken } from './identity-owner';

export const MATERIAL_MAX_BYTES = 64 * 1024 * 1024;
export const MATERIAL_MIME = 'application/pdf' as const;
export type MaterialEventField = 'applicationEventId' | 'contactEventId';
export type MaterialScope<F extends MaterialEventField> = { opportunityId: string } & Record<F, string>;
export interface MaterialInput {
  materialId: string;
  recordId: string;
  filename: string;
  mimeType: typeof MATERIAL_MIME;
  byteLength: number;
  bytesSha256: string;
  attested: true;
}
export interface MaterialAttempt<F extends MaterialEventField> { scope: MaterialScope<F>; input: MaterialInput }
export interface MaterialDeletion<F extends MaterialEventField> { scope: MaterialScope<F>; recordId: string; materialId: string }
export type MaterialErrorCode = 'invalid_input' | 'invalid_pdf' | 'file_too_large' | 'file_mismatch'
  | 'unavailable' | 'invalid_receipt' | 'conflict' | 'sign_in_required' | 'aborted' | 'timeout'
  | 'not_found' | 'deleted' | 'storage_unavailable' | 'invalid_pending' | 'expired' | 'not_ready' | 'busy' | 'not_configured';
export class MaterialError extends Error {
  constructor(readonly code: MaterialErrorCode) {
    super(code === 'file_mismatch' ? 'Select the same PDF to continue this request.'
      : code === 'sign_in_required' ? 'Sign in to manage submitted materials.'
        : code === 'file_too_large' ? 'This PDF exceeds the file size limit.'
          : 'The material request could not be completed.');
    this.name = 'MaterialError';
  }
}
export function materialExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}
export function materialUuid(value: unknown): value is string { return typeof value === 'string' && APPLICATION_EVENT_UUID.test(value); }
export function assertMaterialOwner(owner: OwnerToken): asserts owner is OwnerToken & { uid: string } {
  if (!owner.uid || !isOwnerTokenValid(owner, owner.uid)) throw new OwnerMismatchError();
}
export function validMaterialFilename(value: unknown): value is string {
  return typeof value === 'string' && !!value.trim() && Array.from(value).length <= 200
    && /\.pdf$/i.test(value) && !/[\u0000-\u001f\u007f-\u009f\ud800-\udfff/\\]/u.test(value);
}
export function snapshotMaterialInput(value: unknown): MaterialInput {
  if (!contactRecord(value) || !materialExactKeys(value, ['materialId', 'recordId', 'filename', 'mimeType', 'byteLength', 'bytesSha256', 'attested'])
    || !materialUuid(value.materialId) || !materialUuid(value.recordId) || !validMaterialFilename(value.filename)
    || value.mimeType !== MATERIAL_MIME || !Number.isSafeInteger(value.byteLength)
    || (value.byteLength as number) < 1 || (value.byteLength as number) > MATERIAL_MAX_BYTES
    || typeof value.bytesSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.bytesSha256) || value.attested !== true) {
    throw new MaterialError('invalid_input');
  }
  return Object.freeze({ materialId: value.materialId, recordId: value.recordId, filename: value.filename,
    mimeType: MATERIAL_MIME, byteLength: value.byteLength as number, bytesSha256: value.bytesSha256, attested: true });
}
export function materialInputMatches(left: MaterialInput, right: MaterialInput): boolean {
  return Object.keys(left).every(key => left[key as keyof MaterialInput] === right[key as keyof MaterialInput]);
}
export interface MaterialOperation {
  signal: AbortSignal;
  assertActive: () => void;
  wait: <T>(pending: Promise<T>) => Promise<T>;
}
/** One deadline covers authentication and all body/hash awaits; an abandoned
 * caller cannot release a late result even if an underlying promise ignores abort. */
export async function withMaterialOperation<T>(owner: OwnerToken, signal: AbortSignal | undefined,
  run: (operation: MaterialOperation) => Promise<T>, timeoutMs = 120_000): Promise<T> {
  const origin = { ...owner }; assertMaterialOwner(origin);
  const controller = new AbortController(); let timedOut = false;
  const cancel = () => controller.abort();
  const assertActive = () => {
    assertMaterialOwner(origin);
    if (timedOut) throw new MaterialError('timeout');
    if (controller.signal.aborted) throw new MaterialError('aborted');
  };
  if (signal?.aborted) controller.abort(); else signal?.addEventListener('abort', cancel, { once: true });
  const retire = () => { if (!isOwnerTokenValid(origin, origin.uid)) controller.abort(); };
  const stopOwner = onLocalOwnerStateChange(retire);
  if (typeof window !== 'undefined') window.addEventListener('storage', retire);
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  const wait = <V,>(pending: Promise<V>): Promise<V> => new Promise((resolve, reject) => {
    const stop = () => { try { assertActive(); reject(new MaterialError('aborted')); } catch (error) { reject(error); } };
    if (controller.signal.aborted) { pending.catch(() => {}); stop(); return; }
    controller.signal.addEventListener('abort', stop, { once: true });
    pending.then(value => { try { assertActive(); resolve(value); } catch (error) { reject(error); } }, reject)
      .finally(() => controller.signal.removeEventListener('abort', stop));
  });
  try { assertActive(); const value = await run({ signal: controller.signal, assertActive, wait }); assertActive(); return value; }
  catch (error) {
    assertActive();
    if (error instanceof MaterialError || error instanceof OwnerMismatchError) throw error;
    throw new MaterialError('unavailable');
  } finally {
    clearTimeout(timer); stopOwner(); signal?.removeEventListener('abort', cancel);
    // Early header/receipt rejection must also stop an unread fetch body.
    controller.abort();
    if (typeof window !== 'undefined') window.removeEventListener('storage', retire);
  }
}
/** The browser performs bounded local checks; the backend must independently
 * validate PDF structure and hash the actual uploaded bytes before archiving. */
export async function inspectMaterialFile(owner: OwnerToken, file: File, signal?: AbortSignal): Promise<{
  filename: string; mimeType: typeof MATERIAL_MIME; byteLength: number; bytesSha256: string;
}> {
  const origin = { ...owner }; assertMaterialOwner(origin);
  if (!file || typeof file.arrayBuffer !== 'function' || !validMaterialFilename(file.name)
    || !Number.isSafeInteger(file.size) || file.size < 1) throw new MaterialError('invalid_pdf');
  if (file.size > MATERIAL_MAX_BYTES) throw new MaterialError('file_too_large');
  if (file.type && ![MATERIAL_MIME, 'application/octet-stream'].includes(file.type.toLowerCase())) throw new MaterialError('invalid_pdf');
  const filename = file.name; const byteLength = file.size;
  return withMaterialOperation(origin, signal, async operation => {
    const bytes = new Uint8Array(await operation.wait(file.arrayBuffer()));
    if (bytes.byteLength !== byteLength || new TextDecoder().decode(bytes.subarray(0, 5)) !== '%PDF-') throw new MaterialError('invalid_pdf');
    const hash = new Uint8Array(await operation.wait(crypto.subtle.digest('SHA-256', bytes)));
    return Object.freeze({ filename, mimeType: MATERIAL_MIME, byteLength,
      bytesSha256: Array.from(hash, byte => byte.toString(16).padStart(2, '0')).join('') });
  });
}

export interface MaterialRecordFields {
  version: 1;
  ownerId: string;
  materialId: string;
  recordId: string;
  status: 'staged' | 'ready' | 'deleted';
  filename: string | null;
  mimeType: typeof MATERIAL_MIME | null;
  byteLength: number | null;
  bytesSha256: string | null;
  stagedAt: string;
  archivedAt: string | null;
  linkedAt: string | null;
  deletedAt: string | null;
  confirmationSource: 'user_reported';
}
export interface MaterialCursor { linkedAt: string; recordId: string }
export type MaterialRecord<F extends MaterialEventField> = MaterialRecordFields & MaterialScope<F>;
export interface MaterialPage<F extends MaterialEventField> { items: MaterialRecord<F>[]; nextCursor: MaterialCursor | null }
function materialTime(value: unknown): bigint | null {
  return typeof value === 'string' && /(?:Z|\+00:00)$/.test(value) ? contactTimestamp(value) : null;
}
export function materialRecordMatchesInput(record: MaterialRecordFields, input: MaterialInput): boolean {
  return record.materialId === input.materialId && record.recordId === input.recordId && record.status === 'ready'
    && record.filename === input.filename && record.mimeType === input.mimeType
    && record.byteLength === input.byteLength && record.bytesSha256 === input.bytesSha256;
}
export function snapshotMaterialCursor(value: unknown): MaterialCursor {
  if (!contactRecord(value) || !materialExactKeys(value, ['linkedAt', 'recordId']) || !materialUuid(value.recordId)
    || materialTime(value.linkedAt) === null) throw new MaterialError('invalid_input');
  return Object.freeze({ linkedAt: value.linkedAt as string, recordId: value.recordId });
}
export function materialBefore(left: MaterialCursor, right: MaterialCursor): boolean {
  const a = materialTime(left.linkedAt)!; const b = materialTime(right.linkedAt)!;
  return a < b || (a === b && left.recordId < right.recordId);
}

/** Each source has exact keys at the browser, pending-storage and wire boundaries.
 * A contact ID is never renamed into an application ID to reuse validation. */
export function createMaterialCodec<F extends MaterialEventField>(field: F, wireField: 'application_event_id' | 'contact_event_id') {
  function snapshotMaterialScope(value: unknown): MaterialScope<F> {
    if (!contactRecord(value) || !materialExactKeys(value, ['opportunityId', field])
      || !validContactTarget(value.opportunityId) || !materialUuid(value[field])) throw new MaterialError('invalid_input');
    return Object.freeze({ opportunityId: value.opportunityId, [field]: value[field] }) as MaterialScope<F>;
  }
  function snapshotMaterialAttempt(value: unknown): MaterialAttempt<F> {
    if (!contactRecord(value) || !materialExactKeys(value, ['scope', 'input'])) throw new MaterialError('invalid_input');
    return Object.freeze({ scope: snapshotMaterialScope(value.scope), input: snapshotMaterialInput(value.input) });
  }
  function parseMaterialRecord(value: unknown, ownerId: string, scope: MaterialScope<F>,
    recordId?: string): MaterialRecord<F> {
    const fail = (): never => { throw new MaterialError('invalid_receipt'); };
    if (!contactRecord(value) || !materialExactKeys(value, ['version', 'owner_id', 'opportunity_id', wireField, 'material_id',
      'record_id', 'status', 'filename', 'mime_type', 'byte_length', 'bytes_sha256', 'staged_at', 'archived_at', 'linked_at', 'deleted_at', 'confirmation_source'])
      || value.version !== 1 || value.owner_id !== ownerId || !materialUuid(value.owner_id)
      || value.opportunity_id !== scope.opportunityId || value[wireField] !== scope[field]
      || !materialUuid(value.record_id) || !materialUuid(value.material_id) || (recordId !== undefined && value.record_id !== recordId)
      || value.confirmation_source !== 'user_reported' || !['staged', 'ready', 'deleted'].includes(value.status as string)) return fail();
    const staged = materialTime(value.staged_at); if (staged === null) return fail();
    const archived = value.archived_at === null ? null : materialTime(value.archived_at);
    const linked = value.linked_at === null ? null : materialTime(value.linked_at);
    const deleted = value.deleted_at === null ? null : materialTime(value.deleted_at);
    if ((value.archived_at !== null && archived === null) || (value.linked_at !== null && linked === null)
      || (value.deleted_at !== null && deleted === null) || (archived === null) !== (linked === null)
      || (archived !== null && archived < staged) || (linked !== null && linked < archived!)
      || (deleted !== null && deleted < (linked ?? staged))) return fail();
    if (value.status === 'deleted') {
      if (deleted === null || value.filename !== null || value.mime_type !== null || value.byte_length !== null || value.bytes_sha256 !== null) return fail();
    } else {
      if (!validMaterialFilename(value.filename) || value.mime_type !== MATERIAL_MIME
        || !Number.isSafeInteger(value.byte_length) || (value.byte_length as number) < 1 || (value.byte_length as number) > MATERIAL_MAX_BYTES
        || deleted !== null) return fail();
      if (value.status === 'staged') {
        if (archived !== null || linked !== null || value.bytes_sha256 !== null) return fail();
      } else if (archived === null || linked === null || typeof value.bytes_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.bytes_sha256)) return fail();
    }
    return Object.freeze({ ...snapshotMaterialScope(scope), version: 1, ownerId,
      materialId: value.material_id, recordId: value.record_id, status: value.status as MaterialRecord<F>['status'],
      filename: value.filename as string | null, mimeType: value.mime_type as typeof MATERIAL_MIME | null,
      byteLength: value.byte_length as number | null, bytesSha256: value.bytes_sha256 as string | null,
      stagedAt: value.staged_at as string, archivedAt: value.archived_at as string | null,
      linkedAt: value.linked_at as string | null, deletedAt: value.deleted_at as string | null, confirmationSource: 'user_reported' });
  }
  function snapshotMaterialRecord(value: MaterialRecord<F>, ownerId: string,
    scope: MaterialScope<F>, recordId?: string): MaterialRecord<F> {
    if (!contactRecord(value) || !materialExactKeys(value, ['version', 'ownerId', 'opportunityId', field, 'materialId', 'recordId',
      'status', 'filename', 'mimeType', 'byteLength', 'bytesSha256', 'stagedAt', 'archivedAt', 'linkedAt', 'deletedAt', 'confirmationSource'])) {
      throw new MaterialError('invalid_receipt');
    }
    return parseMaterialRecord({ version: value.version, owner_id: value.ownerId, opportunity_id: value.opportunityId,
      [wireField]: value[field], material_id: value.materialId, record_id: value.recordId, status: value.status,
      filename: value.filename, mime_type: value.mimeType, byte_length: value.byteLength, bytes_sha256: value.bytesSha256,
      staged_at: value.stagedAt, archived_at: value.archivedAt, linked_at: value.linkedAt, deleted_at: value.deletedAt,
      confirmation_source: value.confirmationSource }, ownerId, scope, recordId);
  }
  return Object.freeze({ field, wireField, snapshotScope: snapshotMaterialScope, snapshotAttempt: snapshotMaterialAttempt,
    parseRecord: parseMaterialRecord, snapshotRecord: snapshotMaterialRecord });
}
export type MaterialCodec<F extends MaterialEventField> = ReturnType<typeof createMaterialCodec<F>>;
