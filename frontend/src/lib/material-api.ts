import { getAuthState } from './supabase';
import { OwnerMismatchError, type OwnerToken } from './identity-owner';
import { contactRecord, contactTimestamp } from './contact-ledger';
import { MaterialError, MATERIAL_MIME, assertMaterialOwner,
  materialBefore, materialInputMatches, materialRecordMatchesInput, inspectMaterialFile,
  materialExactKeys, materialUuid, snapshotMaterialCursor, withMaterialOperation,
  type MaterialCodec, type MaterialEventField, type MaterialAttempt, type MaterialErrorCode,
  type MaterialOperation, type MaterialPage, type MaterialRecord, type MaterialScope, type MaterialCursor } from './material-core';
import type { MaterialStorage } from './material-storage';
const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';
type Options = { owner: OwnerToken; signal?: AbortSignal };
const fail = (): never => { throw new MaterialError('invalid_receipt'); };
const errorCodes: Record<string, [number, MaterialErrorCode]> = {
  material_not_configured: [503, 'not_configured'], material_auth_required: [401, 'sign_in_required'],
  material_invalid_request: [422, 'invalid_input'], material_invalid_pdf: [422, 'invalid_pdf'],
  material_too_large: [413, 'file_too_large'], material_conflict: [409, 'conflict'],
  material_not_found: [404, 'not_found'], material_deleted: [410, 'deleted'], material_expired: [409, 'expired'],
  material_not_ready: [409, 'not_ready'], material_busy: [503, 'busy'], material_unavailable: [503, 'unavailable'],
  material_invalid_receipt: [502, 'invalid_receipt'],
};
export function createMaterialApi<F extends MaterialEventField>(source: 'application' | 'contact', codec: MaterialCodec<F>, storage: MaterialStorage<F>) {
  const { snapshotScope: snapshotMaterialScope, snapshotAttempt: snapshotMaterialAttempt, parseRecord: parseMaterialRecord, snapshotRecord: snapshotMaterialRecord } = codec;
  const { beginMaterialDeletion, readPendingMaterialAttempts, readPendingMaterialDeletions, settleMaterialAttempt, settleMaterialDeletion } = storage;
  function wireScope(owner: OwnerToken, scope: MaterialScope<F>): Record<string, string> {
    assertMaterialOwner(owner);
    if (!materialUuid(owner.uid)) throw new MaterialError('invalid_input');
    return { expected_owner_id: owner.uid, opportunity_id: scope.opportunityId, [codec.wireField]: scope[codec.field] };
  }
  function endpoint(owner: OwnerToken, scope: MaterialScope<F>, suffix = '', cursor?: MaterialCursor): string {
    const query = new URLSearchParams(wireScope(owner, scope));
    if (cursor) { query.set('cursor_linked_at', cursor.linkedAt); query.set('cursor_record_id', cursor.recordId); }
    return `${API_BASE}/${source}-materials${suffix}?${query}`;
  }
  async function authenticate(owner: OwnerToken, operation: MaterialOperation): Promise<string> {
    const state = await operation.wait(getAuthState({ throwOnError: true })); operation.assertActive();
    if (!state.session?.access_token || !state.user || state.isAnonymous) throw new MaterialError('sign_in_required');
    if (state.user.id !== owner.uid || state.session.user.id !== owner.uid) throw new OwnerMismatchError();
    return state.session.access_token;
  }
  async function request(url: string, token: string, operation: MaterialOperation, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers); headers.set('Authorization', `Bearer ${token}`);
    operation.assertActive();
    const response = await operation.wait(fetch(url, { ...init, headers, signal: operation.signal, cache: 'no-store', redirect: 'error' }));
    if (response.redirected || response.type === 'opaqueredirect') fail();
    return response;
  }
  /** Never consume an unbounded server body, including private error text. */
  async function readBytes(response: Response, limit: number, operation: MaterialOperation): Promise<Uint8Array<ArrayBuffer>> {
    // Fetch exposes decoded bytes. A compressed transfer's Content-Length does
    // not describe those bytes; the actual stream remains bounded in either case.
    const encoded = response.headers.get('content-encoding');
    const advertised = encoded && encoded.toLowerCase() !== 'identity' ? null : response.headers.get('content-length');
    if (advertised !== null && (!/^\d+$/.test(advertised) || !Number.isSafeInteger(Number(advertised)) || Number(advertised) > limit)) fail();
    const reader = response.body?.getReader(); if (!reader) return fail();
    const chunks: Uint8Array<ArrayBuffer>[] = []; let size = 0;
    try {
      for (;;) {
        const item = await operation.wait(reader.read());
        if (item.done) break;
        size += item.value.byteLength; if (size > limit) fail();
        chunks.push(new Uint8Array(item.value));
      }
    } finally { void reader.cancel().catch(() => {}); }
    if (advertised !== null && Number(advertised) !== size) fail();
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    operation.assertActive(); return bytes;
  }
  async function readJson(response: Response, operation: MaterialOperation): Promise<Record<string, unknown>> {
    const bytes = await readBytes(response, response.ok ? 128 * 1024 : 8192, operation);
    let parsed: unknown;
    try { parsed = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); } catch { return fail(); }
    if (!response.ok) {
      if (contactRecord(parsed) && contactRecord(parsed.detail) && typeof parsed.detail.code === 'string') {
        if (parsed.detail.code === 'material_owner_mismatch' && response.status === 409) throw new OwnerMismatchError();
        const known = errorCodes[parsed.detail.code];
        if (known && known[0] === response.status) throw new MaterialError(known[1]);
      }
      throw new MaterialError('unavailable');
    }
    if ((response.headers.get('content-type') ?? '').split(';')[0].trim().toLowerCase() !== 'application/json' || !contactRecord(parsed)) return fail();
    return parsed;
  }
  function receipt(data: Record<string, unknown>, owner: OwnerToken, scope: MaterialScope<F>, recordId: string, post = false): MaterialRecord<F> {
    if (!materialExactKeys(data, post ? ['version', 'record', 'replayed'] : ['version', 'record']) || data.version !== 1
      || (post && typeof data.replayed !== 'boolean')) return fail();
    return parseMaterialRecord(data.record, owner.uid!, scope, recordId);
  }
  function notDeleting(owner: OwnerToken, scope: MaterialScope<F>, recordId: string) {
    if (readPendingMaterialDeletions(owner, scope).some(item => item.recordId === recordId)) throw new MaterialError('deleted');
  }
  async function lookup(owner: OwnerToken, scope: MaterialScope<F>, recordId: string, token: string,
    operation: MaterialOperation): Promise<MaterialRecord<F> | null> {
    try { return receipt(await readJson(await request(endpoint(owner, scope, `/${recordId}`), token, operation), operation), owner, scope, recordId); }
    catch (error) { if (error instanceof MaterialError && error.code === 'not_found') return null; throw error; }
  }
  async function getMaterial(value: MaterialScope<F>, recordId: string, options: Options): Promise<MaterialRecord<F> | null> {
    const owner = { ...options.owner }; const scope = snapshotMaterialScope(value); wireScope(owner, scope);
    if (!materialUuid(recordId)) throw new MaterialError('invalid_input');
    return withMaterialOperation(owner, options.signal, async operation => lookup(owner, scope, recordId, await authenticate(owner, operation), operation));
  }
  async function getMaterials(value: MaterialScope<F>, options: Options & { cursor?: MaterialCursor }): Promise<MaterialPage<F>> {
    const owner = { ...options.owner }; const scope = snapshotMaterialScope(value); wireScope(owner, scope);
    const cursor = options.cursor ? snapshotMaterialCursor(options.cursor) : undefined;
    return withMaterialOperation(owner, options.signal, async operation => {
      const data = await readJson(await request(endpoint(owner, scope, '', cursor), await authenticate(owner, operation), operation), operation);
      if (!materialExactKeys(data, ['version', 'items', 'next_cursor']) || data.version !== 1 || !Array.isArray(data.items) || data.items.length > 20) return fail();
      const items = data.items.map(row => parseMaterialRecord(row, owner.uid!, scope));
      let previous = cursor; const ids = new Set<string>(); const materialIds = new Set<string>();
      for (const item of items) {
        if (item.status === 'staged' || !item.linkedAt || ids.has(item.recordId) || materialIds.has(item.materialId)) return fail();
        const position = { linkedAt: item.linkedAt, recordId: item.recordId };
        if (previous && !materialBefore(position, previous)) return fail();
        ids.add(item.recordId); materialIds.add(item.materialId); previous = position;
      }
      let nextCursor: MaterialCursor | null = null;
      if (data.next_cursor !== null) {
        if (!contactRecord(data.next_cursor) || !materialExactKeys(data.next_cursor, ['linked_at', 'record_id']) || items.length !== 20) return fail();
        try { nextCursor = snapshotMaterialCursor({ linkedAt: data.next_cursor.linked_at, recordId: data.next_cursor.record_id }); } catch { return fail(); }
        const last = items[items.length - 1];
        if (nextCursor.recordId !== last.recordId || contactTimestamp(nextCursor.linkedAt) !== contactTimestamp(last.linkedAt)) return fail();
      }
      return { items, nextCursor };
    });
  }
  /** Only a durably prepared attempt or a verified immutable prior receipt may be
   * replayed. A different outstanding attempt is never overwritten or removed. */
  async function uploadMaterial(value: MaterialAttempt<F>, file: File, options: Options): Promise<{ record: MaterialRecord<F>; replayed: boolean }> {
    const owner = { ...options.owner }; const attempt = snapshotMaterialAttempt(value); const { scope, input } = attempt;
    wireScope(owner, scope);
    return withMaterialOperation(owner, options.signal, async operation => {
      notDeleting(owner, scope, input.recordId);
      const token = await authenticate(owner, operation);
      const prepared = readPendingMaterialAttempts(owner, scope).find(item => item.input.recordId === input.recordId);
      if (prepared) { if (!materialInputMatches(prepared.input, input)) throw new MaterialError('conflict'); }
      else {
        const saved = await lookup(owner, scope, input.recordId, token, operation);
        if (saved?.status === 'deleted') throw new MaterialError('deleted');
        if (!saved || !materialRecordMatchesInput(saved, input)) throw new MaterialError('invalid_pending');
      }
      const selected = await operation.wait(inspectMaterialFile(owner, file, operation.signal));
      if (selected.byteLength !== input.byteLength || selected.bytesSha256 !== input.bytesSha256) throw new MaterialError('file_mismatch');
      notDeleting(owner, scope, input.recordId);
      const metadata = JSON.stringify({ version: 1, ...wireScope(owner, scope), material_id: input.materialId, record_id: input.recordId,
        filename: input.filename, mime_type: input.mimeType, byte_length: input.byteLength, bytes_sha256: input.bytesSha256, attested: true });
      const body = new FormData(); body.append('metadata', metadata); body.append('file', file, input.filename);
      const data = await readJson(await request(`${API_BASE}/${source}-materials`, token, operation, { method: 'POST', body }), operation);
      const record = receipt(data, owner, scope, input.recordId, true);
      if (!materialRecordMatchesInput(record, input)) return fail();
      notDeleting(owner, scope, input.recordId);
      return { record, replayed: data.replayed as boolean };
    });
  }
  async function deleteMaterial(value: MaterialScope<F>,
    selected: Pick<MaterialRecord<F>, 'recordId' | 'materialId'>, options: Options): Promise<MaterialRecord<F>> {
    const owner = { ...options.owner }; const scope = snapshotMaterialScope(value); const recordId = selected.recordId; const materialId = selected.materialId;
    wireScope(owner, scope); if (!materialUuid(recordId) || !materialUuid(materialId)) throw new MaterialError('invalid_input');
    return withMaterialOperation(owner, options.signal, async operation => {
      const token = await authenticate(owner, operation);
      await operation.wait(beginMaterialDeletion(owner, scope, recordId, materialId));
      const data = await readJson(await request(`${API_BASE}/${source}-materials/${recordId}`, token, operation,
        { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...wireScope(owner, scope), material_id: materialId }) }), operation);
      const record = receipt(data, owner, scope, recordId);
      if (record.status !== 'deleted' || record.materialId !== materialId) return fail();
      await operation.wait(settleMaterialAttempt(owner, scope, record));
      await operation.wait(settleMaterialDeletion(owner, scope, record));
      return record;
    });
  }
  async function downloadMaterial(value: MaterialScope<F>, selected: MaterialRecord<F>, options: Options): Promise<void> {
    const owner = { ...options.owner }; const scope = snapshotMaterialScope(value); wireScope(owner, scope);
    const record = snapshotMaterialRecord(selected, owner.uid!, scope);
    if (record.status !== 'ready') throw new MaterialError(record.status === 'deleted' ? 'deleted' : 'not_ready');
    return withMaterialOperation(owner, options.signal, async operation => {
      notDeleting(owner, scope, record.recordId);
      const response = await request(endpoint(owner, scope, `/${record.recordId}/file`), await authenticate(owner, operation), operation);
      if (!response.ok) { await readJson(response, operation); return fail(); }
      if ((response.headers.get('content-type') ?? '').split(';')[0].trim().toLowerCase() !== MATERIAL_MIME
        || response.headers.get('x-ofe-material-id') !== record.materialId || response.headers.get('x-ofe-material-record') !== record.recordId
        || response.headers.get('x-ofe-material-sha256') !== record.bytesSha256) return fail();
      const bytes = await readBytes(response, record.byteLength!, operation);
      if (bytes.byteLength !== record.byteLength || new TextDecoder().decode(bytes.subarray(0, 5)) !== '%PDF-') return fail();
      const digest = new Uint8Array(await operation.wait(crypto.subtle.digest('SHA-256', bytes)));
      if (Array.from(digest, byte => byte.toString(16).padStart(2, '0')).join('') !== record.bytesSha256) return fail();
      notDeleting(owner, scope, record.recordId); operation.assertActive();
      const url = URL.createObjectURL(new Blob([bytes], { type: MATERIAL_MIME }));
      const link = document.createElement('a'); link.href = url; link.download = record.filename!;
      try { operation.assertActive(); document.body.appendChild(link); link.click(); }
      finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
    });
  }
  return { getMaterial, getMaterials, uploadMaterial, deleteMaterial, downloadMaterial };
}
export type MaterialApi<F extends MaterialEventField> = ReturnType<typeof createMaterialApi<F>>;
