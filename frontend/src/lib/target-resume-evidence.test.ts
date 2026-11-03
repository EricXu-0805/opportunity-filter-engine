import { describe, expect, it } from 'vitest';
import publicFixture from '../../../tests/fixtures/target-resume-context-v4-golden.json';
import researchFixture from '../../../tests/fixtures/target-resume-context-v3-golden.json';
import type { TargetResumeContext } from './target-resume';
import { isTargetResumeEvidence, targetResumeEvidenceSource } from './target-resume-evidence';

const target = () => structuredClone(publicFixture.draft.target_snapshot) as TargetResumeContext;
const research = researchFixture.draft.target_snapshot as TargetResumeContext;
const span = (source: string, quote: string) => {
  const start = Array.from(source.slice(0, source.indexOf(quote))).length;
  return { start, end: start + Array.from(quote).length, quote };
};

describe('complete context for exact résumé citations', () => {
  it('keeps preceding negation and following qualifications without changing the excerpt', () => {
    const t = target(); t.description = '😀 We do not require Python parsers; students can learn on the job.\r\nNext paragraph.';
    const e = { field: 'description', requirement_index: null, ...span(t.description, 'Python parsers') };
    const before = structuredClone(e);
    expect(targetResumeEvidenceSource(t, e)).toBe(t.description);
    expect(isTargetResumeEvidence(t, e)).toBe(true);
    expect(e).toEqual(before);
  });
  it('resolves a requirement independently of identical text elsewhere', () => {
    const t = target(); t.description = 'Python parsers'; t.requirements = ['😀 Python programming, not parser experience.'];
    const e = { field: 'requirement', requirement_index: 0, ...span(t.requirements[0], 'Python') };
    expect(targetResumeEvidenceSource(t, e)).toBe(t.requirements[0]);
  });
  it.each(['paper_title', 'paper_abstract'] as const)('preserves the whole %s source', field => {
    const work = researchFixture.draft.target_snapshot.research.snapshot.works[0];
    const source = field === 'paper_title' ? work.title : work.abstract!;
    const e = { field, paper_index: 0, ...span(source, '研究') };
    expect(targetResumeEvidenceSource(research, e)).toBe(source);
    expect(targetResumeEvidenceSource(research, e, false)).toBeNull();
  });
  it.each(['lab_heading', 'lab_text'] as const)('resolves the cited %s without mixing other sections', field => {
    const section = publicFixture.draft.target_snapshot.lab.snapshot.pages[0].sections[0];
    const source = field === 'lab_heading' ? section.heading : section.text;
    const e = { field, page_index: 0, section_index: 0, ...span(source, '实验室') };
    expect(targetResumeEvidenceSource(target(), e)).toBe(source);
    expect(targetResumeEvidenceSource(target(), e, true, false)).toBeNull();
  });
  it.each([
    { field: 'description', requirement_index: null, start: 0, end: 6, quote: 'Invent' },
    { field: 'description', requirement_index: null, start: -1, end: 6, quote: 'Python' },
    { field: 'description', requirement_index: null, start: 0, end: 6.5, quote: 'Python' },
    { field: 'description', requirement_index: null, start: 0, end: 0, quote: '' },
    { field: 'description', requirement_index: null, start: 0, end: 6, quote: 'Python', extra: true },
    { field: 'requirement', requirement_index: 99, start: 0, end: 6, quote: 'Python' },
    { field: 'paper_abstract', paper_index: 1, start: 0, end: 6, quote: 'Python' },
    { field: 'lab_text', page_index: 0, section_index: 99, start: 0, end: 6, quote: 'Python' },
  ])('does not expand malformed, unavailable or stale evidence: %j', e => {
    for (const t of [target(), research]) {
      expect(targetResumeEvidenceSource(t, e)).toBeNull();
      expect(isTargetResumeEvidence(t, e)).toBe(false);
    }
  });
});
