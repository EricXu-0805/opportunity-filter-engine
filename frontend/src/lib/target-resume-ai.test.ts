import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import golden from '../../../tests/fixtures/target-resume-context-v4-golden.json';
import legacyGolden from '../../../tests/fixtures/target-resume-ai-golden.json';
import { createEmptyResumeMaster } from './resume-master';
import { createTargetResume, validateTargetResume, type TargetResumeV1 } from './target-resume';
import type { ExperienceEntry, ProfileData, ResumeFact } from './types';
import type { PreparedTargetResumeAi, TargetResumeAiLink, TargetResumeAiReceipt, TargetResumeAiResponse, TargetResumeAiUnit } from './target-resume-ai-protocol';
import { prepareTargetResumeAI, validateTargetResumeAIResponse, mergeTargetResumeAIResponses, applyTargetResumeAI, type TargetResumeAIResult } from './target-resume-ai';

beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const unwrap = <T,>(v: TargetResumeAIResult<T>): T => { if (!v.ok) throw Error(v.code); return v.value; };
const lines = (v: TargetResumeV1) => v.document.sections.flatMap(s => s.blocks.flatMap(b => b.lines));
const fact = (id: string, value: string): ResumeFact => ({ id, value, revision: 1, status: 'confirmed', source: { kind: 'manual' } });
const target = { opportunity_id: 'opp', title: 'Robotics', organization: 'University', source_url: '', description: 'Robotics 😀 materials.', requirements: ['Python', '😀研究'], context_version: 4 as const, lab: { version: 1 as const, status: 'unavailable' as const, snapshot: null }, research: { version: 1 as const, status: 'unavailable' as const, snapshot: null },
  criteria: { eligibility: {}, timing: {}, application: {}, setting: {}, availability: {}, attribution: {} } };
async function make(facts: string[] = ['Python'], experiences: string[] = ['Built a Python parser.'], description?: string, research_interests = '') {
  const master = createEmptyResumeMaster('master');
  master.basics = { name: fact('name', 'Student'), links: [] };
  if (facts.reduce((n, value) => n + Array.from(value).length, 0) === 60000) master.basics = { links: [] };
  master.skills = facts.map((value, i) => fact(`skill-${i}`, value));
  const entries: ExperienceEntry[] = experiences.map((text, i) => ({ id: `exp-${i}`, revision: 1, status: 'confirmed', text, source: { kind: 'manual' } }));
  master.activities = entries.map(e => ({ id: `activity-${e.id}`, kind: 'project', details: [{ id: e.id, revision: e.revision }] }));
  const profile: ProfileData = { institution: 'UIUC', college: 'Engineering', major: 'Engineering', grade: 'junior', is_international: false,
    research_interests, skills: [], resume_text: '', experience_entries: entries, resume_master: master };
  return createTargetResume(profile, description === undefined ? target : { ...target, description }, 'draft');
}
const prep = async (draft?: TargetResumeV1) => unwrap(await prepareTargetResumeAI(draft ?? await make()));
const PYTHON = { field: 'requirement' as const, requirement_index: 0, start: 0, end: 6, quote: 'Python' };
/** A link from the unit's own "Python" (codepoint offsets) to the requirement, when the line has one. */
function pythonLinks(u: TargetResumeAiUnit, entailed = false): TargetResumeAiLink[] {
  const at = u.original.indexOf('Python');
  if (at < 0) return [];
  const start = Array.from(u.original.slice(0, at)).length;
  return [{ id: 'L1', relation: 'same', entailed, target_evidence: { ...PYTHON },
    source_evidence: { unit_id: u.unit_id, start, end: start + 6, quote: 'Python' }, written_as: null }];
}
function receipt(p: PreparedTargetResumeAi, id: string, status: TargetResumeAiReceipt['status'] = 'suggested'): TargetResumeAiReceipt {
  const u = p.units.find(u => u.unit_id === id)!;
  const rewrite = status === 'suggested' && u.evidence.kind === 'experience';
  const links = pythonLinks(u, rewrite);
  return { unit_id: id, section_id: u.section_id, block_id: u.block_id, evidence: clone(u.evidence), before_text: u.before_text,
    status: status === 'unchanged' && u.evidence.kind !== 'experience' ? 'suggested' : status,
    reason_code: status === 'skipped' ? 'model_unavailable' : status === 'unchanged' && u.evidence.kind === 'experience' ? 'no_link' : null,
    suggestion: status === 'skipped' ? null : { priority: 'normal', reason: 'Relevant to the stated Python requirement.',
      target_evidence: links.map(link => link.target_evidence), links, ops: rewrite ? [links.length ? 'lead_with' : 'verb_first'] : [],
      proposed_text: rewrite ? 'Built the Python parser with the team.' : null, alternative_text: null } };
}
function response(p: PreparedTargetResumeAi, ids = p.batches[0], request_id = 'request'): TargetResumeAiResponse {
  return { version: 1, pipeline_version: 'full-target-v6', request_id, document_id: p.draft.id, opportunity_id: p.draft.opportunity_id,
    document_signature: p.document_signature, base: clone(p.draft.base), manifest: { unit_ids: p.units.map(u => u.unit_id), protected_unit_count: p.protected_unit_count },
    method: 'ai', logical_calls: 1, provider_attempts_upper_bound: 2, receipts: ids.map(id => receipt(p, id)) };
}
const expected = (r: TargetResumeAiResponse) => ({ request_id: r.request_id, selected_unit_ids: r.receipts.map(x => x.unit_id) });
const exp = (r: TargetResumeAiResponse) => r.receipts.find(x => x.evidence.kind === 'experience')!;
const factReceipt = (r: TargetResumeAiResponse) => r.receipts.find(x => x.evidence.kind === 'fact')!;
const context = (p: PreparedTargetResumeAi) => ({ profile_signature: p.draft.base.profile_signature, source_signature: p.draft.base.source_signature, target_signature: p.draft.base.target_signature });
const options = (p: PreparedTargetResumeAi, rewriteUnitIds: string[] = [], applyStructure = false) => ({ currentContext: context(p), rewriteUnitIds, applyStructure });

