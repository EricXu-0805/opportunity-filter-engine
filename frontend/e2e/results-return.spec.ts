import { contactReceiptForRequest } from './email-contact-receipt';
import { test, expect, request as apiRequest, type APIRequestContext, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';
import type { MatchResult, MatchesResponse, ProfileData } from '../src/lib/types';
import type { MatchViewRequestState } from '../src/lib/api';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { en } from '../src/i18n/dictionaries';

/** M26 browser contract. Only HTTP/auth browser boundaries are replaced.
 * The real Results page, cache/owner/session primitives, Next navigation,
 * detail SSR and modals run unchanged. The one detail target is an existing
 * backend seed: no synthetic RSC or fabricated detail-page HTML is served.
 */
const TARGET = 'uiuc-siebel-ugresearch';
const OWNER_A = '11111111-1111-4111-8111-111111111111';
const OWNER_B = '22222222-2222-4222-8222-222222222222';
const PROFILE = {
  name: 'Return Test Student', institution: 'UIUC',
  college: 'Grainger College of Engineering', major: 'Computer Science',
  grade: 'Sophomore', is_international: false, research_interests: 'machine learning',
  // Preserve legacy string skills: this is a supported pre-CAS profile.
  skills: ['Python'], coursework: ['CS 225'], seeking_types: ['research'],
};
const PUBLIC_FILTERS = { tab: 'all', q: 'Return fixture', paid: 'yes', sort: 'newest' };
const RESET_NOTICE = 'Your previous results are no longer available. Showing the first page.';
const card = (page: Page) => page.locator(`#match-card-${TARGET}`);
const title = (page: Page) => card(page).locator('h3 a');

function authSession(uid: string) {
  const now = Math.floor(Date.now() / 1000);
  const encode = (data: unknown) => Buffer.from(JSON.stringify(data)).toString('base64url');
  return {
    access_token: `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode({ sub: uid, aud: 'authenticated', role: 'authenticated', iat: now, exp: now + 3600, is_anonymous: true })}.e2e-only`,
    refresh_token: `return-test-${uid}`, token_type: 'bearer', expires_in: 3600,
    expires_at: now + 3600,
    user: {
      id: uid, aud: 'authenticated', role: 'authenticated', is_anonymous: true,
      app_metadata: { provider: 'anonymous', providers: ['anonymous'] },
      user_metadata: {}, identities: [], created_at: '2026-01-01T00:00:00Z',
    },
  };
}

function match(index: number, paid: 'yes' | 'no'): MatchResult {
  const id = index === 54 ? TARGET : `return-fixture-${index}`;
  return {
    opportunity_id: id, eligibility_score: 90, readiness_score: 90, upside_score: 90,
    final_score: 90, bucket: 'high_priority', reasons_fit: ['A fixture for navigation only.'],
    reasons_gap: [], next_steps: [],
    opportunity: {
      id, title: `Return fixture ${String(index + 1).padStart(2, '0')}`,
      organization: 'Navigation Test University', opportunity_type: 'research',
      source_type: 'campus_program', record_kind: 'listing', source: 'manual',
      school: 'uiuc', audience: 'campus', paid, location: 'Campus', on_campus: true,
      source_url: 'https://example.edu/navigation-fixture',
      description_clean: 'Synthetic result used only to check return navigation and position.',
      keywords: ['machine learning'], is_rolling: true,
      posted_date: new Date(Date.UTC(2026, 8, 24) - index * 86_400_000).toISOString(),
      target_truth: {
        listing_state: 'open', reference_only: false, actionable: true,
        accepting_state: 'accepting', reason_code: null, verified_at: null, expires_at: null,
      },
      eligibility: { international_friendly: 'yes', preferred_year: [], majors: [], skills_required: ['Python'], citizenship_required: false },
      application: { application_effort: 'medium', requires_resume: 'yes', contact_method: 'email' },
      metadata: { is_active: true, confidence_score: 1 },
    },
  };
}
const CORPUS = Array.from({ length: 70 }, (_, index) => match(index, index < 58 ? 'yes' : 'no'));
interface ViewRequest { profile: Record<string, unknown>; view: MatchViewRequestState; page_size: number; cursor: string | null }
interface Network {
  requests: ViewRequest[];
  writes: string[];
  expiredRequests: number;
  generation: number;
  owner: string;
  variantProfiles: Record<string, unknown>[];
}

async function installNetwork(page: Page, state: Network = { requests: [], writes: [], expiredRequests: 0, generation: 1, owner: OWNER_A, variantProfiles: [] }, realStorage = false): Promise<Network> {
  const cursors = new Map<string, { offset: number; signature: string; generation: number }>();
  if (realStorage) {
    page.on('request', request => {
      const path = new URL(request.url()).pathname;
      if (path.startsWith('/rest/v1/') && !['GET', 'HEAD'].includes(request.method())) {
        state.writes.push(`${request.method()} ${path} ${request.postData() ?? ''}`);
      }
    });
  } else {
    await page.route('**/auth/v1/**', async (route) => {
      const session = authSession(state.owner);
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(new URL(route.request().url()).pathname.endsWith('/user') ? session.user : session) });
    });
    await page.route('**/rest/v1/**', async (route) => {
      const request = route.request();
      if (!['GET', 'HEAD'].includes(request.method())) state.writes.push(`${request.method()} ${new URL(request.url()).pathname} ${request.postData() ?? ''}`);
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });
  }
  // Opening material editors is allowed; paying a provider or sending email
  // is not part of these navigation tests. Every such request fails locally.
  await page.route('**/api/cold-email**', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  await page.route('**/api/tailor**', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  await page.route('**/api/resume/**', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  await page.route('**/api/cold-email/variants', async (route) => {
    const request = route.request().postDataJSON();
    const profile = request.profile as Record<string, unknown>;
    state.variantProfiles.push(profile);
    expectResearchPython(profile);
    await route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({
        opportunity_id: request.opportunity_id, target_version: request.expected_target_version, contact_context_receipt: contactReceiptForRequest(request),
        variants: [{ contact_context_receipt: contactReceiptForRequest(request), id: 'return-template', label: 'Template', subject: 'Navigation draft', body: 'Dear Professor,\n\nNavigation fixture.\n\nReturn Test Student', recipient_email: 'professor@example.edu', mailto_link: 'mailto:professor@example.edu' }],
        recipient_status: 'revealed', lab_type: 'dry',
      }),
    });
  });
  await page.route('**/api/matches/view**', async (route) => {
    const request = route.request().postDataJSON() as ViewRequest;
    state.requests.push(request);
    expectResearchPython(request.profile);
    expect(request.page_size, 'use the production page size, not an artificially tiny fixture').toBe(50);
    expect(new URL(route.request().url()).searchParams.get('llm')).toBe('false');
    const signature = JSON.stringify({ profile: request.profile, view: request.view });
    let offset = 0;
    if (request.cursor) {
      const known = cursors.get(request.cursor);
      if (!known || known.generation !== state.generation || known.signature !== signature) {
        state.expiredRequests += 1;
        await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'MATCH_CURSOR_EXPIRED', message: 'This results cursor has expired.', retryable: false } }) });
        return;
      }
      offset = known.offset;
    }
    const view = request.view;
    let selected = CORPUS.filter((row) => {
      const opp = row.opportunity;
      return (!view.paid || opp.paid === view.paid)
        && (!view.search_query || opp.title.toLowerCase().includes(view.search_query.toLowerCase()))
        && (!view.source || opp.source === view.source)
        && (view.tab === 'all' || view.tab === row.bucket || (view.tab === 'starred' && view.favorite_ids.includes(opp.id)))
        && row.final_score >= view.min_score
        && (view.show_dismissed || !view.dismissed_ids.includes(opp.id));
    });
    if (view.sort_by === 'newest') selected = [...selected].sort((a, b) => b.opportunity.posted_date!.localeCompare(a.opportunity.posted_date!));
    const rows = selected.slice(offset, offset + request.page_size);
    const hasMore = offset + rows.length < selected.length;
    let nextCursor: string | null = null;
    if (hasMore) {
      nextCursor = `opaque-return-${state.generation}-${cursors.size + 1}`;
      cursors.set(nextCursor, { offset: offset + rows.length, signature, generation: state.generation });
    }
    const response: MatchesResponse = {
      total: CORPUS.length, high_priority: CORPUS.length, good_match: 0, reach: 0, low_fit: 0,
      results: rows, returned_count: rows.length, has_more: hasMore, next_cursor: nextCursor,
      result_set_id: `return-set-${state.generation}`, view_id: `return-view-${createHash('sha256').update(signature).digest('hex').slice(0, 16)}`,
      contract_version: 'match-view-v3-faculty-trust', target_truth_contract: 'target-truth-v2',
      view_start: offset, filtered_total: selected.length,
      view_counts: { all: selected.length, high_priority: selected.length, good_match: 0, reach: 0, starred: 0 },
      source_facets: [{ source: 'manual', count: CORPUS.length }], scope_available: false,
      ai_refined: false, matcher_version: 'return-fixture',
    };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) });
  });
  return state;
}

