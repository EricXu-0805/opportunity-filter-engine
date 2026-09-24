import { getDeviceId, supabase } from './supabase';
import { isOwnerTokenValid, type OwnerToken } from './identity-owner';
import {
  validateTargetResume, verifyTargetResumeSignatures,
  type TargetResumeV1, type LoadedTargetResume, type TargetResumeSaveResult,
} from './target-resume';

export type { LoadedTargetResume, TargetResumeSaveResult } from './target-resume';
export interface TargetResumeVersionSummary { revision: number; updated_at: string }
export const TARGET_RESUME_HISTORY_LIMIT = 20;
const MAX_BYTES = 2 * 1024 * 1024;
export class TargetResumeReadError extends Error {
  constructor(public readonly code: 'abandoned' | 'unavailable' | 'failed' | 'invalid') {
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
  if (doc.opportunity_id !== opportunityId || !await verifyTargetResumeSignatures(doc)) throw new TargetResumeReadError('invalid');
  owner(token);
  return { ...meta, doc };
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

/** A successful null is absent; every failed or unreadable read rejects. */
export async function loadTargetResume(opportunityId: string, token: OwnerToken): Promise<LoadedTargetResume | null> {
  try {
    targetId(opportunityId); await ready(token);
    const { data, error } = await supabase.from('target_resumes').select('revision,doc,updated_at')
      .eq('owner_id', token.uid).eq('opportunity_id', opportunityId).maybeSingle();
    owner(token);
    if (error) throw new TargetResumeReadError('failed');
    return data === null ? null : await loaded(data, opportunityId, token);
  } catch (error) { throw errorFor(error, token); }
}

/** Recent metadata only; older rows are retained, not silently deleted. */
export async function loadTargetResumeHistory(opportunityId: string, token: OwnerToken, beforeRevision?: number): Promise<TargetResumeVersionSummary[]> {
  try {
    targetId(opportunityId);
    if (beforeRevision !== undefined && !positive(beforeRevision)) throw new TargetResumeReadError('invalid');
    await ready(token);
    let query = supabase.from('target_resume_versions').select('revision,updated_at')
      .eq('owner_id', token.uid).eq('opportunity_id', opportunityId);
    if (beforeRevision !== undefined) query = query.lt('revision', beforeRevision);
    const { data, error } = await query.order('revision', { ascending: false }).limit(TARGET_RESUME_HISTORY_LIMIT);
    owner(token);
    if (error) throw new TargetResumeReadError('failed');
    if (!Array.isArray(data) || data.length > TARGET_RESUME_HISTORY_LIMIT) throw new TargetResumeReadError('invalid');
    const result = data.map(summary);
    if (result.some((row, i) => (i > 0 && row.revision >= result[i - 1].revision)
      || (beforeRevision !== undefined && row.revision >= beforeRevision))) throw new TargetResumeReadError('invalid');
    return result;
  } catch (error) { throw errorFor(error, token); }
}

export async function loadTargetResumeVersion(opportunityId: string, revision: number, token: OwnerToken): Promise<LoadedTargetResume | null> {
  try {
    targetId(opportunityId);
    if (!positive(revision)) throw new TargetResumeReadError('invalid');
    await ready(token);
    const { data, error } = await supabase.from('target_resume_versions').select('revision,doc,updated_at')
      .eq('owner_id', token.uid).eq('opportunity_id', opportunityId).eq('revision', revision).maybeSingle();
    owner(token);
    if (error) throw new TargetResumeReadError('failed');
    if (data === null) return null;
    const result = await loaded(data, opportunityId, token);
    if (result.revision !== revision) throw new TargetResumeReadError('invalid');
    return result;
  } catch (error) { throw errorFor(error, token); }
}

/** One RPC atomically commits current + history. Restore uses this same CAS. */
export async function saveTargetResume(doc: TargetResumeV1, expectedRevision: number, token: OwnerToken): Promise<TargetResumeSaveResult> {
  try {
    owner(token);
    if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 0) return { status: 'failed' };
    const copy = snapshot(doc);
    targetId(copy.opportunity_id);
    const verified = await verifyTargetResumeSignatures(copy);
    owner(token);
    if (!verified) return { status: 'failed' };
    await ready(token);
    const { data, error } = await supabase.rpc('commit_target_resume_cas', {
      p_expected_owner: token.uid, p_opportunity_id: copy.opportunity_id,
      p_expected_revision: expectedRevision, p_doc: copy,
    });
    owner(token);
    if (error || !object(data)) return { status: 'failed' };
    if (data.status === 'missing') return { status: 'missing' };
    if (!['saved', 'unchanged', 'conflict'].includes(String(data.status))) return { status: 'failed' };
    const value = await loaded(data, copy.opportunity_id, token);
    if (data.status === 'conflict') return { status: 'conflict', current: value };
    if (canonical(value.doc) !== canonical(copy)
      || (data.status === 'saved' && value.revision !== expectedRevision + 1)
      || (data.status === 'unchanged' && value.revision !== expectedRevision && value.revision !== expectedRevision + 1)) return { status: 'failed' };
    return { status: data.status as 'saved' | 'unchanged', value };
  } catch (error) {
    const failure = errorFor(error, token);
    return { status: failure.code === 'abandoned' ? 'abandoned' : failure.code === 'unavailable' ? 'unavailable' : 'failed' };
  }
}
