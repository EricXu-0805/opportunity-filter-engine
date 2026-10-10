import AxeBuilder from '@axe-core/playwright';
import { test, expect, type BrowserContext, type Page } from '@playwright/test';
import { contactReceiptForRequest } from './email-contact-receipt';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { en, zh } from '../src/i18n/dictionaries';

/**
 * M59: the five core screens at phone width (390 px), walked once in English
 * and once in Chinese, each checked with axe-core's default rule set.
 *
 * A finding fails the run when it is serious or critical and BASELINE does not
 * name it. Unnamed moderate and minor findings are annotated and never fail.
 * Every finding, named or not, is in the attached axe-<locale>.json. BASELINE
 * is what was still open on 2026-10-09: a list of debts, not acceptable things.
 * An entry that a run no longer sees fails the run too, so it is deleted when
 * its fix lands; only entries marked mayBeAbsent are exempt.
 *
 * Every cold-email request is answered here, so none reaches the backend or a
 * model: the template variants get a fixed draft and the rest, including the
 * AI draft the editor starts on its own, get a 503. Every non-loopback request
 * is aborted. Results come from the local backend and the tracker from the
 * loopback Supabase stub, so the walk runs the shipped code.
 *
 * Not covered here and still owed by M59: a real screen reader (VoiceOver,
 * TalkBack), real 200% zoom, and real phones.
 */

const ORIGIN = `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3100)}`;
const KNOWN_ID = 'uiuc-siebel-ugresearch';
const STEPS = ['home', 'results', 'detail', 'cold-email-editor', 'tracker'] as const;
type Step = typeof STEPS[number];
type Impact = 'critical' | 'serious' | 'moderate' | 'minor';
const BLOCKING: ReadonlySet<string> = new Set<Impact>(['critical', 'serious']);

interface Finding { step: Step; rule: string; impact: string; help: string; target: string; html: string; fg?: string; ratio?: number }

interface Known {
  rule: string;
  impact: Impact;
  /** Where it may appear. Omitted for a text colour: the debt is the token, wherever it is used. */
  steps?: readonly Step[];
  /** color-contrast only: the foreground colour axe measured. */
  fg?: string;
  /**
   * color-contrast only: just under the lowest ratio measured (or, if never
   * seen, computed) for this colour. A worse pairing is a new debt and fails.
   */
  minRatio?: number;
  /** The element, as axe's selector names it, when the rule must stay live elsewhere on the step. */
  target?: string;
  /** Why a run may not see this entry even though the debt is still open. */
  mayBeAbsent?: string;
  /** What fails, where it comes from, and what the fix needs. */
  name: string;
}

// Colour entries are keyed on the text colour plus a ratio floor. Results come
// from live data, so which card badges and backgrounds appear moves with every
// refresh; a pair-exact key would turn a data PR red without any code change.
// Ratios are axe's, which truncates to two decimals.
const BASELINE: readonly Known[] = [
  {
    rule: 'label', impact: 'critical', steps: ['home'], target: '#resume-upload',
    name: 'ResumeUpload.tsx\'s visually hidden PDF input has no accessible name. A real one ("Upload your résumé (PDF)") '
      + 'is new copy in both languages, so it waits for the post-merge list.',
  },
  {
    rule: 'landmark-main-is-top-level', impact: 'moderate', steps: ['detail'],
    name: 'OpportunityDetail.tsx renders a <main> inside the layout\'s <main id="main-content">.',
  },
  {
    rule: 'landmark-no-duplicate-main', impact: 'moderate', steps: ['detail'],
    name: 'Same nested <main> as above, seen as a second main landmark.',
  },
  {
    rule: 'landmark-unique', impact: 'moderate', steps: ['detail'],
    name: 'Same nested <main> as above: two main landmarks with no distinguishing name.',
  },
  {
    rule: 'heading-order', impact: 'moderate', steps: ['results'],
    name: 'Match card titles are <h3> straight after the page <h1>.',
  },
];

