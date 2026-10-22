import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';

import { ResultsSchoolFreshness, SchoolFreshnessDot, SchoolFreshnessNote } from './SchoolFreshnessNote';
import { dictionaries } from '@/i18n/dictionaries';
import { translate } from '@/i18n/translate';
import {
  SCHOOL_FRESHNESS_SCHEMA,
  parseSchoolFreshness,
  resetSchoolFreshnessForTests,
  type SchoolFreshnessState,
} from '@/lib/school-freshness';

// Midday UTC, so the calendar day is the same in every time zone a test runner
// is likely to sit in; the time-zone rule itself is pinned in school-freshness.test.ts.
const BODY = {
  schema: SCHOOL_FRESHNESS_SCHEMA,
  schools: {
    uiuc: { last_checked_at: '2026-10-12T12:00:00+00:00', status: 'partly_unchecked' },
    swarthmore: { last_checked_at: '2026-09-05T12:00:00+00:00', status: 'stale' },
    // Dated by its newest success, on Aug 29, while both of its sources were
    // read again on Oct 17 and failed, the campus read with 9 records back: the
    // ledger committed at f9f8df7f, read on Oct 19 (tests/test_source_health.py,
    // test_a_school_is_dated_by_its_newest_success_not_by_later_reads_that_failed).
    barnard: { last_checked_at: '2026-08-29T12:00:00+00:00', status: 'stale' },
    yale: { last_checked_at: '2026-10-17T12:00:00+00:00', status: 'current' },
    princeton: { last_checked_at: '2026-10-16T12:00:00+00:00', status: 'partly_unchecked' },
    mit: { last_checked_at: null, status: 'stale' },
    caltech: { last_checked_at: '2026-09-01T12:00:00+00:00', status: 'stale' },
    stanford: { last_checked_at: '2026-09-02T12:00:00+00:00', status: 'stale' },
    // Stale by age alone: every source's latest attempt succeeded on Sep 20
    // and no run has come since, so nothing failed (tests/test_source_health.py,
    // test_a_school_turns_stale_by_age_alone_with_no_failed_attempt).
    cornell: { last_checked_at: '2026-09-20T12:00:00+00:00', status: 'stale' },
    // Partly unchecked by a source never read successfully, whose one attempt
    // on record is 40 days old (test_a_source_never_read_successfully_...).
    dartmouth: { last_checked_at: '2026-10-17T12:00:00+00:00', status: 'partly_unchecked' },
    // Stale while its campus page was read on Oct 5, the date shown: the
    // professor pages last succeeded on Aug 31 and the latest roster run was
    // deferred (test_a_campus_check_dates_a_school_stale_behind_a_deferred_roster_run).
    amherst: { last_checked_at: '2026-10-05T12:00:00+00:00', status: 'stale' },
    // Partly unchecked by a read that brought records back and still failed
    // (test_a_read_that_brought_records_back_and_failed_leaves_its_school_partly_unchecked).
    brown: { last_checked_at: '2026-10-15T12:00:00+00:00', status: 'partly_unchecked' },
  },
};
const READY: SchoolFreshnessState = { status: 'ready', schools: parseSchoolFreshness(BODY)! };

const tFor = (locale: 'en' | 'zh') =>
  (key: string, vars?: Record<string, string | number>) => translate(locale, key, vars);

function answer(body: unknown, ok = true) {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok, json: async () => body }) as unknown as Response));
}

beforeEach(() => resetSchoolFreshnessForTests());
afterEach(() => vi.unstubAllGlobals());

