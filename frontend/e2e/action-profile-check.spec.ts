import { test, expect, request as apiRequest, type APIRequestContext, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { ExperienceEntry, MatchesResponse, ProfileData, ProfileRequest, ResumeFact } from '../src/lib/types';
import { attachProfileReadDiagnostics } from './profile-read-diagnostics';

// Real SDK/coordinator reads from the loopback store. Independent HTTP writes
// are deliberately silent: no focus/online/storage event prompts a refresh.
// Writing/Match responses are synthetic and never reach a model/provider.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const TARGET = 'uiuc-siebel-ugresearch';
const OLD_NAME = 'Earlier profile student 王';
const NEW_NAME = 'Current profile student 王';
const OLD_FACT = 'Earlier confirmed instrumentation work, now withdrawn.';
const NEW_FACT = 'Current confirmed calibration work; I assisted and did not lead.';
const KEPT_FACT = 'Recorded uncertainty in the laboratory notebook.';
const MANUAL_BODY = 'Dear Professor,\n\nKeep my own careful wording exactly. I assisted; I did not lead.\n\n王';
const MANUAL_SUBJECT = 'My manually edited subject';
const MANUAL_RECIPIENT = 'manually-reviewed@example.edu';
const INSTRUCTION = 'Improve the flow without adding claims.';
const PROFILE_CHANGED = 'Your profile or target details changed. Your subject, message and recipient are kept. Regenerate when you are ready to replace this draft.';
const fact = (id: string, value: string): ResumeFact => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
const entry = (id: string, text: string): ExperienceEntry => ({ id, revision: 1, status: 'confirmed', text, source: { kind: 'manual' } });
const isProfile = (url: string) => new URL(url).pathname === '/rest/v1/profiles';
interface Owner { http: APIRequestContext; uid: string; token: string; revision: number }
interface WritingRequest {
  path: string;
  profile: ProfileRequest;
  opportunity_id: string;
  experience_evidence: { version: number; resume_text: string; entries: ExperienceEntry[] };
  current_body?: string;
}
function profile(): ProfileData {
  return { name: OLD_NAME, institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
    major: 'Computer Science', grade: 'Sophomore', is_international: false, research_interests: 'instrumentation',
    skills: [], coursework: [], seeking_types: ['research'], resume_text: 'Complete unchanged original source 王',
    experience_entries: [entry('earlier', OLD_FACT), entry('kept', KEPT_FACT)],
    resume_master: { version: 1, id: 'action-master', revision: 1, source_signature: null,
      basics: { name: fact('name', OLD_NAME), links: [] }, education: [],
      activities: [{ id: 'project', kind: 'project', title: fact('title', 'Instrument project'),
        details: [{ id: 'earlier', revision: 1 }, { id: 'kept', revision: 1 }] }],
      publications: [], skills: [], other_sections: [],
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
    await page.addInitScript(({ session, key }) => {
      if (!localStorage.getItem('action-profile-seeded')) {
        localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(key, 'en');
        localStorage.setItem('action-profile-seeded', '1');
      }
    }, { session, key: STORAGE_KEYS.LOCALE });
    const loaded = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
    await page.goto('/'); await loaded;
    await expect(page.locator('#student_name')).toHaveValue(OLD_NAME);
    await expect(page.getByRole('button', { name: /Generate Matches/i })).toBeEnabled();
    return owner;
  } catch (error) { await http.dispose(); throw error; }
}
async function currentLocalProfile(page: Page): Promise<ProfileData> {
  return page.evaluate(key => JSON.parse(localStorage.getItem(key) ?? 'null'), STORAGE_KEYS.PROFILE);
}
function browserProfileWrites(page: Page) {
  const writes: string[] = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method()) && /\/profiles$|\/commit_profile_patch_cas$/.test(path)) writes.push(path);
  });
  return writes;
}
async function installWriting(page: Page) {
  const requests: WritingRequest[] = [];
  // Any other generation path fails locally rather than calling a provider.
  for (const url of ['**/api/tailor**', '**/api/resume/**']) await page.route(url, route => route.fulfill({ status: 503, body: '{}' }));
  await page.route('**/api/cold-email**', async route => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON();
    requests.push({ ...body, path });
    const confirmed = (body.experience_evidence.entries as ExperienceEntry[]).filter(item => item.status === 'confirmed');
    const draft = { subject: `Checked ${body.profile.name}`, body: `Draft for ${body.profile.name}\n${confirmed.map(item => item.text).join('\n')}`,
      recipient_email: 'checked@example.edu', recipient_status: 'revealed', mailto_link: '', method: 'llm',
      pipeline_version: 'action-check-fixture', corpus_version: 'action-check-fixture' };
    if (path.endsWith('/variants')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...draft,
        variants: [{ id: 'checked', label: 'Checked template', ...draft }] }) });
    } else if (path.endsWith('/stream')) {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: `data: ${JSON.stringify({ stage: 'done', ...draft })}\n\n` });
    } else if (path.endsWith('/refine')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ body: 'Unexpected stale refine result', method: 'llm' }) });
    } else if (path === '/api/cold-email') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(draft) });
    } else await route.fulfill({ status: 503, body: '{}' });
  });
  return requests;
}
async function holdNextProfileRead(page: Page) {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let started = false;
  let serverRow: unknown;
  await page.route('**/rest/v1/profiles?**', async route => {
    if (started) { await route.continue(); return; }
    started = true;
    const response = await route.fetch({ maxRetries: 0 });
    expect(response.status()).toBe(200);
    serverRow = await response.json();
    await gate;
    try { await route.fulfill({ response }); }
    catch (error) { if (!route.request().failure()) throw error; }
  }, { times: 1 });
  return { release, started: () => started, row: () => serverRow };
}
async function detailReady(page: Page) {
  const read = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
  await page.goto(`/opportunities/${TARGET}`); await read;
  await expect(page.getByRole('button', { name: 'Draft email', exact: true })).toBeVisible();
  await expect(page.getByTestId('profile-refresh-status')).toHaveCount(0);
}
const fields = (page: Page) => {
  const section = page.getByTestId('cold-email-editor-fields');
  return { subject: section.locator('input[type="text"]'), body: section.locator('textarea'), recipient: section.locator('input[type="email"]'),
    instruction: page.getByRole('textbox', { name: 'Request an edit', exact: true }) };
};
function assertLatest(requests: WritingRequest[], entries: ExperienceEntry[]) {
  expect(requests.length).toBeGreaterThan(0);
  for (const item of requests) {
    expect(item.opportunity_id).toBe(TARGET);
    expect(item.profile.name).toBe(NEW_NAME);
    expect(item.experience_evidence).toEqual({ version: 1, resume_text: profile().resume_text, entries });
  }
}
function matches(include: boolean, name: string): MatchesResponse {
  const opportunity = { id: TARGET, title: 'Action-time match laboratory', organization: 'Example University',
    opportunity_type: 'research' as const, source_type: 'campus_program' as const, record_kind: 'listing' as const,
    source: 'manual', school: 'uiuc', audience: 'campus' as const, paid: 'yes' as const,
    location: 'Campus', on_campus: true, source_url: 'https://example.edu/action-fixture',
    description_clean: 'Instrumentation research with undergraduate students.', keywords: ['instrumentation'], is_rolling: true,
    target_truth: { listing_state: 'open' as const, reference_only: false, actionable: true, accepting_state: 'accepting' as const,
      reason_code: null, verified_at: null, expires_at: null },
    eligibility: { international_friendly: 'yes' as const, preferred_year: [], majors: [], skills_required: [], citizenship_required: false },
    application: { application_effort: 'medium' as const, requires_resume: 'yes' as const, contact_method: 'email' },
    metadata: { is_active: true, confidence_score: 1 } };
  const results = include ? [{ opportunity_id: TARGET, opportunity, eligibility_score: 90, readiness_score: 90,
    upside_score: 90, final_score: 90, bucket: 'high_priority' as const, reasons_fit: [], reasons_gap: [], next_steps: [] }] : [];
  return { total: 1, high_priority: 1, good_match: 0, reach: 0, low_fit: 0, results, returned_count: results.length,
    has_more: false, next_cursor: null, result_set_id: `action-set-${name}`, view_id: `action-view-${name}`,
    contract_version: 'match-view-v3-faculty-trust', target_truth_contract: 'target-truth-v2', view_start: 0, filtered_total: results.length,
    view_counts: { all: results.length, high_priority: results.length, good_match: 0, reach: 0, starred: 0 },
    source_facets: [{ source: 'manual', count: 1 }], scope_available: false, ai_refined: false, matcher_version: 'action-fixture' };
}

