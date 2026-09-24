import { test, expect, type APIRequestContext, type BrowserContext, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { ProfileData, ResumeFact } from '../src/lib/types';

// Real production UI, SDK, owner/storage coordination and loopback profile CAS.
// These are same-browser/same-account cases, not cross-device refresh coverage.
// The gated second-tab read guards the reported user journey; it does not assert
// that the historical CI flake had one uniquely proved auth-event ordering.
const TARGET = 'uiuc-siebel-ugresearch';
const PROFILE_URL = '**/rest/v1/profiles?**';
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const NAME = 'Baseline Student 王';
const TARGET_EDIT = 'My unchanged local target draft 王';
const SUBJECT = 'My manually edited subject 王';
const BODY = 'Dear Professor,\n\nThese are my own careful words. I assisted; I did not lead.\n\nBaseline Student 王';
const CHAT = 'An unsent instruction that must stay in the editor.';
const RECIPIENT = 'manually-checked@example.edu';
const PROFILE_CHANGED = 'Your profile changed. Your subject, message and recipient are kept. Regenerate when you are ready to replace this draft.';
const fact = (id: string, value: string): ResumeFact => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
const targetDialog = (page: Page) => page.getByRole('dialog', { name: 'Target résumé', exact: true });

function profile(): ProfileData {
  return {
    name: NAME, institution: 'UIUC', college: 'Grainger College of Engineering', major: 'Computer Science',
    grade: 'Sophomore', is_international: false, research_interests: 'instrumentation', skills: [], coursework: [],
    seeking_types: ['Research'], resume_text: 'Original complete source 王',
    experience_entries: [{ id: 'experience-one', revision: 1, status: 'confirmed', source: { kind: 'manual' },
      text: 'Compared instrument readings; I assisted and did not lead the project.' }],
    resume_master: {
      version: 1, id: 'freshness-master', revision: 1, source_signature: null,
      basics: { name: fact('name', NAME), links: [] },
      education: [{ id: 'education', school: fact('school', 'Example University'), degree: fact('degree', 'Bachelor of Science'), details: [] }],
      activities: [{ id: 'project-one', kind: 'project', title: fact('project-title', 'Instrument project'), details: [{ id: 'experience-one', revision: 1 }] }],
      publications: [], skills: [], other_sections: [],
      section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [],
    },
  };
}

async function establishCloudProfile(page: Page, request: APIRequestContext) {
  // Never infer an external endpoint from browser state or environment secrets.
  expect(STUB.hostname).toBe('127.0.0.1');
  const signup = await request.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
  expect(signup.status()).toBe(200);
  const session = await signup.json();
  expect(session.user.id).toBeTruthy();
  const value = profile();
  const saved = await request.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
    headers: { Authorization: `Bearer ${session.access_token}` },
    data: { p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: value },
  });
  expect(saved.status()).toBe(200);
  expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1, profile: value });
  await page.addInitScript(({ session, localeKey }) => {
    if (!localStorage.getItem('profile-freshness-seeded')) {
      localStorage.setItem('ofe_auth', JSON.stringify(session));
      localStorage.setItem(localeKey, 'en');
      localStorage.setItem('profile-freshness-seeded', '1');
    }
  }, { session, localeKey: STORAGE_KEYS.LOCALE });
  const read = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/profiles');
  await page.goto('/');
  expect((await read).status()).toBe(200);
  await openMaster(page);
  await expect(page.locator('#resume-master').getByRole('textbox', { name: 'Full name', exact: true })).toHaveValue(NAME);
  return value;
}

async function openMaster(page: Page) {
  const card = page.locator('#resume-master');
  await card.getByText('Open full résumé editor', { exact: true }).click();
  await expect(card.getByRole('textbox', { name: 'Full name', exact: true })).toBeEnabled();
  return card;
}

