import { contactReceiptForRequest } from './email-contact-receipt';
import { test, expect, request as apiRequest, type APIRequestContext, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';
import type { TargetResumeV1 } from '../src/lib/target-resume';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { PUBLIC_RELEASE_CACHE_VERSION } from '../src/lib/release-scope';
import type { ExperienceEntry, Opportunity, ProfileData, ProfileRequest, ResumeSectionInput } from '../src/lib/types';
import { attachProfileReadDiagnostics } from './profile-read-diagnostics';

// Production UI and SDK, real loopback auth/profile/favorite writes. Silent
// external-device changes use a separate HTTP context, never storage events.
// Every generation endpoint is intercepted; no model or hosted project runs.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const TARGET = 'uiuc-siebel-ugresearch';
const OLD_NAME = 'Writing entry student 王';
const NEW_NAME = 'Updated writing student 王';
const OLD_BULLET = 'Compared earlier instrument readings; I assisted and did not lead.';
const NEW_BULLET = 'Recorded updated calibration measurements; I assisted and did not lead.';
const SECOND_BULLET = 'Documented uncertainty in the laboratory notebook.';
const MANUAL = 'Keep my own careful wording exactly. I assisted; I did not lead. 王';
const SOURCE_CHANGED = 'Profile or target changed. Your draft and edits are kept. Re-renovate before optimizing bullets.';
const MISSING = 'Your profile is no longer available. Your draft is kept; generation and outreach are paused.';
const isProfile = (url: string) => new URL(url).pathname === '/rest/v1/profiles';
const entry = (text: string): ExperienceEntry => ({ id: 'experience', revision: 1, status: 'confirmed', text, source: { kind: 'manual' } });
const rawResume = (first: string) => `EXPERIENCE\n- ${first}\n- ${SECOND_BULLET}`;
interface Owner { http: APIRequestContext; uid: string; token: string; revision: number }
interface WritingRequest {
  path: string; profile?: ProfileRequest; opportunity_id?: string; resume_text?: string;
  expected_target_version?: string; original_bullets?: string[]; sections?: ResumeSectionInput[]; current_text?: string;
  experience_evidence?: { version: number; resume_text: string; entries: ExperienceEntry[] };
}
function profile(): ProfileData {
  return { name: OLD_NAME, institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
    major: 'Computer Science', grade: 'Sophomore', is_international: false, research_interests: 'instrumentation',
    skills: [{ name: 'Python', level: 'beginner' }], coursework: ['ECE 220'], seeking_types: ['research'],
    resume_text: rawResume(OLD_BULLET), experience_entries: [entry(OLD_BULLET)],
    resume_master: { version: 1, id: 'writing-entry-master', revision: 1, source_signature: null,
      basics: { name: { id: 'name', revision: 1, status: 'confirmed', value: OLD_NAME, source: { kind: 'manual' } }, links: [] },
      education: [], activities: [{ id: 'activity', kind: 'project',
        title: { id: 'title', revision: 1, status: 'confirmed', value: 'Instrument project', source: { kind: 'manual' } },
        details: [{ id: 'experience', revision: 1 }] }], publications: [], skills: [], other_sections: [],
      section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [] } };
}
async function commit(owner: Owner, patch: Partial<ProfileData>) {
  const response = await owner.http.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
    headers: { Authorization: `Bearer ${owner.token}` },
    data: { p_expected_device_id: owner.uid, p_expected_revision: owner.revision, p_patch: patch },
  });
  expect(response.status()).toBe(200);
  const receipt = await response.json();
  expect(receipt).toMatchObject({ status: 'applied', revision: owner.revision + 1, profile: patch });
  owner.revision = receipt.revision;
}
async function seed(page: Page): Promise<Owner> {
  expect(STUB.hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
    expect(signup.status()).toBe(200);
    const session = await signup.json();
    const owner = { http, uid: session.user.id as string, token: session.access_token as string, revision: 0 };
    await commit(owner, profile());
    const starred = await http.post(new URL('/rest/v1/favorites', STUB).href, {
      headers: { Authorization: `Bearer ${owner.token}` }, data: { device_id: owner.uid, opportunity_id: TARGET },
    });
    expect(starred.status()).toBe(201);
    await page.addInitScript(({ session, key }) => {
      if (!localStorage.getItem('writing-entry-seeded')) {
        localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(key, 'en');
        localStorage.setItem('writing-entry-seeded', '1');
      }
    }, { session, key: STORAGE_KEYS.LOCALE });
    const read = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
    await page.goto('/'); await read;
    await expect(page.locator('#student_name')).toHaveValue(OLD_NAME);
    await expect(page.getByRole('button', { name: 'Generate Matches', exact: true })).toBeEnabled();
    return owner;
  } catch (error) { await http.dispose(); throw error; }
}
function profileWrites(page: Page) {
  const writes: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method()) && /\/profiles$|\/commit_profile_patch_cas$/.test(path)) writes.push(path);
  });
  return writes;
}
async function localProfile(page: Page): Promise<ProfileData | null> {
  return page.evaluate(key => JSON.parse(localStorage.getItem(key) ?? 'null'), STORAGE_KEYS.PROFILE);
}
async function gateProfileRead(page: Page) {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let started = false;
  await page.route('**/rest/v1/profiles?**', async route => {
    started = true;
    const response = await route.fetch({ maxRetries: 0 });
    expect(response.status()).toBe(200);
    await gate;
    try { await route.fulfill({ response }); }
    catch (error) { if (!route.request().failure()) throw error; }
  }, { times: 1 });
  return { release, started: () => started };
}
async function enter(page: Page, surface: 'favorites' | 'detail') {
  const read = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
  await page.goto(surface === 'favorites' ? '/favorites' : `/opportunities/${TARGET}`); await read;
  await expect(page.getByRole('button', { name: surface === 'favorites' ? 'Draft Email' : 'Draft email', exact: true })).toBeEnabled();
  await expect(page.getByTestId('profile-refresh-status')).toHaveCount(0);
}
async function openLegacy(page: Page) {
  await enter(page, 'detail');
  await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
  await page.getByRole('button', { name: 'Edit résumé bullets', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Renovate with AI', exact: true })).toBeEnabled();
}
async function installWriting(page: Page) {
  const requests: WritingRequest[] = [];
  for (const pattern of ['**/api/tailor**', '**/api/cold-email**', '**/api/resume/**']) await page.route(pattern, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/tailor/status') { await route.fulfill({ json: { ai_available: true, pipeline_version: 'w13.4' } }); return; }
    const body = route.request().postDataJSON() as Omit<WritingRequest, 'path'>;
    requests.push({ ...body, path });
    if (path === '/api/cold-email/variants' || path === '/api/cold-email/stream') {
      const confirmed = body.experience_evidence!.entries.filter(item => item.status === 'confirmed');
      const draft = { opportunity_id: body.opportunity_id, target_version: body.expected_target_version, contact_context_receipt: contactReceiptForRequest(body), subject: `Checked ${body.profile!.name}`, body: `Draft for ${body.profile!.name}\n${confirmed.map(item => item.text).join('\n')}`,
        recipient_email: 'checked@example.edu', recipient_status: 'revealed', mailto_link: '', method: 'ai',
        pipeline_version: 'writing-entry-fixture', corpus_version: 'writing-entry-fixture' };
      if (path.endsWith('/variants')) await route.fulfill({ json: { ...draft, variants: [{ id: 'checked', label: 'Checked template', ...draft }] } });
      else await route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ stage: 'done', ...draft })}\n\n` });
    } else if (path === '/api/tailor') {
      await route.fulfill({ json: { opportunity_id: TARGET, target_version: body.expected_target_version, method: 'ai', warnings: [], pipeline_version: 'w13.4', generated_at: new Date().toISOString(),
        tailored_bullets: body.original_bullets!.map((text, index) => ({ text, source_evidence: text, source_index: index })) } });
    } else if (path === '/api/tailor/structure') {
      const bullets = body.resume_text!.split('\n').filter(line => line.startsWith('- ')).map((line, index) => ({ id: `bullet-${index}`, text: line.slice(2) }));
      await route.fulfill({ json: { sections: [{ id: 'section', heading: 'Experience', kind: 'experience', bullets }], method: 'heuristic', warnings: [] } });
    } else if (path === '/api/tailor/renovate') {
      await route.fulfill({ json: { opportunity_id: TARGET, target_version: body.expected_target_version, sections: body.sections!.map(section => ({ ...section,
        bullets: section.bullets.map(bullet => ({ id: bullet.id, base_text: bullet.text, action: 'keep', variants: [], current: -1 })) })), method: 'fallback', warnings: [] } });
    } else if (path === '/api/tailor/bullet') {
      await route.fulfill({ json: { opportunity_id: body.opportunity_id, target_version: body.expected_target_version, text: body.current_text, source_evidence: '', changed: false, method: 'fallback', warnings: [] } });
    } else await route.fulfill({ status: 503, json: { error: 'Unrequested synthetic generation route' } });
  });
  return requests;
}
const emailFields = (page: Page) => {
  const fields = page.getByTestId('cold-email-editor-fields');
  return { subject: fields.locator('#cold-email-subject'), body: fields.locator('#cold-email-body'), recipient: fields.locator('#cold-email-to'),
    instruction: page.getByRole('textbox', { name: 'Request an edit', exact: true }) };
};
test.afterEach(async ({ context }, info) => {
  if (info.status !== info.expectedStatus) for (const [index, page] of context.pages().entries()) await attachProfileReadDiagnostics(page, info, `writing-entry-page-${index}`);
});

test.describe('Writing entry checks use current profiles', () => {
  test('Favorites email reads silent changes before generation, then preserves all manual fields when a later check discovers deletion', async ({ page }) => {
    const owner = await seed(page), writes = profileWrites(page), requests = await installWriting(page);
    let gate: Awaited<ReturnType<typeof gateProfileRead>> | undefined;
    try {
      await enter(page, 'favorites');
      const nextEntries = [entry(NEW_BULLET)];
      await commit(owner, { name: NEW_NAME, experience_entries: nextEntries });
      expect((await localProfile(page))!.name).toBe(OLD_NAME);
      gate = await gateProfileRead(page);
      await page.getByRole('button', { name: 'Draft Email', exact: true }).click();
      await expect.poll(gate.started).toBe(true); expect(requests).toEqual([]);
      gate.release();
      const fields = emailFields(page);
      await expect(fields.body).toHaveValue(`Draft for ${NEW_NAME}\n${NEW_BULLET}`);
      await expect.poll(() => requests.some(item => item.path.endsWith('/stream'))).toBe(true);
      for (const request of requests) {
        expect(request.profile!.name).toBe(NEW_NAME);
        expect(request.experience_evidence).toEqual({ version: 2, resume_master: profile().resume_master, resume_text: profile().resume_text, entries: nextEntries });
      }
      await fields.subject.fill('My retained subject'); await fields.body.fill(MANUAL);
      await fields.recipient.fill('manual@example.edu'); await fields.instruction.fill('Keep my unsent request');
      const node = await page.getByRole('dialog').elementHandle(), count = requests.length;
      const url = new URL('/rest/v1/profiles', STUB); url.searchParams.set('id', `eq.${owner.uid}`);
      expect((await owner.http.delete(url.href, { headers: { Authorization: `Bearer ${owner.token}` } })).status()).toBe(204);
      gate = await gateProfileRead(page);
      await page.getByRole('button', { name: 'Submit request', exact: true }).click();
      await expect.poll(gate.started).toBe(true); gate.release();
      await expect(page.getByRole('dialog').getByTestId('profile-refresh-status')).toContainText(MISSING);
      expect(await node!.evaluate(element => element.isConnected)).toBe(true);
      await expect(fields.subject).toHaveValue('My retained subject'); await expect(fields.body).toHaveValue(MANUAL);
      await expect(fields.recipient).toHaveValue('manual@example.edu'); await expect(fields.instruction).toHaveValue('Keep my unsent request');
      await expect(fields.body).toBeEditable();
      await expect(page.getByRole('button', { name: 'Submit request', exact: true })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Open in Email', exact: true })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Copy', exact: true })).toBeEnabled();
      expect(requests).toHaveLength(count); expect(writes).toEqual([]);
      expect(await (await owner.http.get(url.href, { headers: { Authorization: `Bearer ${owner.token}` } })).json()).toEqual([]);
      await page.screenshot({ path: test.info().outputPath('favorites-deleted-profile-manual-email.png') });
    } finally { gate?.release(); await owner.http.dispose(); }
  });

  test('Favorites Tailor checks new skills and courses but sends the complete manual bullets unchanged', async ({ page }) => {
    const owner = await seed(page), writes = profileWrites(page), requests = await installWriting(page);
    let gate: Awaited<ReturnType<typeof gateProfileRead>> | undefined;
    try {
      await enter(page, 'favorites'); await page.getByRole('button', { name: 'Tailor Resume', exact: true }).click();
      const input = page.locator('#tailor-bullets-input'); await input.fill(MANUAL);
      const skills: ProfileData['skills'] = [{ name: 'R', level: 'beginner' }];
      await commit(owner, { name: NEW_NAME, skills, coursework: ['STAT 400'] });
      expect((await localProfile(page))!.name).toBe(OLD_NAME);
      gate = await gateProfileRead(page);
      await page.getByRole('button', { name: 'Tailor with AI', exact: true }).click();
      await expect.poll(gate.started).toBe(true); expect(requests).toEqual([]);
      gate.release();
      await expect(page.getByText('Your profile, opportunity requirements, or tailoring rules changed. Review these bullets before continuing.', { exact: true })).toBeVisible();
      expect(requests).toEqual([]);
      await page.getByRole('button', { name: 'I reviewed these bullets', exact: true }).click();
      await page.getByRole('button', { name: 'Tailor with AI', exact: true }).click();
      await expect.poll(() => requests.length).toBe(1);
      expect(requests[0]).toMatchObject({ path: '/api/tailor', opportunity_id: TARGET,
        profile: { name: NEW_NAME, hard_skills: skills, coursework: ['STAT 400'] }, original_bullets: [MANUAL] });
      await expect(input).toHaveValue(MANUAL);
      await expect(page.getByRole('button', { name: 'Re-tailor', exact: true })).toBeEnabled();
      expect(writes).toEqual([]);
      await page.screenshot({ path: test.info().outputPath('favorites-tailor-latest-profile-manual-bullets.png') });
    } finally { gate?.release(); await owner.http.dispose(); }
  });

  test('Detail legacy renovation checks a silently replaced source before structuring and rewriting', async ({ page }) => {
    const owner = await seed(page), writes = profileWrites(page), requests = await installWriting(page);
    let gate: Awaited<ReturnType<typeof gateProfileRead>> | undefined;
    try {
      await openLegacy(page);
      await commit(owner, { name: NEW_NAME, resume_text: rawResume(NEW_BULLET), coursework: ['STAT 400'] });
      expect((await localProfile(page))!.resume_text).toBe(rawResume(OLD_BULLET));
      gate = await gateProfileRead(page);
      await page.getByRole('button', { name: 'Renovate with AI', exact: true }).click();
      await expect.poll(gate.started).toBe(true); expect(requests).toEqual([]);
      gate.release();
      await expect(page.getByText(NEW_BULLET, { exact: true })).toBeVisible();
      expect(requests.map(item => item.path)).toEqual(['/api/tailor/structure', '/api/tailor/renovate']);
      expect(requests[0].resume_text).toBe(rawResume(NEW_BULLET));
      expect(requests[1]).toMatchObject({ profile: { name: NEW_NAME, coursework: ['STAT 400'] }, opportunity_id: TARGET });
      expect(requests[1].sections?.flatMap(section => section.bullets.map(bullet => bullet.text))).toEqual([NEW_BULLET, SECOND_BULLET]);
      await expect(page.getByText(OLD_BULLET, { exact: true })).toHaveCount(0);
      expect(writes).toEqual([]);
      await page.screenshot({ path: test.info().outputPath('detail-legacy-new-source.png') });
    } finally { gate?.release(); await owner.http.dispose(); }
  });

  test('Detail legacy keeps an unsaved inline edit when a pending bullet check observes changed source material', async ({ page }) => {
    const owner = await seed(page), writes = profileWrites(page), requests = await installWriting(page);
    let gate: Awaited<ReturnType<typeof gateProfileRead>> | undefined;
    try {
      await openLegacy(page); await page.getByRole('button', { name: 'Renovate with AI', exact: true }).click();
      await expect(page.getByText(OLD_BULLET, { exact: true })).toBeVisible();
      await page.getByRole('button', { name: 'Edit this bullet', exact: true }).first().click();
      const input = page.getByRole('textbox', { name: 'Edit this bullet', exact: true }); await input.fill(MANUAL);
      await commit(owner, { name: NEW_NAME, resume_text: rawResume(NEW_BULLET), coursework: ['STAT 400'] });
      const count = requests.length;
      gate = await gateProfileRead(page);
      await page.getByRole('button', { name: 'Ask AI to re-optimize this bullet', exact: true }).click();
      await expect.poll(gate.started).toBe(true); expect(requests).toHaveLength(count);
      gate.release();
      const notice = page.getByTestId('renovation-source-review');
      await expect(notice).toHaveCount(1);
      await expect(notice).toHaveText(SOURCE_CHANGED);
      await expect(notice).toBeVisible();
      await expect(page.getByTestId('renovation-action-error')).toHaveCount(0);
      await expect(page.getByTestId('renovation-profile-changed')).toHaveCount(0);
      await expect(page.getByTestId('renovation-profile-unknown')).toHaveCount(0);
      await expect(page.getByText('Your résumé text changed since this renovation was saved — consider re-renovating.', { exact: true })).toHaveCount(0);
      await expect(input).toHaveValue(MANUAL); await expect(input).toBeEditable();
      expect(requests.filter(item => item.path === '/api/tailor/bullet')).toEqual([]);
      expect(requests).toHaveLength(count); expect(writes).toEqual([]);
      await page.screenshot({ path: test.info().outputPath('detail-legacy-source-change-keeps-inline-edit.png') });
    } finally { gate?.release(); await owner.http.dispose(); }
  });
});

// Batch 22 additions: the authority fixture starts with the real anonymous
// loopback detail projection, not a card or an internally stamped record.
async function installControlledWritingTarget(page: Page) {
  const baseURL = String(test.info().project.use.baseURL);
  expect(new URL(baseURL).hostname).toBe('127.0.0.1');
  const path = `/api/opportunities/${encodeURIComponent(TARGET)}`;
  const response = await page.request.get(`${path}?_release_scope=${encodeURIComponent(PUBLIC_RELEASE_CACHE_VERSION)}`, {
    headers: { Accept: 'application/json' },
  });
  expect(response.status()).toBe(200);
  const base = await response.json() as Opportunity;
  expect(base).toMatchObject({ id: TARGET, title: expect.any(String), organization: expect.any(String),
    metadata: expect.any(Object), target_truth: { actionable: true } });
  expect(base.contact_email_status).not.toBe('revealed');
  expect(base).not.toHaveProperty('contact_email');
  let reply: { status: number; body: unknown } = { status: 200, body: base };
  let reads = 0;
  let held: { gate: Promise<void>; release: () => void; started: boolean } | null = null;
  await page.route(url => url.pathname === path, async route => {
    const url = new URL(route.request().url());
    // Only the new anonymous, release-scoped detail reader is controlled.
    // Favorites' existing list/detail and contact-reveal reads remain real.
    if (route.request().method() !== 'GET'
      || url.searchParams.get('_release_scope') !== PUBLIC_RELEASE_CACHE_VERSION
      || route.request().headers().authorization !== undefined) { await route.fallback(); return; }
    reads += 1;
    const captured = structuredClone(reply), gate = held;
    if (gate) { held = null; gate.started = true; await gate.gate; }
    try { await route.fulfill({ status: captured.status, json: captured.body, headers: { 'Cache-Control': 'no-store' } }); }
    catch (error) { if (!route.request().failure()) throw error; }
  });
  return {
    base, reads: () => reads,
    respond(status: number, body: unknown = base) { reply = { status, body }; },
    holdNext() {
      let release!: () => void; const gate = new Promise<void>(resolve => { release = resolve; });
      const record = { gate, release, started: false }; held = record;
      return { release, started: () => record.started };
    },
  };
}
async function openTargetCheckedEmail(page: Page, requests: WritingRequest[]) {
  await enter(page, 'favorites');
  await page.getByRole('button', { name: 'Draft Email', exact: true }).click();
  await expect(emailFields(page).body).toHaveValue(`Draft for ${OLD_NAME}\n${OLD_BULLET}`);
  await expect.poll(() => requests.some(request => request.path === '/api/cold-email/stream')).toBe(true);
  await expect(page.getByRole('button', { name: 'Shorter', exact: true })).toBeEnabled();
}
async function fillRetainedEmail(page: Page) {
  const fields = emailFields(page);
  await fields.subject.fill('My target-check subject 王'); await fields.body.fill(MANUAL);
  await fields.recipient.fill('manual-target@example.edu'); await fields.instruction.fill('Keep my unsent target-check request.');
  return fields;
}
async function expectRetainedEmail(page: Page) {
  const fields = emailFields(page);
  await expect(fields.subject).toHaveValue('My target-check subject 王'); await expect(fields.body).toHaveValue(MANUAL);
  await expect(fields.recipient).toHaveValue('manual-target@example.edu'); await expect(fields.instruction).toHaveValue('Keep my unsent target-check request.');
  await expect(fields.body).toBeEditable();
}
async function reconnectWritingPage(page: Page) {
  // Real browser connectivity events: Chromium focus alone is not reliable
  // in headless test contexts. No synthesized application/DOM callbacks.
  await page.context().setOffline(true);
  await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
  await page.bringToFront();
  await page.context().setOffline(false);
  await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(true);
}

test.describe('Writing entry checks use current authoritative targets', () => {
  for (const scenario of [
    { name: '503 preflight failure', code: 503, reason: 'Could not verify this opportunity. Your draft is kept; generation and outreach are paused.', preflight: true },
    { name: '404 after reconnect', code: 404, reason: 'This opportunity could not be found. Your draft is kept; generation and outreach are paused.', preflight: false },
    { name: 'closed target after reconnect', code: 200, reason: 'Applications for this opportunity are closed. Your draft is kept; generation and outreach are paused.', preflight: false },
  ]) test(`Favorites email preserves every manual field through ${scenario.name} and an explicit same-target retry`, async ({ page }) => {
    const owner = await seed(page), writes = profileWrites(page), requests = await installWriting(page);
    try {
      const target = await installControlledWritingTarget(page);
      await openTargetCheckedEmail(page, requests); await fillRetainedEmail(page);
      const count = requests.length, reads = target.reads(), dialog = await page.getByRole('dialog').elementHandle();
      const closed = { ...target.base, target_truth: { ...target.base.target_truth!, actionable: false,
        listing_state: 'closed', accepting_state: 'not_accepting', reason_code: 'listing_closed' },
        application: { ...target.base.application, application_url: null }, contact_email_status: 'unavailable' };
      target.respond(scenario.code, scenario.code === 200 ? closed : { detail: 'Synthetic target read failure' });
      if (scenario.preflight) await page.getByRole('button', { name: 'Shorter', exact: true }).click();
      else await reconnectWritingPage(page);
      await expect.poll(target.reads).toBeGreaterThan(reads);
      const notice = page.getByRole('dialog').getByTestId('writing-target-status');
      await expect(notice).toContainText(scenario.reason);
      await expect(notice.getByRole('button', { name: 'Check opportunity again', exact: true })).toBeEnabled();
      await expectRetainedEmail(page);
      expect(await dialog!.evaluate(element => element.isConnected)).toBe(true);
      await expect(page.getByRole('button', { name: 'Shorter', exact: true })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Submit request', exact: true })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Open in Email', exact: true })).toBeDisabled();
      expect(requests).toHaveLength(count); expect(requests.filter(request => request.path.endsWith('/refine'))).toEqual([]);
      target.respond(200);
      await notice.getByRole('button', { name: 'Check opportunity again', exact: true }).click();
      await expect(page.getByRole('dialog').getByTestId('writing-target-status')).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Shorter', exact: true })).toBeEnabled();
      await expectRetainedEmail(page); expect(requests).toHaveLength(count); expect(writes).toEqual([]);
      await page.screenshot({ path: test.info().outputPath(`target-${scenario.code}-email-retained.png`) });
    } finally { await owner.http.dispose(); }
  });

  test('a same-id target description change discovered by Shorter preserves the draft and requires explicit regeneration', async ({ page }) => {
    const owner = await seed(page), writes = profileWrites(page), requests = await installWriting(page);
    try {
      const target = await installControlledWritingTarget(page);
      await openTargetCheckedEmail(page, requests); await fillRetainedEmail(page);
      const count = requests.length, reads = target.reads();
      target.respond(200, { ...target.base, description_clean: `${target.base.description_clean}\nUpdated target requirements: document calibration uncertainty.` });
      await page.getByRole('button', { name: 'Shorter', exact: true }).click();
      await expect.poll(target.reads).toBeGreaterThan(reads);
      await expect(page.getByText('Your profile or target details changed. Your subject, message and recipient are kept. Regenerate when you are ready to replace this draft.', { exact: true })).toBeVisible();
      await expectRetainedEmail(page);
      await expect(page.getByRole('button', { name: 'Regenerate from updated materials', exact: true })).toBeEnabled();
      await expect(page.getByRole('button', { name: 'Shorter', exact: true })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Submit request', exact: true })).toBeDisabled();
      expect(requests).toHaveLength(count); expect(writes).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('a quiet unchanged target read keeps the in-flight automatic email stream eligible to populate the editor', async ({ page }) => {
    await page.clock.install();
    const owner = await seed(page), writes = profileWrites(page), requests = await installWriting(page);
    let releaseStream!: () => void;
    const streamGate = new Promise<void>(resolve => { releaseStream = resolve; });
    let targetGate: { release: () => void; started: () => boolean } | undefined;
    const streamBody = 'Stream completed after an unchanged public target check. 王';
    let streamStarted = false;
    await page.route('**/api/cold-email/stream', async route => {
      const body = route.request().postDataJSON() as Omit<WritingRequest, 'path'>;
      requests.push({ ...body, path: '/api/cold-email/stream' }); streamStarted = true;
      await streamGate;
      try { await route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ stage: 'done', opportunity_id: body.opportunity_id, target_version: body.expected_target_version, contact_context_receipt: contactReceiptForRequest(body),
        subject: 'Completed unchanged-target stream', body: streamBody, recipient_email: 'checked@example.edu',
        recipient_status: 'revealed', method: 'ai', mailto_link: '' })}\n\n` }); }
      catch (error) { if (!route.request().failure()) throw error; }
    });
    try {
      const target = await installControlledWritingTarget(page);
      await enter(page, 'favorites'); await page.getByRole('button', { name: 'Draft Email', exact: true }).click();
      await expect.poll(() => streamStarted).toBe(true);
      await expect(emailFields(page).body).toHaveValue(`Draft for ${OLD_NAME}\n${OLD_BULLET}`);
      const node = await page.getByTestId('cold-email-editor-fields').elementHandle(), reads = target.reads();
      targetGate = target.holdNext();
      await page.clock.fastForward(60_000);
      await expect.poll(targetGate.started).toBe(true); expect(target.reads()).toBeGreaterThan(reads);
      await expect(page.getByRole('dialog').getByTestId('writing-target-status')).toHaveCount(0);
      expect(await node!.evaluate(element => element.isConnected)).toBe(true);
      // Register before release so an immediate local response cannot be missed.
      const response = page.waitForResponse(reply => new URL(reply.url()).pathname === `/api/opportunities/${TARGET}`
        && new URL(reply.url()).searchParams.get('_release_scope') === PUBLIC_RELEASE_CACHE_VERSION
        && reply.request().headers().authorization === undefined && reply.status() === 200);
      targetGate.release();
      await response;
      releaseStream();
      await expect(emailFields(page).body).toHaveValue(streamBody);
      await expect(emailFields(page).subject).toHaveValue('Completed unchanged-target stream');
      await expect(page.getByRole('button', { name: 'Shorter', exact: true })).toBeEnabled();
      expect(requests.filter(request => request.path === '/api/cold-email/stream')).toHaveLength(1);
      expect(requests.filter(request => request.path === '/api/cold-email')).toEqual([]);
      expect(writes).toEqual([]);
    } finally { targetGate?.release(); releaseStream(); await owner.http.dispose(); }
  });

  test('a changed opportunity keeps the complete manually edited target résumé on its original snapshot and disables AI', async ({ page }) => {
    const owner = await seed(page), writes = profileWrites(page), requests = await installWriting(page);
    try {
      const target = await installControlledWritingTarget(page);
      await enter(page, 'detail'); await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: 'Target résumé', exact: true });
      await dialog.getByRole('button', { name: 'Create from confirmed master', exact: true }).click();
      const name = dialog.getByRole('textbox', { name: 'Edit Full name', exact: true });
      await expect(name).toHaveValue(OLD_NAME); await name.fill(MANUAL);
      const title = dialog.getByRole('checkbox', { name: 'Include field: Title', exact: true }); await title.uncheck();
      const ai = dialog.getByRole('button', { name: 'Generate AI suggestions', exact: true }); await expect(ai).toBeEnabled();
      const count = requests.length, reads = target.reads(), node = await name.elementHandle();
      const changedDescription = 'Newly revised target description: different instrumentation requirements.';
      target.respond(200, { ...target.base, description_clean: changedDescription });
      await reconnectWritingPage(page); await expect.poll(target.reads).toBeGreaterThan(reads);
      await expect(dialog.getByText('This draft was created from different profile or target materials. Your edits and original source remain intact; they were not rebound to the current profile.', { exact: true })).toBeVisible();
      await expect(ai).toBeDisabled(); await expect(name).toHaveValue(MANUAL); await expect(name).toBeEditable();
      await expect(title).not.toBeChecked(); expect(await node!.evaluate(element => element.isConnected)).toBe(true);
      const originals = dialog.locator('details').filter({ has: page.getByText('Target requirements and original materials', { exact: true }) });
      await originals.locator('summary').first().click();
      await expect(originals.getByText(target.base.description_clean, { exact: true })).toBeVisible();
      await expect(originals.getByText(changedDescription, { exact: true })).toHaveCount(0);
      await expect(dialog.getByRole('button', { name: 'Rebuild from current confirmed master', exact: true })).toBeEnabled();
      await expect(dialog.getByText('Unsaved local edits', { exact: true })).toBeVisible();
      expect(requests).toHaveLength(count); expect(writes).toEqual([]);
    } finally { await owner.http.dispose(); }
  });
});