test.afterEach(async ({ context }, info) => {
  if (info.status === info.expectedStatus) return;
  for (const [index, page] of context.pages().entries()) await attachProfileReadDiagnostics(page, info, `action-check-page-${index}`);
});

test.describe('Action-time profile checks without refresh events', () => {
  test('Detail opening reads silent cloud changes before either templates or AI see the profile', async ({ page }) => {
    const owner = await seed(page), writes = browserProfileWrites(page);
    const requests = await installWriting(page);
    let gate: Awaited<ReturnType<typeof holdNextProfileRead>> | undefined;
    try {
      await detailReady(page);
      const nextEntries = [entry('current', NEW_FACT)];
      await commit(owner, { name: NEW_NAME, experience_entries: nextEntries });
      expect((await currentLocalProfile(page)).name).toBe(OLD_NAME);
      gate = await holdNextProfileRead(page);
      await page.getByRole('button', { name: 'Draft email', exact: true }).click();
      await expect.poll(gate.started, 'opening must perform a fresh profile GET').toBe(true);
      expect(requests).toEqual([]);
      const loaded = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
      gate.release();
      expect(await (await loaded).json()).toMatchObject([{ revision: 2, profile_data: { name: NEW_NAME } }]);
      await expect(fields(page).body).toHaveValue(`Draft for ${NEW_NAME}\n${NEW_FACT}`);
      await expect.poll(() => requests.some(item => item.path.endsWith('/stream'))).toBe(true);
      assertLatest(requests, nextEntries);
      expect(writes).toEqual([]);
      await page.screenshot({ path: test.info().outputPath('checked-latest-profile-draft.png') });
    } finally { gate?.release(); await owner.http.dispose(); }
  });

  test('silent withdrawal cancels a typed refinement, keeps all manual input, and explicit regeneration uses the new evidence', async ({ page }) => {
    const owner = await seed(page), writes = browserProfileWrites(page);
    const requests = await installWriting(page);
    let gate: Awaited<ReturnType<typeof holdNextProfileRead>> | undefined;
    try {
      await detailReady(page);
      await page.getByRole('button', { name: 'Draft email', exact: true }).click();
      await expect(fields(page).body).toHaveValue(`Draft for ${OLD_NAME}\n${OLD_FACT}\n${KEPT_FACT}`);
      await expect.poll(() => requests.some(item => item.path.endsWith('/stream'))).toBe(true);
      const edit = fields(page);
      await edit.subject.fill(MANUAL_SUBJECT); await edit.body.fill(MANUAL_BODY);
      await edit.recipient.fill(MANUAL_RECIPIENT); await edit.instruction.fill(INSTRUCTION);
      const nextEntries: ExperienceEntry[] = [{ ...entry('earlier', OLD_FACT), revision: 2, status: 'withdrawn' }, entry('kept', KEPT_FACT)];
      await commit(owner, { name: NEW_NAME, experience_entries: nextEntries });
      expect((await currentLocalProfile(page)).experience_entries?.[0].status).toBe('confirmed');
      const initialCount = requests.length;
      gate = await holdNextProfileRead(page);
      await page.getByRole('button', { name: 'Submit request', exact: true }).click();
      await expect.poll(gate.started).toBe(true);
      expect(requests).toHaveLength(initialCount);
      gate.release();
      await expect(page.getByText(PROFILE_CHANGED, { exact: true })).toBeVisible();
      await expect(edit.subject).toHaveValue(MANUAL_SUBJECT); await expect(edit.body).toHaveValue(MANUAL_BODY);
      await expect(edit.recipient).toHaveValue(MANUAL_RECIPIENT); await expect(edit.instruction).toHaveValue(INSTRUCTION);
      expect(requests.filter(item => item.path.endsWith('/refine'))).toEqual([]);
      expect(requests).toHaveLength(initialCount);
      await page.screenshot({ path: test.info().outputPath('manual-draft-after-source-change.png') });
      gate = await holdNextProfileRead(page);
      await page.getByRole('button', { name: 'Regenerate from updated profile', exact: true }).click();
      await expect.poll(gate.started).toBe(true);
      expect(requests).toHaveLength(initialCount);
      gate.release();
      await expect(edit.body).toHaveValue(`Draft for ${NEW_NAME}\n${KEPT_FACT}`);
      await expect.poll(() => requests.slice(initialCount).some(item => item.path.endsWith('/stream'))).toBe(true);
      assertLatest(requests.slice(initialCount), nextEntries);
      expect(requests.filter(item => item.path.endsWith('/refine'))).toEqual([]);
      expect(writes).toEqual([]);
    } finally { gate?.release(); await owner.http.dispose(); }
  });

  for (const stillActionable of [true, false]) test(`Results waits for current-profile rematching before writing (${stillActionable ? 'same target confirmed' : 'target removed'})`, async ({ page }) => {
    const owner = await seed(page), writes = browserProfileWrites(page);
    const requests = await installWriting(page);
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    let updatedMatchStarted = false;
    await page.route('**/api/matches/view**', async route => {
      const body = route.request().postDataJSON();
      const updated = body.profile.name === NEW_NAME;
      if (updated) {
        expect(body.profile.research_interests_text).toBe('calibration');
        expect(body.profile.desired_fields).toEqual(['calibration']);
        updatedMatchStarted = true; await gate;
      }
      try { await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(matches(!updated || stillActionable, body.profile.name)) }); }
      catch (error) { if (!route.request().failure()) throw error; }
    });
    try {
      await page.goto('/results?tab=all');
      const opener = page.locator(`#match-card-${TARGET}`).getByRole('button', { name: 'Draft Email', exact: true });
      await expect(opener).toBeEnabled();
      await expect(page.getByTestId('profile-refresh-status')).toHaveCount(0);
      const nextEntries = [entry('current', NEW_FACT)];
      // Name/evidence alone do not change matching scores. Also change an
      // actual matching input so this case exercises the rematch boundary.
      await commit(owner, { name: NEW_NAME, experience_entries: nextEntries, research_interests: 'calibration' });
      expect((await currentLocalProfile(page)).name).toBe(OLD_NAME);
      const loaded = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
      await opener.click();
      expect(await (await loaded).json()).toMatchObject([{ revision: 2, profile_data: { name: NEW_NAME } }]);
      await expect.poll(() => updatedMatchStarted, 'the action check must reach Match before writing').toBe(true);
      expect(requests).toEqual([]);
      release();
      if (stillActionable) {
        await expect(fields(page).body).toHaveValue(`Draft for ${NEW_NAME}\n${NEW_FACT}`);
        await expect.poll(() => requests.some(item => item.path.endsWith('/stream'))).toBe(true);
        assertLatest(requests, nextEntries);
        await page.screenshot({ path: test.info().outputPath('checked-rematched-target-draft.png') });
      } else {
        await expect(page.getByText('No matches in this category.', { exact: true })).toBeVisible();
        await expect(page.getByRole('dialog').getByTestId('profile-refresh-status')).toContainText('This target is not confirmed in the current results. Your draft is kept; generation and outreach are paused.');
        expect(requests, 'the old card cannot authorize writing after the checked profile loses it').toEqual([]);
      }
      expect(writes).toEqual([]);
    } finally { release(); await owner.http.dispose(); }
  });
});
