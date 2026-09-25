import { File as NodeFile } from 'node:buffer';
import { webcrypto, createHash } from 'node:crypto';
import { vi } from 'vitest';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import { parseApplicationMaterialRecord, type ApplicationMaterialInput } from './application-material';
export const OWNER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
export const OTHER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
export const scope = { opportunityId: 'opp / one', applicationEventId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc' };
export const PDF = '%PDF-1.4\nexact submitted bytes\n%%EOF';
export const hash = (value: string | Uint8Array) => createHash('sha256').update(value).digest('hex');
export const file = (name = 'résumé.pdf', content = PDF) => new NodeFile([content], name, { type: 'application/pdf' }) as unknown as File;
export function input(): ApplicationMaterialInput { return { materialId: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
  recordId: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', filename: 'résumé.pdf', mimeType: 'application/pdf', byteLength: Buffer.byteLength(PDF), bytesSha256: hash(PDF), attested: true }; }
export function wire(change: Record<string, unknown> = {}, value = input()) {
  return { version: 1, owner_id: OWNER, opportunity_id: scope.opportunityId, application_event_id: scope.applicationEventId,
    material_id: value.materialId, record_id: value.recordId, status: 'ready', filename: value.filename, mime_type: value.mimeType,
    byte_length: value.byteLength, bytes_sha256: value.bytesSha256, staged_at: '2026-09-25T12:00:00.000001Z',
    archived_at: '2026-09-25T12:00:00.000002Z', linked_at: '2026-09-25T12:00:00.000003Z', deleted_at: null,
    confirmation_source: 'user_reported', ...change };
}
export const record = (change: Record<string, unknown> = {}, value = input()) => parseApplicationMaterialRecord(wire(change, value), OWNER, scope);
export const tombstone = { status: 'deleted', filename: null, mime_type: null, byte_length: null, bytes_sha256: null, deleted_at: '2026-09-25T12:00:01Z' };
export const staged = { status: 'staged', bytes_sha256: null, archived_at: null, linked_at: null };
export async function owner(uid = OWNER) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); return captureOwnerToken(); }
export async function setupOwner() { localStorage.clear(); vi.stubGlobal('crypto', webcrypto); return owner(); }
export function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
