import { describe, expect, it } from 'vitest';
import { shownHeading } from './renovation-review';
import type { RenovatedSection } from './types';

const section = (heading: string, kind: string, lines: string[]) => ({
  heading, kind, bullets: lines.map((base_text, i) => ({ id: `b${i}`, base_text, variants: [], current: -1, action: 'keep' })),
}) as unknown as RenovatedSection;
const EN = ['Ran 40 soil moisture trials for the campus farm'];
const ZH = ['在校园农场完成 40 次土壤湿度试验'];

describe('shownHeading (round-3 re-measure, criterion 1)', () => {
  it('shows the student\'s own heading row in the résumé\'s spelling', () => {
    expect(shownHeading(section('Work Experience', 'experience', EN), 'WORK EXPERIENCE:\n• Ran 40 soil moisture trials for the campus farm')).toBe('WORK EXPERIENCE');
    expect(shownHeading(section('科研经历', 'research', ZH), '科研经历\n• 在校园农场完成 40 次土壤湿度试验')).toBe('科研经历');
  });
  it.each([
    ['Publications', 'research', EN, 'Experience'],
    ['科研经历', 'research', EN, 'Experience'],
    ['Research Experience', 'research', ZH, '项目与经历'],
    ['', 'education', ZH, '教育经历'],
    ['Tools', 'skills', [], 'Skills'],
    ['Awards', 'unknown-kind', EN, 'Additional information'],
  ])('shows a heading %s that is no row of the résumé as the standard name of kind %s', (heading, kind, lines, shown) => {
    expect(shownHeading(section(heading, kind, lines), '• Ran 40 soil moisture trials for the campus farm')).toBe(shown);
  });
});

// Round-3 re-measure: shownHeading took any résumé row equal to the heading. A saved section
// headed "Selected Publications" whose lines sit under "RESEARCH EXPERIENCE" showed the
// résumé's "SELECTED PUBLICATIONS" row, and a glyph row given as a heading showed as one; the
// backend (/tailor/structure, _section_heading) keeps only the nearest heading row above.
describe('shownHeading reads the nearest heading row above the section, as the backend does', () => {
  const RESUME = 'RESEARCH EXPERIENCE\n• Ran 40 soil moisture trials for the campus farm.\n'
    + 'SELECTED PUBLICATIONS\n• Drafted a paper on drip irrigation (not submitted).\n';
  const LINES = ['Ran 40 soil moisture trials for the campus farm.'];
  it.each([
    ['Selected Publications', 'another section\'s row'],
    ['• Drafted a paper on drip irrigation (not submitted).', 'a glyph row'],
    ['Drafted a paper on drip irrigation (not submitted).', 'a later line'],
  ])('shows a heading %s (%s) as the standard name', (heading) => {
    expect(shownHeading(section(heading, 'research', LINES), RESUME)).toBe('Experience');
  });
  it('shows the nearest heading row above, in the résumé\'s spelling', () => {
    expect(shownHeading(section('Research Experience', 'research', LINES), RESUME)).toBe('RESEARCH EXPERIENCE');
    expect(shownHeading(section('Selected publications', 'research', ['Drafted a paper on drip irrigation (not submitted)']), RESUME))
      .toBe('SELECTED PUBLICATIONS');
  });
  it('stops at a row another section of the doc is headed by', () => {
    const resume = 'Work History\nsmith lab, campus farm\n• Ran 40 soil moisture trials for the campus farm\n';
    const own = section('Work History', 'experience', ['Ran 40 soil moisture trials for the campus farm']);
    expect(shownHeading(own, resume, [own])).toBe('Work History');
    expect(shownHeading(own, resume, [own, section('smith lab, campus farm', 'research', [])])).toBe('Experience');
  });
  it('takes the section\'s earliest line and a wrapped or inline-glyph line', () => {
    const resume = 'PROJECTS\nResearch Assistant • Wrote the methods section\n• Built a dashboard for the lab\nthat was never deployed.\n';
    expect(shownHeading(section('Projects', 'projects', ['Built a dashboard for the lab that was never deployed', 'Wrote the methods section']), resume))
      .toBe('PROJECTS');
  });
});

// Round-3 re-verification (3d): lineRow stripped only "•", "-", "*", "–", "—", "+", "▪", "●", "◦", "·" and
// "1." from a row, so a section whose lines open with Word's U+F0B7 bullet, "■", "①", "1、" or "-Built"
// found no row and showed the standard name; backend _section_heading reads them all (_lead_ends).
describe('shownHeading reads a line after any glyph, list number or marks', () => {
  it.each(['\uf0b7\t', '■ ', '➢ ', '(1) ', '①', '1、', '-', '※ ', 'o\t'])('finds the heading above a line after %j', (glyph) => {
    const resume = `RESEARCH EXPERIENCE\n${glyph}Ran 40 soil moisture trials for the campus farm\n`;
    expect(shownHeading(section('Research Experience', 'research', EN), resume)).toBe('RESEARCH EXPERIENCE');
  });
  it('does not read a sign before a number as a glyph', () => {
    const resume = 'RESEARCH EXPERIENCE\n~40 soil moisture trials for the campus farm\n';
    expect(shownHeading(section('Research Experience', 'research', ['40 soil moisture trials for the campus farm']), resume))
      .toBe('Experience');
  });
});
