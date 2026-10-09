import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import type { Opportunity, ProfileData, ResumeProcessingCoverage } from './types';
import { isPublicDetail } from './public-target-shape';
import { compareDraft, createBinding, createDraft, decodeDraft, draftLineSources, editDraft, encodeDraft, reviewDraft,
  TAILOR_DRAFT_RULE_VERSION, TailorDraftError, type TailorDraftBinding } from './tailor-draft';

function profile(): ProfileData {
  return { institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore', is_international: false,
    research_interests: 'instrumentation', skills: [{ name: 'Python', level: 'beginner' }], coursework: ['CS 225'],
    resume_text: '  Built sensors.\r\n原始经历 🧑🏽‍🔬\n',
    experience_entries: [{ id: 'e1', revision: 1, status: 'confirmed', text: 'Built sensors.', source: { kind: 'manual' } }],
  };
}
function target(): Opportunity {
  return { id: 'opp-1', title: '材料研究 🧪', organization: 'Example lab', opportunity_type: 'research', paid: 'unknown', location: 'Campus', on_campus: true,
    description_clean: '  Calibrate sensors.\r\nExact description.', keywords: ['sensors', 'calibration'], record_kind: 'listing', source_type: 'campus_program',
    eligibility: { preferred_year: ['Sophomore'], majors: ['CS'], skills_required: ['Python'], international_friendly: 'unknown', citizenship_required: null },
    application: { contact_method: 'form', requires_resume: 'yes', application_effort: 'low' },
    metadata: { confidence_score: 0.9, is_active: true },
  };
}
const canonical = (value: unknown): string => JSON.stringify(value, (_key, item: unknown) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : item);
const hash = (text: string) => createHash('sha256').update(text).digest('hex');
const binding = (extra: Partial<TailorDraftBinding> = {}): TailorDraftBinding => ({ profile_sig: 'a'.repeat(64), target_sig: 'b'.repeat(64), resume_sig: 'c'.repeat(64), pipeline_version: 'w13.2', rule_version: TAILOR_DRAFT_RULE_VERSION, ...extra });
const draft = (text = '  中文 🧪 exact text\r\nTail.  ') => createDraft('owner-a', 'opp-1', text, 'extract', binding());
beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('complete material bindings', () => {
  it('hashes the full unnormalized profile, public target and raw resume independently', async () => {
    const p = profile(); const t = target();
    expect(await createBinding(p, t, 'w13.2')).toEqual({ profile_sig: hash(canonical(p)), target_sig: hash(canonical(t)), resume_sig: hash(p.resume_text!), pipeline_version: 'w13.2', rule_version: TAILOR_DRAFT_RULE_VERSION });
  });
  it('ignores object insertion order but observes array order, whitespace, and nested criteria', async () => {
    const p = profile(); const t = target(); const original = await createBinding(p, t, 'w13.2');
    const reversedP = Object.fromEntries(Object.entries(p).reverse()) as unknown as ProfileData;
    const reversedT = Object.fromEntries(Object.entries(t).reverse()) as unknown as Opportunity;
    expect(await createBinding(reversedP, reversedT, 'w13.2')).toEqual(original);
    const next = { ...t, eligibility: { ...t.eligibility, citizenship_required: true } };
    expect((await createBinding(p, next, 'w13.2')).target_sig).not.toBe(original.target_sig);
    expect((await createBinding(p, { ...t, keywords: [...t.keywords].reverse() }, 'w13.2')).target_sig).not.toBe(original.target_sig);
    expect((await createBinding({ ...p, resume_text: p.resume_text!.trim() }, t, 'w13.2')).resume_sig).not.toBe(original.resume_sig);
  });
  it('detects skills, withdrawn evidence, source deletion and pipeline changes even without a different target id', async () => {
    const p = profile(); const t = target(); const original = await createBinding(p, t, 'w13.2');
    const entry = p.experience_entries![0];
    const variants: ProfileData[] = [
      { ...p, skills: [{ name: 'Python', level: 'experienced' }] },
      { ...p, experience_entries: [{ ...entry, status: 'withdrawn', revision: 2 }] },
      { ...p, resume_text: '' },
    ];
    for (const changed of variants) expect((await createBinding(changed, t, 'w13.2')).profile_sig).not.toBe(original.profile_sig);
    const empty = await createBinding({ ...p, resume_text: '' }, t, 'w13.2');
    expect(empty.resume_sig).toBe(hash('')); expect(empty.resume_sig).not.toBe(original.resume_sig);
    expect(await compareDraft(createDraft('owner-a', t.id, 'Original text', 'heuristic', original), empty)).toBe('stale');
    expect(await compareDraft(createDraft('owner-a', t.id, 'Original text', 'heuristic', original), { ...original, pipeline_version: 'w13.3' })).toBe('stale');
    expect(await compareDraft(createDraft('owner-a', t.id, 'Original text', 'heuristic', original), { ...original, rule_version: 'next-rule' })).toBe('stale');
  });
  it('captures all inputs before asynchronous digest resolution', async () => {
    const captured: Uint8Array[] = []; const settle: Array<() => void> = [];
    vi.stubGlobal('crypto', { subtle: { digest: (_algorithm: string, bytes: Uint8Array) => {
      captured.push(new Uint8Array(bytes)); return new Promise<ArrayBuffer>((resolve, reject) => {
        settle.push(() => { void webcrypto.subtle.digest('SHA-256', bytes).then(resolve, reject); });
      });
    } } });
    const p = profile(); const t = target(); const oldProfile = canonical(p); const oldTarget = canonical(t); const oldResume = p.resume_text!;
    const pending = createBinding(p, t, 'w13.2');
    p.resume_text = 'MUTATED'; p.skills[0].name = 'MUTATED'; t.eligibility.majors.push('MUTATED');
    expect(captured.map(bytes => new TextDecoder().decode(bytes))).toEqual([oldProfile, oldTarget, oldResume]);
    settle.forEach(done => done());
    expect(await pending).toEqual({ profile_sig: hash(oldProfile), target_sig: hash(oldTarget), resume_sig: hash(oldResume), pipeline_version: 'w13.2', rule_version: TAILOR_DRAFT_RULE_VERSION });
  });
  it('allows optional undefined profile properties but rejects non-JSON values rather than normalizing them', async () => {
    const p = profile(); expect(await createBinding({ ...p, name: undefined }, target(), 'w13.2')).toEqual(await createBinding(p, target(), 'w13.2'));
    for (const extra of [NaN, Infinity, new Date(), [undefined], Array(1), { toJSON: () => 'spoof' }, '\ud800']) {
      await expect(createBinding({ ...p, extra } as ProfileData, target(), 'w13.2')).rejects.toBeInstanceOf(TailorDraftError);
    }
    const cycle: Record<string, unknown> = {}; cycle.again = cycle;
    await expect(createBinding({ ...p, cycle } as ProfileData, target(), 'w13.2')).rejects.toBeInstanceOf(TailorDraftError);
  });
  it.each([null, { id: 'opp-1', title: 'ID and title only' }, { ...target(), metadata: undefined }, { ...target(), contact_email: 'private@example.test' }, { ...target(), record_kind: ['listing'] }, { ...target(), eligibility: { ...target().eligibility, majors: 'CS' } }])('does not establish provenance from malformed or nonpublic targets', async value => {
    await expect(createBinding(profile(), value as unknown as Opportunity, 'w13.2')).rejects.toBeInstanceOf(TailorDraftError);
  });
  it('fails closed when the pipeline version or secure digest is unavailable, without leaking material', async () => {
    await expect(createBinding(profile(), target(), '')).rejects.toMatchObject({ code: 'invalid_binding' });
    vi.stubGlobal('crypto', { subtle: { digest: () => Promise.reject(new Error('PRIVATE INPUT CONTENT')) } });
    const error = await createBinding(profile(), target(), 'w13.2').catch((value: unknown) => value);
    expect(error).toMatchObject({ code: 'signature_unavailable' }); expect((error as Error).message).not.toContain('PRIVATE'); expect(error).not.toHaveProperty('cause');
  });
});