describe('whole-document preparation and bounded complete batches', () => {
  it('matches the shared multilingual whole-draft signature and manifest, with edited text separate from evidence', async () => {
    const p = await prep(golden.draft as TargetResumeV1);
    expect(p.document_signature).toBe(golden.document_signature);
    expect(p.units).toEqual(golden.units);
    expect({ unit_ids: p.units.map(u => u.unit_id), protected_unit_count: p.protected_unit_count }).toEqual(golden.manifest);
    expect(new Set(p.units.map(u => u.section_id))).toEqual(new Set(['education', 'activities', 'publications', 'skills', 'awards']));
    const e = p.units.find(u => u.evidence.kind === 'experience')!;
    expect(e.original).toContain('I did not lead'); expect(e.before_text).toBe('My manual draft edit is not evidence.');
    expect(createHash('sha256').update(p.canonical_draft).digest('hex')).toBe(p.document_signature.slice(10));
  });
  it('traverses more than eight experiences and more than 20 units without omitting any tail', async () => {
    const p = await prep(await make(Array.from({ length: 30 }, (_, i) => `Skill ${i}`), Array.from({ length: 15 }, (_, i) => `I did not lead project ${i}. I contributed one parser.`)));
    expect(p.units).toHaveLength(45); expect(p.batches.flat()).toEqual(p.units.map(u => u.unit_id));
    expect(p.batches.every(b => b.length <= 20)).toBe(true); expect(p.skipped).toEqual([]);
    const experiences = (b: string[]) => b.filter(id => p.units.find(u => u.unit_id === id)!.evidence.kind === 'experience').length;
    expect(p.batches.every(b => experiences(b) <= 8)).toBe(true); expect(p.batches.map(experiences)).toContain(8);
    expect(p.units.some(u => u.evidence.id === 'exp-14')).toBe(true);
  });
  it('keeps entire 6000-codepoint experiences with negation and emoji in separate batches', async () => {
    const original = 'I did not lead. ' + '😀'.repeat(5984);
    expect(Array.from(original)).toHaveLength(6000);
    const p = await prep(await make([], [original, 'A second contribution.']));
    expect(p.batches.map(b => b.length)).toEqual([1, 1]); expect(p.units[0].original).toBe(original);
  });
  it.each([16000, 16001, 60000])('never truncates a complete %i-character fact', async (n) => {
    const original = '😀'.repeat(n - 1) + '尾';
    const p = await prep(await make([original], ['Other contribution.']));
    expect(p.units.find(u => u.evidence.kind === 'fact')!.original).toBe(original);
    expect(p.skipped).toHaveLength(n > 16000 ? 1 : 0);
    if (n > 16000) expect(p.skipped[0].reason_code).toBe('unit_too_large');
    expect(p.batches.flat()).toContain(p.units.find(u => u.evidence.kind === 'experience')!.unit_id);
  });
  it('honors summed original budgets and includes every one of 30 experiences', async () => {
    const p = await prep(await make([], Array.from({ length: 30 }, (_, i) => `${i}:` + 'x'.repeat(997))));
    expect(p.batches).toHaveLength(5);
    for (const b of p.batches) expect(b.reduce((n, id) => n + Array.from(p.units.find(u => u.unit_id === id)!.original).length, 0)).toBeLessThanOrEqual(6000);
    expect(p.batches.flat()).toHaveLength(30);
  });
  it('counts every public target field and marks an oversized target without any provider batch', async () => {
    const overhead = [target.opportunity_id, target.title, target.organization, target.source_url, ...target.requirements].reduce((n, t) => n + Array.from(t).length, 0);
    const criteriaLength = JSON.stringify(target.criteria).length + JSON.stringify(target.research).length + JSON.stringify(target.lab).length;
    const exact = await prep(await make(['Python'], [], 'x'.repeat(24000 - overhead - criteriaLength)));
    expect(exact.batches).toHaveLength(1);
    const over = await prep(await make(['Python'], [], 'x'.repeat(24001 - overhead - criteriaLength)));
    expect(over.batches).toEqual([]); expect(over.skipped.map(r => r.reason_code)).toEqual(['target_too_large']);
  });
  it('packs batches against the repeated target, direction and whole-block facts, not only the unit originals', async () => {
    // 14,000 original characters fit one batch by the original budget, but each
    // fact is repeated in its block context next to a long target and direction.
    const facts = ['A'.repeat(7000), 'B'.repeat(7000)];
    const p = await prep(await make(facts, [], 'd'.repeat(20000), 'i'.repeat(8000)));
    expect(p.skipped).toEqual([]);
    expect(p.batches).toEqual(p.units.map(u => [u.unit_id]));
    const small = await prep(await make(facts, [], 'd'.repeat(200), 'i'.repeat(8000)));
    expect(small.batches).toEqual([small.units.map(u => u.unit_id)]);
  });
  it('refuses over-long research interests by name for every unit and never clips them', async () => {
    const at = await make(['Python'], ['Built a parser.'], undefined, 'i'.repeat(7996) + 'TAIL');
    expect((await prep(at)).batches.flat()).toHaveLength(2);
    const over = await make(['Python'], ['Built a parser.'], undefined, 'i'.repeat(7997) + 'TAIL');
    const p = await prep(over);
    expect(p.batches).toEqual([]); expect(p.skipped.map(r => r.reason_code)).toEqual(['interests_too_large', 'interests_too_large']);
    expect(p.draft.base_snapshot.research_interests).toBe('i'.repeat(7997) + 'TAIL');
  });
  it('ignores object insertion order while binding array order, and clones before the first await', async () => {
    const d = await make(['A', 'B']);
    const reorderedKeys = Object.fromEntries(Object.entries(d).reverse());
    expect(unwrap(await prepareTargetResumeAI(reorderedKeys)).document_signature).toBe((await prep(d)).document_signature);
    const pending = prepareTargetResumeAI(d); const original = clone(d); lines(d)[1].text = 'Later edit';
    const captured = unwrap(await pending); expect(captured.draft).toEqual(original);
    expect(Object.isFrozen(captured.units[0])).toBe(true);
    const ordered = clone(original); ordered.document.sections.reverse();
    expect((await prep(ordered)).document_signature).not.toBe(captured.document_signature);
  });
  it.each(['source_signature', 'target_signature'] as const)('rejects forged %s hashes', async key => {
    const d = await make(); d.base = { ...d.base, [key]: key === 'source_signature' ? 'f'.repeat(64) : 'v1:sha256:' + 'f'.repeat(64) };
    expect(await prepareTargetResumeAI(d)).toEqual({ ok: false, code: 'invalid_signature' });
  });
  it('rejects malformed documents rather than silently dropping fields or source status', async () => {
    expect(await prepareTargetResumeAI(null)).toEqual({ ok: false, code: 'invalid_document' });
    const d = clone(await make()); d.base_snapshot.experience_entries[0].status = 'withdrawn';
    expect(await prepareTargetResumeAI(d)).toEqual({ ok: false, code: 'invalid_document' });
  });
});