function knownFor(finding: Finding): Known | undefined {
  return BASELINE.find(k => k.rule === finding.rule && k.impact === finding.impact
    && (!k.steps || k.steps.includes(finding.step))
    // A colour entry without a floor never matches, so a missing minRatio fails closed.
    && (!k.fg || (k.fg === finding.fg && (finding.ratio ?? 0) >= (k.minRatio ?? Infinity)))
    && (!k.target || k.target === finding.target));
}

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

async function hermetic(context: BrowserContext) {
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) return route.abort('blockedbyclient');
    return route.continue();
  });
}

// The editor starts an AI draft (POST /api/cold-email/stream) by itself once
// the template lands. Passed through, it reaches the local backend, which calls
// the paid model whenever its environment has a provider key: a developer's
// backend/.env, or a dev backend Playwright reuses. A 503 leaves the editor as
// CI's keyless backend does: the automatic draft keeps the template silently.
// Routes registered later win, so the variants stub answers before the 503.
async function stubColdEmail(page: Page, refused: string[]) {
  await page.route('**/api/cold-email**', route => {
    refused.push(new URL(route.request().url()).pathname);
    return route.fulfill({ status: 503, json: {} });
  });
  await page.route('**/api/cold-email/variants', route => {
    const request = route.request().postDataJSON();
    const receipt = contactReceiptForRequest(request);
    return route.fulfill({ json: {
      opportunity_id: request.opportunity_id, target_version: request.expected_target_version,
      contact_context_receipt: receipt, recipient_status: 'revealed', lab_type: null,
      variants: [{ id: 'v1', label: 'Template A', subject: 'Interested in your research',
        body: 'Dear Professor,\n\nI am interested in your lab.\n\nBest,\nAlex', recipient_email: 'prof@illinois.edu',
        mailto_link: 'mailto:prof@illinois.edu', contact_context_receipt: receipt }],
    } });
  });
}

// Client-only parts (the profile, lazily loaded widgets) arrive after the
// server HTML; scanning before they land checks a page nobody keeps seeing.
// A fade or slide caught mid-way is measured at its partial opacity, which
// reads as a contrast failure that no user sees once it settles.
async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(document.getAnimations()
      .filter(a => Number.isFinite(a.effect?.getComputedTiming().endTime ?? Infinity))
      .map(a => a.finished.catch(() => undefined)));
  });
}

async function scan(page: Page, step: Step, locale: 'en' | 'zh', include?: string): Promise<Finding[]> {
  // Screen readers pick the voice from <html lang>, so a zh page marked en is
  // read with English pronunciation regardless of what axe finds.
  await expect(page.locator('html')).toHaveAttribute('lang', locale);
  await settle(page);
  let builder = new AxeBuilder({ page }).exclude('nextjs-portal');
  if (include) builder = builder.include(include);
  const { violations } = await builder.analyze();
  return violations.flatMap(v => v.nodes.map(node => {
    const contrast = v.id === 'color-contrast'
      ? node.any.find(check => check.id === 'color-contrast')?.data as { fgColor?: string; contrastRatio?: number } | undefined
      : undefined;
    return {
      step, rule: v.id, impact: node.impact ?? v.impact ?? 'unknown', help: v.help,
      target: node.target.map(String).join(' '), html: node.html.slice(0, 200),
      ...(contrast ? { fg: contrast.fgColor, ratio: contrast.contrastRatio } : {}),
    };
  }));
}

