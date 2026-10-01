import { resumeMasterEditBase } from './resume-master';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { ExperienceEntry, ResumeFact, ResumeMasterV1 } from './types';
import { sourceDigest } from './experience-evidence';
import {
  buildResumeMasterPreview, createEmptyResumeMaster, isActiveResumeFact, proposeResumeMaster,
  removeResumeMasterSources, resumeMasterFacts, validateResumeMaster, withdrawResumeMaster,
} from './resume-master';

beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const fact = (id: string, value = id, extra: Partial<ResumeFact> = {}): ResumeFact => ({
  id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' }, ...extra,
});
const experience = (id: string, extra: Partial<ExperienceEntry> = {}): ExperienceEntry => ({
  id, revision: 1, status: 'confirmed', text: 'Built an actual robot.', source: { kind: 'manual' }, ...extra,
});
const empty = () => createEmptyResumeMaster('master');
const context = { rawText: '', expectedDigest: '' };
const lines = (value: ReturnType<typeof buildResumeMasterPreview>) => value.sections.flatMap((section) => section.blocks.flatMap((block) => block.lines));
function complete(): ResumeMasterV1 {
  const value = empty();
  value.basics = {
    name: fact('name', '徐国一'), email: fact('email', 'eric@example.test'), phone: fact('phone', '+1 (217) 000-0000'),
    location: fact('location', 'Urbana, IL'), links: [{ id: 'link', label: 'Scholar', url: fact('link-url', 'https://example.test/scholar') }],
  };
  value.education = [{ id: 'education-1', school: fact('school', 'UIUC'), degree: fact('degree', 'B.S.'),
    field: fact('field', 'Computer Engineering'), start: fact('start', 'Fall 2024'), end: fact('end', 'Expected May 2028'), details: [] }];
  value.activities = [{ id: 'activity-1', kind: 'research', title: fact('title', 'Student researcher'),
    organization: fact('org', 'Lab A'), location: fact('act-location', 'Urbana'), start: fact('act-start', '2025'),
    end: fact('act-end', 'Present'), url: fact('act-url', 'https://example.test/project'), details: [{ id: 'exp', revision: 1 }] }];
  value.publications = [{ id: 'publication-1', title: fact('pub-title', 'Actual paper'), authors: fact('authors', 'Lee, A.; Xu, G.; 张三'),
    venue: fact('venue', 'Workshop'), date: fact('date', 'September 2026'), publication_status: fact('pub-status', 'Submitted'),
    url: fact('pub-url', 'https://example.test/paper'), doi: fact('doi', '10.example/real'), details: [] }];
  value.skills = [fact('skill', 'Python — beginner')];
  value.other_sections = [{ id: 'awards', heading: 'Awards', items: [fact('award', 'College scholarship')] }];
  value.section_order.push('awards');
  return value;
}

