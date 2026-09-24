import {
  validateTargetResume, verifyTargetResumeSignatures, type TargetResumeV1,
} from './target-resume';
import { resumeTextCharacters } from './resume-input';
import {
  FULL_TARGET_AI_VERSION, FULL_TARGET_AI_MAX_BODY_BYTES, FULL_TARGET_AI_MAX_UNITS,
  FULL_TARGET_AI_MAX_UNIT_CHARACTERS, FULL_TARGET_AI_MAX_EXPERIENCE_CHARACTERS,
  FULL_TARGET_AI_MAX_TARGET_CHARACTERS,
  type PreparedTargetResumeAi, type TargetResumeAiUnit, type TargetResumeAiReceipt,
  type TargetResumeAiRequest, type TargetResumeAiResponse,
  type TargetResumeAiPriority,
} from './target-resume-ai-protocol';

export type TargetResumeAIErrorCode = 'invalid_document' | 'invalid_signature' | 'signature_unavailable'
  | 'invalid_request' | 'invalid_response' | 'invalid_selection' | 'stale_document' | 'stale_context'
  | 'incomplete_structure' | 'document_too_large';
export type TargetResumeAIResult<T> = { ok: true; value: T } | { ok: false; code: TargetResumeAIErrorCode };
export interface TargetResumeAICurrentContext {
  profile_signature: string; source_signature: string; target_signature: string;
}
export interface TargetResumeAICoverage {
  total: number; protected: number; pending: number; suggested: number;
  unchanged: number; skipped: number; processed: number; complete: boolean;
}
export interface MergedTargetResumeAI {
  receipts: TargetResumeAiReceipt[]; coverage: TargetResumeAICoverage; structureReady: boolean;
}
export interface ApplyTargetResumeAIOptions {
  rewriteUnitIds: string[]; applyStructure: boolean; currentContext: TargetResumeAICurrentContext;
}
class Invalid extends Error {
  constructor(readonly code: TargetResumeAIErrorCode) { super(code); }
}
function fail(code: TargetResumeAIErrorCode): never { throw new Invalid(code); }
function failure(error: unknown, fallback: TargetResumeAIErrorCode): { ok: false; code: TargetResumeAIErrorCode } {
  return { ok: false, code: error instanceof Invalid ? error.code : fallback };
}
function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function shape(value: unknown, keys: readonly string[]): asserts value is Record<string, unknown> {
  if (!object(value) || Object.keys(value).length !== keys.length
    || keys.some((key) => !Object.hasOwn(value, key))) fail('invalid_response');
}
function text(value: unknown): asserts value is string {
  if (typeof value !== 'string') fail('invalid_response');
  for (const character of value) {
    const code = character.codePointAt(0)!;
    if (code === 0 || (code >= 0xd800 && code <= 0xdfff)) fail('invalid_response');
  }
}
/** Same compact JSON bytes as Python sort_keys=True, ensure_ascii=False.
 * Protocol object keys are ASCII; array order and all text remain exact. */