function expectResearchPython(profile: Record<string, unknown>) {
  expect(profile.seeking_type, 'stored plural preference reaches the API as research only').toEqual(['research']);
  expect(profile.hard_skills, 'legacy skills must not become empty objects after hydration').toEqual(
    expect.arrayContaining([expect.objectContaining({ name: 'Python', level: expect.any(String) })]),
  );
  expect((profile.hard_skills as Array<{ name?: unknown; level?: unknown }>).every(skill =>
    typeof skill.name === 'string' && skill.name.length > 0 && typeof skill.level === 'string'),
  'every skill sent to matching/writing has a name and level').toBe(true);
}

const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
interface SavedOwner { http: APIRequestContext; uid: string; token: string; revision: number }
async function commitSavedProfile(owner: SavedOwner, patch: Partial<ProfileData>) {
  const response = await owner.http.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
    headers: { Authorization: `Bearer ${owner.token}` },
    data: { p_expected_device_id: owner.uid, p_expected_revision: owner.revision, p_patch: patch },
  });
  expect(response.status()).toBe(200);
  const receipt = await response.json();
  expect(receipt).toMatchObject({ status: 'applied', revision: owner.revision + 1, profile: patch });
  owner.revision = receipt.revision;
}
async function seedSavedProfile(page: Page): Promise<SavedOwner> {
  expect(STUB.hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
    expect(signup.status()).toBe(200);
    const session = await signup.json();
    const owner = { http, uid: session.user.id as string, token: session.access_token as string, revision: 0 };
    await commitSavedProfile(owner, { ...PROFILE, skills: [{ name: 'Python', level: 'beginner' }] });
    await page.addInitScript(({ session, key }) => {
      if (!localStorage.getItem('e2e_return_cloud_seeded')) {
        localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(key, 'en');
        localStorage.setItem('e2e_return_cloud_seeded', '1');
      }
    }, { session, key: STORAGE_KEYS.LOCALE });
    const read = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/profiles' && response.status() === 200);
    await page.goto('/');
    expect(await (await read).json()).toMatchObject([{ revision: 1, profile_data: { name: PROFILE.name } }]);
    await expect(page.locator('#student_name')).toHaveValue(PROFILE.name);
    await expect(page.getByRole('button', { name: 'Generate Matches', exact: true })).toBeEnabled();
    return owner;
  } catch (error) { await http.dispose(); throw error; }
}
async function reconnectForProfileRead(page: Page, status = 200) {
  const read = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/profiles' && response.status() === status);
  await page.context().setOffline(true);
  await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
  await page.context().setOffline(false);
  await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(true);
  return read;
}