describe('strict receipts and target quotation', () => {
  it('accepts a kept line with its advice, priority and exact Unicode codepoint link targets', async () => {
    const p = await prep(); const r = response(p); const e = r.receipts.find(x => x.evidence.kind === 'experience')!;
    Object.assign(e, receipt(p, e.unit_id, 'unchanged')); e.suggestion!.priority = 'high';
    const emoji = { field: 'description' as const, requirement_index: null, start: 9, end: 10, quote: '😀' };
    e.suggestion!.links = [{ ...e.suggestion!.links[0], relation: 'broader', target_evidence: emoji }, { ...e.suggestion!.links[0], id: 'L2' }];
    e.suggestion!.target_evidence = [emoji, PYTHON];
    const checked = unwrap(validateTargetResumeAIResponse(p, expected(r), r));
    const kept = checked.receipts.find(x => x.unit_id === e.unit_id)!;
    expect(kept).toMatchObject({ status: 'unchanged', reason_code: 'no_link' }); expect(kept.suggestion!.priority).toBe('high');
    expect(Object.isFrozen(checked.receipts)).toBe(true);
  });
  it.each(['no_link', 'already_aligned', 'no_safe_change', 'cosmetic_only', 'beyond_allowed_edit', 'rewrite_rejected', 'review_rejected', 'no_change'] as const)(
    'accepts a line kept as %s', async (code) => {
      const p = await prep(); const r = response(p); const e = r.receipts.find(x => x.evidence.kind === 'experience')!;
      Object.assign(e, receipt(p, e.unit_id, 'unchanged'), { reason_code: code });
      expect(validateTargetResumeAIResponse(p, expected(r), r).ok).toBe(true);
    });
  it('accepts a reviewed rewrite with its alternative and a second logical call for the review', async () => {
    const p = await prep(); const r = response(p); const e = r.receipts.find(x => x.evidence.kind === 'experience')!;
    Object.assign(e.suggestion!, { ops: ['relabel', 'lead_with'], alternative_text: 'Built a parser, in Python, with the team.',
      alternative_reason: 'Leads with the matching part.' });
    Object.assign(r, { logical_calls: 2, provider_attempts_upper_bound: 4 });
    const checked = unwrap(validateTargetResumeAIResponse(p, expected(r), r));
    expect(checked.receipts.find(x => x.unit_id === e.unit_id)!.suggestion!.links[0].entailed).toBe(true);
  });
  it.each([
    ['wrong signature', (r: TargetResumeAiResponse) => { r.document_signature += 'x'; }],
    ['wrong request', (r: TargetResumeAiResponse) => { r.request_id = 'another'; }],
    ['wrong base', (r: TargetResumeAiResponse) => { r.base.master_revision += 1; }],
    ['wrong manifest order', (r: TargetResumeAiResponse) => { r.manifest.unit_ids.reverse(); }],
    ['missing unit', (r: TargetResumeAiResponse) => { r.receipts.pop(); }],
    ['duplicate unit', (r: TargetResumeAiResponse) => { r.receipts[1] = clone(r.receipts[0]); }],
    ['unknown unit', (r: TargetResumeAiResponse) => { r.receipts[0].unit_id = 'unknown'; }],
    ['wrong block', (r: TargetResumeAiResponse) => { r.receipts[0].block_id = 'another'; }],
    ['wrong revision', (r: TargetResumeAiResponse) => { r.receipts[0].evidence.revision += 1; }],
    ['wrong before text', (r: TargetResumeAiResponse) => { r.receipts[0].before_text += 'manual edit'; }],
    ['fact rewrite', (r: TargetResumeAiResponse) => { Object.assign(factReceipt(r).suggestion!, { proposed_text: 'Expert Python', ops: ['verb_first'] }); }],
    ['blank rewrite', (r: TargetResumeAiResponse) => { exp(r).suggestion!.proposed_text = '  '; }],
    ['oversize rewrite', (r: TargetResumeAiResponse) => { exp(r).suggestion!.proposed_text = 'x'.repeat(6001); }],
    ['invalid unicode', (r: TargetResumeAiResponse) => { exp(r).suggestion!.proposed_text = '\ud800'; }],
    ['NUL', (r: TargetResumeAiResponse) => { exp(r).suggestion!.reason += '\0'; }],
    ['target evidence not from its links', (r: TargetResumeAiResponse) => { exp(r).suggestion!.target_evidence = []; }],
    ['target evidence without a link', (r: TargetResumeAiResponse) => { exp(r).suggestion!.links = []; }],
    ['invented quote', (r: TargetResumeAiResponse) => { for (const x of [exp(r).suggestion!.links[0].target_evidence, exp(r).suggestion!.target_evidence[0]]) x.quote = 'Rust'; }],
    ['bad quote offset', (r: TargetResumeAiResponse) => { for (const x of [exp(r).suggestion!.links[0].target_evidence, exp(r).suggestion!.target_evidence[0]]) x.start = 1; }],
    ['source outside its line', (r: TargetResumeAiResponse) => { exp(r).suggestion!.links[0].source_evidence.start += 1; }],
    ['source in another line', (r: TargetResumeAiResponse) => { exp(r).suggestion!.links[0].source_evidence.unit_id = factReceipt(r).unit_id; }],
    ['entailed broader link', (r: TargetResumeAiResponse) => { exp(r).suggestion!.links[0].relation = 'broader'; }],
    ['repeated link id', (r: TargetResumeAiResponse) => { const s = exp(r).suggestion!; s.links.push(clone(s.links[0])); }],
    ['four links', (r: TargetResumeAiResponse) => { const s = exp(r).suggestion!; s.links = [1, 2, 3, 4].map(i => ({ ...s.links[0], id: `L${i}` })); }],
    ['high priority without a link', (r: TargetResumeAiResponse) => { const s = exp(r).suggestion!; Object.assign(s, { priority: 'high', links: [], target_evidence: [], ops: ['verb_first'] }); }],
    ['rewrite without operations', (r: TargetResumeAiResponse) => { exp(r).suggestion!.ops = []; }],
    ['unknown operation', (r: TargetResumeAiResponse) => { (exp(r).suggestion!.ops as string[]).push('trim'); }],
    ['repeated operation', (r: TargetResumeAiResponse) => { exp(r).suggestion!.ops.push('lead_with'); }],
    ['lead_with without a same link', (r: TargetResumeAiResponse) => { const s = exp(r).suggestion!; Object.assign(s, { links: [], target_evidence: [] }); }],
    ['translation with another move', (r: TargetResumeAiResponse) => { exp(r).suggestion!.ops = ['translate', 'lead_with']; }],
    ['alternative without a relabel', (r: TargetResumeAiResponse) => { Object.assign(exp(r).suggestion!, { alternative_text: 'Built a parser.', alternative_reason: 'Leads with the matching part.' }); }],
    ['alternative equal to the rewrite', (r: TargetResumeAiResponse) => { const s = exp(r).suggestion!; Object.assign(s, { ops: ['relabel'], alternative_text: s.proposed_text, alternative_reason: 'Leads with the matching part.' }); }],
    ['alternative without its own reason', (r: TargetResumeAiResponse) => { Object.assign(exp(r).suggestion!, { ops: ['relabel', 'lead_with'], alternative_text: 'Built a parser, in Python, with the team.' }); }],
    ['blank alternative reason', (r: TargetResumeAiResponse) => { Object.assign(exp(r).suggestion!, { ops: ['relabel', 'lead_with'], alternative_text: 'Built a parser, in Python, with the team.', alternative_reason: ' ' }); }],
    ['alternative reason without an alternative', (r: TargetResumeAiResponse) => { Object.assign(exp(r).suggestion!, { alternative_reason: 'Leads with the matching part.' }); }],
    ['blank reason', (r: TargetResumeAiResponse) => { exp(r).suggestion!.reason = ''; }],
    ['no calls but claims AI', (r: TargetResumeAiResponse) => { r.logical_calls = 0; r.provider_attempts_upper_bound = 0; }],
    ['bound not twice the calls', (r: TargetResumeAiResponse) => { r.logical_calls = 2; }],
    ['three calls', (r: TargetResumeAiResponse) => { Object.assign(r, { logical_calls: 3, provider_attempts_upper_bound: 6 }); }],
    ['partial without skipped', (r: TargetResumeAiResponse) => { r.method = 'partial'; }],
    ['unchanged without suggestion', (r: TargetResumeAiResponse) => { Object.assign(exp(r), { status: 'unchanged', reason_code: 'no_link', suggestion: null }); }],
    ['unchanged with rewrite', (r: TargetResumeAiResponse) => { Object.assign(exp(r), { status: 'unchanged', reason_code: 'no_link' }); }],
    ['unchanged fact line', (r: TargetResumeAiResponse) => { Object.assign(factReceipt(r), { status: 'unchanged', reason_code: 'no_link' }); }],
    ['kept line with operations', (r: TargetResumeAiResponse) => { Object.assign(exp(r), { status: 'unchanged', reason_code: 'no_link' }); exp(r).suggestion!.proposed_text = null; }],
    ['kept with a skip code', (r: TargetResumeAiResponse) => { Object.assign(exp(r), { status: 'unchanged', reason_code: 'timeout' }); Object.assign(exp(r).suggestion!, { proposed_text: null, ops: [] }); }],
    ['suggested experience without a rewrite', (r: TargetResumeAiResponse) => { Object.assign(exp(r).suggestion!, { proposed_text: null, ops: [] }); }],
    ['suggested with no_change code', (r: TargetResumeAiResponse) => { exp(r).reason_code = 'no_change'; }],
    ['skipped with suggestion', (r: TargetResumeAiResponse) => { Object.assign(exp(r), { status: 'skipped', reason_code: 'timeout' }); }],
    ['skipped with a keep code', (r: TargetResumeAiResponse) => { Object.assign(exp(r), { status: 'skipped', reason_code: 'no_link', suggestion: null }); }],
    ['retired v5 code', (r: TargetResumeAiResponse) => { Object.assign(exp(r), { status: 'skipped', reason_code: 'ungrounded_rewrite', suggestion: null }); r.method = 'partial'; }],
  ] as const)('rejects %s atomically', async (_name, mutate) => {
    const p = await prep(); const r = response(p); const request = expected(r); mutate(r);
    expect(validateTargetResumeAIResponse(p, request, r)).toEqual({ ok: false, code: 'invalid_response' });
  });
  it('accepts a target with no quotable text as a stop for every line, with no call', async () => {
    const p = await prep(); const r = response(p);
    Object.assign(r, { method: 'unavailable', logical_calls: 0, provider_attempts_upper_bound: 0 });
    for (const item of r.receipts) Object.assign(item, { status: 'skipped', reason_code: 'target_has_no_text', suggestion: null });
    expect(validateTargetResumeAIResponse(p, expected(r), r).ok).toBe(true);
  });
  it('accepts a request-size refusal only for a request of more than one unit', async () => {
    const p = await prep(); const r = response(p);
    Object.assign(r, { method: 'unavailable', logical_calls: 0, provider_attempts_upper_bound: 0 });
    for (const item of r.receipts) Object.assign(item, { status: 'skipped', reason_code: 'batch_context_too_large', suggestion: null });
    expect(validateTargetResumeAIResponse(p, expected(r), r).ok).toBe(true);
    const single = { ...r, receipts: [r.receipts[0]] };
    expect(validateTargetResumeAIResponse(p, expected(single), single)).toEqual({ ok: false, code: 'invalid_response' });
  });
  it('rejects results from the previous writing rules without changing the draft', async () => {
    const p = await prep(); const before = clone(p.draft); const current = response(p);
    const old = { ...current, pipeline_version: 'full-target-v1' };
    expect(validateTargetResumeAIResponse(p, expected(current), old)).toEqual({ ok: false, code: 'invalid_response' });
    expect(p.draft).toEqual(before);
    expect(validateTargetResumeAIResponse(p, expected(current), current).ok).toBe(true);
  });
  it('rejects unknown keys, undefined keys, sparse arrays and incorrect expected selection', async () => {
    const p = await prep(); const r = response(p);
    for (const value of [{ ...r, extra: 'private' }, { ...r, extra: undefined }, { ...r, receipts: new Array(2) }])
      expect(validateTargetResumeAIResponse(p, expected(r), value).ok).toBe(false);
    expect(validateTargetResumeAIResponse(p, { request_id: 'request', selected_unit_ids: ['unknown'] }, r)).toEqual({ ok: false, code: 'invalid_request' });
    expect(validateTargetResumeAIResponse(p, { request_id: 'request', selected_unit_ids: [p.units[0].unit_id, p.units[0].unit_id] }, r).ok).toBe(false);
  });
});

