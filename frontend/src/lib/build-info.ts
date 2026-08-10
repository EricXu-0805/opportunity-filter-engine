/**
 * Which frontend build is being served.
 *
 * The client shipped no build identity at all: `VERCEL_GIT_COMMIT_SHA` was
 * never read, so a page in front of a user could not be traced back to a
 * commit — "is the fix deployed?" was unanswerable except by guessing from
 * behaviour. `next.config.js` now inlines the commit at build time as
 * `NEXT_PUBLIC_RELEASE_SHA` (Vercel's `VERCEL_GIT_COMMIT_SHA`, falling back
 * to an explicit `OFE_RELEASE_SHA`), and this module reads it.
 *
 * Honest-unknown rule, identical to `backend/lib/build_info.py`:
 * unknown is `null`, never a placeholder. A value that is missing, empty, or
 * not shaped like a commit (an unexpanded `$VERCEL_GIT_COMMIT_SHA`, the word
 * "unknown", a branch name) is reported as unknown rather than published as
 * provenance. A fabricated SHA would look like proof and be none.
 *
 * There is deliberately no `git rev-parse` fallback: the value must describe
 * the deployed artifact, and a dev-box checkout says nothing about it.
 */

const SHA_PATTERN = /^[0-9a-f]{7,40}$/i;

export const UNKNOWN_ENVIRONMENT = 'unknown';

const SHORT_SHA_LENGTH = 7;

/** A commit SHA, or `null` when the input is absent or not SHA-shaped. */
export function normalizeSha(raw: string | undefined | null): string | null {
  const value = (raw ?? '').trim();
  return SHA_PATTERN.test(value) ? value.toLowerCase() : null;
}

/** The provided environment label, or `"unknown"`. Never inferred. */
export function normalizeEnvironment(raw: string | undefined | null): string {
  return (raw ?? '').trim() || UNKNOWN_ENVIRONMENT;
}

export interface BuildInfo {
  releaseSha: string | null;
  releaseShaShort: string | null;
  environment: string;
}

/** Pure resolver — exported so the contract is testable without a rebuild. */
export function resolveBuildInfo(
  env: { NEXT_PUBLIC_RELEASE_SHA?: string; NEXT_PUBLIC_RELEASE_ENV?: string },
): BuildInfo {
  const sha = normalizeSha(env.NEXT_PUBLIC_RELEASE_SHA);
  return {
    releaseSha: sha,
    releaseShaShort: sha ? sha.slice(0, SHORT_SHA_LENGTH) : null,
    environment: normalizeEnvironment(env.NEXT_PUBLIC_RELEASE_ENV),
  };
}

const buildInfo = resolveBuildInfo({
  NEXT_PUBLIC_RELEASE_SHA: process.env.NEXT_PUBLIC_RELEASE_SHA,
  NEXT_PUBLIC_RELEASE_ENV: process.env.NEXT_PUBLIC_RELEASE_ENV,
});

export const releaseSha = buildInfo.releaseSha;
export const releaseShaShort = buildInfo.releaseShaShort;
export const environment = buildInfo.environment;

/**
 * What to put in the DOM. `"unknown"` (not an omitted attribute and not a
 * fake SHA) so that an operator reading production HTML can tell "the
 * plumbing works but no SHA was supplied" apart from "this build predates
 * release stamping".
 */
export const releaseShaAttribute = releaseSha ?? UNKNOWN_ENVIRONMENT;