describe('complete resume storage contract', () => {
  it('normalizes only absent legacy values to null, without inventing a master', () => {
    expect(validateResumeMaster(undefined)).toEqual({ ok: true, value: null });
    expect(validateResumeMaster(null)).toEqual({ ok: true, value: null });
    for (const invalid of [{}, [], '', 1, false, { version: 2 }]) expect(validateResumeMaster(invalid).ok).toBe(false);
    expect(removeResumeMasterSources(undefined)).toBeNull();
    expect(withdrawResumeMaster(null)).toBeNull();
  });
  it('creates independent empty documents and rejects an invalid explicit id', () => {
    const first = createEmptyResumeMaster();
    const second = createEmptyResumeMaster();
    expect(first.id).not.toBe(second.id);
    first.skills.push(fact('own'));
    expect(second.skills).toEqual([]);
    expect(() => createEmptyResumeMaster('')).toThrow('invalid_master');
  });
  it('round trips every category, exact contact/date/authors/status and full text', () => {
    const value = complete();
    const restored = JSON.parse(JSON.stringify(value));
    expect(validateResumeMaster(restored)).toEqual({ ok: true, value });
    const rendered = lines(buildResumeMasterPreview(restored, [experience('exp')], context));
    expect(rendered).toEqual([
      '徐国一', 'eric@example.test', '+1 (217) 000-0000', 'Urbana, IL', 'https://example.test/scholar',
      'UIUC', 'B.S.', 'Computer Engineering', 'Fall 2024', 'Expected May 2028',
      'Student researcher', 'Lab A', 'Urbana', '2025', 'Present', 'https://example.test/project', 'Built an actual robot.',
      'Actual paper', 'Lee, A.; Xu, G.; 张三', 'Workshop', 'September 2026', 'Submitted',
      'https://example.test/paper', '10.example/real', 'Python — beginner', 'College scholarship',
    ]);
  });
  it.each([600, 601, 6_000, 6_001, 60_000])('preserves a complete %i codepoint field in storage and preview', (length) => {
    const value = empty();
    const full = '😀'.repeat(length - 1) + '尾';
    value.other_sections = [{ id: 'summary', heading: 'Summary', items: [fact('long', full)] }];
    value.section_order.push('summary');
    expect(validateResumeMaster(value).ok).toBe(true);
    expect(lines(buildResumeMasterPreview(value, [], context))).toEqual([full]);
  });
  it('refuses one oversized field or total values without clipping or changing the saved object', () => {
    const value = empty();
    value.skills = [fact('first', 'x'.repeat(60_000)), fact('second', '尾')];
    const before = JSON.stringify(value);
    expect(validateResumeMaster(value)).toEqual({ ok: false, code: 'value_limit' });
    expect(JSON.stringify(value)).toBe(before);
    value.skills = [fact('first', '😀'.repeat(60_001))];
    expect(validateResumeMaster(value)).toEqual({ ok: false, code: 'value_limit' });
  });
  it('allows 300 facts but rejects 301 distributed across categories', () => {
    const value = empty();
    value.skills = Array.from({ length: 300 }, (_, index) => fact(`f-${index}`));
    expect(validateResumeMaster(value).ok).toBe(true);
    value.basics.name = fact('extra');
    expect(validateResumeMaster(value)).toEqual({ ok: false, code: 'too_many_facts' });
  });
  it('rejects unbounded empty containers and reference-only payloads', () => {
    const value = empty();
    value.education = Array.from({ length: 300 }, (_, i) => ({ id: `e-${i}`, details: [] }));
    expect(validateResumeMaster(value).ok).toBe(true);
    value.publications = [{ id: 'extra', details: [] }];
    expect(validateResumeMaster(value)).toEqual({ ok: false, code: 'too_many_records' });
    value.education = [{ id: 'e', details: Array.from({ length: 300 }, (_, i) => ({ id: `r-${i}`, revision: 1 })) }];
    value.publications = [{ id: 'p', details: [{ id: 'extra', revision: 1 }] }];
    expect(validateResumeMaster(value)).toEqual({ ok: false, code: 'too_many_records' });
  });
  it.each(['id', 'revision', 'status', 'value', 'source'])('requires fact field %s rather than filling missing data', (key) => {
    const value = empty();
    const invalid = { ...fact('f') } as Record<string, unknown>;
    delete invalid[key];
    value.skills = [invalid as unknown as ResumeFact];
    expect(validateResumeMaster(value).ok).toBe(false);
  });
  it.each([
    { revision: 0 }, { revision: 1.1 }, { revision: Number.MAX_SAFE_INTEGER + 1 },
    { status: 'approved' }, { value: '  ' }, { value: { text: 'not a string' } }, { id: 'x'.repeat(81) },
    { secret: 'do not include this in errors' },
  ])('rejects malformed facts without exposing input %j', (invalid) => {
    const value = empty();
    value.skills = [{ ...fact('f'), ...invalid } as ResumeFact];
    const checked = validateResumeMaster(value);
    expect(checked.ok).toBe(false);
    expect(JSON.stringify(checked)).not.toContain('do not include');
    expect(() => withdrawResumeMaster(value)).toThrow();
  });
  it.each(['master', 'fact', 'entity'])('rejects duplicated %s ids across the whole structure', (kind) => {
    const value = empty();
    value.basics.name = fact(kind === 'master' ? 'master' : 'collision');
    if (kind === 'fact') value.skills = [fact('collision')];
    if (kind === 'entity') value.education = [{ id: 'collision', details: [] }];
    expect(validateResumeMaster(value)).toEqual({ ok: false, code: 'duplicate_id' });
  });
  it.each(['id', 'value', 'heading', 'quote'])('rejects lone surrogates in %s, retaining valid Unicode exact', (field) => {
    const value = empty();
    value.skills = [fact('f')];
    if (field === 'id') value.skills[0].id = '\ud800';
    if (field === 'value') value.skills[0].value = 'bad\udfff';
    if (field === 'heading') { value.other_sections = [{ id: 'o', heading: '\ud800', items: [] }]; value.section_order.push('o'); }
    if (field === 'quote') value.skills[0].source = { kind: 'resume', signature: 'a'.repeat(64), quote: '\ud800', start: 0, end: 1 };
    expect(validateResumeMaster(value)).toEqual({ ok: false, code: 'invalid_unicode' });
    expect(validateResumeMaster({ ...empty(), skills: [fact('f', 'e\u0301\ufffd😀')] }).ok).toBe(true);
  });
  it('rejects unknown fields at nested levels instead of silently losing them', () => {
    for (const mutate of [
      (v: ResumeMasterV1) => Object.assign(v, { secret: 'unexpected' }),
      (v: ResumeMasterV1) => Object.assign(v.basics, { old_contact: 'unexpected' }),
      (v: ResumeMasterV1) => Object.assign(v.education[0], { qualification: 'unexpected' }),
      (v: ResumeMasterV1) => Object.assign(v.skills[0].source, { quote: 'unexpected' }),
    ]) {
      const value = complete();
      mutate(value);
      expect(validateResumeMaster(value).ok).toBe(false);
    }
  });
  it('requires all sections exactly once in order and keeps custom headings', () => {
    const value = complete();
    value.section_order.reverse();
    expect(buildResumeMasterPreview(value, [], context).sections[0]).toMatchObject({ id: 'awards', kind: 'other', heading: 'Awards' });
    for (const order of [value.section_order.slice(1), [...value.section_order, 'skills'], [...value.section_order, 'hidden']]) {
      expect(validateResumeMaster({ ...value, section_order: order })).toEqual({ ok: false, code: 'invalid_order' });
    }
    value.other_sections[0].id = 'skills';
    expect(validateResumeMaster(value).ok).toBe(false);
  });
});

