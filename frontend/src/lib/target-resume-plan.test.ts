import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import golden from '../../../tests/fixtures/target-resume-context-v4-golden.json';
import { createEmptyResumeMaster } from './resume-master';
import { sourceDigest } from './experience-evidence';
import { createTargetResume, validateTargetResume, type TargetResumeV1 } from './target-resume';
import type { ExperienceEntry, ProfileData, ResumeFact } from './types';
import type { ApplyTargetResumePlanOptions, PreparedTargetResumePlan, TargetResumePlanResponse } from './target-resume-plan-protocol';
import {
  prepareTargetResumePlan, validateTargetResumePlanResponse, applyTargetResumePlan,
  measureTargetResumeLength, type TargetResumePlanResult,
} from './target-resume-plan';

beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const unwrap = <T,>(value: TargetResumePlanResult<T>): T => { if (!value.ok) throw Error(value.code); return value.value; };
const fact = (id: string, value: string): ResumeFact => ({ id, value, revision: 1, status: 'confirmed', source: { kind: 'manual' } });
const target = { opportunity_id: 'opp', title: 'Robotics', organization: 'University', source_url: '', description: 'Robotics 😀 materials.',
  requirements: ['Python', '😀研究'], context_version: 4 as const, lab: { version: 1 as const, status: 'unavailable' as const, snapshot: null }, research: { version: 1 as const, status: 'unavailable' as const, snapshot: null },
  criteria: { eligibility: {}, timing: {}, application: {}, setting: {}, availability: {}, attribution: {} } };
const lines = (draft: TargetResumeV1) => draft.document.sections.flatMap(s => s.blocks.flatMap(b => b.lines));
const blocks = (draft: TargetResumeV1) => draft.document.sections.flatMap(s => s.blocks);
async function make(texts = ['Built a Python parser with tests.', 'Analyzed 10000 samples with Python.'], extend?: (profile: ProfileData) => void) {
  const master = createEmptyResumeMaster('master');
  master.basics = { name: fact('name', 'Student'), links: [] };
  master.skills = [fact('skill', 'Python')];
  const entries: ExperienceEntry[] = texts.map((text, index) => ({ id: `exp-${index}`, revision: 1, status: 'confirmed', text, source: { kind: 'manual' } }));
  master.activities = entries.map(entry => ({ id: `block-${entry.id}`, kind: 'project', title: fact(`title-${entry.id}`, 'Project'), details: [{ id: entry.id, revision: entry.revision }] }));
  const profile: ProfileData = { institution: 'UIUC', college: 'Engineering', major: 'Engineering', grade: 'junior', is_international: false,
    research_interests: '', skills: [], resume_text: '', experience_entries: entries, resume_master: master };
  extend?.(profile);
  return createTargetResume(profile, target, 'draft');
}
const prepare = async (draft?: TargetResumeV1, target_pages: 1 | 2 = 1) => unwrap(await prepareTargetResumePlan(draft ?? await make(), { target_pages }));
function response(prepared: PreparedTargetResumePlan): TargetResumePlanResponse {
  return { version: 1, pipeline_version: 'full-target-plan-v3', request_id: 'request', document_id: prepared.draft.id,
    opportunity_id: prepared.draft.opportunity_id, document_signature: prepared.document_signature, base: clone(prepared.draft.base),
    options: clone(prepared.options), manifest: clone(prepared.manifest), scope: clone(prepared.scope), method: 'ai', complete: true,
    reason_code: null, logical_calls: 1, provider_attempts_upper_bound: 2,
    items: prepared.manifest.map(item => {
      const line = lines(prepared.draft).find(line => line.id === item.line_ids[0])!;
      return { section_id: item.section_id, block_id: item.block_id, action: 'keep', reason: 'Relevant to the Python requirement.',
        target_evidence: [{ field: 'requirement', requirement_index: 0, start: 0, end: 6, quote: 'Python' }],
        source_evidence: [{ unit_id: line.id, start: 0, end: Array.from(line.original).length, quote: line.original }], rewrites: [] };
    }) };
}
function compressed(prepared: PreparedTargetResumePlan, result = response(prepared)) {
  const line = lines(prepared.draft).find(line => line.evidence.kind === 'experience')!;
  const item = result.items.find(item => prepared.manifest.find(row => row.block_id === item.block_id)!.line_ids.includes(line.id))!;
  item.action = 'compress'; item.rewrites = [{ unit_id: line.id, status: 'suggested', reason_code: null, proposed_text: 'Built a Python parser.' }];
  return { result, item, line };
}
const request = (result: TargetResumePlanResponse) => ({ request_id: result.request_id, options: result.options });
function selection(prepared: PreparedTargetResumePlan, selection_block_ids: string[] = [], rewrite_unit_ids: string[] = []): ApplyTargetResumePlanOptions {
  return { selection_block_ids, rewrite_unit_ids, options: clone(prepared.options), current_context: {
    profile_signature: prepared.draft.base.profile_signature, source_signature: prepared.draft.base.source_signature,
    target_signature: prepared.draft.base.target_signature } };
}

