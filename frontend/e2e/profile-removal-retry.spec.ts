import { createHash } from 'node:crypto';
import { test, expect, request as apiRequest, type APIRequestContext, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { ProfileData, ResumeFact } from '../src/lib/types';
import { attachProfileReadDiagnostics } from './profile-read-diagnostics';

// Real Home + SDK + coordinator. Only local Storage writes and delivery of the
// loopback CAS response are controlled; no app state/callback is substituted.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const SOURCE = 'I assisted with sensor calibration; I did not lead the team.\nComplete last line 王.';
const fact = (id: string, value: string): ResumeFact => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
const MANUAL = { id: 'independent-experience', revision: 2, status: 'confirmed',
  text: 'I documented measurement uncertainty independently.', source: { kind: 'manual' } } as const;
function profile(): ProfileData {
  return {
    name: 'Removal retry student 王', institution: 'UIUC', home_school: 'uiuc',
    college: 'Grainger College of Engineering', major: 'Computer Engineering', grade: 'Sophomore',
    is_international: false, research_interests: 'Keep this independent interest',
    skills: [{ name: 'Python', level: 'beginner', confirmed: true }], seeking_types: ['research'],
    resume_text: SOURCE, coursework: ['ECE 220'],
    experience_entries: [{ id: 'source-experience', revision: 1, status: 'confirmed', text: SOURCE,
      source: { kind: 'resume', signature: createHash('sha256').update(SOURCE).digest('hex'), quote: SOURCE, start: 0, end: [...SOURCE].length } }, MANUAL],
    resume_master: { version: 1, id: 'removal-retry-master', revision: 1, source_signature: null,
      basics: { name: fact('manual-name', 'Removal retry student 王'), links: [] }, education: [],
      activities: [{ id: 'independent-project', kind: 'project', title: fact('manual-title', 'Independent measurements'), details: [{ id: MANUAL.id, revision: MANUAL.revision }] }],
      publications: [], skills: [], other_sections: [], section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [] },
  };
}
interface Owner { http: APIRequestContext; uid: string; token: string }
interface CasBody { p_expected_device_id: string; p_expected_revision: number; p_patch: Record<string, unknown> }
interface Fault { blocked: boolean; attempts: number; restore: () => void }
type FaultWindow = Window & { removalWriteFault?: Fault };
function deferred() { let release!: () => void; const promise = new Promise<void>(resolve => { release = resolve; }); return { promise, release }; }
const isCas = (url: string) => new URL(url).pathname === '/rest/v1/rpc/commit_profile_patch_cas';
async function rows(owner: Owner) {
  const url = new URL('/rest/v1/profiles', STUB);
  url.searchParams.set('select', 'profile_data,revision'); url.searchParams.set('id', `eq.${owner.uid}`);
  const response = await owner.http.get(url.href, { headers: { Authorization: `Bearer ${owner.token}` } });
  expect(response.status()).toBe(200); return response.json();
}
async function mirror(page: Page) {
  return page.evaluate(keys => {
    const owner = JSON.parse(localStorage.getItem(keys.LOCAL_IDENTITY_OWNER)!);
    const prefix = owner.generation === 0 ? '' : `ofe_g${owner.generation}~`;
    return { owner, profile: JSON.parse(localStorage.getItem(prefix + keys.PROFILE)!),
      envelope: JSON.parse(localStorage.getItem(prefix + keys.PROFILE_SYNC)!) };
  }, STORAGE_KEYS);
}
async function seed(page: Page): Promise<Owner> {
  expect(STUB.hostname).toBe('127.0.0.1');
  await page.clock.install();
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
    expect(signup.status()).toBe(200);
    const session = await signup.json();
    const owner = { http, uid: session.user.id as string, token: session.access_token as string };
    const saved = await http.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
      headers: { Authorization: `Bearer ${owner.token}` },
      data: { p_expected_device_id: owner.uid, p_expected_revision: 0, p_patch: profile() },
    });
    expect(saved.status()).toBe(200); expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1 });
    await page.addInitScript(({ session, locale }) => {
      if (!localStorage.getItem('removal-retry-seeded')) {
        localStorage.setItem('ofe_auth', JSON.stringify(session));
        localStorage.setItem(locale, 'en'); localStorage.setItem('removal-retry-seeded', '1');
      }
    }, { session, locale: STORAGE_KEYS.LOCALE });
    const loaded = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/profiles' && response.status() === 200);
    await page.goto('/');
    expect(await (await loaded).json()).toMatchObject([{ revision: 1, profile_data: profile() }]);
    await expect(page.locator('#student_name')).toHaveValue(profile().name!);
    await expect(page.getByTestId('generate-matches')).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Remove file', exact: true })).toBeVisible();
    return owner;
  } catch (error) { await http.dispose(); throw error; }
}

