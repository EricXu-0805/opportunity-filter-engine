import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  normalizeEnvironment,
  normalizeSha,
  resolveBuildInfo,
  UNKNOWN_ENVIRONMENT,
} from './build-info';

const REAL_SHA = '1029f033257f3a3cd581e7e9911efac1e7260f17';

beforeEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('release SHA pass-through', () => {
  it('reports the commit Vercel inlined at build time', () => {
    expect(resolveBuildInfo({ NEXT_PUBLIC_RELEASE_SHA: REAL_SHA })).toEqual({
      releaseSha: REAL_SHA,
      releaseShaShort: '1029f03',
      environment: UNKNOWN_ENVIRONMENT,
    });
  });

  it('shortens to exactly seven characters and lowercases', () => {
    const info = resolveBuildInfo({ NEXT_PUBLIC_RELEASE_SHA: REAL_SHA.toUpperCase() });
    expect(info.releaseSha).toBe(REAL_SHA);
    expect(info.releaseShaShort).toHaveLength(7);
  });

  it('accepts an already-short override SHA', () => {
    expect(normalizeSha('abc1234')).toBe('abc1234');
  });
});

describe('honest unknown', () => {
  it.each([
    ['missing', undefined],
    ['empty', ''],
    ['whitespace', '   '],
    ['the word unknown', 'unknown'],
    ['a placeholder', 'dev'],
    ['an unexpanded template', '$VERCEL_GIT_COMMIT_SHA'],
    ['a shell template', '${OFE_RELEASE_SHA}'],
    ['a branch name', 'main'],
    ['too short to identify a commit', 'abc'],
    ['not hex', 'zzzzzzzzzzzz'],
    ['longer than a SHA', '0'.repeat(41)],
  ])('reports null for %s rather than publishing it', (_label, value) => {
    expect(normalizeSha(value)).toBeNull();
  });

  it('never substitutes a placeholder SHA when the build supplied none', () => {
    const info = resolveBuildInfo({});
    expect(info.releaseSha).toBeNull();
    expect(info.releaseShaShort).toBeNull();
  });

  it('reports "unknown" for a missing environment and never infers production', () => {
    expect(normalizeEnvironment(undefined)).toBe('unknown');
    expect(normalizeEnvironment('')).toBe('unknown');
    expect(resolveBuildInfo({ NEXT_PUBLIC_RELEASE_SHA: REAL_SHA }).environment).toBe('unknown');
  });

  it('passes a supplied environment label through verbatim', () => {
    expect(resolveBuildInfo({ NEXT_PUBLIC_RELEASE_ENV: 'production' }).environment)
      .toBe('production');
    expect(normalizeEnvironment(' preview ')).toBe('preview');
  });
});

describe('module constants', () => {
  it('resolve from the inlined build environment', async () => {
    vi.stubEnv('NEXT_PUBLIC_RELEASE_SHA', REAL_SHA);
    vi.stubEnv('NEXT_PUBLIC_RELEASE_ENV', 'production');
    const mod = await import('./build-info');
    expect(mod.releaseSha).toBe(REAL_SHA);
    expect(mod.releaseShaShort).toBe('1029f03');
    expect(mod.environment).toBe('production');
    expect(mod.releaseShaAttribute).toBe(REAL_SHA);
  });

  it('degrade to unknown — not a fabricated SHA — when the build supplied none', async () => {
    vi.stubEnv('NEXT_PUBLIC_RELEASE_SHA', '');
    vi.stubEnv('NEXT_PUBLIC_RELEASE_ENV', '');
    const mod = await import('./build-info');
    expect(mod.releaseSha).toBeNull();
    expect(mod.releaseShaShort).toBeNull();
    expect(mod.environment).toBe('unknown');
    // The DOM attribute stays present and says "unknown", so an operator can
    // tell "no SHA was supplied" from "this build predates release stamping".
    expect(mod.releaseShaAttribute).toBe('unknown');
  });
});

describe('no local git fallback', () => {
  it('does not read the developer checkout to fill the gap', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const source = readFileSync(resolve('src/lib/build-info.ts'), 'utf8');
    const code = source
      .split('\n')
      .filter((line) => !line.trimStart().startsWith('*') && !line.trimStart().startsWith('//'))
      .join('\n');
    for (const forbidden of ['rev-parse', 'child_process', 'execSync']) {
      expect(code).not.toContain(forbidden);
    }
  });
});
