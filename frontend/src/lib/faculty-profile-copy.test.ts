import { describe, expect, it } from 'vitest';
import fixture from './__fixtures__/faculty-profile-summary.json';
import { translate } from '@/i18n/translate';
import { localizedFacultyDescription } from './faculty-profile-copy';

type Case = (typeof fixture.cases)[number];
const tIn = (locale: 'en' | 'zh') => (key: string, vars?: Record<string, string | number>) => translate(locale, key, vars);
const opp = (record: Case['record']) => ({
  source_type: record.source_type,
  pi_name: 'pi_name' in record ? record.pi_name : undefined,
  department: 'department' in record ? record.department : undefined,
  organization: 'organization' in record ? record.organization : undefined,
});
const withFields = (c: Case) => ({ ...opp(c.record), faculty_profile_summary: c.fields });
const TEMPLATE = ['Faculty research profile for', 'Research areas:', 'Contact this faculty member',
  'The source profile states', 'The source profile reports', 'this faculty member'];
// What a server that reworded its English would send: none of the old
// sentences survive, so nothing here can be recognised by matching them.
const REWORDED = 'Profile of a faculty member, written in new server wording.';

function expectChinese(zh: string | null, c: Case) {
  expect(zh).not.toBeNull();
  const productCopy = c.research_areas ? zh!.replace(c.research_areas, '') : zh!;
  if (c.research_areas) expect(zh).toContain(c.research_areas);
  for (const fragment of TEMPLATE) expect(productCopy).not.toContain(fragment);
  for (const field of ['pi_name', 'department', 'organization'] as const) {
    const value = (c.record as Record<string, unknown>)[field];
    if (typeof value === 'string') expect(zh).toContain(value);
  }
}

// The Chinese detail page showed "Faculty research profile for Yoram Bresler
// in Bioengineering at ... Contact this faculty member to ask whether ..."
// under a Chinese 描述 heading. Only the research areas are source text.
describe('localizedFacultyDescription from the structured fields', () => {
  it.each(fixture.cases)('says the fields in English exactly as the server wrote them: $name', (c) => {
    expect(localizedFacultyDescription(withFields(c), c.server_text, tIn('en'))).toBe(c.server_text);
  });

  it.each(fixture.cases)('says the fields in Chinese whatever the English sentence reads: $name', (c) => {
    expectChinese(localizedFacultyDescription(withFields(c), REWORDED, tIn('zh')), c);
  });

  it('reads the profile from the fields, not from the record around them', () => {
    const c = fixture.cases[0];
    const renamed = { ...withFields(c), pi_name: 'Someone Else', department: 'History' };
    expect(localizedFacultyDescription(renamed, c.server_text, tIn('en'))).toBe(c.server_text);
  });

  it('prefers the fields over an English sentence it could also recognise', () => {
    const c = fixture.cases[0];
    const fields = { ...c.fields, availability: 'research_inactive' };
    expect(localizedFacultyDescription({ ...opp(c.record), faculty_profile_summary: fields }, c.server_text, tIn('en')))
      .toMatch(/not currently conducting active research\.$/);
  });

  it('withholds a description the caller withheld', () => {
    const c = fixture.cases[0];
    expect(localizedFacultyDescription(withFields(c), '', tIn('zh'))).toBeNull();
    expect(localizedFacultyDescription(withFields(c), '   ', tIn('zh'))).toBeNull();
  });

  it('ignores the fields on anything that is not a faculty profile', () => {
    const c = fixture.cases[0];
    expect(localizedFacultyDescription({ ...withFields(c), source_type: 'campus_program' }, c.server_text, tIn('zh'))).toBeNull();
  });

  it.each([
    ['an unknown version', { version: 2 }],
    ['an unknown availability', { availability: 'on_sabbatical' }],
    ['an inherited key as availability', { availability: 'toString' }],
    ['an empty name instead of null', { name: '' }],
    ['a number for the department', { department: 7 }],
    ['a missing research_areas', { research_areas: undefined }],
  ])('treats fields with %s as absent', (_label, patch) => {
    const c = fixture.cases[0];
    const fields = { ...c.fields, ...patch };
    expect(localizedFacultyDescription({ ...opp(c.record), faculty_profile_summary: fields }, REWORDED, tIn('zh'))).toBeNull();
    expect(localizedFacultyDescription({ ...opp(c.record), faculty_profile_summary: fields }, c.server_text, tIn('zh')))
      .toBe(localizedFacultyDescription(opp(c.record), c.server_text, tIn('zh')));
  });
});

// A payload from a backend that predates the fields: only the exact English
// it used to write can be recognised.
describe('localizedFacultyDescription without the fields', () => {
  it.each(fixture.cases)('reads exactly as the server wrote it in English: $name', (c) => {
    expect(localizedFacultyDescription(opp(c.record), c.server_text, tIn('en'))).toBe(c.server_text);
  });

  it.each(fixture.cases)('says the product sentences in Chinese and keeps the source areas: $name', (c) => {
    expectChinese(localizedFacultyDescription(opp(c.record), c.server_text, tIn('zh')), c);
  });

  it('leaves any other description alone', () => {
    const t = tIn('zh');
    const faculty = { source_type: 'faculty_research', pi_name: 'Ada Lovelace', department: 'CS', organization: 'Example U' };
    for (const text of [
      'Faculty research profile: computer vision and medical imaging.',
      // The record changed after the server wrote the text: not ours to re-say.
      'Faculty research profile for Grace Hopper in CS at Example U. Contact this faculty member to ask whether undergraduate research opportunities are currently available.',
      'Faculty research profile for Ada Lovelace in CS at Example U. Research areas: Vision An unknown closing sentence.',
      REWORDED,
    ]) {
      expect(localizedFacultyDescription(faculty, text, t)).toBeNull();
    }
    const listing = { ...faculty, source_type: 'campus_program' };
    expect(localizedFacultyDescription(listing, fixture.cases[0].server_text, t)).toBeNull();
  });
});
