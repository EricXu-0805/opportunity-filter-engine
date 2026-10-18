import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
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

async function signedInWithLegacyProfile(page: Page, request: APIRequestContext, locale: 'en' | 'zh', profile: object = LEGACY) {
  const session = await (await request.post(`${STUB}/auth/v1/signup`, { data: {} })).json();
  const seeded = await request.post(`${STUB}/rest/v1/rpc/commit_profile_patch_cas`, {
    headers: { Authorization: `Bearer ${session.access_token}` },
    data: { p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: profile },
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
    await expect(page.getByText(copy('Not marked yet: 2.', '有 2 门课还未标注。'), { exact: false })).toBeVisible();

    await statusOf('CS 225').selectOption('completed');
    await statusOf('CS 446').selectOption('planned');
    await page.getByLabel(copy('Add a course', '添加课程'), { exact: true }).fill('STAT 400');
    await page.getByLabel(copy('Status of the new course', '新课程的状态'), { exact: true }).selectOption('in_progress');
    await page.getByRole('button', { name: copy('Add', '添加'), exact: true }).click();
    await expect(statusOf('STAT 400')).toHaveValue('in_progress');
    await expect(page.getByText(copy('not marked yet', '还未标注'), { exact: false })).toHaveCount(0);
    // The rows fit a phone without scrolling sideways; a failure names what sticks out.
    const wide = await page.evaluate(() => {
      const edge = document.documentElement.clientWidth;
      return Array.from(document.querySelectorAll('body *'))
        .map((el) => ({ el, right: el.getBoundingClientRect().right }))
        .filter(({ right }) => right > edge + 0.5)
        .slice(0, 12)
        .map(({ el, right }) => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}`
          + ` .${String(el.getAttribute('class') ?? '').split(/\s+/).slice(0, 5).join('.')}`
          + ` right=${Math.round(right)} text="${(el.textContent ?? '').trim().slice(0, 40)}"`);
    });
    expect(await page.evaluate(() => document.body.scrollWidth <= document.documentElement.clientWidth), wide.join('\n')).toBe(true);
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

// A profile whose courses come from one ordinary 115-character résumé line,
// plus a line whose label says the courses on it are current: the form only
// suggests that status until the student confirms it. What is stored
// is what an import stores (names, from the résumé, no status); `evidence` is
// what the previous version of this branch kept with each course, which this
// build neither reads nor writes: every line shown comes from the text.
const LONG_LINE = 'Relevant Coursework: Data Structures, Computer Architecture, Linear Algebra, Probability and Statistics, Algorithms';
const CURRENT_LINE = 'Current courses: CS 374, MATH 415';
const LISTED = ['Data Structures', 'Computer Architecture', 'Linear Algebra', 'Probability and Statistics', 'Algorithms'];
const CURRENT = ['CS 374', 'MATH 415'];
const IMPORTED = {
  ...LEGACY,
  resume_text: `${LONG_LINE}\n${CURRENT_LINE}`,
  courses: [
    ...LISTED.map((name) => ({ name, source: 'resume', evidence: LONG_LINE })),
    ...CURRENT.map((name) => ({ name, source: 'resume', evidence: CURRENT_LINE })),
  ],
  coursework: [...LISTED, ...CURRENT],
};

for (const [locale, width] of [['zh', 390], ['en', 1280]] as const) {
  test(`courses from a long résumé line fit at ${width} px, and a status the résumé suggests is sent only once confirmed (${locale})`, async ({ page, request }, info) => {
    test.setTimeout(90_000);
    expect(LONG_LINE).toHaveLength(115);
    const copy = (en: string, zh: string) => (locale === 'zh' ? zh : en);
    await page.setViewportSize({ width, height: 900 });
    const { session, external, sent } = await signedInWithLegacyProfile(page, request, locale, IMPORTED);
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));

    await page.goto('/');
    const statusOf = (course: string) => page.getByLabel(copy(`Status of ${course}`, `${course} 的状态`), { exact: true });
    const removeOf = (course: string) => page.getByRole('button', { name: copy(`Remove ${course}`, `移除 ${course}`), exact: true });
    await expect(statusOf('MATH 415')).toBeVisible();
    // The list is no wider than the page, and every control is where a finger
    // or a pointer lands on it, not under the next card.
    const list = await page.getByRole('group', { name: copy('Courses', '课程'), exact: true }).evaluate((element) => ({
      right: element.getBoundingClientRect().right, scroll: element.scrollWidth, client: element.clientWidth,
    }));
    expect(list.right).toBeLessThanOrEqual(width);
    expect(list.scroll).toBeLessThanOrEqual(list.client);
    for (const course of [...LISTED, ...CURRENT]) {
      for (const [kind, control] of [['status', statusOf(course)], ['remove', removeOf(course)]] as const) {
        await control.scrollIntoViewIfNeeded();
        const box = (await control.boundingBox())!;
        expect(box.x, `${course} ${kind}`).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width, `${course} ${kind}`).toBeLessThanOrEqual(width);
        const hit = await control.evaluate((element, [x, y]) => {
          const top = document.elementFromPoint(x, y);
          return !!top && (top === element || element.contains(top));
        }, [box.x + box.width / 2, box.y + box.height / 2]);
        expect(hit, `${course} ${kind}: the control is the element at its own centre`).toBe(true);
      }
    }
    // Every control in the list is a target of at least 24 by 24 px, or far
    // enough from the next one (WCAG 2.2 target size, axe "target-size").
    const targets = await new AxeBuilder({ page }).include('fieldset:has(input[id$="-add"])').withRules(['target-size']).analyze();
    expect(targets.violations.flatMap((violation) => violation.nodes.map((node) => node.html))).toEqual([]);
    await statusOf('CS 374').scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`course-status-long-line-${locale}-${width}.png`), fullPage: true });

    for (const course of LISTED) await expect(statusOf(course)).toHaveValue('unknown');
    // Suggested by the line "Current courses:", shown as a status to check.
    for (const course of CURRENT) await expect(statusOf(course)).toHaveValue('in_progress');
    await expect(page.getByText(copy('From your résumé — please check', '据简历推断，请确认'), { exact: true })).toHaveCount(2);
    await expect(page.getByText(copy(`From your résumé: “${LONG_LINE}”`, `来自你的简历：「${LONG_LINE}」`), { exact: true })).toHaveCount(5);

    await page.getByRole('button', { name: copy('Confirm In progress for CS 374', '确认 CS 374 为「在修」'), exact: true }).click();
    await expect(page.getByText(copy('From your résumé — please check', '据简历推断，请确认'), { exact: true })).toHaveCount(1);
    await expect(statusOf('CS 374')).toBeFocused();
    await expect.poll(async () => (await storedProfile(request, session.user.id)).courses?.find((course) => course.name === 'CS 374')?.status,
      { timeout: 15_000 }).toBe('in_progress');
    const stored = await storedProfile(request, session.user.id);
    // Only the status the student set is stored; no line from the résumé is.
    expect(stored.courses).toEqual([
      ...LISTED.map((name) => ({ name, source: 'resume' })),
      { name: 'CS 374', source: 'resume', status: 'in_progress' },
      { name: 'MATH 415', source: 'resume' },
    ]);
    expect(stored.coursework).toEqual([...LISTED, ...CURRENT]);

    await page.getByTestId('generate-matches').click();
    await expect(page).toHaveURL(/\/results/);
    await expect.poll(() => sent.length, { timeout: 30_000 }).toBeGreaterThan(0);
    // The confirmed course goes in progress; the one the résumé only
    // suggests goes as not marked.
    expect(sent[0].courses).toEqual([
      ...LISTED.map((name) => ({ name, status: 'unknown', source: 'resume' })),
      { name: 'CS 374', status: 'in_progress', source: 'resume' },
      { name: 'MATH 415', status: 'unknown', source: 'resume' },
    ]);
    expect(external).toEqual([]);
    expect(errors).toEqual([]);
  });
}
