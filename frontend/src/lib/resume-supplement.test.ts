import { describe, expect, it } from 'vitest';
import type { ExperienceEntry, ProfileData, ResumeFact } from './types';
import { createEmptyResumeMaster, validateResumeMaster } from './resume-master';
import { validateExperienceEntries } from './experience-evidence';
import { prepareConfirmedSupplement, previewSupplement, SUPPLEMENT_ANSWER_KEYS, type SupplementAnswers, type SupplementDraft } from './resume-supplement';

const answers = (extra: Partial<SupplementAnswers> = {}): SupplementAnswers => ({ task: '', method: '', personalRole: '', outcome: '', outcomeBasis: '', ...extra });
const draft = (extra: Partial<SupplementDraft> = {}): SupplementDraft => ({ entryId: 'new', activityId: 'activity', answers: answers({ task: 'Documented tests.' }), selected: ['task'], ...extra });
const entry = (id: string, text = 'Existing experience.', extra: Partial<ExperienceEntry> = {}): ExperienceEntry => ({ id, revision: 1, status: 'confirmed', text, source: { kind: 'manual' }, ...extra });
const fact = (id: string, value = 'Original title'): ResumeFact => ({ id, revision: 4, status: 'candidate', value, source: { kind: 'manual' } });
function profile(): ProfileData {
  const master = createEmptyResumeMaster('master');
  master.revision = 7;
  master.basics.name = fact('name', 'Student Name');
  master.activities = [{ id: 'activity', kind: 'research', title: fact('title'), details: [{ id: 'previous', revision: 3 }] }, { id: 'other', kind: 'project', details: [] }];
  return { institution: 'UIUC', college: 'Engineering', major: 'ECE', grade: 'Sophomore', is_international: true,
    research_interests: 'Measurement', skills: [{ name: 'Python', level: 'beginner', confirmed: true }], coursework: ['ECE 110'],
    resume_text: 'Original source\n😀 exact end.  ', experience_entries: [entry('previous', 'Did not lead the team.', {
      revision: 3, status: 'withdrawn', source: { kind: 'resume', signature: 'a'.repeat(64), quote: 'Original source', start: 0, end: 15 },
    })], resume_master: master, home_school: undefined };
}
function freeze<T>(value: T): T {
  if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}