describe('immutable origin and exact-text review', () => {
  it('keeps a fresh origin current without pretending an explicit review happened', async () => {
    const original = draft(); expect(original.review).toBeNull(); expect(await compareDraft(original, binding())).toBe('current');
    const edited = editDraft(original, 'A manually rewritten line.');
    expect(edited.origin).toEqual(original.origin); expect(edited.review).toBeNull(); expect(original.text).not.toBe(edited.text);
    expect(await compareDraft(edited, binding())).toBe('current');
  });
  it('never rebinds old text on edit; explicit review is a separate exact-text record', async () => {
    const original = draft(); const newer = binding({ profile_sig: 'd'.repeat(64) });
    const edited = editDraft(original, 'My updated draft.'); expect(await compareDraft(edited, newer)).toBe('stale');
    const reviewed = await reviewDraft(edited, newer);
    expect(reviewed.origin).toEqual(original.origin); expect(reviewed.review).toEqual({ text_sig: hash(edited.text), binding: newer });
    expect(await compareDraft(reviewed, newer)).toBe('current');
    const editedAgain = editDraft(reviewed, 'My updated draft. ');
    expect(editedAgain.origin).toEqual(original.origin); expect(editedAgain.review).toEqual(reviewed.review);
    expect(await compareDraft(editedAgain, newer)).toBe('stale'); expect(await compareDraft(reviewed, binding({ target_sig: 'e'.repeat(64) }))).toBe('stale');
  });
  it('does not fall back to origin A after exact-text review against B and a return to A', async () => {
    const sourceA = await createBinding(profile(), target(), 'w13.2');
    const sourceB = await createBinding({ ...profile(), coursework: ['Course added after the first draft'] }, target(), 'w13.2');
    const original = createDraft('owner-a', 'opp-1', 'Text written with source A.', 'manual', sourceA);
    const forB = editDraft(original, 'Text updated and explicitly reviewed with source B.');
    const reviewed = await reviewDraft(forB, sourceB);
    expect(await compareDraft(reviewed, sourceB)).toBe('current');
    expect(await compareDraft(reviewed, sourceA)).toBe('stale');
    expect(reviewed.origin).toEqual(original.origin);
    expect(reviewed.review).toEqual({ text_sig: hash(forB.text), binding: sourceB });
    expect(await compareDraft(editDraft(original, 'An ordinary edit before any explicit review.'), sourceA)).toBe('current');
  });
  it('requires exact text after a review even when the current materials still match the origin', async () => {
    const original = draft(); const reviewed = await reviewDraft(original, binding());
    expect(await compareDraft(reviewed, binding())).toBe('current');
    const edited = editDraft(reviewed, reviewed.text + ' One more change.');
    expect(await compareDraft(edited, binding())).toBe('stale');
    expect(edited.origin).toEqual(original.origin); expect(edited.review).toEqual(reviewed.review);
  });
  it('keeps unknown legacy origin unknown after typing, and preserves that origin even after explicit review', async () => {
    const decoded = decodeDraft('legacy text', 'owner-a', 'opp-1'); if (decoded.status !== 'legacy') throw new Error('expected legacy');
    const edited = editDraft(decoded.draft, 'manual changes'); expect(edited.origin).toEqual({ kind: 'unknown', binding: null });
    expect(await compareDraft(edited, binding())).toBe('unknown');
    const reviewed = await reviewDraft(edited, binding()); expect(reviewed.origin).toEqual(edited.origin); expect(await compareDraft(reviewed, binding())).toBe('current');
    expect(await compareDraft(editDraft(reviewed, 'different manual text'), binding())).toBe('stale');
  });
  it('snapshots text and binding before review hashing so late mutation cannot certify new text', async () => {
    const original = createDraft('owner-a', 'opp-1', 'Review exactly this.', 'manual', null); const against = binding();
    let finish!: () => void;
    vi.stubGlobal('crypto', { subtle: { digest: (_algorithm: string, bytes: Uint8Array) => new Promise<ArrayBuffer>((resolve, reject) => { finish = () => { void webcrypto.subtle.digest('SHA-256', bytes).then(resolve, reject); }; }) } });
    const pending = reviewDraft(original, against); original.text = 'Late change'; against.target_sig = 'f'.repeat(64); finish();
    const reviewed = await pending; expect(reviewed.text).toBe('Review exactly this.'); expect(reviewed.review?.text_sig).toBe(hash(reviewed.text)); expect(reviewed.review?.binding.target_sig).toBe('b'.repeat(64));
  });
  it('retains complete text, empty drafts and honest optional processing through roundtrip', () => {
    const coverage: ResumeProcessingCoverage = { input_characters: 20, ai_chunks: 1, heuristic_chunks: 1,
      chunks: [{ start: 0, end: 10, method: 'ai' }, { start: 10, end: 20, method: 'heuristic', reason: 'deadline' }] };
    for (const value of ['', '   \n', '  中文 🧪\r\n'.repeat(10000) + 'FINAL TAIL']) {
      const item = createDraft('owner-a', 'opp-1', value, 'extract', binding(), coverage);
      expect(decodeDraft(encodeDraft(item), 'owner-a', 'opp-1')).toEqual({ status: 'stored', draft: item });
      expect(item.text).toBe(value); expect(editDraft(item, value + '!').processing).toEqual(coverage);
    }
  });
});