// These round trips use the real browser SDK and loopback CAS store. They do
// not establish hosted database permissions or real model quality.
test.describe('Saved opportunity requirements', () => {
  test.describe.configure({ timeout: 90_000 });
  const legacyNotice = 'This older draft did not save all opportunity requirements. You can still edit, save and export it. Rebuild to use AI with the current requirements.';
  async function saveDraft(page: Page, revision: number): Promise<{ status: string; revision: number; doc: TargetResumeV1 }> {
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/rest/v1/rpc/commit_target_resume_cas'
      && r.request().postDataJSON()?.p_expected_revision === revision);
    await page.getByRole('button', { name: 'Save target draft', exact: true }).click();
    const receipt = await (await response).json();
    expect(receipt.status).toBe('saved'); expect(receipt.revision).toBe(revision + 1);
    await expect(page.getByText(`Saved version ${revision + 1}`, { exact: true })).toBeVisible();
    return receipt;
  }
  async function newDraft(page: Page) {
    await enter(page, 'detail');
    await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
    await page.getByRole('button', { name: 'Create from confirmed master', exact: true }).click();
    await expect(page.getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue(OLD_NAME);
  }
  function forbidAI(page: Page) {
    const requests: string[] = [];
    return page.route('**/api/tailor/full-target/suggestions', async route => {
      requests.push(route.request().url());
      await route.fulfill({ status: 503, json: { detail: { code: 'synthetic_unexpected_ai' } } });
    }).then(() => requests);
  }
  test('criteria-only changes survive close and reopen without replacing the saved draft', async ({ page }, info) => {
    const owner = await seed(page), writes = profileWrites(page), ai = await forbidAI(page);
    try {
      const target = await installControlledWritingTarget(page);
      target.respond(200, { ...target.base, deadline: '2026-12-15', skills_attribution: 'inferred',
        eligibility: { ...target.base.eligibility, citizenship_required: false } });
      await newDraft(page);
      await page.getByRole('textbox', { name: 'Edit Full name', exact: true }).fill(MANUAL);
      const saved = await saveDraft(page, 0);
      expect(saved.doc.target_snapshot).toMatchObject({ context_version: 2, criteria: { eligibility: {
        citizenship_required: false,
      } } });
      await page.getByRole('button', { name: 'Close target résumé', exact: true }).click();
      target.respond(200, { ...target.base, deadline: '2027-01-31',
        eligibility: { ...target.base.eligibility, citizenship_required: true },
        application: { ...target.base.application, requires_transcript: 'yes' } });
      await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
      await expect(page.getByText(/This draft was created from different profile or target materials/)).toBeVisible();
      await expect(page.getByRole('button', { name: 'Generate AI suggestions', exact: true })).toBeDisabled();
      await expect(page.getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue(MANUAL);
      await page.getByText('Target requirements and original materials', { exact: true }).click();
      const criteria = page.getByTestId('saved-target-criteria');
      await expect(criteria).toBeVisible(); await expect(criteria).toContainText('2026-12-15');
      await expect(criteria).not.toContainText('2027-01-31');
      await expect(criteria.getByText('Required skills (inferred)', { exact: true })).toHaveCount(1);
      await expect(criteria.getByRole('region', { name: 'Eligibility', exact: true }).locator('div').filter({
        has: page.locator('dt').getByText('Citizenship requirement', { exact: true }),
      }).locator('dd')).toHaveText('No');
      await expect(criteria.getByRole('region', { name: 'Inference flags', exact: true }).locator('div').filter({
        has: page.locator('dt').getByText('Skills', { exact: true }),
      }).locator('dd')).toHaveText('Inferred');
      // The containing modal scrolls. Screenshot each visible section; a
      // screenshot of its taller child would include clipped background UI.
      for (const [name, file] of [['Eligibility', 'eligibility'], ['Dates and duration', 'dates'], ['Inference flags', 'attribution']] as const) {
        const section = criteria.getByRole('region', { name, exact: true });
        await section.scrollIntoViewIfNeeded();
        await section.screenshot({ path: info.outputPath(`saved-${file}.png`) });
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
      await page.getByRole('textbox', { name: 'Edit Full name', exact: true }).fill('Further manual edit 王');
      const again = await saveDraft(page, 1);
      expect(again.doc.target_snapshot).toEqual(saved.doc.target_snapshot);
      expect(again.doc.base).toEqual(saved.doc.base);
      expect(ai).toEqual([]); expect(writes).toEqual([]);
    } finally { await owner.http.dispose(); }
  });
  test('legacy snapshots save and export, then rebuild and restore without silently changing their history', async ({ page }, info) => {
    const owner = await seed(page), ai = await forbidAI(page);
    try {
      await installControlledWritingTarget(page); await newDraft(page);
      const saved = await saveDraft(page, 0);
      await page.getByRole('button', { name: 'Close target résumé', exact: true }).click();
      const legacy = structuredClone(saved.doc);
      const { opportunity_id, title, organization, source_url, description, requirements } = legacy.target_snapshot;
      legacy.target_snapshot = { opportunity_id, title, organization, source_url, description, requirements };
      const canonical = JSON.stringify(legacy.target_snapshot, (_key, value: unknown) => value && typeof value === 'object' && !Array.isArray(value)
        ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : value);
      legacy.base.target_signature = `v1:sha256:${createHash('sha256').update(canonical).digest('hex')}`;
      const seeded = await owner.http.post(new URL('/rest/v1/rpc/commit_target_resume_cas', STUB).href, {
        headers: { Authorization: `Bearer ${owner.token}` }, data: { p_expected_owner: owner.uid,
          p_opportunity_id: TARGET, p_expected_revision: 1, p_doc: legacy },
      });
      expect(seeded.status()).toBe(200); expect(await seeded.json()).toMatchObject({ status: 'saved', revision: 2 });
      await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
      await expect(page.getByText(legacyNotice, { exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Generate AI suggestions', exact: true })).toBeDisabled();
      await page.getByRole('textbox', { name: 'Edit Full name', exact: true }).fill('Legacy hand edit 王');
      const third = await saveDraft(page, 2);
      expect(third.doc.target_snapshot).toEqual(legacy.target_snapshot);
      expect(third.doc.base.target_signature).toBe(legacy.base.target_signature);
      const file = page.waitForEvent('download');
      const rendered = page.waitForResponse(r => new URL(r.url()).pathname === '/api/resume/full-target/export');
      await page.getByRole('button', { name: 'Export PDF', exact: true }).click();
      const response = await rendered; expect(response.status()).toBe(200);
      expect(JSON.stringify(response.request().postDataJSON())).not.toContain('target_snapshot');
      const pdf = await file; await pdf.saveAs(info.outputPath('legacy-retained-draft.pdf'));
      await page.getByRole('button', { name: 'Rebuild from current confirmed master', exact: true }).click();
      await page.getByRole('button', { name: 'Create new draft', exact: true }).click();
      await expect(page.getByText(legacyNotice, { exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Generate AI suggestions', exact: true })).toBeEnabled();
      const fourth = await saveDraft(page, 3);
      expect(fourth.doc.target_snapshot).toMatchObject({ context_version: 2 });
      await page.getByText('Version history', { exact: true }).click();
      await page.getByRole('button', { name: 'Load latest 20 versions', exact: true }).click();
      await page.getByRole('button', { name: /^View version 3 ·/ }).click();
      const restored = page.waitForResponse(r => new URL(r.url()).pathname === '/rest/v1/rpc/commit_target_resume_cas'
        && r.request().postDataJSON()?.p_expected_revision === 4);
      await page.getByRole('button', { name: 'Restore selected version as a new save', exact: true }).click();
      const fifth = await (await restored).json();
      expect(fifth).toMatchObject({ status: 'saved', revision: 5, doc: third.doc });
      await expect(page.getByText(legacyNotice, { exact: true })).toBeVisible();
      await expect(page.getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue('Legacy hand edit 王');
      await expect(page.getByRole('button', { name: 'Generate AI suggestions', exact: true })).toBeDisabled();
      expect(ai).toEqual([]);
    } finally { await owner.http.dispose(); }
  });
});


test('an interrupted email stream keeps manual text and does not make a second generation request', async ({ page }) => {
  const owner = await seed(page), requests = await installWriting(page);
  let release!: () => void; const gate = new Promise<void>(resolve => { release = resolve; });
  let started = false;
  await page.route('**/api/cold-email/stream', async route => {
    requests.push({ ...route.request().postDataJSON(), path: '/api/cold-email/stream' }); started = true;
    await gate;
    await route.fulfill({ status: 503, contentType: 'text/plain', body: 'Private upstream details must not appear' });
  });
  try {
    await enter(page, 'favorites'); await page.getByRole('button', { name: 'Draft Email', exact: true }).click();
    await expect.poll(() => started).toBe(true);
    await expect(emailFields(page).body).toHaveValue(`Draft for ${OLD_NAME}\n${OLD_BULLET}`);
    await emailFields(page).body.fill(MANUAL);
    const failed = page.waitForResponse(response => new URL(response.url()).pathname === '/api/cold-email/stream' && response.status() === 503);
    release(); await failed;
    await expect(page.getByRole('button', { name: 'Shorter', exact: true })).toBeEnabled();
    await expect(emailFields(page).body).toHaveValue(MANUAL);
    await expect(page.getByText('Private upstream details must not appear')).toHaveCount(0);
    expect(requests.filter(request => request.path === '/api/cold-email/stream')).toHaveLength(1);
    expect(requests.filter(request => request.path === '/api/cold-email')).toEqual([]);
  } finally { release(); await owner.http.dispose(); }
});