test('removal retries stage locally, preserve the exact source bundle through a held failure, and save once', async ({ page }, info) => {
  let phase = 'seed';
  const owner = await seed(page), first = deferred(), second = deferred();
  const attempts: CasBody[] = [];
  const patch = { resume_text: '', coursework: [], experience_entries: [MANUAL], resume_master: profile().resume_master };
  const savedStatus = page.locator('#profile-save-status');
  try {
    await page.route('**/rest/v1/rpc/commit_profile_patch_cas', async route => {
      expect(new URL(route.request().url()).origin).toBe(STUB.origin);
      const body = route.request().postDataJSON() as CasBody;
      attempts.push(body);
      if (attempts.length === 1) {
        await first.promise;
        await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: 'Controlled loopback transport failure' }) });
      } else if (attempts.length === 2) {
        await second.promise;
        await route.continue(); // The real loopback CAS must apply this exact request.
      } else {
        await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ message: 'Unexpected duplicate write' }) });
      }
    });
    const before = await mirror(page);
    phase = 'local-storage-failure';
    await page.evaluate(() => {
      const original = Storage.prototype.setItem;
      const fault: Fault = { blocked: true, attempts: 0, restore: () => { Storage.prototype.setItem = original; } };
      (window as FaultWindow).removalWriteFault = fault;
      Storage.prototype.setItem = function (key, value) {
        if (this === window.localStorage && fault.blocked) {
          fault.attempts += 1;
          throw new DOMException('Controlled local write failure', 'QuotaExceededError');
        }
        return original.call(this, key, value);
      };
    });
    await page.getByRole('button', { name: 'Remove file', exact: true }).click();
    await expect(savedStatus).toContainText("Couldn't save your profile — please retry.");
    expect(await page.evaluate(() => (window as FaultWindow).removalWriteFault!.attempts)).toBeGreaterThan(0);
    expect(attempts).toHaveLength(0);
    expect(await rows(owner)).toEqual([{ profile_data: profile(), revision: 1 }]);
    expect((await mirror(page)).profile).toEqual(before.profile);
    await expect(page.getByRole('button', { name: 'Remove file', exact: true })).toHaveCount(0);

    phase = 'restore-local-and-first-retry';
    await page.evaluate(() => { (window as FaultWindow).removalWriteFault!.blocked = false; });
    expect(attempts).toHaveLength(0);
    await page.getByTestId('retry-sync').click();
    await expect.poll(() => attempts.length).toBe(1);
    expect(attempts[0]).toEqual({ p_expected_device_id: owner.uid, p_expected_revision: 1, p_patch: patch });
    await expect(savedStatus).toContainText('Saving');
    await page.clock.fastForward(2_001);
    expect(attempts).toHaveLength(1);
    expect(await rows(owner)).toEqual([{ profile_data: profile(), revision: 1 }]);

    phase = 'release-cloud-failure';
    const failed = page.waitForResponse(response => isCas(response.url()) && response.status() === 503);
    first.release(); await failed;
    await expect(savedStatus).toContainText("Saved on this device only — we couldn't sync it.");
    await page.clock.fastForward(2_001);
    expect(attempts).toHaveLength(1); // No automatic retry; wait for the user.
    expect((await mirror(page)).envelope.pending.desiredProfile).toMatchObject(patch);

    phase = 'explicit-second-retry';
    await page.getByTestId('retry-sync').click();
    await expect.poll(() => attempts.length).toBe(2);
    expect(attempts[1]).toEqual(attempts[0]);
    await expect(savedStatus).toContainText('Saving');
    const applied = page.waitForResponse(response => isCas(response.url()) && response.status() === 200);
    second.release();
    expect(await (await applied).json()).toMatchObject({ status: 'applied', revision: 2, profile: patch });
    await expect(savedStatus).toHaveText('Profile saved');
    await savedStatus.scrollIntoViewIfNeeded();
    await expect(savedStatus).toBeVisible();
    await page.screenshot({ path: info.outputPath('removal-retry-saved.png') });

    phase = 'final-cloud-and-mirror';
    const finalRow = { ...profile(), ...patch };
    expect(await rows(owner)).toEqual([{ profile_data: finalRow, revision: 2 }]);
    const local = await mirror(page);
    expect(local.owner).toEqual(before.owner);
    expect(local.profile).toEqual(finalRow);
    expect(local.envelope).toMatchObject({ confirmed: { revision: 2, profile: finalRow }, pending: null, tombstone: null });
    await expect(page.locator('#research_interests')).toHaveValue(profile().research_interests);
    await expect(page.locator('#major')).toHaveValue(profile().major);
    await page.clock.fastForward(2_001);
    expect(attempts).toHaveLength(2);
  } catch (error) {
    await info.attach('removal-retry-phase', { contentType: 'application/json', body: JSON.stringify({ phase,
      casAttempts: attempts.map(body => ({ revision: body.p_expected_revision, keys: Object.keys(body.p_patch).sort(), expectedOwner: body.p_expected_device_id === owner.uid })),
      saveStatus: await savedStatus.textContent().catch(() => null),
    }) });
    await attachProfileReadDiagnostics(page, info, 'removal-retry');
    throw error;
  } finally {
    first.release(); second.release();
    await page.evaluate(() => { (window as FaultWindow).removalWriteFault?.restore(); }).catch(() => {});
    await owner.http.dispose();
  }
});
