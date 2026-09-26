import { test, expect, request as apiRequest, type APIRequestContext, type Page } from '@playwright/test';
import { contactReceiptForRequest } from './email-contact-receipt';
import { contactEventReceiptForRequest, type ContactEventRequest } from './contact-ledger-receipt';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { en, zh } from '../src/i18n/dictionaries';

// Production React + Auth SDK + real HTTP. Only network responses are fixtures.
// The in-test ledger models persistence/replay; this does not verify PostgreSQL,
// hosted storage, provider sending or actual delivery.
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const TARGET = 'uiuc-siebel-ugresearch';
const BASE_TIME = '2026-09-25T11:00:00.000Z';
const DRAFT = { id: 'ledger-template', label: 'Checked template', subject: 'Research tools question',
  body: 'Dear Professor,\nI built a research tool. Could we discuss your lab?\nBest,\nStudent 王',
  recipient_email: 'lab@example.edu', mailto_link: '' };
type Receipt = ReturnType<typeof contactEventReceiptForRequest>;
type SavedEvent = Receipt['event'];
interface Owner { http: APIRequestContext; session: { access_token: string; user: { id: string } } }
async function account(): Promise<Owner> {
  expect(new URL(STUB).hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(STUB + '/auth/v1/signup', { data: {} }); expect(signup.status()).toBe(200);
    const session = await signup.json();
    const saved = await http.post(STUB + '/rest/v1/rpc/commit_profile_patch_cas', {
      headers: { Authorization: `Bearer ${session.access_token}` }, data: {
        p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: {
          name: 'Student 王', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
          major: 'Computer Science', grade: 'Sophomore', is_international: false, skills: ['Python'], coursework: ['CS 225'],
          research_interests: 'research tools', seeking_types: ['research'],
        },
      },
    });
    expect(saved.status()).toBe(200); expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1 });
    return { http, session };
  } catch (error) { await http.dispose(); throw error; }
}
async function seed(page: Page, owner: Owner, locale: 'en' | 'zh' = 'en') {
  await page.context().addCookies([{ name: STORAGE_KEYS.LOCALE, value: locale, url: `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3100)}` }]);
  await page.addInitScript(({ session, keys, locale }) => {
    if (localStorage.getItem('contact-ledger-seeded')) return;
    localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, locale);
    localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('contact-ledger-seeded', '1');
  }, { session: owner.session, keys: STORAGE_KEYS, locale });
}
async function network(page: Page, owner: Owner, options: { firstWriteUnknown?: boolean; historyFailsOnce?: boolean } = {}) {
  const state = { requests: [] as ContactEventRequest[], records: new Map<string, SavedEvent>(), summary: null as Receipt['interaction'],
    reads: 0, removals: 0, otherWrites: [] as string[] };
  await page.route('**/api/cold-email**', route => route.fulfill({ status: 503, json: {} }));
  await page.route('**/api/cold-email/variants', route => {
    const request = route.request().postDataJSON(); const receipt = contactReceiptForRequest(request);
    return route.fulfill({ json: { opportunity_id: request.opportunity_id, target_version: request.expected_target_version,
      contact_context_receipt: receipt, variants: [{ ...DRAFT, contact_context_receipt: receipt }], recipient_status: 'revealed', lab_type: null,
      pipeline_version: 'w12.8', corpus_version: 'contact-ledger-browser' } });
  });
  // This older Tracker attachment panel is adjacent to email history. Keep its
  // empty fixture explicit; an unimplemented Storage endpoint must not look empty.
  await page.route('**/storage/v1/object/list/tracker-attachments', route => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON().prefix).toBe(`${owner.session.user.id}/${TARGET}`);
    return route.fulfill({ json: [] });
  });
  await page.route('**/rest/v1/interaction_status_changes?**', route => route.fulfill({ json: [] }));
  await page.route('**/rest/v1/interactions**', async route => {
    const method = route.request().method();
    if (method === 'DELETE') { state.summary = null; state.removals += 1; await route.fulfill({ status: 204 }); return; }
    if (method !== 'GET' && method !== 'HEAD') state.otherWrites.push(method);
    await route.fulfill({ json: state.summary ? [state.summary] : [] });
  });
  await page.route('**/rest/v1/contact_events?**', async route => {
    const params = new URL(route.request().url()).searchParams;
    expect(route.request().method()).toBe('GET');
    expect(params.get('device_id')).toBe(`eq.${owner.session.user.id}`);
    expect(params.get('opportunity_id')).toBe(`eq.${TARGET}`);
    expect(params.get('order')).toBe('confirmed_at.desc,event_id.desc');
    state.reads += 1;
    if (options.historyFailsOnce && state.reads === 1) { await route.fulfill({ status: 500, json: { message: 'controlled ledger read failure' } }); return; }
    let rows = [...state.records.values()].sort((a, b) => b.confirmed_at.localeCompare(a.confirmed_at) || b.event_id.localeCompare(a.event_id));
    const cursor = params.get('or');
    if (cursor) {
      const matched = /^\(confirmed_at\.lt\.([^,]+),and\(confirmed_at\.eq\.([^,]+),event_id\.lt\.([^)]*)\)\)$/.exec(cursor);
      expect(matched).not.toBeNull(); expect(matched![1]).toBe(matched![2]);
      rows = rows.filter(row => row.confirmed_at < matched![1] || (row.confirmed_at === matched![1] && row.event_id < matched![3]));
    }
    await route.fulfill({ json: rows.slice(0, Number(params.get('limit'))) });
  });
  await page.route('**/rest/v1/rpc/confirm_contact_event', async route => {
    const input = route.request().postDataJSON() as ContactEventRequest;
    expect(input.p_expected_device_id).toBe(owner.session.user.id); expect(input.p_opportunity_id).toBe(TARGET);
    state.requests.push(structuredClone(input));
    const prior = state.records.get(input.p_event_id);
    if (prior) {
      const replay = contactEventReceiptForRequest(input, { replayed: true, confirmedAt: prior.confirmed_at, interaction: state.summary });
      expect(replay.event).toEqual(prior);
      await route.fulfill({ json: replay }); return;
    }
    const receipt = contactEventReceiptForRequest(input, { confirmedAt: new Date(Date.parse(BASE_TIME) + state.records.size * 1000).toISOString() });
    state.records.set(input.p_event_id, receipt.event); state.summary = receipt.interaction;
    if (options.firstWriteUnknown && state.requests.length === 1) {
      await route.fulfill({ status: 500, json: { message: 'response lost after stored fixture event' } }); return;
    }
    await route.fulfill({ json: receipt });
  });
  return state;
}
async function openEmail(page: Page, locale: 'en' | 'zh' = 'en') {
  await page.getByRole('button', { name: locale === 'zh' ? '起草邮件' : 'Draft email', exact: true }).click();
  await expect(page.locator('#cold-email-body')).toHaveValue(DRAFT.body);
  await expect(page.getByTestId('cold-email-footer')).toBeVisible();
}
async function copyAndConfirm(page: Page, locale: 'en' | 'zh' = 'en') {
  await page.getByRole('button', { name: (locale === 'zh' ? zh : en).coldEmail.copy, exact: true }).click();
  await page.getByTestId('cold-email-confirm-sent').click();
}
async function openHistory(page: Page, locale: 'en' | 'zh' = 'en') {
  const copy = (locale === 'zh' ? zh : en).detail.tracker;
  const toggle = page.getByRole('button', { name: new RegExp(`${copy.addButton}|${copy.openButton}`) });
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await expect(page.getByTestId('contact-history')).toBeVisible();
  return page.getByTestId('contact-history');
}
async function closeEmail(page: Page, locale: 'en' | 'zh' = 'en') {
  await page.getByRole('button', { name: (locale === 'zh' ? zh : en).coldEmail.closeAria, exact: true }).click();
}

