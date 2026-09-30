import { test, expect, request as apiRequest, type APIRequestContext, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { en, zh } from '../src/i18n/dictionaries';

// Real production React/Auth SDK/HTTP with a page-scoped response fixture.
// This tests the UI contract, not hosted PostgreSQL, actual submission or delivery.
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const TARGET = 'uiuc-siebel-ugresearch';
const AT = '2026-09-25T11:00:00.000Z';
interface Owner { http: APIRequestContext; session: { access_token: string; user: { id: string } } }
interface Input {
  p_expected_device_id: string; p_event_id: string; p_opportunity_id: string;
  p_channel: 'web_form' | 'email' | 'other'; p_destination: string; p_actual_submitted_at: string | null;
  p_notes: string | null; p_result_note: string | null; p_next_step: string | null;
}
function event(input: Input, at = AT) {
  return { event_id: input.p_event_id, device_id: input.p_expected_device_id, opportunity_id: input.p_opportunity_id,
    channel: input.p_channel, destination: input.p_destination, actual_submitted_at: input.p_actual_submitted_at,
    notes: input.p_notes, result_note: input.p_result_note, next_step: input.p_next_step,
    confirmed_at: at, confirmation_source: 'user_reported' };
}
function summary(owner: Owner, type = 'applied') {
  return { device_id: owner.session.user.id, opportunity_id: TARGET, interaction_type: type,
    notes: null as string | null, remind_at: null, last_contacted_at: null, updated_at: AT };
}
async function account(): Promise<Owner> {
  expect(new URL(STUB).hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const response = await http.post(STUB + '/auth/v1/signup', { data: {} }); expect(response.status()).toBe(200);
    return { http, session: await response.json() };
  } catch (error) { await http.dispose(); throw error; }
}
async function seed(page: Page, owner: Owner, locale: 'en' | 'zh' = 'en') {
  await page.context().addCookies([{ name: STORAGE_KEYS.LOCALE, value: locale, url: `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3100)}` }]);
  await page.addInitScript(({ session, keys, locale }) => {
    if (localStorage.getItem('application-ledger-seeded')) return;
    localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, locale);
    localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('application-ledger-seeded', '1');
  }, { session: owner.session, keys: STORAGE_KEYS, locale });
}
async function network(page: Page, owner: Owner, options: { unknown?: 'stored' | 'absent'; historyFailsOnce?: boolean } = {}) {
  const state = { requests: [] as Input[], records: new Map<string, ReturnType<typeof event>>(), summary: null as ReturnType<typeof summary> | null,
    reads: 0, cursorReads: 0, lookups: 0, statusWrites: 0, contactWrites: 0 };
  await page.route('**/api/cold-email**', route => route.fulfill({ status: 503, json: {} }));
  await page.route('**/rest/v1/rpc/confirm_contact_event', route => { state.contactWrites += 1; return route.fulfill({ status: 500, json: {} }); });
  await page.route('**/rest/v1/interaction_status_changes?**', route => route.fulfill({ json: [] }));
  await page.route('**/rest/v1/contact_events?**', route => route.fulfill({ json: [] }));
  await page.route('**/rest/v1/interactions**', async route => {
    if (route.request().method() === 'DELETE') { state.summary = null; await route.fulfill({ status: 204 }); return; }
    if (route.request().method() === 'POST') {
      const input = route.request().postDataJSON(); state.statusWrites += 1;
      state.summary = { ...summary(owner), ...input }; await route.fulfill({ status: 201, json: state.summary }); return;
    }
    await route.fulfill({ json: state.summary ? [state.summary] : [] });
  });
  await page.route('**/rest/v1/application_events?**', async route => {
    const params = new URL(route.request().url()).searchParams;
    expect(route.request().method()).toBe('GET'); expect(params.get('device_id')).toBe(`eq.${owner.session.user.id}`);
    expect(params.get('opportunity_id')).toBe(`eq.${TARGET}`);
    const id = params.get('event_id');
    if (id) { state.lookups += 1; const saved = state.records.get(id.slice(3)); await route.fulfill({ json: saved ? [saved] : [] }); return; }
    state.reads += 1;
    if (options.historyFailsOnce && state.reads === 1) { await route.fulfill({ status: 500, json: { message: 'private database failure' } }); return; }
    expect(params.get('order')).toBe('confirmed_at.desc,event_id.desc');
    let rows = [...state.records.values()].sort((a, b) => b.confirmed_at.localeCompare(a.confirmed_at) || b.event_id.localeCompare(a.event_id));
    const cursor = params.get('or');
    if (cursor) {
      state.cursorReads += 1;
      const matched = /^\(confirmed_at\.lt\.([^,]+),and\(confirmed_at\.eq\.([^,]+),event_id\.lt\.([^)]*)\)\)$/.exec(cursor);
      expect(matched).not.toBeNull(); expect(matched![1]).toBe(matched![2]);
      rows = rows.filter(row => row.confirmed_at < matched![1] || (row.confirmed_at === matched![1] && row.event_id < matched![3]));
    }
    await route.fulfill({ json: rows.slice(0, Number(params.get('limit'))) });
  });
  await page.route('**/rest/v1/rpc/confirm_application_event', async route => {
    const input = route.request().postDataJSON() as Input;
    expect(input.p_expected_device_id).toBe(owner.session.user.id); expect(input.p_opportunity_id).toBe(TARGET);
    state.requests.push(structuredClone(input));
    const prior = state.records.get(input.p_event_id);
    if (prior) {
      expect(event(input, prior.confirmed_at)).toEqual(prior);
      await route.fulfill({ json: { event: prior, interaction: state.summary, replayed: true } }); return;
    }
    if (options.unknown === 'absent' && state.requests.length === 1) {
      await route.fulfill({ status: 500, json: {} }); return;
    }
    const saved = event(input, new Date(Date.parse(AT) + state.records.size * 1000).toISOString());
    state.records.set(saved.event_id, saved);
    if (!state.summary || ['saved', 'contacted'].includes(state.summary.interaction_type)) state.summary = summary(owner);
    if (options.unknown === 'stored' && state.requests.length === 1) { await route.fulfill({ status: 500, json: {} }); return; }
    await route.fulfill({ json: { event: saved, interaction: state.summary, replayed: false } });
  });
  return state;
}
const editor = (page: Page) => page.locator('#application-record-editor');
async function openForm(page: Page, locale: 'en' | 'zh' = 'en') {
  await page.getByRole('button', { name: (locale === 'zh' ? zh : en).applicationRecord.open, exact: true }).click();
  await expect(editor(page)).toBeVisible();
}
async function fill(page: Page, destination = 'https://example.edu/application', locale: 'en' | 'zh' = 'en') {
  await editor(page).getByLabel((locale === 'zh' ? zh : en).applicationRecord.destination, { exact: true }).fill(destination);
}
async function save(page: Page, locale: 'en' | 'zh' = 'en') {
  const copy = (locale === 'zh' ? zh : en).applicationRecord;
  await editor(page).getByRole('checkbox', { name: copy.attestation, exact: true }).check();
  await editor(page).getByRole('button', { name: copy.save, exact: true }).click();
}
async function saved(page: Page, locale: 'en' | 'zh' = 'en') {
  await expect(editor(page).getByRole('status')).toHaveText((locale === 'zh' ? zh : en).applicationRecord.saved);
}
async function history(page: Page, locale: 'en' | 'zh' = 'en') {
  const copy = (locale === 'zh' ? zh : en).detail.tracker;
  const toggle = page.getByRole('button', { name: new RegExp('^' + copy.addButton) });
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await expect(page.getByTestId('application-history')).toBeVisible();
  return page.getByTestId('application-history');
}
function seedEvent(owner: Owner, index: number, notes: string | null = null) {
  return event({ p_expected_device_id: owner.session.user.id, p_opportunity_id: TARGET,
    p_event_id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`, p_channel: 'web_form',
    p_destination: `https://example.edu/application/${index}`, p_actual_submitted_at: null,
    p_notes: notes, p_result_note: null, p_next_step: null }, new Date(Date.parse(AT) + index * 1000).toISOString());
}