function mutationLog(context: BrowserContext) {
  const profileWrites: unknown[] = [], targetWrites: unknown[] = [], contactWrites: string[] = [];
  context.on('request', request => {
    if (request.method() !== 'POST') return;
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/commit_profile_patch_cas')) profileWrites.push(request.postDataJSON());
    if (path.endsWith('/commit_target_resume_cas')) targetWrites.push(request.postDataJSON());
    if (/\/confirm_interaction_contact$|\/interactions$/.test(path)) contactWrites.push(path);
  });
  return { profileWrites, targetWrites, contactWrites };
}

test.describe('Profile readiness and same-account writing preservation', () => {
  test('a second Home tab completes its real profile read without losing the first tab target edits', async ({ page, context, request }) => {
    const value = await establishCloudProfile(page, request);
    const writes = mutationLog(context);
    await page.goto(`/opportunities/${TARGET}`);
    await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
    await targetDialog(page).getByRole('button', { name: 'Create from confirmed master', exact: true }).click();
    const name = targetDialog(page).getByRole('textbox', { name: 'Edit Full name', exact: true });
    await name.fill(TARGET_EDIT);
    const includeDegree = targetDialog(page).getByRole('checkbox', { name: 'Include field: Degree', exact: true });
    await includeDegree.uncheck();
    const other = await context.newPage();
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    let reads = 0;
    await other.route(PROFILE_URL, async route => {
      const response = await route.fetch({ maxRetries: 0 });
      expect(response.status()).toBe(200);
      const data = await response.json();
      const row = Array.isArray(data) ? data[0] : data;
      expect(row).toMatchObject({ revision: 1, profile_data: value });
      reads += 1;
      await gate;
      try { await route.fulfill({ response }); }
      catch (error) { if (!route.request().failure()) throw error; }
    });
    try {
      await other.goto('/');
      await expect.poll(() => reads, 'second-tab profile GET must be issued, not spin before the network').toBeGreaterThan(0);
      await expect(other.locator('#resume-master')).toContainText('Loading your profile. Editing is unavailable until it is ready.');
      await expect(other.getByTestId('resume-master-editor')).toHaveCount(0);
      await expect(other.locator('input[type="file"]')).toHaveCount(0);
      await expect(name).toHaveValue(TARGET_EDIT);
      release();
      const master = await openMaster(other);
      await expect(master.getByRole('textbox', { name: 'Full name', exact: true })).toHaveValue(NAME);
      await expect(master).not.toContainText('Loading your profile.');
      await page.bringToFront();
      await expect(targetDialog(page)).toBeVisible();
      await expect(name).toHaveValue(TARGET_EDIT);
      await expect(includeDegree).not.toBeChecked();
      await expect(targetDialog(page).getByText('Unsaved local edits', { exact: true })).toBeVisible();
      await expect(targetDialog(page)).not.toContainText('This draft was created from different profile or target materials.');
      expect(writes.profileWrites).toEqual([]); expect(writes.targetWrites).toEqual([]); expect(writes.contactWrites).toEqual([]);
      await test.info().attach('profile-read-count', { body: JSON.stringify({ reads }), contentType: 'application/json' });
      await page.screenshot({ path: test.info().outputPath('target-edits-preserved.png') });
    } finally { release(); await other.close(); }
  });

  test('a real same-account profile save preserves the email subject, body, recipient and unsent instruction and retires an old refinement', async ({ page, context, request }) => {
    await establishCloudProfile(page, request);
    const writes = mutationLog(context);
    let variants = 0, refinements = 0;
    await page.route('**/api/cold-email**', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
    await page.route('**/api/cold-email/variants', route => {
      variants += 1;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        variants: [{ id: 'preservation-template', label: 'Template', subject: 'Original template subject',
          body: 'Original complete template body.', recipient_email: 'initial@example.edu', mailto_link: 'mailto:initial@example.edu' }],
        recipient_status: 'revealed', lab_type: null, pipeline_version: 'e2e-profile-preservation', corpus_version: 'e2e-profile-preservation',
      }) });
    });
    let release!: () => void, settle!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const settled = new Promise<void>(resolve => { settle = resolve; });
    await page.route('**/api/cold-email/refine', async route => {
      refinements += 1;
      expect(route.request().postDataJSON().current_body).toBe(BODY);
      await gate;
      try { await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ body: 'LATE OLD PROFILE REFINEMENT MUST NOT REPLACE MY WORDS', method: 'llm' }) }); }
      catch (error) { if (!route.request().failure()) throw error; }
      finally { settle(); }
    });
    let other: Page | null = null;
    try {
      await page.goto(`/opportunities/${TARGET}`);
      await page.getByRole('button', { name: 'Draft email', exact: true }).click();
      const editor = page.getByTestId('cold-email-editor-fields');
      const subject = editor.locator('input[type="text"]');
      const body = editor.locator('textarea');
      const recipient = editor.locator('input[type="email"]');
      await expect(subject).toHaveValue('Original template subject');
      await subject.fill(SUBJECT); await body.fill(BODY); await recipient.fill(RECIPIENT);
      const instruction = page.getByRole('textbox', { name: 'Request an edit', exact: true });
      await instruction.fill('Keep my facts and improve the transition.');
      await page.getByRole('button', { name: 'Submit request', exact: true }).click();
      await expect.poll(() => refinements).toBe(1);
      await instruction.fill(CHAT);
      other = await context.newPage();
      await other.goto('/');
      const master = await openMaster(other);
      await master.getByRole('textbox', { name: 'Full name', exact: true }).fill('Updated confirmed master name 王');
      await master.getByRole('button', { name: 'Confirm Full name', exact: true }).click();
      const receipt = other.waitForResponse(response => response.url().includes('/rest/v1/rpc/commit_profile_patch_cas')
        && response.request().postDataJSON()?.p_patch?.resume_master?.basics?.name?.value === 'Updated confirmed master name 王');
      await master.getByRole('button', { name: 'Apply changes', exact: true }).click();
      expect(await (await receipt).json()).toMatchObject({ status: 'applied', revision: 2,
        profile: { resume_master: { basics: { name: { value: 'Updated confirmed master name 王', status: 'confirmed' } } } } });
      await page.bringToFront();
      await expect(page.getByText(PROFILE_CHANGED, { exact: true })).toBeVisible();
      await expect(subject).toHaveValue(SUBJECT); await expect(body).toHaveValue(BODY);
      await expect(recipient).toHaveValue(RECIPIENT); await expect(instruction).toHaveValue(CHAT);
      await expect(page.getByRole('button', { name: 'Regenerate from updated profile', exact: true })).toBeEnabled();
      await expect(page.getByRole('button', { name: 'Submit request', exact: true })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Copy', exact: true })).toBeEnabled();
      expect(variants, 'a profile update must not silently regenerate over manual text').toBe(1);
      release(); await settled;
      await expect(subject).toHaveValue(SUBJECT); await expect(body).toHaveValue(BODY);
      await expect(recipient).toHaveValue(RECIPIENT); await expect(instruction).toHaveValue(CHAT);
      await expect(page.getByText('LATE OLD PROFILE REFINEMENT MUST NOT REPLACE MY WORDS', { exact: true })).toHaveCount(0);
      expect(writes.profileWrites).toHaveLength(1); expect(writes.targetWrites).toEqual([]); expect(writes.contactWrites).toEqual([]);
      await instruction.scrollIntoViewIfNeeded();
      const inputRect = await instruction.boundingBox();
      const footerRect = await page.getByTestId('cold-email-footer').boundingBox();
      expect(inputRect).not.toBeNull(); expect(footerRect).not.toBeNull();
      expect(inputRect!.y + inputRect!.height).toBeLessThanOrEqual(footerRect!.y);
      await expect(page.getByText('Your profile changed, so this edit was discarded. Your draft is kept.', { exact: true })).toBeVisible();
      await page.screenshot({ path: test.info().outputPath('email-edits-preserved.png') });
    } finally { release(); await other?.close(); }
  });
});
