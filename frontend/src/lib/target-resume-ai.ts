import { parseTargetResumeSupportGroups, supportGroupsForUnits, supportSourceIds, targetResumeSupportEvidence, type TargetResumeSupportGroup } from './target-resume-support';
import { isTargetResumeEvidence } from './target-resume-evidence';
import {
  validateTargetResume, verifyTargetResumeSignatures, isCurrentTargetResumeContext, type TargetResumeV1,
} from './target-resume';
import { resumeTextCharacters } from './resume-input';
import {
  FULL_TARGET_AI_VERSION, FULL_TARGET_AI_MAX_BODY_BYTES, FULL_TARGET_AI_MAX_UNITS, FULL_TARGET_AI_MAX_EXPERIENCE_UNITS,
  FULL_TARGET_AI_MAX_UNIT_CHARACTERS, FULL_TARGET_AI_MAX_EXPERIENCE_CHARACTERS,
  FULL_TARGET_AI_MAX_TARGET_CHARACTERS, FULL_TARGET_AI_MAX_PROMPT_CHARACTERS, FULL_TARGET_AI_MAX_INTERESTS_CHARACTERS,
  FULL_TARGET_AI_SYSTEM_PROMPT_CHARACTERS, FULL_TARGET_AI_MAX_ANCHORS, TARGET_RESUME_AI_OPS,
  type PreparedTargetResumeAi, type TargetResumeAiUnit, type TargetResumeAiReceipt,
  type TargetResumeAiRequest, type TargetResumeAiResponse,
  type TargetResumeAiPriority,
} from './target-resume-ai-protocol';

export type TargetResumeAIErrorCode = 'invalid_document' | 'invalid_signature' | 'signature_unavailable'
  | 'invalid_request' | 'invalid_response' | 'invalid_selection' | 'stale_document' | 'stale_context'
  | 'incomplete_structure' | 'document_too_large' | 'legacy_target_context';
export type TargetResumeAIResult<T> = { ok: true; value: T } | { ok: false; code: TargetResumeAIErrorCode };
export interface TargetResumeAICurrentContext {
  profile_signature: string; source_signature: string; target_signature: string;
}
export interface TargetResumeAICoverage {
  total: number; protected: number; pending: number; suggested: number;
  /** suggested = rewrites (reviewed new wording) + advice (a fact line's priority and links). */
  rewrites: number; advice: number;
  unchanged: number; skipped: number; processed: number; complete: boolean;
}
export interface MergedTargetResumeAI {
  receipts: TargetResumeAiReceipt[]; coverage: TargetResumeAICoverage; structureReady: boolean;
}
export interface ApplyTargetResumeAIOptions {
  supportGroups?: TargetResumeSupportGroup[];
  rewriteUnitIds: string[]; applyStructure: boolean; currentContext: TargetResumeAICurrentContext;
  /** Selected rewrites to apply without the posting's terms (their alternative_text). */
  alternativeUnitIds?: string[];
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
  if (!isCurrentTargetResumeContext(prepared.draft.target_snapshot)) fail('legacy_target_context');
  if (canonical(prepared.draft) !== prepared.canonical_draft) fail('invalid_request');
  if (prepared.support_groups !== undefined) {
    const parsed = parseTargetResumeSupportGroups(prepared.draft, prepared.support_groups);
    if (parsed === null || !same(parsed, prepared.support_groups)) fail('invalid_request');
  }
  const expected = unitsFor(prepared.draft);
  if (!same(expected.units, prepared.units) || expected.protectedCount !== prepared.protected_unit_count) fail('invalid_request');
}

/** One anchor's JSON around its text: {"from":"requirement","id":"t48","text":""} and a comma. */
const ANCHOR_JSON_CHARACTERS = 44;

/** Freeze one exact draft before hashing. All eligible lines are traversed;
 * call budgets make multiple batches, not a first-N document selection. */