describe('whole draft capture and honest coverage', () => {
  it('matches the shared canonical signature and includes hidden blocks beyond 24 lines', async () => {
    const shared = await prepare(golden.draft as TargetResumeV1);
    expect(shared.document_signature).toBe(golden.document_signature);
    expect(createHash('sha256').update(shared.canonical_draft).digest('hex')).toBe(shared.document_signature.slice(10));
    const draft = await make(Array.from({ length: 30 }, (_, index) => `Built parser ${index} with tests.`));
    const activities = draft.document.sections.find(section => section.kind === 'activities')!;
    activities.included = false; activities.blocks.at(-1)!.included = false; activities.blocks.at(-1)!.lines.at(-1)!.included = false;
    const prepared = await prepare(draft);
    expect(prepared.manifest).toHaveLength(31);
    const last = prepared.manifest.find(item => item.block_id === 'block-exp-29')!;
    expect(last.line_ids).toEqual(activities.blocks.at(-1)!.lines.map(line => line.id));
    expect(prepared.draft.document).toEqual(draft.document);
    expect(validateTargetResumePlanResponse(prepared, request(response(prepared)), response(prepared)).ok).toBe(true);
  });
  it('counts visible Unicode text only, through all three selection levels', async () => {
    const draft = await make(['😀研究\n正文']);
    for (const section of draft.document.sections) section.included = section.kind === 'activities';
    const block = draft.document.sections.find(section => section.kind === 'activities')!.blocks[0];
    block.lines[0].included = false;
    expect(measureTargetResumeLength(draft)).toBe(6);
    block.included = false; expect(measureTargetResumeLength(draft)).toBe(0);
    block.included = true; block.lines[1].included = false; expect(measureTargetResumeLength(draft)).toBe(0);
  });
  it('distinguishes unlinked confirmed, candidate, stale, withdrawn and unmapped material', async () => {
    const raw = 'source 😀'; const digest = await sourceDigest(raw);
    const draft = await make(undefined, profile => {
      profile.resume_text = raw;
      profile.experience_entries!.push(
        { id: 'unlinked', revision: 1, status: 'confirmed', text: 'Other work.', source: { kind: 'manual' } },
        { id: 'candidate', revision: 1, status: 'candidate', text: 'Unconfirmed.', source: { kind: 'manual' } },
        { id: 'stale', revision: 1, status: 'confirmed', text: 'Stale work.', source: { kind: 'resume', signature: 'f'.repeat(64), start: 0, end: Array.from(raw).length, quote: raw } },
        { id: 'wrong-quote', revision: 1, status: 'confirmed', text: 'Wrong quote.', source: { kind: 'resume', signature: digest, start: 0, end: 3, quote: 'bad' } },
        { id: 'withdrawn', revision: 1, status: 'withdrawn', text: 'Withdrawn.', source: { kind: 'manual' } },
      );
      profile.resume_master!.source_signature = digest;
      profile.resume_master!.unmapped_ranges = [{ start: 0, end: Array.from(raw).length }];
    });
    const prepared = await prepare(draft);
    expect(prepared.scope).toEqual({ unreferenced_experience_ids: ['unlinked'], pending_experience_ids: ['candidate'], stale_experience_ids: ['stale', 'wrong-quote'], unmapped_range_count: 1 });
    expect(prepared.manifest.flatMap(row => row.line_ids)).not.toContain('unlinked');
  });
  it('does not count a superseded master reference as covering the revised confirmed experience', async () => {
    const draft = await make(undefined, profile => { profile.experience_entries![0].revision = 2; });
    const prepared = await prepare(draft);
    expect(prepared.scope.unreferenced_experience_ids).toEqual(['exp-0']);
    expect(prepared.scope.stale_experience_ids).toEqual([]);
    expect(lines(prepared.draft).some(line => line.evidence.id === 'exp-0')).toBe(false);
  });
  it('does not call a basics-only document a complete plan', async () => {
    const prepared = await prepare(await make([], profile => { profile.resume_master!.skills = []; }));
    expect(prepared.manifest).toEqual([]);
    const result = response(prepared);
    expect(validateTargetResumePlanResponse(prepared, request(result), result).ok).toBe(false);
    Object.assign(result, { method: 'unavailable', complete: false, reason_code: 'no_plan_items', logical_calls: 0, provider_attempts_upper_bound: 0 });
    expect(validateTargetResumePlanResponse(prepared, request(result), result).ok).toBe(true);
  });
  it('captures options and manual draft before awaiting hashes', async () => {
    const draft = await make(); const settings = { target_pages: 1 as 1 | 2 }; const before = clone(draft);
    const pending = prepareTargetResumePlan(draft, settings);
    lines(draft).at(-1)!.text = 'Later manual edit'; settings.target_pages = 2;
    const prepared = unwrap(await pending);
    expect(prepared.draft).toEqual(before); expect(prepared.options).toEqual({ target_pages: 1 });
    expect(Object.isFrozen(prepared.draft.document.sections)).toBe(true);
    expect(Object.isFrozen(prepared.options)).toBe(true);
  });
  it('rejects invalid source signatures and unsupported options without truncation', async () => {
    const draft = clone(await make()); draft.base.target_signature = 'v1:sha256:' + 'f'.repeat(64);
    expect(await prepareTargetResumePlan(draft, { target_pages: 1 })).toEqual({ ok: false, code: 'invalid_signature' });
    for (const options of [{ target_pages: 3 }, { target_pages: '1' }, { target_pages: 1, max_lines: 20 }, null]) {
      expect(await prepareTargetResumePlan(await make(), options as never)).toEqual({ ok: false, code: 'invalid_options' });
    }
  });
});

