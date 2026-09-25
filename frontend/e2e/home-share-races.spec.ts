import { test, expect, type Page, type APIRequestContext, type TestInfo } from '@playwright/test';
import { attachProfileReadDiagnostics } from './profile-read-diagnostics';
import type { ProfileData } from '../src/lib/types';

// No profile or identity is injected into localStorage. Anonymous auth, profile
// GET and CAS all use the actual SDK + loopback server. Gates delay real HTTP
// responses. These controlled windows do not identify the historical one-off
// share-url failure unless the corresponding production behavior fails here.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const PROFILE_ROUTE = '**/rest/v1/profiles?**';
const isProfile = (url: string) => new URL(url).pathname === '/rest/v1/profiles';
const isCas = (url: string) => new URL(url).pathname === '/rest/v1/rpc/commit_profile_patch_cas';
const isSignup = (url: string) => new URL(url).pathname === '/auth/v1/signup';
const requireLoopback = (url: string) => expect(new URL(url).origin, 'SDK test traffic must stay on the loopback stub').toBe(STUB.origin);
interface Fields { college: string; major: string; grade: string; interests: string }
const FIRST: Fields = { college: 'Grainger College of Engineering', major: 'Computer Engineering', grade: 'Junior', interests: 'Before identity: calibration 王' };
const FIRST_FINAL: Fields = { ...FIRST, interests: 'After identity but before profile receipt: final calibration detail 王' };
const ONLINE_FINAL: Fields = { ...FIRST, grade: 'Senior', interests: 'Latest unsaved reconnect-check wording 王 — keep the complete tail.' };
const initialProfile = (): ProfileData => ({ name: 'Synthetic share-race student', institution: 'UIUC', home_school: 'uiuc',
  college: FIRST.college, major: 'Computer Science', grade: 'Sophomore', research_interests: 'Saved initial interest',
  is_international: false, skills: [{ name: 'Python', level: 'beginner' }], coursework: ['ECE 220'], seeking_types: ['research'] });
interface Session { access_token: string; user: { id: string } }
interface Observation { phase: string; fields: unknown; decoded?: unknown }
function deferred() {
  let release!: () => void;
  const promise = new Promise<void>(resolve => { release = resolve; });
  return { promise, release };
}
async function fields(page: Page) {
  return page.evaluate(() => ({
    college: (document.querySelector('#college') as HTMLSelectElement | null)?.value ?? null,
    major: (document.querySelector('#major') as HTMLSelectElement | null)?.value ?? null,
    grade: (document.querySelector('#grade') as HTMLSelectElement | null)?.value ?? null,
    interests: (document.querySelector('#research_interests') as HTMLTextAreaElement | null)?.value ?? null,
  }));
}
async function expectFields(page: Page, expected: Fields) {
  await expect(page.locator('#college')).toHaveValue(expected.college);
  await expect(page.locator('#major')).toHaveValue(expected.major);
  await expect(page.locator('#grade')).toHaveValue(expected.grade);
  await expect(page.locator('#research_interests')).toHaveValue(expected.interests);
}
async function fillFields(page: Page, value: Fields) {
  await page.locator('#college').selectOption(value.college);
  await page.locator('#major').selectOption(value.major);
  await page.locator('#grade').selectOption(value.grade);
  await page.locator('#research_interests').fill(value.interests);
}
function traffic(page: Page) {
  const result = { reads: 0, writes: 0 };
  page.on('request', request => {
    if (isProfile(request.url()) && request.method() === 'GET') result.reads += 1;
    if ((isProfile(request.url()) || isCas(request.url())) && ['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method())) result.writes += 1;
  });
  return result;
}
function decodedShare(url: string) {
  const parsed = new URL(url);
  expect(parsed.hostname).toBe('127.0.0.1'); expect(parsed.pathname).toBe('/');
  const encoded = parsed.searchParams.get('share'); expect(encoded).not.toBeNull();
  return JSON.parse(Buffer.from(encoded!, 'base64url').toString('utf8')) as Record<string, unknown>;
}
async function copyShare(page: Page, expected: Fields, observations: Observation[]) {
  await expectFields(page, expected);
  observations.push({ phase: 'source-before-copy', fields: await fields(page) });
  await page.getByRole('button', { name: 'Share profile', exact: true }).click();
  await expect(page.getByText('Copied!', { exact: true })).toBeVisible();
  const url = await page.evaluate(() => navigator.clipboard.readText());
  const decoded = decodedShare(url);
  observations.push({ phase: 'source-after-copy', fields: await fields(page), decoded });
  expect(decoded).toMatchObject({ v: 1, ...expected });
  return url;
}
async function importShared(source: Page, url: string, expected: Fields, observations: Observation[]) {
  const victim = await source.context().newPage();
  const reads = traffic(victim);
  await victim.goto(url);
  await expect(victim.getByText(/Loaded a shared profile/i)).toBeVisible();
  observations.push({ phase: 'victim-after-banner', fields: await fields(victim), decoded: decodedShare(url) });
  await expectFields(victim, expected);
  expect(reads.reads, 'viewing a share must not hydrate the receiver’s own profile over it').toBe(0);
  expect(reads.writes, 'viewing a share does not save it').toBe(0);
  return victim;
}
async function attachFailure(info: TestInfo, source: Page, observations: Observation[], completed: boolean) {
  if (completed) return;
  observations.push({ phase: 'source-at-failure', fields: await fields(source).catch(() => ({ unavailable: true })) });
  await info.attach('home-share-race-observations', { body: JSON.stringify(observations, null, 2), contentType: 'application/json' });
  for (const [index, page] of source.context().pages().entries()) await attachProfileReadDiagnostics(page, info, `share-race-${index}`);
}
async function commit(request: APIRequestContext, session: Session, value: ProfileData) {
  expect(STUB.hostname).toBe('127.0.0.1');
  const response = await request.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
    headers: { Authorization: `Bearer ${session.access_token}` },
    data: { p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: value },
  });
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ status: 'applied', revision: 1, profile: value });
}

