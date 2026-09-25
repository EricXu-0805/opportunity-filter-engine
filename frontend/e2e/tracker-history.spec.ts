import { contactEventReceiptForRequest } from './contact-ledger-receipt';
import { test, expect, request as apiRequest, type APIRequestContext, type Page, type Route } from '@playwright/test';
import { contactReceiptForRequest } from './email-contact-receipt';
import { STORAGE_KEYS } from '../src/lib/storage-keys';

// Real production React, Auth SDK, identity owner and HTTP query construction.
// Only history/writing/confirmation responses are controlled at the network edge.
// This is not PostgreSQL trigger, hosted persistence, model quality or actual-send evidence.
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const TARGET = 'uiuc-siebel-ugresearch';
const SECOND = 'uiuc-our-general';
const UPDATED = '2001-01-02T10:00:00Z';
const CHANGED = '2019-03-04T10:00:00Z';
const LATE = '2018-05-06T10:00:00Z';
const EMPTY = 'No status history is available. The time of this status change is unknown.';
const FAILED = 'Could not load status history.';
const CONFIRM_FAILED = 'Could not confirm whether this was saved. Check your tracker before retrying.';
const pathOf = (url: string) => new URL(url).pathname;
const timeline = (page: Page) => page.getByTestId('status-timeline');
interface Owner { http: APIRequestContext; session: { access_token: string; user: { id: string } } }
function gate() { let release!: () => void; const pending = new Promise<void>(resolve => { release = resolve; }); return { pending, release }; }
function history(type = 'applied', at = CHANGED) { return [{ from_status: null, to_status: type, changed_at: at }]; }
async function account(type = 'applied'): Promise<Owner> {
  expect(new URL(STUB).hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(STUB + '/auth/v1/signup', { data: {} }); expect(signup.status()).toBe(200);
    const session = await signup.json(); const headers = { Authorization: `Bearer ${session.access_token}` };
    const saved = await http.post(STUB + '/rest/v1/rpc/commit_profile_patch_cas', { headers, data: {
      p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: {
        name: 'Tracker student 王', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
        major: 'Computer Science', grade: 'Sophomore', is_international: false, skills: [], coursework: [],
        research_interests: 'research tools', seeking_types: ['research'],
      },
    } });
    expect(saved.status()).toBe(200); expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1 });
    for (const id of [TARGET, SECOND]) {
      const tracked = await http.post(STUB + '/rest/v1/interactions', { headers, data: {
        device_id: session.user.id, opportunity_id: id, interaction_type: type, notes: 'Synthetic private tracker note',
        updated_at: UPDATED, last_contacted_at: null, remind_at: null,
      } }); expect(tracked.status()).toBe(201);
      const favorite = await http.post(STUB + '/rest/v1/favorites', { headers, data: { device_id: session.user.id, opportunity_id: id } });
      expect(favorite.status()).toBe(201);
    }
    return { http, session };
  } catch (error) { await http.dispose(); throw error; }
}
async function seed(page: Page, owner: Owner) {
  await page.addInitScript(({ session, keys }) => {
    if (localStorage.getItem('tracker-history-seeded')) return;
    localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, 'en');
    localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('tracker-history-seeded', '1');
  }, { session: owner.session, keys: STORAGE_KEYS });
}
function writes(page: Page) {
  const values: string[] = [];
  page.on('request', request => {
    if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(request.method())
      && /\/(?:profiles|interactions|interaction_status_changes|commit_profile_patch_cas|confirm_interaction_contact|confirm_contact_event|set_interaction_reminder)$/.test(pathOf(request.url()))) values.push(pathOf(request.url()));
  });
  return values;
}
async function openTimeline(page: Page, status = 'Applied') {
  await expect(page.getByRole('button', { name: status, exact: true })).toHaveAttribute('aria-pressed', 'true');
  const toggle = page.getByRole('button', { name: /^Records, notes & reminders/ });
  await expect(toggle).toBeVisible();
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await expect(timeline(page)).toBeVisible();
}
async function settleFrames(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}
async function fulfillLate(page: Page, route: Route, rows: ReturnType<typeof history>) {
  try { await route.fulfill({ json: rows }); }
  catch (error) { if (!page.isClosed() && !route.request().failure()) throw error; }
}

