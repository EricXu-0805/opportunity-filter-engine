import { test, expect, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';
import type { MatchResult, MatchesResponse } from '../src/lib/types';
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
  skills: ['Python'], coursework: ['CS 225'], seeking_type: ['research'],
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
}

async function installNetwork(page: Page, state: Network = { requests: [], writes: [], expiredRequests: 0, generation: 1, owner: OWNER_A }): Promise<Network> {
  const cursors = new Map<string, { offset: number; signature: string; generation: number }>();
  await page.route('**/auth/v1/**', async (route) => {
    const session = authSession(state.owner);
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(new URL(route.request().url()).pathname.endsWith('/user') ? session.user : session) });
  });
  await page.route('**/rest/v1/**', async (route) => {
    const request = route.request();
    if (!['GET', 'HEAD'].includes(request.method())) state.writes.push(`${request.method()} ${new URL(request.url()).pathname} ${request.postData() ?? ''}`);
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });
  // Opening material editors is allowed; paying a provider or sending email
  // is not part of these navigation tests. Every such request fails locally.
  await page.route('**/api/cold-email**', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  await page.route('**/api/tailor**', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  await page.route('**/api/resume/**', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  await page.route('**/api/cold-email/variants', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      variants: [{ id: 'return-template', label: 'Template', subject: 'Navigation draft', body: 'Dear Professor,\n\nNavigation fixture.\n\nReturn Test Student', recipient_email: 'professor@example.edu', mailto_link: 'mailto:professor@example.edu' }],
      recipient_status: 'revealed', lab_type: 'dry',
    }),
  }));
  await page.route('**/api/matches/view**', async (route) => {
    const request = route.request().postDataJSON() as ViewRequest;
    state.requests.push(request);
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
      expect(net.writes.filter((write) => /interactions|confirm_interaction_contact/.test(write))).toEqual([]);
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
    expect(net.writes.filter((write) => /interactions|confirm_interaction_contact/.test(write))).toEqual([]);
  });
  }

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
      await page.route('**/rest/v1/resume_renovations?**', async (route) => {
        expect(route.request().method()).toBe('GET');
        reads += 1;
        if (reads === 1 && failure === 'read failure') {
          await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ message: 'synthetic-private-backend-detail' }) });
          return;
        }
        const data = reads === 1 ? { ...stored, doc: { sections: 'broken' } } : stored;
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([data]) });
      });
      await onSecondPage(page, net);
      await card(page).getByRole('button', { name: 'Renovate Resume', exact: true }).click();
      await page.getByRole('button', { name: 'Edit résumé bullets', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: 'Résumé bullets', exact: true });
      await expect(dialog.getByText(en.renovate.restoreFailed, { exact: true })).toBeVisible();
      await expect(dialog.getByRole('button', { name: en.renovate.start, exact: true })).toHaveCount(0);
      await expect(dialog.getByText('synthetic-private-backend-detail')).toHaveCount(0);
      expect(net.writes.filter((write) => write.includes('resume_renovation'))).toEqual([]);
      await dialog.getByRole('button', { name: en.renovate.restoreRetry, exact: true }).click();
      await expect(dialog.getByText(en.renovate.restored, { exact: true })).toBeVisible();
      await expect(dialog.getByRole('button', { name: en.renovate.copyAll, exact: true })).toBeVisible();
      await expect(dialog.getByText(existingText, { exact: false })).toBeVisible();
      expect(reads).toBe(2);
      expect(net.writes.filter((write) => write.includes('resume_renovation'))).toEqual([]);
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
