import { test, expect, request as apiRequest, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { normalizeEmailContactContext, serializeEmailContactContext } from '../src/lib/email-contact-context';
import type { EmailContactContext } from '../src/lib/types';

// Real local SDK/auth/profile/target reads. Only writing output is controlled.
// This tests transport/context lifetime, not real-model quality or sending.
const STUB = 'http://127.0.0.1:' + Number(process.env.E2E_SUPABASE_PORT ?? 54321);
const TARGET = 'uiuc-siebel-ugresearch';
const MANUAL = { subject: 'My manual subject 王', body: 'My complete manual email.\nI helped; I did not lead the team. 王',
  recipient: 'manual@example.edu', request: 'Keep this unsent editing request 王' };
interface Owner { http: APIRequestContext; session: { access_token: string; user: { id: string } } }
interface Call { path: string; opportunity_id: string; expected_target_version: string; contact_context: EmailContactContext }
const pathOf = (url: string) => new URL(url).pathname;
async function account(): Promise<Owner> {
  expect(new URL(STUB).hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(STUB + '/auth/v1/signup', { data: {} }); expect(signup.status()).toBe(200);
    const session = await signup.json();
    const headers = { Authorization: 'Bearer ' + session.access_token };
    const saved = await http.post(STUB + '/rest/v1/rpc/commit_profile_patch_cas', { headers, data: {
      p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: {
        name: 'Context student 王', institution: 'UIUC', home_school: 'uiuc',
        college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Sophomore',
        is_international: false, skills: [], coursework: ['ECE 220'], research_interests: 'research tools', seeking_types: ['research'],
      },
    } });
    expect(saved.status()).toBe(200); expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1 });
    const favorite = await http.post(STUB + '/rest/v1/favorites', { headers, data: { device_id: session.user.id, opportunity_id: TARGET } });
    expect(favorite.status()).toBe(201);
    return { http, session };
  } catch (error) { await http.dispose(); throw error; }
}
async function seed(page: Page, owner: Owner) {
  await page.addInitScript(({ session, keys }) => {
    if (localStorage.getItem('contact-context-seeded')) return;
    localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, 'en');
    localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('contact-context-seeded', '1');
  }, { session: owner.session, keys: STORAGE_KEYS });
}
function writes(page: Page) {
  const events: string[] = [];
  page.on('request', request => {
    if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(request.method())
      && /\/(?:profiles|interactions|commit_profile_patch_cas|(?:confirm_interaction_contact|confirm_contact_event)|set_interaction_reminder)$/.test(pathOf(request.url()))) events.push(request.url());
  });
  return events;
}
function fields(page: Page) {
  return { subject: page.locator('#cold-email-subject'), body: page.locator('#cold-email-body'),
    recipient: page.locator('#cold-email-to'), request: page.getByRole('textbox', { name: 'Request an edit', exact: true }) };
}
async function edit(page: Page) {
  for (const key of ['subject', 'body', 'recipient', 'request'] as const) await fields(page)[key].fill(MANUAL[key]);
}
async function kept(page: Page) {
  for (const key of ['subject', 'body', 'recipient', 'request'] as const) await expect(fields(page)[key]).toHaveValue(MANUAL[key]);
}
const panel = (page: Page) => page.getByTestId('email-contact-context-panel');
async function expand(page: Page) {
  if (!(await panel(page).getAttribute('open') !== null)) await panel(page).locator('summary').click();
}
const purpose = (page: Page) => panel(page).getByRole('combobox', { name: 'Contact purpose', exact: true });
const apply = (page: Page) => panel(page).getByRole('button', { name: 'Apply background to this draft', exact: true });
const regenerate = (page: Page) => page.getByRole('button', { name: 'Regenerate from updated materials', exact: true });
async function fillReferral(page: Page) {
  await expand(page);
  await purpose(page).selectOption('referral');
  await panel(page).getByRole('textbox', { name: 'Who referred you? (required)', exact: true }).fill('Pat 李');
  await panel(page).getByRole('textbox', { name: 'What did they actually say or suggest? (required)', exact: true })
    .fill('Pat suggested I ask about student research. This was not an endorsement.');
  await panel(page).getByRole('checkbox', { name: 'I confirm these referral details are accurate and I may mention this person in the draft.', exact: true }).check();
}
async function fillFollowUp(page: Page) {
  await expand(page);
  await purpose(page).selectOption('follow_up');
  await panel(page).getByRole('textbox', { name: 'Previous email you sent (required)', exact: true })
    .fill('Dear researcher,\nCould I ask about student research opportunities?\nThank you.');
  await panel(page).getByRole('checkbox', { name: 'I confirm I actually sent this email to this target and these details are accurate. This does not record a new send.', exact: true }).check();
}
function receipt(context: EmailContactContext) {
  return { version: 1, purpose: context.purpose,
    context_sig: createHash('sha256').update(serializeEmailContactContext(context), 'utf8').digest('hex') };
}
function writing(page: Page, heldKind?: 'stream' | 'refine') {
  const state = { calls: [] as Call[], heldStarted: false, heldCompleted: false };
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const install = page.route('**/api/cold-email**', async route => {
    const path = pathOf(route.request().url());
    const payload = route.request().postDataJSON() as Call;
    expect(payload.opportunity_id).toBe(TARGET);
    expect(payload.expected_target_version).toMatch(/^wt1:[0-9a-f]{64}$/);
    const context = normalizeEmailContactContext(payload.contact_context);
    expect(payload.contact_context).toEqual(context);
    state.calls.push({ ...payload, path });
    const bound = { opportunity_id: TARGET, target_version: payload.expected_target_version, contact_context_receipt: receipt(context) };
    const body = (kind: string) => kind + ' ' + context.purpose + ' draft 王';
    const draft = { ...bound, subject: 'Confirmed context subject', body: body('Template'), recipient_email: 'lab@example.edu',
      recipient_status: 'revealed', mailto_link: '', method: 'template', pipeline_version: 'w12.8', corpus_version: 'controlled-context' };
    if (path === '/api/cold-email/variants') {
      await route.fulfill({ json: { ...draft, variants: [{ id: 'context-template', label: 'Context template', ...draft }] } }); return;
    }
    const holding = !state.heldStarted && path === '/api/cold-email/' + heldKind;
    if (holding) { state.heldStarted = true; await gate; }
    if (path === '/api/cold-email/stream') {
      await route.fulfill({ contentType: 'text/event-stream',
        body: 'data: ' + JSON.stringify({ ...draft, body: holding ? 'STALE held output must not replace my draft' : body('AI'), method: 'ai', stage: 'done' }) + '\n\n' });
    } else if (path === '/api/cold-email/refine') {
      await route.fulfill({ json: { ...bound, body: holding ? 'STALE held output must not replace my draft' : body('Refined'), method: 'llm', pipeline_version: 'w12.8' } });
    } else {
      await route.fulfill({ status: 503, json: { detail: 'Unexpected writing request' } });
    }
    if (holding) state.heldCompleted = true;
  });
  return { state, release, install };
}
async function open(page: Page) {
  const profileRead = page.waitForResponse(response => pathOf(response.url()) === '/rest/v1/profiles' && response.status() === 200);
  await page.goto('/favorites'); await profileRead;
  await page.getByRole('button', { name: 'Draft Email', exact: true }).click();
}
// Opening shows the template; only the Generate control starts an AI draft.
const generate = (page: Page) => page.getByRole('button', { name: 'Generate AI draft', exact: true });
async function ready(page: Page) {
  await expect(fields(page).body).toHaveValue('Template first_contact draft 王');
  await expect(generate(page)).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Shorter', exact: true })).toBeEnabled();
}