for (const locale of ['en', 'zh'] as const) {
  test(`390 px ${locale}: home, results, detail, cold-email editor and tracker`, async ({ page, context }, info) => {
    test.slow();
    const t = locale === 'zh' ? zh : en;
    const refused: string[] = [];
    await hermetic(context);
    await stubColdEmail(page, refused);
    await context.addCookies([{ name: STORAGE_KEYS.LOCALE, value: locale, url: ORIGIN }]);
    await page.addInitScript(({ key, value }) => localStorage.setItem(key, value), { key: STORAGE_KEYS.LOCALE, value: locale });
    const findings: Finding[] = [];

    await page.goto('/');
    const generate = page.getByRole('button', { name: t.home.actions.generate });
    await expect(generate).toBeVisible();
    // Named by the card heading it sits under, so the spoken name is the visible one.
    await expect(page.getByRole('slider', { name: t.home.cards.searchFocusTitle, exact: true })).toBeVisible();
    // The saved profile has loaded and the lazily imported résumé upload is in.
    await expect(page.getByTestId('hydration-note')).toHaveCount(0);
    await expect(page.locator('#resume-upload')).toBeAttached();
    findings.push(...await scan(page, 'home', locale));

    // Synthetic student; the name keeps the editor out of its name-required state.
    await page.locator('#student_name').fill('Alex Chen');
    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });
    await page.locator('#research_interests').fill('machine learning');
    await generate.click();
    await page.waitForURL('**/results*', { timeout: 30_000 });
    await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 60_000 });
    await expect(page.locator('main [aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
    findings.push(...await scan(page, 'results', locale));

    await page.goto(`/opportunities/${KNOWN_ID}`);
    const applied = page.getByRole('button', { name: t.detail.interactions.applied, exact: true });
    await expect(applied).toBeVisible();
    findings.push(...await scan(page, 'detail', locale));

    await page.getByRole('button', { name: t.detail.draftEmail, exact: true }).click();
    await expect(page.getByTestId('cold-email-footer')).toBeVisible({ timeout: 20_000 });
    // The automatic AI draft has been tried and refused, so the scan sees the
    // editor in the state it keeps, not mid-request. This wait assumes the
    // editor starts that draft by itself; if the draft becomes opt-in, the
    // wait has to change with it.
    await expect.poll(() => refused, { message: 'the editor\'s AI draft request was answered here' })
      .toContain('/api/cold-email/stream');
    // aria-modal hides the page behind it, so only the dialog is the editor.
    findings.push(...await scan(page, 'cold-email-editor', locale, '[role="dialog"][aria-modal="true"]'));
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('cold-email-footer')).toBeHidden();

    // The detail controls render before hydration; retry until the click lands.
    await expect(async () => {
      if (await applied.getAttribute('aria-pressed') !== 'true') await applied.click();
      await expect(applied).toHaveAttribute('aria-pressed', 'true', { timeout: 1_000 });
    }).toPass({ timeout: 15_000 });
    await page.goto('/tracker');
    await expect(page.getByRole('heading', { level: 1, name: t.tracker.title })).toBeVisible();
    await expect(page.locator(`[data-tracker-column="applied"] [data-tracker-card-id="${KNOWN_ID}"]`)).toBeVisible();
    findings.push(...await scan(page, 'tracker', locale));

    await info.attach(`axe-${locale}.json`, { body: JSON.stringify(findings, null, 2), contentType: 'application/json' });
    const seen = new Set<Known>();
    const blocking: string[] = [];
    for (const finding of findings) {
      const known = knownFor(finding);
      if (known) { seen.add(known); continue; }
      const line = `${finding.step}: ${finding.rule} (${finding.impact}) ${finding.target}`
        + `${finding.fg ? ` fg ${finding.fg} ${finding.ratio}:1` : ''} - ${finding.help}`;
      if (BLOCKING.has(finding.impact)) blocking.push(line);
      else info.annotations.push({ type: 'a11y below threshold', description: line });
    }
    const stale: string[] = [];
    for (const known of BASELINE) {
      if (seen.has(known)) continue;
      if (known.mayBeAbsent) info.annotations.push({ type: 'a11y baseline not seen', description: `${known.rule} ${known.fg ?? ''}: ${known.mayBeAbsent}` });
      else stale.push(`${known.rule}${known.fg ? ` ${known.fg}` : ''}${known.target ? ` ${known.target}` : ''}: ${known.name}`);
    }
    expect.soft(blocking, 'serious or critical axe violations not named in BASELINE').toEqual([]);
    expect(stale, 'BASELINE entries this run did not see; delete each one whose fix landed').toEqual([]);
  });
}
