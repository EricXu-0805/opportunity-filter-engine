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
