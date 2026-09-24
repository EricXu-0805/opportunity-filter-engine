import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import type { ExperienceEntry, Opportunity, ProfileData, ResumeFact, ResumeMasterV1 } from './types';
import { createEmptyResumeMaster } from './resume-master';
import { sourceDigest } from './experience-evidence';
import {
  MAX_TARGET_RESUME_BYTES, createTargetResume, suggestTargetResumeOrder,
  targetResumeContextFromOpportunity, targetResumeContextSignature, targetResumeProfileSignature,
  validateTargetResume, verifyTargetResumeSignatures,
  type TargetResumeContext, type TargetResumeV1,
} from './target-resume';

beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const fact = (id: string, value = id, overrides: Partial<ResumeFact> = {}): ResumeFact => ({
  id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' }, ...overrides,
});
const entry = (id: string, overrides: Partial<ExperienceEntry> = {}): ExperienceEntry => ({
  id, revision: 1, status: 'confirmed', text: 'Built the project.', source: { kind: 'manual' }, ...overrides,
});
const target = (): TargetResumeContext => ({ opportunity_id: 'opp-one', title: 'Robotics research', organization: 'Example University',
  source_url: 'https://example.test/lab', description: 'Embedded systems project.', requirements: ['Python', 'C++'] });
function master(): ResumeMasterV1 {
  const value = createEmptyResumeMaster('master');
  value.basics = { name: fact('name', '徐国一'), email: fact('email', 'student@example.test'), phone: fact('phone', '+1 (217) 000 0000'),
    location: fact('location', 'Urbana'), links: [{ id: 'scholar', label: 'Google Scholar', url: fact('link-url', 'https://example.test/me') }] };
  value.education = [{ id: 'education-one', school: fact('school', 'UIUC'), degree: fact('degree', 'B.S.'), field: fact('field', 'Computer Engineering'),
    start: fact('ed-start', 'Fall 2024'), end: fact('ed-end', 'Expected 2028'), details: [] }];
  value.activities = [{ id: 'activity-one', kind: 'project', title: fact('title', 'Humanities project'), organization: fact('org', 'Local group'),
    start: fact('act-start', '2025'), end: fact('act-end', 'Present'), location: fact('act-location', 'Illinois'),
    url: fact('act-url', 'https://example.test/project'), details: [{ id: 'exp', revision: 1 }] }];
  value.publications = [{ id: 'publication-one', title: fact('pub-title', 'Actual paper'), authors: fact('authors', 'Lee, A.; Xu, G.; 张三'),
    venue: fact('venue', 'Workshop'), date: fact('pub-date', 'September 2026'), publication_status: fact('pub-status', 'Submitted'),
    doi: fact('doi', '10.example/real'), url: fact('pub-url', 'https://example.test/paper'), details: [] }];
  value.skills = [fact('skill', 'Python — beginner')];
  value.other_sections = [{ id: 'awards', heading: 'Awards', items: [fact('award', 'College scholarship')] }];
  value.section_order.push('awards');
  return value;
}
const profile = (resumeMaster: ResumeMasterV1 | null = master()): ProfileData => ({
  institution: 'UIUC', college: 'Engineering', major: 'Computer Engineering', grade: 'junior', is_international: false,
  research_interests: 'Embedded systems', skills: [{ name: 'Python', level: 'beginner' }],
  resume_text: '', experience_entries: [entry('exp')], resume_master: resumeMaster,
});
const allLines = (doc: TargetResumeV1) => doc.document.sections.flatMap((section) => section.blocks.flatMap((block) => block.lines));
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).byteLength;
const doc = () => createTargetResume(profile(), target(), 'draft-one');

 describe('full target document creation and provenance', () => {
  it('creates whole confirmed fields with exact role/labels, dates, contacts and authors', async () => {
    const source = profile();
    const result = await createTargetResume(source, target(), 'draft-one');
    expect(result.base_snapshot).toEqual({ resume_text: '', experience_entries: source.experience_entries, resume_master: source.resume_master });
    expect(result.base).toMatchObject({ master_id: 'master', master_revision: 1, source_signature: await sourceDigest('') });
    expect(allLines(result).map((row) => [row.role, row.original])).toEqual([
      ['name', '徐国一'], ['email', 'student@example.test'], ['phone', '+1 (217) 000 0000'], ['location', 'Urbana'],
      ['url', 'https://example.test/me'], ['school', 'UIUC'], ['degree', 'B.S.'], ['field', 'Computer Engineering'],
      ['start', 'Fall 2024'], ['end', 'Expected 2028'], ['title', 'Humanities project'], ['organization', 'Local group'],
      ['location', 'Illinois'], ['start', '2025'], ['end', 'Present'], ['url', 'https://example.test/project'],
      ['experience', 'Built the project.'], ['title', 'Actual paper'], ['authors', 'Lee, A.; Xu, G.; 张三'],
      ['venue', 'Workshop'], ['date', 'September 2026'], ['publication_status', 'Submitted'],
      ['url', 'https://example.test/paper'], ['doi', '10.example/real'], ['skill', 'Python — beginner'], ['other', 'College scholarship'],
    ]);
    expect(allLines(result).find((row) => row.evidence.id === 'link-url')?.label).toBe('Google Scholar');
    expect(result.document.sections.at(-1)).toMatchObject({ id: 'awards', heading: 'Awards' });
    expect(await verifyTargetResumeSignatures(result)).toBe(true);
  });
  it.each([601, 6_001, 60_000])('preserves a complete %i-codepoint fact without passing through the bullet cap', async (length) => {
    const m = createEmptyResumeMaster('master');
    const original = '😀'.repeat(length - 1) + '尾';
    m.basics.name = fact('whole', original);
    const result = await createTargetResume(profile(m), target());
    expect(allLines(result)[0]).toMatchObject({ original, text: original });
    expect(result.base_snapshot.resume_master.basics.name?.value).toBe(original);
    expect(validateTargetResume(result).ok).toBe(true);
  });
  it('retains full 60000-character raw/quote/fact and full 6000-character referenced experience', async () => {
    const raw = '😀'.repeat(59_999) + '尾';
    const signature = await sourceDigest(raw);
    const m = createEmptyResumeMaster('master');
    m.basics.name = fact('whole', raw, { source: { kind: 'resume', signature, quote: raw, start: 0, end: 60_000 } });
    m.activities = [{ id: 'act', kind: 'project', details: [{ id: 'long-experience', revision: 2 }] }];
    const p = profile(m);
    p.resume_text = raw;
    p.experience_entries = [entry('long-experience', { revision: 2, text: 'x'.repeat(5_999) + '尾' })];
    const result = await createTargetResume(p, target());
    expect(result.base_snapshot.resume_text).toBe(raw);
    expect(allLines(result).map((line) => line.original)).toEqual([raw, p.experience_entries[0].text]);
    expect(await verifyTargetResumeSignatures(result)).toBe(true);
  });
  it('keeps all snapshot states exact but excludes candidate/rejected/withdrawn/stale and changed experience revisions', async () => {
    const p = profile();
    const raw = 'Actual source';
    const signature = await sourceDigest(raw);
    p.resume_text = raw;
    p.resume_master!.skills = [
      fact('valid', 'Exact skill', { source: { kind: 'resume', signature, quote: raw, start: 0, end: raw.length } }),
      ...(['candidate', 'rejected', 'withdrawn'] as const).map((status) => fact(status, `${status} skill`, { status })),
      fact('stale', 'Old skill', { source: { kind: 'resume', signature: 'f'.repeat(64), quote: raw, start: 0, end: raw.length } }),
    ];
    p.experience_entries = [entry('exp', { revision: 2 }), entry('candidate', { status: 'candidate' }), entry('unused')];
    p.resume_master!.activities[0].details.push({ id: 'candidate', revision: 1 }, { id: 'missing', revision: 1 });
    const before = clone(p);
    const result = await createTargetResume(p, target());
    expect(result.base_snapshot.experience_entries).toEqual(before.experience_entries);
    expect(result.base_snapshot.resume_master).toEqual(before.resume_master);
    const ids = allLines(result).map((line) => line.evidence.id);
    expect(ids).toContain('valid');
    for (const absent of ['exp', 'candidate', 'rejected', 'withdrawn', 'stale', 'unused']) expect(ids).not.toContain(absent);
    expect(p).toEqual(before);
  });
  it('requires an existing master with at least one current confirmed fact or experience', async () => {
    await expect(createTargetResume(profile(null), target())).rejects.toMatchObject({ code: 'master_required' });
    const missing = profile(); delete missing.resume_master;
    await expect(createTargetResume(missing, target())).rejects.toMatchObject({ code: 'master_required' });
    const m = createEmptyResumeMaster('master');
    m.basics.name = fact('candidate', 'Only candidate', { status: 'candidate' });
    await expect(createTargetResume(profile(m), target())).rejects.toMatchObject({ code: 'confirmed_content_required' });
    const invalid = profile({ broken: true } as unknown as ResumeMasterV1);
    await expect(createTargetResume(invalid, target())).rejects.toMatchObject({ code: 'invalid_master' });
  });
  it('does not store unrelated profile data, private opportunity fields or inferred requirements', async () => {
    const p = { ...profile(), research_interests: 'UNRELATED_PRIVATE_INTEREST', github_url: 'https://example.test/private-account', gpa: 'PRIVATE_GPA' };
    const opportunity = { id: 'o', title: 'Public title', organization: 'Public organization', source_url: 'https://example.test/source',
      description_clean: 'Public description', description_raw: 'PRIVATE_RAW_SCRAPE', contact_email: 'PRIVATE_CONTACT', professor_id: 'PRIVATE_TRACKING',
      eligibility: { skills_required: ['Exact skill'] }, metadata: { skills_attribution: 'inferred' } } as unknown as Opportunity;
    const currentTarget = targetResumeContextFromOpportunity(opportunity);
    expect(currentTarget).toEqual({ opportunity_id: 'o', title: 'Public title', organization: 'Public organization',
      source_url: 'https://example.test/source', description: 'Public description', requirements: [] });
    const result = await createTargetResume(p, currentTarget);
    for (const hidden of ['UNRELATED_PRIVATE_INTEREST', 'private-account', 'PRIVATE_GPA', 'PRIVATE_RAW_SCRAPE', 'PRIVATE_CONTACT', 'PRIVATE_TRACKING']) {
      expect(JSON.stringify(result)).not.toContain(hidden);
    }
    opportunity.metadata.skills_attribution = null;
    expect(targetResumeContextFromOpportunity(opportunity).requirements).toEqual(['Exact skill']);
    opportunity.skills_attribution = 'inferred';
    expect(targetResumeContextFromOpportunity(opportunity).requirements).toEqual([]);
  });
});

