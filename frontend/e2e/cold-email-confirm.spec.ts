import { test, expect, type Page, type Route } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { en, zh } from '../src/i18n/dictionaries';

/**
 * Cold Email — the verified-send contract, in a real browser.
 *
 * The jsdom fixtures (ColdEmailModal.confirm.test.tsx) prove the component's
 * logic. This proves the same rules survive the real thing: a production React
 * build, the real identity-owner primitive over real Web Locks, the real
 * supabase-js client issuing real HTTP, and a real user clicking.
 *
 * Only the network is stubbed, and only at its outermost edge:
 *   - the draft source (/api/cold-email/variants), so the test does not depend
 *     on an LLM or on which faculty rows the corpus happens to hold;
 *   - Supabase auth + the confirm RPC, so no hosted project is touched and the
 *     success / failure / still-in-flight cases are all reachable.
 * Everything between the click and that edge is the shipped code.
 */
const KNOWN_ID = 'uiuc-siebel-ugresearch';
const DEVICE_ID = '11111111-1111-4111-8111-111111111111';

const PROFILE = {
  name: 'Alex Chen',
  institution: 'UIUC',
  college: 'Grainger College of Engineering',
  major: 'Computer Science',
  grade: 'Sophomore',
  is_international: false,
  research_interests: 'machine learning',
  skills: ['Python'],
  coursework: ['CS 225'],
};

const VARIANT = {
  id: 'v1',
  label: 'Template A',
  subject: 'Interested in your research',
  body: 'Dear Professor,\n\nI am interested in your lab.\n\nBest,\nAlex',
  recipient_email: 'prof@illinois.edu',
  mailto_link: 'mailto:prof@illinois.edu',
};

function session() {
  return {
    access_token: 'e2e-stub-access-token',
    refresh_token: 'e2e-stub-refresh-token',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    user: {
      id: DEVICE_ID,
      aud: 'authenticated',
      role: 'authenticated',
      is_anonymous: true,
      app_metadata: {},
      user_metadata: {},
      created_at: '2026-01-01T00:00:00.000Z',
    },
  };
}

/** Counts every request that could possibly write to the tracker. */
interface Tracker {
  confirms: string[];
  otherWrites: string[];
  /** Resolve/reject the confirm RPC that is currently parked. */
  release: (mode: 'ok' | 'fail') => void;
}

async function installNetwork(page: Page, opts: { hold?: boolean; labType?: 'dry'; body?: string; recipient?: string } = {}): Promise<Tracker> {
  const state: Tracker = { confirms: [], otherWrites: [], release: () => {} };
  let parked: Route | null = null;

  // Playwright matches routes in REVERSE registration order, so the broad
  // fallbacks go first and the specific handlers below override them.
  await page.route('**/api/cold-email**', (route) => route.fulfill({
    // The AI pipeline fires automatically on open; it is not this test's
    // subject, and the modal is designed to stay on the template when it fails.
    status: 503,
    contentType: 'application/json',
    body: '{}',
  }));
  await page.route('**/rest/v1/**', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }));
  await page.route('**/auth/v1/**', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(session()),
  }));

  await page.route('**/api/cold-email/variants', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ variants: [{ ...VARIANT, body: opts.body ?? VARIANT.body, recipient_email: opts.recipient ?? VARIANT.recipient_email }], recipient_status: opts.recipient === '' ? 'unavailable' : 'revealed', lab_type: opts.labType ?? null }),
  }));

  await page.route('**/rest/v1/rpc/confirm_interaction_contact', async (route) => {
    state.confirms.push(route.request().postData() ?? '');
    if (opts.hold) {
      parked = route;
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{
        device_id: DEVICE_ID,
        opportunity_id: KNOWN_ID,
        interaction_type: 'contacted',
        notes: null,
        remind_at: null,
        last_contacted_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }]),
    });
  });

  // Any OTHER tracker mutation is recorded and allowed to succeed emptily, so
  // "Copy wrote nothing" is asserted against every write path, not just the RPC.
  await page.route('**/rest/v1/interactions**', async (route) => {
    const method = route.request().method();
    if (method !== 'GET' && method !== 'HEAD') {
      state.otherWrites.push(`${method} ${route.request().url()}`);
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });

  state.release = (mode) => {
    const r = parked;
    parked = null;
    if (!r) return;
    if (mode === 'ok') {
      void r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{
          device_id: DEVICE_ID,
          opportunity_id: KNOWN_ID,
          interaction_type: 'contacted',
          notes: null,
          remind_at: null,
          last_contacted_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }]),
      });
    } else {
      void r.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ message: 'e2e injected failure' }),
      });
    }
  };

  return state;
}