test.describe('Explicit formal application records', () => {
  test('saves exact application details with separate reported and saved dates, no contact event', async ({ page }, info) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner);
      await page.goto(`/opportunities/${TARGET}`); await openForm(page);
      await expect(editor(page).locator('input[type="datetime-local"]')).toHaveValue('');
      await fill(page, 'https://example.edu/application?program=王');
      await editor(page).locator('input[type="datetime-local"]').fill('2026-08-01T10:30');
      const actual = await page.evaluate(() => new Date('2026-08-01T10:30').toISOString());
      await editor(page).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('application-form-en.png') });
      await editor(page).locator('summary').click();
      const note = 'What I submitted 王\n<img src=x onerror="alert(1)">\n' + 'long'.repeat(70);
      await editor(page).getByLabel(en.applicationRecord.notes, { exact: true }).fill(note);
      await editor(page).getByLabel(en.applicationRecord.resultNote, { exact: true }).fill('Portal acknowledged receipt');
      await editor(page).getByLabel(en.applicationRecord.nextStep, { exact: true }).fill('Check next week');
      await save(page); await saved(page);
      expect(net.requests).toHaveLength(1); expect(net.requests[0]).toMatchObject({ p_channel: 'web_form', p_destination: 'https://example.edu/application?program=王',
        p_actual_submitted_at: actual, p_notes: note, p_result_note: 'Portal acknowledged receipt', p_next_step: 'Check next week' });
      expect(net.contactWrites).toBe(0); expect(net.statusWrites).toBe(0); expect(net.summary?.last_contacted_at).toBeNull();
      const records = await history(page); await records.locator('ol > li > details > summary').click();
      await expect(records).toContainText(note); await expect(records).toContainText(en.applicationRecord.history.hint);
      await expect(records.locator('time').nth(0)).toHaveAttribute('datetime', actual);
      await expect(records.locator('time').nth(1)).toHaveAttribute('datetime', AT);
      await expect(records.locator('img,script,svg,a')).toHaveCount(0);
      await expect(records.getByTestId('application-event-details')).not.toHaveAttribute('open');
      expect(await records.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await records.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('application-details.png') });
    } finally { await owner.http.dispose(); }
  });

  test('unknown stored save survives reload and retries the same frozen record once', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner, { unknown: 'stored' });
      await page.goto(`/opportunities/${TARGET}`); await openForm(page); await fill(page); await save(page);
      await expect(editor(page).getByRole('alert')).toHaveText(en.applicationRecord.unavailable);
      await expect(editor(page).getByRole('textbox')).toHaveCount(0); expect(net.records.size).toBe(1);
      await page.reload(); await openForm(page);
      await expect(editor(page)).toContainText(en.applicationRecord.pendingTitle);
      await expect(editor(page).getByRole('textbox')).toHaveCount(0);
      await editor(page).getByRole('button', { name: en.applicationRecord.retry, exact: true }).click(); await saved(page);
      expect(net.requests).toHaveLength(2); expect(net.requests[1]).toEqual(net.requests[0]); expect(net.records.size).toBe(1);
      expect(net.statusWrites).toBe(0); expect(net.contactWrites).toBe(0);
    } finally { await owner.http.dispose(); }
  });

  test('checking a stored unknown record replays its id and honors summary deletion on another device', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner, { unknown: 'stored' }); net.summary = summary(owner, 'contacted');
      await page.goto(`/opportunities/${TARGET}`); await expect(page.getByRole('button', { name: 'Contacted', exact: true })).toHaveAttribute('aria-pressed', 'true');
      await openForm(page); await fill(page); await save(page);
      await expect(editor(page).getByRole('alert')).toHaveText(en.applicationRecord.unavailable);
      net.summary = null;
      await editor(page).getByRole('button', { name: en.applicationRecord.checkSaved, exact: true }).click();
      await expect(editor(page).getByRole('status')).toHaveText(en.applicationRecord.savedNoStatus);
      expect(net.lookups).toBe(1); expect(net.requests).toHaveLength(2); expect(net.requests[1]).toEqual(net.requests[0]); expect(net.summary).toBeNull();
      await expect(page.getByRole('button', { name: 'Contacted', exact: true })).toHaveAttribute('aria-pressed', 'false');
      await expect((await history(page)).locator('ol > li > details')).toHaveCount(1);
    } finally { await owner.http.dispose(); }
  });

  test('checking an absent uncertain record keeps it retryable instead of inventing success', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner, { unknown: 'absent' });
      await page.goto(`/opportunities/${TARGET}`); await openForm(page); await fill(page); await save(page);
      await expect(editor(page).getByRole('alert')).toHaveText(en.applicationRecord.unavailable);
      await editor(page).getByRole('button', { name: en.applicationRecord.checkSaved, exact: true }).click();
      await expect(editor(page).getByRole('alert')).toHaveText(en.applicationRecord.notFound);
      expect(net.records.size).toBe(0); expect(net.requests).toHaveLength(1);
      await editor(page).getByRole('button', { name: en.applicationRecord.retry, exact: true }).click(); await saved(page);
      expect(net.requests[1]).toEqual(net.requests[0]); expect(net.records.size).toBe(1);
    } finally { await owner.http.dispose(); }
  });

  test('a second explicit application has a new id and keeps the first record', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner);
      await page.goto(`/opportunities/${TARGET}`); await openForm(page); await fill(page); await save(page); await saved(page);
      await editor(page).getByRole('button', { name: en.applicationRecord.another, exact: true }).click();
      await expect(editor(page).getByRole('checkbox')).not.toBeChecked(); await expect(editor(page).getByRole('button', { name: en.applicationRecord.save, exact: true })).toBeDisabled();
      await editor(page).getByRole('combobox', { name: en.applicationRecord.channel, exact: true }).selectOption('email');
      await fill(page, 'applications@example.edu'); await save(page); await saved(page);
      expect(net.requests).toHaveLength(2); expect(net.requests[1].p_event_id).not.toBe(net.requests[0].p_event_id);
      expect(net.records.size).toBe(2); expect(net.contactWrites).toBe(0);
      const records = await history(page); await expect(records.locator('ol > li > details')).toHaveCount(2);
      await expect(records).toContainText('applications@example.edu');
    } finally { await owner.http.dispose(); }
  });

  test('explicitly recording the same submission details again creates a distinct event', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner);
      await page.goto(`/opportunities/${TARGET}`); await openForm(page); await fill(page); await save(page); await saved(page);
      await editor(page).getByRole('button', { name: en.applicationRecord.another, exact: true }).click();
      await fill(page); await save(page); await saved(page);
      expect(net.requests).toHaveLength(2); expect(net.requests[1].p_event_id).not.toBe(net.requests[0].p_event_id);
      const { p_event_id: firstId, ...first } = net.requests[0];
      const { p_event_id: secondId, ...second } = net.requests[1];
      expect(firstId).not.toBe(secondId); expect(first).toEqual(second); expect(net.records.size).toBe(2);
    } finally { await owner.http.dispose(); }
  });

  test('a new application preserves a later status and existing tracker notes', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner); net.summary = { ...summary(owner, 'replied'), notes: 'Existing tracker note' };
      const before = structuredClone(net.summary);
      await page.goto(`/opportunities/${TARGET}`); await expect(page.getByRole('button', { name: en.detail.interactions.replied, exact: true })).toHaveAttribute('aria-pressed', 'true');
      await openForm(page); await fill(page); await save(page); await saved(page);
      await expect(page.getByRole('button', { name: en.detail.interactions.replied, exact: true })).toHaveAttribute('aria-pressed', 'true');
      expect(net.summary).toEqual(before); expect(net.records.size).toBe(1); expect(net.statusWrites).toBe(0); expect(net.contactWrites).toBe(0);
      await history(page);
      await expect(page.getByPlaceholder(en.detail.tracker.notesPlaceholder, { exact: true })).toHaveValue('Existing tracker note');
    } finally { await owner.http.dispose(); }
  });

  test('failure to save a local retry copy blocks the remote write', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner); await page.goto(`/opportunities/${TARGET}`); await openForm(page); await fill(page);
      await page.evaluate(prefix => {
        const original = Storage.prototype.setItem;
        Storage.prototype.setItem = function(key, value) {
          if (key.includes(prefix)) throw new DOMException('Controlled storage failure', 'QuotaExceededError');
          original.call(this, key, value);
        };
      }, STORAGE_KEYS.APPLICATION_ATTEMPT_PREFIX);
      await save(page); await expect(editor(page).getByRole('alert')).toHaveText(en.applicationRecord.storageError);
      expect(net.requests).toHaveLength(0); expect(net.records.size).toBe(0); expect(net.statusWrites).toBe(0);
    } finally { await owner.http.dispose(); }
  });

  test('missing confirmation, invalid destinations and future dates create no record', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner); await page.goto(`/opportunities/${TARGET}`); await openForm(page);
      await fill(page); await expect(editor(page).getByRole('button', { name: en.applicationRecord.save, exact: true })).toBeDisabled();
      await fill(page, 'javascript:alert(1)'); await save(page); await expect(editor(page).getByRole('alert')).toHaveText(en.applicationRecord.invalid);
      await editor(page).getByRole('combobox', { name: en.applicationRecord.channel, exact: true }).selectOption('email');
      await fill(page, 'not-an-email'); await save(page); await expect(editor(page).getByRole('alert')).toHaveText(en.applicationRecord.invalid);
      await fill(page, 'application@example.edu'); await editor(page).locator('input[type="datetime-local"]').fill('2099-01-01T10:30');
      await save(page); await expect(editor(page).getByRole('alert')).toHaveText(en.applicationRecord.invalid);
      expect(net.requests).toHaveLength(0); expect(net.records.size).toBe(0); expect(net.statusWrites).toBe(0); expect(net.contactWrites).toBe(0);
    } finally { await owner.http.dispose(); }
  });

  test('manual Applied and opening or closing the record form do not create application events', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner); await page.goto(`/opportunities/${TARGET}`);
      await page.getByRole('button', { name: 'Applied', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Applied', exact: true })).toHaveAttribute('aria-pressed', 'true'); expect(net.statusWrites).toBe(1);
      await openForm(page); await expect(editor(page).getByRole('combobox')).toBeFocused();
      await page.keyboard.press('Tab'); await expect(editor(page).getByLabel(en.applicationRecord.destination, { exact: true })).toBeFocused();
      await fill(page); await page.keyboard.press('Escape'); await expect(editor(page)).toHaveCount(0);
      await expect(page.getByRole('button', { name: en.applicationRecord.open, exact: true })).toBeFocused();
      const records = await history(page); await expect(records).toContainText(en.applicationRecord.history.empty);
      expect(net.requests).toHaveLength(0); expect(net.contactWrites).toBe(0);
    } finally { await owner.http.dispose(); }
  });

  test('records entry opens without a tracker summary and pages past twenty application records', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const net = await network(page, owner);
      for (let index = 0; index < 21; index += 1) { const saved = seedEvent(owner, index); net.records.set(saved.event_id, saved); }
      await page.goto(`/opportunities/${TARGET}#tracker-records`);
      const records = page.getByTestId('application-history'); await expect(records).toBeVisible();
      await expect(records.locator('ol > li > details')).toHaveCount(20); await expect(records).toContainText('Records shown: 20. More records are available.');
      const readsBeforePage = net.reads;
      await records.getByRole('button', { name: en.applicationRecord.history.loadMore, exact: true }).click();
      await expect(records.locator('ol > li > details')).toHaveCount(21); await expect(records).toContainText('Saved records: 21');
      expect(net.reads).toBe(readsBeforePage + 1); expect(net.cursorReads).toBe(1);
      const destinations = await records.locator('ol > li > details > summary > span:last-child').allTextContents();
      expect(new Set(destinations).size).toBe(21);
      expect(net.requests).toEqual([]); expect(net.summary).toBeNull();
    } finally { await owner.http.dispose(); }
  });

  test('Chinese history failure retries safely and plain saved text fits a narrow viewport', async ({ page }, info) => {
    const owner = await account();
    try {
      await page.setViewportSize({ width: 320, height: 568 }); await seed(page, owner, 'zh');
      const net = await network(page, owner, { historyFailsOnce: true });
      await page.goto(`/opportunities/${TARGET}`); await openForm(page, 'zh');
      await editor(page).getByRole('combobox', { name: zh.applicationRecord.channel, exact: true }).selectOption('other');
      await fill(page, '学院现场申请窗口', 'zh');
      expect(await editor(page).evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await editor(page).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('application-form-zh-mobile.png') });
      await editor(page).locator('summary').click();
      await editor(page).getByLabel(zh.applicationRecord.notes, { exact: true }).fill('已提交的内容：王同学\n<svg onload=alert(1)>\n' + '长'.repeat(160));
      await save(page, 'zh'); await saved(page, 'zh'); const records = await history(page, 'zh');
      await expect(records.getByRole('alert').locator('p')).toHaveText(zh.applicationRecord.history.error);
      await expect(records).not.toContainText('private database failure'); await expect(records).not.toContainText(zh.applicationRecord.history.empty);
      await records.getByRole('button', { name: zh.applicationRecord.history.retry, exact: true }).click();
      await records.locator('ol > li > details > summary').click();
      await expect(records).toContainText('已提交的内容：王同学'); await expect(records).toContainText(zh.applicationRecord.history.submittedUnknown);
      await expect(records.locator('svg,script,img,a')).toHaveCount(0); expect(await records.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await records.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('application-zh-mobile.png') });
      expect(net.reads).toBe(2); expect(net.contactWrites).toBe(0);
    } finally { await owner.http.dispose(); }
  });
});