test('referral confirmation applies background without generating or recording contact; explicit generation uses the confirmed context', async ({ page }, info) => {
  const owner = await account();
  try {
    await seed(page, owner); const model = writing(page); await model.install; const mutations = writes(page);
    await open(page); await ready(page); await edit(page);
    const before = model.state.calls.length;
    await fillReferral(page);
    await expect(regenerate(page)).toBeDisabled(); await kept(page);
    await apply(page).click();
    await expect(page.getByTestId('email-contact-context-status')).toContainText('Background confirmed for the next draft');
    await expect(regenerate(page)).toBeEnabled(); await kept(page);
    expect(model.state.calls).toHaveLength(before); expect(mutations).toEqual([]);
    await apply(page).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath('contact-background-referral-confirmed.png'), fullPage: true });
    await regenerate(page).click();
    await expect(fields(page).body).toHaveValue('Template referral draft 王');
    expect(model.state.calls.slice(before).map(call => call.path)).toEqual(['/api/cold-email/variants']);
    await generate(page).click();
    await expect(fields(page).body).toHaveValue('AI referral draft 王');
    const after = model.state.calls.slice(before);
    expect(after.map(call => call.path)).toEqual(['/api/cold-email/variants', '/api/cold-email/stream']);
    for (const call of after) expect(call.contact_context).toEqual({ version: 1, purpose: 'referral',
      referral: { referrer_name: 'Pat 李', referral_note: 'Pat suggested I ask about student research. This was not an endorsement.', confirmed: true } });
    await expect(fields(page).recipient).toHaveValue(MANUAL.recipient);
    await expect(fields(page).request).toHaveValue(MANUAL.request);
    expect(mutations).toEqual([]);
  } finally { await owner.http.dispose(); }
});

