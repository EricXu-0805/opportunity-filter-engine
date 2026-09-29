/** Owner-bound private import persistence. This is not a public writing target. */
import type { ImportedOpportunity } from './api';
import { getAuthState } from './supabase';
import { isOwnerTokenValid, onLocalOwnerStateChange, OwnerMismatchError, type OwnerToken } from './identity-owner';
import { contactTimestamp } from './contact-ledger';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';
export const PRIVATE_TARGET_MAX_BYTES = 8 * 1024 * 1024;
export const PRIVATE_TARGET_TIMEOUT_MS = 30_000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ID = /^private-import:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
type Options = { owner: OwnerToken; signal?: AbortSignal };
export type PrivateTargetErrorCode = 'invalid_input' | 'invalid_receipt' | 'sign_in_required' | 'conflict' | 'changed' | 'deleted' | 'not_found' | 'too_large' | 'unavailable' | 'timeout' | 'aborted' | 'contact_blocked' | 'ai_unavailable';
export class PrivateTargetError extends Error {
  constructor(readonly code: PrivateTargetErrorCode) { super('The private import request could not be completed.'); this.name = 'PrivateTargetError'; }
}
interface TargetBase {
  id: string; owner_id: string; revision: number; created_at: string; updated_at: string; deleted_at: string | null;
  target_scope: 'private_import'; verification: 'unverified'; target_version: string;
}
export interface PrivateImportTarget extends TargetBase {
  opportunity: ImportedOpportunity | null;
  import_source: { version: 1; description_source: 'page_text' | 'page_excerpt' | 'pasted_text' | 'unknown'; ai_input_scope: 'source_excerpt' | 'unknown'; llm_enriched: boolean } | null;
}
export interface PrivateImportSummary extends TargetBase {
  deleted_at: null; title: string; organization: string | null; source_url: string; url: string; source: 'url_parser' | 'text_parser';
}
export interface PrivateImportCursor { updated_at: string; id: string }
export interface PrivateImportReceipt { version: 1; target: PrivateImportTarget; replayed: boolean }
export interface PrivateImportPage { version: 1; items: PrivateImportSummary[]; next_cursor: PrivateImportCursor | null }
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const fail = (code: PrivateTargetErrorCode = 'invalid_receipt'): never => { throw new PrivateTargetError(code); };
const same = (a: unknown, b: unknown): boolean => {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((value, index) => same(value, b[index]));
  return record(a) && record(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(key => Object.hasOwn(b, key) && same(a[key], b[key]));
};
function assertOwner(owner: OwnerToken): asserts owner is OwnerToken & { uid: string } {
  if (!owner.uid || !UUID.test(owner.uid) || !isOwnerTokenValid(owner, owner.uid)) throw new OwnerMismatchError();
}
function validateId(id: string) { if (!ID.test(id)) fail('invalid_input'); }
function revision(value: unknown, minimum: number): value is number { return Number.isSafeInteger(value) && (value as number) >= minimum && (value as number) <= Number.MAX_SAFE_INTEGER - 1; }
function jsonText(value: unknown): string {
  const check = (item: unknown, depth = 0): void => {
    if (depth > 32) fail('invalid_input');
    if (typeof item === 'string') { if (/[\u0000\ud800-\udfff]/u.test(item)) fail('invalid_input'); }
    else if (Array.isArray(item)) item.forEach(child => check(child, depth + 1));
    else if (record(item)) Object.entries(item).forEach(([key, child]) => { check(key, depth + 1); if (child !== undefined) check(child, depth + 1); });
    else if (item !== null && typeof item !== 'boolean' && !(typeof item === 'number' && Number.isFinite(item))) fail('invalid_input');
  };
  try { check(value); return JSON.stringify(value); } catch (error) { if (error instanceof PrivateTargetError) throw error; return fail('invalid_input'); }
}
function snapshotOpportunity(value: unknown): ImportedOpportunity {
  if (!record(value) || !['url_parser', 'text_parser'].includes(value.source as string)
    || typeof value.title !== 'string' || !value.title.trim() || Array.from(value.title).length > 1000
    || typeof value.description_raw !== 'string' || !value.description_raw.trim()) return fail('invalid_input');
  const allowed = ['source', 'title', 'description_raw', 'source_url', 'url', 'organization', 'deadline', 'posted_date', 'location', 'raw_html', 'extra_fields'];
  if (Object.keys(value).some(key => !allowed.includes(key)) || (value.extra_fields !== undefined && !record(value.extra_fields))) return fail('invalid_input');
  for (const key of ['source_url', 'url', 'organization', 'deadline', 'posted_date', 'location', 'raw_html']) {
    const field = value[key];
    if (field === undefined || (field === null && !['source_url', 'url'].includes(key))) continue;
    if (typeof field !== 'string') return fail('invalid_input');
    const cap = ['source_url', 'url'].includes(key) ? 8192 : ['organization', 'location'].includes(key) ? 2000 : ['deadline', 'posted_date'].includes(key) ? 128 : Infinity;
    if (Array.from(field).length > cap) return fail('invalid_input');
  }
  if (Array.from(value.description_raw).length > 5 * 1024 * 1024) return fail('too_large');
  const text = jsonText(value);
  if (new TextEncoder().encode(text).length > PRIVATE_TARGET_MAX_BYTES) fail('too_large');
  if (new TextEncoder().encode(jsonText(value.extra_fields ?? {})).length > 256 * 1024) fail('too_large');
  return JSON.parse(text) as ImportedOpportunity;
}
interface Operation { signal: AbortSignal; check: () => void; wait: <T>(value: Promise<T>) => Promise<T> }
async function run<T>(origin: OwnerToken, signal: AbortSignal | undefined, work: (operation: Operation) => Promise<T>): Promise<T> {
  assertOwner(origin);
  const controller = new AbortController(); let timeout = false;
  const abort = () => controller.abort();
  const check = () => { assertOwner(origin); if (timeout) fail('timeout'); if (controller.signal.aborted) fail('aborted'); };
  const retire = () => { if (!isOwnerTokenValid(origin, origin.uid)) abort(); };
  const off = onLocalOwnerStateChange(retire);
  if (typeof window !== 'undefined') window.addEventListener('storage', retire);
  if (signal?.aborted) abort(); else signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => { timeout = true; abort(); }, PRIVATE_TARGET_TIMEOUT_MS);
  const wait = <V,>(pending: Promise<V>): Promise<V> => new Promise((resolve, reject) => {
    const stop = () => { try { check(); reject(new PrivateTargetError('aborted')); } catch (error) { reject(error); } };
    if (controller.signal.aborted) { pending.catch(() => {}); stop(); return; }
    controller.signal.addEventListener('abort', stop, { once: true });
    pending.then(value => { try { check(); resolve(value); } catch (error) { reject(error); } }, reject)
      .finally(() => controller.signal.removeEventListener('abort', stop));
  });
  try { check(); const result = await work({ signal: controller.signal, check, wait }); check(); return result; }
  catch (error) { check(); if (error instanceof PrivateTargetError || error instanceof OwnerMismatchError) throw error; return fail('unavailable'); }
  finally { clearTimeout(timer); off(); signal?.removeEventListener('abort', abort); controller.abort(); if (typeof window !== 'undefined') window.removeEventListener('storage', retire); }
}
const errors: Record<string, [number, PrivateTargetErrorCode]> = {
  auth_required: [401, 'sign_in_required'], changed: [409, 'changed'], conflict: [409, 'conflict'], deleted: [409, 'deleted'], not_found: [404, 'not_found'],
  invalid_request: [422, 'invalid_input'], too_large: [413, 'too_large'], invalid_receipt: [502, 'invalid_receipt'], unavailable: [503, 'unavailable'],
};
async function request(path: string, owner: OwnerToken, operation: Operation, init?: RequestInit, list = false): Promise<Record<string, unknown>> {
  const auth = await operation.wait(getAuthState({ throwOnError: true }));
  if (!auth.user || !auth.session?.access_token || auth.isAnonymous) return fail('sign_in_required');
  if (auth.user.id !== owner.uid || auth.session.user.id !== owner.uid) throw new OwnerMismatchError();
  const headers = new Headers(init?.headers); headers.set('Authorization', `Bearer ${auth.session.access_token}`);
  operation.check();
  const response = await operation.wait(fetch(`${API_BASE}/private-import-targets${path}`, { ...init, headers, signal: operation.signal, cache: 'no-store', redirect: 'error' }));
  if (response.redirected || response.type === 'opaqueredirect') fail();
  const limit = response.ok ? (list ? PRIVATE_TARGET_MAX_BYTES : PRIVATE_TARGET_MAX_BYTES + 65536) : 8192;
  const contentLength = response.headers.get('content-encoding') ? null : response.headers.get('content-length');
  if (contentLength !== null && (!/^\d+$/.test(contentLength) || !Number.isSafeInteger(Number(contentLength)) || Number(contentLength) > limit)) fail();
  const reader = response.body?.getReader(); if (!reader) return fail();
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) { const chunk = await operation.wait(reader.read()); if (chunk.done) break; size += chunk.value.byteLength; if (size > limit) fail(); chunks.push(chunk.value); }
  } finally { void reader.cancel().catch(() => {}); }
  if (contentLength !== null && Number(contentLength) !== size) fail();
  const all = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { all.set(chunk, offset); offset += chunk.byteLength; }
  let data: unknown;
  try { data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(all)); } catch { return fail(response.ok ? 'invalid_receipt' : 'unavailable'); }
  if (!response.ok) {
    const code = record(data) && record(data.detail) && typeof data.detail.code === 'string' ? data.detail.code : '';
    if (code === 'private_email_contact_blocked' && response.status === 409) return fail('contact_blocked');
    if (code === 'private_email_ai_unavailable' && response.status === 409) return fail('ai_unavailable');
    if (code === 'private_target_owner_changed' && response.status === 409) throw new OwnerMismatchError();
    const known = code.startsWith('private_target_') ? errors[code.slice('private_target_'.length)] : undefined;
    return fail(known?.[0] === response.status ? known[1] : 'unavailable');
  }
  if ((response.headers.get('content-type') ?? '').split(';')[0].trim().toLowerCase() !== 'application/json' || !record(data)) return fail();
  operation.check(); return data;
}
const BASE_KEYS = ['id', 'owner_id', 'revision', 'created_at', 'updated_at', 'deleted_at', 'target_scope', 'verification', 'target_version'];
async function base(value: unknown, owner: OwnerToken, op: Operation, id?: string): Promise<Record<string, unknown>> {
  if (!record(value) || typeof value.id !== 'string' || !ID.test(value.id) || (id !== undefined && value.id !== id)
    || value.owner_id !== owner.uid || !Number.isSafeInteger(value.revision) || (value.revision as number) < 1
    || value.target_scope !== 'private_import' || value.verification !== 'unverified'
    || typeof value.target_version !== 'string' || !/^pit1:[a-f0-9]{64}$/.test(value.target_version)) return fail();
  const created = contactTimestamp(value.created_at); const updated = contactTimestamp(value.updated_at);
  const deleted = value.deleted_at === null ? null : contactTimestamp(value.deleted_at);
  if (created === null || updated === null || updated < created || (value.deleted_at !== null && (deleted === null || deleted !== updated))) return fail();
  const bytes = new TextEncoder().encode(JSON.stringify({ id: value.id, owner_id: value.owner_id, revision: value.revision }));
  const digest = new Uint8Array(await op.wait(crypto.subtle.digest('SHA-256', bytes)));
  if ('pit1:' + Array.from(digest, b => b.toString(16).padStart(2, '0')).join('') !== value.target_version) return fail();
  return value;
}
// Must match src/import_source.py: raw labels describe retained source only.
// Imported metadata never establishes official status or full-source AI use.
function sourceLabels(opportunity: ImportedOpportunity): PrivateImportTarget['import_source'] {
  const extra = opportunity.extra_fields;
  if (!extra || !['description_source', 'ai_input_scope', 'llm_enriched'].some(key => Object.hasOwn(extra, key))) return null;
  const unknown = { version: 1 as const, description_source: 'unknown' as const, ai_input_scope: 'unknown' as const, llm_enriched: false };
  const source = extra.description_source;
  const allowed = opportunity.source === 'url_parser' ? ['page_text', 'page_excerpt'] : ['pasted_text'];
  if (typeof source !== 'string' || !allowed.includes(source)) return unknown;
  const enriched = extra.llm_enriched === true;
  return { version: 1, description_source: source as 'page_text' | 'page_excerpt' | 'pasted_text',
    ai_input_scope: enriched && extra.ai_input_scope === 'source_excerpt' ? 'source_excerpt' : 'unknown', llm_enriched: enriched };
}
async function receipt(data: Record<string, unknown>, owner: OwnerToken, op: Operation, id: string): Promise<PrivateImportReceipt> {
  if (!exact(data, ['version', 'target', 'replayed']) || data.version !== 1 || typeof data.replayed !== 'boolean') return fail();
  const value = await base(data.target, owner, op, id);
  if (!exact(value, [...BASE_KEYS, 'opportunity', 'import_source'])) return fail();
  if (value.deleted_at !== null) { if (value.opportunity !== null || value.import_source !== null) return fail(); }
  else {
    let opportunity: ImportedOpportunity;
    try { opportunity = snapshotOpportunity(value.opportunity); } catch { return fail(); }
    if (!same(value.import_source, sourceLabels(opportunity))) return fail();
  }
  return data as unknown as PrivateImportReceipt;
}
export async function getPrivateImportTarget(id: string, options: Options): Promise<PrivateImportReceipt | null> {
  const owner = { ...options.owner }; assertOwner(owner); validateId(id);
  return run(owner, options.signal, async op => {
    try { return await receipt(await request(`/${encodeURIComponent(id)}?${new URLSearchParams({ expected_owner_id: owner.uid })}`, owner, op), owner, op, id); }
    catch (error) { if (error instanceof PrivateTargetError && error.code === 'not_found') return null; throw error; }
  });
}
export async function savePrivateImportTarget(id: string, value: ImportedOpportunity, expectedRevision: number, options: Options): Promise<PrivateImportReceipt> {
  const owner = { ...options.owner }; assertOwner(owner); validateId(id); if (!revision(expectedRevision, 0)) fail('invalid_input');
  const opportunity = snapshotOpportunity(value);
  const body = JSON.stringify({ expected_owner_id: owner.uid, expected_revision: expectedRevision, opportunity });
  return run(owner, options.signal, async op => {
    const result = await receipt(await request(`/${encodeURIComponent(id)}`, owner, op, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body }), owner, op, id);
    if (result.target.revision !== expectedRevision + 1 || result.target.deleted_at !== null || !same(result.target.opportunity, opportunity)) fail();
    return result;
  });
}
export async function deletePrivateImportTarget(id: string, expectedRevision: number, options: Options): Promise<PrivateImportReceipt> {
  const owner = { ...options.owner }; assertOwner(owner); validateId(id); if (!revision(expectedRevision, 1)) fail('invalid_input');
  const body = JSON.stringify({ expected_owner_id: owner.uid, expected_revision: expectedRevision });
  return run(owner, options.signal, async op => {
    const result = await receipt(await request(`/${encodeURIComponent(id)}`, owner, op, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body }), owner, op, id);
    if (result.target.revision !== expectedRevision + 1 || result.target.deleted_at === null) fail();
    return result;
  });
}
export async function listPrivateImportTargets(options: Options & { cursor?: PrivateImportCursor; limit?: number }): Promise<PrivateImportPage> {
  const owner = { ...options.owner }; assertOwner(owner);
  const limit = options.limit ?? 20; if (!Number.isInteger(limit) || limit < 1 || limit > 50) fail('invalid_input');
  const query = new URLSearchParams({ expected_owner_id: owner.uid, limit: String(limit) });
  const cursor = options.cursor ? { ...options.cursor } : null;
  if (cursor) { validateId(cursor.id); if (contactTimestamp(cursor.updated_at) === null) fail('invalid_input'); query.set('before_id', cursor.id); query.set('before_updated_at', cursor.updated_at); }
  return run(owner, options.signal, async op => {
    const data = await request(`?${query}`, owner, op, undefined, true);
    if (!exact(data, ['version', 'items', 'next_cursor']) || data.version !== 1 || !Array.isArray(data.items) || data.items.length > limit) return fail();
    const ids = new Set<string>(); let previous = cursor;
    for (const raw of data.items) {
      const value = await base(raw, owner, op);
      if (!exact(value, [...BASE_KEYS, 'title', 'organization', 'source_url', 'url', 'source']) || value.deleted_at !== null
        || typeof value.title !== 'string' || !value.title.trim() || (value.organization !== null && typeof value.organization !== 'string')
        || typeof value.source_url !== 'string' || typeof value.url !== 'string' || !['url_parser', 'text_parser'].includes(value.source as string) || ids.has(value.id as string)) return fail();
      try {
        snapshotOpportunity({ source: value.source, title: value.title, organization: value.organization,
          source_url: value.source_url, url: value.url, description_raw: 'Summary validation only.' });
      } catch { return fail(); }
      const next = { updated_at: value.updated_at as string, id: value.id as string };
      if (previous) { const a = contactTimestamp(next.updated_at)!; const b = contactTimestamp(previous.updated_at)!; if (a > b || (a === b && next.id >= previous.id)) return fail(); }
      previous = next; ids.add(next.id);
    }
    if (data.next_cursor !== null && (!record(data.next_cursor) || !exact(data.next_cursor, ['updated_at', 'id']) || data.items.length !== limit || !same(data.next_cursor, previous))) return fail();
    return data as unknown as PrivateImportPage;
  });
}