describe('unconfirmed literal preview', () => {
  it('keeps fixed question order and exact negation, team role, numbers and whitespace', () => {
    const input = draft({ answers: answers({ task: '  I did not lead.\r\nI logged tests.  ', method: 'Python 3.12; 2 sensors.', personalRole: 'Our team built it; I recorded data only.', outcome: 'No significant result.', outcomeBasis: 'Notebook p. 17: 2/20 trials, unverified.' }), selected: ['outcomeBasis', 'outcome', 'personalRole', 'method', 'task'] });
    const before = structuredClone(input);
    expect(previewSupplement(freeze(input))).toEqual({ ok: true, previewText: 'Task:   I did not lead.\r\nI logged tests.  \nMethod: Python 3.12; 2 sensors.\nMy role: Our team built it; I recorded data only.\nOutcome: No significant result.\nOutcome basis: Notebook p. 17: 2/20 trials, unverified.' });
    expect(input).toEqual(before);
  });
  it('allows an empty outcome and omits unchecked/blank answers without modifying buffers', () => {
    const input = draft({ answers: answers({ task: 'Only task.', method: ' \t\n', outcome: 'Unchecked.' }), selected: ['task', 'method'] });
    expect(previewSupplement(input)).toEqual({ ok: true, previewText: 'Task: Only task.' });
    expect(input.answers.outcome).toBe('Unchecked.');
    expect(input.answers.method).toBe(' \t\n');
  });
  it.each([draft({ selected: [] }), draft({ answers: answers() }), draft({ answers: answers({ task: ' \t\n', outcome: 'unchecked' }) })])('rejects empty selection without inventing claims', (input) => {
    expect(previewSupplement(input)).toEqual({ ok: false, reason: 'empty' });
  });
  it('counts Unicode codepoints including all labels and separators at 6000', () => {
    const full = '😀'.repeat(5_993) + '尾';
    expect(previewSupplement(draft({ answers: answers({ task: full }) }))).toEqual({ ok: true, previewText: `Task: ${full}` });
    expect(previewSupplement(draft({ answers: answers({ task: full + '超' }) }))).toEqual({ ok: false, reason: 'limit' });
    const combined = draft({ answers: answers({ task: 'x'.repeat(2_990), method: 'y'.repeat(2_995) }), selected: ['task', 'method'] });
    expect(previewSupplement(combined).ok).toBe(true);
    combined.answers.method += 'z';
    expect(previewSupplement(combined)).toEqual({ ok: false, reason: 'limit' });
  });
  it('does not count or truncate long unchecked answers', () => {
    const input = draft({ answers: answers({ task: 'Included.', outcome: 'x'.repeat(60_001) }) });
    expect(previewSupplement(input)).toEqual({ ok: true, previewText: 'Task: Included.' });
    expect(input.answers.outcome).toHaveLength(60_001);
  });
  it.each([null, {}, { answers: null, selected: [] }, { answers: answers(), selected: null },
    { answers: answers(), selected: ['task', 'task'] }, { answers: answers(), selected: ['unknown'] }, { answers: answers(), selected: new Array(1) },
    { answers: { task: 'missing fields' }, selected: ['task'] }, { answers: { ...answers(), extra: 'unknown' }, selected: [] },
    { answers: answers({ task: 7 as unknown as string }), selected: ['task'] },
    ...['\ud800', '\udfff', 'secret\0text'].map((task) => ({ answers: answers({ task }), selected: ['task'] })),
  ])('safely rejects malformed input %#', (input) => {
    expect(previewSupplement(input as never)).toEqual({ ok: false, reason: 'invalid' });
  });
  it('does not echo private accessor errors', () => {
    expect(previewSupplement({ get answers() { throw new Error('private secret'); }, selected: ['task'] } as never)).toEqual({ ok: false, reason: 'invalid' });
  });
  it('exports the fixed order', () => expect(SUPPLEMENT_ANSWER_KEYS).toEqual(['task', 'method', 'personalRole', 'outcome', 'outcomeBasis']));
});