export async function prepareTargetResumeAI(value: unknown, supportGroups?: TargetResumeSupportGroup[]): Promise<TargetResumeAIResult<PreparedTargetResumeAi>> {
  try {
    const checked = validateTargetResume(value);
    if (!checked.ok) fail(checked.code === 'document_too_large' ? 'document_too_large' : 'invalid_document');
    const draft = checked.value;
    if (!isCurrentTargetResumeContext(draft.target_snapshot)) fail('legacy_target_context');
    const capturedGroups = supportGroups === undefined ? undefined : parseTargetResumeSupportGroups(draft, supportGroups);
    if (capturedGroups === null) fail('invalid_request');
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
      target.description, ...target.requirements].reduce((sum, field) => sum + resumeTextCharacters(field), 0)
      + resumeTextCharacters(canonical(target.criteria)) + resumeTextCharacters(canonical(target.research)) + resumeTextCharacters(canonical(target.lab)) > FULL_TARGET_AI_MAX_TARGET_CHARACTERS;
    const interests = draft.base_snapshot.research_interests;
    const documentReason = targetTooLarge ? 'target_too_large'
      : interests !== undefined && resumeTextCharacters(interests) > FULL_TARGET_AI_MAX_INTERESTS_CHARACTERS ? 'interests_too_large' : null;
    const batches: string[][] = [];
    const skippedUnits: TargetResumeAiReceipt[] = [];
    let batch: string[] = [];
    const byId = new Map(units.map(unit=>[unit.unit_id,unit]));
    const fits = (ids: string[]) => {
      const sources = supportSourceIds(ids, capturedGroups).map(id=>byId.get(id)!);
      return ids.length <= FULL_TARGET_AI_MAX_UNITS
        && ids.filter(id => byId.get(id)!.evidence.kind === 'experience').length <= FULL_TARGET_AI_MAX_EXPERIENCE_UNITS
        && sources.reduce((sum,unit)=>sum+resumeTextCharacters(unit.original),0) <= FULL_TARGET_AI_MAX_UNIT_CHARACTERS
        && sources.reduce((sum,unit)=>sum+(unit.evidence.kind==='experience' ? resumeTextCharacters(unit.original) : 0),0) <= FULL_TARGET_AI_MAX_EXPERIENCE_CHARACTERS;
    };
    // Bounds the server's canonical prompt: every batch repeats the system
    // instructions, anchors, criteria, direction and whole-block fact context.
    // The server cuts the anchors, so every quotable field counts as if all of
    // it were anchor text, plus each anchor's own JSON. The server stays
    // authoritative and asks for a smaller request if this falls short.
    const quotable = [target.description, ...target.requirements,
      ...(target.research.status === 'available' ? target.research.snapshot!.works.map(work => work.title) : []),
      ...(target.lab.status === 'available' ? target.lab.snapshot!.pages.flatMap(page => page.sections.flatMap(section => [section.heading, section.text])) : [])];
    const anchorPrompt = quotable.reduce((sum, field) => sum + resumeTextCharacters(JSON.stringify(field)), 0)
      + FULL_TARGET_AI_MAX_ANCHORS * ANCHOR_JSON_CHARACTERS;
    const fixedPrompt = FULL_TARGET_AI_SYSTEM_PROMPT_CHARACTERS + anchorPrompt + resumeTextCharacters(canonical({ anchors: [],
      block_contexts: [], criteria: target.criteria, locale: 'en', opportunity: { organization: target.organization, title: target.title },
      units: [], ...(interests === undefined ? {} : { student_direction: { research_interests: interests } }) }));
    const blockKey = (unit: TargetResumeAiUnit) => JSON.stringify([unit.section_id, unit.block_id]);
    const blockPrompt = new Map<string, number>();
    for (const section of draft.document.sections) for (const block of section.blocks) {
      blockPrompt.set(JSON.stringify([section.id, block.id]), resumeTextCharacters(canonical({ section_id: section.id, block_id: block.id,
        fields: block.lines.filter(line => line.evidence.kind === 'fact').map(line => ({ role: line.role, label: line.label, value: line.original })) })));
    }
    const unitPrompt = (unit: TargetResumeAiUnit) => {
      const group = capturedGroups?.find(item => item.unit_id === unit.unit_id);
      return resumeTextCharacters(canonical({ unit_id: unit.unit_id, section_id: unit.section_id, block_id: unit.block_id,
        kind: unit.evidence.kind, role: unit.role, label: unit.label, original: unit.original,
        ...(group?.support_unit_ids.length ? { support_sources: group.support_unit_ids.map(id => byId.get(id)!)
          .map(source => ({ unit_id: source.unit_id, evidence: source.evidence, original: source.original })) } : {}) }));
    };
    const promptFits = (ids: string[]) => {
      const selected = ids.map(id => byId.get(id)!);
      const blocks = new Set(selected.map(blockKey));
      // Each array's separators: one comma fewer than its entries.
      const size = fixedPrompt + [...blocks].reduce((sum, key) => sum + blockPrompt.get(key)! + 1, -1)
        + selected.reduce((sum, unit) => sum + unitPrompt(unit) + 1, -1);
      return size <= FULL_TARGET_AI_MAX_PROMPT_CHARACTERS;
    };
    for (const unit of units) {
      if (documentReason || !fits([unit.unit_id])) { skippedUnits.push(skipped(unit, documentReason ?? 'unit_too_large')); continue; }
      // A unit whose own prompt overflows still gets its own request; only the
      // server can refuse it as permanently too large.
      if (batch.length && (!fits([...batch,unit.unit_id]) || !promptFits([...batch,unit.unit_id]))) { batches.push(batch); batch=[]; }
      batch.push(unit.unit_id);
    }
    if (batch.length) batches.push(batch);
    return { ok: true, value: freeze({ draft, canonical_draft: canonicalDraft, document_signature: documentSignature,
      units, protected_unit_count: protectedCount, batches, skipped: skippedUnits, ...(capturedGroups === undefined ? {} : {support_groups:capturedGroups}) }) };
  } catch (error) { return failure(error, 'invalid_document'); }
}

