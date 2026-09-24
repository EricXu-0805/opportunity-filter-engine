import { test, expect, request as apiRequest, type APIRequestContext, type BrowserContext, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { MatchResult, MatchesResponse, ProfileData, ResumeFact } from '../src/lib/types';

// Only the independent API client changes cloud data after setup. No profile
// localStorage writes, synthetic DOM events, or second Home saves. The real
// browser reconnect event triggers refresh; window focus is unit-covered only.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const TARGET = 'uiuc-siebel-ugresearch';
const NAME = 'Cloud refresh student 王';
const LOCAL_NAME = 'My unsaved target name 王';
const SUBJECT = 'My manually edited subject 王';
const BODY = 'Dear Professor,\n\nI reviewed the experiment notes; I did not lead the project.\n\nCloud refresh student 王';
const RECIPIENT = 'my-reviewed-recipient@example.edu';
const UNSENT = 'Keep this unsent editing request exactly as typed.';
const PROFILE_CHANGED = 'Your profile or target details changed. Your subject, message and recipient are kept. Regenerate when you are ready to replace this draft.';
const READ_FAILED = 'Could not check for profile updates. Your draft is kept.';
const fact = (id: string, value: string): ResumeFact => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
const dialog = (page: Page) => page.getByRole('dialog', { name: 'Target résumé', exact: true });
const isProfileRead = (url: string) => new URL(url).pathname === '/rest/v1/profiles';

function initialProfile(): ProfileData {
  return {
    name: NAME, institution: 'UIUC', college: 'Grainger College of Engineering', major: 'Computer Science',
    grade: 'Sophomore', is_international: false, research_interests: 'instrumentation', skills: [], coursework: [],
    seeking_types: ['Research'], resume_text: 'Original complete source 王',
    experience_entries: [{ id: 'cloud-experience', revision: 1, status: 'confirmed', source: { kind: 'manual' },
      text: 'Compared instrument readings; I assisted and did not lead the project.' }],
    resume_master: {
      version: 1, id: 'cloud-master', revision: 1, source_signature: null,
      basics: { name: fact('cloud-name', NAME), links: [] },
      education: [{ id: 'education', school: fact('school', 'Example University'), degree: fact('degree', 'Bachelor of Science'), details: [] }],
      activities: [{ id: 'project-one', kind: 'project', title: fact('title', 'Instrument project'), details: [{ id: 'cloud-experience', revision: 1 }] }],
      publications: [], skills: [], other_sections: [],
      section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [],
    },
  };
}
interface CloudOwner { http: APIRequestContext; uid: string; token: string; revision: number }
async function updateCloud(owner: CloudOwner, patch: Partial<ProfileData>) {
  const response = await owner.http.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
    headers: { Authorization: `Bearer ${owner.token}` },
    data: { p_expected_device_id: owner.uid, p_expected_revision: owner.revision, p_patch: patch },
  });
  expect(response.status()).toBe(200);
  const receipt = await response.json();
  expect(receipt).toMatchObject({ status: 'applied', revision: owner.revision + 1, profile: patch });
  owner.revision = receipt.revision;
}
function expectCloudRow(data: unknown, revision: number) {
  expect(Array.isArray(data) ? data[0] : data).toMatchObject({ revision, profile_data: { name: NAME } });
}
async function seedOwner(page: Page): Promise<CloudOwner> {
  expect(STUB.hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
    expect(signup.status()).toBe(200);
    const session = await signup.json();
    expect(session.user.id).toBeTruthy();
    const owner = { http, uid: session.user.id as string, token: session.access_token as string, revision: 0 };
    await updateCloud(owner, initialProfile());
    await page.addInitScript(({ session, localeKey }) => {
      // Session bootstrap only; the profile is always obtained by a real GET.
      if (!localStorage.getItem('cloud-profile-refresh-seeded')) {
        localStorage.setItem('ofe_auth', JSON.stringify(session));
        localStorage.setItem(localeKey, 'en');
        localStorage.setItem('cloud-profile-refresh-seeded', '1');
      }
    }, { session, localeKey: STORAGE_KEYS.LOCALE });
    const read = page.waitForResponse(response => isProfileRead(response.url()) && response.status() === 200);
    await page.goto('/');
    expectCloudRow(await (await read).json(), 1);
    await page.locator('#resume-master').getByText('Open full résumé editor', { exact: true }).click();
    await expect(page.locator('#resume-master').getByRole('textbox', { name: 'Full name', exact: true })).toHaveValue(NAME);
    return owner;
  } catch (error) { await http.dispose(); throw error; }
}
function logBrowserWrites(context: BrowserContext) {
  const writes: string[] = [];
  context.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (request.method() === 'POST' && /commit_profile_patch_cas|commit_target_resume_cas|confirm_interaction_contact|\/interactions$/.test(path)) writes.push(path);
  });
  return writes;
}
async function background(page: Page) {
  const other = await page.context().newPage();
  await other.goto('about:blank'); await other.bringToFront();
  // Playwright keeps each regular Chromium test context focused. A real
  // offline -> online transition is testable without synthesized DOM events.
  await page.context().setOffline(true);
  await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
  return other;
}
async function resumeAndRead(page: Page, revision: number) {
  const read = page.waitForResponse(response => isProfileRead(response.url()) && response.status() === 200);
  await page.bringToFront();
  await page.context().setOffline(false);
  await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(true);
  expectCloudRow(await (await read).json(), revision);
}
async function blockPaidWriting(page: Page) {
  for (const pattern of ['**/api/cold-email**', '**/api/tailor**', '**/api/resume/**']) {
    await page.route(pattern, route => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  }
}
async function createLocalTarget(page: Page) {
  await dialog(page).getByRole('button', { name: 'Create from confirmed master', exact: true }).click();
  const name = dialog(page).getByRole('textbox', { name: 'Edit Full name', exact: true });
  const degree = dialog(page).getByRole('checkbox', { name: 'Include field: Degree', exact: true });
  await name.fill(LOCAL_NAME); await degree.uncheck();
  return { name, degree };
}
function resultRow(): MatchResult {
  return {
    opportunity_id: TARGET, eligibility_score: 90, readiness_score: 90, upside_score: 90, final_score: 90,
    bucket: 'high_priority', reasons_fit: ['Synthetic match for editor lifetime only.'], reasons_gap: [], next_steps: [],
    opportunity: {
      id: TARGET, title: 'Cloud refresh test laboratory', organization: 'Example University', opportunity_type: 'research',
      source_type: 'campus_program', record_kind: 'listing', source: 'manual', school: 'uiuc', audience: 'campus', paid: 'yes',
      location: 'Campus', on_campus: true, source_url: 'https://example.edu/cloud-fixture',
      description_clean: 'Instrumentation research with undergraduate students.', keywords: ['instrumentation'], is_rolling: true,
      target_truth: { listing_state: 'open', reference_only: false, actionable: true, accepting_state: 'accepting', reason_code: null, verified_at: null, expires_at: null },
      eligibility: { international_friendly: 'yes', preferred_year: [], majors: [], skills_required: [], citizenship_required: false },
      application: { application_effort: 'medium', requires_resume: 'yes', contact_method: 'email' }, metadata: { is_active: true, confidence_score: 1 },
    },
  };
}
function matches(rows: MatchResult[], revision: number): MatchesResponse {
  return {
    total: 1, high_priority: 1, good_match: 0, reach: 0, low_fit: 0, results: rows, returned_count: rows.length,
    has_more: false, next_cursor: null, result_set_id: `cloud-set-${revision}`, view_id: `cloud-view-${revision}`,
    contract_version: 'match-view-v3-faculty-trust', target_truth_contract: 'target-truth-v2', view_start: 0, filtered_total: rows.length,
    view_counts: { all: rows.length, high_priority: rows.length, good_match: 0, reach: 0, starred: 0 },
    source_facets: [{ source: 'manual', count: 1 }], scope_available: false, ai_refined: false, matcher_version: 'cloud-fixture',
  };
}

test.describe('Server-only profile refresh', () => {
  test('Results keeps the same unsaved full résumé through cloud refresh, re-matching and removal of its card', async ({ page, context }) => {
    const owner = await seedOwner(page);
    const writes = logBrowserWrites(context);
    let other: Page | null = null, release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const requests: Array<{ profile: { coursework?: string[]; hard_skills?: Array<{ name: string }> } }> = [];
    let updatedRequestStarted = false;
    await blockPaidWriting(page);
    await page.route('**/api/matches/view**', async route => {
      const body = route.request().postDataJSON(); requests.push(body);
      const updated = body.profile.coursework?.includes('CS 374');
      if (updated) { updatedRequestStarted = true; await gate; }
      try { await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(matches(updated ? [] : [resultRow()], updated ? 2 : 1)) }); }
      catch (error) { if (!route.request().failure()) throw error; }
    });
    try {
      await page.goto('/results?tab=all');
      await page.locator(`#match-card-${TARGET}`).getByRole('button', { name: 'Renovate Resume', exact: true }).click();
      const fields = await createLocalTarget(page);
      const close = dialog(page).getByRole('button', { name: 'Close target résumé', exact: true });
      await close.focus(); await page.keyboard.press('/'); await expect(close).toBeFocused();
      await page.keyboard.press('Escape');
      await dialog(page).getByRole('button', { name: 'Keep editing', exact: true }).click();
      await expect(fields.name).toHaveValue(LOCAL_NAME);
      const originalDialog = await dialog(page).elementHandle();
      expect(originalDialog).not.toBeNull();
      other = await background(page);
      await updateCloud(owner, { coursework: ['CS 374'], skills: [{ name: 'Python', level: 'experienced', confirmed: true }] });
      await resumeAndRead(page, 2);
      await expect.poll(() => updatedRequestStarted, 'new server material must reach the Match request').toBe(true);
      expect(requests.at(-1)?.profile).toMatchObject({ coursework: ['CS 374'], hard_skills: [{ name: 'Python' }] });
      await expect(fields.name).toHaveValue(LOCAL_NAME); await expect(fields.degree).not.toBeChecked();
      expect(await originalDialog!.evaluate(node => node.isConnected), 'rematch loading must not remount the editor').toBe(true);
      const rematched = page.waitForResponse(response => new URL(response.url()).pathname === '/api/matches/view'
        && response.request().postDataJSON()?.profile?.coursework?.includes('CS 374') && response.status() === 200);
      release();
      expect(await (await rematched).json()).toMatchObject({ result_set_id: 'cloud-set-2', results: [] });
      await expect(page.getByText('No matches in this category.', { exact: true })).toBeVisible();
      await expect(page.locator(`#match-card-${TARGET}`)).toHaveCount(0);
      await expect(dialog(page)).toBeVisible();
      expect(await originalDialog!.evaluate(node => node.isConnected), 'a missing result card must not destroy local work').toBe(true);
      await expect(fields.name).toHaveValue(LOCAL_NAME); await expect(fields.degree).not.toBeChecked();
      await expect(dialog(page).getByText('Unsaved local edits', { exact: true })).toBeVisible();
      await expect(dialog(page).getByTestId('profile-refresh-status')).toContainText('This target is not confirmed in the current results. Your draft is kept; generation and outreach are paused.');
      expect(writes).toEqual([]);
      await page.screenshot({ path: test.info().outputPath('results-target-draft-preserved.png') });
      await test.info().attach('server-revision-and-match-profile', { body: JSON.stringify({ revision: owner.revision, profiles: requests.map(item => item.profile) }), contentType: 'application/json' });
    } finally { release(); await other?.close(); await owner.http.dispose(); }
  });

  test('Detail email preserves manual fields and unsent input and rejects a refinement from before the cloud refresh', async ({ page, context }) => {
    const owner = await seedOwner(page);
    const writes = logBrowserWrites(context);
    let other: Page | null = null, release!: () => void, settle!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const settled = new Promise<void>(resolve => { settle = resolve; });
    let variants = 0, refinements = 0;
    await blockPaidWriting(page);
    await page.route('**/api/cold-email/variants', route => {
      variants += 1;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        variants: [{ id: 'cloud-template', label: 'Template', subject: 'Initial template subject', body: 'Initial template body.', recipient_email: 'initial@example.edu', mailto_link: '' }],
        recipient_status: 'revealed', pipeline_version: 'cloud-refresh-fixture', corpus_version: 'cloud-refresh-fixture',
      }) });
    });
    await page.route('**/api/cold-email/refine', async route => {
      refinements += 1; expect(route.request().postDataJSON().current_body).toBe(BODY);
      await gate;
      try { await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ body: 'LATE PRE-REFRESH AI RESULT', method: 'llm' }) }); }
      catch (error) { if (!route.request().failure()) throw error; }
      finally { settle(); }
    });
    try {
      await page.goto(`/opportunities/${TARGET}`);
      await page.getByRole('button', { name: 'Draft email', exact: true }).click();
      const fields = page.getByTestId('cold-email-editor-fields');
      const subject = fields.locator('input[type="text"]'), body = fields.locator('textarea'), recipient = fields.locator('input[type="email"]');
      await expect(subject).toHaveValue('Initial template subject');
      await subject.fill(SUBJECT); await body.fill(BODY); await recipient.fill(RECIPIENT);
      const instruction = page.getByRole('textbox', { name: 'Request an edit', exact: true });
      await instruction.fill('Improve flow without changing facts.');
      await page.getByRole('button', { name: 'Submit request', exact: true }).click();
      await expect.poll(() => refinements).toBe(1);
      await instruction.fill(UNSENT);
      other = await background(page);
      await updateCloud(owner, { coursework: ['CS 374'] });
      await resumeAndRead(page, 2);
      await expect(page.getByText(PROFILE_CHANGED, { exact: true })).toBeVisible();
      await expect(subject).toHaveValue(SUBJECT); await expect(body).toHaveValue(BODY);
      await expect(recipient).toHaveValue(RECIPIENT); await expect(instruction).toHaveValue(UNSENT);
      await expect(page.getByRole('button', { name: 'Submit request', exact: true })).toBeDisabled();
      expect(variants, 'reading the new profile is not permission to replace a draft').toBe(1);
      release(); await settled;
      await expect(body).toHaveValue(BODY); await expect(subject).toHaveValue(SUBJECT);
      await expect(recipient).toHaveValue(RECIPIENT); await expect(instruction).toHaveValue(UNSENT);
      await expect(page.getByText('LATE PRE-REFRESH AI RESULT', { exact: true })).toHaveCount(0);
      await expect(page.getByText('Your profile or target is being checked, so this edit was discarded. Your draft is kept.', { exact: true })).toBeVisible();
      expect(writes).toEqual([]);
    } finally { release(); await other?.close(); await owner.http.dispose(); }
  });

  test('a failed cloud check keeps the complete local target draft and a visible Retry accepts the later server version', async ({ page, context }) => {
    const owner = await seedOwner(page);
    const writes = logBrowserWrites(context);
    let other: Page | null = null, failReads = false, failedReads = 0;
    await blockPaidWriting(page);
    await page.route('**/rest/v1/profiles?**', async route => {
      if (failReads) { failedReads += 1; await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: 'Synthetic read unavailable', code: 'E2E_OFFLINE' }) }); }
      else await route.continue();
    });
    try {
      await page.goto(`/opportunities/${TARGET}`);
      await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
      const fields = await createLocalTarget(page);
      other = await background(page);
      await updateCloud(owner, { coursework: ['CS 374'] });
      failReads = true;
      await page.bringToFront();
      await context.setOffline(false);
      await expect.poll(() => failedReads).toBeGreaterThan(0);
      // The SDK retries 503 reads. The hook must surface failure by its 15s deadline.
      await expect(dialog(page).getByText(READ_FAILED, { exact: true })).toBeVisible({ timeout: 18_000 });
      await expect(fields.name).toHaveValue(LOCAL_NAME); await expect(fields.degree).not.toBeChecked();
      await expect(dialog(page).getByText('Unsaved local edits', { exact: true })).toBeVisible();
      failReads = false;
      const read = page.waitForResponse(response => isProfileRead(response.url()) && response.status() === 200);
      await dialog(page).getByTestId('profile-refresh-status').getByRole('button', { name: 'Retry', exact: true }).click();
      expectCloudRow(await (await read).json(), 2);
      await expect(dialog(page).getByText(READ_FAILED, { exact: true })).toHaveCount(0);
      await expect(fields.name).toHaveValue(LOCAL_NAME); await expect(fields.degree).not.toBeChecked();
      await expect(dialog(page).getByText('This draft was created from different profile or target materials. Your edits and original source remain intact; they were not rebound to the current profile.', { exact: true })).toBeVisible();
      expect(writes).toEqual([]);
      await page.screenshot({ path: test.info().outputPath('profile-retry-draft-preserved.png') });
    } finally { await other?.close(); await owner.http.dispose(); }
  });
});
