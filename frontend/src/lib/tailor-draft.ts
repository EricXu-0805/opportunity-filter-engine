import type { Opportunity, ProfileData, ResumeProcessingCoverage } from './types';
import { isPublicDetail } from './public-target-shape';

/** Local provenance/comparison rules, distinct from the server pipeline version. */
export const TAILOR_DRAFT_RULE_VERSION = 'tailor-draft-v2';
const DIGEST = /^[0-9a-f]{64}$/;
const ORIGIN_KINDS = ['unknown', 'heuristic', 'extract', 'manual', 'reviewed_output'] as const;
const ORIGIN_KIND_SET: ReadonlySet<string> = new Set(ORIGIN_KINDS);
export type TailorDraftOriginKind = typeof ORIGIN_KINDS[number];
export interface TailorDraftBinding {
  profile_sig: string;
  target_sig: string;
  resume_sig: string;
  pipeline_version: string;
  rule_version: string;
}
/** The evidence behind one draft line: after "Use kept as new originals" a line
 * holds reviewed wording, and its source is still the student's own bullet. */
export interface TailorDraftSource { line: string; source: string }
/** Version 2 records (no sources) decode unchanged; new records are version 3. */
export interface TailorDraft {
  version: 2 | 3;
  owner_id: string;
  opportunity_id: string;
  text: string;
  origin: { kind: TailorDraftOriginKind; binding: TailorDraftBinding | null };
  /** Explicit review of this exact text alongside these materials, not a fact attestation. */
  review: { text_sig: string; binding: TailorDraftBinding } | null;
  processing?: ResumeProcessingCoverage;
  /** Only lines whose source differs from their text; a line typed or edited since has none. */
  sources?: TailorDraftSource[];
}
export type TailorDraftDecodeResult =
  | { status: 'stored'; draft: TailorDraft }
  | { status: 'legacy'; draft: TailorDraft }
  | { status: 'invalid' | 'foreign' };
