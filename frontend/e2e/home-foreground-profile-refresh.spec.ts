import { test, expect, request as apiRequest, type APIRequestContext, type Page, type Request } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { encodeProfile } from '../src/lib/profile-share';
import type { ProfileData, ResumeFact } from '../src/lib/types';
import { attachProfileReadDiagnostics } from './profile-read-diagnostics';

// Production Home/SDK with genuine loopback rows and independent CAS. Only
// response delivery/failure is controlled. The clock advances the shipped 60s
// timer; the test never dispatches focus, online or storage events.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const PROFILE_ROUTE = '**/rest/v1/profiles?**';
const NAME = 'Home foreground student 王';
const SOURCE = 'Complete source 王\nI assisted with instrumentation; I did not lead.\nThe final source line remains intact.';
const EXPERIENCE = 'Compared instrument readings and documented uncertainty; I assisted and did not lead.';
const INTEREST = 'My current interest in calibration, including the final detail 王';
const FAILED = 'Could not check for profile updates. Your entries are kept; saving and matching are paused.';
const DELETED = 'Your saved profile was deleted elsewhere. Your entries are kept; saving and matching are paused.';
const fact = (id: string, value: string): ResumeFact => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
const isProfile = (url: string) => new URL(url).pathname === '/rest/v1/profiles';
const isCas = (url: string) => new URL(url).pathname === '/rest/v1/rpc/commit_profile_patch_cas';
const freshStatus = (page: Page) => page.getByTestId('home-profile-refresh-status');
function profile(): ProfileData {
  return {
    name: NAME, institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
    major: 'Computer Science', grade: 'Sophomore', is_international: false,
    research_interests: 'instrumentation', skills: [{ name: 'Python', level: 'beginner' }],
    coursework: ['ECE 220'], seeking_types: ['research'], resume_text: SOURCE,
    experience_entries: [{ id: 'home-periodic-experience', revision: 1, status: 'confirmed', text: EXPERIENCE, source: { kind: 'manual' } }],
    resume_master: {
      version: 1, id: 'home-periodic-master', revision: 1, source_signature: null,
      basics: { name: fact('name', NAME), links: [] },
      education: [{ id: 'education', school: fact('school', 'Complete Example University'), degree: fact('degree', 'Bachelor of Science'), details: [] }],
      activities: [{ id: 'project', kind: 'project', title: fact('title', 'Instrument comparison project'), details: [{ id: 'home-periodic-experience', revision: 1 }] }],
      publications: [], skills: [fact('skill', 'Beginner Python')], other_sections: [],
      section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [],
    },
  };
}
interface Owner { http: APIRequestContext; uid: string; token: string }
interface Row { profile_data: ProfileData; revision: number }
function profileUrl(owner: Owner) {
  const url = new URL('/rest/v1/profiles', STUB);
  url.searchParams.set('select', 'profile_data,revision'); url.searchParams.set('id', `eq.${owner.uid}`);
  return url.href;
}
const headers = (owner: Owner) => ({ Authorization: `Bearer ${owner.token}` });
async function rows(owner: Owner): Promise<Row[]> {
  const response = await owner.http.get(profileUrl(owner), { headers: headers(owner) });
  expect(response.status()).toBe(200); return response.json();
}
async function commit(owner: Owner, patch: Partial<ProfileData>, expectedRevision: number) {
  const response = await owner.http.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
    headers: headers(owner), data: { p_expected_device_id: owner.uid, p_expected_revision: expectedRevision, p_patch: patch },
  });
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ status: 'applied', revision: expectedRevision + 1, profile: patch });
}
async function seed(page: Page): Promise<Owner> {
  expect(STUB.hostname).toBe('127.0.0.1');
  await page.clock.install();
  const http = await apiRequest.newContext();
  try {
    const response = await http.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
    expect(response.status()).toBe(200);
    const session = await response.json();
    const owner = { http, uid: session.user.id as string, token: session.access_token as string };
    await commit(owner, profile(), 0);
    await page.addInitScript(({ session, locale }) => {
      // Auth only; the SDK must obtain the complete row through a real read.
      if (!localStorage.getItem('home-foreground-seeded')) {
        localStorage.setItem('ofe_auth', JSON.stringify(session));
        localStorage.setItem(locale, 'en'); localStorage.setItem('home-foreground-seeded', '1');
      }
    }, { session, locale: STORAGE_KEYS.LOCALE });
    const read = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
    await page.goto('/');
    expect(await (await read).json()).toMatchObject([{ revision: 1, profile_data: profile() }]);
    await expect(page.locator('#student_name')).toHaveValue(NAME);
    await expect(page.getByTestId('generate-matches')).toBeEnabled();
    await expect(page.getByTestId('hydration-note')).toHaveCount(0);
    return owner;
  } catch (error) { await http.dispose(); throw error; }
}
function monitor(page: Page) {
  const state = { reads: 0, writes: [] as Request[] };
  page.on('request', request => {
    if (isProfile(request.url()) && request.method() === 'GET') state.reads += 1;
    if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method()) && (isProfile(request.url()) || isCas(request.url()))) state.writes.push(request);
  });
  return state;
}
async function observeTriggers(page: Page) {
  expect(await page.evaluate(() => document.visibilityState)).toBe('visible');
  await page.evaluate(() => {
    const state = { focus: 0, online: 0, visibilitychange: 0, initialLoading: false };
    Object.assign(window, { homeForegroundTriggers: state });
    window.addEventListener('focus', () => { state.focus += 1; });
    window.addEventListener('online', () => { state.online += 1; });
    document.addEventListener('visibilitychange', () => { state.visibilitychange += 1; });
    new MutationObserver(() => {
      if (document.querySelector('[data-testid="hydration-note"]')) state.initialLoading = true;
    }).observe(document.body, { childList: true, subtree: true });
  });
}
async function expectNoTriggers(page: Page) {
  expect(await page.evaluate(() => (window as typeof window & { homeForegroundTriggers: unknown }).homeForegroundTriggers))
    .toEqual({ focus: 0, online: 0, visibilitychange: 0, initialLoading: false });
}
async function period(page: Page, status = 200) {
  const response = page.waitForResponse(response => isProfile(response.url()) && response.status() === status);
  await page.clock.fastForward(60_001);
  return response;
}
function deferred() {
  let release!: () => void;
  const promise = new Promise<void>(resolve => { release = resolve; });
  return { promise, release };
}
async function expectFields(page: Page, value: ProfileData) {
  await expect(page.locator('#student_name')).toHaveValue(value.name!);
  await expect(page.locator('#college')).toHaveValue(value.college);
  await expect(page.locator('#major')).toHaveValue(value.major);
  await expect(page.locator('#grade')).toHaveValue(value.grade);
  await expect(page.locator('#research_interests')).toHaveValue(value.research_interests);
}
async function openMaster(page: Page) {
  await page.locator('#resume-master').getByText('Open full résumé editor', { exact: true }).click();
  await expect(page.locator('#resume-master').getByRole('textbox', { name: 'Full name', exact: true })).toHaveValue(NAME);
}
async function inputValues(page: Page) {
  return page.locator('main input:not([type="file"]), main select, main textarea').evaluateAll(elements => elements.map(element => {
    const input = element as HTMLInputElement;
    return { id: input.id, label: input.getAttribute('aria-label'), type: input.type, value: input.value,
      checked: input.type === 'checkbox' || input.type === 'radio' ? input.checked : undefined };
  }));
}
test.afterEach(async ({ context }, info) => {
  if (info.status !== info.expectedStatus) for (const [index, page] of context.pages().entries()) {
    await attachProfileReadDiagnostics(page, info, `home-foreground-${index}`);
  }
});