test('follow-up confirms an actual previous message without inventing a date, reply state or contact record', async ({ page }) => {
  const owner = await account();
  try {
    await seed(page, owner); const model = writing(page); await model.install; const mutations = writes(page);
    await open(page); await ready(page); await edit(page); const before = model.state.calls.length;
    await fillFollowUp(page);
    await expect(panel(page).getByRole('combobox', { name: 'Reply status', exact: true })).toHaveValue('unknown');
    await expect(panel(page).getByRole('textbox', { name: 'Date sent (optional, YYYY-MM-DD)', exact: true })).toHaveValue('');
    await apply(page).click(); await expect(regenerate(page)).toBeEnabled(); await kept(page);
    expect(model.state.calls).toHaveLength(before); expect(mutations).toEqual([]);
    await regenerate(page).click(); await expect(fields(page).body).toHaveValue('Template follow_up draft 王');
    await generate(page).click(); await expect(fields(page).body).toHaveValue('AI follow_up draft 王');
    expect(model.state.calls.at(-1)!.path).toBe('/api/cold-email/stream');
    const context = model.state.calls.at(-1)!.contact_context;
    expect(context.follow_up).toEqual({ sent_confirmed: true,
      previous_message: 'Dear researcher,\nCould I ask about student research opportunities?\nThank you.', reply_status: 'unknown' });
    expect(context.follow_up).not.toHaveProperty('sent_on'); expect(context.follow_up).not.toHaveProperty('reply_text');
    expect(mutations).toEqual([]);
  } finally { await owner.http.dispose(); }
});

for (const kind of ['stream', 'refine'] as const) {
  test('a held ' + kind + ' cannot restore context A after the user applies B then A again', async ({ page }) => {
    const owner = await account(); let release = () => {};
    try {
      await seed(page, owner); const model = writing(page, kind); release = model.release; await model.install;
      const mutations = writes(page); await open(page); await ready(page);
      if (kind === 'stream') {
        await generate(page).click();
        await expect.poll(() => model.state.heldStarted).toBe(true);
      }
      await edit(page);
      if (kind === 'refine') {
        await page.getByRole('button', { name: 'Shorter', exact: true }).click();
        await expect.poll(() => model.state.heldStarted).toBe(true);
      }
      const count = model.state.calls.length;
      await fillReferral(page); await apply(page).click();
      await purpose(page).selectOption('first_contact'); await apply(page).click();
      await expect(regenerate(page)).toBeEnabled(); await kept(page);
      expect(model.state.calls).toHaveLength(count);
      const returned = page.waitForResponse(response => pathOf(response.url()) === '/api/cold-email/' + kind);
      release(); const response = await returned; await response.finished();
      await expect.poll(() => model.state.heldCompleted).toBe(true);
      // A user event after the completed response also exercises the still-live editor.
      await fields(page).body.click(); await kept(page);
      await expect(page.getByText('STALE held output must not replace my draft', { exact: true })).toHaveCount(0);
      expect(model.state.calls).toHaveLength(count); expect(mutations).toEqual([]);
    } finally { release(); await owner.http.dispose(); }
  });
}

test('a refusal or no-contact response cannot be applied as a follow-up and never erases the current draft', async ({ page }) => {
  const owner = await account();
  try {
    await seed(page, owner); const model = writing(page); await model.install; const mutations = writes(page);
    await open(page); await ready(page); await edit(page); const before = model.state.calls.length;
    await fillFollowUp(page);
    for (const reply of ['declined', 'do_not_contact']) {
      await panel(page).getByRole('combobox', { name: 'Reply status', exact: true }).selectOption(reply);
      await expect(apply(page)).toBeDisabled(); await expect(regenerate(page)).toBeDisabled();
      await expect(panel(page).getByRole('alert')).toContainText('Your current email and answers are kept');
      await kept(page); expect(model.state.calls).toHaveLength(before); expect(mutations).toEqual([]);
    }
  } finally { await owner.http.dispose(); }
});