describe('partial completion, explicit continuation and independent application', () => {
  it('keeps pending/skipped visible and accepts only failed-unit retry without duplicating successes', async () => {
    const p = await prep(); const r = response(p); const failedId = r.receipts[1].unit_id;
    r.receipts[1] = receipt(p, failedId, 'skipped'); r.method = 'partial';
    const partial = unwrap(mergeTargetResumeAIResponses(p, [r, r]));
    expect(partial.coverage).toMatchObject({ total: 2, processed: 1, skipped: 1, pending: 0, complete: false });
    const retry = response(p, [failedId], 'retry');
    const complete = unwrap(mergeTargetResumeAIResponses(p, [r, retry]));
    expect(complete.coverage).toMatchObject({ processed: 2, skipped: 0, complete: true }); expect(complete.structureReady).toBe(true);
    const conflict = clone(retry); conflict.receipts[0].suggestion!.priority = 'low';
    expect(mergeTargetResumeAIResponses(p, [r, retry, conflict])).toEqual({ ok: false, code: 'invalid_response' });
  });
  it('lets a rewrite the review could not check be sent again and replaced', async () => {
    const p = await prep(); const r = response(p); const e = exp(r);
    Object.assign(e, { status: 'skipped', reason_code: 'rewrite_unchecked', suggestion: null });
    Object.assign(r, { method: 'partial', logical_calls: 2, provider_attempts_upper_bound: 4 });
    const first = unwrap(mergeTargetResumeAIResponses(p, [r]));
    expect(first.coverage).toMatchObject({ skipped: 1, rewrites: 0, advice: 1, complete: false });
    const done = unwrap(mergeTargetResumeAIResponses(p, [r, response(p, [e.unit_id], 'retry')]));
    expect(done.coverage).toMatchObject({ skipped: 0, suggested: 2, rewrites: 1, advice: 1, unchanged: 0, complete: true });
  });
  it('applies a selected rewrite without the posting terms only when asked and offered', async () => {
    const p = await prep(); const r = response(p); const e = exp(r);
    Object.assign(e.suggestion!, { ops: ['relabel'], alternative_text: 'Built a parser, in Python, with the team.', alternative_reason: 'Advice.' });
    const plain = unwrap(applyTargetResumeAI(p, p.draft, [r], { ...options(p, [e.unit_id]), alternativeUnitIds: [e.unit_id] }));
    expect(lines(plain).find(l => l.id === e.unit_id)!.text).toBe('Built a parser, in Python, with the team.');
    const tailored = unwrap(applyTargetResumeAI(p, p.draft, [r], options(p, [e.unit_id])));
    expect(lines(tailored).find(l => l.id === e.unit_id)!.text).toBe('Built the Python parser with the team.');
    expect(applyTargetResumeAI(p, p.draft, [r], { ...options(p, []), alternativeUnitIds: [e.unit_id] })).toEqual({ ok: false, code: 'invalid_selection' });
    e.suggestion!.alternative_text = null; delete e.suggestion!.alternative_reason;
    expect(applyTargetResumeAI(p, p.draft, [r], { ...options(p, [e.unit_id]), alternativeUnitIds: [e.unit_id] })).toEqual({ ok: false, code: 'invalid_selection' });
  });
  it('merges out-of-order disjoint batches and counts every unit once', async () => {
    const p = await prep(await make(Array.from({ length: 50 }, (_, i) => `Skill ${i}`), []));
    const rs = p.batches.map((ids, i) => response(p, ids, `r-${i}`)).reverse();
    expect(unwrap(mergeTargetResumeAIResponses(p, rs)).receipts.map(r => r.unit_id)).toEqual(p.units.map(u => u.unit_id));
    expect(unwrap(mergeTargetResumeAIResponses(p, rs.slice(1))).coverage.pending).toBe(p.batches.at(-1)!.length);
  });
  it('never considers skipped or basics-only material complete', async () => {
    const p = await prep(await make(['x'.repeat(16001)], []));
    expect(unwrap(mergeTargetResumeAIResponses(p, [])).structureReady).toBe(false);
    const basics = await prep(await make([], []));
    expect(unwrap(mergeTargetResumeAIResponses(basics, [])).coverage).toMatchObject({ total: 0, protected: 1, complete: false });
  });
  it('requires explicit selection, preserves source and inclusion, and does not implicitly sort', async () => {
    const d = await make(['A'], ['First contribution.', 'Second contribution.']);
    d.document.sections.reverse(); const before = clone(d); const p = await prep(d); const r = response(p);
    const chosen = r.receipts.find(x => x.evidence.kind === 'experience')!;
    const applied = unwrap(applyTargetResumeAI(p, d, [r], options(p, [chosen.unit_id])));
    expect(applied.document.sections.map(s => s.id)).toEqual(d.document.sections.map(s => s.id));
    expect(applied.base_snapshot).toEqual(d.base_snapshot); expect(applied.base).toEqual(d.base);
    for (const line of lines(applied)) expect(line.text).toBe(line.id === chosen.unit_id ? chosen.suggestion!.proposed_text : lines(d).find(l => l.id === line.id)!.text);
    expect(d).toEqual(before); expect(validateTargetResume(applied).ok).toBe(true);
    expect(applyTargetResumeAI(p, applied, [r], options(p, [chosen.unit_id]))).toEqual({ ok: false, code: 'stale_document' });
  });
  it('sorts only whole sections/blocks by mean priority with stable ties, basics first, without rewriting facts', async () => {
    const d = await make(['A', 'B', 'C'], ['First contribution.', 'Second contribution.']);
    d.document.sections.reverse(); const skills = d.document.sections.find(s => s.kind === 'skills')!;
    skills.included = false; skills.blocks[0].included = false; skills.blocks[0].lines[0].included = false;
    const p = await prep(d); const r = response(p);
    const robotics = { field: 'description' as const, requirement_index: null, start: 0, end: 8, quote: 'Robotics' };
    for (const item of r.receipts) {
      item.suggestion!.priority = item.evidence.id === 'skill-0' ? 'low' : item.evidence.id.startsWith('skill-') ? 'high' : 'normal';
      // "high" is a relevance claim, so it comes with a link.
      if (item.suggestion!.priority === 'high') {
        const original = p.units.find(u => u.unit_id === item.unit_id)!.original;
        Object.assign(item.suggestion!, { target_evidence: [robotics], links: [{ id: 'L1', relation: 'broader', entailed: false, target_evidence: robotics,
          source_evidence: { unit_id: item.unit_id, start: 0, end: Array.from(original).length, quote: original }, written_as: null }] });
      }
    }
    const result = unwrap(applyTargetResumeAI(p, d, [r], options(p, [], true)));
    expect(result.document.sections.map(s => s.kind)).toEqual(['basics', 'skills', 'activities']);
    expect(result.document.sections[1].blocks.map(b => b.lines[0].evidence.id)).toEqual(['skill-1', 'skill-2', 'skill-0']);
    expect(result.document.sections[1].included).toBe(false);
    expect(result.document.sections[1].blocks[2]).toMatchObject({ included: false, lines: [expect.objectContaining({ included: false })] });
    expect(lines(result).map(l => ({ ...l })).sort((a, b) => a.id.localeCompare(b.id))).toEqual(lines(d).sort((a, b) => a.id.localeCompare(b.id)));
    expect(result.base_snapshot).toEqual(d.base_snapshot);
  });
  it('rejects structure until all units have valid advice, and rejects fact/unknown/duplicate rewrite selection', async () => {
    const p = await prep(); const r = response(p, [p.units[0].unit_id]);
    expect(applyTargetResumeAI(p, p.draft, [r], options(p, [], true))).toEqual({ ok: false, code: 'incomplete_structure' });
    const full = response(p); const factId = p.units.find(u => u.evidence.kind === 'fact')!.unit_id;
    for (const ids of [[factId], ['unknown'], [p.units[0].unit_id, p.units[0].unit_id]])
      expect(applyTargetResumeAI(p, p.draft, [full], options(p, ids))).toEqual({ ok: false, code: 'invalid_selection' });
  });
  it.each(['profile_signature', 'source_signature', 'target_signature'] as const)('refuses stale current %s even for an otherwise unchanged draft', async key => {
    const p = await prep(); const o = options(p); o.currentContext[key] += 'changed';
    expect(applyTargetResumeAI(p, p.draft, [response(p)], o)).toEqual({ ok: false, code: 'stale_context' });
  });
  it.each([
    ['manual text', (d: TargetResumeV1) => { lines(d)[1].text += 'user edit'; }],
    ['inclusion', (d: TargetResumeV1) => { lines(d)[1].included = false; }],
    ['order', (d: TargetResumeV1) => { d.document.sections.reverse(); }],
    ['new document', (d: TargetResumeV1) => { d.id = 'rebuilt'; }],
    ['source withdrawal', (d: TargetResumeV1) => { d.base_snapshot.experience_entries[0].status = 'withdrawn'; }],
  ] as const)('rejects %s changed since preparation', async (_label, mutate) => {
    const p = await prep(); const d = clone(p.draft); mutate(d);
    expect(applyTargetResumeAI(p, d, [response(p)], options(p))).toEqual({ ok: false, code: 'stale_document' });
  });
  it('rejects final document capacity overflow without trimming or mutating the existing draft', async () => {
    const d = await make(); const all = lines(d); const experience = all.find(l => l.evidence.kind === 'experience')!;
    const basic = all.find(l => l.role === 'name')!; basic.text = 'x'.repeat(2 * 1024 * 1024 - new TextEncoder().encode(JSON.stringify(d)).length - 50);
    expect(validateTargetResume(d).ok).toBe(true);
    const p = await prep(d); const r = response(p); const choice = r.receipts.find(x => x.unit_id === experience.id)!;
    choice.suggestion!.proposed_text = 'x'.repeat(6000); const snapshot = clone(d);
    expect(applyTargetResumeAI(p, d, [r], options(p, [choice.unit_id]))).toEqual({ ok: false, code: 'document_too_large' });
    expect(d).toEqual(snapshot);
  });
});