describe('per-line sources after "Use kept as new originals"', () => {
  const promoted = () => createDraft('owner-a', 'opp-1', 'Reviewed parser wording.\nMy own line.', 'reviewed_output', binding(), undefined,
    [{ line: 'Reviewed parser wording.', source: 'Wrote parser tests.' }, { line: 'My own line.', source: 'My own line.' }]);
  it('keeps each promoted line tied to its source through storage, and stores only lines that differ', () => {
    const item = promoted();
    expect(item.version).toBe(3); expect(item.sources).toEqual([{ line: 'Reviewed parser wording.', source: 'Wrote parser tests.' }]);
    expect(decodeDraft(encodeDraft(item), 'owner-a', 'opp-1')).toEqual({ status: 'stored', draft: item });
    expect(draftLineSources(item, ['My own line.', 'Reviewed parser wording.'])).toEqual(['My own line.', 'Wrote parser tests.']);
  });
  it('treats a line the student typed or edited since as their own words', () => {
    const edited = editDraft(promoted(), 'Reviewed parser wording, edited.\nMy own line.');
    expect(edited.sources).toEqual(promoted().sources);
    expect(draftLineSources(edited, ['Reviewed parser wording, edited.', 'My own line.'])).toEqual(['Reviewed parser wording, edited.', 'My own line.']);
    expect(createDraft('owner-a', 'opp-1', 'Typed.', 'manual', null)).not.toHaveProperty('sources');
  });
  it('reads a stored version 2 draft unchanged', () => {
    const { sources: _none, ...rest } = draft();
    const stored = { ...rest, version: 2 };
    expect(decodeDraft(JSON.stringify(stored), 'owner-a', 'opp-1')).toEqual({ status: 'stored', draft: stored });
    expect(draftLineSources(stored as ReturnType<typeof draft>, ['A line'])).toEqual(['A line']);
  });
});