test.describe('Home foreground profile refresh', () => {
  test('does not save an unchanged read and accepts a remote major after the previous local major was saved', async ({ page }, info) => {
    const traffic = monitor(page), owner = await seed(page);
    try {
      const saved = page.waitForResponse(response => isCas(response.url()) && response.status() === 200);
      await page.locator('#major').selectOption('Computer Engineering');
      await page.clock.fastForward(1_601);
      expect(await (await saved).json()).toMatchObject({ status: 'applied', revision: 2, profile: { major: 'Computer Engineering' } });
      await expect(page.locator('#profile-save-status')).toHaveText('Profile saved');
      await page.clock.fastForward(2_501); // Settle the existing save badge before comparing a read.
      const beforeStatus = await page.locator('#profile-save-status').textContent();
      expect(traffic.writes).toHaveLength(1);
      const readsBefore = traffic.reads, node = await page.locator('#research_interests').elementHandle();
      await observeTriggers(page);
      const unchanged = await period(page);
      expect(await unchanged.json()).toMatchObject([{ revision: 2, profile_data: { major: 'Computer Engineering' } }]);
      await expect(freshStatus(page)).toHaveCount(0);
      await expect(page.locator('#profile-save-status')).toHaveText(beforeStatus ?? '');
      await expect(page.getByTestId('generate-matches')).toBeEnabled();
      expect(await node!.evaluate(element => element.isConnected)).toBe(true);
      expect(traffic.writes).toHaveLength(1); expect(traffic.reads).toBe(readsBefore + 1);
      await commit(owner, { major: 'Electrical Engineering' }, 2);
      const changed = await period(page);
      expect(await changed.json()).toMatchObject([{ revision: 3, profile_data: { major: 'Electrical Engineering' } }]);
      await expectFields(page, { ...profile(), major: 'Electrical Engineering' });
      await expect(freshStatus(page)).toHaveCount(0);
      await page.clock.fastForward(2_001);
      expect(traffic.writes, 'historical dirty keys must not overwrite or re-save the new cloud major').toHaveLength(1);
      expect(traffic.reads).toBe(readsBefore + 2);
      expect(await rows(owner)).toMatchObject([{ revision: 3, profile_data: { ...profile(), major: 'Electrical Engineering' } }]);
      await expectNoTriggers(page);
      await page.locator('#major').scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('home-remote-major-after-local-save.png') });
    } finally { await owner.http.dispose(); }
  });

  test('merges an unrelated remote field with typing during a held read and sends one current autosave', async ({ page }, info) => {
    const traffic = monitor(page), owner = await seed(page), gate = deferred(), settled = deferred();
    let held = false;
    try {
      await commit(owner, { grade: 'Junior' }, 1);
      await page.route(PROFILE_ROUTE, async route => {
        if (held) { await route.continue(); return; }
        try {
          const response = await route.fetch({ maxRetries: 0 });
          expect(response.status()).toBe(200);
          expect(await response.json()).toMatchObject([{ revision: 2, profile_data: { grade: 'Junior' } }]);
          held = true; await gate.promise; await route.fulfill({ response });
        } finally { settled.release(); }
      });
      await observeTriggers(page); const readsBefore = traffic.reads;
      await page.clock.fastForward(60_001);
      await expect.poll(() => held).toBe(true);
      await expect(freshStatus(page)).toHaveText('Checking for profile updates…');
      await expect(page.getByTestId('generate-matches')).toBeDisabled();
      await expect(page.getByTestId('hydration-note')).toHaveCount(0);
      await page.locator('#research_interests').fill('First unfinished thought');
      await page.clock.fastForward(2_001);
      expect(traffic.writes, 'an unresolved read pauses even an elapsed autosave debounce').toHaveLength(0);
      // Release before the last edit has had the normal 400ms journal burst.
      // Both that final edit and the earlier durable intent must survive.
      await page.locator('#research_interests').fill(INTEREST);
      const read = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
      const saved = page.waitForResponse(async response => isCas(response.url())
        && response.status() === 200 && (await response.json()).status === 'applied');
      gate.release(); await read; await settled.promise;
      await expectFields(page, { ...profile(), grade: 'Junior', research_interests: INTEREST });
      await expect(freshStatus(page)).toHaveCount(0);
      await page.clock.fastForward(1_601);
      expect(await (await saved).json()).toMatchObject({ status: 'applied', revision: 3, profile: { grade: 'Junior', research_interests: INTEREST } });
      await expect(page.locator('#profile-save-status')).toHaveText('Profile saved');
      await page.clock.fastForward(2_001);
      expect(traffic.reads).toBe(readsBefore + 1);
      const receipts = await Promise.all(traffic.writes.map(async request => {
        const response = await request.response(); expect(response?.status()).toBe(200);
        return response!.json();
      }));
      // A recorded edit may still carry revision 1; one conflict followed by
      // revision-2 success is legitimate. No hidden repeat or second applied
      // save is accepted, and every attempt must carry the final typed value.
      expect([['applied'], ['conflict', 'applied']]).toContainEqual(receipts.map(receipt => receipt.status));
      for (const [index, request] of traffic.writes.entries()) {
        expect(request.postDataJSON()).toMatchObject({ p_expected_revision: receipts[index].status === 'conflict' ? 1 : 2,
          p_patch: { research_interests: INTEREST } });
        expect(Object.keys(request.postDataJSON().p_patch)).toEqual(['research_interests']);
      }
      expect(receipts.at(-1)).toMatchObject({ status: 'applied', revision: 3, profile: { grade: 'Junior', research_interests: INTEREST } });
      expect(await rows(owner)).toMatchObject([{ revision: 3, profile_data: { ...profile(), grade: 'Junior', research_interests: INTEREST } }]);
      await expectNoTriggers(page);
      await page.locator('#research_interests').scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('home-held-read-preserves-latest-typing.png') });
    } finally { gate.release(); await owner.http.dispose(); }
  });

  test('keeps every visible input after remote deletion without recreating the saved profile', async ({ page }, info) => {
    const traffic = monitor(page), owner = await seed(page);
    try {
      await openMaster(page);
      const before = await inputValues(page); expect(before.length).toBeGreaterThan(10);
      await observeTriggers(page); const readsBefore = traffic.reads;
      expect((await owner.http.delete(profileUrl(owner), { headers: headers(owner) })).status()).toBe(204);
      const deleted = await period(page); expect(await deleted.json()).toEqual([]);
      await expect(freshStatus(page)).toContainText(DELETED);
      expect(await inputValues(page)).toEqual(before);
      await expectFields(page, profile());
      await expect(page.getByTestId('generate-matches')).toBeDisabled();
      await expect(page.getByTestId('retry-profile-refresh')).toHaveText('Check again');
      await page.clock.fastForward(2_001);
      expect(traffic.writes).toHaveLength(0); expect(traffic.reads).toBe(readsBefore + 1);
      expect(await rows(owner)).toEqual([]);
      // Typing while absence is known must not implicitly recreate the row.
      await page.locator('#research_interests').fill(INTEREST);
      await page.clock.fastForward(2_001);
      await expect(page.locator('#research_interests')).toHaveValue(INTEREST);
      const retry = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
      await page.getByTestId('retry-profile-refresh').click(); expect(await (await retry).json()).toEqual([]);
      await expect(freshStatus(page)).toContainText(DELETED);
      await page.clock.fastForward(2_001);
      expect(traffic.writes).toHaveLength(0); expect(await rows(owner)).toEqual([]);
      await expect(page.locator('#resume-master').getByRole('textbox', { name: 'Full name', exact: true })).toHaveValue(NAME);
      await expectNoTriggers(page);
      await freshStatus(page).scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('home-deleted-profile-keeps-input.png') });
    } finally { await owner.http.dispose(); }
  });

  test('keeps the form on a failed periodic read, retries the true cloud row and leaves a shared draft unpolled', async ({ page }, info) => {
    const traffic = monitor(page), owner = await seed(page);
    let fail = true;
    try {
      await observeTriggers(page); const readsBefore = traffic.reads;
      await page.route(PROFILE_ROUTE, route => fail
        ? route.fulfill({ status: 403, json: { message: 'Controlled loopback read denial' } }) : route.continue());
      const failed = await period(page, 403); expect(failed.status()).toBe(403);
      await expect(freshStatus(page)).toContainText(FAILED);
      await expectFields(page, profile());
      await expect(page.getByTestId('generate-matches')).toBeDisabled();
      await page.clock.fastForward(2_001);
      expect(traffic.writes).toHaveLength(0);
      expect(await rows(owner)).toMatchObject([{ revision: 1, profile_data: profile() }]);
      await freshStatus(page).scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath('home-read-failure-preserves-input.png') });
      await commit(owner, { grade: 'Junior' }, 1); fail = false;
      const recovered = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
      await page.getByRole('button', { name: 'Check again', exact: true }).click();
      expect(await (await recovered).json()).toMatchObject([{ revision: 2, profile_data: { grade: 'Junior' } }]);
      await expectFields(page, { ...profile(), grade: 'Junior' });
      await expect(freshStatus(page)).toHaveCount(0);
      await expect(page.getByTestId('generate-matches')).toBeEnabled();
      await page.clock.fastForward(2_001);
      expect(traffic.writes).toHaveLength(0); expect(traffic.reads).toBe(readsBefore + 2);
      await expectNoTriggers(page);

      const shared = { ...profile(), major: 'Mechanical Engineering', research_interests: 'Shared research draft only' };
      const shareReads = traffic.reads;
      await page.goto(`/?share=${encodeProfile(shared)}`);
      await expect(page.getByText('Loaded a shared profile. Review & tweak before generating matches — your saved profile is untouched until you click generate.', { exact: true })).toBeVisible();
      await expect(page.locator('#major')).toHaveValue(shared.major);
      await expect(page.locator('#research_interests')).toHaveValue(shared.research_interests);
      await expect(page.getByTestId('hydration-note')).toHaveCount(0);
      expect(traffic.reads, 'opening a shared draft must not read the visitor’s saved profile').toBe(shareReads);
      await observeTriggers(page);
      await page.clock.fastForward(120_001);
      expect(traffic.reads, 'a shared draft must not periodically load the visitor’s own row over itself').toBe(shareReads);
      expect(traffic.writes).toHaveLength(0);
      await expect(page.locator('#major')).toHaveValue(shared.major);
      await expect(page.locator('#research_interests')).toHaveValue(shared.research_interests);
      expect(await rows(owner)).toMatchObject([{ revision: 2, profile_data: { ...profile(), grade: 'Junior' } }]);
      await expectNoTriggers(page);
    } finally { await owner.http.dispose(); }
  });
});