const KEEP_CODES = new Set(['no_change', 'no_link', 'already_aligned', 'no_safe_change', 'cosmetic_only',
  'beyond_allowed_edit', 'rewrite_rejected', 'review_rejected']);
const SKIP_CODES = new Set(['unit_too_large', 'context_too_large', 'target_too_large', 'target_has_no_text',
  'interests_too_large', 'batch_context_too_large', 'model_unavailable', 'invalid_model_response', 'missing_result',
  'budget_exhausted', 'timeout', 'rewrite_unchecked']);
const OPS: ReadonlySet<string> = new Set(TARGET_RESUME_AI_OPS);
const PRIORITIES = new Set(['high', 'normal', 'low']);
function evidenceQuote(draft: TargetResumeV1, value: unknown): void {
  if (!isTargetResumeEvidence(draft.target_snapshot, value)) fail('invalid_response');
}
/** A literal codepoint span of the unit's original or of one of its confirmed support lines. */
function sourceQuote(originals: Map<string, string>, value: unknown): void {
  shape(value, ['unit_id', 'start', 'end', 'quote']);
  const original = typeof value.unit_id === 'string' ? originals.get(value.unit_id) : undefined;
  text(value.quote);
  if (original === undefined || !value.quote.trim() || !Number.isSafeInteger(value.start) || !Number.isSafeInteger(value.end)
    || (value.start as number) < 0 || (value.end as number) <= (value.start as number)
    || Array.from(original).slice(value.start as number, value.end as number).join('') !== value.quote) fail('invalid_response');
}
function rewriteText(value: unknown): void {
  text(value);
  if (!value.trim() || resumeTextCharacters(value) > FULL_TARGET_AI_MAX_EXPERIENCE_CHARACTERS) fail('invalid_response');
}
function validateReceipt(prepared: PreparedTargetResumeAi, unit: TargetResumeAiUnit, value: unknown): TargetResumeAiReceipt {
  shape(value, ['unit_id', 'section_id', 'block_id', 'evidence', 'before_text', 'status', 'reason_code', 'suggestion']);
  if (value.unit_id !== unit.unit_id || value.section_id !== unit.section_id || value.block_id !== unit.block_id
    || !same(value.evidence, unit.evidence) || value.before_text !== unit.before_text) fail('invalid_response');
  const experience = unit.evidence.kind === 'experience';
  if (value.status === 'skipped') {
    if (value.suggestion !== null || !SKIP_CODES.has(String(value.reason_code))) fail('invalid_response');
    return value as unknown as TargetResumeAiReceipt;
  }
  // suggested: a reviewed rewrite of an experience, or advice on a fact line.
  // unchanged: an experience kept as written, with its advice and the reason.
  if (!(value.status === 'suggested' && value.reason_code === null)
    && !(value.status === 'unchanged' && experience && KEEP_CODES.has(String(value.reason_code)))) fail('invalid_response');
  const group = prepared.support_groups?.find(item=>item.unit_id===unit.unit_id);
  const alternative = object(value.suggestion) && value.suggestion.alternative_text !== null;
  shape(value.suggestion, ['priority', 'reason', 'target_evidence', 'proposed_text', 'links', 'ops', 'alternative_text',
    ...(group ? ['source_evidence'] : []), ...(alternative ? ['alternative_reason'] : [])]);
  if (group && !same(value.suggestion.source_evidence, targetResumeSupportEvidence(prepared.draft,group))) fail('invalid_response');
  const suggestion = value.suggestion;
  text(suggestion.reason);
  if (!PRIORITIES.has(String(suggestion.priority)) || !suggestion.reason.trim()
    || !Array.isArray(suggestion.links) || suggestion.links.length > 3
    || !Array.isArray(suggestion.target_evidence) || !Array.isArray(suggestion.ops)) fail('invalid_response');
  const originals = new Map(supportSourceIds([unit.unit_id], group ? [group] : undefined)
    .map(id => [id, prepared.units.find(item => item.unit_id === id)!.original] as const));
  const ids = new Set<string>();
  for (const link of suggestion.links as unknown[]) {
    shape(link, ['id', 'relation', 'entailed', 'target_evidence', 'source_evidence', 'written_as']);
    text(link.id);
    // Only a link an operation used can be reviewed, and only a "same" link can be used.
    if (!link.id || ids.has(link.id) || !['same', 'broader'].includes(String(link.relation)) || typeof link.entailed !== 'boolean'
      || (link.entailed && link.relation !== 'same')) fail('invalid_response');
    ids.add(link.id);
    evidenceQuote(prepared.draft, link.target_evidence);
    sourceQuote(originals, link.source_evidence);
    if (link.written_as !== null) text(link.written_as);
  }
  const links = suggestion.links as TargetResumeAiLinkShape[];
  const targets = [...new Map(links.map(link => [canonical(link.target_evidence), link.target_evidence])).values()];
  if (!same(suggestion.target_evidence, targets) || (suggestion.priority === 'high' && !links.length)) fail('invalid_response');
  const ops = suggestion.ops as unknown[];
  if (ops.some(op => typeof op !== 'string' || !OPS.has(op)) || new Set(ops).size !== ops.length) fail('invalid_response');
  if (suggestion.proposed_text === null) {
    // Advice and kept lines carry no operations and nothing to apply.
    if (ops.length || suggestion.alternative_text !== null || (value.status === 'suggested' && experience)) fail('invalid_response');
  } else {
    rewriteText(suggestion.proposed_text);
    if (!experience || value.status !== 'suggested' || !ops.length
      || ((ops.includes('lead_with') || ops.includes('relabel')) && !links.some(link => link.relation === 'same'))
      || (ops.includes('translate') && ops.length !== 1)) fail('invalid_response');
    if (suggestion.alternative_text !== null) {
      rewriteText(suggestion.alternative_text);
      text(suggestion.alternative_reason);
      if (!ops.includes('relabel') || suggestion.alternative_text === suggestion.proposed_text
        || !suggestion.alternative_reason.trim()) fail('invalid_response');
    }
  }
  return value as unknown as TargetResumeAiReceipt;
}
type TargetResumeAiLinkShape = { relation: string; target_evidence: unknown };