describe('legacy and strict local envelope decoding', () => {
  it.each(['Plain old text\r\n尾行', '"quoted plain text"', '[1,2]', '{"arbitrary":"plain JSON-looking content"}', '', '  '])('preserves plain legacy text exactly: %j', value => {
    const decoded = decodeDraft(value, 'owner-a', 'opp-1');
    expect(decoded).toEqual({ status: 'legacy', draft: createDraft('owner-a', 'opp-1', value, 'unknown', null) });
  });
  it.each([{ t: '  Extracted old text 🧪  ', s: 'weak-old-hash' }, { t: 'Manual old text', s: null }, { t: '' }])('preserves old {t,s} text but never trusts a weak signature', value => {
    const decoded = decodeDraft(JSON.stringify(value), 'owner-a', 'opp-1');
    expect(decoded).toEqual({ status: 'legacy', draft: createDraft('owner-a', 'opp-1', value.t, 'unknown', null) });
  });
  it('does not return another owner or opportunity text', () => {
    const raw = encodeDraft(draft('PRIVATE BODY'));
    expect(decodeDraft(raw, 'owner-b', 'opp-1')).toEqual({ status: 'foreign' });
    expect(decodeDraft(raw, 'owner-a', 'opp-2')).toEqual({ status: 'foreign' });
  });
  it.each([
    { ...draft(), version: '2' }, { ...draft(), version: 4 }, { ...draft(), owner_id: '' }, { ...draft(), extra: true },
    { ...draft(), sources: [] }, { ...draft(), sources: [{ line: 'Same', source: 'Same' }] }, { ...draft(), sources: [{ line: 'Only a line' }] },
    { ...draft(), sources: [{ line: 'Reviewed', source: ['coerced'] }] }, { ...draft(), version: 2, sources: [{ line: 'Reviewed', source: 'Own' }] },
    { ...draft(), text: ['coerced'] }, { ...draft(), origin: { kind: ['extract'], binding: binding() } },
    { ...draft(), origin: { kind: 'unknown', binding: binding() } },
    { ...draft(), origin: { kind: 'extract', binding: { ...binding(), profile_sig: ['a'.repeat(64)] } } },
    { ...draft(), origin: { kind: 'extract', binding: { ...binding(), profile_sig: 'v1:sha256:' + 'a'.repeat(64) } } },
    { ...draft(), origin: { kind: 'extract', binding: { ...binding(), pipeline_version: ['w13.2'] } } },
    { ...draft(), origin: { kind: 'extract', binding: { ...binding(), extra: true } } },
    { ...draft(), review: { text_sig: ['a'.repeat(64)], binding: binding() } },
    { ...draft(), review: { text_sig: 'a'.repeat(64), binding: binding(), extra: true } },
    { ...draft(), processing: { input_characters: 1, ai_chunks: 1, heuristic_chunks: 0, chunks: [{ start: 0, end: 2, method: 'ai' }] } },
    { ...draft(), processing: { input_characters: 1, ai_chunks: 0, heuristic_chunks: 1, chunks: [{ start: 0, end: 1, method: 'ai' }] } },
    { t: 123, s: null }, { t: 'text', s: {} },
  ])('rejects malformed marked envelopes without downgrading them to visible legacy text', value => {
    expect(decodeDraft(JSON.stringify(value), 'owner-a', 'opp-1')).toEqual({ status: 'invalid' });
  });
  it('does not touch browser persistence when parsing, reviewing or encoding', async () => {
    const read = vi.spyOn(window.localStorage, 'getItem'); const write = vi.spyOn(window.localStorage, 'setItem'); const clear = vi.spyOn(window.localStorage, 'removeItem');
    const item = await reviewDraft(draft(), binding()); decodeDraft(encodeDraft(item), 'owner-a', 'opp-1');
    expect(read).not.toHaveBeenCalled(); expect(write).not.toHaveBeenCalled(); expect(clear).not.toHaveBeenCalled();
  });
});

describe('shared public target shape', () => {
  it('accepts actual anonymous detail without internal is_active but does not confuse a list card with full detail', () => {
    const { is_active: _active, ...metadata } = target().metadata;
    expect(isPublicDetail({ ...target(), metadata }, 'opp-1')).toBe(true);
    const { metadata: _metadata, ...card } = target(); expect(isPublicDetail(card, 'opp-1')).toBe(false);
    expect(isPublicDetail(target(), 'other')).toBe(false);
  });
  it('accepts neutralized unknown records without fabricating offer fields', () => {
    expect(isPublicDetail({ id: 'unknown-1', title: 'Source', organization: 'Lab', keywords: [], metadata: {}, record_kind: 'unknown', source_type: 'unreviewed', eligibility: {}, application: {} }, 'unknown-1')).toBe(true);
  });
});
