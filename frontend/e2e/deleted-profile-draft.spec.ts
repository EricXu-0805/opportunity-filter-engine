import { test, expect, request as apiRequest, type APIRequestContext, type BrowserContext, type Locator, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { MatchResult, MatchesResponse, ProfileData, ResumeFact } from '../src/lib/types';
import { attachProfileReadDiagnostics } from './profile-read-diagnostics';

// Actual production UI + SDK + loopback profile reads/deletion. The standalone
// HTTP client represents another device. The stub is not hosted RLS evidence.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const TARGET = 'uiuc-siebel-ugresearch';
const NAME = 'Deleted profile student 王';
const LOCAL_NAME = 'My retained unsaved target résumé 王';
const SUBJECT = 'My retained manually written subject 王';
const BODY = 'Dear Professor,\n\nI compared readings; I assisted and did not lead the project.\n\nMy words must stay here 王';
const RECIPIENT = 'my-checked-address@example.edu';
const UNSENT = 'My unsent instruction must remain editable.';
const MISSING = 'Your profile is no longer available. Your draft is kept; generation and outreach are paused.';
const fact = (id: string, value: string): ResumeFact => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
const profileRead = (url: string) => new URL(url).pathname === '/rest/v1/profiles';
type Surface = 'Detail' | 'Results';
type Editor = 'email' | 'full résumé';
interface Owner { http: APIRequestContext; uid: string; token: string }
interface Draft { modal: Locator; assertKept(): Promise<void>; assertPaused(): Promise<void>; close(): Promise<void> }

function initialProfile(): ProfileData {
  return {
    name: NAME, institution: 'UIUC', college: 'Grainger College of Engineering', major: 'Computer Science',
    grade: 'Sophomore', is_international: false, research_interests: 'instrumentation',
    skills: [{ name: 'Python', level: 'beginner' }], coursework: ['ECE 220'], seeking_types: ['Research'],
    resume_text: 'Complete original source 王. I assisted and did not lead.',
    experience_entries: [{ id: 'deleted-profile-experience', revision: 1, status: 'confirmed', source: { kind: 'manual' },
      text: 'Compared instrument readings and documented uncertainty; I assisted and did not lead.' }],
    resume_master: {
      version: 1, id: 'deleted-profile-master', revision: 1, source_signature: null,
      basics: { name: fact('name', NAME), links: [] },
      education: [{ id: 'education', school: fact('school', 'Example University'), degree: fact('degree', 'Bachelor of Science'), details: [] }],
      activities: [{ id: 'project', kind: 'project', title: fact('project-title', 'Instrument project'),
        details: [{ id: 'deleted-profile-experience', revision: 1 }] }],
      publications: [], skills: [], other_sections: [],
      section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [],
    },
  };
}

async function seedOwner(page: Page): Promise<Owner> {
  expect(STUB.hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
    expect(signup.status()).toBe(200);
    const session = await signup.json();
    const owner = { http, uid: session.user.id as string, token: session.access_token as string };
    const value = initialProfile();
    const saved = await http.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
      headers: { Authorization: `Bearer ${owner.token}` },
      data: { p_expected_device_id: owner.uid, p_expected_revision: 0, p_patch: value },
    });
    expect(saved.status()).toBe(200);
    expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1, profile: value });
    await page.addInitScript(({ session, localeKey }) => {
      if (!localStorage.getItem('deleted-profile-seeded')) {
        localStorage.setItem('ofe_auth', JSON.stringify(session));
        localStorage.setItem(localeKey, 'en');
        localStorage.setItem('deleted-profile-seeded', '1');
      }
    }, { session, localeKey: STORAGE_KEYS.LOCALE });
    const read = page.waitForResponse(response => profileRead(response.url()) && response.status() === 200);
    await page.goto('/');
    expect(await (await read).json()).toMatchObject([{ revision: 1, profile_data: value }]);
    await page.locator('#resume-master').getByText('Open full résumé editor', { exact: true }).click();
    await expect(page.locator('#resume-master').getByRole('textbox', { name: 'Full name', exact: true })).toHaveValue(NAME);
    return owner;
  } catch (error) { await http.dispose(); throw error; }
}
function profileUrl(uid: string) {
  const url = new URL('/rest/v1/profiles', STUB);
  url.searchParams.set('id', `eq.${uid}`);
  return url;
}
async function assertAbsent(owner: Owner) {
  const response = await owner.http.get(profileUrl(owner.uid).href, { headers: { Authorization: `Bearer ${owner.token}` } });
  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual([]);
}
function mutations(context: BrowserContext) {
  const writes: string[] = [];
  context.on('request', request => {
    if (!['POST', 'PATCH', 'PUT', 'DELETE'].includes(request.method())) return;
    const path = new URL(request.url()).pathname;
    if (/\/profiles$|\/commit_profile_patch_cas$|\/commit_target_resume_cas$|\/confirm_interaction_contact$|\/interactions$/.test(path)) writes.push(`${request.method()} ${path}`);
  });
  return writes;
}
function matched(): MatchesResponse {
  const row: MatchResult = {
    opportunity_id: TARGET, eligibility_score: 90, readiness_score: 90, upside_score: 90, final_score: 90,
    bucket: 'high_priority', reasons_fit: ['Synthetic match for editor lifetime only.'], reasons_gap: [], next_steps: [],
    opportunity: {
      id: TARGET, title: 'Profile deletion test laboratory', organization: 'Example University', opportunity_type: 'research',
      source_type: 'campus_program', record_kind: 'listing', source: 'manual', school: 'uiuc', audience: 'campus', paid: 'yes',
      location: 'Campus', on_campus: true, source_url: 'https://example.edu/deletion-fixture',
      description_clean: 'Instrumentation research with undergraduate students.', keywords: ['instrumentation'], is_rolling: true,
      target_truth: { listing_state: 'open', reference_only: false, actionable: true, accepting_state: 'accepting', reason_code: null, verified_at: null, expires_at: null },
      eligibility: { international_friendly: 'yes', preferred_year: [], majors: [], skills_required: [], citizenship_required: false },
      application: { application_effort: 'medium', requires_resume: 'yes', contact_method: 'email' }, metadata: { is_active: true, confidence_score: 1 },
    },
  };
  return {
    total: 1, high_priority: 1, good_match: 0, reach: 0, low_fit: 0, results: [row], returned_count: 1,
    has_more: false, next_cursor: null, result_set_id: 'deleted-profile-set', view_id: 'deleted-profile-view',
    contract_version: 'match-view-v3-faculty-trust', target_truth_contract: 'target-truth-v2', view_start: 0, filtered_total: 1,
    view_counts: { all: 1, high_priority: 1, good_match: 0, reach: 0, starred: 0 },
    source_facets: [{ source: 'manual', count: 1 }], scope_available: false, ai_refined: false, matcher_version: 'deleted-profile-fixture',
  };
}
async function installNetwork(page: Page) {
  // Do not call any provider. Profile/auth/storage traffic is not intercepted.
  for (const pattern of ['**/api/cold-email**', '**/api/tailor**', '**/api/resume/**']) {
    await page.route(pattern, route => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  }
  await page.route('**/api/cold-email/variants', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
    variants: [{ id: 'deletion-template', label: 'Template', subject: 'Initial template subject', body: 'Initial template body.', recipient_email: 'initial@example.edu', mailto_link: '' }],
    recipient_status: 'revealed', pipeline_version: 'profile-deletion-fixture', corpus_version: 'profile-deletion-fixture',
  }) }));
  await page.route('**/api/matches/view**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(matched()) }));
}
async function openDraft(page: Page, surface: Surface, editor: Editor): Promise<Draft> {
  await page.goto(surface === 'Detail' ? `/opportunities/${TARGET}` : '/results?tab=all');
  const entry = surface === 'Detail' ? page : page.locator(`#match-card-${TARGET}`);
  const actionName = editor === 'email' ? (surface === 'Results' ? 'Draft Email' : 'Draft email') : 'Renovate Resume';
  await entry.getByRole('button', { name: actionName, exact: true }).click();
  if (editor === 'email') {
    const fields = page.getByTestId('cold-email-editor-fields');
    const modal = page.getByRole('dialog').filter({ has: fields });
    const subject = fields.locator('input[type="text"]'), body = fields.locator('textarea'), recipient = fields.locator('input[type="email"]');
    const instruction = page.getByRole('textbox', { name: 'Request an edit', exact: true });
    await expect(subject).toHaveValue('Initial template subject');
    await subject.fill(SUBJECT); await body.fill(BODY); await recipient.fill(RECIPIENT); await instruction.fill(UNSENT);
    return { modal,
      assertKept: async () => {
        await expect(subject).toHaveValue(SUBJECT); await expect(body).toHaveValue(BODY);
        await expect(recipient).toHaveValue(RECIPIENT); await expect(instruction).toHaveValue(UNSENT);
        await expect(subject).toBeEditable(); await expect(body).toBeEditable(); await expect(recipient).toBeEditable();
      },
      assertPaused: async () => {
        await expect(modal.getByRole('button', { name: 'Copy', exact: true })).toBeEnabled();
        await expect(modal.getByRole('button', { name: 'Submit request', exact: true })).toBeDisabled();
        await expect(modal.getByRole('button', { name: 'Open in Email', exact: true })).toBeDisabled();
      },
      close: async () => { await modal.getByRole('button', { name: 'Close email editor', exact: true }).click(); },
    };
  }
  const modal = page.getByRole('dialog', { name: 'Target résumé', exact: true });
  await modal.getByRole('button', { name: 'Create from confirmed master', exact: true }).click();
  const name = modal.getByRole('textbox', { name: 'Edit Full name', exact: true });
  const degree = modal.getByRole('checkbox', { name: 'Include field: Degree', exact: true });
  await name.fill(LOCAL_NAME); await degree.uncheck();
  return { modal,
    assertKept: async () => {
      await expect(name).toHaveValue(LOCAL_NAME); await expect(degree).not.toBeChecked(); await expect(name).toBeEditable();
      await expect(modal.getByText('Unsaved local edits', { exact: true })).toBeVisible();
    },
    assertPaused: async () => {
      await expect(modal.getByRole('button', { name: 'Rebuild from current confirmed master', exact: true })).toBeDisabled();
      await expect(modal.getByRole('button', { name: 'Generate AI suggestions', exact: true })).toBeDisabled();
      await expect(modal.getByRole('button', { name: 'Save target draft', exact: true })).toBeEnabled();
      // Saving this independent target draft is allowed; this scenario makes
      // no save click and never conflates that ability with restoring profile.
    },
    close: async () => {
      await modal.getByRole('button', { name: 'Close target résumé', exact: true }).click();
      await modal.getByRole('button', { name: 'Keep editing', exact: true }).click();
      await expect(name).toHaveValue(LOCAL_NAME);
      await modal.getByRole('button', { name: 'Close target résumé', exact: true }).click();
      await modal.getByRole('button', { name: 'Discard unsaved edits and continue', exact: true }).click();
    },
  };
}
async function deleteAndRefresh(page: Page, owner: Owner, draft: Draft) {
  const original = await draft.modal.elementHandle();
  expect(original).not.toBeNull();
  const other = await page.context().newPage();
  try {
    await other.goto('about:blank'); await other.bringToFront();
    await page.context().setOffline(true);
    await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
    const deleted = await owner.http.delete(profileUrl(owner.uid).href, { headers: { Authorization: `Bearer ${owner.token}` } });
    expect(deleted.status()).toBe(204);
    await assertAbsent(owner);
    const read = page.waitForResponse(response => profileRead(response.url()) && response.status() === 200);
    await page.bringToFront(); await page.context().setOffline(false);
    expect(await (await read).json()).toEqual([]);
    await expect(draft.modal.getByTestId('profile-refresh-status')).toContainText(MISSING);
    expect(await original!.evaluate(node => node.isConnected), 'profile deletion must not unmount the open editing buffer').toBe(true);
    await draft.assertKept(); await draft.assertPaused();
  } finally { await page.context().setOffline(false); await other.close(); }
}
async function verifyAbsentAfterExit(page: Page, surface: Surface, owner: Owner) {
  await expect(page.getByTestId('cold-email-editor-fields')).toHaveCount(0);
  await expect(page.getByRole('dialog', { name: 'Target résumé', exact: true })).toHaveCount(0);
  if (surface === 'Results') await expect(page).toHaveURL(/\/$/);
  else {
    await expect(page.getByRole('button', { name: 'Draft email', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Renovate Resume', exact: true })).toHaveCount(0);
  }
  // A fresh entry cannot use the closed session's held profile as a source.
  await page.goto(surface === 'Detail' ? `/opportunities/${TARGET}` : '/results?tab=all');
  if (surface === 'Results') await expect(page).toHaveURL(/\/$/);
  else {
    await expect(page.getByRole('button', { name: 'Draft email', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Renovate Resume', exact: true })).toHaveCount(0);
  }
  const read = page.waitForResponse(response => profileRead(response.url()) && response.status() === 200);
  await page.goto('/');
  expect(await (await read).json()).toEqual([]);
  await expect(page.locator('#student_name')).toHaveValue('');
  await expect(page.locator('#resume-master').getByRole('textbox', { name: 'Full name', exact: true })).toHaveCount(0);
  await expect(page.getByText(LOCAL_NAME, { exact: true })).toHaveCount(0);
  await expect(page.getByText(BODY, { exact: true })).toHaveCount(0);
  await assertAbsent(owner);
}
async function changeOwnerThroughAnotherTab(page: Page, owner: Owner): Promise<Owner> {
  const signup = await owner.http.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
  expect(signup.status()).toBe(200);
  const session = await signup.json();
  expect(session.user.id).not.toBe(owner.uid);
  const other = await page.context().newPage();
  try {
    await other.goto('/robots.txt');
    // Same cross-tab transport consumed by the real supabase-js client. The
    // replacement is a real loopback-issued session, not a React/owner stub.
    await other.evaluate((session) => {
      localStorage.setItem('ofe_auth', JSON.stringify(session));
      const channel = new BroadcastChannel('ofe_auth');
      channel.postMessage({ event: 'SIGNED_IN', session }); channel.close();
    }, session);
    await expect.poll(() => page.evaluate(key => localStorage.getItem(key), STORAGE_KEYS.LOCAL_IDENTITY_OWNER)).toContain(session.user.id);
  } finally { await other.close(); }
  return { http: owner.http, uid: session.user.id, token: session.access_token };
}

test.afterEach(async ({ context }, info) => {
  if (info.status === info.expectedStatus) return;
  for (const [index, page] of context.pages().entries()) await attachProfileReadDiagnostics(page, info, `deleted-profile-page-${index}`);
});

test.describe('Open writing drafts after profile deletion', () => {
  for (const surface of ['Detail', 'Results'] as const) for (const editor of ['email', 'full résumé'] as const) {
    test(`${surface} keeps the open ${editor}, then drops its held profile on deliberate exit`, async ({ page, context }) => {
      const owner = await seedOwner(page);
      const writes = mutations(context);
      try {
        await installNetwork(page);
        const draft = await openDraft(page, surface, editor);
        await deleteAndRefresh(page, owner, draft);
        if (surface === 'Detail') await page.screenshot({ path: test.info().outputPath(`retained-${editor === 'email' ? 'email' : 'resume'}.png`) });
        expect(writes, 'a refresh must not recreate profile or silently save/contact anything').toEqual([]);
        await draft.close();
        await verifyAbsentAfterExit(page, surface, owner);
        expect(writes, 'exit and fresh entry must never recreate the deleted profile').toEqual([]);
      } finally { await owner.http.dispose(); }
    });
  }
  for (const [surface, editor] of [['Detail', 'email'], ['Results', 'full résumé']] as const) {
    test(`${surface} retires the retained ${editor} immediately when a different owner arrives`, async ({ page, context }) => {
      const owner = await seedOwner(page);
      const writes = mutations(context);
      try {
        await installNetwork(page);
        const draft = await openDraft(page, surface, editor);
        await deleteAndRefresh(page, owner, draft);
        const replacement = await changeOwnerThroughAnotherTab(page, owner);
        await expect(draft.modal).toHaveCount(0);
        await expect(page.getByTestId('cold-email-editor-fields')).toHaveCount(0);
        await expect(page.getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveCount(0);
        await expect(page.getByText(BODY, { exact: true })).toHaveCount(0);
        await expect(page.getByText(LOCAL_NAME, { exact: true })).toHaveCount(0);
        await assertAbsent(owner); await assertAbsent(replacement);
        expect(writes, 'U1 drafts must not become U2 profile/target/contact writes').toEqual([]);
      } finally { await owner.http.dispose(); }
    });
  }
});