test('an authoritative empty status history shows current status without assigning the interaction update time', async ({ page }, info) => {
  const owner = await account();
  try {
    await seed(page, owner); const mutations = writes(page); let reads = 0;
    await page.route('**/rest/v1/interaction_status_changes?**', route => {
      expect(new URL(route.request().url()).searchParams.get('device_id')).toBe(`eq.${owner.session.user.id}`);
      reads += 1; return route.fulfill({ status: 200, json: [] });
    });
    await page.goto(`/opportunities/${TARGET}`); await openTimeline(page);
    await expect(timeline(page)).toContainText(EMPTY);
    await expect(timeline(page)).toContainText('Current status'); await expect(timeline(page)).toContainText('Applied');
    await expect(timeline(page)).not.toContainText(UPDATED.slice(0, 10)); await expect(timeline(page).locator('li')).toHaveCount(0);
    expect(reads).toBe(1); expect(mutations).toEqual([]);
    await timeline(page).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('tracker-empty-history.png') });
    await page.getByRole('button', { name: 'Switch to Chinese', exact: true }).click();
    await expect(timeline(page)).toContainText('暂无状态历史记录，无法确认此状态的变更时间。');
    await expect(timeline(page)).toContainText('当前状态'); await expect(timeline(page)).toContainText('已申请');
    await expect(timeline(page)).not.toContainText(UPDATED.slice(0, 10)); expect(mutations).toEqual([]);
    await timeline(page).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('tracker-empty-history-zh.png') });
  } finally { await owner.http.dispose(); }
});

test('a history HTTP failure is retryable and only successful history supplies the status-change time', async ({ page }, info) => {
  const owner = await account();
  try {
    await seed(page, owner); const mutations = writes(page); let reads = 0;
    await page.route('**/rest/v1/interaction_status_changes?**', route => {
      reads += 1;
      return reads === 1 ? route.fulfill({ status: 500, json: { message: 'controlled history failure' } }) : route.fulfill({ json: history() });
    });
    await page.goto(`/opportunities/${TARGET}`); await openTimeline(page);
    await expect(timeline(page).getByRole('alert')).toContainText(FAILED);
    await expect(timeline(page)).toContainText('Current status'); await expect(timeline(page)).not.toContainText(EMPTY);
    await expect(timeline(page)).not.toContainText(UPDATED.slice(0, 10));
    await timeline(page).getByRole('button', { name: 'Retry status history', exact: true }).click();
    await expect(timeline(page).locator('li')).toHaveCount(1); await expect(timeline(page)).toContainText(CHANGED.slice(0, 10));
    await expect(timeline(page)).not.toContainText(UPDATED.slice(0, 10)); await expect(timeline(page).getByRole('alert')).toHaveCount(0);
    expect(reads).toBe(2); expect(mutations).toEqual([]);
    await timeline(page).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('tracker-verified-history.png') });
  } finally { await owner.http.dispose(); }
});

