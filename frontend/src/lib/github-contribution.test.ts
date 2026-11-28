import { describe, expect, it } from 'vitest';
import { dictionaries } from '@/i18n/dictionaries';
import { githubProfileLogin, githubPullPath, linkedGitHubPull, validGitHubPullSource } from './github-contribution';

describe('public GitHub contribution links', () => {
  it('requires an actual GitHub profile and a positive pull number on GitHub', () => {
    expect(githubProfileLogin('https://github.com/Student/')).toBe('Student');
    expect(githubPullPath('https://github.com/team/vision/pull/23#discussion')).toEqual({ owner: 'team', repo: 'vision', number: 23 });
    expect(githubProfileLogin('https://different.test/github.com/Student')).toBeNull();
    expect(githubProfileLogin('https://github.com/Student/project')).toBeNull();
    for (const link of ['https://github.com.evil.test/team/repo/pull/2', 'https://github.com/team/repo/issues/2',
      'https://github.com/team/repo/pull/0', 'https://github.com/team/repo/pull/9007199254740993']) {
      expect(githubPullPath(link)).toBeNull();
    }
  });
  it('validates the stored source before presenting its link', () => {
    const source = { kind: 'github', repository: 'org/repo', head_repository: null, author: 'student', number: 23, title: 'Measure 🌱' };
    expect(validGitHubPullSource(source)).toBe(true);
    expect(validGitHubPullSource({ ...source, repository: 'org/../evil' })).toBe(false);
    expect(validGitHubPullSource({ ...source, number: -3 })).toBe(false);
  });
  it('keeps the pull request as an entry\'s source only while the text names its repository and number', () => {
    const source = { kind: 'github' as const, repository: 'lab/vision', head_repository: null, author: 'Student', number: 8, title: 'Measure crop growth' };
    const fill = (text: string) => text.replace('{repo}', source.repository).replace('{number}', String(source.number)).replace('{title}', source.title);
    // The sentence the import writes, in either language, and a correction that still names the pull request.
    for (const text of [fill(dictionaries.en.home.experience.githubFact), fill(dictionaries.zh.home.experience.githubFact),
      'In LAB/Vision I opened pull request 8, which adds a growth measure.']) {
      expect(linkedGitHubPull({ text, source })).toBe(source);
    }
    for (const text of ['I trained a speech recognition model in PyTorch that reached 97% accuracy on 40 speakers.',
      'I opened pull request #8.', 'I contributed to lab/vision.', 'I opened pull request #80 in lab/vision.',
      'I opened 18 pull requests in lab/vision.']) {
      expect(linkedGitHubPull({ text, source })).toBeNull();
    }
    expect(linkedGitHubPull({ text: 'lab/vision 8', source: { kind: 'manual' } })).toBeNull();
    expect(linkedGitHubPull({ text: 'lab/vision 8', source: { ...source, repository: 'lab/../vision' } })).toBeNull();
  });
});
