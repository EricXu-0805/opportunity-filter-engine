#!/usr/bin/env node
/**
 * Vercel "Ignored Build Step" — wired as `ignoreCommand` in vercel.json.
 *
 * EXIT CODES ARE INVERTED, and getting them backwards is the whole risk:
 *   exit 0 => SKIP this build
 *   exit 1 => RUN this build
 *
 * WHY THIS EXISTS
 * Render deploys the backend only after the commit's checks pass
 * (`autoDeployTrigger: checksPass` in render.yaml). Vercel has no equivalent:
 * its Git integration creates a production deployment the moment main is
 * pushed, so a commit whose CI later goes red is already live on the
 * production frontend. This closes as much of that asymmetry as an
 * ignoreCommand honestly can.
 *
 * WHAT IT DOES CLOSE
 * A production deployment for a commit whose required checks are ALREADY
 * conclusive is decided correctly: red => skipped, green => built. That
 * covers manual redeploys, promotions, and any deployment created after CI
 * finished — the cases where a human is most likely to ship known-broken
 * code.
 *
 * WHAT IT CANNOT CLOSE (do not read this file as a complete fix)
 * On a normal push the deployment is created seconds after the push, while
 * CI is still queued: CI on this repo takes ~20-35 minutes (measured over
 * the last eight main pushes). The ignore step is evaluated exactly once,
 * is never re-run when the checks later conclude, and cannot sit and wait
 * for half an hour without occupying a build slot and burning build
 * minutes. So on the common path the checks are PENDING, and this script
 * deliberately fails OPEN (builds) rather than fail closed — a fail-closed
 * default here would silently freeze the production frontend forever, which
 * is a worse outage than the problem being fixed.
 *
 * Full CI-green gating therefore needs one of two things this repository
 * cannot provide from vercel.json:
 *   (a) Vercel-side: turn OFF Git auto-deploy for production (Project
 *       Settings > Git, or `git.deploymentEnabled`) and promote from CI
 *       after checks pass — which requires a VERCEL_TOKEN secret; or
 *   (b) a Vercel-side "wait for CI" setting, which does not exist today.
 * Until one of those lands, this gate is genuinely partial and says so.
 *
 * OFE_VERCEL_CI_WAIT_SECONDS (default 0) opts into real gating at a cost:
 * the step polls for that many seconds waiting for the checks to conclude,
 * holding the build slot. Set it to ~2100 to actually block red pushes.
 *
 * The check query uses the public GitHub REST API unauthenticated (this repo
 * is public); GITHUB_TOKEN is used if present. `gh` is not available in the
 * ignore-step environment, and no token is guaranteed, so every failure mode
 * of the query (rate limit, network, private repo) is treated as "unknown"
 * and falls open with a loud log line — never a silent pass.
 */

import { pathToFileURL } from 'node:url';

// The four CI jobs that gate merges (.github/workflows/ci.yml). Names must
// match the workflow's `name:` values exactly; a renamed job shows up as a
// missing check, which reads as PENDING (falls open) rather than as green.
export const REQUIRED_CHECKS = [
  'Backend (lint + pytest)',
  'Frontend (typecheck + build)',
  'Migrations (Flow B merge + CLI replay)',
  'E2E (Playwright)',
];

// Conclusions that mean "this commit is not shippable".
const RED_CONCLUSIONS = new Set([
  'failure',
  'timed_out',
  'cancelled',
  'action_required',
  'startup_failure',
  'stale',
]);

// GitHub reports a skipped-by-condition job as a pass, not a failure.
const PASS_CONCLUSIONS = new Set(['success', 'neutral', 'skipped']);

/**
 * @param {Array<{name: string, status: string, conclusion: string|null}>} checkRuns
 * @returns {{decision: 'red'|'green'|'pending', reason: string}}
 */