describe('strict source cross-checking and independent draft edits', () => {
  it('allows arbitrary manual edits, empty text, inclusion changes and order while leaving originals intact', async () => {
    const original = await doc();
    const edited = clone(original);
    edited.document.sections.reverse();
    for (const section of edited.document.sections) section.blocks.reverse();
    const row = allLines(edited)[0];
    row.text = 'User rewrite — not a new confirmed fact'; row.included = false;
    allLines(edited)[1].text = '';
    edited.document.sections[0].included = false;
    edited.document.sections[1].blocks[0].included = false;
    expect(validateTargetResume(edited).ok).toBe(true);
    expect(await verifyTargetResumeSignatures(edited)).toBe(true);
    expect(edited.base_snapshot).toEqual(original.base_snapshot);
    expect(allLines(original).every((line) => line.text === line.original)).toBe(true);
  });
  it.each([
    ['original', (v: TargetResumeV1) => { allLines(v)[0].original = 'Invented name'; }],
    ['fact revision', (v: TargetResumeV1) => { allLines(v)[0].evidence.revision += 1; }],
    ['fact id', (v: TargetResumeV1) => { allLines(v)[0].evidence.id = 'other-fact'; }],
    ['fact kind', (v: TargetResumeV1) => { allLines(v)[0].evidence.kind = 'experience'; }],
    ['role', (v: TargetResumeV1) => { allLines(v)[0].role = 'degree'; }],
    ['label', (v: TargetResumeV1) => { allLines(v)[0].label = 'Invented label'; }],
    ['line id', (v: TargetResumeV1) => { allLines(v)[0].id = 'different-line'; }],
    ['master revision', (v: TargetResumeV1) => { v.base.master_revision += 1; }],
    ['target id', (v: TargetResumeV1) => { v.opportunity_id = 'other-target'; }],
    ['section kind', (v: TargetResumeV1) => { v.document.sections[0].kind = 'education'; }],
    ['custom heading', (v: TargetResumeV1) => { v.document.sections.at(-1)!.heading = 'Fake award'; }],
  ] as const)('rejects modified source claims: %s', async (_name, mutate) => {
    const value = clone(await doc()); mutate(value);
    expect(validateTargetResume(value).ok).toBe(false);
    expect(await verifyTargetResumeSignatures(value)).toBe(false);
  });
  it('rejects a no-longer-confirmed or revised fact/experience behind unchanged originals', async () => {
    const original = await doc();
    for (const mutate of [
      (v: TargetResumeV1) => { v.base_snapshot.resume_master.basics.name!.status = 'candidate'; },
      (v: TargetResumeV1) => { v.base_snapshot.resume_master.basics.name!.revision += 1; },
      (v: TargetResumeV1) => { v.base_snapshot.experience_entries[0].revision += 1; },
      (v: TargetResumeV1) => { v.base_snapshot.experience_entries[0].status = 'withdrawn'; },
      (v: TargetResumeV1) => { v.base_snapshot.experience_entries[0].text = 'Invented experience'; },
    ]) {
      const value = clone(original); mutate(value); expect(validateTargetResume(value).ok).toBe(false);
    }
  });
  it('rejects duplicate, missing or invented sections/blocks/lines instead of silently dropping evidence', async () => {
    for (const mutate of [
      (v: TargetResumeV1) => { v.document.sections.push(clone(v.document.sections[0])); },
      (v: TargetResumeV1) => { v.document.sections.pop(); },
      (v: TargetResumeV1) => { v.document.sections[0].blocks.push(clone(v.document.sections[0].blocks[0])); },
      (v: TargetResumeV1) => { v.document.sections[0].blocks[0].lines[1] = clone(v.document.sections[0].blocks[0].lines[0]); },
      (v: TargetResumeV1) => { v.document.sections[0].blocks[0].lines.pop(); },
    ]) {
      const value = clone(await doc()); mutate(value); expect(validateTargetResume(value).ok).toBe(false);
    }
  });
  it('rejects moving legitimate evidence into the wrong project or section', async () => {
    const value = clone(await doc());
    const name = value.document.sections[0].blocks[0].lines[0];
    const school = value.document.sections[1].blocks[0].lines[0];
    value.document.sections[0].blocks[0].lines[0] = school;
    value.document.sections[1].blocks[0].lines[0] = name;
    expect(validateTargetResume(value)).toMatchObject({ ok: false, code: 'invalid_evidence' });
  });
  it('rejects unknown keys at every contract boundary without leaking their values', async () => {
    const original = await doc();
    for (const item of [
      (v: TargetResumeV1) => v, (v: TargetResumeV1) => v.base, (v: TargetResumeV1) => v.base_snapshot,
      (v: TargetResumeV1) => v.target_snapshot, (v: TargetResumeV1) => v.document,
      (v: TargetResumeV1) => v.document.sections[0], (v: TargetResumeV1) => v.document.sections[0].blocks[0],
      (v: TargetResumeV1) => allLines(v)[0], (v: TargetResumeV1) => allLines(v)[0].evidence,
    ]) {
      const value = clone(original); Object.assign(item(value), { unexpected: 'PRIVATE REJECTED INPUT' });
      const result = validateTargetResume(value);
      expect(result.ok).toBe(false); expect(JSON.stringify(result)).not.toContain('PRIVATE REJECTED INPUT');
    }
  });
  it('returns safe failure for non-JSON, cyclic, malformed Unicode and invalid signature inputs', async () => {
    const original = await doc();
    const circular: Record<string, unknown> = {}; circular.self = circular;
    for (const invalid of [null, undefined, [], {}, new Date(), circular, { ...original, version: 2 },
      { ...original, id: '\ud800' }, { ...original, id: 'x'.repeat(81) }, { ...original, id: Number.NaN },
      { ...original, base: { ...original.base, source_signature: 'A'.repeat(64) } },
      { ...original, base: { ...original.base, target_signature: 'not-a-digest' } }]) {
      expect(validateTargetResume(invalid).ok).toBe(false);
    }
    const value = clone(original); allLines(value)[0].text = 'private\udfff';
    expect(validateTargetResume(value)).toEqual({ ok: false, code: 'invalid_unicode' });
  });
  it('rejects NUL that PostgreSQL jsonb cannot store without removing or changing original input', async () => {
    const p = profile();
    p.resume_master!.basics.name!.value = 'Before\u0000After';
    const before = JSON.stringify(p);
    await expect(createTargetResume(p, target())).rejects.toMatchObject({ code: 'invalid_unicode' });
    expect(JSON.stringify(p)).toBe(before);
    const value = clone(await doc());
    allLines(value)[0].text = 'Edited\u0000text';
    expect(validateTargetResume(value)).toEqual({ ok: false, code: 'invalid_unicode' });
    expect(allLines(value)[0].text).toBe('Edited\u0000text');
    allLines(value)[0].text = 'Other\u0001control';
    expect(validateTargetResume(value).ok).toBe(true);
  });
  it('deep clones and freezes provenance without freezing editable text or mutating input', async () => {
    const p = profile(); const t = target(); const value = await createTargetResume(p, t);
    p.resume_master!.basics.name!.value = 'Changed after creation'; p.experience_entries![0].text = 'Changed'; t.requirements.push('New requirement');
    expect(value.base_snapshot.resume_master.basics.name?.value).toBe('徐国一');
    expect(value.target_snapshot.requirements).toEqual(['Python', 'C++']);
    expect(() => { value.base_snapshot.resume_master.basics.name!.value = 'Not allowed'; }).toThrow();
    const plain = clone(value);
    const checked = validateTargetResume(plain);
    if (!checked.ok) throw new Error('expected valid');
    plain.base_snapshot.resume_master.basics.name!.value = 'Plain input changed';
    expect(checked.value.base_snapshot.resume_master.basics.name!.value).toBe('徐国一');
    allLines(checked.value)[0].text = 'New draft';
    expect(allLines(value)[0].text).toBe('徐国一');
    expect(Object.isFrozen(plain.base_snapshot)).toBe(false);
  });
});