describe('strict complete plan receipts', () => {
  it('checks exact codepoint quotes against the original rather than manual wording', async () => {
    const draft = await make(['😀研究 原文内容。']);
    const experience = lines(draft).find(line => line.evidence.kind === 'experience')!;
    experience.text = 'Manual text that is not new evidence.';
    const prepared = await prepare(draft); const result = response(prepared);
    const item = result.items.find(item => item.block_id === 'block-exp-0')!;
    item.target_evidence = [{ field: 'requirement', requirement_index: 1, start: 0, end: 1, quote: '😀' }];
    item.source_evidence = [{ unit_id: experience.id, start: 0, end: 3, quote: '😀研究' }];
    expect(validateTargetResumePlanResponse(prepared, request(result), result).ok).toBe(true);
    item.source_evidence = [{ unit_id: experience.id, start: 0, end: 6, quote: 'Manual' }];
    expect(validateTargetResumePlanResponse(prepared, request(result), result)).toEqual({ ok: false, code: 'invalid_response' });
  });
  it('accepts duplicate valid quotations and out-of-order items without changing the manifest', async () => {
    const prepared = await prepare(); const result = response(prepared);
    result.items.reverse(); result.items[0].source_evidence.push(clone(result.items[0].source_evidence[0]));
    expect(validateTargetResumePlanResponse(prepared, request(result), result).ok).toBe(true);
  });
  it.each([
    ['document identity', (r: TargetResumePlanResponse) => { r.document_id += 'other'; }],
    ['target identity', (r: TargetResumePlanResponse) => { r.opportunity_id += 'other'; }],
    ['request identity', (r: TargetResumePlanResponse) => { r.request_id += 'other'; }],
    ['document SHA', (r: TargetResumePlanResponse) => { r.document_signature += 'bad'; }],
    ['master revision', (r: TargetResumePlanResponse) => { r.base.master_revision += 1; }],
    ['page goal', (r: TargetResumePlanResponse) => { r.options.target_pages = 2; }],
    ['scope hides candidate', (r: TargetResumePlanResponse) => { r.scope.pending_experience_ids.push('not-present'); }],
    ['unmapped count', (r: TargetResumePlanResponse) => { r.scope.unmapped_range_count = 1; }],
    ['manifest omission', (r: TargetResumePlanResponse) => { r.manifest.pop(); }],
    ['manifest order', (r: TargetResumePlanResponse) => { r.manifest.reverse(); }],
    ['manifest line identity', (r: TargetResumePlanResponse) => { r.manifest[0].line_ids[0] = 'other'; }],
    ['last block omission', (r: TargetResumePlanResponse) => { r.items.pop(); }],
    ['duplicate block', (r: TargetResumePlanResponse) => { r.items[1] = clone(r.items[0]); }],
    ['unknown block', (r: TargetResumePlanResponse) => { r.items[0].block_id = 'new'; }],
    ['wrong section', (r: TargetResumePlanResponse) => { r.items[0].section_id = 'basics'; }],
    ['missing target quote', (r: TargetResumePlanResponse) => { r.items[0].target_evidence = []; }],
    ['missing source quote', (r: TargetResumePlanResponse) => { r.items[0].source_evidence = []; }],
    ['invented target quote', (r: TargetResumePlanResponse) => { r.items[0].target_evidence[0].quote = 'RUST!!'; }],
    ['cross-block source', (r: TargetResumePlanResponse) => { r.items[0].source_evidence[0] = clone(r.items[1].source_evidence[0]); }],
    ['empty reason', (r: TargetResumePlanResponse) => { r.items[0].reason = ' '; }],
    ['invalid Unicode', (r: TargetResumePlanResponse) => { r.items[0].reason = '\ud800'; }],
    ['nul', (r: TargetResumePlanResponse) => { r.items[0].reason += '\0'; }],
    ['fractional offset', (r: TargetResumePlanResponse) => { r.items[0].source_evidence[0].end = 2.5; }],
    ['unsafe offset', (r: TargetResumePlanResponse) => { r.items[0].source_evidence[0].end = Number.MAX_SAFE_INTEGER + 1; }],
    ['negative offset', (r: TargetResumePlanResponse) => { r.items[0].source_evidence[0].start = -1; }],
    ['string offset', (r: TargetResumePlanResponse) => { r.items[0].source_evidence[0].start = '0' as never; }],
    ['out-of-range quote', (r: TargetResumePlanResponse) => { r.items[0].source_evidence[0].end += 1; }],
    ['no calls but ai', (r: TargetResumePlanResponse) => { r.logical_calls = 0; r.provider_attempts_upper_bound = 0; }],
    ['call count boolean', (r: TargetResumePlanResponse) => { r.logical_calls = true as never; }],
    ['incomplete ai', (r: TargetResumePlanResponse) => { r.complete = false; }],
    ['unexpected reason', (r: TargetResumePlanResponse) => { r.reason_code = 'timeout'; }],
  ] as const)('refuses %s atomically', async (_name, mutate) => {
    const prepared = await prepare(); const result = response(prepared); const expected = clone(request(result)); const original = clone(prepared.draft);
    mutate(result);
    expect(validateTargetResumePlanResponse(prepared, expected, result)).toEqual({ ok: false, code: 'invalid_response' });
    expect(prepared.draft).toEqual(original);
  });
  it('rejects unknown fields, undefined, sparse arrays and oversized payloads', async () => {
    const prepared = await prepare(); const result = response(prepared);
    for (const invalid of [{ ...result, extra: undefined }, { ...result, items: new Array(3) }, { ...result, scope: { ...result.scope, hidden: 0 } }]) {
      expect(validateTargetResumePlanResponse(prepared, request(result), invalid).ok).toBe(false);
    }
    result.items[0].reason = 'x'.repeat(2 * 1024 * 1024 + 64 * 1024);
    expect(validateTargetResumePlanResponse(prepared, request(result), result)).toEqual({ ok: false, code: 'invalid_response' });
  });
  it('distinguishes honest unavailable from complete plans and never applies it', async () => {
    const prepared = await prepare(); const result = response(prepared);
    Object.assign(result, { method: 'unavailable', complete: false, reason_code: 'context_too_large', logical_calls: 0, provider_attempts_upper_bound: 0, items: [] });
    expect(validateTargetResumePlanResponse(prepared, request(result), result).ok).toBe(true);
    expect(applyTargetResumePlan(prepared, prepared.draft, result, selection(prepared, [prepared.manifest[0].block_id]))).toEqual({ ok: false, code: 'incomplete_plan' });
    result.items = response(prepared).items;
    expect(validateTargetResumePlanResponse(prepared, request(result), result).ok).toBe(false);
  });
  it.each([
    ['fact line', (p: PreparedTargetResumePlan, r: TargetResumePlanResponse) => { r.items[0].rewrites[0].unit_id = p.manifest[0].line_ids[0]; }],
    ['other block', (p: PreparedTargetResumePlan, r: TargetResumePlanResponse) => { r.items[0].rewrites[0].unit_id = p.manifest[1].line_ids.at(-1)!; }],
    ['unknown line', (_p: PreparedTargetResumePlan, r: TargetResumePlanResponse) => { r.items[0].rewrites[0].unit_id = 'unknown'; }],
    ['duplicate rewrite', (_p: PreparedTargetResumePlan, r: TargetResumePlanResponse) => { r.items[0].rewrites.push(clone(r.items[0].rewrites[0])); }],
    ['keep carries rewrite', (_p: PreparedTargetResumePlan, r: TargetResumePlanResponse) => { r.items[0].action = 'keep'; }],
    ['omit carries rewrite', (_p: PreparedTargetResumePlan, r: TargetResumePlanResponse) => { r.items[0].action = 'omit'; }],
    ['equal to original', (p: PreparedTargetResumePlan, r: TargetResumePlanResponse) => { r.items[0].rewrites[0].proposed_text = lines(p.draft).find(l => l.id === r.items[0].rewrites[0].unit_id)!.original; }],
    ['blank rewrite', (_p: PreparedTargetResumePlan, r: TargetResumePlanResponse) => { r.items[0].rewrites[0].proposed_text = '  '; }],
    ['suggested without text', (_p: PreparedTargetResumePlan, r: TargetResumePlanResponse) => { r.items[0].rewrites[0].proposed_text = null; }],
    ['suggested with rejection', (_p: PreparedTargetResumePlan, r: TargetResumePlanResponse) => { r.items[0].rewrites[0].reason_code = 'not_shorter'; }],
    ['skipped with text', (_p: PreparedTargetResumePlan, r: TargetResumePlanResponse) => { Object.assign(r.items[0].rewrites[0], { status: 'skipped', reason_code: 'not_shorter' }); }],
  ] as const)('refuses invalid compression: %s', async (_name, mutate) => {
    const prepared = await prepare(); const { result } = compressed(prepared); mutate(prepared, result);
    expect(validateTargetResumePlanResponse(prepared, request(result), result)).toEqual({ ok: false, code: 'invalid_response' });
  });
  it('compares compression with the shorter manual current text as well as original', async () => {
    const draft = await make(); lines(draft).find(line => line.evidence.kind === 'experience')!.text = 'Parser';
    const prepared = await prepare(draft); const { result, item } = compressed(prepared);
    expect(validateTargetResumePlanResponse(prepared, request(result), result).ok).toBe(false);
    item.rewrites[0] = { unit_id: item.rewrites[0].unit_id, status: 'skipped', reason_code: 'not_shorter', proposed_text: null };
    expect(validateTargetResumePlanResponse(prepared, request(result), result).ok).toBe(true);
    expect(applyTargetResumePlan(prepared, draft, result, selection(prepared, [], [item.rewrites[0].unit_id]))).toEqual({ ok: false, code: 'invalid_selection' });
  });
});