async function onTop(locator: Locator) {
  expect(await locator.evaluate(element => {
    const box = element.getBoundingClientRect();
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    const hit = document.elementFromPoint(x, y);
    return x >= 0 && x <= innerWidth && y >= 0 && y <= innerHeight && !!hit && (hit === element || element.contains(hit));
  })).toBe(true);
}
async function reachable(locator: Locator) {
  await locator.scrollIntoViewIfNeeded(); await expect(locator).toBeVisible(); await expect(locator).toBeInViewport();
  await onTop(locator);
}
// M29: Copy and Open in Email stay in view and usable without scrolling.
async function actionsPinned(page: Page) {
  for (const name of ['Copy', 'Open in Email']) {
    const action = page.getByRole('button', { name, exact: true });
    await expect(action).toBeInViewport({ ratio: 1 }); await onTop(action);
  }
}
test('contact fields and writing controls remain reachable at 390px, a short window and 200 percent equivalent reflow', async ({ page }, info) => {
  const owner = await account();
  try {
    await page.setViewportSize({ width: 390, height: 640 });
    // `next dev` pins its Dev Tools badge over the bottom-left corner; the production build has none.
    await page.addInitScript(() => document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style'); style.textContent = 'nextjs-portal { display: none !important; }'; document.head.append(style);
    }));
    await seed(page, owner); const model = writing(page); await model.install;
    await open(page); await ready(page); await expand(page);
    await actionsPinned(page);
    await purpose(page).selectOption('referral');
    const name = panel(page).getByRole('textbox', { name: 'Who referred you? (required)', exact: true });
    const note = panel(page).getByRole('textbox', { name: 'What did they actually say or suggest? (required)', exact: true });
    await reachable(name); await name.fill('Pat 李');
    await page.keyboard.press('Tab'); await expect(note).toBeFocused();
    await note.fill('Suggested asking about the research methods.');
    await page.keyboard.press('Tab');
    const confirm = panel(page).getByRole('checkbox', { name: 'I confirm these referral details are accurate and I may mention this person in the draft.', exact: true });
    await expect(confirm).toBeFocused(); await page.keyboard.press('Space');
    // Short viewport approximates space lost to a keyboard; this is not a real-device keyboard claim.
    await page.setViewportSize({ width: 390, height: 400 });
    await reachable(apply(page));
    await actionsPinned(page);
    await page.screenshot({ path: info.outputPath('contact-background-390-short.png'), fullPage: true });
    await apply(page).click();
    await reachable(regenerate(page)); await expect(regenerate(page)).toBeEnabled();
    await reachable(fields(page).body); await fields(page).body.fill(MANUAL.body);
    await reachable(fields(page).request); await fields(page).request.fill(MANUAL.request);
    await actionsPinned(page);
    const close = page.getByRole('button', { name: 'Close email editor', exact: true });
    await reachable(close);
    // 1280×800 at 200% browser zoom has a 640×400 effective CSS viewport.
    // This verifies that reflow, not native zoom or a 390×400 window zoomed again.
    // CSS zoom:2 is deliberately not used: it doubles 100dvh independently of the viewport.
    await page.setViewportSize({ width: 640, height: 400 });
    await actionsPinned(page);
    await reachable(name); await reachable(note); await reachable(confirm); await reachable(apply(page));
    await page.screenshot({ path: info.outputPath('contact-background-200-percent-equivalent-reflow.png'), fullPage: true });
    await reachable(regenerate(page)); await expect(regenerate(page)).toBeEnabled();
    await reachable(fields(page).body);
    await page.screenshot({ path: info.outputPath('contact-background-reflow-editor.png'), fullPage: true });
    await reachable(fields(page).request);
    await actionsPinned(page);
    await page.screenshot({ path: info.outputPath('contact-background-reflow-request.png'), fullPage: true });
    await reachable(close);
    await expect(fields(page).body).toHaveValue(MANUAL.body); await expect(fields(page).request).toHaveValue(MANUAL.request);
    await close.click(); await expect(page.getByRole('dialog')).toHaveCount(0);
  } finally { await owner.http.dispose(); }
});