describe('SchoolFreshnessNote — under the school picker', () => {
  function renderNote(slug: string, locale: 'en' | 'zh' = 'en') {
    render(<SchoolFreshnessNote slug={slug} t={tFor(locale)} locale={locale} />);
    return screen.getByTestId('school-freshness');
  }

  it('says when the school was last checked successfully and that part of it was not', async () => {
    answer(BODY);
    const note = renderNote('uiuc');
    await waitFor(() => expect(note).toHaveTextContent('Last successful check: Oct 12, 2026'));
    expect(note).toHaveTextContent('Some pages lack a recent successful read.');
  });

  it('shows a school the runner is refused by with its real date and the stale hint', async () => {
    answer(BODY);
    const note = renderNote('swarthmore');
    await waitFor(() => expect(note).toHaveTextContent('Last successful check: Sep 5, 2026'));
    const hint = screen.getByText('Professor pages: no recent successful read.');
    expect(hint).toHaveClass('text-amber-700');
  });

  it('says only what the ledger holds of a school stale by age alone: no recent successful read, nothing failed', async () => {
    answer(BODY);
    const note = renderNote('cornell');
    await waitFor(() => expect(note).toHaveTextContent('Last successful check: Sep 20, 2026'));
    expect(note).toHaveTextContent('Professor pages: no recent successful read.');
    expect(note).not.toHaveTextContent(/fail|couldn't|could not/i);
  });

  it('ties nothing about the professor pages to a date a campus page set', async () => {
    answer(BODY);
    const note = renderNote('amherst');
    await waitFor(() => expect(note).toHaveTextContent('Last successful check: Oct 5, 2026'));
    expect(note).toHaveTextContent('Professor pages: no recent successful read.');
    expect(note).not.toHaveTextContent(/since/i);
  });

  it('claims no failed check for a school partly unchecked by a source never read', async () => {
    answer(BODY);
    const note = renderNote('dartmouth');
    await waitFor(() => expect(note).toHaveTextContent('Last successful check: Oct 17, 2026'));
    expect(note).toHaveTextContent('Some pages lack a recent successful read.');
    expect(note).not.toHaveTextContent(/fail|couldn't|could not/i);
  });

  it('does not say pages went unread when a read brought records back and still failed', async () => {
    answer(BODY);
    const note = renderNote('brown');
    await waitFor(() => expect(note).toHaveTextContent('Last successful check: Oct 15, 2026'));
    expect(note).toHaveTextContent('Some pages lack a recent successful read.');
    expect(note).not.toHaveTextContent(/(haven't|not) been read(?! successfully)|unread/i);
  });

  it('dates a school by its newest successful check, not as last checked then: later reads failed', async () => {
    answer(BODY);
    const note = renderNote('barnard');
    await waitFor(() => expect(note).toHaveTextContent('Last successful check: Aug 29, 2026'));
    expect(note.textContent).toBe(
      'Last successful check: Aug 29, 2026Professor pages: no recent successful read.');
    expect(note).not.toHaveTextContent(/last checked/i);
  });

  it('adds no hint to a current school', async () => {
    answer(BODY);
    const note = renderNote('yale');
    await waitFor(() => expect(note).toHaveTextContent('Last successful check: Oct 17, 2026'));
    expect(note.querySelectorAll('p')).toHaveLength(1);
  });

  it('never invents a date for a school with no successful check', async () => {
    answer(BODY);
    const note = renderNote('mit');
    await waitFor(() => expect(note).toHaveTextContent('No successful check on record'));
    expect(note).not.toHaveTextContent(/last (successful )?check/i);
    // Its first line already says no check succeeded; the hint says what that means.
    expect(note).toHaveTextContent('Details may be out of date.');
  });

  it('reads in Chinese with a Chinese date', async () => {
    answer(BODY);
    const partly = renderNote('uiuc', 'zh');
    await waitFor(() => expect(partly).toHaveTextContent('最近成功检查：2026年10月12日'));
    expect(partly).toHaveTextContent('这所学校有些页面最近没有成功读取。');
  });

  it('dates a school by its newest successful check in Chinese too, with the stale hint', async () => {
    answer(BODY);
    const stale = renderNote('barnard', 'zh');
    await waitFor(() => expect(stale).toHaveTextContent('最近成功检查：2026年8月29日'));
    expect(stale.textContent).toBe('最近成功检查：2026年8月29日教授页面最近没有成功读取。');
  });

  it('ties nothing about the professor pages to a date a campus page set, in Chinese', async () => {
    answer(BODY);
    const stale = renderNote('amherst', 'zh');
    await waitFor(() => expect(stale).toHaveTextContent('最近成功检查：2026年10月5日'));
    expect(stale).toHaveTextContent('教授页面最近没有成功读取。');
    expect(stale).not.toHaveTextContent('此后');
  });

  it('reads a school stale by age alone in Chinese without claiming a failure', async () => {
    answer(BODY);
    const stale = renderNote('cornell', 'zh');
    await waitFor(() => expect(stale).toHaveTextContent('最近成功检查：2026年9月20日'));
    expect(stale).toHaveTextContent('教授页面最近没有成功读取。');
    expect(stale).not.toHaveTextContent(/未能|失败/);
  });

  it('holds its two lines while loading, and fills them in place', async () => {
    let release!: () => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => {
      release = () => resolve({ ok: true, json: async () => BODY } as unknown as Response);
    })));
    const note = renderNote('uiuc');
    expect(note).toBeEmptyDOMElement();
    expect(note).toHaveClass('min-h-[2rem]', 'leading-4');
    await act(async () => { release(); });
    await waitFor(() => expect(note).toHaveTextContent('Last successful check: Oct 12, 2026'));
    expect(screen.getByTestId('school-freshness')).toBe(note);
    expect(note.querySelectorAll('p')).toHaveLength(2);
  });

  it.each([
    ['the read fails', () => answer(BODY, false)],
    ['the body is an older schema', () => answer({ schools: BODY.schools })],
    ['the school is not monitored', () => answer({ ...BODY, schools: {} })],
  ])('shows nothing when %s', async (_label, setUp) => {
    setUp();
    const fetchMock = vi.mocked(fetch);
    const note = renderNote('uiuc');
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await act(async () => {});
    expect(note).toBeEmptyDOMElement();
    expect(note).toHaveClass('min-h-[2rem]');
  });
});

describe('the hint wording', () => {
  const HINTS = ['partlyUnchecked', 'stale', 'staleNeverChecked', 'resultsOtherStale', 'resultsOtherStaleOne'] as const;

  it.each(HINTS)('%s claims no failed check in either language: a status can come from age alone', (key) => {
    expect(dictionaries.en.schoolFreshness[key]).not.toMatch(/fail|couldn't|could not|error/i);
    expect(dictionaries.zh.schoolFreshness[key]).not.toMatch(/未能|失败|错误/);
  });

  it.each(HINTS)('%s is not tied to the date before it: a campus page can set that date', (key) => {
    expect(dictionaries.en.schoolFreshness[key]).not.toMatch(/\bsince\b/i);
    expect(dictionaries.zh.schoolFreshness[key]).not.toMatch(/此后/);
  });

  it.each(['partlyUnchecked', 'stale', 'resultsOtherStale', 'resultsOtherStaleOne'] as const)(
    '%s says no recent read succeeded, not that pages went unread: a read can bring records back and still fail',
    (key) => {
      expect(dictionaries.en.schoolFreshness[key]).toMatch(/\bsuccessful(ly)?\b/);
      expect(dictionaries.zh.schoolFreshness[key]).toMatch(/成功读取/);
    },
  );

  it.each(['lastChecked', 'resultsLastChecked'] as const)(
    '%s dates the newest successful check, not the latest check: later reads can fail',
    (key) => {
      expect(dictionaries.en.schoolFreshness[key]).toMatch(/\bsuccessful check\b/i);
      expect(dictionaries.zh.schoolFreshness[key]).toMatch(/成功检查/);
    },
  );

  it('no line in either language says when a school was last checked, only when a check last succeeded', () => {
    for (const text of Object.values(dictionaries.en.schoolFreshness)) {
      expect(text).not.toMatch(/\bchecked\b/i);
    }
    for (const text of Object.values(dictionaries.zh.schoolFreshness)) {
      expect(text).not.toMatch(/(?<!成功)检查/);
    }
  });
});

describe('SchoolFreshnessDot — beside the school name', () => {
  it.each([
    ['swarthmore', 'bg-amber-500'],
    ['uiuc', 'bg-gray-400'],
    ['yale', 'bg-emerald-500'],
  ])('is not left green when the hint qualifies the school (%s)', async (slug, colour) => {
    answer(BODY);
    render(<SchoolFreshnessDot slug={slug} />);
    const dot = screen.getByTestId('school-freshness-dot');
    await waitFor(() => expect(dot).toHaveClass(colour));
    expect(dot.className.match(/\bbg-\S+/g)).toEqual([colour]);
  });

  it('stays green, as before the school had a date, while loading or after a failed read', async () => {
    answer(BODY, false);
    render(<SchoolFreshnessDot slug="swarthmore" />);
    const dot = screen.getByTestId('school-freshness-dot');
    expect(dot).toHaveClass('bg-emerald-500');
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    await act(async () => {});
    expect(dot).toHaveClass('bg-emerald-500');
  });
});

describe('ResultsSchoolFreshness — on the results page', () => {
  function renderResults(
    props: Partial<Parameters<typeof ResultsSchoolFreshness>[0]> = {},
    locale: 'en' | 'zh' = 'en',
  ) {
    return render(
      <ResultsSchoolFreshness freshness={READY} homeSchool="uiuc" shownSchools={[]}
        t={tFor(locale)} locale={locale} {...props} />,
    );
  }

  it('gives the home school its date and hint in one line', () => {
    renderResults({ shownSchools: ['uiuc'] });
    expect(screen.getByTestId('results-school-freshness')).toHaveTextContent(
      'UIUC: last successful check Oct 12, 2026. Some pages lack a recent successful read.');
  });

  it.each([
    ['amherst', 'Amherst: last successful check Oct 5, 2026. Professor pages: no recent successful read.',
      'Amherst：最近成功检查 2026年10月5日。教授页面最近没有成功读取。'],
    ['brown', 'Brown: last successful check Oct 15, 2026. Some pages lack a recent successful read.',
      'Brown：最近成功检查 2026年10月15日。这所学校有些页面最近没有成功读取。'],
    // Read again on Oct 17 and failed: Aug 29 is its last successful check, not its last check.
    ['barnard', 'Barnard: last successful check Aug 29, 2026. Professor pages: no recent successful read.',
      'Barnard：最近成功检查 2026年8月29日。教授页面最近没有成功读取。'],
  ])('makes the same claims for the home school %s as the picker does', (school, en, zh) => {
    const { unmount } = renderResults({ homeSchool: school, shownSchools: [school] });
    expect(screen.getByTestId('results-school-freshness').textContent).toBe(en);
    unmount();
    renderResults({ homeSchool: school, shownSchools: [school] }, 'zh');
    expect(screen.getByTestId('results-school-freshness').textContent).toBe(zh);
  });

  it('reads in Chinese, with no space after the full-width 。', () => {
    renderResults({ shownSchools: ['uiuc', 'barnard'] }, 'zh');
    const [home, others] = screen.getByTestId('results-school-freshness').querySelectorAll('p');
    expect(home.textContent).toBe('UIUC：最近成功检查 2026年10月12日。这所学校有些页面最近没有成功读取。');
    expect(others.textContent).toBe('结果中还有 Barnard：它的教授页面最近没有成功读取，数据可能已过时。');
  });

  it('lists several schools in Chinese with 、, not run into 和', () => {
    const { unmount } = renderResults({ shownSchools: ['uiuc', 'barnard', 'swarthmore'] }, 'zh');
    expect(screen.getByTestId('results-school-freshness').querySelectorAll('p')[1].textContent).toBe(
      '结果中还有 Barnard、Swarthmore：它们的教授页面最近没有成功读取，数据可能已过时。');
    unmount();
    renderResults({ shownSchools: ['swarthmore', 'barnard', 'mit', 'caltech', 'stanford'] }, 'zh');
    expect(screen.getByTestId('results-school-freshness')).toHaveTextContent(
      '结果中还有 Swarthmore、Barnard、MIT 和另外 2 所：');
  });

  it('gives a stale home school its date and the stale hint, in Chinese', () => {
    renderResults({ homeSchool: 'swarthmore', shownSchools: ['swarthmore'] }, 'zh');
    expect(screen.getByTestId('results-school-freshness').textContent).toBe(
      'Swarthmore：最近成功检查 2026年9月5日。教授页面最近没有成功读取。');
  });

  it('names the stale schools among the results, and only those', () => {
    renderResults({ shownSchools: ['uiuc', 'barnard', 'yale', 'princeton', 'swarthmore', 'ucd'] });
    const block = screen.getByTestId('results-school-freshness');
    expect(block).toHaveTextContent(
      "Also in these results: Barnard and Swarthmore. Their professor pages haven't been read successfully "
      + 'recently, so their data may be out of date.');
    expect(block).not.toHaveTextContent('Yale');
    expect(block).not.toHaveTextContent('Princeton');
  });

  it('uses the singular for one school and shortens a long list', () => {
    const { unmount } = renderResults({ shownSchools: ['swarthmore'] });
    expect(screen.getByTestId('results-school-freshness')).toHaveTextContent(
      "Also in these results: Swarthmore. Its professor pages haven't been read successfully recently, "
      + 'so its data may be out of date.');
    unmount();
    renderResults({ shownSchools: ['swarthmore', 'barnard', 'mit', 'caltech', 'stanford'] });
    expect(screen.getByTestId('results-school-freshness')).toHaveTextContent(
      'Also in these results: Swarthmore, Barnard, MIT, and 2 more.');
  });

  it('gives a stale home school with no successful check no date', () => {
    renderResults({ homeSchool: 'mit', shownSchools: ['mit'] });
    expect(screen.getByTestId('results-school-freshness')).toHaveTextContent(
      'MIT: no successful check on record. Details may be out of date.');
  });

  it('names a school stale by age alone without claiming a failure', () => {
    renderResults({ shownSchools: ['uiuc', 'cornell'] });
    const block = screen.getByTestId('results-school-freshness');
    expect(block).toHaveTextContent(
      "Also in these results: Cornell. Its professor pages haven't been read successfully recently");
    expect(block).not.toHaveTextContent(/fail|couldn't|could not/i);
  });

  it('renders nothing for an unmonitored home school with no stale school shown', () => {
    renderResults({ homeSchool: 'ucd', shownSchools: ['ucd', 'yale'] });
    expect(screen.queryByTestId('results-school-freshness')).toBeNull();
  });

  it('renders nothing while loading or after a failed read', () => {
    const { rerender } = renderResults({ freshness: { status: 'loading' } });
    expect(screen.queryByTestId('results-school-freshness')).toBeNull();
    rerender(<ResultsSchoolFreshness freshness={{ status: 'failed' }} homeSchool="uiuc"
      shownSchools={[]} t={tFor('en')} locale="en" />);
    expect(screen.queryByTestId('results-school-freshness')).toBeNull();
  });

  it('does not push painted results down: a late answer waits for the next page of results', () => {
    const page1 = ['uiuc', 'barnard'];
    const { rerender } = renderResults({ freshness: { status: 'loading' }, shownSchools: page1 });
    rerender(<ResultsSchoolFreshness freshness={READY} homeSchool="uiuc"
      shownSchools={page1} t={tFor('en')} locale="en" />);
    expect(screen.queryByTestId('results-school-freshness')).toBeNull();
    const page2 = ['uiuc', 'barnard'];
    rerender(<ResultsSchoolFreshness freshness={READY} homeSchool="uiuc"
      shownSchools={page2} t={tFor('en')} locale="en" />);
    expect(screen.getByTestId('results-school-freshness')).toHaveTextContent('Barnard');
  });
});