describe('explicit independent choices and stale-plan fences', () => {
  it('can omit and restore blocks without deleting hidden originals or manual text', async () => {
    const draft = await make(); const hidden = draft.document.sections.find(section => section.kind === 'activities')!;
    hidden.included = false; hidden.blocks[0].lines[0].included = false;
    const before = clone(draft); const prepared = await prepare(draft); const result = response(prepared);
    const item = result.items[0]; item.action = 'omit';
    const omitted = unwrap(applyTargetResumePlan(prepared, draft, result, selection(prepared, [item.block_id])));
    expect(blocks(omitted).find(b => b.id === item.block_id)!.included).toBe(false);
    expect(omitted.base_snapshot).toEqual(before.base_snapshot); expect(omitted.base).toEqual(before.base); expect(omitted.target_snapshot).toEqual(before.target_snapshot);
    expect(lines(omitted)).toEqual(lines(before)); expect(draft).toEqual(before);
    const next = await prepare(omitted); const keep = response(next);
    const restored = unwrap(applyTargetResumePlan(next, omitted, keep, selection(next, [item.block_id])));
    expect(restored).toEqual(before); // Hidden parent and hidden child remain untouched.
  });
  it('selection does not rewrite, and a rewrite does not select its hidden block', async () => {
    const draft = await make(); const block = blocks(draft).find(block => block.id === 'block-exp-0')!; block.included = false;
    const prepared = await prepare(draft); const { result, item, line } = compressed(prepared);
    const selectedOnly = unwrap(applyTargetResumePlan(prepared, draft, result, selection(prepared, [item.block_id])));
    expect(blocks(selectedOnly).find(block => block.id === item.block_id)!.included).toBe(true);
    expect(lines(selectedOnly)).toEqual(lines(draft));
    const rewrittenOnly = unwrap(applyTargetResumePlan(prepared, draft, result, selection(prepared, [], [line.id])));
    expect(blocks(rewrittenOnly).find(block => block.id === item.block_id)!.included).toBe(false);
    expect(lines(rewrittenOnly).find(row => row.id === line.id)!.text).toBe('Built a Python parser.');
    expect(rewrittenOnly.base_snapshot).toEqual(draft.base_snapshot); expect(validateTargetResume(rewrittenOnly).ok).toBe(true);
    expect(applyTargetResumePlan(prepared, rewrittenOnly, result, selection(prepared, [item.block_id]))).toEqual({ ok: false, code: 'stale_document' });
  });
  it('keeps identical wording in two experiences separate when accepting only one rewrite', async () => {
    const draft = await make(['Built a Python parser with tests.', 'Built a Python parser with tests.']);
    const prepared = await prepare(draft); const { result, line } = compressed(prepared);
    const selected = unwrap(applyTargetResumePlan(prepared, draft, result, selection(prepared, [], [line.id])));
    const experiences = lines(selected).filter(row => row.evidence.kind === 'experience');
    expect(experiences.map(row => [row.evidence.id, row.text])).toEqual([
      ['exp-0', 'Built a Python parser.'], ['exp-1', 'Built a Python parser with tests.'],
    ]);
    expect(experiences.every(row => row.original === 'Built a Python parser with tests.')).toBe(true);
  });
  it('changes neither section/block order nor unchosen block states', async () => {
    const draft = await make(); draft.document.sections.reverse();
    const prepared = await prepare(draft); const result = response(prepared);
    const omitted = result.items.find(item => item.block_id === 'block-exp-0')!; omitted.action = 'omit';
    const applied = unwrap(applyTargetResumePlan(prepared, draft, result, selection(prepared, [omitted.block_id])));
    const expected = clone(draft); blocks(expected).find(block => block.id === omitted.block_id)!.included = false;
    expect(applied).toEqual(expected);
  });
  it.each(['profile_signature', 'source_signature', 'target_signature'] as const)('refuses changed current %s', async key => {
    const prepared = await prepare(); const selected = selection(prepared, [prepared.manifest[0].block_id]); selected.current_context[key] += 'changed';
    expect(applyTargetResumePlan(prepared, prepared.draft, response(prepared), selected)).toEqual({ ok: false, code: 'stale_context' });
  });
  it.each([
    ['manual text', (draft: TargetResumeV1) => { lines(draft).at(-1)!.text += ' edited'; }],
    ['block inclusion', (draft: TargetResumeV1) => { blocks(draft)[0].included = false; }],
    ['line inclusion', (draft: TargetResumeV1) => { lines(draft)[0].included = false; }],
    ['order', (draft: TargetResumeV1) => { draft.document.sections.reverse(); }],
    ['new identity', (draft: TargetResumeV1) => { draft.id += 'rebuilt'; }],
    ['source withdrawn', (draft: TargetResumeV1) => { draft.base_snapshot.experience_entries[0].status = 'withdrawn'; }],
    ['new master', (draft: TargetResumeV1) => { draft.base.master_revision += 1; }],
  ] as const)('does not overwrite %s changed after preview', async (_name, mutate) => {
    const prepared = await prepare(); const draft = clone(prepared.draft); mutate(draft); const before = clone(draft);
    expect(applyTargetResumePlan(prepared, draft, response(prepared), selection(prepared, [prepared.manifest[0].block_id]))).toEqual({ ok: false, code: 'stale_document' });
    expect(draft).toEqual(before);
  });
  it('revalidates every receipt before applying and refuses page-goal change, empty or duplicate selections', async () => {
    const prepared = await prepare(); const { result, item, line } = compressed(prepared); const base = selection(prepared, [item.block_id], [line.id]);
    const changedGoal = clone(base); changedGoal.options.target_pages = 2;
    expect(applyTargetResumePlan(prepared, prepared.draft, result, changedGoal)).toEqual({ ok: false, code: 'stale_context' });
    for (const invalid of [selection(prepared), selection(prepared, [item.block_id, item.block_id]), selection(prepared, [], [line.id, line.id]), selection(prepared, ['master']), selection(prepared, [], ['unknown'])]) {
      expect(applyTargetResumePlan(prepared, prepared.draft, result, invalid)).toEqual({ ok: false, code: 'invalid_selection' });
    }
    result.items.at(-1)!.source_evidence[0].quote = 'Changed after initial validation';
    expect(applyTargetResumePlan(prepared, prepared.draft, result, base)).toEqual({ ok: false, code: 'invalid_response' });
  });
});


describe('negotiated source-check rule metadata', () => {
  it('keeps legacy metadata unknown and preserves the reported rule without upgrading it', async () => {
    const p = await prepare(); const r = response(p);
    const old = unwrap(validateTargetResumePlanResponse(p, request(r), r));
    expect(Object.hasOwn(old, 'check_version')).toBe(false);
    for (const version of [null, 'target-resume-source-checks-v1', 'target-resume-source-checks-v42']) {
      r.check_version = version;
      expect(unwrap(validateTargetResumePlanResponse(p, request(r), r)).check_version).toBe(version);
    }
  });
  it.each(['', 'full-target-v2', 'target-resume-source-checks-v0', true, 123, { verified: true }])('rejects malformed rule metadata %j', async value => {
    const p = await prepare(); const r = response(p);
    Object.assign(r, { check_version: value });
    expect(validateTargetResumePlanResponse(p, request(r), r)).toEqual({ ok: false, code: 'invalid_response' });
  });
});
