import { test, expect, type Page } from '@playwright/test';
import { attachProfileReadDiagnostics } from './profile-read-diagnostics';

const LOCK = 'ofe-profile-local-storage';
const marker = 'First restored owner — calibration evidence 王';
const wanted = { college: 'Grainger College of Engineering', major: 'Computer Engineering', grade: 'Junior', interests: marker };
const isProfile = (url: string) => new URL(url).pathname === '/rest/v1/profiles';
async function fields(page: Page) {
  return page.evaluate(() => ({
    college: (document.querySelector('#college') as HTMLSelectElement | null)?.value,
    major: (document.querySelector('#major') as HTMLSelectElement | null)?.value,
    grade: (document.querySelector('#grade') as HTMLSelectElement | null)?.value,
    interests: (document.querySelector('#research_interests') as HTMLTextAreaElement | null)?.value,
  }));
}

// A genuine SDK-created anonymous identity is restored into a new page. A real
// Web Lock holds the local owner transition before Home is notified. No owner
// token, private profile, event or application callback is injected.
test('first restored owner preserves input while its native local-owner lock is held, including the copied share', async ({ page, context }, info) => {
  const observations: unknown[] = [];
  let source: Page | undefined, completed = false;
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  for (const pattern of ['**/auth/v1/**', '**/rest/v1/profiles?**', '**/rest/v1/rpc/commit_profile_patch_cas']) {
    await context.route(pattern, route => {
      expect(new URL(route.request().url()).origin).toBe(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
      return route.continue();
    });
  }
  try {
    const auth = page.waitForResponse(response => new URL(response.url()).pathname === '/auth/v1/signup' && response.status() === 200);
    const firstRead = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
    await page.goto('/');
    expect((await (await auth).json()).user.id).toBeTruthy();
    expect(await (await firstRead).json()).toEqual([]);
    await expect(page.getByTestId('hydration-note')).toHaveCount(0);
    // Same-origin plain text is a lock holder with no mounted app subscribers.
    await page.goto('/robots.txt');
    await page.evaluate(name => {
      Object.assign(window, { firstOwnerLockHeld: false });
      void navigator.locks.request(name, { mode: 'exclusive' }, () => new Promise<void>(resolve => {
        Object.assign(window, { firstOwnerLockHeld: true, releaseFirstOwnerLock: resolve });
      }));
    }, LOCK);
    await expect.poll(() => page.evaluate(() => (window as typeof window & { firstOwnerLockHeld: boolean }).firstOwnerLockHeld)).toBe(true);
    source = await context.newPage();
    let reads = 0, writes = 0;
    source.on('request', request => {
      if (isProfile(request.url()) && request.method() === 'GET') reads += 1;
      if (new URL(request.url()).pathname === '/rest/v1/rpc/commit_profile_patch_cas') writes += 1;
    });
    await source.goto('/');
    await expect.poll(() => source!.evaluate(async name => {
      const locks = await navigator.locks.query();
      return (locks.pending ?? []).filter(lock => lock.name === name).length;
    }, LOCK), 'a real identity transition must be queued behind the native lock').toBeGreaterThan(0);
    await expect.poll(() => source!.evaluate(() => performance.getEntriesByType('mark')
      .filter(mark => /^ofe-profile-read:home:[0-9]+:started$/.test(mark.name)).length),
      'Home has actually issued its fallback read before accepting input').toBeGreaterThan(0);
    await source.locator('#college').selectOption(wanted.college);
    await source.locator('#major').selectOption(wanted.major);
    await source.locator('#grade').selectOption(wanted.grade);
    await source.locator('#research_interests').fill(marker);
    expect(await fields(source)).toEqual(wanted);
    observations.push({ phase: 'before-owner-lock-release', fields: await fields(source) });
    expect(reads).toBe(0); expect(writes).toBe(0);
    const restored = source.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
    await page.evaluate(() => (window as typeof window & { releaseFirstOwnerLock: () => void }).releaseFirstOwnerLock());
    expect(await (await restored).json()).toEqual([]);
    await expect(source.getByTestId('hydration-note')).toHaveCount(0);
    observations.push({ phase: 'after-owner-notification-and-read', fields: await fields(source) });
    expect.soft(await fields(source), 'first-owner notification must preserve the four current inputs').toEqual(wanted);
    await source.getByRole('button', { name: 'Share profile', exact: true }).click();
    await expect(source.getByText('Copied!', { exact: true })).toBeVisible();
    const url = await source.evaluate(() => navigator.clipboard.readText());
    const encoded = new URL(url).searchParams.get('share');
    expect(encoded).toBeTruthy();
    const decoded = JSON.parse(Buffer.from(encoded!, 'base64url').toString('utf8'));
    observations.push({ phase: 'copied', fields: await fields(source), decoded });
    expect(decoded).toMatchObject({ v: 1, ...wanted });
    await source.locator('#research_interests').scrollIntoViewIfNeeded();
    await source.screenshot({ path: info.outputPath('first-owner-lock-input-and-share.png') });
    completed = true;
  } finally {
    await page.evaluate(() => (window as typeof window & { releaseFirstOwnerLock?: () => void }).releaseFirstOwnerLock?.()).catch(() => {});
    if (!completed) {
      await info.attach('first-owner-observations', { body: JSON.stringify(observations, null, 2), contentType: 'application/json' });
      if (source) await attachProfileReadDiagnostics(source, info, 'first-owner-source');
    }
  }
});