async function seedProfile(page: Page, blockSessionStorage = false, profile: typeof PROFILE & { resume_text?: string } = PROFILE): Promise<void> {
  await page.addInitScript(({ profileKey, profile, localeKey, session, blocked }) => {
    // Do not replace an account after reload/back. This one-time test setup
    // leaves all subsequent owner transitions to the shipped application.
    if (!localStorage.getItem('e2e_return_seeded')) {
      localStorage.setItem(profileKey, JSON.stringify(profile));
      localStorage.setItem('ofe_auth', JSON.stringify(session));
      localStorage.setItem(localeKey, 'en');
      localStorage.setItem('e2e_return_seeded', '1');
    }
    Object.defineProperty(navigator, 'share', { configurable: true, value: undefined });
    if (blocked) Object.defineProperty(window, 'sessionStorage', { configurable: true, get() { throw new DOMException('Blocked for test', 'SecurityError'); } });
  }, { profileKey: STORAGE_KEYS.PROFILE, profile, localeKey: STORAGE_KEYS.LOCALE, session: authSession(OWNER_A), blocked: blockSessionStorage });
}

async function onSecondPage(page: Page, state: Network) {
  await page.goto('/results?tab=all');
  await expect(page.locator('[id^="match-card-"]')).toHaveCount(50);
  await page.locator('#results-search-input').fill(PUBLIC_FILTERS.q);
  await page.locator('select').filter({ has: page.locator('option', { hasText: /^Paid only$/ }) }).selectOption('yes');
  await page.locator('select').filter({ has: page.locator('option[value="newest"]') }).selectOption('newest');
  await expect.poll(() => state.requests.at(-1)?.view).toMatchObject({ tab: 'all', search_query: PUBLIC_FILTERS.q, paid: 'yes', sort_by: 'newest' });
  await expect(page.getByText('1 / 2', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByText('2 / 2', { exact: true })).toBeVisible();
  await expect(page.locator('[id^="match-card-"]')).toHaveCount(8);
  await title(page).scrollIntoViewIfNeeded();
  await title(page).evaluate((el) => window.scrollTo({ top: window.scrollY + el.getBoundingClientRect().top - 160, behavior: 'instant' }));
  await expect(title(page)).toBeInViewport();
}

function expectPublicFilters(url: string) {
  const params = new URL(url).searchParams;
  for (const [key, value] of Object.entries(PUBLIC_FILTERS)) expect(params.get(key)).toBe(value);
  // No account, profile, cursor or result payload belongs in any navigation URL.
  expect([...params.keys()].filter((key) => ![...Object.keys(PUBLIC_FILTERS), 'returnSession'].includes(key))).toEqual([]);
}

async function expectRestored(page: Page, state: Network, requestCount: number) {
  await expect(page).toHaveURL(/\/results\?/);
  await expect(page.getByText('2 / 2', { exact: true })).toBeVisible();
  await expect(page.locator('[id^="match-card-"]')).toHaveCount(8);
  await expect(title(page)).toBeInViewport();
  await expect.poll(() => state.requests.length).toBeGreaterThan(requestCount);
  expect(state.requests.at(-1)?.cursor).toBeTruthy();
  expectPublicFilters(page.url());
  await expect(page.locator('#results-search-input')).toHaveValue(PUBLIC_FILTERS.q);
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(300);
}

// The remaining assertions are public behavior, not the record's internal
// shape. A change to session serialization should not require updating them.
test.describe('Results return context', () => {
  test.use({ viewport: { width: 1366, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'] });

  test('a delayed first legacy profile read preserves the current page, request and return session', async ({ page }) => {
    const net = await installNetwork(page);
    await seedProfile(page);
    let started = false;
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/rest/v1/profiles?**', async route => {
      started = true; await gate;
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    }, { times: 1 });
    try {
      await onSecondPage(page, net);
      await expect.poll(() => started).toBe(true);
      await expect(page.getByTestId('profile-refresh-status')).toContainText('Checking for profile updates');
      const before = { url: page.url(), count: net.requests.length, request: net.requests.at(-1) };
      expect(new URL(before.url).searchParams.get('returnSession')).toBeTruthy();
      expect(before.request?.profile.hard_skills).toEqual([{ name: 'Python', level: 'beginner' }]);
      const read = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/profiles');
      release(); expect(await (await read).json()).toEqual([]);
      await expect(page.getByTestId('profile-refresh-status')).toHaveCount(0);
      await expect(page.getByText('2 / 2', { exact: true })).toBeVisible();
      await expect(page.locator('[id^="match-card-"]')).toHaveCount(8);
      await expect(title(page)).toBeInViewport();
      expect(page.url()).toBe(before.url); expect(net.requests).toHaveLength(before.count);
      expect(net.requests.at(-1)).toEqual(before.request); expect(net.expiredRequests).toBe(0);
      expect(net.writes.filter(write => /profiles|commit_profile_patch_cas/.test(write))).toEqual([]);
      await title(page).click(); await page.getByTestId('return-to-results').click();
      await expectRestored(page, net, before.count);
    } finally { release(); }
  });

  test('a legacy profile passes the writing receipt check and receives an actual email template', async ({ page }) => {
    const net = await installNetwork(page);
    await seedProfile(page); await onSecondPage(page, net);
    const before = { url: page.url(), count: net.requests.length };
    await card(page).getByRole('button', { name: 'Draft Email', exact: true }).click();
    const fields = page.getByTestId('cold-email-editor-fields');
    await expect(fields.locator('#cold-email-subject')).toHaveValue('Navigation draft');
    await expect(fields.locator('#cold-email-body')).toHaveValue('Dear Professor,\n\nNavigation fixture.\n\nReturn Test Student');
    expect(net.variantProfiles.length).toBeGreaterThan(0);
    for (const profile of net.variantProfiles) {
      expectResearchPython(profile);
      expect(profile.hard_skills).toEqual([{ name: 'Python', level: 'beginner' }]);
    }
    await expect(page.getByTestId('cold-email-footer')).toBeVisible();
    await page.getByRole('button', { name: 'Close email editor', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(page.getByText('2 / 2', { exact: true })).toBeVisible();
    expect(page.url()).toBe(before.url); expect(net.requests).toHaveLength(before.count);
    expect(net.writes.filter(write => /commit_profile_patch_cas|interactions|(?:confirm_interaction_contact|confirm_contact_event)/.test(write))).toEqual([]);
  });

  test('a saved cloud profile restores page two until a real matching skill change arrives', async ({ page }) => {
    const net = await installNetwork(page, undefined, true);
    const owner = await seedSavedProfile(page);
    try {
      await onSecondPage(page, net);
      await expect(page.getByTestId('profile-refresh-status')).toHaveCount(0);
      const url = page.url(), count = net.requests.length;
      await page.reload(); await expectRestored(page, net, count);
      await expect(page.getByTestId('profile-refresh-status')).toHaveCount(0);
      expect(page.url()).toBe(url);
      const beforeChange = net.requests.length;
      await commitSavedProfile(owner, { skills: [{ name: 'Python', level: 'experienced', confirmed: true }] });
      const read = await reconnectForProfileRead(page);
      expect(await read.json()).toMatchObject([{ revision: 2, profile_data: { skills: [{ name: 'Python', level: 'experienced' }] } }]);
      await expect.poll(() => net.requests.at(-1)?.profile.hard_skills).toEqual([{ name: 'Python', level: 'experienced', confirmed: true }]);
      await expect(page.getByText('1 / 2', { exact: true })).toBeVisible();
      await expect(page.locator('[id^="match-card-"]')).toHaveCount(50);
      await expect(page.getByTestId('profile-refresh-status')).toHaveCount(0);
      expect(net.requests.length).toBeGreaterThan(beforeChange); expect(net.requests.at(-1)?.cursor).toBeNull();
      expect(net.expiredRequests).toBe(0); expectPublicFilters(page.url());
      expect(net.writes.filter(write => /profiles|commit_profile_patch_cas/.test(write))).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('foreground polling preserves page two until a silent cloud skill change arrives', async ({ page }) => {
    await page.clock.install();
    const net = await installNetwork(page, undefined, true);
    const owner = await seedSavedProfile(page);
    try {
      await onSecondPage(page, net);
      await expect(page.getByTestId('profile-refresh-status')).toHaveCount(0);
      const before = { url: page.url(), count: net.requests.length, scroll: await page.evaluate(() => window.scrollY) };
      const sameRead = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/profiles');
      await page.clock.fastForward(60_001);
      expect(await (await sameRead).json()).toMatchObject([{ revision: 1 }]);
      // Wait through the real hydration/React commit, not just the HTTP response.
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await expect(page.getByText('2 / 2', { exact: true })).toBeVisible();
      await expect(page.locator('[id^="match-card-"]')).toHaveCount(8);
      expect(page.url()).toBe(before.url); expect(net.requests).toHaveLength(before.count);
      expect(await page.evaluate(() => window.scrollY)).toBeCloseTo(before.scroll, 0);
      await commitSavedProfile(owner, { skills: [{ name: 'Python', level: 'experienced', confirmed: true }] });
      const changedRead = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/profiles');
      await page.clock.fastForward(60_001);
      expect(await (await changedRead).json()).toMatchObject([{ revision: 2 }]);
      await expect.poll(() => net.requests.at(-1)?.profile.hard_skills).toEqual([{ name: 'Python', level: 'experienced', confirmed: true }]);
      await expect(page.getByText('1 / 2', { exact: true })).toBeVisible();
      await expect(page.locator('[id^="match-card-"]')).toHaveCount(50);
      expect(net.requests.length).toBeGreaterThan(before.count); expect(net.requests.at(-1)?.cursor).toBeNull();
      expectPublicFilters(page.url()); expect(net.expiredRequests).toBe(0);
      expect(net.writes.filter(write => /profiles|commit_profile_patch_cas/.test(write))).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('a saved profile read failure preserves page two and never becomes a deletion', async ({ page }) => {
    const net = await installNetwork(page, undefined, true);
    const owner = await seedSavedProfile(page);
    try {
      await onSecondPage(page, net);
      await expect(page.getByTestId('profile-refresh-status')).toHaveCount(0);
      const before = { url: page.url(), count: net.requests.length,
        raw: await page.evaluate(key => localStorage.getItem(key), STORAGE_KEYS.PROFILE) };
      // Unlike [], an explicit read failure cannot fence a confirmed row as deleted.
      await page.route('**/rest/v1/profiles?**', route => route.fulfill({ status: 403,
        contentType: 'application/json', body: JSON.stringify({ message: 'Controlled profile read failure' }) }));
      await reconnectForProfileRead(page, 403);
      const notice = page.getByTestId('profile-refresh-status');
      await expect(notice).toContainText('Could not check for profile updates. Your draft is kept.');
      await expect(page.getByText('2 / 2', { exact: true })).toBeVisible(); await expect(card(page)).toBeVisible();
      expect(page.url()).toBe(before.url); expect(net.requests).toHaveLength(before.count);
      expect(await page.evaluate(key => localStorage.getItem(key), STORAGE_KEYS.PROFILE)).toBe(before.raw);
      await page.unroute('**/rest/v1/profiles?**');
      const read = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/profiles' && response.status() === 200);
      await notice.getByRole('button', { name: 'Retry', exact: true }).click();
      expect(await (await read).json()).toMatchObject([{ revision: 1, profile_data: { name: PROFILE.name } }]);
      await expect(notice).toHaveCount(0); await expect(page.getByText('2 / 2', { exact: true })).toBeVisible();
      expect(page.url()).toBe(before.url); expect(net.requests).toHaveLength(before.count);
      expect(net.writes.filter(write => /profiles|commit_profile_patch_cas/.test(write))).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  for (const back of ['detail button', 'browser back'] as const) {
    test(`page, filters and target position survive ${back}`, async ({ page }) => {
      const net = await installNetwork(page);
      await seedProfile(page);
      await onSecondPage(page, net);
      const count = net.requests.length;
      await title(page).click();
      await expect(page).toHaveURL(new RegExp(`/opportunities/${TARGET}`));
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      if (back === 'detail button') await page.getByTestId('return-to-results').click();
      else await page.goBack();
      await expectRestored(page, net, count);
      await expect(card(page).getByText(en.card.viewed, { exact: true })).toBeVisible();
      expect(net.writes.filter((write) => /interactions|(?:confirm_interaction_contact|confirm_contact_event)/.test(write))).toEqual([]);
    });
  }

  test('refresh on page two validates the saved cursor before restoring the target', async ({ page }) => {
    const net = await installNetwork(page);
    await seedProfile(page);
    await onSecondPage(page, net);
    const count = net.requests.length;
    await page.reload();
    await expectRestored(page, net, count);
  });

  test('refreshing the detail page preserves its return to the same result context', async ({ page }) => {
    const net = await installNetwork(page);
    await seedProfile(page);
    await onSecondPage(page, net);
    const count = net.requests.length;
    await title(page).click();
    await expect(page.getByTestId('return-to-results')).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.getByTestId('return-to-results').click();
    await expectRestored(page, net, count);
  });

  for (const exit of ['close button', 'browser back'] as const) {
    test(`email and resume ${exit} retains the list and only marks viewed`, async ({ page }) => {
    const net = await installNetwork(page);
    await seedProfile(page);
    await onSecondPage(page, net);
    const url = page.url();
    const count = net.requests.length;
    for (const [open, close] of [['Draft Email', 'Close email editor'], ['Tailor Resume', 'Close tailor panel'], ['Renovate Resume', 'Close target résumé']]) {
      await card(page).getByRole('button', { name: open, exact: true }).click();
      await expect(page.getByRole('dialog')).toBeVisible();
      if (exit === 'close button') await page.getByRole('button', { name: close, exact: true }).click();
      else await page.goBack();
      await expect(page.getByRole('dialog')).toBeHidden();
      await expect(page.getByText('2 / 2', { exact: true })).toBeVisible();
      await expect(title(page)).toBeInViewport();
      expect(page.url()).toBe(url);
    }
    await expect(card(page).getByText(en.card.viewed, { exact: true })).toBeVisible();
    expect(net.requests).toHaveLength(count);
    expect(net.writes.filter((write) => /interactions|(?:confirm_interaction_contact|confirm_contact_event)/.test(write))).toEqual([]);
  });
  }

  test('browser Back keeps supplemental answers until the user confirms leaving', async ({ page }) => {
    const net = await installNetwork(page); await seedProfile(page); await onSecondPage(page, net);
    const url = page.url(); const count = net.requests.length;
    await card(page).getByRole('button', { name: 'Renovate Resume', exact: true }).click();
    await page.getByRole('button', { name: 'Add experience details', exact: true }).click();
    const panel = page.getByRole('region', { name: 'Add experience details', exact: true });
    const answer = panel.getByRole('textbox', { name: 'What was the task?', exact: true });
    await answer.fill('Keep this unconfirmed answer when Back is cancelled.');
    await page.goBack();
    await expect(page.getByRole('dialog', { name: 'Target résumé', exact: true })).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Target résumé', exact: true }).getByRole('alert')).toContainText('unsaved edits, suggestions or answers');
    await page.getByRole('button', { name: 'Keep editing', exact: true }).click();
    await expect(answer).toHaveValue('Keep this unconfirmed answer when Back is cancelled.');
    expect(page.url()).toBe(url);
    await page.goBack();
    await expect(page.getByRole('dialog', { name: 'Target résumé', exact: true }).getByRole('alert')).toContainText('unsaved edits, suggestions or answers');
    await page.getByRole('button', { name: 'Discard unsaved edits and continue', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(page.getByText('2 / 2', { exact: true })).toBeVisible();
    await expect(title(page)).toBeInViewport();
    expect(page.url()).toBe(url); expect(net.requests).toHaveLength(count);
    expectPublicFilters(page.url());
    expect(net.writes.filter(write => /commit_profile_patch_cas|commit_target_resume_cas/.test(write))).toEqual([]);
  });

  for (const failure of ['read failure', 'invalid saved document'] as const) {
    test(`renovation ${failure} blocks replacement until retry restores the saved draft`, async ({ page }) => {
      const net = await installNetwork(page);
      await seedProfile(page, false, { ...PROFILE, resume_text: 'Built a small Python research project.' });
      const existingText = 'Manually edited experience from the saved draft.';
      const stored = {
        doc: {
          sections: [{ id: 's1', heading: 'Projects', kind: 'projects', bullets: [{
            id: 'b1', base_text: 'Built a Python project.',
            variants: [{ source: 'user', text: existingText, source_evidence: '' }],
            current: 0, action: 'keep',
          }] }], method: 'fallback', warnings: [],
        },
        base_snapshot: {}, method: 'fallback', warnings: [], updated_at: '2026-09-24T00:00:00Z',
      };
      let reads = 0;
      // Every read before the user's retry fails: `next dev` runs React
      // StrictMode, whose mount/unmount/mount issues a second, discarded read.
      let retried = false;
      await page.route('**/rest/v1/rpc/read_renovation', async (route) => {
        expect(route.request().method()).toBe('POST');
        reads += 1;
        if (!retried && failure === 'read failure') {
          await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ message: 'synthetic-private-backend-detail' }) });
          return;
        }
        const data = retried ? stored : { ...stored, doc: { sections: 'broken' } };
        const request = route.request().postDataJSON();
        const { updated_at, ...payload } = data;
        await route.fulfill({ status: 200, json: { status: 'found', current: { owner_id: request.p_expected_owner,
          opportunity_id: request.p_opportunity_id, revision: 1, updated_at, payload } } });
      });
      await onSecondPage(page, net);
      await card(page).getByRole('button', { name: 'Renovate Resume', exact: true }).click();
      await page.getByRole('button', { name: 'Edit résumé bullets', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: 'Résumé bullets', exact: true });
      await expect(dialog.getByText(en.renovate.restoreFailed, { exact: true })).toBeVisible();
      await expect(dialog.getByRole('button', { name: en.renovate.start, exact: true })).toHaveCount(0);
      await expect(dialog.getByText('synthetic-private-backend-detail')).toHaveCount(0);
      expect(net.writes.filter((write) => write.includes('/save_renovation_cas') || write.includes('/resume_renovations'))).toEqual([]);
      const readsBeforeRetry = reads;
      // playwright.config serves the production build only under CI.
      expect(readsBeforeRetry).toBeGreaterThanOrEqual(1); expect(readsBeforeRetry).toBeLessThanOrEqual(process.env.CI ? 1 : 2);
      retried = true;
      await dialog.getByRole('button', { name: en.renovate.restoreRetry, exact: true }).click();
      await expect(dialog.getByText(en.renovate.restored, { exact: true })).toBeVisible();
      await expect(dialog.getByRole('button', { name: en.renovate.copyAll, exact: true })).toBeVisible();
      await expect(dialog.getByText(existingText, { exact: false })).toBeVisible();
      expect(reads).toBe(readsBeforeRetry + 1);
      expect(net.writes.filter((write) => write.includes('/save_renovation_cas') || write.includes('/resume_renovations'))).toEqual([]);
    });
  }

  test('an expired result cursor resets once with an explanation and keeps filters', async ({ page }) => {
    const net = await installNetwork(page);
    await seedProfile(page);
    await onSecondPage(page, net);
    await title(page).click();
    await expect(page.getByTestId('return-to-results')).toBeVisible();
    net.generation += 1;
    await page.getByTestId('return-to-results').click();
    await expect(page.getByText('1 / 2', { exact: true })).toBeVisible();
    await expect(page.getByText(RESET_NOTICE, { exact: true })).toBeVisible();
    await expect(card(page)).toHaveCount(0);
    expect(net.expiredRequests).toBe(1);
    expect(net.requests.at(-1)?.cursor).toBeNull();
    expectPublicFilters(page.url());
  });

  test('unavailable sessionStorage leaves working filters and safe page-one navigation', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const net = await installNetwork(page);
    await seedProfile(page, true);
    await onSecondPage(page, net);
    await title(page).click();
    await page.getByTestId('return-to-results').click();
    await expect(page.getByText('1 / 2', { exact: true })).toBeVisible();
    await expect(page.locator('[id^="match-card-"]')).toHaveCount(50);
    expectPublicFilters(page.url());
    expect(errors).toEqual([]);
  });

  test('a different auth owner cannot restore the previous account\'s result page', async ({ page, context }) => {
    const net = await installNetwork(page);
    await seedProfile(page);
    await onSecondPage(page, net);
    await title(page).click();
    await expect(page.getByTestId('return-to-results')).toBeVisible();
    const count = net.requests.length;
    net.owner = OWNER_B;
    // Same browser boundary used by supabase-js for another tab's sign-in.
    // No production function or React state is invoked by this fixture.
    const secondTab = await context.newPage();
    await secondTab.goto('/robots.txt');
    await secondTab.evaluate((session) => {
      localStorage.setItem('ofe_auth', JSON.stringify(session));
      const channel = new BroadcastChannel('ofe_auth');
      channel.postMessage({ event: 'SIGNED_IN', session });
      channel.close();
    }, authSession(OWNER_B));
    await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), STORAGE_KEYS.LOCAL_IDENTITY_OWNER)).toContain(OWNER_B);
    await secondTab.close();
    await page.getByTestId('return-to-results').click();
    // U2 has no saved profile in this fixture, so the ordinary profile gate
    // is the safe outcome; U1's rows, filters/cursor record cannot be reused.
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole('heading', { name: /Find Your Perfect/i })).toBeVisible();
    expect(net.requests.slice(count).some((request) => !!request.cursor)).toBe(false);
    await expect(card(page)).toHaveCount(0);
  });

  test('detail sharing is canonical and neither copied navigation nor public filter links restore a private page in a new tab', async ({ page, context }) => {
    const net = await installNetwork(page);
    await seedProfile(page);
    await onSecondPage(page, net);
    expectPublicFilters(page.url());
    const copiedNavigationUrl = page.url();
    const publicUrl = new URL('/results', page.url());
    for (const [key, value] of Object.entries(PUBLIC_FILTERS)) publicUrl.searchParams.set(key, value);
    await title(page).click();
    await page.getByRole('button', { name: 'Share', exact: true }).click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(`${new URL(page.url()).origin}/opportunities/${TARGET}`);
    // There is no Results Share button in this release. Test the two actual
    // supported link forms: copying its address bar, and a public filter URL.
    for (const url of [copiedNavigationUrl, publicUrl.toString()]) {
      const fresh = await context.newPage();
      const freshNet = await installNetwork(fresh);
      await fresh.goto(url);
      await expect(fresh.getByText('1 / 2', { exact: true })).toBeVisible();
      await expect(fresh.locator('[id^="match-card-"]')).toHaveCount(50);
      await expect(card(fresh)).toHaveCount(0);
      expectPublicFilters(fresh.url());
      expect(freshNet.requests.every((request) => request.cursor === null)).toBe(true);
      await fresh.close();
    }
  });
});
