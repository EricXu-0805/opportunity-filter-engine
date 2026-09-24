import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import golden from '../../../tests/fixtures/target-resume-ai-golden.json';
import { createEmptyResumeMaster } from './resume-master';
import { createTargetResume, validateTargetResume, type TargetResumeV1 } from './target-resume';
import type { ExperienceEntry, ProfileData, ResumeFact } from './types';
import type { PreparedTargetResumeAi, TargetResumeAiReceipt, TargetResumeAiResponse } from './target-resume-ai-protocol';
import { prepareTargetResumeAI, validateTargetResumeAIResponse, mergeTargetResumeAIResponses, applyTargetResumeAI, type TargetResumeAIResult } from './target-resume-ai';

beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const unwrap = <T,>(v: TargetResumeAIResult<T>): T => { if (!v.ok) throw Error(v.code); return v.value; };
const lines = (v: TargetResumeV1) => v.document.sections.flatMap(s => s.blocks.flatMap(b => b.lines));
const fact = (id: string, value: string): ResumeFact => ({ id, value, revision: 1, status: 'confirmed', source: { kind: 'manual' } });
const target = { opportunity_id: 'opp', title: 'Robotics', organization: 'University', source_url: '', description: 'Robotics 😀 materials.', requirements: ['Python', '😀研究'] };
async function make(facts: string[] = ['Python'], experiences: string[] = ['Built a Python parser.'], description?: string) {
  const master = createEmptyResumeMaster('master');
  master.basics = { name: fact('name', 'Student'), links: [] };
  if (facts.reduce((n, value) => n + Array.from(value).length, 0) === 60000) master.basics = { links: [] };
  master.skills = facts.map((value, i) => fact(`skill-${i}`, value));
  const entries: ExperienceEntry[] = experiences.map((text, i) => ({ id: `exp-${i}`, revision: 1, status: 'confirmed', text, source: { kind: 'manual' } }));
  master.activities = entries.map(e => ({ id: `activity-${e.id}`, kind: 'project', details: [{ id: e.id, revision: e.revision }] }));
  const profile: ProfileData = { institution: 'UIUC', college: 'Engineering', major: 'Engineering', grade: 'junior', is_international: false,
    research_interests: '', skills: [], resume_text: '', experience_entries: entries, resume_master: master };
  return createTargetResume(profile, description === undefined ? target : { ...target, description }, 'draft');
}
const prep = async (draft?: TargetResumeV1) => unwrap(await prepareTargetResumeAI(draft ?? await make()));
function receipt(p: PreparedTargetResumeAi, id: string, status: TargetResumeAiReceipt['status'] = 'suggested'): TargetResumeAiReceipt {
  const u = p.units.find(u => u.unit_id === id)!;
  return { unit_id: id, section_id: u.section_id, block_id: u.block_id, evidence: clone(u.evidence), before_text: u.before_text,
    status, reason_code: status === 'skipped' ? 'model_unavailable' : status === 'unchanged' ? 'no_change' : null,
    suggestion: status === 'skipped' ? null : { priority: 'normal', reason: 'Relevant to the stated Python requirement.',
      target_evidence: [{ field: 'requirement', requirement_index: 0, start: 0, end: 6, quote: 'Python' }],
      proposed_text: status === 'suggested' && u.evidence.kind === 'experience' ? 'Built the Python parser with the team.' : null } };
}
function response(p: PreparedTargetResumeAi, ids = p.batches[0], request_id = 'request'): TargetResumeAiResponse {
  return { version: 1, pipeline_version: 'full-target-v1', request_id, document_id: p.draft.id, opportunity_id: p.draft.opportunity_id,
    document_signature: p.document_signature, base: clone(p.draft.base), manifest: { unit_ids: p.units.map(u => u.unit_id), protected_unit_count: p.protected_unit_count },
    method: 'ai', logical_calls: 1, provider_attempts_upper_bound: 2, receipts: ids.map(id => receipt(p, id)) };
}
const expected = (r: TargetResumeAiResponse) => ({ request_id: r.request_id, selected_unit_ids: r.receipts.map(x => x.unit_id) });
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
  it('traverses more than eight experiences and more than 24 units without omitting any tail', async () => {
    const p = await prep(await make(Array.from({ length: 30 }, (_, i) => `Skill ${i}`), Array.from({ length: 15 }, (_, i) => `I did not lead project ${i}. I contributed one parser.`)));
    expect(p.units).toHaveLength(45); expect(p.batches.flat()).toEqual(p.units.map(u => u.unit_id));
    expect(p.batches.every(b => b.length <= 24)).toBe(true); expect(p.skipped).toEqual([]);
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
    const exact = await prep(await make(['Python'], [], 'x'.repeat(24000 - overhead)));
    expect(exact.batches).toHaveLength(1);
    const over = await prep(await make(['Python'], [], 'x'.repeat(24001 - overhead)));
    expect(over.batches).toEqual([]); expect(over.skipped.map(r => r.reason_code)).toEqual(['target_too_large']);
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
  it('accepts genuine unchanged priorities and exact Unicode codepoint evidence', async () => {
    const p = await prep(); const r = response(p); const e = r.receipts.find(x => x.evidence.kind === 'experience')!;
    Object.assign(e, receipt(p, e.unit_id, 'unchanged')); e.suggestion!.priority = 'high';
    e.suggestion!.target_evidence = [{ field: 'description', requirement_index: null, start: 9, end: 10, quote: '😀' }];
    const checked = unwrap(validateTargetResumeAIResponse(p, expected(r), r));
    expect(checked.receipts[0].suggestion!.priority).toBe('high'); expect(Object.isFrozen(checked.receipts)).toBe(true);
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
    ['fact rewrite', (r: TargetResumeAiResponse) => { r.receipts.find(x => x.evidence.kind === 'fact')!.suggestion!.proposed_text = 'Expert Python'; }],
    ['blank rewrite', (r: TargetResumeAiResponse) => { r.receipts[0].suggestion!.proposed_text = '  '; }],
    ['oversize rewrite', (r: TargetResumeAiResponse) => { r.receipts[0].suggestion!.proposed_text = 'x'.repeat(6001); }],
    ['invalid unicode', (r: TargetResumeAiResponse) => { r.receipts[0].suggestion!.proposed_text = '\ud800'; }],
    ['NUL', (r: TargetResumeAiResponse) => { r.receipts[0].suggestion!.reason += '\0'; }],
    ['missing target evidence', (r: TargetResumeAiResponse) => { r.receipts[0].suggestion!.target_evidence = []; }],
    ['invented quote', (r: TargetResumeAiResponse) => { r.receipts[0].suggestion!.target_evidence[0].quote = 'Rust'; }],
    ['bad quote offset', (r: TargetResumeAiResponse) => { r.receipts[0].suggestion!.target_evidence[0].start = 1; }],
    ['blank reason', (r: TargetResumeAiResponse) => { r.receipts[0].suggestion!.reason = ''; }],
    ['no calls but claims AI', (r: TargetResumeAiResponse) => { r.logical_calls = 0; r.provider_attempts_upper_bound = 0; }],
    ['partial without skipped', (r: TargetResumeAiResponse) => { r.method = 'partial'; }],
    ['unchanged without suggestion', (r: TargetResumeAiResponse) => { Object.assign(r.receipts[0], { status: 'unchanged', reason_code: 'no_change', suggestion: null }); }],
    ['unchanged with rewrite', (r: TargetResumeAiResponse) => { Object.assign(r.receipts[0], { status: 'unchanged', reason_code: 'no_change' }); }],
    ['suggested with no_change code', (r: TargetResumeAiResponse) => { r.receipts[0].reason_code = 'no_change'; }],
    ['skipped with suggestion', (r: TargetResumeAiResponse) => { Object.assign(r.receipts[0], { status: 'skipped', reason_code: 'timeout' }); }],
  ] as const)('rejects %s atomically', async (_name, mutate) => {
    const p = await prep(); const r = response(p); const request = expected(r); mutate(r);
    expect(validateTargetResumeAIResponse(p, request, r)).toEqual({ ok: false, code: 'invalid_response' });
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
  it('merges out-of-order disjoint batches and counts every unit once', async () => {
    const p = await prep(await make(Array.from({ length: 50 }, (_, i) => `Skill ${i}`), []));
    const rs = p.batches.map((ids, i) => response(p, ids, `r-${i}`)).reverse();
    expect(unwrap(mergeTargetResumeAIResponses(p, rs)).receipts.map(r => r.unit_id)).toEqual(p.units.map(u => u.unit_id));
    expect(unwrap(mergeTargetResumeAIResponses(p, rs.slice(1))).coverage.pending).toBe(2);
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
    for (const item of r.receipts) item.suggestion!.priority = item.evidence.id === 'skill-0' ? 'low' : item.evidence.id.startsWith('skill-') ? 'high' : 'normal';
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
