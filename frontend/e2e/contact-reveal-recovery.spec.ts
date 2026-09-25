import { test, expect, request as apiRequest, type APIRequestContext, type Page, type Route, type Request } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { en, zh } from '../src/i18n/dictionaries';

// Production page + real Supabase SDK; only loopback auth/detail responses are
// fixtures. Cross-tab owner events use the SDK's BroadcastChannel protocol.
// These tests do not prove hosted authentication, proxy reliability or delivery.
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const TARGET = 'uiuc-siebel-ugresearch';
const PATH = `/opportunities/${TARGET}`;
const EMAIL = 'verified-contact@example.test';
type Locale = 'en' | 'zh';
interface Session { access_token: string; refresh_token: string; user: { id: string; email: string; is_anonymous: boolean; app_metadata: Record<string, unknown> } }
interface Owner { http: APIRequestContext; session: Session }
interface NetworkAudit { pageErrors: string[]; injected: Array<{ path: string; outcome: string }>; responses: Array<{ path: string; status: number; injected: string | null }>; failed: Array<{ path: string; error: string | null; injected: string | null }>; blockedExternal: string[] }
const audits = new WeakMap<Page, NetworkAudit>();
const injectedRequests = new WeakMap<Request, string>();
const copy = (locale: Locale) => (locale === 'zh' ? zh : en).detail;
const errorPanel = (page: Page) => page.getByTestId('contact-reveal-error');
const emailLink = (page: Page) => page.getByTestId('contact-email-link');
const retryButton = (page: Page, locale: Locale = 'en') => page.locator('section').filter({ has: errorPanel(page) }).getByRole('button', { name: copy(locale).contactRetry, exact: true });
function gate() { let release!: () => void; const promise = new Promise<void>(resolve => { release = resolve; }); return { promise, release }; }
async function account(label = 'reveal'): Promise<Owner> {
  expect(new URL(STUB).hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const response = await http.post(`${STUB}/auth/v1/signup`, { data: {} }); expect(response.status()).toBe(200);
    const session = await response.json() as Session;
    session.user = { ...session.user, is_anonymous: false, email: `${label}@example.test`, app_metadata: { provider: 'email', providers: ['email'] } };
    const token = session.access_token.split('.');
    const claims = JSON.parse(Buffer.from(token[1], 'base64url').toString());
    token[1] = Buffer.from(JSON.stringify({ ...claims, is_anonymous: false })).toString('base64url'); session.access_token = token.join('.');
    return { http, session };
  } catch (error) { await http.dispose(); throw error; }
}
async function seed(page: Page, owner: Owner, locale: Locale = 'en') {
  const state = { owner, refreshes: 0 };
  await page.context().addCookies([{ name: STORAGE_KEYS.LOCALE, value: locale, url: `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3100)}` }]);
  await page.addInitScript(({ session, keys, locale }) => {
    if (localStorage.getItem('contact-reveal-seeded')) return;
    localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, locale);
    localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('contact-reveal-seeded', '1');
  }, { session: owner.session, keys: STORAGE_KEYS, locale });
  await page.route('**/auth/v1/user', route => route.fulfill({ json: state.owner.session.user }));
  await page.route('**/auth/v1/token?grant_type=refresh_token', route => {
    state.refreshes += 1;
    expect(route.request().postDataJSON().refresh_token).toBe(state.owner.session.refresh_token);
    return route.fulfill({ json: state.owner.session });
  });
  return state;
}
function injected(page: Page, route: Route, outcome: string) {
  injectedRequests.set(route.request(), outcome);
  audits.get(page)!.injected.push({ path: new URL(route.request().url()).pathname, outcome });
}
async function reveal(route: Route, address = EMAIL) {
  await route.fulfill({ json: { id: decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)!), contact_email_status: 'revealed', contact_email: address } });
}
async function assertNoSignIn(page: Page) { await expect(page.getByTestId('contact-sign-in')).toHaveCount(0); }
async function switchOwner(page: Page, owner: Owner | null) {
  await page.evaluate(session => {
    if (session) localStorage.setItem('ofe_auth', JSON.stringify(session)); else localStorage.removeItem('ofe_auth');
    const channel = new BroadcastChannel('ofe_auth'); channel.postMessage({ event: session ? 'SIGNED_IN' : 'SIGNED_OUT', session }); channel.close();
  }, owner?.session ?? null);
}