/**
 * Whether this build can reach Supabase at all.
 *
 * CI builds the E2E app with NEXT_PUBLIC_SUPABASE_URL empty (see ci.yml), and
 * an unconfigured client never issues a request for a route to intercept —
 * `confirmInteractionContact` fails closed instead. Both configurations are
 * real, so the spec adapts rather than pretending: the rules that hold in both
 * are asserted unconditionally, and only the ones that need a reachable RPC
 * (a SUCCESSFUL confirmation) are gated. The app's own startup warning is the
 * signal, so the test and the app can never disagree about which mode this is.
 */
async function openModal(page: Page, opts: { profile?: typeof PROFILE; locale?: 'en' | 'zh'; readyState?: 'name-required' | 'error' } = {}): Promise<{ supabaseConfigured: boolean }> {
  const warnings: string[] = [];
  page.on('console', (msg) => { if (msg.type() === 'warning') warnings.push(msg.text()); });
  await page.addInitScript(
    ({ profileKey, profile, localeKey, locale }) => {
      window.localStorage.setItem(profileKey, profile);
      window.localStorage.setItem(localeKey, locale);
    },
    { profileKey: STORAGE_KEYS.PROFILE, profile: JSON.stringify(opts.profile ?? PROFILE), localeKey: STORAGE_KEYS.LOCALE, locale: opts.locale ?? 'en' },
  );
  await page.goto(`/opportunities/${KNOWN_ID}`);
  await page.getByRole('button', { name: opts.locale === 'zh' ? '起草邮件' : 'Draft Email' }).click();
  const copy = opts.locale === 'zh' ? zh.coldEmail : en.coldEmail;
  const ready = opts.readyState === 'name-required'
    ? page.getByTestId('cold-email-name-required')
    : opts.readyState === 'error'
      ? page.getByRole('button', { name: copy.tryAgain, exact: true })
      : page.getByTestId('cold-email-footer');
  await expect(ready).toBeVisible({ timeout: 20_000 });
  return {
    supabaseConfigured: !warnings.some((w) => w.includes('NEXT_PUBLIC_SUPABASE_URL')),
  };
}

const confirmButton = (page: Page) => page.getByTestId('cold-email-confirm-sent');
const remindPrompt = (page: Page) => page.getByText('Remind me to follow up:');

