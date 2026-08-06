import { test, expect, type Page, type Route } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';

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

async function installNetwork(page: Page, opts: { hold?: boolean } = {}): Promise<Tracker> {
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
    body: JSON.stringify({ variants: [VARIANT], recipient_status: 'revealed', lab_type: null }),
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
        interaction_type: 'applied',
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
          interaction_type: 'applied',
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
async function openModal(page: Page): Promise<{ supabaseConfigured: boolean }> {
  const warnings: string[] = [];
  page.on('console', (msg) => { if (msg.type() === 'warning') warnings.push(msg.text()); });
  await page.addInitScript(
    ([key, value]) => { window.localStorage.setItem(key, value); },
    [STORAGE_KEYS.PROFILE, JSON.stringify(PROFILE)] as const,
  );
  await page.goto(`/opportunities/${KNOWN_ID}`);
  await page.getByRole('button', { name: 'Draft Email' }).click();
  await expect(page.getByRole('button', { name: 'Copy' })).toBeVisible({ timeout: 20_000 });
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