test.describe('Contact reveal recovery', () => {
  test.beforeEach(async ({ page, context }) => {
    const audit: NetworkAudit = { pageErrors: [], injected: [], responses: [], failed: [], blockedExternal: [] }; audits.set(page, audit);
    page.on('pageerror', error => audit.pageErrors.push(error.message));
    page.on('response', response => { if (response.status() >= 400) audit.responses.push({ path: new URL(response.url()).pathname, status: response.status(), injected: injectedRequests.get(response.request()) ?? null }); });
    page.on('requestfailed', request => audit.failed.push({ path: new URL(request.url()).pathname, error: request.failure()?.errorText ?? null, injected: injectedRequests.get(request) ?? null }));
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) { audit.blockedExternal.push(url.origin); return route.abort('blockedbyclient'); }
      return route.continue();
    });
  });
  test.afterEach(async ({ page }, info) => {
    const audit = audits.get(page)!;
    await info.attach('contact-reveal-network-audit', { body: JSON.stringify(audit, null, 2), contentType: 'application/json' });
    expect(audit.pageErrors, 'Unexpected browser errors, including hydration').toEqual([]);
    expect(audit.responses.filter(row => row.status >= 500 && !row.injected), 'Uninjected server failures').toEqual([]);
  });

  for (const locale of ['en', 'zh'] as const) test(`${locale}: server failure offers reachable retry and recovers the verified email`, async ({ page }, info) => {
    const owner = await account(); const pending = gate(); let reads = 0;
    try {
      await seed(page, owner, locale);
      if (info.project.name === 'mobile-chrome') await page.setViewportSize({ width: 320, height: 760 });
      await page.route(`**/api/opportunities/${TARGET}`, async route => {
        expect(route.request().headers().authorization).toBe(`Bearer ${owner.session.access_token}`); reads += 1;
        if (reads === 1) { injected(page, route, 'HTTP 500'); await route.fulfill({ status: 500, contentType: 'text/plain', body: 'Internal Server Error' }); return; }
        await pending.promise; await reveal(route);
      });
      await page.goto(PATH); await expect(errorPanel(page)).toBeVisible(); await assertNoSignIn(page);
      await expect(emailLink(page)).toHaveCount(0); expect(reads).toBe(1);
      const retry = retryButton(page, locale);
      await retry.scrollIntoViewIfNeeded(); await expect(retry).toBeEnabled();
      const area = await retry.evaluate(element => { const r = element.getBoundingClientRect(); return { fits: r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight, hit: element.contains(document.elementFromPoint(r.left + 4, r.top + r.height / 2)) }; });
      expect(area).toEqual({ fits: true, hit: true });
      await page.screenshot({ path: info.outputPath(`contact-retry-${locale}.png`) });
      await retry.click(); await expect(page.getByTestId('contact-reveal-loading')).toBeVisible();
      await assertNoSignIn(page); await expect(errorPanel(page)).toHaveCount(0);
      await expect.poll(() => reads).toBe(2); pending.release();
      await expect(emailLink(page)).toHaveText(EMAIL); await expect(emailLink(page)).toHaveAttribute('href', `mailto:${encodeURIComponent(EMAIL)}`);
      await expect(errorPanel(page)).toHaveCount(0); await expect(page.getByTestId('contact-reveal-loading')).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    } finally { pending.release(); await owner.http.dispose(); }
  });

  test('a dropped connection stays recoverable without asking a signed-in user to log in', async ({ page }) => {
    const owner = await account(); let reads = 0;
    try {
      await seed(page, owner);
      await page.route(`**/api/opportunities/${TARGET}`, async route => {
        reads += 1; if (reads === 1) { injected(page, route, 'network connection reset'); await route.abort('connectionreset'); return; } await reveal(route);
      });
      await page.goto(PATH); await expect(errorPanel(page)).toBeVisible(); await assertNoSignIn(page);
      await retryButton(page).click();
      await expect(emailLink(page)).toHaveText(EMAIL); expect(reads).toBe(2);
    } finally { await owner.http.dispose(); }
  });

  test('an explicit unavailable response shows no verified address and no login or retry prompt', async ({ page }, info) => {
    const owner = await account();
    try {
      await seed(page, owner, 'zh');
      await page.route(`**/api/opportunities/${TARGET}`, route => route.fulfill({ json: { id: TARGET, contact_email_status: 'unavailable', contact_email: null } }));
      await page.goto(PATH); await expect(page.getByTestId('contact-unavailable')).toBeVisible();
      await assertNoSignIn(page); await expect(emailLink(page)).toHaveCount(0); await expect(errorPanel(page)).toHaveCount(0);
      await page.getByTestId('contact-unavailable').scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('contact-unavailable-zh.png') });
    } finally { await owner.http.dispose(); }
  });

  test('a still-locked response refreshes once and then asks to sign in again', async ({ page }) => {
    const owner = await account(); const otp = gate(); let reads = 0, otpCalls = 0, locked = true;
    try {
      const state = await seed(page, owner);
      await page.route('**/auth/v1/otp**', async route => {
        otpCalls += 1; expect(route.request().postDataJSON()).toMatchObject({ email: owner.session.user.email, create_user: false });
        injected(page, route, 'loopback OTP acknowledgement; no email sent'); await otp.promise; await route.fulfill({ json: {} });
      });
      await page.route(`**/api/opportunities/${TARGET}`, route => { reads += 1; return locked ? route.fulfill({ json: { id: TARGET, contact_email_status: 'sign_in_required' } }) : reveal(route); });
      await page.goto(PATH); await expect(page.getByTestId('contact-sign-in')).toBeVisible();
      await expect.poll(() => reads).toBe(2); expect(state.refreshes).toBe(1);
      await expect(errorPanel(page)).toHaveCount(0); await expect(emailLink(page)).toHaveCount(0);
      await page.getByTestId('contact-sign-in').getByRole('button', { name: copy('en').contactSignInCta, exact: true }).click();
      const dialog = page.getByRole('dialog'); await expect(dialog).toBeVisible();
      await dialog.getByRole('textbox', { name: en.auth.modal.signin.emailLabel }).fill(owner.session.user.email);
      await dialog.getByRole('button', { name: en.auth.modal.signin.submit, exact: true }).click();
      await expect.poll(() => otpCalls).toBe(1); await expect(dialog.getByRole('heading', { name: en.auth.modal.sent.title, exact: true })).toHaveCount(0);
      otp.release(); await expect(dialog.getByRole('heading', { name: en.auth.modal.sent.title, exact: true })).toBeVisible();
      await dialog.getByRole('button', { name: en.auth.modal.sent.done, exact: true }).click();
      locked = false; await switchOwner(page, owner);
      await expect(page.getByTestId('contact-check-again')).toBeVisible(); expect(reads).toBe(2);
      await page.getByTestId('contact-check-again').click(); await expect(emailLink(page)).toHaveText(EMAIL); expect(reads).toBe(3);
    } finally { otp.release(); await owner.http.dispose(); }
  });

  for (const status of [401, 403]) test(`HTTP ${status} is classified without inventing an unavailable address`, async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner);
      await page.route(`**/api/opportunities/${TARGET}`, route => { injected(page, route, `HTTP ${status}`); return route.fulfill({ status, json: { detail: 'controlled access failure' } }); });
      await page.goto(PATH);
      if (status === 401) { await expect(page.getByTestId('contact-sign-in')).toBeVisible(); await expect(errorPanel(page)).toHaveCount(0); }
      else { await expect(errorPanel(page)).toBeVisible(); await assertNoSignIn(page); }
      await expect(page.getByTestId('contact-unavailable')).toHaveCount(0); await expect(emailLink(page)).toHaveCount(0);
    } finally { await owner.http.dispose(); }
  });

  test('signing out while reveal is delayed never displays the old response', async ({ page }) => {
    const owner = await account(); const pending = gate(); let reads = 0; let settled = false;
    try {
      await seed(page, owner);
      await page.route(`**/api/opportunities/${TARGET}`, async route => { reads += 1; await pending.promise; try { await reveal(route, 'late-owner@example.test'); } finally { settled = true; } });
      await page.goto(PATH); await expect.poll(() => reads).toBe(1); await expect(page.getByTestId('contact-reveal-loading')).toBeVisible();
      await switchOwner(page, null); await expect(page.getByTestId('contact-sign-in')).toBeVisible(); pending.release();
      await expect.poll(() => settled).toBe(true); await expect(emailLink(page)).toHaveCount(0); await expect(page.getByText('late-owner@example.test', { exact: true })).toHaveCount(0);
      await expect(errorPanel(page)).toHaveCount(0);
    } finally { pending.release(); await owner.http.dispose(); }
  });

  for (const timing of ['pending', 'visible'] as const) test(`owner switch clears ${timing} email and uses only the new owner response`, async ({ page }) => {
    const first = await account('first'), second = await account('second'); const pending = gate(); const next = gate(); let firstReads = 0, secondReads = 0, firstSettled = false;
    try {
      const state = await seed(page, first);
      await page.route(`**/api/opportunities/${TARGET}`, async route => {
        if (route.request().headers().authorization === `Bearer ${first.session.access_token}`) {
          firstReads += 1; if (timing === 'pending') await pending.promise;
          try { await reveal(route, 'first-owner@example.test'); } finally { firstSettled = true; }
        } else { expect(route.request().headers().authorization).toBe(`Bearer ${second.session.access_token}`); secondReads += 1; await next.promise; await reveal(route, 'second-owner@example.test'); }
      });
      await page.goto(PATH); await expect.poll(() => firstReads).toBe(1);
      if (timing === 'visible') await expect(emailLink(page)).toHaveText('first-owner@example.test');
      state.owner = second; await switchOwner(page, second);
      await expect.poll(() => secondReads).toBe(1); await expect(emailLink(page)).toHaveCount(0);
      pending.release(); await expect.poll(() => firstSettled).toBe(true); await expect(emailLink(page)).toHaveCount(0);
      next.release(); await expect(emailLink(page)).toHaveText('second-owner@example.test');
      await expect(page.getByText('first-owner@example.test', { exact: true })).toHaveCount(0); await assertNoSignIn(page);
    } finally { pending.release(); next.release(); await first.http.dispose(); await second.http.dispose(); }
  });

  test('following a related target cancels pending contact reveal and does not leak the previous email', async ({ page }) => {
    const owner = await account(); const pending = gate(); let reads = 0, settled = false;
    try {
      await seed(page, owner);
      await page.route(`**/api/opportunities/${TARGET}`, async route => { reads += 1; await pending.promise; try { await reveal(route, 'previous-target@example.test'); } finally { settled = true; } });
      // This verified local recommendation has no known email. Its real
      // target page must stay unavailable after the old response arrives.
      await page.goto(PATH); await expect.poll(() => reads).toBe(1);
      const related = page.locator('section[aria-labelledby="similar-heading"] a[href="/opportunities/purdue-74a073b99827"]'); await expect(related).toBeVisible();
      const href = await related.getAttribute('href'); expect(href).toMatch(/^\/opportunities\//); expect(href).not.toBe(PATH);
      await related.click(); await expect(page).toHaveURL(new RegExp(`${href}$`)); await expect(page.locator('h1')).toBeVisible();
      pending.release(); await expect.poll(() => settled).toBe(true);
      await expect(page.getByText('previous-target@example.test', { exact: true })).toHaveCount(0);
      await expect(page.getByTestId('contact-unavailable')).toBeVisible(); await expect(emailLink(page)).toHaveCount(0);
    } finally { pending.release(); await owner.http.dispose(); }
  });
});