test.describe('Cold Email verified-send contract (real browser)', () => {
  test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

  test('copying the draft reveals the attestation strip and writes nothing', async ({ page }) => {
    const net = await installNetwork(page);
    await openModal(page);

    await page.getByRole('button', { name: 'Copy' }).click();

    await expect(page.getByText('Did you send the email?')).toBeVisible();
    expect(net.confirms, 'Copy is not evidence of a send').toHaveLength(0);
    expect(net.otherWrites, 'no tracker write of any kind').toHaveLength(0);
    await expect(remindPrompt(page)).toBeHidden();
  });

  test('the confirmed state waits for the write, then appears', async ({ page }) => {
    const net = await installNetwork(page, { hold: true });
    const { supabaseConfigured } = await openModal(page);
    test.skip(!supabaseConfigured, 'a successful confirmation needs a reachable Supabase');
    await page.getByRole('button', { name: 'Copy' }).click();

    await confirmButton(page).click();
    await expect(confirmButton(page)).toHaveText('Recording…');
    await expect.poll(() => net.confirms.length).toBe(1);
    expect(net.confirms[0], 'the RPC names the opportunity being confirmed').toContain(KNOWN_ID);

    // Parked: nothing has persisted, so nothing may claim it has.
    await expect(remindPrompt(page)).toBeHidden();
    await expect(page.getByText('Did you send the email?')).toBeVisible();

    net.release('ok');
    await expect(remindPrompt(page)).toBeVisible();
    expect(net.confirms, 'exactly one atomic call').toHaveLength(1);
  });

  test('a write that does not land is visible, unconfirmed and retryable', async ({ page }) => {
    // Holds in BOTH configurations: with Supabase reachable the RPC is failed
    // on purpose; without it the client fails closed on its own. Either way a
    // contact that did not persist may not read as recorded.
    const net = await installNetwork(page, { hold: true });
    const { supabaseConfigured } = await openModal(page);
    await page.getByRole('button', { name: 'Copy' }).click();

    await confirmButton(page).click();
    if (supabaseConfigured) {
      await expect.poll(() => net.confirms.length).toBe(1);
      net.release('fail');
    }

    await expect(page.getByText(/nothing was saved to your tracker/)).toBeVisible();
    await expect(remindPrompt(page)).toBeHidden();
    await expect(page.getByText('Did you send the email?')).toBeVisible();
    await expect(confirmButton(page)).toHaveText('Try again');

    await confirmButton(page).click();
    if (!supabaseConfigured) {
      // The retry runs and fails the same way — the point is that the latch
      // released, not that the second attempt succeeds.
      await expect(page.getByText(/nothing was saved to your tracker/)).toBeVisible();
      await expect(remindPrompt(page)).toBeHidden();
      return;
    }
    await expect.poll(() => net.confirms.length).toBe(2);
    net.release('ok');
    await expect(remindPrompt(page)).toBeVisible();
    await expect(page.getByText(/nothing was saved to your tracker/)).toBeHidden();
  });

  test('closing and reopening starts a clean, unconfirmed session', async ({ page }) => {
    await installNetwork(page);
    const { supabaseConfigured } = await openModal(page);
    await page.getByRole('button', { name: 'Copy' }).click();
    await confirmButton(page).click();
    // Whatever the outcome was — confirmed, or a visible failure — none of it
    // may survive the close.
    await expect(
      supabaseConfigured ? remindPrompt(page) : page.getByText(/nothing was saved to your tracker/),
    ).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: 'Copy' })).toBeHidden();

    await page.getByRole('button', { name: 'Draft Email' }).click();
    await expect(page.getByRole('button', { name: 'Copy' })).toBeVisible({ timeout: 20_000 });
    await expect(remindPrompt(page), 'the previous confirmation did not survive').toBeHidden();
    await expect(page.getByText(/nothing was saved to your tracker/), 'nor the previous error').toBeHidden();
    await expect(page.getByText('Did you send the email?'), 'strip starts hidden').toBeHidden();

    await page.getByRole('button', { name: 'Copy' }).click();
    await expect(confirmButton(page), 'asked again, not shown as already recorded')
      .toHaveText('Yes — mark as contacted');
  });
});

test.describe('Cold Email — a clipboard that refuses', () => {
  // Found by running the flow above in a real browser before granting the
  // permission: `writeText` rejected, the handler aborted on that rejection,
  // and the Copy button did nothing at all — no feedback, no strip, one
  // unhandled promise rejection. jsdom's stub never rejects, so no unit
  // fixture could have found it.
  test('says so, and claims nothing it did not do', async ({ page }) => {
    const net = await installNetwork(page);
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) },
      });
    });
    await openModal(page);

    await page.getByRole('button', { name: 'Copy' }).click();

    await expect(page.getByText(/select the text above and copy it manually/)).toBeVisible();
    await expect(page.getByText('Copied'), 'nothing was copied').toBeHidden();
    await expect(page.getByText('Did you send the email?'), 'no draft in hand').toBeHidden();
    expect(net.confirms).toHaveLength(0);
  });
});