export interface PrivateResolvedTarget {
  version: 1; target_scope: 'private_import'; verification: 'unverified';
  id: string; owner_id: string; revision: number; target_version: string;
  detail: {
    title: string; organization: string | null; description_raw: string;
    source_url: string | null; url: string | null; location: string | null;
    deadline: string | null; posted_date: string | null; import_source: PrivateImportTarget['import_source'];
  };
  tracker: {
    id: string; title: string; organization: string | null; source_url: string | null; url: string | null;
    target_scope: 'private_import'; verification: 'unverified'; target_version: string;
  };
  capabilities: { read: true; tracker_identity: true; writes: false };
}
export function isPrivateImportId(value: string): boolean { return ID.test(value); }
function safeProjectedUrl(value: unknown): boolean {
  if (value === null) return true;
  if (typeof value !== 'string' || /[\u0000-\u0020\u007f\\]/.test(value)) return false;
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !!url.hostname; }
  catch { return false; }
}
/** Owner-authorized display only; this receipt cannot authorize AI or sending. */
export async function getResolvedPrivateImportTarget(id: string, options: Options & { expectedVersion?: string }): Promise<PrivateResolvedTarget> {
  const owner = { ...options.owner }; assertOwner(owner); validateId(id);
  const expected = options.expectedVersion;
  if (expected !== undefined && !/^pit1:[a-f0-9]{64}$/.test(expected)) fail('invalid_input');
  const query = new URLSearchParams({ expected_owner_id: owner.uid });
  if (expected) query.set('expected_target_version', expected);
  return run(owner, options.signal, async op => {
    const value = await request(`/${encodeURIComponent(id)}/resolved?${query}`, owner, op);
    if (!exact(value, ['version','id','owner_id','revision','target_version','target_scope','verification','detail','tracker','capabilities'])
      || value.version !== 1 || value.id !== id || value.owner_id !== owner.uid
      || value.target_scope !== 'private_import' || value.verification !== 'unverified'
      || !Number.isSafeInteger(value.revision) || (value.revision as number) < 1) return fail();
    const bytes = new TextEncoder().encode(JSON.stringify({ id, owner_id: owner.uid, revision: value.revision }));
    const digest = new Uint8Array(await op.wait(crypto.subtle.digest('SHA-256', bytes)));
    const version = 'pit1:' + Array.from(digest, b => b.toString(16).padStart(2, '0')).join('');
    if (value.target_version !== version || (expected && version !== expected)) return fail();
    const detail = value.detail;
    if (!record(detail) || !exact(detail, ['title','organization','description_raw','source_url','url','location','deadline','posted_date','import_source'])
      || !safeProjectedUrl(detail.source_url) || !safeProjectedUrl(detail.url)
      || !['organization','location','deadline','posted_date'].every(key => detail[key] === null || typeof detail[key] === 'string')) return fail();
    try { snapshotOpportunity({ source: 'text_parser', title: detail.title, description_raw: detail.description_raw,
      source_url: detail.source_url ?? '', url: detail.url ?? '', organization: detail.organization,
      location: detail.location, deadline: detail.deadline, posted_date: detail.posted_date }); }
    catch { return fail(); }
    const labels = detail.import_source;
    if (labels !== null && (!record(labels) || !exact(labels, ['version','description_source','ai_input_scope','llm_enriched'])
      || labels.version !== 1 || !['page_text','page_excerpt','pasted_text','unknown'].includes(labels.description_source as string)
      || !['source_excerpt','unknown'].includes(labels.ai_input_scope as string) || typeof labels.llm_enriched !== 'boolean'
      || (labels.ai_input_scope === 'source_excerpt' && (labels.llm_enriched !== true || labels.description_source === 'unknown'))
      || (labels.description_source === 'unknown' && labels.llm_enriched !== false))) return fail();
    const tracker = { id, title: detail.title, organization: detail.organization, source_url: detail.source_url, url: detail.url,
      target_scope: 'private_import', verification: 'unverified', target_version: version };
    if (!same(value.tracker, tracker) || !same(value.capabilities, { read: true, tracker_identity: true, writes: false })) return fail();
    return value as unknown as PrivateResolvedTarget;
  });
}

/** Private email transport shares the account/auth/deadline boundary. No public
 * endpoint or model endpoint is reachable through this finite action set. */
export async function privateImportEmailRequest(id: string, action: 'context' | 'variants' | 'validate',
  value: Record<string, unknown> | undefined, options: Options & { verify?: (data: Record<string, unknown>, wait: Operation['wait']) => Promise<void> }): Promise<Record<string, unknown>> {
  const owner = { ...options.owner }; assertOwner(owner); validateId(id);
  const body = action === 'context' ? undefined : jsonText({ ...value, expected_owner_id: owner.uid });
  if (body && new TextEncoder().encode(body).length > 120000) fail('too_large');
  return run(owner, options.signal, async op => {
    const data = await request(`/${encodeURIComponent(id)}` + (action === 'context'
      ? `/email-context?${new URLSearchParams({ expected_owner_id: owner.uid })}` : `/cold-email/${action}`), owner, op,
      body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body } : undefined);
    if (options.verify) await op.wait(options.verify(data, op.wait));
    return data;
  });
}
