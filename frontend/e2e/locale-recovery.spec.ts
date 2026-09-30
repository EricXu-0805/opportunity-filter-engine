import { test, expect, type BrowserContext, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';

const TARGET = '/opportunities/uiuc-siebel-ugresearch';
type Locale = 'en' | 'zh';
const footer = (locale: Locale) => locale === 'zh' ? '隐私政策' : 'Privacy Policy';

async function seed(page: Page, context: BrowserContext, origin: string, stored: Locale, cookie?: Locale) {
  if (cookie) await context.addCookies([{ name: STORAGE_KEYS.LOCALE, value: cookie, url: origin }]);
  await page.addInitScript(({ stored, keys }) => {
    if (localStorage.getItem('locale-recovery-seeded')) return;
    localStorage.setItem(keys.LOCALE, stored); localStorage.setItem(keys.ONBOARDING_SEEN, '1');
    sessionStorage.setItem('ofe_school_confirm_deferred', '1');
    localStorage.setItem('locale-recovery-seeded', '1');
  }, { stored, keys: STORAGE_KEYS });
}
async function assertLanguage(page: Page, locale: Locale) {
  await expect(page.locator('html')).toHaveAttribute('lang', locale);
  await expect(page.getByRole('contentinfo').getByRole('link', { name: footer(locale), exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: locale === 'zh' ? 'Switch to English' : 'Switch to Chinese' })).toBeEnabled();
}

test.describe('Server and client language recovery', () => {
  test.beforeEach(async ({ context, page }) => {
    await page.setViewportSize({ width: 320, height: 760 });
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) return route.abort('blockedbyclient');
      // This read-only locale regression requires no real account or AI work.
      if (/\/(?:auth|rest)\/v1\//.test(url.pathname)) return route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
      return route.continue();
    });
  });

  for (const scenario of [
    { name: 'missing cookie', stored: 'zh', cookie: undefined },
    { name: 'English cookie conflicting with Chinese storage', stored: 'zh', cookie: 'en' },
    { name: 'Chinese cookie conflicting with English storage', stored: 'en', cookie: 'zh' },
    { name: 'matching Chinese preference', stored: 'zh', cookie: 'zh' },
  ] as const) test(`${scenario.name} recovers streamed detail once and stays correct on reload`, async ({ page, context, baseURL }) => {
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
    let refreshes = 0;
    page.on('request', request => {
      if (new URL(request.url()).pathname === TARGET && request.headers().rsc === '1' && !request.headers()['next-router-prefetch']) refreshes += 1;
    });
    await seed(page, context, baseURL!, scenario.stored, scenario.cookie);
    const response = await page.goto(TARGET);
    const html = await response!.text();
    const initial = scenario.cookie ?? 'en';
    expect(html).toContain(`<html lang="${initial}"`);
    expect(html).toContain(footer(initial));
    // Real Next-produced streamed/Suspense markup, not page.route HTML/RSC.
    expect(html).toMatch(/<!--\$[?]?-->|\$RC\(/);
    await assertLanguage(page, scenario.stored);
    await expect(page.getByTestId('return-to-results')).toHaveText(scenario.stored === 'zh' ? '返回匹配列表' : 'Back to matches');
    expect((await context.cookies()).find(cookie => cookie.name === STORAGE_KEYS.LOCALE)?.value).toBe(scenario.stored);
    expect(refreshes).toBe(initial === scenario.stored ? 0 : 1);
    const afterRecovery = refreshes;
    const reloaded = await page.reload();
    const reloadedHtml = await reloaded!.text();
    expect(reloadedHtml).toContain(`<html lang="${scenario.stored}"`);
    expect(reloadedHtml).toContain(footer(scenario.stored));
    await assertLanguage(page, scenario.stored);
    expect(refreshes).toBe(afterRecovery);
    expect(errors).toEqual([]);
  });

  test('localStorage-only recovery stays consistent while the detail client chunk is delayed', async ({ page, context, baseURL }) => {
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
    await seed(page, context, baseURL!, 'zh');
    let release!: () => void; const gate = new Promise<void>(resolve => { release = resolve; });
    let heldChunkURL: string | undefined;
    let heldChunkFulfilled = false;
    let refreshes = 0;
    page.on('request', request => {
      if (new URL(request.url()).pathname === TARGET && request.headers().rsc === '1' && !request.headers()['next-router-prefetch']) refreshes += 1;
    });
    // Delay a real browser JS response. This does NOT intercept the server's
    // internal backend fetch or claim coverage of every slow upstream case.
    await page.route('**/_next/static/chunks/*.js', async route => {
      const response = await route.fetch({ maxRedirects: 0 });
      const body = await response.text();
      const holdThisChunk = !heldChunkURL && body.includes('detail.backToMatches');
      if (holdThisChunk) { heldChunkURL = route.request().url(); await gate; }
      await route.fulfill({ response, body });
      if (holdThisChunk) heldChunkFulfilled = true;
    });
    try {
      const response = await page.goto(TARGET, { waitUntil: 'commit' });
      await expect.poll(() => heldChunkURL, { message: 'the real detail client bundle is held before hydration' }).toBeDefined();
      const html = await response!.text();
      expect(html).toContain('<html lang="en"');
      expect(html).toContain(footer('en'));
      expect(html).toMatch(/<!--\$[?]?-->|\$RC\(/);
      expect(new URL(heldChunkURL!).pathname).toMatch(/^\/_next\/static\/chunks\/.+\.js$/);
      expect(heldChunkFulfilled).toBe(false);
      // The root layout may finish its RSC locale recovery while the detail
      // bundle is still held. Both locales are valid here, but must agree.
      await expect(page.getByRole('contentinfo').locator('a[href="/privacy"]')).toBeVisible();
      const duringDelay = await page.evaluate(() => ({
        locale: document.documentElement.lang,
        footer: document.querySelector('footer a[href="/privacy"]')?.textContent,
      }));
      expect([
        { locale: 'en', footer: footer('en') },
        { locale: 'zh', footer: footer('zh') },
      ]).toContainEqual(duringDelay);
      expect(heldChunkFulfilled).toBe(false);
      release();
      await page.waitForLoadState('load');
      await assertLanguage(page, 'zh');
      await expect(page.getByTestId('return-to-results')).toHaveText('返回匹配列表');
      expect(heldChunkFulfilled).toBe(true);
      expect(refreshes).toBe(1);
      expect(errors).toEqual([]);
    } finally { release(); }
  });

  test('an explicit switch shows progress and preserves the unsaved profile form', async ({ page, context, baseURL }) => {
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
    await seed(page, context, baseURL!, 'en', 'en');
    await page.goto('/');
    await page.locator('#student_name').fill('Unsaved name 王');
    await page.locator('#research_interests').fill('Existing research draft stays in the form.');
    let release!: () => void; const gate = new Promise<void>(resolve => { release = resolve; });
    let held = 0;
    await page.route('**/*', async route => {
      if (new URL(route.request().url()).pathname === '/' && route.request().headers().rsc === '1' && !route.request().headers()['next-router-prefetch']) {
        held += 1; await gate;
      }
      return route.fallback();
    });
    try {
      await page.getByRole('button', { name: 'Switch to Chinese' }).click();
      await expect.poll(() => held).toBe(1);
      await expect(page.getByRole('button', { name: 'Switch to Chinese' })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Switch to Chinese' })).toHaveText('Switching…');
      await expect(page.locator('#student_name')).toHaveValue('Unsaved name 王');
      release();
      await assertLanguage(page, 'zh');
      await expect(page.locator('#student_name')).toHaveValue('Unsaved name 王');
      await expect(page.locator('#research_interests')).toHaveValue('Existing research draft stays in the form.');
      expect(held).toBe(1);
      expect(errors).toEqual([]);
    } finally { release(); }
  });

  test('blocked cookie writes retain one consistent language without refresh loops', async ({ page, context, baseURL }) => {
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
    await seed(page, context, baseURL!, 'zh', 'en');
    await page.addInitScript(() => {
      const descriptor = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie')!;
      Object.defineProperty(document, 'cookie', { configurable: true, get: () => descriptor.get!.call(document), set: () => {} });
    });
    let refreshes = 0;
    page.on('request', request => { if (request.headers().rsc === '1' && !request.headers()['next-router-prefetch']) refreshes += 1; });
    await page.goto(TARGET);
    await assertLanguage(page, 'en');
    await expect(page.getByRole('alert').filter({ hasText: 'Allow cookies' })).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Switch to Chinese' })).toHaveText('Retry language');
    await page.getByRole('button', { name: 'Switch to Chinese' }).click();
    await page.reload();
    await assertLanguage(page, 'en');
    expect(refreshes).toBe(0);
    expect(errors).toEqual([]);
  });
});