describe('complete source activity and unmapped ranges', () => {
  it('accepts a 60000-character source quote and verifies exact Unicode ranges, without trimming', async () => {
    const rawText = '😀'.repeat(59_999) + '尾';
    const expectedDigest = await sourceDigest(rawText);
    const source = { kind: 'resume' as const, signature: expectedDigest, quote: rawText, start: 0, end: 60_000 };
    const value = empty();
    value.skills = [fact('f', 'Displayed skill', { source })];
    expect(validateResumeMaster(value).ok).toBe(true);
    expect(isActiveResumeFact(value.skills[0], { rawText, expectedDigest })).toBe(true);
    expect(isActiveResumeFact(value.skills[0], { rawText: 'x' + rawText.slice(1), expectedDigest })).toBe(false);
    expect(isActiveResumeFact(value.skills[0], { rawText, expectedDigest: 'b'.repeat(64) })).toBe(false);
  });
  it('checks quote total separately from value total', () => {
    const value = empty();
    const source = { kind: 'resume' as const, signature: 'a'.repeat(64), quote: 'x'.repeat(30_000), start: 0, end: 30_000 };
    value.skills = [fact('one', 'x', { source }), fact('two', 'x', { source })];
    expect(validateResumeMaster(value).ok).toBe(true);
    value.skills.push(fact('three', 'x', { source: { ...source, quote: 'x', end: 1 } }));
    expect(validateResumeMaster(value)).toEqual({ ok: false, code: 'quote_limit' });
  });
  it.each([
    { signature: 'A'.repeat(64) }, { signature: 'not a digest' }, { start: -1 }, { start: 0.1 },
    { end: 0 }, { end: 60_001 }, { quote: 'too short', end: 3 }, { kind: 'external' }, { extra: 'hidden' },
  ])('rejects malformed sources %j', (extra) => {
    const source = { kind: 'resume', signature: 'a'.repeat(64), quote: 'abc', start: 0, end: 3, ...extra };
    const value = { ...empty(), skills: [fact('f', 'value', { source: source as ResumeFact['source'] })] };
    expect(validateResumeMaster(value).ok).toBe(false);
  });
  it('preserves structurally valid old sources but excludes every nonconfirmed/stale fact from preview', async () => {
    const rawText = '  actual😀  ';
    const expectedDigest = await sourceDigest(rawText);
    const valid = fact('valid', 'Actual claim', { source: { kind: 'resume', signature: expectedDigest, quote: 'actual😀', start: 2, end: 9 } });
    const value = empty();
    value.skills = [valid, ...(['candidate', 'rejected', 'withdrawn'] as const).map((status) => ({ ...valid, id: status, status })),
      fact('stale', 'Old claim', { source: { ...valid.source, signature: 'f'.repeat(64) } as ResumeFact['source'] })];
    expect(validateResumeMaster(value).ok).toBe(true);
    const preview = buildResumeMasterPreview(value, [], { rawText, expectedDigest });
    expect(lines(preview)).toEqual(['Actual claim']);
    expect(preview.excludedFactCount).toBe(4);
    expect(isActiveResumeFact(valid, { rawText: '  wrong😀  ', expectedDigest })).toBe(false);
    expect(isActiveResumeFact(valid, { rawText: '\ud800', expectedDigest })).toBe(false);
  });
  it('keeps unmapped ranges exact and rejects overlap, reversed/unsafe spans or missing source binding', () => {
    const value = { ...empty(), source_signature: 'a'.repeat(64), unmapped_ranges: [{ start: 0, end: 2 }, { start: 2, end: 60_000 }] };
    expect(validateResumeMaster(value)).toEqual({ ok: true, value });
    for (const ranges of [[{ start: -1, end: 1 }], [{ start: 3, end: 3 }], [{ start: 0.1, end: 1 }],
      [{ start: 0, end: 60_001 }], [{ start: 0, end: 5 }, { start: 4, end: 6 }], [{ start: 0, end: 2, extra: true }]]) {
      expect(validateResumeMaster({ ...value, unmapped_ranges: ranges })).toEqual({ ok: false, code: 'invalid_range' });
    }
    expect(validateResumeMaster({ ...value, source_signature: null })).toEqual({ ok: false, code: 'invalid_range' });
  });
});

