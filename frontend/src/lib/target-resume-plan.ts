import { parseTargetResumeSupportGroups, targetResumeSupportEvidence, type TargetResumeSupportGroup } from './target-resume-support';
import { isTargetResumeEvidence } from './target-resume-evidence';
import { isActiveExperience } from './experience-evidence';
import { resumeTextCharacters } from './resume-input';
import {
  isCurrentTargetResumeContext, validateTargetResume, verifyTargetResumeSignatures,
  type TargetResumeV1,
} from './target-resume';
import {
  TARGET_RESUME_PLAN_VERSION, TARGET_RESUME_PLAN_MAX_BODY_BYTES,
  type PreparedTargetResumePlan, type TargetResumePlanOptions, type TargetResumePlanManifestItem,
  type TargetResumePlanScope, type TargetResumePlanRequest, type TargetResumePlanResponse,
  type ApplyTargetResumePlanOptions,
} from './target-resume-plan-protocol';

export type TargetResumePlanErrorCode = 'invalid_document' | 'document_too_large' | 'invalid_signature'
  | 'signature_unavailable' | 'legacy_target_context' | 'invalid_options' | 'invalid_request'
  | 'invalid_response' | 'invalid_selection' | 'incomplete_plan' | 'stale_document' | 'stale_context';
export type TargetResumePlanResult<T> = { ok: true; value: T } | { ok: false; code: TargetResumePlanErrorCode };
class Invalid extends Error {
  constructor(readonly code: TargetResumePlanErrorCode) { super(code); }
}
function fail(code: TargetResumePlanErrorCode): never { throw new Invalid(code); }
function failure(error: unknown, fallback: TargetResumePlanErrorCode): { ok: false; code: TargetResumePlanErrorCode } {
  return { ok: false, code: error instanceof Invalid ? error.code : fallback };
}
function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function shape(value: unknown, keys: readonly string[], code: TargetResumePlanErrorCode = 'invalid_response'): asserts value is Record<string, unknown> {
  if (!object(value) || Object.keys(value).length !== keys.length || keys.some(key => !Object.hasOwn(value, key))) fail(code);
}
function text(value: unknown): asserts value is string {
  if (typeof value !== 'string') fail('invalid_response');
  for (const character of value) {
    const code = character.codePointAt(0)!;
    if (code === 0 || code >= 0xd800 && code <= 0xdfff) fail('invalid_response');
  }
}
/** Exact canonical JSON, matching the shared Python protocol. Text and array
 * order remain untouched; invalid values are rejected rather than omitted. */
