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
const TEMPLATE = ['Faculty research profile for', 'Research areas:', 'Contact this faculty member',
  'The source profile states', 'The source profile reports', 'this faculty member'];

// The Chinese detail page showed "Faculty research profile for Yoram Bresler
// in Bioengineering at ... Contact this faculty member to ask whether ..."
// under a Chinese 描述 heading. Only the research areas are source text.
describe('localizedFacultyDescription', () => {
  it.each(fixture.cases)('reads exactly as the server wrote it in English: $name', (c) => {
    expect(localizedFacultyDescription(opp(c.record), c.server_text, tIn('en'))).toBe(c.server_text);
  });

  it.each(fixture.cases)('says the product sentences in Chinese and keeps the source areas: $name', (c) => {
    const zh = localizedFacultyDescription(opp(c.record), c.server_text, tIn('zh'));
    expect(zh).not.toBeNull();
    const productCopy = c.research_areas ? zh!.replace(c.research_areas, '') : zh!;
    if (c.research_areas) expect(zh).toContain(c.research_areas);
    for (const fragment of TEMPLATE) expect(productCopy).not.toContain(fragment);
    for (const field of ['pi_name', 'department', 'organization'] as const) {
      const value = (c.record as Record<string, unknown>)[field];
      if (typeof value === 'string') expect(zh).toContain(value);
    }
  });

  it('leaves any other description alone', () => {
    const t = tIn('zh');
    const faculty = { source_type: 'faculty_research', pi_name: 'Ada Lovelace', department: 'CS', organization: 'Example U' };
    for (const text of [
      'Faculty research profile: computer vision and medical imaging.',
      // The record changed after the server wrote the text: not ours to re-say.
      'Faculty research profile for Grace Hopper in CS at Example U. Contact this faculty member to ask whether undergraduate research opportunities are currently available.',
      'Faculty research profile for Ada Lovelace in CS at Example U. Research areas: Vision An unknown closing sentence.',
    ]) {
      expect(localizedFacultyDescription(faculty, text, t)).toBeNull();
    }
    const listing = { ...faculty, source_type: 'campus_program' };
    expect(localizedFacultyDescription(listing, fixture.cases[0].server_text, t)).toBeNull();
  });
});