it('rejects a legacy prepared object at response validation, merge and application without relying on prepare', () => {
  const draft = clone(legacyGolden.draft) as TargetResumeV1;
  const canonicalDraft = JSON.stringify(draft, (_key, value: unknown) => value && typeof value === 'object' && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : value);
  const legacy: PreparedTargetResumeAi = { draft, document_signature: legacyGolden.document_signature,
    canonical_draft: canonicalDraft, units: clone(legacyGolden.units) as PreparedTargetResumeAi['units'],
    protected_unit_count: legacyGolden.manifest.protected_unit_count, batches: [legacyGolden.manifest.unit_ids], skipped: [] };
  const oldResponse = response(legacy);
  expect(validateTargetResumeAIResponse(legacy, expected(oldResponse), oldResponse)).toEqual({ ok: false, code: 'legacy_target_context' });
  expect(mergeTargetResumeAIResponses(legacy, [oldResponse])).toEqual({ ok: false, code: 'legacy_target_context' });
  expect(applyTargetResumeAI(legacy, draft, [oldResponse], options(legacy))).toEqual({ ok: false, code: 'legacy_target_context' });
  expect(draft).toEqual(legacyGolden.draft);
});


describe('negotiated source-check rule metadata', () => {
  it('keeps legacy metadata unknown and preserves the reported rule without upgrading it', async () => {
    const p = await prep(); const r = response(p);
    const old = unwrap(validateTargetResumeAIResponse(p, expected(r), r));
    expect(Object.hasOwn(old, 'check_version')).toBe(false);
    for (const version of [null, 'target-resume-source-checks-v1', 'target-resume-source-checks-v42']) {
      r.check_version = version;
      expect(unwrap(validateTargetResumeAIResponse(p, expected(r), r)).check_version).toBe(version);
    }
  });
  it.each(['', 'full-target-v2', 'target-resume-source-checks-v0', true, 123, { verified: true }])('rejects malformed rule metadata %j', async value => {
    const p = await prep(); const r = response(p);
    Object.assign(r, { check_version: value });
    expect(validateTargetResumeAIResponse(p, expected(r), r)).toEqual({ ok: false, code: 'invalid_response' });
  });
});