function canonical(value: unknown): string {
  const parents = new Set<object>();
  const walk = (item: unknown, depth: number): string => {
    if (depth > 32) fail('invalid_response');
    if (item === null) return 'null';
    if (typeof item === 'string') { text(item); return JSON.stringify(item); }
    if (typeof item === 'boolean') return JSON.stringify(item);
    if (typeof item === 'number' && Number.isSafeInteger(item)) return JSON.stringify(item);
    if (!item || typeof item !== 'object' || parents.has(item)) fail('invalid_response');
    const proto = Object.getPrototypeOf(item);
    if (!Array.isArray(item) && proto !== Object.prototype && proto !== null) fail('invalid_response');
    parents.add(item);
    let result: string;
    if (Array.isArray(item)) {
      const values: string[] = [];
      for (let index = 0; index < item.length; index += 1) {
        if (!Object.hasOwn(item, index)) fail('invalid_response');
        values.push(walk(item[index], depth + 1));
      }
      result = `[${values.join(',')}]`;
    } else {
      const row = item as Record<string, unknown>;
      result = `{${Object.keys(row).sort().map(key => {
        text(key); return `${JSON.stringify(key)}:${walk(row[key], depth + 1)}`;
      }).join(',')}}`;
    }
    parents.delete(item);
    return result;
  };
  return walk(value, 0);
}
function clone<T>(value: T): T { return JSON.parse(canonical(value)) as T; }
function freeze<T>(value: T): T {
  if (value && typeof value === 'object') {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}
function same(left: unknown, right: unknown): boolean { return canonical(left) === canonical(right); }
function options(value: unknown, code: TargetResumePlanErrorCode = 'invalid_options'): asserts value is TargetResumePlanOptions {
  shape(value, ['target_pages'], code);
  if (value.target_pages !== 1 && value.target_pages !== 2) fail(code);
}

/** Includes hidden blocks and lines. Basics remain protected outside the plan. */
export function targetResumePlanManifest(draft: TargetResumeV1): TargetResumePlanManifestItem[] {
  return draft.document.sections.filter(section => section.kind !== 'basics').flatMap(section =>
    section.blocks.map(block => ({ section_id: section.id, block_id: block.id, line_ids: block.lines.map(line => line.id) })));
}
/** Coverage is explicitly narrower than all imported material. Stale and
 * pending sources remain visible in scope, never silently promoted to facts. */
export function targetResumePlanScope(draft: TargetResumeV1): TargetResumePlanScope {
  const referenced = new Set(draft.document.sections.filter(section => section.kind !== 'basics')
    .flatMap(section => section.blocks.flatMap(block => block.lines.filter(line => line.evidence.kind === 'experience').map(line => line.evidence.id))));
  const scope: TargetResumePlanScope = { unreferenced_experience_ids: [], pending_experience_ids: [], stale_experience_ids: [],
    unmapped_range_count: draft.base_snapshot.resume_master.unmapped_ranges.length };
  const context = { rawText: draft.base_snapshot.resume_text, expectedDigest: draft.base.source_signature };
  for (const entry of draft.base_snapshot.experience_entries) {
    if (entry.status === 'candidate') scope.pending_experience_ids.push(entry.id);
    else if (entry.status === 'confirmed') {
      if (!isActiveExperience(entry, context)) scope.stale_experience_ids.push(entry.id);
      else if (!referenced.has(entry.id)) scope.unreferenced_experience_ids.push(entry.id);
    }
  }
  return scope;
}
/** Visible text codepoints, including existing whitespace. No headings, labels,
 * synthetic separators, or page-count estimate are added. */
export function measureTargetResumeLength(draft: TargetResumeV1): number {
  return draft.document.sections.filter(section => section.included).reduce((total, section) => total
    + section.blocks.filter(block => block.included).reduce((sum, block) => sum
      + block.lines.filter(line => line.included).reduce((count, line) => count + resumeTextCharacters(line.text), 0), 0), 0);
}
function requirePrepared(prepared: PreparedTargetResumePlan): void {
  shape(prepared, ['draft', 'canonical_draft', 'document_signature', 'options', 'manifest', 'scope', ...(Object.hasOwn(prepared,'support_groups') ? ['support_groups'] : [])], 'invalid_request');
  if (prepared.support_groups !== undefined) {
    const parsed = parseTargetResumeSupportGroups(prepared.draft, prepared.support_groups);
    if (parsed === null || !same(parsed, prepared.support_groups)) fail('invalid_request');
  }
  options(prepared.options, 'invalid_request');
  const checked = validateTargetResume(prepared.draft);
  if (!checked.ok) fail('invalid_request');
  if (!isCurrentTargetResumeContext(checked.value.target_snapshot)) fail('legacy_target_context');
  if (typeof prepared.document_signature !== 'string' || !/^v1:sha256:[a-f0-9]{64}$/.test(prepared.document_signature)
    || canonical(checked.value) !== prepared.canonical_draft
    || !same(prepared.manifest, targetResumePlanManifest(checked.value))
    || !same(prepared.scope, targetResumePlanScope(checked.value))) fail('invalid_request');
  const blocks = prepared.manifest.map(item => item.block_id);
  const lines = prepared.manifest.flatMap(item => item.line_ids);
  if (new Set(blocks).size !== blocks.length || new Set(lines).size !== lines.length) fail('invalid_request');
}

/** Capture both the entire draft and options before the first await. Whole
 * prompt capacity belongs to the server; preparation never takes a first N. */
export async function prepareTargetResumePlan(value: unknown, settings: TargetResumePlanOptions, supportGroups?: TargetResumeSupportGroup[]): Promise<TargetResumePlanResult<PreparedTargetResumePlan>> {
  try {
    options(settings);
    const capturedOptions = clone(settings);
    const checked = validateTargetResume(value);
    if (!checked.ok) fail(checked.code === 'document_too_large' ? 'document_too_large' : 'invalid_document');
    const draft = checked.value;
    if (!isCurrentTargetResumeContext(draft.target_snapshot)) fail('legacy_target_context');
    const capturedGroups = supportGroups === undefined ? undefined : parseTargetResumeSupportGroups(draft,supportGroups);
    if (capturedGroups === null) fail('invalid_request');
    const canonicalDraft = canonical(draft);
    if (!await verifyTargetResumeSignatures(draft)) fail('invalid_signature');
    let signature: string;
    try {
      const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalDraft));
      signature = `v1:sha256:${Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')}`;
    } catch { fail('signature_unavailable'); }
    const prepared = { draft, canonical_draft: canonicalDraft, document_signature: signature, options: capturedOptions,
      manifest: targetResumePlanManifest(draft), scope: targetResumePlanScope(draft), ...(capturedGroups === undefined ? {} : {support_groups:capturedGroups}) };
    requirePrepared(prepared);
    return { ok: true, value: freeze(prepared) };
  } catch (error) { return failure(error, 'invalid_document'); }
}

