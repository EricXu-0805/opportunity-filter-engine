import type { GitHubPullSource } from './types';

const loginPattern = /^[a-z0-9](?:[a-z0-9]|-[a-z0-9])*$/i;
const repoPattern = /^[a-z0-9_.-]{1,100}$/i;

function validLogin(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 39 && loginPattern.test(value);
}

function validRepository(value: unknown): boolean {
  if (typeof value !== 'string') return false;
  const [owner, repo, ...more] = value.split('/');
  return !more.length && validLogin(owner) && !!repo && repo !== '.' && repo !== '..' && repoPattern.test(repo);
}

function githubPath(raw: string): string[] {
  try {
    const url = new URL(raw.trim());
    if (url.protocol === 'https:' && ['github.com', 'www.github.com'].includes(url.hostname)
      && !url.username && !url.password && !url.port) return url.pathname.replace(/\/$/, '').slice(1).split('/');
  } catch { /* Not a public GitHub URL. */ }
  return [];
}

export function githubProfileLogin(raw: string): string | null {
  const parts = githubPath(raw);
  return parts.length === 1 && validLogin(parts[0]) ? parts[0] : null;
}

export function githubPullPath(raw: string) {
  const [owner, repo, route, number, ...rest] = githubPath(raw);
  if (rest.length || !validRepository(`${owner}/${repo}`) || route !== 'pull' || !/^[1-9]\d*$/.test(number)
    || !Number.isSafeInteger(Number(number))) return null;
  return { owner, repo, number: Number(number) };
}

export function validGitHubPullSource(source: Record<string, unknown>): boolean {
  return source.kind === 'github' && Object.keys(source).length === 6
    && validRepository(source.repository) && (source.head_repository === null || validRepository(source.head_repository))
    && validLogin(source.author) && Number.isSafeInteger(source.number) && Number(source.number) > 0
    && typeof source.title === 'string' && !!source.title.trim() && Array.from(source.title).length <= 512
    && Array.from(source.title).every(char => {
      const code = char.codePointAt(0)!;
      return code >= 32 && (code < 0xd800 || code > 0xdfff);
    });
}

export function githubPullUrl(source: GitHubPullSource): string {
  return `https://github.com/${source.repository}/pull/${source.number}`;
}

/** The pull request an entry may be shown with. The student may reword an imported
 * sentence; once it no longer names both the repository and the pull number it is their
 * own statement, entered by them (backend/lib/github_contribution.py names_pull). */
export function linkedGitHubPull({ text, source }: {
  text: string; source: GitHubPullSource | { kind: 'manual' | 'resume' };
}): GitHubPullSource | null {
  return source.kind === 'github' && validGitHubPullSource({ ...source })
    && text.toLowerCase().includes(source.repository.toLowerCase())
    && new RegExp(`(?<![0-9])${source.number}(?![0-9])`).test(text) ? source : null;
}