// M29: real CSS geometry, with every generated draft and AI response stubbed.
// These fixtures also retain the independent confirmation boundary: changing
// layout and copying a draft never records a send.
test.describe('Cold Email reachable editing workspace', () => {
  test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

  for (const viewport of [
    { width: 1366, height: 900 },
    { width: 390, height: 640 },
    { width: 320, height: 568 },
    { width: 1280, height: 500 },
  ]) {
    test(`${viewport.width}x${viewport.height}: long guidelines, request, footer and close remain reachable`, async ({ page }) => {
      await page.setViewportSize(viewport);
      const net = await installNetwork(page, { labType: 'dry', body: VARIANT.body.repeat(20) });
      await openModal(page);
      const workspace = page.getByTestId('cold-email-workspace');
      const guidelines = page.getByRole('region', { name: 'Writing guidelines' });
      const request = page.getByRole('textbox', { name: 'Request an edit' });
      const submit = page.getByRole('button', { name: 'Submit request' });
      const close = page.getByRole('button', { name: 'Close email editor' });

      await guidelines.scrollIntoViewIfNeeded();
      await expect(guidelines).toBeInViewport();
      // The guideline list has its own scroll range; it does not grow until it
      // pushes the request form outside a clipped flex parent.
      expect(await guidelines.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
      await guidelines.evaluate((el) => { el.scrollTop = el.scrollHeight; });
      expect(await guidelines.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
      await expect(page.getByTestId('tips-read-more')).toBeInViewport();

      await request.scrollIntoViewIfNeeded();
      await expect(request).toBeInViewport({ ratio: 1 });
      await expect(submit).toBeInViewport({ ratio: 1 });
      await request.fill('Keep the original facts and shorten the introduction.');
      await expect(submit).toBeEnabled();
      await expect(close).toBeInViewport({ ratio: 1 });

      await page.getByRole('button', { name: 'Copy', exact: true }).click();
      await expect(page.getByTestId('cold-email-footer')).toBeInViewport();
      await page.getByText('Did you send the email?').scrollIntoViewIfNeeded();
      await expect(page.getByText('Did you send the email?')).toBeInViewport();
      expect(net.confirms).toHaveLength(0);
      expect(net.otherWrites).toHaveLength(0);
      expect(await workspace.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await close.click();
      await expect(page.getByRole('dialog')).toBeHidden();
    });
  }

  test('long AI history follows replies without scrolling the editor or workspace', async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 900 });
    await installNetwork(page, { labType: 'dry', body: VARIANT.body.repeat(20) });
    await page.route('**/api/cold-email/refine', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ body: VARIANT.body.repeat(20), method: 'llm' }),
    }));
    await openModal(page);
    const workspace = page.getByTestId('cold-email-workspace');
    const editor = page.getByTestId('cold-email-editor-fields');
    const guidelines = page.getByTestId('cold-email-guidelines');
    const history = page.getByTestId('cold-email-chat-history');
    const request = page.getByRole('textbox', { name: 'Request an edit' });
    const submit = page.getByRole('button', { name: 'Submit request' });
    await editor.evaluate((el) => { el.scrollTop = 40; });
    await guidelines.evaluate((el) => { el.scrollTop = 30; });
    const before = await Promise.all([workspace, editor, guidelines].map((el) => el.evaluate((node) => node.scrollTop)));
    for (let i = 0; i < 3; i += 1) {
      await request.fill(`Request ${i}: preserve each source fact. `.repeat(20));
      await submit.click();
      await expect(request).toHaveValue('');
      await expect(history.getByText('Editing...', { exact: true })).toBeHidden();
    }
    await expect.poll(() => history.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
    expect(await Promise.all([workspace, editor, guidelines].map((el) => el.evaluate((node) => node.scrollTop)))).toEqual(before);
    await expect(request).toBeInViewport({ ratio: 1 });
    await expect(page.getByTestId('cold-email-footer')).toBeInViewport();
  });
});


