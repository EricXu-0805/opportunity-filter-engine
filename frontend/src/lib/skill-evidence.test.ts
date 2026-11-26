import { describe, it, expect } from 'vitest';
import { skillLevelIsTheStudentsOwn, skillNeedsConfirming, skillsWithResume, withGitHubImportEvidence } from './skill-evidence';
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

describe('skillsWithResume — checklist M18', () => {
  it('leaves a skill with no source alone: it may have been typed', () => {
    const legacy = s({ name: 'MATLAB', level: 'experienced' });
    expect(skillsWithResume([legacy], [])).toEqual({ skills: [legacy], onlyAdds: true });
  });

  it('is only additions when the same résumé is read again, keeping each skill as stored', () => {
    const python = s({ source: 'resume', evidence: 'Skills: Python' });
    const result = skillsWithResume([python], [s({ source: 'resume', evidence: 'Skills: Python' }), s({ name: 'Java', source: 'resume' })]);
    expect(result.onlyAdds).toBe(true);
    expect(result.skills[0]).toBe(python);
    expect(result.skills.map((skill) => skill.name)).toEqual(['Python', 'Java']);
  });
});

describe('re-importing GitHub evidence', () => {
  const imported = s({ source: 'github', evidence: 'repo example: language Python' });
  it('adds only the receipt, preserving the remote level and confirmation', () => {
    const confirmed = s({ source: 'github', level: 'expert', confirmed: true });
    expect(withGitHubImportEvidence(confirmed, imported)).toEqual({ ...confirmed, evidence: imported.evidence });
  });
  it('keeps other sources, earlier evidence and unrelated names unchanged', () => {
    for (const existing of [s({}), s({ source: 'resume' }), s({ source: 'shared' }),
      s({ source: 'github', evidence: 'prior receipt' }), s({ source: 'github', name: 'pandas' })]) {
      expect(withGitHubImportEvidence(existing, imported)).toBe(existing);
    }
    const old = s({ source: 'github' });
    expect(withGitHubImportEvidence(old, { ...imported, evidence: ' ' })).toBe(old);
  });
});

describe('M18 independent sources on the same skill', () => {
  const resume = s({ source: 'resume', level: 'experienced', evidence: 'Skills: Python' });
  const github = s({ source: 'github', evidence: 'repo example: language Python',
    github_receipt: { account: 'example', evidence: 'repo example: language Python' } });

  it('keeps the résumé quote while both sources are present, then uses only the remaining repository', () => {
    const combined = withGitHubImportEvidence(resume, github);
    expect(combined).toEqual({ ...resume, github_receipt: github.github_receipt });
    expect(withGitHubImportEvidence(combined, github)).toBe(combined);
    const replacement = s({ source: 'resume', evidence: 'Used Python for maps' });
    const updated = skillsWithResume([combined], [replacement], 'example').skills;
    expect(updated).toEqual([{ ...combined, evidence: replacement.evidence }]);
    const expected: SkillWithLevel = { name: 'Python', source: 'github', evidence: github.evidence, level: 'experienced' };
    for (const profile of ['example', 'https://github.com/Example/', 'https://github.com/example/tools']) {
      expect(skillsWithResume(updated, [], profile)).toEqual({ skills: [expected], onlyAdds: false });
    }
    expect(skillNeedsConfirming(expected)).toBe(true);
  });

  it('does not use a previous account, an unattributed import, or evidence from an unrelated name', () => {
    const combined = withGitHubImportEvidence(resume, github);
    for (const url of ['', 'another', 'https://unrelated.example/example', 'https://notgithub.com/example']) {
      expect(skillsWithResume([combined], [], url).skills).toEqual([]);
    }
    expect(withGitHubImportEvidence(resume, { ...github, name: 'Java' })).toBe(resume);
    expect(withGitHubImportEvidence(resume, { ...github, github_receipt: undefined })).toBe(resume);
    const shared = s({ source: 'shared', level: 'experienced' });
    expect(withGitHubImportEvidence(shared, github)).toBe(shared);
    const typed = s({ level: 'expert', confirmed: true });
    expect(withGitHubImportEvidence(typed, github)).toBe(typed);
  });
});