describe('confirmed supplement desired profile', () => {
  it('builds one confirmed manual entry and one activity ref while preserving everything else', () => {
    const input = profile(); const before = structuredClone(input);
    const result = prepareConfirmedSupplement(freeze(input), freeze(draft()));
    if (!result.ok) throw new Error(result.reason);
    expect(result.entry).toEqual({ id: 'new', revision: 1, status: 'confirmed', text: 'Task: Documented tests.', source: { kind: 'manual' } });
    expect(result.previewText).toBe(result.entry.text);
    expect(result.desired.experience_entries).toEqual([...before.experience_entries!, result.entry]);
    expect(result.desired.resume_master).toEqual({ ...before.resume_master!, revision: 8, activities: before.resume_master!.activities.map((item) => item.id === 'activity' ? { ...item, details: [...item.details, { id: 'new', revision: 1 }] } : item) });
    expect({ ...result.desired, experience_entries: before.experience_entries, resume_master: before.resume_master }).toEqual(before);
    expect(Object.hasOwn(result.desired, 'home_school')).toBe(true);
    expect(validateExperienceEntries(result.desired.experience_entries).ok).toBe(true);
    expect(validateResumeMaster(result.desired.resume_master).ok).toBe(true);
    expect(input).toEqual(before);
  });
  it('deeply isolates every output from input and the separate entry receipt', () => {
    const input = profile(); const before = structuredClone(input); const inputDraft = draft();
    const result = prepareConfirmedSupplement(input, inputDraft);
    if (!result.ok) throw new Error(result.reason);
    result.desired.skills[0].level = 'expert'; result.desired.coursework!.push('Later');
    result.desired.resume_master!.activities[0].title!.value = 'Changed title';
    result.desired.experience_entries![0].source = { kind: 'manual' };
    result.entry.text = 'Changed receipt'; inputDraft.answers.task = 'Changed buffer';
    expect(result.desired.experience_entries!.at(-1)!.text).toBe('Task: Documented tests.'); expect(input).toEqual(before);
  });
  it('preserves historical statuses/revisions and stale references, without upgrading skills', () => {
    const input = profile();
    input.experience_entries = ['candidate', 'confirmed', 'rejected', 'withdrawn'].map((status, i) => entry(`old-${i}`, `History ${i}`, { status: status as ExperienceEntry['status'], revision: i + 9 }));
    input.resume_master!.activities[0].details = [{ id: 'old-0', revision: 1 }];
    const result = prepareConfirmedSupplement(input, draft()); if (!result.ok) throw new Error(result.reason);
    expect(result.desired.experience_entries!.slice(0, 4)).toEqual(input.experience_entries);
    expect(result.desired.resume_master!.activities[0].details[0]).toEqual({ id: 'old-0', revision: 1 });
    expect(result.desired.skills).toEqual(input.skills);
  });
  it('supports legacy missing entries without replacing raw text', () => {
    const input = profile(); delete input.experience_entries;
    const result = prepareConfirmedSupplement(input, draft()); if (!result.ok) throw new Error(result.reason);
    expect(result.desired.experience_entries).toEqual([result.entry]); expect(result.desired.resume_text).toBe(input.resume_text);
  });
  it.each([undefined, null])('reports absent master %s', (resume_master) => {
    expect(prepareConfirmedSupplement({ ...profile(), resume_master }, draft())).toEqual({ ok: false, reason: 'missing-master' });
  });
  it('does not substitute an activity', () => expect(prepareConfirmedSupplement(profile(), draft({ activityId: 'missing' }))).toEqual({ ok: false, reason: 'missing-activity' }));
  it.each(['candidate', 'confirmed', 'rejected', 'withdrawn'] as const)('will not overwrite an existing %s entry id', (status) => {
    const input = profile(); input.experience_entries!.push(entry('new', 'Old content', { status })); const before = structuredClone(input);
    expect(prepareConfirmedSupplement(input, draft())).toEqual({ ok: false, reason: 'duplicate-id' }); expect(input).toEqual(before);
  });
  it.each(['education', 'activities', 'publications'] as const)('will not activate a dangling historical %s reference', (section) => {
    const input = profile();
    if (section === 'activities') input.resume_master!.activities[1].details = [{ id: 'new', revision: 1 }];
    else input.resume_master![section] = [{ id: 'record', details: [{ id: 'new', revision: 17 }] }];
    expect(prepareConfirmedSupplement(input, draft())).toEqual({ ok: false, reason: 'duplicate-id' });
  });
  it('will not append a saved operation twice', () => {
    const result = prepareConfirmedSupplement(profile(), draft()); if (!result.ok) throw new Error(result.reason);
    expect(prepareConfirmedSupplement(result.desired, draft())).toEqual({ ok: false, reason: 'duplicate-id' });
  });
  it('increments safely up to MAX_SAFE_INTEGER only', () => {
    const input = profile(); input.resume_master!.revision = Number.MAX_SAFE_INTEGER - 1;
    const result = prepareConfirmedSupplement(input, draft()); if (!result.ok) throw new Error(result.reason);
    expect(result.desired.resume_master!.revision).toBe(Number.MAX_SAFE_INTEGER);
    expect(prepareConfirmedSupplement(result.desired, draft({ entryId: 'next' }))).toEqual({ ok: false, reason: 'revision-limit' });
  });
  it('allows 100 entries exactly and refuses 101 without trimming', () => {
    const input = profile(); input.experience_entries = Array.from({ length: 99 }, (_, i) => entry(`old-${i}`));
    const result = prepareConfirmedSupplement(input, draft()); if (!result.ok) throw new Error(result.reason);
    expect(result.desired.experience_entries).toHaveLength(100);
    expect(prepareConfirmedSupplement(result.desired, draft({ entryId: 'next' }))).toEqual({ ok: false, reason: 'limit' });
    expect(input.experience_entries).toHaveLength(99);
  });
  it('counts withdrawn entries toward the 60000 aggregate text limit', () => {
    const input = profile(); input.experience_entries = Array.from({ length: 10 }, (_, i) => entry(`old-${i}`, 'x'.repeat(i === 9 ? 5993 : 6000), { status: 'withdrawn' }));
    expect(prepareConfirmedSupplement(input, draft({ answers: answers({ task: 'x' }) })).ok).toBe(true);
    expect(prepareConfirmedSupplement(input, draft({ answers: answers({ task: 'xx' }) }))).toEqual({ ok: false, reason: 'limit' });
  });
  it('enforces 300 references across categories including historical references', () => {
    const input = profile(); input.resume_master!.education = [{ id: 'school', details: Array.from({ length: 299 }, (_, i) => ({ id: `history-${i}`, revision: 9 })) }]; input.resume_master!.activities[0].details = [];
    const result = prepareConfirmedSupplement(input, draft()); if (!result.ok) throw new Error(result.reason);
    expect(result.desired.resume_master!.activities[0].details).toEqual([{ id: 'new', revision: 1 }]);
    expect(prepareConfirmedSupplement(result.desired, draft({ entryId: 'next' }))).toEqual({ ok: false, reason: 'limit' });
  });
  it('preserves full 60000-codepoint master facts and source text', () => {
    const input = profile(); input.resume_master!.basics = { links: [], name: fact('long', '😀'.repeat(60000)) }; delete input.resume_master!.activities[0].title; input.resume_text = '界'.repeat(60000);
    const result = prepareConfirmedSupplement(input, draft()); if (!result.ok) throw new Error(result.reason);
    expect(result.desired.resume_master!.basics.name!.value).toBe(input.resume_master!.basics.name!.value);
    expect(result.desired.resume_text).toBe(input.resume_text);
    expect(prepareConfirmedSupplement({ ...input, resume_text: input.resume_text + '超' }, draft())).toEqual({ ok: false, reason: 'limit' });
  });
  it.each(['', '  ', 'x'.repeat(81), '\ud800', 'nul\0id'])('rejects invalid supplied ids %#', (id) => {
    expect(prepareConfirmedSupplement(profile(), draft({ entryId: id }))).toEqual({ ok: false, reason: 'invalid' });
    expect(prepareConfirmedSupplement(profile(), draft({ activityId: id }))).toEqual({ ok: false, reason: 'invalid' });
  });
  it.each([{ experience_entries: null }, { experience_entries: [{ id: 'malformed' }] }, { resume_master: {} }, { resume_text: 42 }, { resume_text: 'private\0text' }, { resume_text: '\udfff' }])('rejects invalid existing data without a partial output %#', (extra) => {
    expect(prepareConfirmedSupplement({ ...profile(), ...extra } as ProfileData, draft())).toEqual({ ok: false, reason: 'invalid' });
  });
  it('rejects unknown draft fields and non-cloneable data without echoing it', () => {
    expect(prepareConfirmedSupplement(profile(), { ...draft(), operationId: 'controller only' } as SupplementDraft)).toEqual({ ok: false, reason: 'invalid' });
    expect(prepareConfirmedSupplement({ ...profile(), name: (() => 'secret') as unknown as string }, draft())).toEqual({ ok: false, reason: 'invalid' });
  });
});
