import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';

import { ResultsSchoolFreshness, SchoolFreshnessNote } from './SchoolFreshnessNote';
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
    barnard: { last_checked_at: '2026-08-29T12:00:00+00:00', status: 'stale' },
    yale: { last_checked_at: '2026-10-17T12:00:00+00:00', status: 'current' },
    princeton: { last_checked_at: '2026-10-16T12:00:00+00:00', status: 'partly_unchecked' },
    mit: { last_checked_at: null, status: 'stale' },
    caltech: { last_checked_at: '2026-09-01T12:00:00+00:00', status: 'stale' },
    stanford: { last_checked_at: '2026-09-02T12:00:00+00:00', status: 'stale' },
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

  it('says when the school was last checked and that part of it was not', async () => {
    answer(BODY);
    const note = renderNote('uiuc');
    await waitFor(() => expect(note).toHaveTextContent('Last checked: Oct 12, 2026'));
    expect(note).toHaveTextContent("Some pages couldn't be read in recent checks.");
  });

  it('shows a school the runner is refused by with its real date and the stale hint', async () => {
    answer(BODY);
    const note = renderNote('swarthmore');
    await waitFor(() => expect(note).toHaveTextContent('Last checked: Sep 5, 2026'));
    const hint = screen.getByText('Professor pages failed recent checks.');
    expect(hint).toHaveClass('text-amber-700');
  });

  it('adds no hint to a current school', async () => {
    answer(BODY);
    const note = renderNote('yale');
    await waitFor(() => expect(note).toHaveTextContent('Last checked: Oct 17, 2026'));
    expect(note.querySelectorAll('p')).toHaveLength(1);
  });

  it('never invents a date for a school with no successful check', async () => {
    answer(BODY);
    const note = renderNote('mit');
    await waitFor(() => expect(note).toHaveTextContent('No successful check on record'));
    expect(note).not.toHaveTextContent('Last checked');
    expect(note).toHaveTextContent('Professor pages failed recent checks.');
  });

  it('reads in Chinese with a Chinese date', async () => {
    answer(BODY);
    const partly = renderNote('uiuc', 'zh');
    await waitFor(() => expect(partly).toHaveTextContent('最近成功检查：2026年10月12日'));
    expect(partly).toHaveTextContent('部分页面在最近的检查中未能读取。');
  });

  it('reads the stale hint in Chinese', async () => {
    answer(BODY);
    const stale = renderNote('barnard', 'zh');
    await waitFor(() => expect(stale).toHaveTextContent('最近成功检查：2026年8月29日'));
    expect(stale).toHaveTextContent('教授页面在最近的检查中未能读取。');
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
    await waitFor(() => expect(note).toHaveTextContent('Last checked: Oct 12, 2026'));
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
      "UIUC: last checked Oct 12, 2026. Some pages couldn't be read in recent checks.");
  });

  it('reads in Chinese', () => {
    renderResults({ shownSchools: ['uiuc', 'barnard'] }, 'zh');
    const block = screen.getByTestId('results-school-freshness');
    expect(block).toHaveTextContent('UIUC：最近成功检查 2026年10月12日。 部分页面在最近的检查中未能读取。');
    expect(block).toHaveTextContent('结果中还有 Barnard：最近的检查未能读取它的教授页面，数据可能已过时。');
  });

  it('names the stale schools among the results, and only those', () => {
    renderResults({ shownSchools: ['uiuc', 'barnard', 'yale', 'princeton', 'swarthmore', 'ucd'] });
    const block = screen.getByTestId('results-school-freshness');
    expect(block).toHaveTextContent(
      'Also in these results: Barnard and Swarthmore. Recent checks of their professor pages failed, '
      + 'so their data may be out of date.');
    expect(block).not.toHaveTextContent('Yale');
    expect(block).not.toHaveTextContent('Princeton');
  });

  it('uses the singular for one school and shortens a long list', () => {
    const { unmount } = renderResults({ shownSchools: ['swarthmore'] });
    expect(screen.getByTestId('results-school-freshness')).toHaveTextContent(
      'Also in these results: Swarthmore. Recent checks of its professor pages failed, so its data may be out of date.');
    unmount();
    renderResults({ shownSchools: ['swarthmore', 'barnard', 'mit', 'caltech', 'stanford'] });
    expect(screen.getByTestId('results-school-freshness')).toHaveTextContent(
      'Also in these results: Swarthmore, Barnard, MIT, and 2 more.');
  });

  it('gives a stale home school with no successful check no date', () => {
    renderResults({ homeSchool: 'mit', shownSchools: ['mit'] });
    expect(screen.getByTestId('results-school-freshness')).toHaveTextContent(
      'MIT: no successful check on record. Professor pages failed recent checks.');
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
