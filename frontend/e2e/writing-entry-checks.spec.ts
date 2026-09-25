import { test, expect, request as apiRequest, type APIRequestContext, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { ExperienceEntry, ProfileData, ProfileRequest, ResumeSectionInput } from '../src/lib/types';
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
  original_bullets?: string[]; sections?: ResumeSectionInput[]; current_text?: string;
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
    if (path === '/api/tailor/status') { await route.fulfill({ json: { ai_available: true } }); return; }
    const body = route.request().postDataJSON() as Omit<WritingRequest, 'path'>;
    requests.push({ ...body, path });
    if (path === '/api/cold-email/variants' || path === '/api/cold-email/stream') {
      const confirmed = body.experience_evidence!.entries.filter(item => item.status === 'confirmed');
      const draft = { subject: `Checked ${body.profile!.name}`, body: `Draft for ${body.profile!.name}\n${confirmed.map(item => item.text).join('\n')}`,
        recipient_email: 'checked@example.edu', recipient_status: 'revealed', mailto_link: '', method: 'ai',
        pipeline_version: 'writing-entry-fixture', corpus_version: 'writing-entry-fixture' };
      if (path.endsWith('/variants')) await route.fulfill({ json: { ...draft, variants: [{ id: 'checked', label: 'Checked template', ...draft }] } });
      else await route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ stage: 'done', ...draft })}\n\n` });
    } else if (path === '/api/tailor') {
      await route.fulfill({ json: { opportunity_id: TARGET, method: 'ai', warnings: [],
        tailored_bullets: body.original_bullets!.map((text, index) => ({ text, source_evidence: text, source_index: index })) } });
    } else if (path === '/api/tailor/structure') {
      const bullets = body.resume_text!.split('\n').filter(line => line.startsWith('- ')).map((line, index) => ({ id: `bullet-${index}`, text: line.slice(2) }));
      await route.fulfill({ json: { sections: [{ id: 'section', heading: 'Experience', kind: 'experience', bullets }], method: 'heuristic', warnings: [] } });
    } else if (path === '/api/tailor/renovate') {
      await route.fulfill({ json: { opportunity_id: TARGET, sections: body.sections!.map(section => ({ ...section,
        bullets: section.bullets.map(bullet => ({ id: bullet.id, base_text: bullet.text, action: 'keep', variants: [], current: -1 })) })), method: 'fallback', warnings: [] } });
    } else if (path === '/api/tailor/bullet') {
      await route.fulfill({ json: { text: body.current_text, source_evidence: '', changed: false, method: 'fallback', warnings: [] } });
    } else await route.fulfill({ status: 503, json: { error: 'Unrequested synthetic generation route' } });
  });
  return requests;
}
const emailFields = (page: Page) => {
  const fields = page.getByTestId('cold-email-editor-fields');
  return { subject: fields.locator('input[type="text"]'), body: fields.locator('textarea'), recipient: fields.locator('input[type="email"]'),
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
        expect(request.experience_evidence).toEqual({ version: 1, resume_text: profile().resume_text, entries: nextEntries });
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