function canonical(value: unknown): string {
  const ancestors = new Set<object>();
  const walk = (item: unknown, depth: number): string => {
    if (depth > 32) fail('invalid_response');
    if (item === null) return 'null';
    if (typeof item === 'string') { text(item); return JSON.stringify(item); }
    if (typeof item === 'boolean') return JSON.stringify(item);
    if (typeof item === 'number') {
      if (!Number.isSafeInteger(item)) fail('invalid_response');
      return JSON.stringify(item);
    }
    if (!item || typeof item !== 'object' || ancestors.has(item)) fail('invalid_response');
    const proto = Object.getPrototypeOf(item);
    if (!Array.isArray(item) && proto !== Object.prototype && proto !== null) fail('invalid_response');
    ancestors.add(item);
    let serialized: string;
    if (Array.isArray(item)) {
      const values: string[] = [];
      for (let index = 0; index < item.length; index += 1) {
        if (!Object.hasOwn(item, index)) fail('invalid_response');
        values.push(walk(item[index], depth + 1));
      }
      serialized = `[${values.join(',')}]`;
    } else {
      const row = item as Record<string, unknown>;
      serialized = `{${Object.keys(row).sort().map((key) => {
        text(key); return `${JSON.stringify(key)}:${walk(row[key], depth + 1)}`;
      }).join(',')}}`;
    }
    ancestors.delete(item);
    return serialized;
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
function unitsFor(draft: TargetResumeV1): { units: TargetResumeAiUnit[]; protectedCount: number } {
  const units: TargetResumeAiUnit[] = [];
  let protectedCount = 0;
  for (const section of draft.document.sections) for (const block of section.blocks) for (const line of block.lines) {
    if (section.kind === 'basics') { protectedCount += 1; continue; }
    units.push({ unit_id: line.id, section_id: section.id, block_id: block.id,
      evidence: { ...line.evidence }, role: line.role, label: line.label,
      original: line.original, before_text: line.text });
  }
  return { units, protectedCount };
}
function skipped(unit: TargetResumeAiUnit, reason: TargetResumeAiReceipt['reason_code']): TargetResumeAiReceipt {
  return { unit_id: unit.unit_id, section_id: unit.section_id, block_id: unit.block_id,
    evidence: { ...unit.evidence }, before_text: unit.before_text, status: 'skipped', reason_code: reason, suggestion: null };
}
function same(left: unknown, right: unknown): boolean { return canonical(left) === canonical(right); }
function requirePrepared(prepared: PreparedTargetResumeAi): void {
  if (canonical(prepared.draft) !== prepared.canonical_draft) fail('invalid_request');
  const expected = unitsFor(prepared.draft);
  if (!same(expected.units, prepared.units) || expected.protectedCount !== prepared.protected_unit_count) fail('invalid_request');
}

/** Freeze one exact draft before hashing. All eligible lines are traversed;
 * call budgets make multiple batches, not a first-N document selection. */
export async function prepareTargetResumeAI(value: unknown): Promise<TargetResumeAIResult<PreparedTargetResumeAi>> {
  try {
    const checked = validateTargetResume(value);
    if (!checked.ok) fail(checked.code === 'document_too_large' ? 'document_too_large' : 'invalid_document');
    const draft = checked.value;
    const canonicalDraft = canonical(draft);
    if (!await verifyTargetResumeSignatures(draft)) fail('invalid_signature');
    let documentSignature: string;
    try {
      const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalDraft));
      documentSignature = `v1:sha256:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
    } catch { fail('signature_unavailable'); }
    const { units, protectedCount } = unitsFor(draft);
    const target = draft.target_snapshot;
    const targetTooLarge = [target.opportunity_id, target.title, target.organization, target.source_url,
      target.description, ...target.requirements].reduce((sum, field) => sum + resumeTextCharacters(field), 0) > FULL_TARGET_AI_MAX_TARGET_CHARACTERS;
    const batches: string[][] = [];
    const skippedUnits: TargetResumeAiReceipt[] = [];
    let batch: string[] = [];
    let characters = 0;
    let experienceCharacters = 0;
    for (const unit of units) {
      const length = resumeTextCharacters(unit.original);
      const experience = unit.evidence.kind === 'experience' ? length : 0;
      if (targetTooLarge || length > FULL_TARGET_AI_MAX_UNIT_CHARACTERS || experience > FULL_TARGET_AI_MAX_EXPERIENCE_CHARACTERS) {
        skippedUnits.push(skipped(unit, targetTooLarge ? 'target_too_large' : 'unit_too_large')); continue;
      }
      if (batch.length && (batch.length === FULL_TARGET_AI_MAX_UNITS
        || characters + length > FULL_TARGET_AI_MAX_UNIT_CHARACTERS
        || experienceCharacters + experience > FULL_TARGET_AI_MAX_EXPERIENCE_CHARACTERS)) {
        batches.push(batch); batch = []; characters = 0; experienceCharacters = 0;
      }
      batch.push(unit.unit_id); characters += length; experienceCharacters += experience;
    }
    if (batch.length) batches.push(batch);
    return { ok: true, value: freeze({ draft, canonical_draft: canonicalDraft, document_signature: documentSignature,
      units, protected_unit_count: protectedCount, batches, skipped: skippedUnits }) };
  } catch (error) { return failure(error, 'invalid_document'); }
}

const REASONS = new Set(['no_change', 'unit_too_large', 'context_too_large', 'target_too_large',
  'model_unavailable', 'invalid_model_response', 'ungrounded_rewrite', 'missing_result',
  'no_target_evidence', 'budget_exhausted', 'timeout']);
const PRIORITIES = new Set(['high', 'normal', 'low']);
function evidenceQuote(draft: TargetResumeV1, value: unknown): void {
  shape(value, ['field', 'requirement_index', 'start', 'end', 'quote']);
  text(value.quote);
  let source: string;
  if (value.field === 'description' && value.requirement_index === null) source = draft.target_snapshot.description;
  else if (value.field === 'requirement' && Number.isSafeInteger(value.requirement_index)
    && (value.requirement_index as number) >= 0 && (value.requirement_index as number) < draft.target_snapshot.requirements.length) {
    source = draft.target_snapshot.requirements[value.requirement_index as number];
  } else fail('invalid_response');
  if (!Number.isSafeInteger(value.start) || !Number.isSafeInteger(value.end)
    || (value.start as number) < 0 || (value.end as number) <= (value.start as number)
    || (value.end as number) > resumeTextCharacters(source) || !value.quote.trim()
    || Array.from(source).slice(value.start as number, value.end as number).join('') !== value.quote) fail('invalid_response');
}
function validateReceipt(prepared: PreparedTargetResumeAi, unit: TargetResumeAiUnit, value: unknown): TargetResumeAiReceipt {
  shape(value, ['unit_id', 'section_id', 'block_id', 'evidence', 'before_text', 'status', 'reason_code', 'suggestion']);
  if (value.unit_id !== unit.unit_id || value.section_id !== unit.section_id || value.block_id !== unit.block_id
    || !same(value.evidence, unit.evidence) || value.before_text !== unit.before_text
    || !['suggested', 'unchanged', 'skipped'].includes(String(value.status))
    || !(value.reason_code === null || REASONS.has(String(value.reason_code)))) fail('invalid_response');
  if (value.status === 'skipped') {
    if (value.suggestion !== null || value.reason_code === null || value.reason_code === 'no_change') fail('invalid_response');
  } else if (value.suggestion !== null) {
    if ((value.status === 'suggested' && value.reason_code !== null)
      || (value.status === 'unchanged' && value.reason_code !== 'no_change')) fail('invalid_response');
    shape(value.suggestion, ['priority', 'reason', 'target_evidence', 'proposed_text']);
    const suggestion = value.suggestion;
    text(suggestion.reason);
    if (!PRIORITIES.has(String(suggestion.priority)) || !suggestion.reason.trim()
      || !Array.isArray(suggestion.target_evidence) || suggestion.target_evidence.length === 0) fail('invalid_response');
    for (const quote of suggestion.target_evidence) evidenceQuote(prepared.draft, quote);
    if (suggestion.proposed_text !== null) {
      text(suggestion.proposed_text);
      if (unit.evidence.kind !== 'experience' || !suggestion.proposed_text.trim()
        || resumeTextCharacters(suggestion.proposed_text) > FULL_TARGET_AI_MAX_EXPERIENCE_CHARACTERS) fail('invalid_response');
    }
    if (value.status === 'unchanged' && suggestion.proposed_text !== null) fail('invalid_response');
  } else fail('invalid_response');
  return value as unknown as TargetResumeAiReceipt;
}

/** Wire verification is deliberately stricter than a TypeScript cast. It
 * cannot prove semantic entailment; only the server's fact checks plus the
 * student's explicit review can assess the proposed prose. */
export function validateTargetResumeAIResponse(prepared: PreparedTargetResumeAi,
  expected: Pick<TargetResumeAiRequest, 'request_id' | 'selected_unit_ids'>,
  response: unknown): TargetResumeAIResult<TargetResumeAiResponse> {
  try {
    requirePrepared(prepared);
    if (typeof expected.request_id !== 'string' || !expected.request_id.trim()
      || !Array.isArray(expected.selected_unit_ids) || !expected.selected_unit_ids.length
      || expected.selected_unit_ids.length > FULL_TARGET_AI_MAX_UNITS
      || new Set(expected.selected_unit_ids).size !== expected.selected_unit_ids.length) fail('invalid_request');
    const byId = new Map(prepared.units.map((unit) => [unit.unit_id, unit]));
    const eligible = new Set(prepared.batches.flat());
    if (expected.selected_unit_ids.some((id) => !byId.has(id) || !eligible.has(id))) fail('invalid_request');
    const selectedUnits = expected.selected_unit_ids.map((id) => byId.get(id)!);
    if (selectedUnits.reduce((sum, unit) => sum + resumeTextCharacters(unit.original), 0) > FULL_TARGET_AI_MAX_UNIT_CHARACTERS
      || selectedUnits.reduce((sum, unit) => sum + (unit.evidence.kind === 'experience' ? resumeTextCharacters(unit.original) : 0), 0)
        > FULL_TARGET_AI_MAX_EXPERIENCE_CHARACTERS) fail('invalid_request');
    const serialized = canonical(response);
    if (new TextEncoder().encode(serialized).byteLength > FULL_TARGET_AI_MAX_BODY_BYTES) fail('invalid_response');
    const value: unknown = JSON.parse(serialized);
    shape(value, ['version', 'pipeline_version', 'request_id', 'document_id', 'opportunity_id', 'document_signature',
      'base', 'manifest', 'method', 'logical_calls', 'provider_attempts_upper_bound', 'receipts']);
    if (value.version !== 1 || value.pipeline_version !== FULL_TARGET_AI_VERSION || value.request_id !== expected.request_id
      || value.document_id !== prepared.draft.id || value.opportunity_id !== prepared.draft.opportunity_id
      || value.document_signature !== prepared.document_signature || !same(value.base, prepared.draft.base)
      || !['ai', 'partial', 'unavailable'].includes(String(value.method))
      || ![0, 1].includes(value.logical_calls as number) || ![0, 2].includes(value.provider_attempts_upper_bound as number)
      || (value.logical_calls === 0) !== (value.provider_attempts_upper_bound === 0)) fail('invalid_response');
    shape(value.manifest, ['unit_ids', 'protected_unit_count']);
    if (!same(value.manifest.unit_ids, prepared.units.map((unit) => unit.unit_id))
      || value.manifest.protected_unit_count !== prepared.protected_unit_count
      || !Array.isArray(value.receipts) || value.receipts.length !== expected.selected_unit_ids.length) fail('invalid_response');
    const seen = new Set<string>();
    const selected = new Set(expected.selected_unit_ids);
    for (const item of value.receipts) {
      if (!object(item) || typeof item.unit_id !== 'string' || !selected.has(item.unit_id) || seen.has(item.unit_id)) fail('invalid_response');
      seen.add(item.unit_id);
      validateReceipt(prepared, byId.get(item.unit_id)!, item);
    }
    const skippedCount = value.receipts.filter((item) => (item as TargetResumeAiReceipt).status === 'skipped').length;
    if ((value.method === 'ai' && (skippedCount !== 0 || value.logical_calls !== 1))
      || (value.method === 'partial' && (skippedCount === 0 || skippedCount === value.receipts.length || value.logical_calls !== 1))
      || (value.method === 'unavailable' && skippedCount !== value.receipts.length)) fail('invalid_response');
    return { ok: true, value: freeze(value as unknown as TargetResumeAiResponse) };
  } catch (error) { return failure(error, 'invalid_response'); }
}

/** A failed unit may be explicitly retried. Successful advice is immutable
 * within a run: a conflicting duplicate cannot silently replace reviewed text. */
export function mergeTargetResumeAIResponses(prepared: PreparedTargetResumeAi,
  responses: readonly TargetResumeAiResponse[]): TargetResumeAIResult<MergedTargetResumeAI> {
  try {
    requirePrepared(prepared);
    const byId = new Map(prepared.units.map((unit) => [unit.unit_id, unit]));
    const receipts = new Map<string, TargetResumeAiReceipt>();
    for (const item of prepared.skipped) {
      const unit = byId.get(item.unit_id);
      if (!unit) fail('invalid_request');
      receipts.set(item.unit_id, validateReceipt(prepared, unit, item));
    }
    for (const response of responses) {
      const checked = validateTargetResumeAIResponse(prepared, {
        request_id: response.request_id, selected_unit_ids: response.receipts.map((item) => item.unit_id),
      }, response);
      if (!checked.ok) fail(checked.code);
      for (const receipt of checked.value.receipts) {
        const old = receipts.get(receipt.unit_id);
        if (old && old.status !== 'skipped' && !same(old, receipt)) fail('invalid_response');
        receipts.set(receipt.unit_id, receipt);
      }
    }
    const ordered = prepared.units.flatMap((unit) => receipts.has(unit.unit_id) ? [receipts.get(unit.unit_id)!] : []);
    const count = (status: TargetResumeAiReceipt['status']) => ordered.filter((item) => item.status === status).length;
    const suggested = count('suggested');
    const unchanged = count('unchanged');
    const processed = suggested + unchanged;
    const complete = prepared.units.length > 0 && processed === prepared.units.length;
    return { ok: true, value: freeze(clone({ receipts: ordered, coverage: { total: prepared.units.length,
      protected: prepared.protected_unit_count, pending: prepared.units.length - ordered.length,
      suggested, unchanged, skipped: count('skipped'), processed, complete }, structureReady: complete })) };
  } catch (error) { return failure(error, 'invalid_response'); }
}

const PRIORITY_WEIGHT: Record<TargetResumeAiPriority, number> = { high: 2, normal: 1, low: 0 };
/** Explicit application is atomic. Structure uses the arithmetic mean of all
 * reviewed unit priorities per whole block/section; ties retain CURRENT order. Basics stays first. No inclusion,
 * membership, fact value, original or provenance field is ever rewritten. */
export function applyTargetResumeAI(prepared: PreparedTargetResumeAi, currentDraft: unknown,
  responses: readonly TargetResumeAiResponse[], options: ApplyTargetResumeAIOptions): TargetResumeAIResult<TargetResumeV1> {
  try {
    requirePrepared(prepared);
    const context = options.currentContext;
    if (!context || context.profile_signature !== prepared.draft.base.profile_signature
      || context.source_signature !== prepared.draft.base.source_signature
      || context.target_signature !== prepared.draft.base.target_signature) fail('stale_context');
    if (canonical(currentDraft) !== prepared.canonical_draft) fail('stale_document');
    if (!Array.isArray(options.rewriteUnitIds) || new Set(options.rewriteUnitIds).size !== options.rewriteUnitIds.length
      || typeof options.applyStructure !== 'boolean') fail('invalid_selection');
    const merged = mergeTargetResumeAIResponses(prepared, responses);
    if (!merged.ok) fail(merged.code);
    if (options.applyStructure && !merged.value.structureReady) fail('incomplete_structure');
    const receipts = new Map(merged.value.receipts.map((receipt) => [receipt.unit_id, receipt]));
    const changes = new Map<string, string>();
    for (const id of options.rewriteUnitIds) {
      const receipt = receipts.get(id);
      if (!receipt || receipt.status !== 'suggested' || receipt.evidence.kind !== 'experience'
        || typeof receipt.suggestion?.proposed_text !== 'string') fail('invalid_selection');
      changes.set(id, receipt.suggestion.proposed_text);
    }
    const draft = clone(prepared.draft);
    for (const section of draft.document.sections) for (const block of section.blocks) for (const line of block.lines) {
      const replacement = changes.get(line.id);
      if (replacement !== undefined) line.text = replacement;
    }
    if (options.applyStructure) {
      const score = (ids: string[]) => ids.length ? ids.reduce((sum, id) =>
        sum + PRIORITY_WEIGHT[receipts.get(id)!.suggestion!.priority], 0) / ids.length : 1;
      for (const section of draft.document.sections) {
        if (section.kind === 'basics') continue;
        section.blocks = section.blocks.map((block, index) => ({ block, index, score: score(block.lines.map((line) => line.id)) }))
          .sort((a, b) => b.score - a.score || a.index - b.index).map(({ block }) => block);
      }
      draft.document.sections = draft.document.sections.map((section, index) => ({ section, index,
        score: section.kind === 'basics' ? 0 : score(section.blocks.flatMap((block) => block.lines.map((line) => line.id))) }))
        .sort((a, b) => Number(b.section.kind === 'basics') - Number(a.section.kind === 'basics')
          || b.score - a.score || a.index - b.index).map(({ section }) => section);
    }
    const checked = validateTargetResume(draft);
    if (!checked.ok) fail(checked.code === 'document_too_large' ? 'document_too_large' : 'invalid_document');
    return { ok: true, value: checked.value };
  } catch (error) { return failure(error, 'invalid_document'); }
}