test('client navigation to another opportunity retires the former target history response', async ({ page }) => {
  const owner = await account(); const held = gate(); let started = false, settled = false;
  try {
    await seed(page, owner); const mutations = writes(page);
    await page.route('**/rest/v1/interaction_status_changes?**', async route => {
      const id = new URL(route.request().url()).searchParams.get('opportunity_id');
      if (id === `eq.${TARGET}`) { started = true; await held.pending; try { await fulfillLate(page, route, history('rejected', LATE)); } finally { settled = true; } }
      else { expect(id).toBe(`eq.${SECOND}`); await route.fulfill({ json: history('applied') }); }
    });
    await page.goto('/favorites'); await page.locator(`a[href="/opportunities/${TARGET}"]`).first().click();
    await openTimeline(page); await expect.poll(() => started).toBe(true);
    await expect(timeline(page).getByRole('status')).toContainText('Loading status history');
    await page.goBack(); await expect(page).toHaveURL(/\/favorites$/);
    await page.locator(`a[href="/opportunities/${SECOND}"]`).first().click();
    await expect(page).toHaveURL(new RegExp(`/opportunities/${SECOND}$`)); await openTimeline(page);
    await expect(timeline(page)).toContainText(CHANGED.slice(0, 10));
    held.release(); await expect.poll(() => settled).toBe(true); await settleFrames(page);
    await expect(timeline(page)).toContainText(CHANGED.slice(0, 10)); await expect(timeline(page)).not.toContainText(LATE.slice(0, 10));
    await expect(timeline(page)).not.toContainText('Rejected'); expect(mutations).toEqual([]);
  } finally { held.release(); await owner.http.dispose(); }
});

test('a real SDK owner change discards the old owner history, including a late response', async ({ page, context }) => {
  const first = await account(), second = await account('replied'); const held = gate(); let started = false, settled = false;
  try {
    await seed(page, first); const mutations = writes(page);
    await page.route('**/rest/v1/interaction_status_changes?**', async route => {
      const id = new URL(route.request().url()).searchParams.get('device_id');
      if (id === `eq.${first.session.user.id}`) { started = true; await held.pending; try { await fulfillLate(page, route, history('rejected', LATE)); } finally { settled = true; } }
      else { expect(id).toBe(`eq.${second.session.user.id}`); await route.fulfill({ json: history('replied') }); }
    });
    await page.goto(`/opportunities/${TARGET}`); await openTimeline(page); await expect.poll(() => started).toBe(true);
    const secondProfile = page.waitForResponse(response => {
      const url = new URL(response.url());
      return url.pathname === '/rest/v1/profiles' && url.searchParams.get('id') === `eq.${second.session.user.id}` && response.status() === 200;
    });
    const other = await context.newPage();
    try {
      await other.goto('/robots.txt');
      await other.evaluate(session => {
        localStorage.setItem('ofe_auth', JSON.stringify(session));
        const channel = new BroadcastChannel('ofe_auth'); channel.postMessage({ event: 'SIGNED_IN', session }); channel.close();
      }, second.session);
      await expect.poll(() => page.evaluate(key => localStorage.getItem(key), STORAGE_KEYS.LOCAL_IDENTITY_OWNER)).toContain(second.session.user.id);
    } finally { await other.close(); }
    await secondProfile; await settleFrames(page);
    // A new owner may be asked to confirm their school; defer through the UI.
    const school = page.getByRole('dialog', { name: 'Confirm your school', exact: true });
    if (await school.isVisible()) await school.getByRole('button', { name: 'Close', exact: true }).click();
    await openTimeline(page, 'Got reply'); await expect(timeline(page)).toContainText(CHANGED.slice(0, 10));
    held.release(); await expect.poll(() => settled).toBe(true); await settleFrames(page);
    await expect(timeline(page)).toContainText('Got reply'); await expect(timeline(page)).not.toContainText('Rejected');
    await expect(timeline(page)).not.toContainText(LATE.slice(0, 10)); expect(mutations).toEqual([]);
  } finally { held.release(); await first.http.dispose(); await second.http.dispose(); }
});