test.describe('Contact event snapshots through the real browser', () => {
  test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

  test('edited content and declared send time persist as a distinct plain-text snapshot with source versions', async ({ page }, info) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner);
      await page.goto(`/opportunities/${TARGET}`); await openEmail(page);
      const body = 'My actual message 王\n<img src=x onerror="alert(1)">\nhttps://example.edu/' + 'x'.repeat(180);
      await page.locator('#cold-email-to').fill('actual-recipient@example.edu');
      await page.locator('#cold-email-subject').fill('My actual subject 王'); await page.locator('#cold-email-body').fill(body);
      await page.getByTestId('contact-record-details').locator('summary').click();
      await page.locator('#cold-email-sent-at').fill('2026-08-01T10:30');
      const actual = await page.evaluate(() => new Date('2026-08-01T10:30').toISOString());
      await copyAndConfirm(page); await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
      expect(net.requests).toHaveLength(1); expect(net.records.size).toBe(1);
      expect(net.requests[0]).toMatchObject({ p_recipient: 'actual-recipient@example.edu', p_subject: 'My actual subject 王', p_body: body, p_actual_sent_at: actual });
      expect(net.requests[0].p_materials.map(ref => ref.kind)).toEqual(['profile', 'target', 'contact_context']);
      await closeEmail(page); const history = await openHistory(page);
      await history.locator('ol > li > details > summary').click();
      await expect(history).toContainText(body); await expect(history).toContainText('actual-recipient@example.edu');
      await expect(history.locator('time').nth(0)).toHaveAttribute('datetime', actual);
      await expect(history.locator('time').nth(1)).toHaveAttribute('datetime', BASE_TIME);
      await expect(history).toContainText(en.detail.tracker.contactHistory.hint);
      await expect(history.getByTestId('contact-event-sources')).not.toHaveAttribute('open');
      await history.getByTestId('contact-event-sources').locator('summary').click();
      await expect(history.getByText(en.detail.tracker.contactHistory.materialsHint, { exact: true })).toBeVisible();
      await expect(history.locator('img,script,a')).toHaveCount(0);
      expect(await history.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await history.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('contact-snapshot-details.png') });
      expect(net.otherWrites).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('an unknown stored result retries and survives refresh with one stable event id', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner, { firstWriteUnknown: true });
      await page.goto(`/opportunities/${TARGET}`); await openEmail(page); await copyAndConfirm(page);
      await expect(page.getByText(en.coldEmail.confirmFailed, { exact: true })).toBeVisible();
      expect(net.records.size).toBe(1); expect(net.requests).toHaveLength(1);
      await page.getByTestId('cold-email-confirm-sent').click();
      await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
      expect(net.requests).toHaveLength(2); expect(net.requests[1].p_event_id).toBe(net.requests[0].p_event_id);
      await page.reload(); await openEmail(page); await copyAndConfirm(page);
      await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
      expect(net.requests).toHaveLength(3); expect(new Set(net.requests.map(request => request.p_event_id)).size).toBe(1); expect(net.records.size).toBe(1);
      await closeEmail(page); const history = await openHistory(page); await expect(history.locator('ol > li > details')).toHaveCount(1);
    } finally { await owner.http.dispose(); }
  });

  test('a changed body needs a new confirmation and keeps both snapshots', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner);
      await page.goto(`/opportunities/${TARGET}`); await openEmail(page); await copyAndConfirm(page);
      await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
      await page.locator('#cold-email-body').fill('Second email with a different question.');
      expect(net.records.size).toBe(1);
      await copyAndConfirm(page); await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
      expect(net.requests).toHaveLength(2); expect(net.requests[1].p_event_id).not.toBe(net.requests[0].p_event_id);
      expect([...net.records.values()].map(event => event.body)).toEqual([DRAFT.body, 'Second email with a different question.']);
      await closeEmail(page); const history = await openHistory(page); await expect(history.locator('ol > li > details')).toHaveCount(2);
      await history.locator('ol > li > details > summary').first().click(); await expect(history).toContainText('Second email with a different question.');
    } finally { await owner.http.dispose(); }
  });

  test('invalid recipient, empty subject/body and future time cannot write a contact event', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner);
      await page.goto(`/opportunities/${TARGET}`); await openEmail(page);
      for (const [selector, invalid, restore] of [
        ['#cold-email-to', 'not-an-email', DRAFT.recipient_email], ['#cold-email-subject', ' ', DRAFT.subject], ['#cold-email-body', ' ', DRAFT.body],
      ]) {
        await page.locator(selector).fill(invalid); await copyAndConfirm(page);
        await expect(page.getByText(en.coldEmail.contactInvalid, { exact: true })).toBeVisible();
        expect(net.requests).toHaveLength(0); expect(net.records.size).toBe(0);
        await page.locator(selector).fill(restore);
      }
      await page.getByTestId('contact-record-details').locator('summary').click(); await page.locator('#cold-email-sent-at').fill('2099-01-01T12:00');
      await copyAndConfirm(page); await expect(page.getByText(en.coldEmail.contactInvalid, { exact: true })).toBeVisible();
      expect(net.requests).toHaveLength(0); expect(net.records.size).toBe(0); expect(net.otherWrites).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('removing the current tracker summary keeps its snapshot and replay does not recreate the summary', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner);
      await page.goto(`/opportunities/${TARGET}`); await openEmail(page); await copyAndConfirm(page);
      await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0); await closeEmail(page);
      await page.getByRole('button', { name: 'Remove from Tracker', exact: true }).click();
      await page.getByRole('dialog', { name: 'Remove from Tracker', exact: true }).getByRole('button', { name: 'Remove', exact: true }).click();
      await expect.poll(() => net.removals).toBe(1); expect(net.summary).toBeNull();
      await expect(page.getByRole('button', { name: 'Contacted', exact: true })).toHaveAttribute('aria-pressed', 'false');
      const history = await openHistory(page); await expect(history.locator('ol > li > details')).toHaveCount(1);
      await page.reload(); await openEmail(page); await copyAndConfirm(page);
      await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
      expect(net.requests).toHaveLength(2); expect(net.requests[1].p_event_id).toBe(net.requests[0].p_event_id);
      expect(net.summary).toBeNull(); expect(net.records.size).toBe(1);
      await closeEmail(page); await expect(page.getByRole('button', { name: 'Contacted', exact: true })).toHaveAttribute('aria-pressed', 'false');
      await expect((await openHistory(page)).locator('ol > li > details')).toHaveCount(1);
    } finally { await owner.http.dispose(); }
  });

  test('a replay clears a stale local status after another device removed the summary', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner);
      await page.goto(`/opportunities/${TARGET}`); await openEmail(page); await copyAndConfirm(page);
      await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0); await closeEmail(page);
      await expect(page.getByRole('button', { name: 'Contacted', exact: true })).toHaveAttribute('aria-pressed', 'true');
      const history = await openHistory(page); await expect(history.locator('ol > li > details')).toHaveCount(1);
      // Network fixture changes outside this page, modelling another device's deletion.
      net.summary = null;
      await openEmail(page); await copyAndConfirm(page);
      await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0); await closeEmail(page);
      await expect(page.getByRole('button', { name: 'Contacted', exact: true })).toHaveAttribute('aria-pressed', 'false');
      await expect(history.locator('ol > li > details')).toHaveCount(1);
      expect(net.summary).toBeNull(); expect(net.removals).toBe(0); expect(net.records.size).toBe(1);
      expect(net.requests).toHaveLength(2); expect(net.requests[1].p_event_id).toBe(net.requests[0].p_event_id);
    } finally { await owner.http.dispose(); }
  });

  test('an unchanged replay refreshes an open history even when the summary timestamp did not change', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner, { historyFailsOnce: true });
      await page.goto(`/opportunities/${TARGET}`); await openEmail(page); await copyAndConfirm(page);
      await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0); await closeEmail(page);
      const history = await openHistory(page);
      await expect(history.getByRole('alert')).toContainText(en.detail.tracker.contactHistory.error);
      const summaryBeforeReplay = structuredClone(net.summary);
      await openEmail(page); await copyAndConfirm(page);
      await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0); await closeEmail(page);
      await expect(history.getByRole('alert')).toHaveCount(0);
      await expect(history.locator('ol > li > details')).toHaveCount(1);
      expect(net.summary).toEqual(summaryBeforeReplay); expect(net.requests).toHaveLength(2); expect(net.records.size).toBe(1);
      expect(net.reads).toBe(2);
    } finally { await owner.http.dispose(); }
  });

  test('history explicitly pages past twenty records without hiding older messages', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner);
      for (let index = 0; index < 21; index += 1) {
        const receipt = contactEventReceiptForRequest({ p_expected_device_id: owner.session.user.id,
          p_event_id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`, p_opportunity_id: TARGET,
          p_recipient: DRAFT.recipient_email, p_subject: `Saved message ${index}`, p_body: `Saved body ${index}`,
          p_actual_sent_at: null, p_materials: [],
        }, { confirmedAt: new Date(Date.parse(BASE_TIME) + index * 1000).toISOString() });
        net.records.set(receipt.event.event_id, receipt.event);
      }
      await page.goto(`/opportunities/${TARGET}`); const history = await openHistory(page);
      await expect(history.locator('ol > li > details')).toHaveCount(20);
      await expect(history).toContainText('Records shown: 20. More records are available.');
      await expect(history.getByText('Saved message 0', { exact: true })).toHaveCount(0);
      await history.getByRole('button', { name: 'Load older records', exact: true }).click();
      await expect(history.locator('ol > li > details')).toHaveCount(21);
      await expect(history.getByText('Saved message 0', { exact: true })).toBeVisible();
      await expect(history).toContainText('Saved records: 21');
      await expect(history.getByRole('button', { name: 'Load older records', exact: true })).toHaveCount(0);
      expect(net.reads).toBe(2); expect(net.requests).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('Chinese history failure retries safely and saved text fits a narrow viewport', async ({ page }, info) => {
    const owner = await account();
    try {
      await page.setViewportSize({ width: 320, height: 568 }); await seed(page, owner, 'zh');
      const net = await network(page, owner, { historyFailsOnce: true });
      await page.goto(`/opportunities/${TARGET}`); await openEmail(page, 'zh');
      await page.locator('#cold-email-body').fill('实际发送的正文：王同学\n<svg onload=alert(1)>\n' + '长'.repeat(160));
      await copyAndConfirm(page, 'zh'); await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0); await closeEmail(page, 'zh');
      const history = await openHistory(page, 'zh');
      await expect(history.getByRole('alert')).toContainText(zh.detail.tracker.contactHistory.error);
      await expect(history).not.toContainText(zh.detail.tracker.contactHistory.empty);
      await history.getByRole('button', { name: zh.detail.tracker.contactHistory.retry, exact: true }).click();
      await history.locator('ol > li > details > summary').click(); await expect(history).toContainText('实际发送的正文：王同学');
      await expect(history).toContainText(zh.detail.tracker.contactHistory.sentUnknown);
      await expect(history.locator('svg,script,img')).toHaveCount(0); expect(net.reads).toBe(2);
      expect(await history.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await history.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('contact-snapshot-zh-mobile.png') });
    } finally { await owner.http.dispose(); }
  });
});