test.describe('Cold Email short-screen state recovery', () => {
  test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

  for (const locale of ['en', 'zh'] as const) {
    const copy = locale === 'zh' ? zh.coldEmail : en.coldEmail;

    test(`${locale} 320x320: the missing-name action is reachable and closes the modal`, async ({ page }) => {
      await page.setViewportSize({ width: 320, height: 320 });
      const net = await installNetwork(page);
      await openModal(page, { locale, profile: { ...PROFILE, name: '' }, readyState: 'name-required' });
      const action = page.getByRole('link', { name: copy.nameRequiredCta });
      await action.scrollIntoViewIfNeeded();
      await expect(action).toBeInViewport({ ratio: 1 });
      await expect(page.getByRole('button', { name: copy.closeAria })).toBeInViewport({ ratio: 1 });
      await action.click();
      await expect(page.getByRole('dialog')).toBeHidden();
      expect(net.confirms).toHaveLength(0);
      expect(net.otherWrites).toHaveLength(0);
    });

    test(`${locale} 320x568: missing recipient and failed confirmation keep controls reachable`, async ({ page }) => {
      await page.setViewportSize({ width: 320, height: 568 });
      const net = await installNetwork(page, { hold: true, labType: 'dry', recipient: '' });
      const { supabaseConfigured } = await openModal(page, { locale });
      const openEmail = page.getByRole('button', { name: copy.openInEmail, exact: true });
      await openEmail.scrollIntoViewIfNeeded();
      await expect(openEmail).toBeInViewport({ ratio: 1 });
      await expect(openEmail).toBeDisabled();
      await page.getByRole('button', { name: copy.copy, exact: true }).click();
      expect(net.confirms).toHaveLength(0);
      expect(net.otherWrites).toHaveLength(0);
      await confirmButton(page).click();
      if (supabaseConfigured) {
        await expect.poll(() => net.confirms.length).toBe(1);
        await expect(confirmButton(page)).toHaveText(copy.confirming);
        net.release('fail');
      }
      const failure = page.getByText(copy.confirmFailed, { exact: true });
      await failure.scrollIntoViewIfNeeded();
      await expect(failure).toBeInViewport({ ratio: 1 });
      await confirmButton(page).scrollIntoViewIfNeeded();
      await expect(confirmButton(page)).toBeInViewport({ ratio: 1 });
      await expect(confirmButton(page)).toHaveText(copy.confirmRetry);
      const request = page.getByRole('textbox', { name: copy.requestLabel });
      await request.scrollIntoViewIfNeeded();
      await expect(request).toBeInViewport({ ratio: 1 });
      await expect(page.getByRole('button', { name: copy.closeAria })).toBeInViewport({ ratio: 1 });
      expect(await page.getByTestId('cold-email-workspace').evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    });
  }

  test('320x320: a generation error exposes a reachable retry', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 320 });
    await installNetwork(page);
    let attempts = 0;
    await page.route('**/api/cold-email/variants', (route) => {
      attempts += 1;
      return route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
    });
    await openModal(page, { readyState: 'error' });
    const retry = page.getByRole('button', { name: en.coldEmail.tryAgain, exact: true });
    await retry.scrollIntoViewIfNeeded();
    await expect(retry).toBeInViewport({ ratio: 1 });
    const before = attempts;
    await retry.click();
    await expect.poll(() => attempts).toBeGreaterThan(before);
    await expect(page.getByRole('button', { name: en.coldEmail.closeAria })).toBeInViewport({ ratio: 1 });
  });
});