async function referralDraft(page: Page) {
  const panel = page.getByTestId('email-contact-context-panel'); await panel.locator('summary').click();
  await panel.getByRole('combobox', { name: 'Contact purpose', exact: true }).selectOption('referral');
  await panel.getByRole('textbox', { name: 'Who referred you? (required)', exact: true }).fill('Pat 李');
  await panel.getByRole('textbox', { name: 'What did they actually say or suggest? (required)', exact: true }).fill('Pat suggested I ask about research opportunities.');
  await panel.getByRole('checkbox', { name: 'I confirm these referral details are accurate and I may mention this person in the draft.', exact: true }).check();
  await panel.getByRole('button', { name: 'Apply background to this draft', exact: true }).click();
  await page.getByRole('button', { name: 'Regenerate from updated materials', exact: true }).click();
  await expect(page.locator('#cold-email-body')).toHaveValue('Referral draft 王');
}

test.describe('Send-error ownership after a new email background', () => {
  test.use({ permissions: ['clipboard-read', 'clipboard-write'] });
  for (const late of [false, true]) test(`a failed old confirmation ${late ? 'arriving after' : 'received before'} rebuilding does not label the new draft as failed`, async ({ page }, info) => {
    const owner = await account(); const held = gate(); let confirms = 0, settled = false;
    try {
      await seed(page, owner); const mutations = writes(page);
      await page.route('**/api/cold-email**', route => route.fulfill({ status: 503, json: {} }));
      await page.route('**/api/cold-email/variants', route => {
        const request = route.request().postDataJSON(); const receipt = contactReceiptForRequest(request);
        const variant = { id: 'history-template', label: 'Checked template', subject: 'Careful request 王',
          body: request.contact_context?.purpose === 'referral' ? 'Referral draft 王' : 'First-contact draft 王',
          recipient_email: 'lab@example.edu', mailto_link: '', contact_context_receipt: receipt };
        return route.fulfill({ json: { opportunity_id: request.opportunity_id, target_version: request.expected_target_version,
          contact_context_receipt: receipt, variants: [variant], recipient_status: 'revealed', pipeline_version: 'w12.8', corpus_version: 'history-browser' } });
      });
      await page.route('**/rest/v1/rpc/confirm_contact_event', async route => {
        confirms += 1;
        if (confirms === 1) {
          if (late) await held.pending;
          try { await route.fulfill({ status: 500, json: { message: 'controlled old confirmation failure' } }); } finally { settled = true; }
        } else {
          expect(confirms).toBe(2);
          await route.fulfill({ json: contactEventReceiptForRequest(route.request().postDataJSON(), { confirmedAt: '2026-09-25T08:00:00Z' }) });
        }
      });
      await page.goto(`/opportunities/${TARGET}`); await page.getByRole('button', { name: 'Draft email', exact: true }).click();
      await expect(page.locator('#cold-email-body')).toHaveValue('First-contact draft 王');
      await page.getByRole('button', { name: 'Copy', exact: true }).click(); await page.getByTestId('cold-email-confirm-sent').click();
      await expect.poll(() => confirms).toBe(1);
      if (!late) await expect(page.getByText(CONFIRM_FAILED, { exact: true })).toBeVisible();
      await referralDraft(page);
      if (late) { held.release(); await expect.poll(() => settled).toBe(true); await settleFrames(page); }
      await page.getByRole('button', { name: 'Copy', exact: true }).click();
      await expect(page.getByTestId('cold-email-confirm-sent')).toBeEnabled();
      await expect(page.getByTestId('cold-email-confirm-sent')).toHaveText('Yes — mark as contacted');
      await expect(page.getByText(CONFIRM_FAILED, { exact: true })).toHaveCount(0);
      expect(confirms).toBe(1); expect(mutations).toEqual(['/rest/v1/rpc/confirm_contact_event']);
      await page.getByTestId('cold-email-confirm-sent').scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath(`new-draft-old-confirm-${late ? 'late' : 'early'}-failure.png`) });
      await page.getByTestId('cold-email-confirm-sent').click();
      await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
      expect(confirms).toBe(2); expect(mutations).toEqual(['/rest/v1/rpc/confirm_contact_event', '/rest/v1/rpc/confirm_contact_event']);
    } finally { held.release(); await owner.http.dispose(); }
  });
});