const REASONS = new Set(['context_too_large', 'target_too_large', 'interests_too_large', 'no_plan_items', 'budget_exhausted',
  'model_unavailable', 'timeout', 'invalid_model_response', 'no_target_evidence', 'no_source_evidence']);
function quote(source: string, value: Record<string, unknown>): void {
  text(value.quote);
  if (!Number.isSafeInteger(value.start) || !Number.isSafeInteger(value.end)
    || (value.start as number) < 0 || (value.end as number) <= (value.start as number)
    || (value.end as number) > resumeTextCharacters(source) || !value.quote.trim()
    || Array.from(source).slice(value.start as number, value.end as number).join('') !== value.quote) fail('invalid_response');
}
function validateItem(prepared: PreparedTargetResumePlan, manifest: TargetResumePlanManifestItem, value: unknown): void {
  shape(value, ['section_id', 'block_id', 'action', 'reason', 'target_evidence', 'source_evidence', 'rewrites']);
  if (value.section_id !== manifest.section_id || value.block_id !== manifest.block_id
    || !['keep', 'compress', 'omit'].includes(String(value.action))) fail('invalid_response');
  text(value.reason);
  if (!value.reason.trim() || !Array.isArray(value.target_evidence) || !value.target_evidence.length
    || !Array.isArray(value.source_evidence) || !value.source_evidence.length || !Array.isArray(value.rewrites)) fail('invalid_response');
  const target = prepared.draft.target_snapshot;
  for (const item of value.target_evidence) {
    if (!isTargetResumeEvidence(target, item)) fail('invalid_response');
  }
  const block = prepared.draft.document.sections.find(section => section.id === manifest.section_id)!.blocks.find(block => block.id === manifest.block_id)!;
  const lines = new Map(block.lines.map(line => [line.id, line]));
  for (const item of value.source_evidence) {
    shape(item, ['unit_id', 'start', 'end', 'quote']);
    if (typeof item.unit_id !== 'string' || !lines.has(item.unit_id)) fail('invalid_response');
    quote(lines.get(item.unit_id)!.original, item);
  }
  // v5 proposes no wording: an older server's unreviewed shorter or combined wording is never shown or applied.
  if (value.rewrites.length) fail('invalid_response');
}

/** This verifies the wire contract and source locations, not semantic truth.
 * The plan carries no wording (v5); the user reviews each content choice before applying. */
export function validateTargetResumePlanResponse(prepared: PreparedTargetResumePlan,
  request: Pick<TargetResumePlanRequest, 'request_id' | 'options' | 'support_groups'>, response: unknown): TargetResumePlanResult<TargetResumePlanResponse> {
  try {
    requirePrepared(prepared);
    if (!request || typeof request.request_id !== 'string' || !request.request_id.trim()) fail('invalid_request');
    if (!same(request.support_groups ?? null, prepared.support_groups ?? null)) fail('invalid_request');
    options(request.options, 'invalid_request');
    if (!same(request.options, prepared.options)) fail('invalid_request');
    if ('document_signature' in request && request.document_signature !== prepared.document_signature) fail('invalid_request');
    if ('draft' in request && canonical(request.draft) !== prepared.canonical_draft) fail('invalid_request');
    const serialized = canonical(response);
    if (new TextEncoder().encode(serialized).byteLength > TARGET_RESUME_PLAN_MAX_BODY_BYTES) fail('invalid_response');
    const value: unknown = JSON.parse(serialized);
    const checkKeys = object(value) && Object.hasOwn(value, 'check_version') ? ['check_version'] : [];
    shape(value, ['version', 'pipeline_version', 'request_id', 'document_id', 'opportunity_id', 'document_signature',
      'base', 'options', 'manifest', 'scope', 'method', 'complete', 'reason_code', 'logical_calls', 'provider_attempts_upper_bound', 'items', ...checkKeys, ...(prepared.support_groups === undefined ? [] : ['support_groups'])]);
    if (!same(value.support_groups ?? null,prepared.support_groups ?? null)) fail('invalid_response');
    if (checkKeys.length && value.check_version !== null
      && (typeof value.check_version !== 'string' || !/^target-resume-source-checks-v[1-9][0-9]{0,5}$/.test(value.check_version))) fail('invalid_response');
    if (value.version !== 1 || value.pipeline_version !== TARGET_RESUME_PLAN_VERSION || value.request_id !== request.request_id
      || value.document_id !== prepared.draft.id || value.opportunity_id !== prepared.draft.opportunity_id
      || value.document_signature !== prepared.document_signature || !same(value.base, prepared.draft.base)
      || !same(value.options, prepared.options) || !same(value.manifest, prepared.manifest) || !same(value.scope, prepared.scope)
      || !Array.isArray(value.items) || ![0, 1].includes(value.logical_calls as number)
      || ![0, 2].includes(value.provider_attempts_upper_bound as number)
      || (value.logical_calls === 0) !== (value.provider_attempts_upper_bound === 0)) fail('invalid_response');
    if (value.method === 'unavailable') {
      if (value.complete !== false || value.items.length || !REASONS.has(String(value.reason_code))) fail('invalid_response');
    } else if (value.method === 'ai') {
      if (value.complete !== true || value.reason_code !== null || value.logical_calls !== 1
        || !prepared.manifest.length || value.items.length !== prepared.manifest.length) fail('invalid_response');
      const blocks = new Map(prepared.manifest.map(item => [item.block_id, item]));
      const seen = new Set<string>();
      for (const item of value.items) {
        if (!object(item) || typeof item.block_id !== 'string' || seen.has(item.block_id) || !blocks.has(item.block_id)) fail('invalid_response');
        seen.add(item.block_id); validateItem(prepared, blocks.get(item.block_id)!, item);
      }
    } else fail('invalid_response');
    return { ok: true, value: freeze(value as unknown as TargetResumePlanResponse) };
  } catch (error) { return failure(error, 'invalid_response'); }
}

