import { test, expect, type Page, type Locator, type Request } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { en, zh } from '../src/i18n/dictionaries';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { account, seed, network, audits, seeded, addRecord, PDF, TARGET, EVENT, SUBMITTED, CONFIRMED, ARCHIVED, LINKED, type Owner } from './contact-materials-fixture';

// UI uses the real SDK, local storage, crypto, file picker and download. These
// scoped HTTP fixtures do not prove PostgreSQL, Storage, sending or delivery.
const copy = (locale: 'en' | 'zh' = 'en') => ({ ...(locale === 'zh' ? zh : en).applicationRecord.materials, ...(locale === 'zh' ? zh : en).contactMaterials });
const panel = (page: Page) => page.getByTestId('contact-material-panel');
const action = (parent: Locator, key: keyof ReturnType<typeof copy>, locale: 'en' | 'zh' = 'en') => parent.getByRole('button', { name: copy(locale)[key], exact: true });
async function eventView(page: Page, index = 0, locale: 'en' | 'zh' = 'en') {
  const dict = locale === 'zh' ? zh : en;
  const toggle = page.getByRole('button', { name: new RegExp('^' + dict.detail.tracker.addButton) });
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  const event = page.getByTestId('contact-history').locator('ol > li > details').nth(index);
  if (await event.getAttribute('open') === null) await event.locator(':scope > summary').click();
  return event;
}
async function open(page: Page, index = 0, locale: 'en' | 'zh' = 'en') {
  const event = await eventView(page, index, locale); await action(event, 'open', locale).click();
  await expect(event.getByTestId('contact-material-panel')).toBeVisible(); return event.getByTestId('contact-material-panel');
}
async function upload(parent: Locator, name = 'actual-email-attachment.pdf', bytes = PDF, locale: 'en' | 'zh' = 'en') {
  await parent.getByLabel(copy(locale).fileLabel, { exact: true }).setInputFiles({ name, mimeType: 'application/pdf', buffer: bytes });
  await parent.getByRole('checkbox', { name: copy(locale).attestation, exact: true }).check(); await action(parent, 'save', locale).click();
}
async function start(page: Page, owner: Owner, options: Parameters<typeof network>[2] = {}, locale: 'en' | 'zh' = 'en') {
  await seed(page, owner, locale); const net = await network(page, owner, options); await page.goto(`/opportunities/${TARGET}`); return net;
}
async function pending(page: Page, prefix: string) { return page.evaluate(prefix => Object.keys(localStorage).filter(key => key.includes(prefix)).map(key => localStorage.getItem(key)!), prefix); }
function gate() { let release!: () => void; const promise = new Promise<void>(resolve => { release = resolve; }); return { release, promise }; }