describe('canonical SHA256 fingerprints and asynchronous verification', () => {
  it('uses the native SHA256 result for canonical target JSON, including exact Unicode and order', async () => {
    const t = target();
    const canonical = JSON.stringify({ description: t.description, opportunity_id: t.opportunity_id, organization: t.organization,
      requirements: t.requirements, source_url: t.source_url, title: t.title });
    expect(await targetResumeContextSignature(t)).toBe(`v1:sha256:${createHash('sha256').update(canonical).digest('hex')}`);
    const reordered = Object.fromEntries(Object.entries(t).reverse()) as unknown as TargetResumeContext;
    expect(await targetResumeContextSignature(reordered)).toBe(await targetResumeContextSignature(t));
    expect(await targetResumeContextSignature({ ...t, requirements: [...t.requirements].reverse() })).not.toBe(await targetResumeContextSignature(t));
  });
  it('ignores nested object key order but fingerprints all defined profile content and exact array/whitespace order', async () => {
    const p = profile();
    const reverseKeys = (value: unknown): unknown => Array.isArray(value) ? value.map(reverseKeys)
      : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).reverse().map(([key, item]) => [key, reverseKeys(item)])) : value;
    const signature = await targetResumeProfileSignature(p);
    expect(await targetResumeProfileSignature(reverseKeys(p) as ProfileData)).toBe(signature);
    expect(await targetResumeProfileSignature({ ...p, name: undefined })).toBe(signature);
    expect(await targetResumeProfileSignature({ ...p, research_interests: p.research_interests + ' ' })).not.toBe(signature);
    const reordered = clone(p); reordered.resume_master!.section_order.reverse();
    expect(await targetResumeProfileSignature(reordered)).not.toBe(signature);
    const changed = clone(p); changed.resume_master!.basics.name!.revision += 1;
    expect(await targetResumeProfileSignature(changed)).not.toBe(signature);
    expect(await targetResumeContextSignature({ ...target(), title: 'e\u0301' })).not.toBe(await targetResumeContextSignature({ ...target(), title: 'é' }));
  });
  it('detects source/target digest mismatch separately from safe synchronous structural validation', async () => {
    const original = await doc();
    const source = clone(original); source.base.source_signature = 'a'.repeat(64);
    expect(validateTargetResume(source).ok).toBe(true); // Manual facts need no raw source.
    expect(await verifyTargetResumeSignatures(source)).toBe(false);
    const changed = clone(original); changed.target_snapshot.title = 'Different actual target content';
    expect(validateTargetResume(changed).ok).toBe(true);
    expect(await verifyTargetResumeSignatures(changed)).toBe(false);
  });
  it('captures creation and verification inputs before hashing awaits', async () => {
    const native = webcrypto.subtle.digest.bind(webcrypto.subtle);
    const release: Array<() => void> = [];
    vi.spyOn(webcrypto.subtle, 'digest').mockImplementation((algorithm, data) => new Promise((resolve, reject) => {
      release.push(() => { void native(algorithm, data).then(resolve, reject); });
    }));
    const p = profile(); const t = target();
    const promise = createTargetResume(p, t);
    p.resume_master!.basics.name!.value = 'Changed during await'; t.title = 'Changed during await';
    release.splice(0).forEach((done) => done());
    const created = await promise;
    expect(created.base_snapshot.resume_master.basics.name!.value).toBe('徐国一');
    expect(created.target_snapshot.title).toBe('Robotics research');
    const mutable = clone(created);
    const verification = verifyTargetResumeSignatures(mutable);
    mutable.target_snapshot.title = 'Changed after verify started';
    release.splice(0).forEach((done) => done());
    expect(await verification).toBe(true);
  });
  it('fails closed when crypto is unavailable instead of substituting weak hashes', async () => {
    const original = await doc();
    vi.stubGlobal('crypto', {});
    await expect(targetResumeProfileSignature(profile())).rejects.toMatchObject({ code: 'signature_unavailable' });
    await expect(createTargetResume(profile(), target(), 'id')).rejects.toMatchObject({ code: 'signature_unavailable' });
    expect(await verifyTargetResumeSignatures(original)).toBe(false);
  });
});