describe('source withdrawal/removal and exact experience references', () => {
  it('withdraws every source-linked field once, keeps manual content and reference history, and never mutates input', async () => {
    const value = complete();
    const source = { kind: 'resume' as const, signature: await sourceDigest('actual'), quote: 'actual', start: 0, end: 6 };
    value.source_signature = source.signature;
    value.unmapped_ranges = [{ start: 0, end: 6 }];
    for (const item of resumeMasterFacts(value)) item.source = source;
    value.basics.name!.source = { kind: 'manual' };
    value.skills[0].status = 'withdrawn';
    const before = JSON.stringify(value);
    const next = withdrawResumeMaster(value)!;
    expect(JSON.stringify(value)).toBe(before);
    expect(next.revision).toBe(2);
    expect(next.source_signature).toBeNull();
    expect(next.unmapped_ranges).toEqual([]);
    expect(next.basics.name).toEqual(value.basics.name);
    expect(next.activities[0].details).toEqual(value.activities[0].details);
    expect(next.skills[0]).toEqual(value.skills[0]);
    for (const item of resumeMasterFacts(next).filter((entry) => entry.source.kind === 'resume')) expect(item.status).toBe('withdrawn');
    expect(withdrawResumeMaster(next)).toEqual(next);
    expect(lines(buildResumeMasterPreview(next, [], context))).toEqual(['徐国一']);
  });
  it('removes all source quotes across all categories while keeping independent manual fields and optional manual references', () => {
    const value = complete();
    for (const item of resumeMasterFacts(value)) item.source = { kind: 'resume', signature: 'a'.repeat(64), quote: 'SECRET', start: 0, end: 6 };
    value.basics.name = fact('own-name', 'My own name');
    value.activities[0].details = [{ id: 'removed', revision: 1 }, { id: 'manual', revision: 1 }];
    const next = removeResumeMasterSources(value, [experience('manual')])!;
    expect(JSON.stringify(next)).not.toContain('SECRET');
    expect(resumeMasterFacts(next)).toEqual([value.basics.name]);
    expect(next.basics.links).toEqual([]);
    expect(next.activities[0].details).toEqual([{ id: 'manual', revision: 1 }]);
    expect(next.revision).toBe(2);
    expect(removeResumeMasterSources(next, [experience('manual')])).toEqual(next);
    expect(() => removeResumeMasterSources(value, [experience('manual', { text: '' })])).toThrow('invalid_reference');
  });
  it('does not increment revisions when an already independent manual master is unchanged', () => {
    const value = complete();
    expect(withdrawResumeMaster(value)).toBe(value);
    expect(removeResumeMasterSources(value)).toBe(value);
  });
  it('refuses revision overflow instead of losing provenance or wrapping a version', () => {
    const value = empty();
    const source = { kind: 'resume' as const, signature: 'a'.repeat(64), quote: 'actual', start: 0, end: 6 };
    value.skills = [fact('f', 'v', { source, revision: Number.MAX_SAFE_INTEGER })];
    expect(() => withdrawResumeMaster(value)).toThrow('revision_limit');
    value.skills[0].revision = 1;
    value.revision = Number.MAX_SAFE_INTEGER;
    expect(() => removeResumeMasterSources(value)).toThrow('revision_limit');
  });
  it('keeps historical and unconfirmed refs stored, but resolves only same-revision active confirmed entries', async () => {
    const rawText = 'Verified source';
    const expectedDigest = await sourceDigest(rawText);
    const entries = [
      experience('long', { text: '😀'.repeat(5_999) + '尾' }),
      experience('newer', { revision: 2 }), experience('candidate', { status: 'candidate' }),
      experience('rejected', { status: 'rejected' }), experience('withdrawn', { status: 'withdrawn' }),
      experience('stale', { source: { kind: 'resume', signature: 'a'.repeat(64), quote: rawText, start: 0, end: 15 } }),
      experience('source', { source: { kind: 'resume', signature: expectedDigest, quote: rawText, start: 0, end: 15 } }),
    ];
    const value = empty();
    value.activities = [{ id: 'activity', kind: 'project', details: [...entries.map((entry) => ({ id: entry.id, revision: 1 })), { id: 'missing', revision: 1 }] }];
    const before = JSON.stringify({ value, entries });
    expect(validateResumeMaster(value).ok).toBe(true);
    const preview = buildResumeMasterPreview(value, entries, { rawText, expectedDigest });
    expect(lines(preview)).toEqual([entries[0].text, entries[6].text]);
    expect(preview.unresolvedExperienceRefs.map((ref) => ref.id)).toEqual(['newer', 'candidate', 'rejected', 'withdrawn', 'stale', 'missing']);
    expect(JSON.stringify({ value, entries })).toBe(before);
  });
  it('rejects duplicate/malformed refs and does not resolve an invalid experience collection', () => {
    const value = empty();
    value.education = [{ id: 'e', details: [{ id: 'exp', revision: 1 }] }];
    const invalid = [experience('exp'), experience('exp')];
    expect(lines(buildResumeMasterPreview(value, invalid, context))).toEqual([]);
    for (const refs of [[{ id: 'exp', revision: 0 }], [{ id: 'exp', revision: 1, text: 'fake' }],
      [{ id: 'exp', revision: 1 }, { id: 'exp', revision: 2 }]]) {
      value.education[0].details = refs;
      expect(validateResumeMaster(value).ok).toBe(false);
    }
  });
  it('does not expose draft facts or raw unmapped content as confirmed preview', () => {
    const value = empty();
    value.basics.email = fact('email', 'candidate@example.test', { status: 'candidate' });
    value.source_signature = 'a'.repeat(64);
    value.unmapped_ranges = [{ start: 0, end: 6 }];
    expect(buildResumeMasterPreview(value, [], { rawText: 'SECRET', expectedDigest: 'a'.repeat(64) })).toEqual({
      sections: [], excludedFactCount: 1, unresolvedExperienceRefs: [],
    });
    expect(buildResumeMasterPreview(null, [], context)).toEqual({ sections: [], excludedFactCount: 0, unresolvedExperienceRefs: [] });
    expect(() => buildResumeMasterPreview({}, [], context)).toThrow('invalid_master');
  });
});