export class TailorDraftError extends Error {
  constructor(public readonly code: 'invalid_draft' | 'invalid_binding' | 'invalid_profile' | 'invalid_target' | 'invalid_json' | 'signature_unavailable') {
    super('The draft source could not be verified. Your text is kept.');
    this.name = 'TailorDraftError';
  }
}
function fail(code: TailorDraftError['code']): never { throw new TailorDraftError(code); }
function record(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function keys(value: Record<string, unknown>, required: readonly string[], optional: readonly string[] = []): boolean {
  return required.every(key => Object.hasOwn(value, key)) && Object.keys(value).every(key => required.includes(key) || optional.includes(key));
}
function text(value: unknown): value is string {
  if (typeof value !== 'string' || value.includes('\0')) return false;
  for (const character of value) {
    const point = character.codePointAt(0)!;
    if (point >= 0xd800 && point <= 0xdfff) return false;
  }
  return true;
}
function nonempty(value: unknown): value is string { return text(value) && value.trim().length > 0; }
/** JSON values only: no Date/toJSON conversion, sparse arrays, coercion or lost finite values. */
function canonical(value: unknown, omitUndefined = false): string {
  const ancestors = new Set<object>();
  const walk = (item: unknown, depth: number): string => {
    if (depth > 32) fail('invalid_json');
    if (item === null) return 'null';
    if (typeof item === 'string') { if (!text(item)) fail('invalid_json'); return JSON.stringify(item); }
    if (typeof item === 'boolean') return JSON.stringify(item);
    if (typeof item === 'number') { if (!Number.isFinite(item)) fail('invalid_json'); return JSON.stringify(item); }
    if (typeof item !== 'object' || ancestors.has(item)) fail('invalid_json');
    const prototype = Object.getPrototypeOf(item);
    if (!Array.isArray(item) && prototype !== Object.prototype && prototype !== null) fail('invalid_json');
    ancestors.add(item);
    let output: string;
    if (Array.isArray(item)) {
      const values: string[] = [];
      for (let i = 0; i < item.length; i += 1) {
        if (!Object.hasOwn(item, i)) fail('invalid_json');
        values.push(walk(item[i], depth + 1));
      }
      output = `[${values.join(',')}]`;
    } else {
      const object = item as Record<string, unknown>;
      output = `{${Object.keys(object).filter(key => !omitUndefined || object[key] !== undefined).sort().map(key => {
        if (!text(key)) fail('invalid_json');
        return `${JSON.stringify(key)}:${walk(object[key], depth + 1)}`;
      }).join(',')}}`;
    }
    ancestors.delete(item);
    return output;
  };
  return walk(value, 0);
}
async function digest(value: string): Promise<string> {
  try {
    const result = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return Array.from(new Uint8Array(result), byte => byte.toString(16).padStart(2, '0')).join('');
  } catch { return fail('signature_unavailable'); }
}
function binding(value: unknown): value is TailorDraftBinding {
  return record(value) && keys(value, ['profile_sig', 'target_sig', 'resume_sig', 'pipeline_version', 'rule_version'])
    && ['profile_sig', 'target_sig', 'resume_sig'].every(key => typeof value[key] === 'string' && DIGEST.test(value[key]))
    && nonempty(value.pipeline_version) && nonempty(value.rule_version);
}
function bindingCopy(value: unknown): TailorDraftBinding {
  const copy: unknown = JSON.parse(canonical(value));
  if (!binding(copy)) fail('invalid_binding');
  return copy;
}
function processing(value: unknown): value is ResumeProcessingCoverage {
  const count = (item: unknown): item is number => Number.isSafeInteger(item) && (item as number) >= 0;
  if (!record(value) || !keys(value, ['input_characters', 'chunks', 'ai_chunks', 'heuristic_chunks'])
    || !count(value.input_characters) || !count(value.ai_chunks) || !count(value.heuristic_chunks) || !Array.isArray(value.chunks)) return false;
  let ai = 0; let heuristic = 0;
  for (const chunk of value.chunks) {
    if (!record(chunk) || !keys(chunk, ['start', 'end', 'method'], ['reason'])
      || !count(chunk.start) || !count(chunk.end) || chunk.end < chunk.start || chunk.end > value.input_characters
      || (chunk.method !== 'ai' && chunk.method !== 'heuristic')
      || (chunk.reason !== undefined && chunk.reason !== null && !text(chunk.reason))) return false;
    if (chunk.method === 'ai') ai += 1; else heuristic += 1;
  }
  return ai === value.ai_chunks && heuristic === value.heuristic_chunks;
}
function sources(value: unknown): value is TailorDraftSource[] {
  return Array.isArray(value) && value.length > 0 && value.every(item => record(item) && keys(item, ['line', 'source'])
    && nonempty(item.line) && nonempty(item.source) && item.line !== item.source);
}
function draftCopy(value: unknown): TailorDraft {
  const copy: unknown = JSON.parse(canonical(value));
  if (!record(copy) || !keys(copy, ['version', 'owner_id', 'opportunity_id', 'text', 'origin', 'review'], ['processing', 'sources'])
    || (copy.version !== 2 && copy.version !== 3) || (copy.version === 2 && Object.hasOwn(copy, 'sources'))
    || (copy.sources !== undefined && !sources(copy.sources))
    || !nonempty(copy.owner_id) || !nonempty(copy.opportunity_id) || !text(copy.text)
    || !record(copy.origin) || !keys(copy.origin, ['kind', 'binding']) || typeof copy.origin.kind !== 'string'
    || !ORIGIN_KIND_SET.has(copy.origin.kind)
    || (copy.origin.binding !== null && !binding(copy.origin.binding))
    || (copy.origin.kind === 'unknown' && copy.origin.binding !== null)
    || (copy.review !== null && (!record(copy.review) || !keys(copy.review, ['text_sig', 'binding'])
      || typeof copy.review.text_sig !== 'string' || !DIGEST.test(copy.review.text_sig) || !binding(copy.review.binding)))
    || (copy.processing !== undefined && !processing(copy.processing))) fail('invalid_draft');
  return copy as unknown as TailorDraft;
}

/** Capture complete materials synchronously, before any SHA promise can yield. */
export async function createBinding(profile: ProfileData, target: Opportunity | null, pipelineVersion: string): Promise<TailorDraftBinding> {
  if (!record(profile) || (profile.resume_text !== undefined && !text(profile.resume_text))) fail('invalid_profile');
  if (!nonempty(pipelineVersion)) fail('invalid_binding');
  const profileJson = canonical(profile, true);
  const targetJson = canonical(target);
  const profileCopy: ProfileData = JSON.parse(profileJson);
  const targetCopy: unknown = JSON.parse(targetJson);
  if (!record(targetCopy) || !nonempty(targetCopy.id) || !isPublicDetail(targetCopy, targetCopy.id)) fail('invalid_target');
  const resumeText = profileCopy.resume_text ?? '';
  const [profile_sig, target_sig, resume_sig] = await Promise.all([digest(profileJson), digest(targetJson), digest(resumeText)]);
  return { profile_sig, target_sig, resume_sig, pipeline_version: pipelineVersion, rule_version: TAILOR_DRAFT_RULE_VERSION };
}
export function createDraft(ownerId: string, opportunityId: string, value: string, kind: TailorDraftOriginKind,
  originBinding: TailorDraftBinding | null, coverage?: ResumeProcessingCoverage, lineSources: TailorDraftSource[] = []): TailorDraft {
  const kept = lineSources.filter(item => item.line !== item.source);
  return draftCopy({ version: 3, owner_id: ownerId, opportunity_id: opportunityId, text: value,
    origin: { kind, binding: originBinding }, review: null, ...(coverage === undefined ? {} : { processing: coverage }),
    ...(kept.length ? { sources: kept } : {}) });
}
/** Editing does not reattach old text to newer sources or renew an earlier review. */
export function editDraft(draft: TailorDraft, value: string): TailorDraft {
  const copy = draftCopy(draft);
  return draftCopy({ ...copy, text: value });
}
/** Each line's evidence: its recorded source while the line is exactly as promoted, else itself. */
export function draftLineSources(draft: TailorDraft, lines: readonly string[]): string[] {
  const recorded = new Map<string, string>();
  for (const item of draft.sources ?? []) if (!recorded.has(item.line)) recorded.set(item.line, item.source);
  return lines.map(line => recorded.get(line) ?? line);
}
export async function reviewDraft(draft: TailorDraft, currentBinding: TailorDraftBinding): Promise<TailorDraft> {
  const copy = draftCopy(draft); const checked = bindingCopy(currentBinding);
  const text_sig = await digest(copy.text);
  return { ...copy, review: { text_sig, binding: checked } };
}
export async function compareDraft(draft: TailorDraft, currentBinding: TailorDraftBinding): Promise<'current' | 'stale' | 'unknown'> {
  const copy = draftCopy(draft); const checked = bindingCopy(currentBinding);
  const current = canonical(checked);
  // Once explicitly reviewed, that exact-text decision is authoritative.
  // The immutable origin remains historical metadata, never a fallback that
  // can certify later edits or a return to earlier materials.
  if (copy.review !== null) {
    return canonical(copy.review.binding) === current && copy.review.text_sig === await digest(copy.text)
      ? 'current' : 'stale';
  }
  if (copy.origin.binding !== null && canonical(copy.origin.binding) === current) return 'current';
  return copy.origin.binding === null ? 'unknown' : 'stale';
}
export function encodeDraft(draft: TailorDraft): string { return canonical(draftCopy(draft)); }
/** This parser handles a value from an already owner-scoped slot. It never reads or migrates ownerless slots. */
export function decodeDraft(raw: string, ownerId: string, opportunityId: string): TailorDraftDecodeResult {
  try {
    if (!text(raw) || !nonempty(ownerId) || !nonempty(opportunityId)) return { status: 'invalid' };
    let parsed: unknown;
    try { parsed = JSON.parse(raw); } catch { return { status: 'legacy', draft: createDraft(ownerId, opportunityId, raw, 'unknown', null) }; }
    if (record(parsed) && Object.hasOwn(parsed, 'version')) {
      const checked = draftCopy(parsed);
      if (checked.owner_id !== ownerId || checked.opportunity_id !== opportunityId) return { status: 'foreign' };
      return { status: 'stored', draft: checked };
    }
    if (record(parsed) && Object.hasOwn(parsed, 't')) {
      if (!keys(parsed, ['t'], ['s']) || !text(parsed.t) || (parsed.s !== undefined && parsed.s !== null && !text(parsed.s))) return { status: 'invalid' };
      return { status: 'legacy', draft: createDraft(ownerId, opportunityId, parsed.t, 'unknown', null) };
    }
    return { status: 'legacy', draft: createDraft(ownerId, opportunityId, raw, 'unknown', null) };
  } catch { return { status: 'invalid' }; }
}
