import { validateTargetResumeProvenance, type TargetResumeProvenance } from './target-resume-provenance';
import { getDeviceId, supabase } from './supabase';
import { isOwnerTokenValid, type OwnerToken } from './identity-owner';
import {
  validateTargetResume, verifyTargetResumeSignatures,
  type TargetResumeV1, type LoadedTargetResume, type TargetResumeSaveResult,
} from './target-resume';

export type { LoadedTargetResume, TargetResumeSaveResult } from './target-resume';
export interface TargetResumeVersionSummary { revision: number; updated_at: string }
export const TARGET_RESUME_HISTORY_LIMIT = 20;
export const TARGET_RESUME_READ_TIMEOUT_MS = 30_000;
export type TargetResumeReadOptions = { signal?: AbortSignal; timeoutMs?: number };
const MAX_BYTES = 2 * 1024 * 1024;
export class TargetResumeReadError extends Error {
  constructor(public readonly code: 'abandoned' | 'unavailable' | 'failed' | 'invalid' | 'timeout') {
    super(`target_resume_${code}`);
    this.name = 'TargetResumeReadError';
  }
}
function owner(token: OwnerToken): void {
  if (!token.uid) throw new TargetResumeReadError('unavailable');
  if (!isOwnerTokenValid(token, token.uid)) throw new TargetResumeReadError('abandoned');
}
async function ready(token: OwnerToken): Promise<void> {
  owner(token);
  let uid: string | null;
  try { uid = await getDeviceId(); } catch { owner(token); throw new TargetResumeReadError('failed'); }
  owner(token);
  if (uid === null) throw new TargetResumeReadError('unavailable');
  if (uid !== token.uid) throw new TargetResumeReadError('abandoned');
}
/** One deadline covers identity, transport, body and signature work. This
 * helper is read-only: cancellation never claims a save RPC was rolled back. */
async function readWithin<T>(token: OwnerToken, options: TargetResumeReadOptions,
  read: (origin: OwnerToken, signal: AbortSignal, wait: <V>(value: PromiseLike<V>) => Promise<V>) => Promise<T>): Promise<T> {
  const origin = { ...token };
  owner(origin);
  const duration = options.timeoutMs ?? TARGET_RESUME_READ_TIMEOUT_MS;
  if (!Number.isFinite(duration) || duration < 0 || duration > 2_147_483_647) throw new TargetResumeReadError('invalid');
  const controller = new AbortController();
  let timedOut = false;
  let retired = false;
  const interrupted = () => new TargetResumeReadError(timedOut ? 'timeout' : 'abandoned');
  const active = () => { owner(origin); if (retired || controller.signal.aborted) throw interrupted(); };
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, duration);
  const wait = <V,>(value: PromiseLike<V>): Promise<V> => new Promise((resolve, reject) => {
    const clean = () => controller.signal.removeEventListener('abort', stop);
    const stop = () => { clean(); reject(interrupted()); };
    if (retired || controller.signal.aborted) {
      // The argument may already be running even though this wait was retired.
      void Promise.resolve(value).catch(() => {});
      stop(); return;
    }
    controller.signal.addEventListener('abort', stop, { once: true });
    Promise.resolve(value).then(result => {
      clean(); try { active(); resolve(result); } catch (error) { reject(error); }
    }, error => { clean(); reject(error); });
  });
  try {
    active();
    await wait(ready(origin));
    active();
    return await wait(read(origin, controller.signal, wait));
  } catch (error) { throw errorFor(error, origin); }
  finally { retired = true; clearTimeout(timer); options.signal?.removeEventListener('abort', abort); controller.abort(); }
}
function cancellable<T>(query: T, signal: AbortSignal): T {
  // PostgREST supports this; small test/legacy adapters may only be thenable.
  const candidate = query as T & { abortSignal?: (signal: AbortSignal) => T };
  return typeof candidate.abortSignal === 'function' ? candidate.abortSignal(signal) : query;
}
function targetId(value: string): void {
  if (typeof value !== 'string' || !value.trim() || Array.from(value).length > 200) {
    throw new TargetResumeReadError('invalid');
  }
}
function positive(value: unknown): value is number { return Number.isSafeInteger(value) && (value as number) > 0; }
function object(value: unknown): value is Record<string, unknown> { return !!value && typeof value === 'object' && !Array.isArray(value); }
function summary(value: unknown): TargetResumeVersionSummary {
  if (!object(value) || !positive(value.revision) || typeof value.updated_at !== 'string'
    || !value.updated_at.trim() || !Number.isFinite(Date.parse(value.updated_at))) throw new TargetResumeReadError('invalid');
  return { revision: value.revision, updated_at: value.updated_at };
}
function snapshot(value: unknown): TargetResumeV1 {
  // Freeze the request before any asynchronous identity/hash operation. No
  // caller mutation can change the document after its verification succeeds.
  const checked = validateTargetResume(value);
  if (!checked.ok) throw new TargetResumeReadError('invalid');
  const serialized = JSON.stringify(checked.value);
  if (new TextEncoder().encode(serialized).byteLength > MAX_BYTES) throw new TargetResumeReadError('invalid');
  return checked.value;
}
async function loaded(value: unknown, opportunityId: string, token: OwnerToken): Promise<LoadedTargetResume> {
  owner(token);
  const meta = summary(value);
  const doc = snapshot((value as Record<string, unknown>).doc);
  const provenance = provenanceSnapshot((value as Record<string, unknown>).provenance ?? null, doc);
  if (doc.opportunity_id !== opportunityId || !await verifyTargetResumeSignatures(doc)) throw new TargetResumeReadError('invalid');
  owner(token);
  return { ...meta, doc, provenance };
}
function provenanceSnapshot(value: unknown, doc: TargetResumeV1): TargetResumeProvenance | null {
  const checked = validateTargetResumeProvenance(value, doc);
  if (!checked.ok) throw new TargetResumeReadError('invalid');
  return checked.value;
}
function errorFor(error: unknown, token: OwnerToken): TargetResumeReadError {
  try { owner(token); } catch (failure) { return failure as TargetResumeReadError; }
  return error instanceof TargetResumeReadError ? error : new TargetResumeReadError('failed');
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (object(value)) return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}

