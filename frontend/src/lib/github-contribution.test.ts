import { describe, expect, it } from 'vitest';
import { githubProfileLogin, githubPullPath, validGitHubPullSource } from './github-contribution';

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
});
