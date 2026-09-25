import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { APPLICATION_MATERIAL_MAX_BYTES, applicationMaterialBefore, inspectApplicationMaterialFile,
  parseApplicationMaterialRecord, snapshotApplicationMaterialInput, validApplicationMaterialFilename,
  withApplicationMaterialOperation } from './application-material';
import { captureOwnerToken, OwnerMismatchError } from './identity-owner';
import { OWNER, OTHER, scope, file, input, wire, record, tombstone, staged, setupOwner, owner, deferred } from './application-material.test-utils';
beforeEach(setupOwner);
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
it('accepts immutable ready/staged/deleted snapshots without making staged hashes look verified', () => {
  expect(Object.isFrozen(record())).toBe(true); expect(record(staged).bytesSha256).toBeNull();
  expect(record(tombstone)).toMatchObject({ status: 'deleted', filename: null, byteLength: null });
  expect(record({ ...staged, ...tombstone, archived_at: null, linked_at: null }).archivedAt).toBeNull();
});
it.each([
  { owner_id: OTHER }, { opportunity_id: 'other' }, { application_event_id: input().recordId }, { material_id: 'bad' },
  { version: 2 }, { unexpected: true }, { confirmation_source: 'delivered' }, { staged_at: '2026-02-30T12:00:00Z' },
  { staged_at: '2026-09-25T12:00:00-05:00' }, { archived_at: null }, { linked_at: '2026-09-25T11:00:00Z' },
  { deleted_at: '2026-09-25T13:00:00Z' }, { filename: '../resume.pdf' }, { byte_length: APPLICATION_MATERIAL_MAX_BYTES + 1 },
  { bytes_sha256: 'ABC' }, { ...staged, bytes_sha256: input().bytesSha256 }, { ...staged, archived_at: wire().archived_at },
  { ...tombstone, filename: 'sensitive.pdf' }, { ...tombstone, bytes_sha256: input().bytesSha256 },
  { ...tombstone, deleted_at: '2026-09-24T00:00:00Z' },
])('rejects malformed/mixed receipts %j', change => {
  expect(() => parseApplicationMaterialRecord(wire(change), OWNER, scope)).toThrowError(expect.objectContaining({ code: 'invalid_receipt' }));
});
it('rejects the wrong record and preserves microsecond pagination boundaries', () => {
  expect(() => parseApplicationMaterialRecord(wire(), OWNER, scope, input().materialId)).toThrow();
  expect(applicationMaterialBefore({ linkedAt: '2026-09-25T12:00:00.000001Z', recordId: input().recordId },
    { linkedAt: '2026-09-25T12:00:00.000002Z', recordId: input().recordId })).toBe(true);
});
it('uses codepoints for Unicode filenames and excludes paths/control characters', () => {
  expect(validApplicationMaterialFilename('😀'.repeat(196) + '.PDF')).toBe(true);
  expect(validApplicationMaterialFilename('😀'.repeat(197) + '.pdf')).toBe(false);
  for (const name of ['x.txt', 'x.pdf\n', '../x.pdf', 'a\\b.pdf', 'x\u0085.pdf', 'x\ud800.pdf', 'x\u007f.pdf', 'x\0.pdf']) expect(validApplicationMaterialFilename(name)).toBe(false);
});
it('validates metadata size boundary and attestation without normalizing it', () => {
  expect(snapshotApplicationMaterialInput({ ...input(), byteLength: APPLICATION_MATERIAL_MAX_BYTES }).byteLength).toBe(APPLICATION_MATERIAL_MAX_BYTES);
  for (const change of [{ byteLength: 0 }, { byteLength: 2.1 }, { byteLength: APPLICATION_MATERIAL_MAX_BYTES + 1 }, { attested: false }])
    expect(() => snapshotApplicationMaterialInput({ ...input(), ...change })).toThrow();
});
it('hashes full PDF bytes; accepts omitted/octet MIME but rejects magic and sizes before hashing', async () => {
  expect(await inspectApplicationMaterialFile(captureOwnerToken(), file())).toMatchObject({ bytesSha256: input().bytesSha256, byteLength: input().byteLength });
  const selected = file(); Object.defineProperty(selected, 'type', { value: 'application/octet-stream' });
  await expect(inspectApplicationMaterialFile(captureOwnerToken(), selected)).resolves.toHaveProperty('bytesSha256');
  await expect(inspectApplicationMaterialFile(captureOwnerToken(), file('x.pdf', 'not a pdf'))).rejects.toMatchObject({ code: 'invalid_pdf' });
  Object.defineProperty(selected, 'size', { value: APPLICATION_MATERIAL_MAX_BYTES + 1 });
  await expect(inspectApplicationMaterialFile(captureOwnerToken(), selected)).rejects.toMatchObject({ code: 'file_too_large' });
});
it('retires a held file read immediately when the owner changes', async () => {
  const pending = deferred<ArrayBuffer>(); const selected = file(); Object.defineProperty(selected, 'arrayBuffer', { value: () => pending.promise });
  const result = inspectApplicationMaterialFile(captureOwnerToken(), selected); const check = expect(result).rejects.toBeInstanceOf(OwnerMismatchError);
  await owner(OTHER); await check; pending.resolve(new ArrayBuffer(1));
});
it('does not expose late results after abort or timeout even if the promise ignores abort', async () => {
  const held = deferred<string>(); const signal = new AbortController();
  const run = withApplicationMaterialOperation(captureOwnerToken(), signal.signal, op => op.wait(held.promise));
  const aborted = expect(run).rejects.toMatchObject({ code: 'aborted' }); signal.abort(); await aborted;
  vi.useFakeTimers(); const timeout = withApplicationMaterialOperation(captureOwnerToken(), undefined, op => op.wait(held.promise), 50);
  const check = expect(timeout).rejects.toMatchObject({ code: 'timeout' }); await vi.advanceTimersByTimeAsync(50); await check; held.resolve('late');
});
it('fails safely when cryptographic hashing is unavailable', async () => {
  vi.stubGlobal('crypto', {}); await expect(inspectApplicationMaterialFile(captureOwnerToken(), file())).rejects.toMatchObject({ code: 'unavailable' });
});