/** A successful null is absent; every failed, timed-out or unreadable read rejects. */
export async function loadTargetResume(opportunityId: string, token: OwnerToken, options: TargetResumeReadOptions = {}): Promise<LoadedTargetResume | null> {
  targetId(opportunityId);
  return readWithin(token, options, async (origin, signal, wait) => {
    const query = supabase.from('target_resumes').select('revision,doc,updated_at,provenance')
      .eq('owner_id', origin.uid).eq('opportunity_id', opportunityId).maybeSingle();
    const { data, error } = await wait(cancellable(query, signal));
    if (error) throw new TargetResumeReadError('failed');
    return data === null ? null : await wait(loaded(data, opportunityId, origin));
  });
}

/** Metadata only. The server keeps the newest 20 versions per target, so one page is the whole history. */
export async function loadTargetResumeHistory(opportunityId: string, token: OwnerToken, beforeRevision?: number,
  options: TargetResumeReadOptions = {}): Promise<TargetResumeVersionSummary[]> {
  targetId(opportunityId);
  if (beforeRevision !== undefined && !positive(beforeRevision)) throw new TargetResumeReadError('invalid');
  return readWithin(token, options, async (origin, signal, wait) => {
    let query = supabase.from('target_resume_versions').select('revision,updated_at')
      .eq('owner_id', origin.uid).eq('opportunity_id', opportunityId);
    if (beforeRevision !== undefined) query = query.lt('revision', beforeRevision);
    const { data, error } = await wait(cancellable(query.order('revision', { ascending: false }).limit(TARGET_RESUME_HISTORY_LIMIT), signal));
    if (error) throw new TargetResumeReadError('failed');
    if (!Array.isArray(data) || data.length > TARGET_RESUME_HISTORY_LIMIT) throw new TargetResumeReadError('invalid');
    const result = data.map(summary);
    if (result.some((row, i) => (i > 0 && row.revision >= result[i - 1].revision)
      || (beforeRevision !== undefined && row.revision >= beforeRevision))) throw new TargetResumeReadError('invalid');
    return result;
  });
}

export async function loadTargetResumeVersion(opportunityId: string, revision: number, token: OwnerToken,
  options: TargetResumeReadOptions = {}): Promise<LoadedTargetResume | null> {
  targetId(opportunityId);
  if (!positive(revision)) throw new TargetResumeReadError('invalid');
  return readWithin(token, options, async (origin, signal, wait) => {
    const query = supabase.from('target_resume_versions').select('revision,doc,updated_at,provenance')
      .eq('owner_id', origin.uid).eq('opportunity_id', opportunityId).eq('revision', revision).maybeSingle();
    const { data, error } = await wait(cancellable(query, signal));
    if (error) throw new TargetResumeReadError('failed');
    if (data === null) return null;
    const result = await wait(loaded(data, opportunityId, origin));
    if (result.revision !== revision) throw new TargetResumeReadError('invalid');
    return result;
  });
}

/** One RPC atomically commits current + history. Restore uses this same CAS. */
export async function saveTargetResume(doc: TargetResumeV1, expectedRevision: number, token: OwnerToken, provenance: TargetResumeProvenance | null = null): Promise<TargetResumeSaveResult> {
  try {
    owner(token);
    if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 0) return { status: 'failed' };
    const copy = snapshot(doc);
    const provenanceCopy = provenanceSnapshot(provenance, copy);
    targetId(copy.opportunity_id);
    const verified = await verifyTargetResumeSignatures(copy);
    owner(token);
    if (!verified) return { status: 'failed' };
    await ready(token);
    const { data, error } = await supabase.rpc('commit_target_resume_with_provenance_cas', {
      p_expected_owner: token.uid, p_opportunity_id: copy.opportunity_id,
      p_expected_revision: expectedRevision, p_doc: copy, p_provenance: provenanceCopy,
    });
    owner(token);
    if (error || !object(data)) return { status: 'failed' };
    if (data.status === 'missing') return { status: 'missing' };
    if (!['saved', 'unchanged', 'conflict'].includes(String(data.status))) return { status: 'failed' };
    const value = await loaded(data, copy.opportunity_id, token);
    if (data.status === 'conflict') return { status: 'conflict', current: value };
    if (canonical(value.doc) !== canonical(copy) || canonical(value.provenance) !== canonical(provenanceCopy)
      || (data.status === 'saved' && value.revision !== expectedRevision + 1)
      || (data.status === 'unchanged' && value.revision !== expectedRevision && value.revision !== expectedRevision + 1)) return { status: 'failed' };
    return { status: data.status as 'saved' | 'unchanged', value };
  } catch (error) {
    const failure = errorFor(error, token);
    return { status: failure.code === 'abandoned' ? 'abandoned' : failure.code === 'unavailable' ? 'unavailable' : 'failed' };
  }
}