describe('byte limits and whole-block literal ordering', () => {
  it('accepts exactly 2MiB of compact UTF8 JSON and rejects the next byte without clipping', async () => {
    const m = createEmptyResumeMaster('master'); m.basics.name = fact('name', 'A');
    const value = clone(await createTargetResume(profile(m), target(), 'id'));
    const row = allLines(value)[0];
    row.text = 'x'.repeat(MAX_TARGET_RESUME_BYTES - bytes(value) + 1);
    expect(bytes(value)).toBe(MAX_TARGET_RESUME_BYTES);
    expect(validateTargetResume(value).ok).toBe(true);
    row.text += '尾';
    const original = row.text;
    expect(validateTargetResume(value)).toEqual({ ok: false, code: 'document_too_large' });
    expect(row.text).toBe(original);
  });
  it('counts UTF8 bytes and JSON escaping rather than codepoints or UTF16 length', async () => {
    const value = clone(await doc());
    allLines(value)[0].text = '😀'.repeat(530_000);
    expect(validateTargetResume(value)).toEqual({ ok: false, code: 'document_too_large' });
    allLines(value)[0].text = '\u0001'.repeat(350_000);
    expect(validateTargetResume(value)).toEqual({ ok: false, code: 'document_too_large' });
  });
  it('rejects an over-budget whole document instead of dropping repeated references during creation', async () => {
    const m = createEmptyResumeMaster('master');
    m.activities = Array.from({ length: 180 }, (_, index) => ({ id: `activity-${index}`, kind: 'project', details: [{ id: 'exp', revision: 1 }] }));
    const p = profile(m); p.experience_entries = [entry('exp', { text: 'x'.repeat(6_000) })];
    await expect(createTargetResume(p, target())).rejects.toMatchObject({ code: 'document_too_large' });
    expect(p.resume_master!.activities).toHaveLength(180);
    expect(p.experience_entries[0].text).toHaveLength(6_000);
  });
  it('suggests an order for whole blocks using literal target terms, preserving all fields, flags and snapshots', async () => {
    const p = profile();
    p.resume_master!.activities.push({ id: 'relevant', kind: 'research', title: fact('robotics', 'Robotics research using Python.'),
      start: fact('robot-date', '2025'), details: [] });
    const original = await createTargetResume(p, target());
    const before = JSON.stringify(original);
    const result = suggestTargetResumeOrder(original);
    const activities = result.document.sections.find((section) => section.kind === 'activities')!;
    expect(activities.blocks.map((block) => block.id)).toEqual(['relevant', 'activity-one']);
    expect(activities.blocks[0].lines.map((line) => line.original)).toEqual(['Robotics research using Python.', '2025']);
    expect(result.base_snapshot).toEqual(original.base_snapshot);
    expect(result.target_snapshot).toEqual(original.target_snapshot);
    expect(JSON.stringify(original)).toBe(before);
    expect(validateTargetResume(result).ok).toBe(true);
    expect(await verifyTargetResumeSignatures(result)).toBe(true);
  });
  it('uses whole long-block tails and keeps ties stable without re-enabling excluded content', async () => {
    const m = createEmptyResumeMaster('master');
    m.activities = [
      { id: 'first', kind: 'other', title: fact('first-title', 'Nothing relevant'), details: [] },
      { id: 'second', kind: 'other', title: fact('second-title', Array.from({ length: 5_000 }, (_, index) => `word${index}`).join(' ') + ' Robotics'), details: [] },
      { id: 'third', kind: 'other', title: fact('third-title', 'Nothing relevant'), details: [] },
    ];
    const original = await createTargetResume(profile(m), { ...target(), title: 'Robotics', organization: '', description: '', requirements: [] });
    const result = suggestTargetResumeOrder(original);
    expect(result.document.sections[0].blocks.map((block) => block.id)).toEqual(['second', 'first', 'third']);
    const edited = clone(original); edited.document.sections[0].blocks[1].included = false;
    const next = suggestTargetResumeOrder(edited);
    expect(next.document.sections[0].blocks.map((block) => block.id)).toEqual(['first', 'second', 'third']);
    expect(next.document.sections[0].blocks[1].included).toBe(false);
  });
});