export function evaluateChecks(checkRuns) {
  const latest = new Map();
  for (const run of checkRuns ?? []) {
    if (!REQUIRED_CHECKS.includes(run.name)) continue;
    // A re-run appends a newer check with the same name; last one wins.
    latest.set(run.name, run);
  }

  const red = REQUIRED_CHECKS.filter((name) => {
    const run = latest.get(name);
    return run && run.status === 'completed' && RED_CONCLUSIONS.has(run.conclusion);
  });
  if (red.length > 0) {
    return { decision: 'red', reason: `required checks failed: ${red.join(', ')}` };
  }

  const unfinished = REQUIRED_CHECKS.filter((name) => {
    const run = latest.get(name);
    return !run || run.status !== 'completed' || !PASS_CONCLUSIONS.has(run.conclusion);
  });
  if (unfinished.length > 0) {
    return { decision: 'pending', reason: `still waiting on: ${unfinished.join(', ')}` };
  }

  return { decision: 'green', reason: 'all required checks passed' };
}

async function fetchCheckRuns({ apiBase, owner, repo, sha, token }) {
  const url = `${apiBase}/repos/${owner}/${repo}/commits/${sha}/check-runs?per_page=100`;
  const headers = { Accept: 'application/vnd.github+json', 'User-Agent': 'ofe-vercel-ignore' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(url, { headers });
  if (!response.ok) {
    throw new Error(`GitHub check-runs query returned HTTP ${response.status}`);
  }
  const body = await response.json();
  return Array.isArray(body.check_runs) ? body.check_runs : [];
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// exit(0) = skip, exit(1) = build. Every path logs the reason.
function skip(reason) {
  console.log(`[vercel-ignore] SKIP build — ${reason}`);
  process.exit(0);
}

function build(reason) {
  console.log(`[vercel-ignore] BUILD — ${reason}`);
  process.exit(1);
}

async function main() {
  const env = process.env;
  const vercelEnv = env.VERCEL_ENV || '';

  // Previews are the safe surface and are left exactly as they were: gating
  // them would remove the per-PR deployment reviewers rely on.
  if (vercelEnv !== 'production') {
    build(`${vercelEnv || 'non-production'} deployment — CI gate applies to production only`);
  }

  const owner = env.VERCEL_GIT_REPO_OWNER;
  const repo = env.VERCEL_GIT_REPO_SLUG;
  const sha = env.VERCEL_GIT_COMMIT_SHA;
  if (!owner || !repo || !sha) {
    build('cannot identify the commit (VERCEL_GIT_* unset) — falling open, gate not applied');
  }

  const apiBase = (env.OFE_GITHUB_API_BASE || 'https://api.github.com').replace(/\/+$/, '');
  const token = env.GITHUB_TOKEN || env.GH_TOKEN || '';
  const waitSeconds = Math.max(0, Number.parseInt(env.OFE_VERCEL_CI_WAIT_SECONDS || '0', 10) || 0);
  const pollSeconds = 15;
  const deadline = Date.now() + waitSeconds * 1000;

  let lastReason = 'no check status was retrieved';
  for (;;) {
    try {
      const runs = await fetchCheckRuns({ apiBase, owner, repo, sha, token });
      const { decision, reason } = evaluateChecks(runs);
      lastReason = reason;
      if (decision === 'red') skip(`${reason} for ${sha.slice(0, 7)}`);
      if (decision === 'green') build(`${reason} for ${sha.slice(0, 7)}`);
    } catch (error) {
      // Unknown, not green: logged, and falls open below rather than silently
      // passing as if the checks had been verified.
      lastReason = `check status unavailable (${error.message})`;
      console.log(`[vercel-ignore] ${lastReason}`);
    }

    if (Date.now() + pollSeconds * 1000 > deadline) break;
    await sleep(pollSeconds * 1000);
  }

  build(
    `${lastReason} — the required checks were never observed green, and this step `
    + 'cannot wait out a ~20-35min CI run, so this production build proceeds '
    + 'UNGATED. Raise OFE_VERCEL_CI_WAIT_SECONDS to trade build minutes for real '
    + 'gating, or close it properly by disabling Vercel Git auto-deploy for '
    + 'production and promoting from CI after the checks pass.',
  );
}

// Only run when invoked as a script, so the decision logic stays importable.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
