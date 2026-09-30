import { test, expect, request as apiRequest } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';

// Widen only the closing transition to expose its first-frame hit area. No
// sleeps or animation-completion waits are allowed after dismissal. Actual
// mouse and keyboard input must reach the existing footer form immediately.
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const ORIGIN = `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3100)}`;

test('dismissed mobile navigation immediately releases the feedback input hit area', async ({ page, context }, info) => {
  const pageErrors: string[] = [], serverErrors: string[] = [], externalRequests: string[] = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('response', response => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${new URL(response.url()).pathname}`); });
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) { externalRequests.push(url.origin); return route.abort('blockedbyclient'); }
    return route.continue();
  });
  const http = await apiRequest.newContext();
  try {
    expect(new URL(STUB).hostname).toBe('127.0.0.1');
    const response = await http.post(`${STUB}/auth/v1/signup`, { data: {} }); expect(response.status()).toBe(200);
    const session = await response.json();
    await context.addCookies([{ name: STORAGE_KEYS.LOCALE, value: 'en', url: ORIGIN }]);
    await page.addInitScript(({ session, keys }) => {
      localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, 'en'); localStorage.setItem(keys.ONBOARDING_SEEN, '1');
    }, { session, keys: STORAGE_KEYS });
    await page.route('**/auth/v1/user', route => route.fulfill({ json: session.user }));
    await page.route('**/auth/v1/token?grant_type=refresh_token', route => route.fulfill({ json: session }));
    await page.setViewportSize({ width: 640, height: 360 });
    await page.goto('/about');
    const toggle = page.getByTestId('mobile-nav-toggle');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    const closedHeight = await page.getByRole('banner').evaluate(element => element.getBoundingClientRect().height);
    // Put an existing input in view before opening the menu. This isolates
    // dismissal from the feedback form's separate initial scroll scheduling.
    const opener = page.getByTestId('feedback-open'); await opener.scrollIntoViewIfNeeded(); await opener.click();
    await expect(page.locator('#site-feedback-title')).toBeFocused();
    await page.getByTestId('feedback-subject').evaluate(element => element.scrollIntoView({ block: 'center', behavior: 'instant' }));
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    // Finish OPENING only, so the closing test starts from a fully open menu.
    await page.locator('#mobile-nav-panel').evaluate(element => { for (const animation of element.getAnimations()) animation.finish(); });
    const link = page.getByTestId('mobile-feedback-link'); await expect(link).toBeVisible();
    await page.addStyleTag({ content: '#mobile-nav-panel[aria-hidden="true"] { transition-duration: 5s !important; }' });
    await link.click();
    const firstFrame = await page.evaluate(() => new Promise<{
      headerHeight: number; expanded: string | null; panelHidden: string | null;
      x: number; y: number; inViewport: boolean; hitSubject: boolean; covering: string | null;
    }>(resolve => requestAnimationFrame(() => {
      const subject = document.querySelector<HTMLInputElement>('[data-testid="feedback-subject"]')!;
      const box = subject.getBoundingClientRect(); const x = box.left + box.width / 2, y = box.top + box.height / 2;
      const hit = document.elementFromPoint(x, y);
      resolve({ headerHeight: document.querySelector('header')!.getBoundingClientRect().height,
        expanded: document.querySelector('[data-testid="mobile-nav-toggle"]')!.getAttribute('aria-expanded'),
        panelHidden: document.querySelector('#mobile-nav-panel')!.getAttribute('aria-hidden'),
        x, y, inViewport: x > 0 && x < innerWidth && y > 0 && y < innerHeight,
        hitSubject: subject === hit || subject.contains(hit), covering: hit?.outerHTML.slice(0, 300) ?? null });
    })));
    // Raw mouse input deliberately bypasses locator auto-waits for overlays.
    await page.mouse.click(firstFrame.x, firstFrame.y);
    const focused = await page.evaluate(() => document.activeElement?.getAttribute('data-testid') === 'feedback-subject');
    if (focused) await page.keyboard.type('After menu close');
    const after = await page.evaluate(() => ({ path: location.pathname, value: document.querySelector<HTMLInputElement>('[data-testid="feedback-subject"]')?.value ?? null }));
    await info.attach('nav-dismiss-first-frame', { body: JSON.stringify({ closedHeight, firstFrame, focused, after, pageErrors, serverErrors, externalRequests }, null, 2), contentType: 'application/json' });
    await page.screenshot({ path: info.outputPath('nav-dismiss-first-frame.png') });
    expect(firstFrame.expanded).toBe('false'); expect(firstFrame.panelHidden).toBe('true');
    expect(firstFrame.inViewport).toBe(true);
    expect(firstFrame.headerHeight).toBeLessThanOrEqual(closedHeight + 1);
    expect(firstFrame.hitSubject).toBe(true); expect(focused).toBe(true);
    expect(after).toEqual({ path: '/about', value: 'After menu close' });
    expect(pageErrors).toEqual([]); expect(serverErrors).toEqual([]); expect(externalRequests).toEqual([]);
  } finally { await http.dispose(); }
});