test.describe('PDFs recorded for a confirmed contact', () => {
  test.afterEach(async ({ page }, info) => {
    const audit = audits.get(page); if (!audit) return;
    await info.attach('contact-material-network-audit', { body: JSON.stringify(audit, null, 2), contentType: 'application/json' });
    expect(audit.pageErrors).toEqual([]); expect(audit.external).toEqual([]);
    expect(audit.responses.filter(row => row.status >= 500 && !row.injected)).toEqual([]);
  });

  test('attachment reads stay lazy and anonymous visitors must sign in', async ({ page }) => {
    const owner = await account(true); try {
      const net = await start(page, owner); const event = await eventView(page); expect(net.state.reads).toBe(0);
      await action(event, 'open').click(); await expect(event).toContainText(copy().signInHint);
      expect(net.state.reads).toBe(0); expect(net.state.uploads).toHaveLength(0);
      await action(event, 'signIn').click(); await expect(page.getByRole('dialog')).toBeVisible();
    } finally { await owner.http.dispose(); }
  });

  test('explicitly records and downloads original bytes without changing the original message or send dates', async ({ page }, info) => {
    const owner = await account(); try {
      const net = await start(page, owner); const before = structuredClone(net.events[0]); const event = await eventView(page);
      expect(net.state.reads).toBe(0); await event.getByTestId('contact-event-sources').locator('summary').click();
      await expect(event.getByTestId('contact-event-sources')).toContainText('saved-profile-v1');
      await expect(event.getByTestId('contact-event-sources').getByRole('button')).toHaveCount(0);
      const files = await open(page); await expect(action(files, 'save')).toBeDisabled();
      await files.getByLabel(copy().fileLabel, { exact: true }).setInputFiles({ name: 'actual-email-attachment.pdf', mimeType: 'application/pdf', buffer: PDF });
      await expect(action(files, 'save')).toBeDisabled(); await files.getByRole('checkbox').check(); await action(files, 'save').click();
      await expect(files).toContainText(copy().saved); expect(net.state.bodies).toEqual([PDF]); expect(net.events[0]).toEqual(before);
      expect(net.state.contactWrites).toBe(0); expect(net.state.appWrites).toBe(0); expect(net.state.statusWrites).toBe(0); expect(net.state.applicationMaterialRequests).toBe(0);
      const row = files.getByTestId('contact-material-record'); await expect(row.locator('time').nth(0)).toHaveAttribute('datetime', ARCHIVED); await expect(row.locator('time').nth(1)).toHaveAttribute('datetime', LINKED);
      await expect(event.locator(':scope > dl > div > dd > time').nth(0)).toHaveAttribute('datetime', SUBMITTED); await expect(event.locator(':scope > dl > div > dd > time').nth(1)).toHaveAttribute('datetime', CONFIRMED);
      const downloaded = page.waitForEvent('download'); await action(files, 'download').click(); const file = await downloaded;
      expect(file.suggestedFilename()).toBe('actual-email-attachment.pdf'); const path = info.outputPath('original-email-attachment.pdf'); await file.saveAs(path); expect(await readFile(path)).toEqual(PDF);
      await row.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('contact-material-saved.png') });
      await page.reload(); await open(page); await expect(panel(page)).toContainText('actual-email-attachment.pdf'); expect(net.state.uploads).toHaveLength(1);
      await expect.poll(() => pending(page, STORAGE_KEYS.CONTACT_MATERIAL_ATTEMPT_PREFIX)).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('an unknown committed upload reloads and checks the same contact record without a second upload', async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner, { uploadUnknown: 'ready' }); const files = await open(page); await upload(files); await expect(files.getByRole('alert')).toBeVisible();
      const [attempt] = await pending(page, STORAGE_KEYS.CONTACT_MATERIAL_ATTEMPT_PREFIX); expect(attempt).toBeTruthy(); expect(attempt).not.toContain('application_event_id');
      await page.reload(); await open(page); await action(panel(page), 'check').click(); await expect(panel(page)).toContainText(copy().saved);
      expect(net.state.uploads).toHaveLength(1); expect(net.state.records.size).toBe(1); expect(net.state.applicationMaterialRequests).toBe(0);
      await expect.poll(() => pending(page, STORAGE_KEYS.CONTACT_MATERIAL_ATTEMPT_PREFIX)).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('a rejected file stays blocked through unknown cancellation until its tombstone is checked', async ({ page }, info) => {
    const owner = await account(); try {
      const net = await start(page, owner, { rejectPdf: true, deleteUnknown: 'deleted' }); const files = await open(page);
      await upload(files, 'damaged.pdf', Buffer.from('%PDF-1.4 broken structure')); await expect(files.getByRole('alert')).toHaveText(copy().invalidFile);
      await action(files, 'cancelUpload').click(); await expect(action(files, 'keepUpload')).toBeFocused();
      await files.getByRole('alertdialog').scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('contact-material-cancel.png') });
      await action(files, 'confirmCancelUpload').click(); await expect(files.getByRole('alert')).toHaveText(copy().cancelUnknown);
      await page.reload(); await open(page); await expect(panel(page).getByLabel(copy().fileLabel, { exact: true })).toHaveCount(0);
      await action(panel(page), 'check').click(); await expect(panel(page)).toContainText(copy().cancelled);
      await action(panel(page), 'another').click(); await upload(panel(page), 'replacement.pdf'); await expect(panel(page)).toContainText(copy().saved);
      expect(net.state.uploads).toHaveLength(2); expect(net.state.uploads[1].material_id).not.toBe(net.state.uploads[0].material_id); expect(net.state.uploads[1].record_id).not.toBe(net.state.uploads[0].record_id);
      expect(net.state.records.get(net.state.uploads[0].record_id)).toMatchObject({ status: 'deleted', filename: null, linked_at: null });
      expect(net.state.contactWrites).toBe(0); expect(net.state.appWrites).toBe(0);
    } finally { await owner.http.dispose(); }
  });

  test('unknown deletion hides downloads and filename through reload until the dated deletion is confirmed', async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner, { deleteUnknown: 'deleted' }); addRecord(net, seeded(owner, 'private-old.pdf')); const files = await open(page);
      await action(files, 'delete').click(); await expect(action(files, 'cancel')).toBeFocused(); await page.keyboard.press('Escape'); expect(net.state.deletions).toHaveLength(0);
      await action(files, 'delete').click(); await action(files, 'confirmDelete').click(); await expect(files.getByTestId('contact-material-delete-pending')).toBeVisible();
      await expect(action(files, 'download')).toHaveCount(0); await page.reload(); await open(page); await expect(panel(page)).not.toContainText('private-old.pdf');
      await action(panel(page), 'check').click(); await expect(panel(page).getByTestId('contact-material-record')).toContainText(copy().deleted);
      await expect(panel(page).getByTestId('contact-material-record').locator('time')).toHaveCount(3); expect(net.state.downloads).toBe(0);
      await expect.poll(() => pending(page, STORAGE_KEYS.CONTACT_MATERIAL_DELETE_PREFIX)).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('identical files recorded for different contact events get independent IDs and deletion stays in its event', async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner); const second = '22222222-2222-4222-8222-222222222221'; net.events.push({ ...net.events[0], event_id: second, subject: 'Second saved email' });
      await page.reload(); const firstFiles = await open(page, 0); await upload(firstFiles, 'same.pdf'); await expect(firstFiles).toContainText(copy().saved);
      const secondFiles = await open(page, 1); await upload(secondFiles, 'same.pdf'); await expect(secondFiles).toContainText(copy().saved);
      expect(net.state.uploads.map(row => row.contact_event_id)).toEqual([EVENT, second]); expect(new Set(net.state.uploads.map(row => row.material_id)).size).toBe(2); expect(new Set(net.state.uploads.map(row => row.record_id)).size).toBe(2);
      const originalSecond = structuredClone(net.state.records.get(net.state.uploads[1].record_id)); await action(firstFiles, 'delete').click(); await action(firstFiles, 'confirmDelete').click();
      await expect(firstFiles).toContainText(copy().deleted); await expect(secondFiles).toContainText('same.pdf'); expect(net.state.records.get(net.state.uploads[1].record_id)).toEqual(originalSecond);
      expect(net.state.applicationMaterialRequests).toBe(0); expect(net.state.appWrites).toBe(0); expect(net.state.contactWrites).toBe(0);
    } finally { await owner.http.dispose(); }
  });

  test('signing out during a delayed download prevents the old file from being saved', async ({ page }) => {
    const owner = await account(); const held = gate(); let started = false, downloads = 0;
    let fileRequest: Request | null = null, terminal: 'finished' | 'aborted' | null = null;
    try {
      const net = await start(page, owner); addRecord(net, seeded(owner)); await open(page); page.on('download', () => { downloads += 1; });
      page.on('requestfinished', request => { if (request === fileRequest) terminal = 'finished'; });
      page.on('requestfailed', request => { if (request === fileRequest) { expect(request.failure()?.errorText).toMatch(/abort|cancel/i); terminal = 'aborted'; } });
      await page.route('**/api/contact-materials/*/file*', async route => {
        fileRequest = route.request(); started = true; await held.promise; const row = [...net.state.records.values()][0];
        try { await route.fulfill({ body: PDF, headers: { 'content-type': 'application/pdf', 'x-ofe-material-id': row.material_id, 'x-ofe-material-record': row.record_id, 'x-ofe-material-sha256': row.bytes_sha256! } }); }
        catch (error) { if (!/abort|cancel/i.test(route.request().failure()?.errorText ?? '')) throw error; }
      });
      await action(panel(page), 'download').click(); await expect.poll(() => started).toBe(true);
      await page.evaluate(() => { localStorage.removeItem('ofe_auth'); const channel = new BroadcastChannel('ofe_auth'); channel.postMessage({ event: 'SIGNED_OUT', session: null }); channel.close(); });
      await expect(panel(page)).toHaveCount(0); held.release(); await expect.poll(() => terminal).not.toBeNull();
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      expect(downloads).toBe(0); await expect(page.getByText('submitted-original.pdf', { exact: true })).toHaveCount(0);
    } finally { held.release(); await owner.http.dispose(); }
  });

  test('Chinese narrow-screen attachment form and deletion confirmation stay keyboard usable', async ({ page }, info) => {
    const owner = await account(); try {
      await page.setViewportSize({ width: 320, height: 760 }); const net = await start(page, owner, {}, 'zh'); const files = await open(page, 0, 'zh');
      await files.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('contact-material-form-zh-320.png') });
      const filename = '<img onerror=alert(1)>王'.repeat(5) + '.pdf'; await upload(files, filename, PDF, 'zh'); await expect(files).toContainText(copy('zh').saved);
      await expect(files.getByText(filename, { exact: true })).toBeVisible(); await expect(files.locator('img,script')).toHaveCount(0);
      expect(await files.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      await action(files, 'delete', 'zh').focus(); await page.keyboard.press('Enter'); await expect(action(files, 'cancel', 'zh')).toBeFocused(); await page.keyboard.press('Escape'); await expect(action(files, 'delete', 'zh')).toBeFocused(); expect(net.state.deletions).toHaveLength(0);
      await files.getByTestId('contact-material-record').scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('contact-material-saved-zh-320.png') });
    } finally { await owner.http.dispose(); }
  });
});
