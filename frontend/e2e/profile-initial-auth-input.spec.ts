import { test, expect, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';

// Hold the SDK's real browser lock before initialization. The form can be used
// while auth is pending; releasing the lock then exercises INITIAL_SESSION(null)
// and local-only recovery. No sleeps or readiness wait precedes the first edits.
// Auth/REST responses are loopback failures; no hosted account or email is used.
interface AuthGateWindow extends Window {
  __releaseInitialProfileAuth?: () => void;
  __initialProfileAuthHeld?: boolean;
  __profileAuthSettled?: number;
  __initialResearchNode?: HTMLTextAreaElement;
}
const audit = new WeakMap<Page, { pageErrors: string[]; blockedExternal: string[] }>();

test.describe('Input during initial auth observation', () => {
  test.beforeEach(async ({ page, context }) => {
    const state = { pageErrors: [] as string[], blockedExternal: [] as string[] }; audit.set(page, state);
    page.on('pageerror', error => state.pageErrors.push(error.message));
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) { state.blockedExternal.push(url.origin); return route.abort('blockedbyclient'); }
      if (/\/(?:auth|rest)\/v1\//.test(url.pathname)) return route.fulfill({ status: 503, json: {} });
      return route.continue();
    });
    await page.context().addCookies([{ name: STORAGE_KEYS.LOCALE, value: 'en', url: `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3100)}` }]);
    await page.addInitScript(({ keys }) => {
      const target = window as AuthGateWindow;
      localStorage.removeItem('ofe_auth'); localStorage.setItem(keys.LOCALE, 'en'); localStorage.setItem(keys.ONBOARDING_SEEN, '1');
      const gate = new Promise<void>(resolve => { target.__releaseInitialProfileAuth = resolve; });
      void navigator.locks.request('lock:ofe_auth', async () => { target.__initialProfileAuthHeld = true; await gate; target.__initialProfileAuthHeld = false; });
      // Count completed SDK lock callbacks, excluding the gate above. This is
      // browser API observation only, not access to React or app internals.
      const request = navigator.locks.request.bind(navigator.locks);
      target.__profileAuthSettled = 0;
      navigator.locks.request = ((name: string, options: LockOptions | LockGrantedCallback<unknown>, callback?: LockGrantedCallback<unknown>) => {
        const run = typeof options === 'function' ? options : callback!;
        const wrapped: LockGrantedCallback<unknown> = async lock => { try { return await run(lock); } finally { if (name === 'lock:ofe_auth') target.__profileAuthSettled! += 1; } };
        return typeof options === 'function' ? request(name, wrapped) : request(name, options, wrapped);
      }) as typeof navigator.locks.request;
    }, { keys: STORAGE_KEYS });
  });

  test('the first null auth observation preserves the focused research field and subsequent typing', async ({ page }, info) => {
    let failures = 0; page.on('response', response => { if (new URL(response.url()).pathname === '/auth/v1/signup' && response.status() === 503) failures += 1; });
    try {
      await page.goto('/');
      expect(await page.evaluate(() => (window as AuthGateWindow).__initialProfileAuthHeld)).toBe(true);
      const name = page.locator('#student_name'), research = page.locator('#research_interests');
      await name.fill('First visitor 王'); await research.fill('Before auth');
      await expect(name).toHaveValue('First visitor 王'); await expect(research).toHaveValue('Before auth');
      await expect(research).toBeFocused();
      const before = await page.evaluate(() => {
        const target = window as AuthGateWindow;
        target.__initialResearchNode = document.querySelector<HTMLTextAreaElement>('#research_interests')!;
        return target.__profileAuthSettled;
      });
      expect(failures).toBe(0);
      await page.evaluate(() => (window as AuthGateWindow).__releaseInitialProfileAuth!());
      await expect.poll(() => failures, { message: 'the delayed real SDK initialization reaches the controlled auth failure' }).toBeGreaterThan(0);
      await expect.poll(() => page.evaluate(() => (window as AuthGateWindow).__profileAuthSettled), { message: 'the SDK auth observation has completed' }).toBeGreaterThan(before!);
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      const focus = await page.evaluate(() => {
        const node = (window as AuthGateWindow).__initialResearchNode!;
        return { connected: node.isConnected, focused: document.activeElement === node, sameNode: document.querySelector('#research_interests') === node };
      });
      await info.attach('initial-auth-input-observation', { body: JSON.stringify({ focus, auth503Responses: failures, pageErrors: audit.get(page)!.pageErrors }, null, 2), contentType: 'application/json' });
      expect(focus).toEqual({ connected: true, focused: true, sameNode: true });
      // Keyboard input goes to actual browser focus, not a locator that would
      // silently find and refocus a replacement textarea after a remount.
      await page.keyboard.type(' and after auth');
      await expect(research).toHaveValue('Before auth and after auth'); await expect(name).toHaveValue('First visitor 王');
      await research.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('initial-auth-keeps-focused-input.png') });
      expect(audit.get(page)!.pageErrors).toEqual([]);
    } finally { await page.evaluate(() => (window as AuthGateWindow).__releaseInitialProfileAuth?.()).catch(() => {}); }
  });

  for (const hadDraft of [true, false]) test(hadDraft
    ? 'the first successful anonymous sign-in preserves focused input from the same first visitor'
    : 'the first successful anonymous sign-in preserves an empty focused field before the first character', async ({ page }, info) => {
    let releaseSignup!: () => void;
    const signupGate = new Promise<void>(resolve => { releaseSignup = resolve; });
    let returnedOwner: string | null = null;
    let pendingSignup = false;
    await page.route('**/auth/v1/signup', async route => {
      expect(new URL(route.request().url()).hostname).toBe('127.0.0.1');
      // The existing local stub creates an anonymous account. The response is
      // held, not replaced by a fabricated React/auth state.
      const response = await route.fetch({ maxRedirects: 0 });
      expect(response.status()).toBe(200);
      const session = await response.json();
      expect(session.user.is_anonymous).toBe(true); returnedOwner = session.user.id;
      pendingSignup = true; await signupGate; await route.fulfill({ response });
    });
    try {
      await page.goto('/');
      await page.evaluate(() => (window as AuthGateWindow).__releaseInitialProfileAuth!());
      // Isolate the SECOND observation: initialization is null, while the
      // first anonymous sign-in is still awaiting its real HTTP response.
      await expect.poll(() => pendingSignup).toBe(true);
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      expect(await page.evaluate(() => localStorage.getItem('ofe_auth'))).toBeNull();
      const name = page.locator('#student_name'), research = page.locator('#research_interests');
      if (hadDraft) { await name.fill('First anonymous visitor 王'); await research.fill('Before first sign-in'); }
      else await research.focus();
      await expect(name).toHaveValue(hadDraft ? 'First anonymous visitor 王' : '');
      await expect(research).toHaveValue(hadDraft ? 'Before first sign-in' : '');
      await expect(research).toBeFocused();
      await page.evaluate(() => { (window as AuthGateWindow).__initialResearchNode = document.querySelector<HTMLTextAreaElement>('#research_interests')!; });
      releaseSignup();
      await expect.poll(() => page.evaluate(() => {
        const raw = localStorage.getItem('ofe_auth'); return raw ? JSON.parse(raw).user.id : null;
      })).toBe(returnedOwner);
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      const observation = await page.evaluate(() => {
        const node = (window as AuthGateWindow).__initialResearchNode!;
        const session = JSON.parse(localStorage.getItem('ofe_auth')!);
        return { focus: { connected: node.isConnected, focused: document.activeElement === node, sameNode: document.querySelector('#research_interests') === node }, anonymous: session.user.is_anonymous };
      });
      await info.attach('initial-anonymous-input-observation', { body: JSON.stringify({ hadDraft, ...observation, pageErrors: audit.get(page)!.pageErrors }, null, 2), contentType: 'application/json' });
      expect(observation.anonymous).toBe(true);
      expect(observation.focus).toEqual({ connected: true, focused: true, sameNode: true });
      await page.keyboard.type(hadDraft ? ' and after first sign-in' : 'First text after sign-in');
      await expect(research).toHaveValue(hadDraft ? 'Before first sign-in and after first sign-in' : 'First text after sign-in');
      await expect(name).toHaveValue(hadDraft ? 'First anonymous visitor 王' : '');
      await research.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(hadDraft ? 'first-anonymous-keeps-focused-input.png' : 'first-anonymous-empty-field-keeps-focus.png') });
      expect(audit.get(page)!.pageErrors).toEqual([]);
    } finally { releaseSignup(); await page.evaluate(() => (window as AuthGateWindow).__releaseInitialProfileAuth?.()).catch(() => {}); }
  });

});
