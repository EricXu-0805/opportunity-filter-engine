import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { CourseEntry, ProfileData, ProfileRequest } from '../src/lib/types';

// Checklist M13 end to end: a profile saved before course statuses existed
// (only `coursework` names) reads as courses not marked; the student marks
// them on the home form, adds one by hand, and the request that goes out
// carries each course with the status they chose. The save lands in the
// cloud row with the names beside it for older clients.
const STUB = `http://127.0.0.1:${process.env.E2E_SUPABASE_PORT ?? 54321}`;
const FRONT = `http://127.0.0.1:${process.env.E2E_PORT ?? 3100}`;
const BACK = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT ?? 8100}`;

const LEGACY: ProfileData = {
  name: 'Alex 王', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
  major: 'Computer Science', grade: 'Junior', is_international: false, research_interests: 'robotics',
  skills: [{ name: 'Python', level: 'beginner' }], coursework: ['CS 225', 'CS 446'], seeking_types: ['research'],
  search_weight: 50,
};
const MARKED: CourseEntry[] = [
  { name: 'CS 225', status: 'completed', source: 'resume' },
  { name: 'CS 446', status: 'planned', source: 'resume' },
  { name: 'STAT 400', status: 'in_progress', source: 'manual' },
];

async function signedInWithLegacyProfile(page: Page, request: APIRequestContext, locale: 'en' | 'zh') {
  const session = await (await request.post(`${STUB}/auth/v1/signup`, { data: {} })).json();
  const seeded = await request.post(`${STUB}/rest/v1/rpc/commit_profile_patch_cas`, {
    headers: { Authorization: `Bearer ${session.access_token}` },
    data: { p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: LEGACY },
  });
  expect(await seeded.json()).toMatchObject({ status: 'applied' });
  const external: string[] = [];
  const sent: ProfileRequest[] = [];
  await page.context().route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (![STUB, FRONT, BACK].includes(url.origin)) { external.push(url.origin); return route.abort(); }
    // Nothing is ranked or written by a model here: the request is the evidence.
    if (url.pathname.startsWith('/api/matches')) {
      const body = route.request().postDataJSON() as { profile?: ProfileRequest } & ProfileRequest;
      sent.push(body.profile ?? body);
      return route.abort();
    }
    if (/^\/api\/(cold-email|tailor|chat|send)/.test(url.pathname)) return route.abort();
    return route.continue();
  });
  await page.context().addCookies([{ name: STORAGE_KEYS.LOCALE, value: locale, url: FRONT }]);
  await page.addInitScript(({ session, keys, locale }) => {
    if (sessionStorage.getItem('m13-seeded')) return;
    localStorage.setItem('ofe_auth', JSON.stringify(session));
    localStorage.setItem(keys.LOCALE, locale);
    localStorage.setItem(keys.ONBOARDING_SEEN, '1');
    sessionStorage.setItem('m13-seeded', '1');
  }, { session, keys: STORAGE_KEYS, locale });
  return { session, external, sent };
}

async function storedProfile(request: APIRequestContext, uid: string): Promise<ProfileData> {
  const rows = await (await request.get(`${STUB}/rest/v1/profiles?select=id,revision,profile_data&id=eq.${uid}`)).json();
  return rows[0].profile_data as ProfileData;
}

for (const locale of ['en', 'zh'] as const) {
  test(`marks course statuses on the home form and sends them with the profile (${locale})`, async ({ page, request }, info) => {
    test.setTimeout(90_000);
    const copy = (en: string, zh: string) => (locale === 'zh' ? zh : en);
    if (locale === 'zh') await page.setViewportSize({ width: 390, height: 844 });
    const { session, external, sent } = await signedInWithLegacyProfile(page, request, locale);
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));

    await page.goto('/');
    const statusOf = (course: string) => page.getByLabel(copy(`Status of ${course}`, `${course} 的状态`), { exact: true });
    // A course saved before statuses existed is never shown as completed.
    await expect(statusOf('CS 225')).toHaveValue('unknown');
    await expect(statusOf('CS 446')).toHaveValue('unknown');
    await expect(page.getByText(copy('2 not marked yet.', '有 2 门课还未标注。'), { exact: false })).toBeVisible();

    await statusOf('CS 225').selectOption('completed');
    await statusOf('CS 446').selectOption('planned');
    await page.getByLabel(copy('Add a course', '添加课程'), { exact: true }).fill('STAT 400');
    await page.getByLabel(copy('Status of the new course', '新课程的状态'), { exact: true }).selectOption('in_progress');
    await page.getByRole('button', { name: copy('Add', '添加'), exact: true }).click();
    await expect(statusOf('STAT 400')).toHaveValue('in_progress');
    await expect(page.getByText(copy('not marked yet', '还未标注'), { exact: false })).toHaveCount(0);
    // The rows fit a phone without scrolling sideways.
    expect(await page.evaluate(() => document.body.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await statusOf('STAT 400').scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`course-status-${locale}.png`) });

    await page.getByTestId('generate-matches').click();
    await expect(page).toHaveURL(/\/results/);
    await expect.poll(() => sent.length, { timeout: 30_000 }).toBeGreaterThan(0);
    expect(sent[0].courses).toEqual(MARKED);
    expect(sent[0].coursework).toEqual(['CS 225', 'CS 446', 'STAT 400']);

    const stored = await storedProfile(request, session.user.id);
    expect(stored.courses).toEqual(MARKED);
    expect(stored.coursework).toEqual(['CS 225', 'CS 446', 'STAT 400']);

    // Read back from the cloud row: the statuses the student chose.
    await page.goto('/');
    await expect(statusOf('CS 225')).toHaveValue('completed');
    await expect(statusOf('CS 446')).toHaveValue('planned');
    await expect(statusOf('STAT 400')).toHaveValue('in_progress');
    expect(external).toEqual([]);
    expect(errors).toEqual([]);
  });
}