/** An explicit atomic choice changes only block inclusion and selected
 * experience text. Originals, provenance, all nodes, order, and the master
 * stay intact. Owner/session fences belong to the caller around this pure step. */
export function applyTargetResumePlan(prepared: PreparedTargetResumePlan, currentDraft: unknown, response: unknown,
  selection: ApplyTargetResumePlanOptions): TargetResumePlanResult<TargetResumeV1> {
  try {
    requirePrepared(prepared);
    if (canonical(currentDraft) !== prepared.canonical_draft) fail('stale_document');
    shape(selection, ['selection_block_ids', 'rewrite_unit_ids', 'current_context', 'options', ...(Object.hasOwn(selection,'support_groups') ? ['support_groups'] : [])], 'invalid_selection');
    if (!same(selection.support_groups ?? [],prepared.support_groups ?? [])) fail('stale_context');
    options(selection.options, 'invalid_options');
    if (!same(selection.options, prepared.options)) fail('stale_context');
    shape(selection.current_context, ['profile_signature', 'source_signature', 'target_signature'], 'stale_context');
    for (const key of ['profile_signature', 'source_signature', 'target_signature'] as const) {
      if (selection.current_context[key] !== prepared.draft.base[key]) fail('stale_context');
    }
    for (const ids of [selection.selection_block_ids, selection.rewrite_unit_ids]) {
      if (!Array.isArray(ids) || ids.some(id => typeof id !== 'string') || new Set(ids).size !== ids.length) fail('invalid_selection');
    }
    if (!selection.selection_block_ids.length && !selection.rewrite_unit_ids.length) fail('invalid_selection');
    const requestId = object(response) && typeof response.request_id === 'string' ? response.request_id : '';
    const checked = validateTargetResumePlanResponse(prepared, { request_id: requestId, options: prepared.options, ...(prepared.support_groups === undefined ? {} : {support_groups:prepared.support_groups}) }, response);
    if (!checked.ok) fail(checked.code);
    if (!checked.value.complete || checked.value.method !== 'ai') fail('incomplete_plan');
    const items = new Map(checked.value.items.map(item => [item.block_id, item]));
    const included = new Map<string, boolean>();
    for (const id of selection.selection_block_ids) {
      const item = items.get(id);
      if (!item) fail('invalid_selection');
      included.set(id, item.action !== 'omit');
    }
    const rewrites = new Map(checked.value.items.flatMap(item => item.rewrites.map(rewrite => [rewrite.unit_id, rewrite] as const)));
    const changes = new Map<string, string>();
    for (const id of selection.rewrite_unit_ids) {
      const rewrite = rewrites.get(id);
      if (!rewrite || rewrite.status !== 'suggested' || typeof rewrite.proposed_text !== 'string') fail('invalid_selection');
      changes.set(id, rewrite.proposed_text);
    }
    const draft = clone(prepared.draft);
    for (const section of draft.document.sections) for (const block of section.blocks) {
      if (included.has(block.id)) block.included = included.get(block.id)!;
      for (const line of block.lines) if (changes.has(line.id)) line.text = changes.get(line.id)!;
    }
    const valid = validateTargetResume(draft);
    if (!valid.ok) fail(valid.code === 'document_too_large' ? 'document_too_large' : 'invalid_document');
    return { ok: true, value: valid.value };
  } catch (error) { return failure(error, 'invalid_document'); }
}