describe('resume editor comparison snapshot', () => {
  it('ignores only object-key order while retaining source, array and fact changes', () => {
    const master = createEmptyResumeMaster('snapshot-master');
    master.basics.name = { id: 'name', revision: 1, status: 'confirmed', value: 'Alex 王', source: { kind: 'manual' } };
    const profile = { resume_text: 'Exact raw\r\n🧪', resume_master: master };
    const reordered = JSON.parse(JSON.stringify(profile, (_key, value) => value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).reverse()) : value));
    expect(resumeMasterEditBase(reordered)).toEqual(resumeMasterEditBase(profile));
    reordered.resume_master.basics.name.revision = 2;
    expect(resumeMasterEditBase(reordered)).not.toEqual(resumeMasterEditBase(profile));
    expect(resumeMasterEditBase({ ...profile, resume_text: 'Exact raw\n🧪' })).not.toEqual(resumeMasterEditBase(profile));
    const order = { ...master, section_order: [...master.section_order].reverse() };
    expect(resumeMasterEditBase({ ...profile, resume_master: order })).not.toEqual(resumeMasterEditBase(profile));
  });
});

describe('résumé master candidates proposed from the résumé text', () => {
  const persona = readFileSync(join(__dirname, '__fixtures__/resume-pdf/persona.txt'), 'utf8');
  const values = (master: ResumeMasterV1) => ({
    basics: Object.fromEntries((['name', 'email', 'phone', 'location'] as const)
      .flatMap((key) => master.basics[key] ? [[key, master.basics[key]!.value]] : [])),
    links: master.basics.links.map((link) => [link.label, link.url.value]),
    education: master.education.map(({ id: _id, details: _details, ...fields }) =>
      Object.fromEntries(Object.entries(fields).map(([key, item]) => [key, (item as ResumeFact).value]))),
    activities: master.activities.map(({ id: _id, details: _details, kind, ...fields }) => ({ kind,
      ...Object.fromEntries(Object.entries(fields).map(([key, item]) => [key, (item as ResumeFact).value])) })),
    skills: master.skills.map((skill) => skill.value),
  });

  it('offers every contact, education, role, date and skill fact of the persona as an exact, unconfirmed quote', async () => {
    const signature = await sourceDigest(persona);
    const master = proposeResumeMaster(null, persona, signature);
    expect(values(master)).toEqual({
      basics: { name: 'JORDAN AVERY LEE', email: 'jordan.lee.test@example.com', location: 'Urbana, IL' },
      links: [],
      education: [{ school: 'University of Illinois Urbana-Champaign', degree: 'B.S.', field: 'Computer Science', end: 'expected May 2028' }],
      activities: [
        { kind: 'research', title: 'Undergraduate Research Assistant', organization: 'Health Imaging Lab (UIUC)', start: 'Jan 2026', end: 'Present' },
        { kind: 'employment', title: 'Software Engineering Intern', organization: 'Prairie Analytics', location: 'Champaign, IL', start: 'Jun 2026', end: 'Aug 2026' },
        { kind: 'project', title: 'Swahili-English Sentiment Classifier' },
        { kind: 'project', title: 'Campus Bus Tracker' },
      ],
      skills: ['Python', 'PyTorch', 'SQL', 'C++', 'Git', 'Linux', 'pandas', 'scikit-learn'],
    });
    const facts = resumeMasterFacts(master);
    expect(facts).toHaveLength(26);
    for (const item of facts) {
      expect(item.status).toBe('candidate');
      if (item.source.kind !== 'resume') throw new Error('expected a résumé source');
      expect(item.source.signature).toBe(signature);
      expect(Array.from(persona).slice(item.source.start, item.source.end).join('')).toBe(item.source.quote);
      expect(item.value).toBe(item.source.quote);
      expect(isActiveResumeFact(item, { rawText: persona, expectedDigest: signature })).toBe(false);
      expect(isActiveResumeFact({ ...item, status: 'confirmed' }, { rawText: persona, expectedDigest: signature })).toBe(true);
    }
    expect(master.source_signature).toBe(signature);
    expect(validateResumeMaster(master).ok).toBe(true);
  });

  it('reads a sidebar résumé: phone, profile link, a degree line under the school and right-aligned rows', async () => {
    const raw = ['Priya Natarajan', 'priya.natarajan.test@example.com', '(217) 555-0142', 'Champaign, IL', 'github.com/priya-test',
      'EDUCATION', 'University of Illinois Urbana-Champaign', 'B.S. in Bioengineering, Aug 2024 - May 2028',
      'Relevant coursework: Signals and Systems, Biomedical Imaging', 'SKILLS', 'Python, MATLAB, NumPy',
      'RESEARCH EXPERIENCE', 'Undergraduate Researcher, Tissue Mechanics Lab\tSep 2025 - Present',
      'University of Illinois Urbana-Champaign\tUrbana, IL',
      'Designed an efficient finite-element workflow that reduced the simulation time from six hours to forty minutes.',
      'Wrote first-draft test fixtures.', 'PROJECTS', 'Affordable Spirometer\tSpring 2025',
      'Built a low-cost flow meter and validated it against a clinical spirometer within five percent.'].join('\n');
    expect(values(proposeResumeMaster(null, raw, await sourceDigest(raw)))).toEqual({
      basics: { name: 'Priya Natarajan', email: 'priya.natarajan.test@example.com', phone: '(217) 555-0142', location: 'Champaign, IL' },
      links: [['github.com', 'github.com/priya-test']],
      education: [{ school: 'University of Illinois Urbana-Champaign', degree: 'B.S.', field: 'Bioengineering', start: 'Aug 2024', end: 'May 2028' }],
      activities: [
        { kind: 'research', title: 'Undergraduate Researcher', organization: 'Tissue Mechanics Lab', location: 'Urbana, IL', start: 'Sep 2025', end: 'Present' },
        { kind: 'project', title: 'Affordable Spirometer', start: 'Spring 2025' },
      ],
      skills: ['Python', 'MATLAB', 'NumPy'],
    });
  });

  it('reads this product\'s labelled export, a name in capitals and a skills list of acronyms', async () => {
    const raw = ['JORDAN AVERY LEE', 'Email: jordan.lee.test@example.com', 'Location: Urbana, Illinois', 'Education',
      'School: University of Illinois Urbana-Champaign', 'Degree: B.S.', 'Field: Computer Science', 'End: Expected May 2028',
      'Experience', 'Undergraduate Research Assistant', 'Organization: Health Imaging Lab (UIUC)', 'Start: Jan 2026', 'End: Present',
      '- Built a PyTorch pipeline that preprocesses 12,000 chest X-ray images.', 'Skills', 'Python', 'SQL', 'MATLAB'].join('\n');
    expect(values(proposeResumeMaster(null, raw, await sourceDigest(raw)))).toEqual({
      basics: { name: 'JORDAN AVERY LEE', email: 'jordan.lee.test@example.com', location: 'Urbana, Illinois' },
      links: [],
      education: [{ school: 'University of Illinois Urbana-Champaign', degree: 'B.S.', field: 'Computer Science', end: 'Expected May 2028' }],
      activities: [{ kind: 'research', title: 'Undergraduate Research Assistant', organization: 'Health Imaging Lab (UIUC)', start: 'Jan 2026', end: 'Present' }],
      skills: ['Python', 'SQL', 'MATLAB'],
    });
  });

  it('lets a replaced résumé\'s withdrawn facts make room for the new résumé\'s candidates', async () => {
    const old = 'OLD NAME | old@example.com\nSKILLS\nPython';
    const oldMaster = proposeResumeMaster(null, old, await sourceDigest(old));
    const confirmedOld = { ...oldMaster, basics: { ...oldMaster.basics, name: { ...oldMaster.basics.name!, status: 'confirmed' as const, revision: 2 } } };
    const withdrawn = withdrawResumeMaster(confirmedOld)!;
    expect(withdrawn.basics.name?.status).toBe('withdrawn');
    const next = proposeResumeMaster(withdrawn, persona, await sourceDigest(persona));
    expect(next.basics.name).toMatchObject({ value: 'JORDAN AVERY LEE', status: 'candidate' });
    expect(next.skills.filter((skill) => skill.value === 'Python').map((skill) => skill.status)).toEqual(['withdrawn', 'candidate']);
  });

  it('reads school, employer and skills set in capitals as content, not as headings', async () => {
    const raw = ['Jordan Lee', 'EDUCATION', 'UNIVERSITY OF MICHIGAN', 'B.S. Computer Science, Aug 2024 - May 2028', 'EXPERIENCE',
      'Software Engineering Intern, PRAIRIE ANALYTICS - Jun 2026 - Aug 2026', '- Wrote SQL jobs.', 'SKILLS', 'HTML, CSS, SQL',
      'Python, Git'].join('\n');
    expect(values(proposeResumeMaster(null, raw, await sourceDigest(raw)))).toEqual({
      basics: { name: 'Jordan Lee' },
      links: [],
      education: [{ school: 'UNIVERSITY OF MICHIGAN', degree: 'B.S.', field: 'Computer Science', start: 'Aug 2024', end: 'May 2028' }],
      activities: [{ kind: 'employment', title: 'Software Engineering Intern', organization: 'PRAIRIE ANALYTICS', start: 'Jun 2026', end: 'Aug 2026' }],
      skills: ['HTML', 'CSS', 'SQL', 'Python', 'Git'],
    });
  });

  it('never takes a heading on the first line for the name', async () => {
    const chinese = ['教育背景', '伊利诺伊大学厄巴纳-香槟分校 计算机科学 本科 2024.09 - 2028.05', '专业技能', 'Python、PyTorch、SQL'].join('\n');
    expect(values(proposeResumeMaster(null, chinese, await sourceDigest(chinese)))).toEqual({
      basics: {},
      links: [],
      education: [{ school: '伊利诺伊大学厄巴纳-香槟分校', degree: '本科', start: '2024.09', end: '2028.05' }],
      activities: [],
      skills: ['Python', 'PyTorch', 'SQL'],
    });
    const mainFirst = ['Work Experience', 'Research Intern, Biomechanics Lab\tJun 2025 - Aug 2025', 'Priya Natarajan',
      'priya.natarajan.test@example.com'].join('\n');
    const master = proposeResumeMaster(null, mainFirst, await sourceDigest(mainFirst));
    expect(master.basics.name).toBeUndefined();
    expect(values(master).activities).toEqual([
      { kind: 'research', title: 'Research Intern', organization: 'Biomechanics Lab', start: 'Jun 2025', end: 'Aug 2025' },
    ]);
  });

  it('takes a role row only from a row of names when the section has no glyph bullets', async () => {
    // Graphic list markers leave no glyph: a short point with a comma or a
    // role word in it ("mentors") is still a point, not the next role.
    const raw = ['Jordan Lee', 'EXPERIENCE', 'Research Assistant, Health Imaging Lab - Jan 2026 - Present',
      'Built a PyTorch pipeline that preprocesses 12,000 chest X-ray images and reports AUC.',
      'Built dashboards with Python, SQL', 'Presented weekly progress updates to the PI and two graduate mentors',
      'Python, SQL, Tableau',
      'Teaching Assistant, CS 225 Data Structures', 'Graded weekly assignments for 180 students',
      'Grader - Aug 2023 - May 2024', 'Checked weekly problem sets for two sections'].join('\n');
    expect(values(proposeResumeMaster(null, raw, await sourceDigest(raw))).activities).toEqual([
      { kind: 'research', title: 'Research Assistant', organization: 'Health Imaging Lab', start: 'Jan 2026', end: 'Present' },
      { kind: 'employment', title: 'Teaching Assistant', organization: 'CS 225 Data Structures' },
      { kind: 'employment', title: 'Grader', start: 'Aug 2023', end: 'May 2024' },
    ]);
  });

  it('takes no project from a row without a separator where the other projects have one', async () => {
    // A section title the list does not know ("Competitions") and the award
    // and outreach rows under it would read as projects in a list of bare
    // project names, but not among "Name | stack" rows.
    const raw = JSON.parse(readFileSync(join(__dirname, '__fixtures__/resume-pdf/resume-texts.json'), 'utf8'))['reflowed-unlisted-title'] as string;
    const master = values(proposeResumeMaster(null, raw, await sourceDigest(raw)));
    expect(master.activities.filter((activity) => activity.kind === 'project')).toEqual([
      { kind: 'project', title: 'Lumos' }, { kind: 'project', title: 'Quill' },
    ]);
    // Dates name a project too.
    const dated = ['Jordan Lee', 'PROJECTS', 'Quill (2024–2025)', '- Wrote the sync engine.', 'Competitions',
      'Finalist, Illinois Innovation Prize'].join('\n');
    expect(values(proposeResumeMaster(null, dated, await sourceDigest(dated))).activities).toEqual([
      { kind: 'project', title: 'Quill', start: '2024', end: '2025' },
    ]);
    // A list of bare project names still reads as projects, whatever its points say.
    const bare = ['Jordan Lee', 'PROJECTS', 'PantryPal', '- Built the inventory tracker for the food pantry.', 'Lumos',
      '- Trained a plant disease classifier - 4,000 leaf images.'].join('\n');
    expect(values(proposeResumeMaster(null, bare, await sourceDigest(bare))).activities).toEqual([
      { kind: 'project', title: 'PantryPal' }, { kind: 'project', title: 'Lumos' },
    ]);
  });

  it('reads Title Case section titles joined by "&" as headings', async () => {
    const raw = ['Jordan Lee', 'Experience & Leadership', 'President, Chess Club - Aug 2024 - Present', '- Organized weekly tournaments.',
      'Research & Projects', 'Campus Bus Tracker - React and Flask web app used by about 200 students during Fall 2025.',
      'Skills & Tools', 'Python, SQL'].join('\n');
    const master = values(proposeResumeMaster(null, raw, await sourceDigest(raw)));
    expect(master.activities).toEqual([
      { kind: 'other', title: 'President', organization: 'Chess Club', start: 'Aug 2024', end: 'Present' },
      { kind: 'project', title: 'Campus Bus Tracker' },
    ]);
    expect(master.skills).toEqual(['Python', 'SQL']);
  });

  it('skips a link that names no usable host instead of failing the whole proposal', async () => {
    const raw = [`Jordan Lee | https:///weird | www.${'a'.repeat(130)}.com | github.com/jlee`, 'SKILLS', 'Python'].join('\n');
    const master = proposeResumeMaster(null, raw, await sourceDigest(raw));
    expect(values(master).links).toEqual([['github.com', 'github.com/jlee']]);
    expect(values(master).skills).toEqual(['Python']);
  });

  it('keeps what the master already holds and never re-proposes a span, even one the student excluded', async () => {
    const signature = await sourceDigest(persona);
    const own = empty();
    own.basics.name = fact('own-name', 'Jordan Lee');
    own.skills = [fact('own-skill', 'python')];
    const first = proposeResumeMaster(own, persona, signature);
    expect(first.basics.name).toEqual(own.basics.name);
    expect(first.skills.map((skill) => skill.value)).not.toContain('Python');
    const excluded = { ...first, skills: first.skills.map((skill) => ({ ...skill, status: 'rejected' as const, revision: 2 })) };
    expect(proposeResumeMaster(excluded, persona, signature)).toEqual(excluded);
    expect(proposeResumeMaster(first, persona, signature)).toEqual(first);
  });
});
