import { describe, it, expect } from 'vitest';
import { skillLevelIsTheStudentsOwn, skillNeedsConfirming } from './skill-evidence';
import type { SkillWithLevel } from './types';

const s = (o: Partial<SkillWithLevel> & { name?: string }): SkillWithLevel =>
  ({ name: 'Python', level: 'beginner', ...o } as SkillWithLevel);

describe('skillLevelIsTheStudentsOwn — mirrors src/student_evidence.py', () => {
  it('an import is not theirs until they say so', () => {
    expect(skillLevelIsTheStudentsOwn(s({ level: 'experienced', source: 'resume' }))).toBe(false);
    expect(skillLevelIsTheStudentsOwn(s({ level: 'expert', source: 'github' }))).toBe(false);
    expect(skillLevelIsTheStudentsOwn(s({ level: 'expert', source: 'shared' }))).toBe(false);
  });

  it('confirming beats any source — that is the upgrade path', () => {
    expect(skillLevelIsTheStudentsOwn(
      s({ level: 'expert', source: 'github', confirmed: true }),
    )).toBe(true);
  });

  it('a legacy experienced fails closed', () => {
    // Both import sites stamped this literal value, and one badge click looks
    // identical in stored data. The ambiguous one is withheld.
    expect(skillLevelIsTheStudentsOwn(s({ level: 'experienced' }))).toBe(false);
  });

  it('a legacy expert does not', () => {
    // Nothing writes 'expert' but cycleLevel, the badge the student clicks.
    expect(skillLevelIsTheStudentsOwn(s({ level: 'expert' }))).toBe(true);
  });
});

describe('skillNeedsConfirming — who gets asked, and who is left alone', () => {
  it('asks about an import, whatever level it landed at', () => {
    expect(skillNeedsConfirming(s({ source: 'resume' }))).toBe(true);
    expect(skillNeedsConfirming(s({ level: 'experienced', source: 'github' }))).toBe(true);
  });

  it('asks about a legacy level that is being withheld', () => {
    // Otherwise the student is muted invisibly: their profile says experienced
    // and their email says exposure, with nothing explaining the gap.
    expect(skillNeedsConfirming(s({ level: 'experienced' }))).toBe(true);
  });

  it('leaves a plain typed beginner alone', () => {
    // It claims nothing, so there is nothing to restore and nothing to ask.
    expect(skillNeedsConfirming(s({ level: 'beginner' }))).toBe(false);
  });

  it('leaves a settled skill alone', () => {
    expect(skillNeedsConfirming(s({ level: 'expert' }))).toBe(false);
    expect(skillNeedsConfirming(
      s({ level: 'experienced', source: 'resume', confirmed: true }),
    )).toBe(false);
  });
});