test.beforeEach(async ({ context }) => {
  for (const pattern of ['**/auth/v1/**', PROFILE_ROUTE, '**/rest/v1/rpc/commit_profile_patch_cas']) {
    await context.route(pattern, route => { requireLoopback(route.request().url()); return route.continue(); });
  }
});

test.describe('Controlled Home share races', () => {
  test('keeps four first-visit inputs through genuine held auth and profile reads, then shares the final form', async ({ page, context }, info) => {
    const authGate = deferred(), readGate = deferred(), authDone = deferred(), readDone = deferred();
    const observations: Observation[] = [];
    const requests = traffic(page);
    let authHeld = false, readHeld = false, completed = false;
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.route('**/auth/v1/signup', async route => {
      requireLoopback(route.request().url());
      if (authHeld) { await route.continue(); return; }
      try {
        const response = await route.fetch({ maxRetries: 0 });
        expect(response.status()).toBe(200);
        expect((await response.json()).user.id).toBeTruthy();
        authHeld = true; await authGate.promise; await route.fulfill({ response });
      } finally { authDone.release(); }
    });
    await page.route(PROFILE_ROUTE, async route => {
      requireLoopback(route.request().url());
      if (readHeld) { await route.continue(); return; }
      try {
        const response = await route.fetch({ maxRetries: 0 });
        expect(response.status()).toBe(200); expect(await response.json()).toEqual([]);
        readHeld = true; await readGate.promise; await route.fulfill({ response });
      } finally { readDone.release(); }
    });
    try {
      await page.goto('/');
      await expect.poll(() => authHeld, 'the actual anonymous signup response is held').toBe(true);
      await fillFields(page, FIRST); await expectFields(page, FIRST);
      observations.push({ phase: 'four-fields-before-auth-receipt', fields: await fields(page) });
      await expect(page.getByTestId('generate-matches')).toBeDisabled();
      expect(requests.reads).toBe(0); expect(requests.writes).toBe(0);
      authGate.release(); await authDone.promise;
      await expect.poll(() => readHeld, 'the first genuine profile GET must reach the loopback server').toBe(true);
      await expectFields(page, FIRST);
      await page.locator('#research_interests').fill(FIRST_FINAL.interests);
      observations.push({ phase: 'final-edit-before-profile-receipt', fields: await fields(page) });
      expect(requests.writes).toBe(0);
      const read = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
      readGate.release(); expect(await (await read).json()).toEqual([]); await readDone.promise;
      await expect(page.getByTestId('hydration-note')).toHaveCount(0);
      await expect(page.getByTestId('generate-matches')).toBeEnabled();
      const url = await copyShare(page, FIRST_FINAL, observations);
      const victim = await importShared(page, url, FIRST_FINAL, observations);
      await victim.locator('#research_interests').scrollIntoViewIfNeeded();
      await victim.screenshot({ path: info.outputPath('first-visit-share-retains-four-fields.png') });
      completed = true;
    } finally {
      authGate.release(); readGate.release();
      await attachFailure(info, page, observations, completed);
    }
  });

  test('a genuine offline-to-online check keeps pending edits and shares the last edit after the held read', async ({ page, context, request }, info) => {
    const gate = deferred(), readDone = deferred(), observations: Observation[] = [];
    const requests = traffic(page);
    let held = false, completed = false;
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.clock.install();
    try {
      // Let this browser sign itself in. The independent CAS creates a real
      // cloud row; reload then obtains it through the ordinary SDK read path.
      const auth = page.waitForResponse(response => isSignup(response.url()) && response.status() === 200);
      const initialRead = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
      await page.goto('/');
      const session = await (await auth).json() as Session;
      expect(await (await initialRead).json()).toEqual([]);
      await expect(page.getByTestId('hydration-note')).toHaveCount(0);
      await commit(request, session, initialProfile());
      const hydrated = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
      await page.reload();
      expect(await (await hydrated).json()).toMatchObject([{ revision: 1, profile_data: initialProfile() }]);
      await expect(page.locator('#student_name')).toHaveValue(initialProfile().name!);
      await expect(page.getByTestId('generate-matches')).toBeEnabled();
      await expect(page.getByTestId('home-profile-refresh-status')).toHaveCount(0);
      // Pause only elapsed timers so the local edit is genuinely pending when
      // the connection returns. Real network responses and SDK events still run.
      await page.clock.pauseAt(await page.evaluate(() => Date.now()) + 100);
      // Chromium's test context did not reliably lose native focus even with
      // focus emulation disabled. This case deliberately covers the actual
      // browser offline/online transition, not focus or a dispatched DOM event.
      await page.evaluate(() => {
        Object.assign(window, { shareRaceOnlineEvents: 0 });
        window.addEventListener('online', () => {
          (window as typeof window & { shareRaceOnlineEvents: number }).shareRaceOnlineEvents += 1;
        });
      });
      const writesBefore = requests.writes;
      await fillFields(page, { ...FIRST, interests: 'Pending before connection returns' });
      await expectFields(page, { ...FIRST, interests: 'Pending before connection returns' });
      expect(requests.writes).toBe(writesBefore);
      await page.route(PROFILE_ROUTE, async route => {
        requireLoopback(route.request().url());
        if (held) { await route.continue(); return; }
        try {
          const response = await route.fetch({ maxRetries: 0 });
          expect(response.status()).toBe(200);
          expect(await response.json()).toMatchObject([{ revision: 1, profile_data: initialProfile() }]);
          held = true; await gate.promise; await route.fulfill({ response });
        } finally { readDone.release(); }
      });
      await context.setOffline(true);
      await expect.poll(() => page.evaluate(() => navigator.onLine), 'the browser must actually enter its offline state').toBe(false);
      const onlineBefore = await page.evaluate(() => (window as typeof window & { shareRaceOnlineEvents: number }).shareRaceOnlineEvents);
      const readsBefore = requests.reads;
      await context.setOffline(false);
      await expect.poll(() => page.evaluate(() => navigator.onLine), 'the browser connection must actually return').toBe(true);
      await expect.poll(() => page.evaluate(() => (window as typeof window & { shareRaceOnlineEvents: number }).shareRaceOnlineEvents),
        'a genuine browser online event, not a synthetic dispatch').toBe(onlineBefore + 1);
      await expect.poll(() => held, 'the online event must start the genuine profile GET').toBe(true);
      expect(requests.reads).toBe(readsBefore + 1);
      await expect(page.getByTestId('home-profile-refresh-status')).toHaveText('Checking for profile updates…');
      await page.locator('#grade').selectOption(ONLINE_FINAL.grade);
      await page.locator('#research_interests').fill(ONLINE_FINAL.interests);
      observations.push({ phase: 'latest-pending-input-while-reconnect-read-held', fields: await fields(page) });
      expect(requests.writes).toBe(writesBefore);
      const receipt = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
      gate.release(); expect(await (await receipt).json()).toMatchObject([{ revision: 1 }]); await readDone.promise;
      await expect(page.getByTestId('home-profile-refresh-status')).toHaveCount(0);
      const url = await copyShare(page, ONLINE_FINAL, observations);
      expect(requests.writes, 'sharing must use the live form without requiring its pending autosave').toBe(writesBefore);
      await page.clock.resume();
      const victim = await importShared(page, url, ONLINE_FINAL, observations);
      await victim.locator('#research_interests').scrollIntoViewIfNeeded();
      await victim.screenshot({ path: info.outputPath('online-recovery-share-retains-latest-input.png') });
      completed = true;
    } finally {
      gate.release(); await attachFailure(info, page, observations, completed);
      await context.setOffline(false);
    }
  });
});
