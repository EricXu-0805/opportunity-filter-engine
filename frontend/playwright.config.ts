import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT ?? 3100);
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8100);
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // One retry in CI (down from 2): still absorbs a single flake, but halves the
  // worst-case time a failing test adds — part of keeping the suite inside the
  // job timeout. Kept serial (workers: 1) so cross-file state stays predictable.
  retries: 1,
  workers: 1,
  // A systemic breakage (e.g. a modal covering the viewport) makes every test
  // eat its full timeout serially and the job hang to its 30m cap — bail after
  // a burst of failures instead so CI reports red in minutes.
  maxFailures: process.env.CI ? 10 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  // Both default to true on CI. `diff` shells out to git and accumulates the
  // whole commit diff into one string, which for a data repo (a batch touches
  // 100+ corpus shards) exceeds V8's max string length and crashes the run
  // before any test executes — "RangeError: Invalid string length". The diff
  // only enriches the HTML report, so keep the cheap commit metadata and drop it.
  captureGitInfo: { commit: true, diff: false },
  globalSetup: './e2e/global-setup.ts',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // Written by e2e/global-setup.ts: marks the onboarding tour as seen so the
    // full-screen first-visit modal doesn't intercept every click.
    storageState: './e2e/.storage-state.json',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 7'] },
    },
  ],
  webServer: [
    {
      command: `python3 -m uvicorn backend.main:app --port ${BACKEND_PORT} --host 127.0.0.1`,
      cwd: '..',
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        OFE_DISABLE_RATE_LIMIT: '1',
      },
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // In CI, serve the pre-built production app (`next start`) — the CI job
      // runs `npm run build` first. `next start` serves already-compiled routes,
      // avoiding the per-route on-demand compilation of `next dev` that pushed
      // the suite past the job timeout. Locally keep `next dev` for HMR.
      // NOTE: the build must run with BACKEND_URL=http://127.0.0.1:8100 —
      // rewrites are baked into the build (see ci.yml), or /api/* proxies to
      // the live production backend instead of the local uvicorn above.
      command: process.env.CI
        ? `npm run start -- --port ${PORT} --hostname 127.0.0.1`
        : `npm run dev -- --port ${PORT} --hostname 127.0.0.1`,
      url: BASE_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        BACKEND_URL: `http://127.0.0.1:${BACKEND_PORT}`,
      },
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
});