/** Wire verification is deliberately stricter than a TypeScript cast. It
 * cannot prove semantic entailment; only the server's fact checks plus the
 * student's explicit review can assess the proposed prose. */
export function validateTargetResumeAIResponse(prepared: PreparedTargetResumeAi,
  expected: Pick<TargetResumeAiRequest, 'request_id' | 'selected_unit_ids' | 'support_groups'>,
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
    const groups = prepared.support_groups === undefined ? undefined : supportGroupsForUnits(prepared.support_groups, expected.selected_unit_ids);
    if (!same(expected.support_groups ?? null, groups ?? null)) fail('invalid_request');
    const selectedUnits = supportSourceIds(expected.selected_unit_ids, groups).map((id) => byId.get(id)!);
    if (selectedUnits.reduce((sum, unit) => sum + resumeTextCharacters(unit.original), 0) > FULL_TARGET_AI_MAX_UNIT_CHARACTERS
      || selectedUnits.reduce((sum, unit) => sum + (unit.evidence.kind === 'experience' ? resumeTextCharacters(unit.original) : 0), 0)
        > FULL_TARGET_AI_MAX_EXPERIENCE_CHARACTERS) fail('invalid_request');
    const serialized = canonical(response);
    if (new TextEncoder().encode(serialized).byteLength > FULL_TARGET_AI_MAX_BODY_BYTES) fail('invalid_response');
    const value: unknown = JSON.parse(serialized);
    const checkKeys = object(value) && Object.hasOwn(value, 'check_version') ? ['check_version'] : [];
    shape(value, ['version', 'pipeline_version', 'request_id', 'document_id', 'opportunity_id', 'document_signature',
      'base', 'manifest', 'method', 'logical_calls', 'provider_attempts_upper_bound', 'receipts', ...checkKeys, ...(groups === undefined ? [] : ['support_groups'])]);
    if (!same(value.support_groups ?? null, groups ?? null)) fail('invalid_response');
    if (checkKeys.length && value.check_version !== null
      && (typeof value.check_version !== 'string' || !/^target-resume-source-checks-v[1-9][0-9]{0,5}$/.test(value.check_version))) fail('invalid_response');
    if (value.version !== 1 || value.pipeline_version !== FULL_TARGET_AI_VERSION || value.request_id !== expected.request_id
      || value.document_id !== prepared.draft.id || value.opportunity_id !== prepared.draft.opportunity_id
      || value.document_signature !== prepared.document_signature || !same(value.base, prepared.draft.base)
      || !['ai', 'partial', 'unavailable'].includes(String(value.method))
      || ![0, 1, 2].includes(value.logical_calls as number)
      || value.provider_attempts_upper_bound !== 2 * (value.logical_calls as number)) fail('invalid_response');
    shape(value.manifest, ['unit_ids', 'protected_unit_count']);
    if (!same(value.manifest.unit_ids, prepared.units.map((unit) => unit.unit_id))
      || value.manifest.protected_unit_count !== prepared.protected_unit_count
      || !Array.isArray(value.receipts) || value.receipts.length !== expected.selected_unit_ids.length) fail('invalid_response');
    const seen = new Set<string>();
    const selected = new Set(expected.selected_unit_ids);
    for (const item of value.receipts) {
      if (!object(item) || typeof item.unit_id !== 'string' || !selected.has(item.unit_id) || seen.has(item.unit_id)) fail('invalid_response');
      seen.add(item.unit_id);
      // The server gives this only when a smaller request would fit; a single
      // unit can never be split further, so it would retry forever.
      if (item.reason_code === 'batch_context_too_large' && expected.selected_unit_ids.length < 2) fail('invalid_response');
      validateReceipt(prepared, byId.get(item.unit_id)!, item);
    }
    const skippedCount = value.receipts.filter((item) => (item as TargetResumeAiReceipt).status === 'skipped').length;
    if ((value.method === 'ai' && (skippedCount !== 0 || value.logical_calls === 0))
      || (value.method === 'partial' && (skippedCount === 0 || skippedCount === value.receipts.length || value.logical_calls === 0))
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
        ...(prepared.support_groups === undefined ? {} : {support_groups:supportGroupsForUnits(prepared.support_groups,response.receipts.map(item=>item.unit_id))}),
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
    const rewrites = ordered.filter((item) => item.status === 'suggested' && typeof item.suggestion?.proposed_text === 'string'
      && item.suggestion.proposed_text !== item.before_text).length;
    const unchanged = count('unchanged');
    const processed = suggested + unchanged;
    const complete = prepared.units.length > 0 && processed === prepared.units.length;
    return { ok: true, value: freeze(clone({ receipts: ordered, coverage: { total: prepared.units.length,
      protected: prepared.protected_unit_count, pending: prepared.units.length - ordered.length,
      suggested, rewrites, advice: suggested - rewrites, unchanged, skipped: count('skipped'), processed, complete },
      structureReady: complete })) };
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
    if (!same(options.supportGroups ?? [], prepared.support_groups ?? [])) fail('stale_context');
    const context = options.currentContext;
    if (!context || context.profile_signature !== prepared.draft.base.profile_signature
      || context.source_signature !== prepared.draft.base.source_signature
      || context.target_signature !== prepared.draft.base.target_signature) fail('stale_context');
    if (canonical(currentDraft) !== prepared.canonical_draft) fail('stale_document');
    const alternatives = options.alternativeUnitIds ?? [];
    if (!Array.isArray(options.rewriteUnitIds) || new Set(options.rewriteUnitIds).size !== options.rewriteUnitIds.length
      || !Array.isArray(alternatives) || new Set(alternatives).size !== alternatives.length
      || alternatives.some((id) => !options.rewriteUnitIds.includes(id))
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
      const plain = alternatives.includes(id);
      if (plain && typeof receipt.suggestion.alternative_text !== 'string') fail('invalid_selection');
      changes.set(id, plain ? receipt.suggestion.alternative_text! : receipt.suggestion.proposed_text);
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
